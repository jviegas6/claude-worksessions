"""claude-inbox: the scan's answer becomes flagged request folders; the hourly run is scheduled."""

import json
import os
import subprocess

import pytest

from conftest import load_script


@pytest.fixture
def inbox(home, monkeypatch, tmp_path):
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    mod = load_script("claude-inbox")
    os.makedirs(mod.DATA_DIR, exist_ok=True)
    return mod


def item(**kw):
    base = {"who": "Ana Silva", "subject": "firewall rule", "what": "confirm the new IP", "where": "teams",
            "link": "https://teams.microsoft.com/l/message/1", "message_id": "m1",
            "received": "2026-10-12T08:00:00Z", "ticket": ""}
    base.update(kw)
    return base


def cfg(home, **kw):
    c = {"root": str(home / "work_sessions"), "profile": "personal", "hours": 3.0, "task_type": "support",
         "model": "sonnet", "timeout": 600.0}
    c.update(kw)
    return c


def test_settings_from_config_env_and_environment(inbox, home, monkeypatch):
    conf = inbox.read_config()
    assert conf["CWS_WORK_ROOT"] == str(home / "work_sessions") and conf["CWS_PROFILES"] == "personal work"
    s = inbox.settings(conf)
    assert (s["root"], s["profile"], s["hours"], s["task_type"], s["model"]) == (
        str(home / "work_sessions"), "personal", 3.0, "support", "sonnet")
    monkeypatch.setenv("CWS_INBOX_PROFILE", "work")
    monkeypatch.setenv("CWS_INBOX_HOURS", "24")
    s = inbox.settings(inbox.read_config())
    assert (s["profile"], s["hours"]) == ("work", 24.0)
    assert inbox.settings({})["profile"] == "personal"
    assert inbox.settings({"CWS_PROFILES": "ops work"})["profile"] == "ops"
    assert "CWS_WORK_ROOT" not in inbox.read_config("/nonexistent/config.env")


def test_scan_runs_claude_headless_with_the_connector_only(inbox, home, monkeypatch):
    (home / ".claude-personal").mkdir()
    calls = []

    def run(cmd, **kw):
        calls.append((cmd, kw))
        out = {"structured_output": {"items": [item(), item(message_id="m2", where="MAIL", ticket="btpa-7"),
                                               {"who": "", "subject": ""}, "junk"]}}
        return subprocess.CompletedProcess(cmd, 0, json.dumps(out), "")
    monkeypatch.setattr(inbox.subprocess, "run", run)
    items, err = inbox.scan(cfg(home), 3)
    assert err is None and [i["message_id"] for i in items] == ["m1", "m2"]
    assert items[1]["where"] == "mail" and items[1]["ticket"] == "BTPA-7"
    cmd, kw = calls[0]
    assert cmd[:2] == ["claude", "-p"] and "--no-session-persistence" in cmd and "--strict-mcp-config" not in cmd
    assert cmd[cmd.index("--tools") + 1] == "" and cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
    assert all(t.startswith("mcp__claude_ai_Microsoft_365__") for t in allowed) and "outlook_send_mail" not in "".join(allowed)
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == inbox.SCHEMA
    assert "last 3 hours" in cmd[-1] and "send nothing" in cmd[-1]
    assert kw["env"]["CLAUDE_CONFIG_DIR"] == str(home / ".claude-personal") and kw["cwd"] == inbox.DATA_DIR
    # a ticket in the subject counts when the model gave none
    monkeypatch.setattr(inbox.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, json.dumps({"structured_output": {"items": [item(subject="BTPA-12 access", ticket="")]}}), ""))
    assert inbox.scan(cfg(home), 2.5)[0][0]["ticket"] == "BTPA-12"


@pytest.mark.parametrize("stdout, stderr, exc, err", [
    ("{}", "", None, "no answer"),
    (json.dumps({"is_error": True, "result": "Not logged in"}), "", None, "Not logged in"),
    (json.dumps({"structured_output": {"items": "x"}}), "boom", None, "boom"),
    ("not json", "", None, "Expecting value"),
    ("", "", subprocess.TimeoutExpired("claude", 600), "timeout after 600s"),
    ("", "", OSError("no claude"), "no claude"),
])
def test_scan_errors(inbox, home, monkeypatch, stdout, stderr, exc, err):
    (home / ".claude-personal").mkdir()

    def run(cmd, **kw):
        if exc:
            raise exc
        return subprocess.CompletedProcess(cmd, 0, stdout, stderr)
    monkeypatch.setattr(inbox.subprocess, "run", run)
    items, e = inbox.scan(cfg(home), 3)
    assert items == [] and err in e


