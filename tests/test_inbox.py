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
            "received": "2026-10-12T08:00:00Z", "ticket": "", "thread_id": "", "history": "",
            "message": "Hi Jose, is 10.0.0.5 the new IP?\nWe need it by Thursday."}
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
    items, answered, err = inbox.scan(cfg(home), 3)
    assert err is None and [i["message_id"] for i in items] == ["m1", "m2"] and answered == []
    assert items[1]["where"] == "mail" and items[1]["ticket"] == "BTPA-7"
    cmd, kw = calls[0]
    assert cmd[:2] == ["claude", "-p"] and "--no-session-persistence" in cmd and "--strict-mcp-config" not in cmd
    assert cmd[cmd.index("--tools") + 1] == "" and cmd[cmd.index("--permission-mode") + 1] == "dontAsk"
    allowed = cmd[cmd.index("--allowedTools") + 1].split(",")
    assert all(t.startswith("mcp__claude_ai_Microsoft_365__") for t in allowed) and "outlook_send_mail" not in "".join(allowed)
    assert json.loads(cmd[cmd.index("--json-schema") + 1]) == inbox.SCHEMA
    assert "last 3 hours" in cmd[-1] and "send nothing" in cmd[-1] and "thread id" in cmd[-1] and "my own message is the latest" in cmd[-1]
    assert items[0]["message"] == "Hi Jose, is 10.0.0.5 the new IP?\nWe need it by Thursday." and items[0]["history"] == ""
    assert kw["env"]["CLAUDE_CONFIG_DIR"] == str(home / ".claude-personal") and kw["cwd"] == inbox.DATA_DIR
    # a ticket in the subject counts when the model gave none
    monkeypatch.setattr(inbox.subprocess, "run", lambda cmd, **kw: subprocess.CompletedProcess(
        cmd, 0, json.dumps({"structured_output": {"items": [item(subject="BTPA-12 access", ticket="", thread_id=" 19:abc@unq.gbl.spaces ",
                                                                    history="  Ana asked.\n\n  I  said no.\n", message="x" * 3000)],
                                                   "answered": [{"who": "Bo", "subject": "quote", "where": "Teams", "link": "https://t/9",
                                                                 "thread_id": "19:q@thread.v2", "replied": "2026-10-12T09:00:00Z",
                                                                 "summary": "sent  the quote", "what": "", "ticket": "see BTPA-3"}, {"who": ""}, 3]}}), ""))
    items, answered, _ = inbox.scan(cfg(home), 2.5)
    it = items[0]
    assert it["ticket"] == "BTPA-12" and it["thread_id"] == "19:abc@unq.gbl.spaces"
    assert it["history"] == "Ana asked.\nI said no." and len(it["message"]) == 2000
    assert answered == [{"who": "Bo", "subject": "quote", "where": "teams", "link": "https://t/9", "thread_id": "19:q@thread.v2",
                         "replied": "2026-10-12T09:00:00Z", "summary": "sent the quote", "what": "", "ticket": "BTPA-3"}]


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
    items, answered, e = inbox.scan(cfg(home), 3)
    assert items == [] and answered == [] and err in e