def test_scan_needs_the_profile_dir(inbox, home):
    assert inbox.scan(cfg(home, profile="nope"), 3) == ([], "profile dir {} not found".format(home / ".claude-nope"))


def make_request(root, day, name, meta):
    d = root / "2026" / "10" / day / ("10-00-00_" + name)
    d.mkdir(parents=True)
    (d / ".session.json").write_text(json.dumps(dict({"name": name}, **meta)))
    return d


def test_place_creates_flags_flips_and_remembers(inbox, home, monkeypatch, capsys):
    import datetime as dt
    root = home / "work_sessions"
    monkeypatch.setattr(inbox.dt, "datetime", type("D", (dt.datetime,), {
        "now": classmethod(lambda cls, tz=None: cls(2026, 10, 12, 14, 30, 0, tzinfo=tz))}))
    ticketed = make_request(root, "10", "ticketed", {"ticket": "BTPA-7", "waiting": {
        "on": "other", "who": "Ana Silva", "what": "the IP", "since": "2026-10-10T09:00:00Z", "where": "teams", "link": ""}})
    old = root / "2026" / "01" / "05" / "10-00-00_old"
    old.mkdir(parents=True)
    (old / ".session.json").write_text(json.dumps({"name": "old", "ticket": "BTPA-8"}))
    items = [item(), item(message_id="m2", ticket="BTPA-7"), item(message_id="m3", ticket="BTPA-8", who="Bo")]
    c = cfg(home)
    lines = inbox.place(items, c, dry_run=True)
    assert lines == ["would create Ana Silva · firewall rule -> a new folder",
                     "would flag   Ana Silva · firewall rule · BTPA-7 -> 2026/10/10/10-00-00_ticketed",
                     "would create Bo · firewall rule · BTPA-8 -> a new folder"]   # BTPA-8's folder is too old
    assert not os.path.exists(os.path.join(inbox.DATA_DIR, "seen.json"))
    lines = inbox.place(items, c)
    assert lines[0] == "created  Ana Silva · firewall rule -> 2026/10/12/14-30-00_reply-ana-silva-firewall-rule"
    assert lines[1] == "flipped  Ana Silva · firewall rule · BTPA-7 -> 2026/10/10/10-00-00_ticketed"
    assert lines[2] == "created  Bo · firewall rule · BTPA-8 -> 2026/10/12/14-30-00_reply-bo-firewall-rule"
    new = json.loads((root / "2026/10/12/14-30-00_reply-ana-silva-firewall-rule/.session.json").read_text())
    assert new["name"] == "Reply to Ana Silva: firewall rule" and new["ticket"] == "Other" and new["task_type"] == "support"
    assert new["profile"] == "personal" and new["source"] == "claude-inbox" and new["audit"] is True
    assert new["waiting"] == {"on": "me", "who": "Ana Silva", "what": "confirm the new IP",
                              "since": "2026-10-12T08:00:00Z", "where": "teams", "link": "https://teams.microsoft.com/l/message/1"}
    assert new["started_at"] == "2026-10-12T14:30:00Z" and new["goal"] == "reply to Ana Silva about firewall rule"
    flipped = json.loads((ticketed / ".session.json").read_text())
    assert flipped["waiting"]["on"] == "me" and flipped["waiting_history"][0]["on"] == "other"
    assert flipped["waiting_history"][0]["until"] == "2026-10-12T14:30:00Z"
    seen = json.load(open(os.path.join(inbox.DATA_DIR, "seen.json")))
    assert sorted(seen) == ["teams:m1", "teams:m2", "teams:m3"]
    # again: everything is seen; a new message on BTPA-7 keeps the flag that is already on me
    lines = inbox.place(items + [item(message_id="m4", ticket="BTPA-7")], c)
    assert lines[:3] == ["seen     Ana Silva · firewall rule", "seen     Ana Silva · firewall rule · BTPA-7",
                         "seen     Bo · firewall rule · BTPA-8"]
    assert lines[3] == "kept     Ana Silva · firewall rule · BTPA-7 -> 2026/10/10/10-00-00_ticketed"
    # a second message with no ticket on the same minute gets a -2 folder; one with no flag gets "set"
    make_request(root, "11", "plain", {"ticket": "BTPA-9"})
    lines = inbox.place([item(message_id="m5", who="Ana Silva"), item(message_id="", link="", ticket="BTPA-9")], c)
    assert lines[0].endswith("reply-ana-silva-firewall-rule-2")
    assert lines[1].startswith("set      ")
    assert "teams:Ana Silva|firewall rule" in json.load(open(os.path.join(inbox.DATA_DIR, "seen.json")))