def test_scan_needs_the_profile_dir(inbox, home):
    assert inbox.scan(cfg(home, profile="nope"), 3) == ([], [], "profile dir {} not found".format(home / ".claude-nope"))


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
    items = [item(thread_id="19:aaa@unq.gbl.spaces"), item(message_id="m2", ticket="BTPA-7", subject="the IP"),
             item(message_id="m3", ticket="BTPA-8", who="Bo")]
    c = cfg(home)
    lines = inbox.place(items, c, dry_run=True)
    assert lines == ["would create Ana Silva · firewall rule -> a new folder",
                     "would flag   Ana Silva · the IP · BTPA-7 -> 2026/10/10/10-00-00_ticketed",
                     "would create Bo · firewall rule · BTPA-8 -> a new folder"]   # BTPA-8's folder is too old
    assert not os.path.exists(os.path.join(inbox.DATA_DIR, "seen.json"))
    lines = inbox.place(items, c)
    assert lines[0] == "created  Ana Silva · firewall rule -> 2026/10/12/14-30-00_reply-ana-silva-firewall-rule"
    assert lines[1] == "flipped  Ana Silva · the IP · BTPA-7 -> 2026/10/10/10-00-00_ticketed"
    assert lines[2] == "created  Bo · firewall rule · BTPA-8 -> 2026/10/12/14-30-00_reply-bo-firewall-rule"
    created = root / "2026/10/12/14-30-00_reply-ana-silva-firewall-rule"
    new = json.loads((created / ".session.json").read_text())
    assert new["name"] == "Reply to Ana Silva: firewall rule" and new["ticket"] == "Other" and new["task_type"] == "support"
    assert new["profile"] == "personal" and new["source"] == "claude-inbox" and new["audit"] is True
    assert new["waiting"] == {"on": "me", "who": "Ana Silva", "what": "confirm the new IP",
                              "since": "2026-10-12T08:00:00Z", "where": "teams", "link": "https://teams.microsoft.com/l/message/1"}
    assert new["started_at"] == "2026-10-12T14:30:00Z" and new["goal"] == "reply to Ana Silva about firewall rule"
    assert (new["thread"], new["thread_who"], new["thread_subject"]) == ("19:aaa@unq.gbl.spaces", "Ana Silva", "firewall rule")
    # the message is in thread.md: when and who, the text quoted, what it needs, the link
    assert (created / "thread.md").read_text() == (
        "# Reply to Ana Silva: firewall rule\n\n"
        "Who said what, in order. claude-inbox adds the messages it finds; claude-wait --note adds yours.\n\n"
        "## 2026-10-12 08:00 · Ana Silva (teams) · waiting on me\n\n"
        "Ana Silva wrote:\n\n> Hi Jose, is 10.0.0.5 the new IP?\n> We need it by Thursday.\n\n"
        "Needs: confirm the new IP\nLink: https://teams.microsoft.com/l/message/1\n\n")
    flipped = json.loads((ticketed / ".session.json").read_text())
    assert flipped["waiting"]["on"] == "me" and flipped["waiting_history"][0]["on"] == "other"
    assert flipped["waiting_history"][0]["until"] == "2026-10-12T14:30:00Z"
    assert "## 2026-10-12 08:00 · Ana Silva (teams) · waiting on me" in (ticketed / "thread.md").read_text()
    assert (ticketed / "thread.md").read_text().startswith("# ticketed\n")
    seen = json.load(open(os.path.join(inbox.DATA_DIR, "seen.json")))
    assert sorted(seen) == ["teams:m1", "teams:m2", "teams:m3"]
    # again: everything is seen; a new message on BTPA-7 keeps the flag that is already on me,
    # pointed at the newer message, and lands in thread.md under the earlier one
    lines = inbox.place(items + [item(message_id="m4", ticket="BTPA-7", subject="the IP", what="the new IP, please", link="https://t/4",
                                      history="I asked for the IP.\nAna said Thursday.", received="2026-10-12T10:00:00Z")], c)
    assert lines[:3] == ["seen     Ana Silva · firewall rule", "seen     Ana Silva · the IP · BTPA-7",
                         "seen     Bo · firewall rule · BTPA-8"]
    assert lines[3] == "kept     Ana Silva · the IP · BTPA-7 -> 2026/10/10/10-00-00_ticketed"
    kept = json.loads((ticketed / ".session.json").read_text())["waiting"]
    assert (kept["what"], kept["link"], kept["since"]) == ("the new IP, please", "https://t/4", "2026-10-12T08:00:00Z")
    t = (ticketed / "thread.md").read_text()
    assert t.index("## 2026-10-12 08:00") < t.index("## 2026-10-12 10:00 · Ana Silva (teams) · waiting on me\n\nBefore this:\n\n> I asked for the IP.\n> Ana said Thursday.\n\nAna Silva wrote:")
    assert t.count("## ") == 2
    # a follow-up on a thread already placed goes to its folder, not a new one: by thread id, by the chat
    # id in an older flag's link, or by the same person and subject (Re: stripped) -- even after the flag
    # was cleared; a different subject from the same person is a new folder
    inbox.save_json(str(created / ".session.json"), dict(new, waiting=None))
    bo = root / "2026/10/12/14-30-00_reply-bo-firewall-rule"
    inbox.save_json(str(bo / ".session.json"), {"name": "Reply to Bo: firewall rule", "source": "claude-inbox", "waiting": {
        "on": "other", "who": "Bo", "link": "https://teams.microsoft.com/l/message/19%3Abbb%40thread.tacv2/17?context=x"}})
    lines = inbox.place([item(message_id="m6", subject="something else", thread_id="19:aaa@unq.gbl.spaces"),
                         item(message_id="m7", who="Bo", subject="FW: Re: Firewall rule", link="https://teams.microsoft.com/l/message/19%3Abbb%40thread.tacv2/18"),
                         item(message_id="m8", subject="Re: firewall rule", link="https://t/8"),
                         item(message_id="m9", subject="another thing", link="")], c)
    assert lines == ["set      Ana Silva · something else -> 2026/10/12/14-30-00_reply-ana-silva-firewall-rule",
                     "flipped  Bo · FW: Re: Firewall rule -> 2026/10/12/14-30-00_reply-bo-firewall-rule",
                     "kept     Ana Silva · Re: firewall rule -> 2026/10/12/14-30-00_reply-ana-silva-firewall-rule",
                     "created  Ana Silva · another thing -> 2026/10/12/14-30-00_reply-ana-silva-another-thing"]
    assert json.loads((bo / ".session.json").read_text())["thread"] == "19:bbb@thread.tacv2"
    # a new thread whose folder name is taken on the same minute gets a -2 folder; a ticket folder
    # with no flag gets "set"
    make_request(root, "11", "plain", {"ticket": "BTPA-9"})
    (root / "2026/10/12/14-30-00_reply-dan-firewall-rule").mkdir()
    lines = inbox.place([item(message_id="m10", who="Dan", link="https://t/10"),
                         item(message_id="", link="", ticket="BTPA-9", who="Cy", subject="BTPA-9")], c)
    assert lines[0].endswith("reply-dan-firewall-rule-2")
    assert lines[1].startswith("set      ")
    assert "teams:Cy|BTPA-9" in json.load(open(os.path.join(inbox.DATA_DIR, "seen.json")))
    # threads I answered (found like messages: thread, person and subject, else ticket): a folder waiting on me
    # flips to waiting on them with my reply in thread.md; one waiting on them already, or with no folder, is not news
    ans = lambda **kw: dict({"who": "Ana Silva", "subject": "the IP", "where": "teams", "link": "https://t/r1", "thread_id": "",
                             "replied": "2026-10-12T15:00:00Z", "summary": "sent 10.0.0.5", "what": "confirm it is in the allow-list",
                             "ticket": "BTPA-7"}, **kw)
    lines = inbox.place([], c, dry_run=True, answered=[ans(), ans(who="Zed", subject="nothing", ticket="")])
    assert lines == ["would answer Ana Silva · the IP -> 2026/10/10/10-00-00_ticketed"]
    assert json.loads((ticketed / ".session.json").read_text())["waiting"]["on"] == "me"
    lines = inbox.place([], c, answered=[ans(thread_id="19:ttt@unq.gbl.spaces"), ans(who="Zed", subject="nothing", ticket=""),
                                         ans(who="Cy", subject="BTPA-9", what="", summary="", ticket="BTPA-9")])
    assert lines == ["answered Ana Silva · the IP -> 2026/10/10/10-00-00_ticketed", "answered Cy · BTPA-9 -> 2026/10/11/10-00-00_plain"]
    m = json.loads((ticketed / ".session.json").read_text())
    assert m["waiting"] == {"on": "other", "who": "Ana Silva", "what": "confirm it is in the allow-list", "since": "2026-10-12T15:00:00Z",
                            "where": "teams", "link": "https://t/r1"}
    assert m["waiting_history"][-1]["on"] == "me" and m["waiting_history"][-1]["until"] == "2026-10-12T14:30:00Z" and m["thread"] == "19:ttt@unq.gbl.spaces"
    assert (ticketed / "thread.md").read_text().endswith(
        "## 2026-10-12 15:00 · waiting on them: Ana Silva -- confirm it is in the allow-list (teams)\n\nI replied: sent 10.0.0.5\nLink: https://t/r1\n\n")
    plain = json.loads((root / "2026/10/11/10-00-00_plain/.session.json").read_text())["waiting"]
    assert plain["on"] == "other" and plain["what"] == "confirm the new IP"      # nothing said: what it was waiting for stays
    assert inbox.place([], c, answered=[ans()]) == []                            # already waiting on them


def test_helpers(inbox, home):
    assert inbox.slugify("Reply: Ana / Silva!!") == "reply-ana-silva"
    assert inbox.slugify("") == "reply" and len(inbox.slugify("x" * 100)) == 60
    assert inbox.ticket_of("see btpa-12 and BTPA-13") == "BTPA-12" and inbox.ticket_of("nothing") == ""
    assert inbox.folder_for_ticket([], "Other") is None and inbox.folder_for_ticket([], "") is None
    assert inbox.chat_id("https://teams.microsoft.com/l/message/19%3Aabc-1_2%40unq.gbl.spaces/1?x") == "19:abc-1_2@unq.gbl.spaces"
    assert inbox.chat_id("https://outlook.office.com/mail/x") == "" and inbox.chat_id("") == ""
    assert inbox.thread_of({"thread_id": "", "link": "https://t/19%3Aq%40thread.v2/1"}) == "19:q@thread.v2"
    assert inbox.subject_key("Ana Silva", "RE: Fwd:  Firewall rule!") == "ana-silva|firewall-rule"
    assert inbox.folder_for_thread([], item()) is None
    assert inbox.folder_for_thread([("/w/2026/10/12/10-00-00_x", {"source": "claude-inbox", "name": "odd"})], item()) is None
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
    monkeypatch.setattr(inbox, "scan", lambda cfg, hours: ([item()], [], None))
    assert inbox.main([]) == 0
    out = capsys.readouterr().out
    assert "1 item(s) need a reply in the last 3h, 1 new\n" in out and "created  Ana Silva" in out
    st = json.load(open(os.path.join(inbox.DATA_DIR, "state.json")))
    assert (st["found"], st["new"], st["answered"], st["error"], st["hours"]) == (1, 1, 0, None, 3.0)
    assert inbox.main(["--status"]) == 0
    assert "last run" in capsys.readouterr().out and "1 item(s), 1 new" in inbox.status()
    # I answered it: the next run flips the folder and says so
    monkeypatch.setattr(inbox, "scan", lambda cfg, hours: ([], [{"who": "Ana Silva", "subject": "firewall rule", "where": "teams",
        "link": "", "thread_id": "", "replied": "", "summary": "done", "what": "", "ticket": ""}], None))
    assert inbox.main([]) == 0
    out = capsys.readouterr().out
    assert "0 item(s) need a reply in the last 3h, 0 new; 1 answered by me" in out and "answered Ana Silva" in out
    assert json.load(open(os.path.join(inbox.DATA_DIR, "state.json")))["answered"] == 1
    monkeypatch.setattr(inbox, "scan", lambda cfg, hours: ([item()], [], None))
    assert inbox.main(["--dry-run", "--hours", "24"]) == 0
    assert "would" not in capsys.readouterr().out      # already seen
    monkeypatch.setattr(inbox, "scan", lambda cfg, hours: ([], [], "Not logged in"))
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