def test_helpers(inbox, home):
    assert inbox.slugify("Reply: Ana / Silva!!") == "reply-ana-silva"
    assert inbox.slugify("") == "reply" and len(inbox.slugify("x" * 100)) == 60
    assert inbox.ticket_of("see btpa-12 and BTPA-13") == "BTPA-12" and inbox.ticket_of("nothing") == ""
    assert inbox.folder_for_ticket([], "Other") is None and inbox.folder_for_ticket([], "") is None
    assert inbox.load_json(str(home / "missing.json"), {}) == {}
    (home / "list.json").write_text("[1]")
    assert inbox.load_json(str(home / "list.json"), {}) == {}
    assert inbox.request_folders(str(home / "work_sessions")) == []
    d = home / "work_sessions" / "2026" / "10" / "12" / "10-00-00_bad"
    d.mkdir(parents=True)
    (d / ".session.json").write_text("nope")
    assert inbox.request_folders(str(home / "work_sessions")) == []


def test_install_launchd_and_cron(inbox, home, monkeypatch):
    calls = []

    def run(cmd, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "0 1 * * * other\n", "")
    msg = inbox.install("/x/claude-inbox", run=run, platform="darwin")
    p = inbox.plist_path()
    assert "runs every hour" in msg and os.path.exists(p)
    text = open(p).read()
    assert "<string>/x/claude-inbox</string>" in text and "<integer>3600</integer>" in text
    assert str(home / ".local" / "bin") in text and "inbox.log" in text
    assert calls[-1] == ["launchctl", "load", p]
    assert "hourly run installed" in inbox.status()
    msg = inbox.install("/x/claude-inbox", uninstall=True, run=run, platform="darwin")
    assert "removed" in msg and not os.path.exists(p)
    inbox.install("/x/claude-inbox", uninstall=True, run=run, platform="darwin")   # already gone: fine

    def failing(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1 if cmd[:2] == ["launchctl", "load"] else 0, "", "bad plist")
    assert "launchctl load failed: bad plist" in inbox.install("/x/claude-inbox", run=failing, platform="darwin")

    calls.clear()
    stdin = []

    def cron(cmd, **kw):
        calls.append(cmd)
        if cmd == ["crontab", "-"]:
            stdin.append(kw["input"])
        return subprocess.CompletedProcess(cmd, 0, "0 1 * * * other\n0 * * * * old  # com.claude-worksessions.inbox\n", "")
    assert "cron entry installed" in inbox.install("/x/claude-inbox", run=cron, platform="linux")
    assert stdin[-1] == "0 1 * * * other\n0 * * * * /x/claude-inbox >> {} 2>&1  # com.claude-worksessions.inbox\n".format(
        os.path.join(inbox.DATA_DIR, "inbox.log"))
    assert "cron entry removed" in inbox.install("/x/claude-inbox", uninstall=True, run=cron, platform="linux")
    assert stdin[-1] == "0 1 * * * other\n"

    def nocron(cmd, **kw):
        return subprocess.CompletedProcess(cmd, 1, "", "no crontab")
    inbox.install("/x/claude-inbox", run=nocron, platform="linux")


def test_main_scans_places_and_records_state(inbox, home, monkeypatch, capsys):
    (home / ".claude-personal").mkdir()
    monkeypatch.setattr(inbox, "scan", lambda cfg, hours: ([item()], None))
    assert inbox.main([]) == 0
    out = capsys.readouterr().out
    assert "1 item(s) need a reply in the last 3h, 1 new" in out and "created  Ana Silva" in out
    st = json.load(open(os.path.join(inbox.DATA_DIR, "state.json")))
    assert (st["found"], st["new"], st["error"], st["hours"]) == (1, 1, None, 3.0)
    assert inbox.main(["--status"]) == 0
    assert "last run" in capsys.readouterr().out and "1 item(s), 1 new" in inbox.status()
    assert inbox.main(["--dry-run", "--hours", "24"]) == 0
    assert "would" not in capsys.readouterr().out      # already seen
    monkeypatch.setattr(inbox, "scan", lambda cfg, hours: ([], "Not logged in"))
    assert inbox.main([]) == 1
    assert "scan failed: Not logged in" in capsys.readouterr().err
    assert json.load(open(os.path.join(inbox.DATA_DIR, "state.json")))["error"] == "Not logged in"
    assert inbox.main(["--dry-run"]) == 1
    assert "error: Not logged in" in inbox.status()
    os.remove(os.path.join(inbox.DATA_DIR, "state.json"))
    assert inbox.status().startswith("claude-inbox: never run; hourly run not installed")
    monkeypatch.setattr(inbox, "install", lambda exe, uninstall=False: "installed " + exe + str(uninstall))
    assert inbox.main(["--install"]) == 0 and "installed " in capsys.readouterr().out
    assert inbox.main(["--uninstall"]) == 0 and "True" in capsys.readouterr().out
