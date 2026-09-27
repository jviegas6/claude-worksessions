"""claude-guard: the prompt / tool / stop hooks that keep a session on its request."""

import io
import json
import os
import subprocess
import types

import pytest

from conftest import load_script


@pytest.fixture
def guard(home, monkeypatch):
    monkeypatch.setenv("CWS_GUARD_MODE", "shadow")
    monkeypatch.delenv("CWS_GUARD_JUDGE", raising=False)
    return load_script("claude-guard")


@pytest.fixture
def sdir(home):
    d = home / "work_sessions" / "2026" / "09" / "26" / "10-00-00_access-policy"
    d.mkdir(parents=True)
    (d / ".session.json").write_text(json.dumps({"name": "access policy", "goal": "fix the row filter on core",
                                                 "done_when": "verified with an test user"}))
    return d


def cfg(guard, mode="shadow", **kw):
    c = guard.settings(guard.load_config())
    return dict(c, mode=mode, **kw)


def records(sdir):
    p = sdir / ".quality.jsonl"
    return [json.loads(l) for l in p.read_text().splitlines()] if p.exists() else []


def state(sdir, sid="s1"):
    return json.loads((sdir / ".scope.json").read_text())["sessions"][sid]


def fake_judge(monkeypatch, guard, answer=None, stdout=None, exc=None, calls=None):
    def run(cmd, **kw):
        if calls is not None:
            calls.append((cmd, kw))
        if exc:
            raise exc
        out = stdout if stdout is not None else json.dumps({"is_error": False, "structured_output": answer})
        return types.SimpleNamespace(stdout=out, stderr="")
    monkeypatch.setattr(guard.subprocess, "run", run)


def prompt(guard, sdir, text, c, sid="s1"):
    return guard.on_prompt({"session_id": sid, "cwd": str(sdir), "prompt": text}, c)


def tool(guard, sdir, name, inp, c, sid="s1"):
    return guard.on_tool({"session_id": sid, "cwd": str(sdir), "tool_name": name, "tool_input": inp}, c)


# --- what things name --------------------------------------------------------------------
def test_anchors_and_matching(guard):
    a = guard.prompt_anchors("pesquisa as fontes em sales_db.core e ~/Repos/BI Handover/sabio. "
                             "Ver https://x.com/a, file.md")
    assert {"sales_db.core", "https://x.com/a"} <= a and "sales_db" not in a
    assert os.path.expanduser("~/repos/bi handover/sabio").lower() in a and "file.md" not in a
    b = guard.anchors("dbcli tables get sales_db.staging.fact_x 2>/dev/null | python3 -c 'os.path.join'; "
                      "self.x.y('a.b.c.py')")
    assert b == {"sales_db.staging.fact_x", "/dev/null"}
    assert guard.matches("sales_db.core.dim_x", ["core"])
    assert guard.matches("/r/sabio/x.py", ["/r/sabio"]) and guard.matches("a.b.fact_x", ["fact_x"])
    assert not guard.matches("sales_db.staging.x", ["sales_db.core", "ab"])


def test_reached_by_tool(guard):
    assert guard.reached("Read", {"file_path": "/A/b.py"}) == {"/a/b.py"}
    assert guard.reached("Grep", {"pattern": "x"}) == set()
    assert guard.reached("WebFetch", {"url": "https://X"}) == {"https://x"}
    assert guard.reached("WebSearch", {"query": " Access Rules "}) == {"search: access rules"} and guard.reached("WebSearch", {}) == set()
    assert guard.reached("Bash", {"command": "cat /etc/hosts"}) == {"/etc/hosts"}
    assert guard.reached("mcp__sql__run", {"q": ["select 1 from a_b.c.d"]}) == {"a_b.c.d"}


def test_trivial(guard):
    for t in ("", "/weekly-review", "<bash-input>", "yes", "ok go ahead", "sim, faz", "merge it"):
        assert guard.trivial(t), t
    for t in ("yes but also check the staging schema tables and views", "why?", "check sales_db.core"):
        assert not guard.trivial(t), t


def test_session_dir_and_settings(guard, sdir, home, tmp_path):
    sub = sdir / "notes"
    sub.mkdir()
    root = guard.settings(guard.load_config())["root"]
    assert guard.session_dir(str(sub), root) == os.path.realpath(sdir)
    assert guard.session_dir(str(home / "work_sessions"), root) is None
    assert guard.session_dir(str(tmp_path), root) is None
    s = guard.settings({"CWS_GUARD_MODE": "Loud", "CWS_GUARD_JUDGE_TIMEOUT": "x", "CWS_WORK_ROOT": str(tmp_path)})
    assert s["mode"] == "off" and s["timeout"] == 15.0 and s["model"] == "haiku"
    assert guard.session_goal(str(sdir)) == ("fix the row filter on core", "verified with an test user")
    (sdir / ".session.json").write_text(json.dumps({"name": "access policy"}))
    assert guard.session_goal(str(sdir)) == ("access policy", "")


def test_config_file(guard, home, monkeypatch, tmp_path):
    monkeypatch.delenv("CWS_GUARD_MODE")
    conf = tmp_path / "c.env"
    conf.write_text('# comment\nCWS_GUARD_MODE=enforce  # on\nCWS_GUARD_MODEL="sonnet"\nCWS_WORK_ROOT=$HOME/ws\n')
    monkeypatch.setenv("CWS_CONFIG", str(conf))
    s = guard.settings(guard.load_config())
    assert (s["mode"], s["model"], s["root"]) == ("enforce", "sonnet", os.path.realpath(str(home / "ws")))
    monkeypatch.setenv("CWS_GUARD_IGNORE_NAMES", "Platform sdk")
    ig = guard.settings(guard.load_config())["ignore"]
    assert guard.anchors("run platform.jobs.list and a.b.c", ig) == {"a.b.c"}
    assert guard.session_goal(str(tmp_path)) == ("", "")                                # no .session.json


# --- prompt ----------------------------------------------------------------------------------
def test_shadow_prompt_judges_in_the_background(guard, sdir, monkeypatch):
    started = []
    monkeypatch.setattr(guard.subprocess, "Popen", lambda args, **kw: started.append((args, kw)))
    assert prompt(guard, sdir, "fix the row filter on sales_db.core.orders_daily", cfg(guard)) is None
    (args, kw), = started
    assert args[2:4] == ["judge", os.path.realpath(sdir)] and kw["start_new_session"]
    job = json.loads(args[4])
    assert job["goal"] == "fix the row filter on core" and job["no"] == 1 and job["literal"] == ""
    assert "sales_db.core.orders_daily" in state(sdir)["targets"]
    assert prompt(guard, sdir, "yes", cfg(guard)) is None and len(started) == 1       # trivial: no judge
    assert records(sdir) == []


def test_shadow_prompt_logs_when_the_judge_cannot_start(guard, sdir, monkeypatch):
    def boom(*a, **k):
        raise OSError("no python")
    monkeypatch.setattr(guard.subprocess, "Popen", boom)
    prompt(guard, sdir, "look at the policy function code", cfg(guard))
    assert records(sdir)[0]["judge_error"] and "no python" in records(sdir)[0]["reason"]


def test_force_and_widen(guard, sdir, monkeypatch):
    monkeypatch.setattr(guard.subprocess, "Popen", lambda *a, **k: None)
    assert prompt(guard, sdir, "force: survey every permission method", cfg(guard, "enforce")) is None
    r, = records(sdir)
    assert r["override"] and r["decision"] == "allow" and state(sdir)["open"]
    prompt(guard, sdir, "aprofunda as fontes do modelo", cfg(guard))
    assert records(sdir)[-1]["widened"] and state(sdir)["open"]
    prompt(guard, sdir, "now list the columns of the table", cfg(guard))
    assert not state(sdir)["open"]


def test_enforce_blocks_a_pivot_and_keeps_the_scope(guard, sdir, monkeypatch):
    calls = []
    fake_judge(monkeypatch, guard, {"verdict": "continuation", "literal": "Fix the filter.", "targets": ["Core"],
                                    "reason": "first"}, calls=calls)
    out = prompt(guard, sdir, "fix the row filter function", cfg(guard, "enforce"))
    assert "Fix the filter." in out["hookSpecificOutput"]["additionalContext"]
    cmd, kw = calls[0]
    assert cmd[:4] == ["claude", "-p", "--settings", '{"disableAllHooks": true}'] and kw["env"]["CWS_GUARD_JUDGE"] == "1"
    assert "first request" in cmd[-1]
    fake_judge(monkeypatch, guard, {"verdict": "pivot", "literal": "Survey methods.", "targets": ["everything"],
                                    "reason": "broader survey"}, calls=calls)
    out = prompt(guard, sdir, "what permission methods exist in the platform overall?", cfg(guard, "enforce"))
    assert out["decision"] == "block" and "broader survey" in out["reason"] and "force:" in out["reason"]
    assert "CURRENT SCOPE: Fix the filter." in calls[-1][0][-1]
    st = state(sdir)
    assert st["literal"] == "Fix the filter." and st["targets"] == ["core"]           # the pivot added nothing
    fake_judge(monkeypatch, guard, {"verdict": "pivot", "literal": "x", "targets": [], "reason": "r"})
    prompt(guard, sdir, "go deeper into other_db.audit.events", cfg(guard, "enforce"))
    assert state(sdir)["targets"] == ["core"] and not state(sdir)["open"]
    assert [(r["type"], r.get("widened")) for r in records(sdir)] == [("ok", None), ("pivot", None), ("ok", True), ("pivot", None)]


def test_first_prompt_is_never_a_pivot_and_shadow_pivots_still_grow_scope(guard, sdir, monkeypatch):
    fake_judge(monkeypatch, guard, {"verdict": "pivot", "literal": "", "targets": [], "reason": "?"})
    job = {"sid": "s1", "no": 1, "prompt": "p", "goal": "g", "done_when": "", "literal": ""}
    ans, err, _ = guard.judge(job, cfg(guard))
    assert ans["verdict"] == "continuation" and err is None
    with guard.scope(str(sdir), "s1") as st:
        st["prompt_no"] = 2
    fake_judge(monkeypatch, guard, {"verdict": "pivot", "literal": "L", "targets": ["t1 "], "reason": "r"})
    guard.main(["judge", str(sdir), json.dumps(dict(job, no=2, literal="before"))])
    assert state(sdir)["targets"] == ["t1"] and records(sdir)[-1]["decision"] == "block"


def test_a_late_verdict_does_not_overwrite_a_newer_request(guard, sdir):
    with guard.scope(str(sdir), "s1") as st:
        st.update(prompt_no=3, literal="newer")
    job = {"sid": "s1", "no": 2, "prompt": "p"}
    guard.apply_verdict(str(sdir), job, cfg(guard), {"verdict": "continuation", "literal": "old", "targets": ["x"]},
                        None, 5)
    assert state(sdir)["literal"] == "newer" and "targets" not in state(sdir)


@pytest.mark.parametrize("kw,err", [
    ({"stdout": json.dumps({"is_error": True, "result": "Not logged in"})}, "Not logged in"),
    ({"stdout": "garbage"}, "Expecting value"),
    ({"exc": subprocess.TimeoutExpired("claude", 15)}, "timeout after 15s"),
    ({"exc": OSError("no claude")}, "no claude"),
])
def test_judge_failures_let_the_prompt_through(guard, sdir, monkeypatch, kw, err):
    fake_judge(monkeypatch, guard, **kw)
    assert prompt(guard, sdir, "fix the row filter function", cfg(guard, "enforce")) is None
    r = records(sdir)[-1]
    assert r["judge_error"] and r["decision"] == "allow" and err in r["reason"]
    assert "fix" not in state(sdir)["targets"] and state(sdir)["open"] is False       # failed open: names kept


def test_rules_come_from_config(guard, home, sdir, monkeypatch):
    calls = []
    fake_judge(monkeypatch, guard, {"verdict": "continuation", "literal": "", "targets": [], "reason": ""}, calls=calls)
    c = cfg(guard, "enforce")
    assert guard.rules_text(c["root"]) == guard.DEFAULT_RULES
    (home / "work_sessions" / "_config").mkdir()
    (home / "work_sessions" / "_config" / "guard-rules.md").write_text("MY RULES")
    assert prompt(guard, sdir, "fix the row filter function", c) is None
    assert calls[0][0][calls[0][0].index("--system-prompt") + 1].startswith("MY RULES")
    (home / "work_sessions" / "_config" / "guard-rules.md").write_text("  ")
    assert guard.rules_text(c["root"]) == guard.DEFAULT_RULES


def test_outside_a_session_folder_nothing_happens(guard, tmp_path):
    c = cfg(guard, "enforce")
    payload = {"session_id": "s", "cwd": str(tmp_path), "prompt": "x y z", "tool_name": "Bash", "tool_input": {}}
    assert guard.on_prompt(payload, c) is None and guard.on_tool(payload, c) is None and guard.on_stop(payload, c) is None


# --- tool ------------------------------------------------------------------------------------
def test_tool_flags_calls_outside_the_targets(guard, sdir, monkeypatch):
    monkeypatch.setattr(guard.subprocess, "Popen", lambda *a, **k: None)
    prompt(guard, sdir, "list the sources of sales_db.core.orders_daily", cfg(guard))
    sql = {"statement": "select * from sales_db.staging.orders"}
    assert tool(guard, sdir, "mcp__sql__run", sql, cfg(guard)) is None        # shadow: log only
    assert tool(guard, sdir, "mcp__sql__run", sql, cfg(guard)) is None        # logged once
    r, = records(sdir)
    assert r["type"] == "depth" and r["reached"] == ["sales_db.staging.orders"] and r["initiated_by"] == "agent"
    out = tool(guard, sdir, "Read", {"file_path": "/etc/other.conf"}, cfg(guard, "enforce"))
    reason = out["hookSpecificOutput"]["permissionDecisionReason"]
    assert out["hookSpecificOutput"]["permissionDecision"] == "deny" and "/etc/other.conf" in reason
    again = tool(guard, sdir, "Read", {"file_path": "/etc/other.conf"}, cfg(guard, "enforce"))
    assert again["hookSpecificOutput"]["permissionDecision"] == "deny" and len(records(sdir)) == 2
    for ok in ({"file_path": str(sdir / "notes.md")}, {"file_path": "/tmp/x"}):
        assert tool(guard, sdir, "Read", ok, cfg(guard, "enforce")) is None
    assert tool(guard, sdir, "Bash", {"command": "dbcli tables get sales_db.core.orders_daily"},
                cfg(guard, "enforce")) is None
    assert tool(guard, sdir, "Edit", {"file_path": "/etc/x"}, cfg(guard, "enforce")) is None     # not a read
    assert state(sdir)["turn"]["reach"] == 7


def test_tool_is_open_without_targets_or_after_go_deeper(guard, sdir, monkeypatch):
    monkeypatch.setattr(guard.subprocess, "Popen", lambda *a, **k: None)
    assert tool(guard, sdir, "Read", {"file_path": "/etc/a"}, cfg(guard, "enforce")) is None     # no contract yet
    prompt(guard, sdir, "go deeper into sales_db.core lineage", cfg(guard))
    assert tool(guard, sdir, "Read", {"file_path": "/etc/a"}, cfg(guard, "enforce")) is None
    assert [r.get("widened") for r in records(sdir)] == [True]


def test_tool_catches_a_loop(guard, sdir):
    c = cfg(guard, "enforce")
    for _ in range(2):
        assert tool(guard, sdir, "Bash", {"command": "ls"}, c) is None
    out = tool(guard, sdir, "Bash", {"command": "ls"}, c)
    assert "same Bash call 3 times" in out["hookSpecificOutput"]["permissionDecisionReason"]
    assert records(sdir)[-1]["type"] == "loop"
    assert "4 times" in tool(guard, sdir, "Bash", {"command": "ls"}, c)["hookSpecificOutput"]["permissionDecisionReason"]
    assert len(records(sdir)) == 1                                                               # logged once


# --- stop ------------------------------------------------------------------------------------
def stop(guard, sdir, c, text, active=False):
    return guard.on_stop({"session_id": "s1", "cwd": str(sdir), "last_assistant_message": text,
                          "stop_hook_active": active}, c)


def test_stop_asks_once_for_next_level_proposals(guard, sdir, monkeypatch):
    monkeypatch.setattr(guard.subprocess, "Popen", lambda *a, **k: None)
    c = cfg(guard, "enforce")
    prompt(guard, sdir, "list the sources of the orders_daily model", c | {"mode": "shadow"})
    tool(guard, sdir, "Read", {"file_path": str(sdir / "a")}, c)
    tool(guard, sdir, "Read", {"file_path": str(sdir / "b")}, c)
    out = stop(guard, sdir, c, "The sources are A and B.")
    assert out["decision"] == "block" and "next level" in out["reason"]
    assert stop(guard, sdir, c, "The sources are A and B. Next step: open A.", active=True) is None
    assert stop(guard, sdir, c, "again") is None                                    # nothing new since the last stop
    assert [(r["event"], r["decision"], r.get("retry")) for r in records(sdir)[-2:]] == [
        ("stop", "block", False), ("stop", "allow", True)]


def test_stop_in_shadow_logs_and_lets_go(guard, sdir, monkeypatch):
    monkeypatch.setattr(guard.subprocess, "Popen", lambda *a, **k: None)
    c = cfg(guard)
    assert stop(guard, sdir, c, "hi") is None and records(sdir)[-1]["type"] == "ok"                 # no investigation
    prompt(guard, sdir, "list the sources of sales_db.core.orders_daily", c)
    tool(guard, sdir, "Read", {"file_path": "/etc/x"}, c)
    tool(guard, sdir, "Read", {"file_path": "/etc/y"}, c)
    assert stop(guard, sdir, c, "Done.") is None
    r = records(sdir)[-1]
    assert r["type"] == "depth" and r["decision"] == "block" and r["outside"] == 2 and "/etc/x" in r["reason"]
    prompt(guard, sdir, "and the columns of sales_db.core.orders_daily?", c)
    tool(guard, sdir, "Read", {"file_path": str(sdir / "a")}, c)
    tool(guard, sdir, "Read", {"file_path": str(sdir / "b")}, c)
    assert stop(guard, sdir, c, "Columns: a, b. Want me to check the lineage too?") is None
    assert records(sdir)[-1]["type"] == "ok"


# --- main and report ---------------------------------------------------------------------------
def test_main_is_quiet_and_fails_open(guard, sdir, monkeypatch, capsys):
    run = lambda argv, data: (guard.main(argv, io.StringIO(data), io.StringIO()))
    payload = json.dumps({"session_id": "s1", "cwd": str(sdir), "tool_name": "Bash", "tool_input": {"command": "ls"}})
    for _ in range(2):
        assert run(["tool"], payload) == 0
    monkeypatch.setenv("CWS_GUARD_MODE", "enforce")
    out = io.StringIO()
    assert guard.main(["tool"], io.StringIO(payload), out) == 0 and "deny" in out.getvalue()
    monkeypatch.setenv("CWS_GUARD_JUDGE", "1")                                        # inside the judge: silent
    out = io.StringIO()
    assert guard.main(["tool"], io.StringIO(payload), out) == 0 and out.getvalue() == ""
    monkeypatch.delenv("CWS_GUARD_JUDGE")
    for bad in ("not json", "[1]"):
        out = io.StringIO()
        assert guard.main(["stop"], io.StringIO(bad), out) == 0 and out.getvalue() == ""
    assert "JSONDecodeError" in capsys.readouterr().err
    monkeypatch.setenv("CWS_GUARD_MODE", "off")
    assert run(["tool"], payload) == 0
    assert run(["nope"], "") == 1 and run(["--help"], "") == 0
    assert "usage" in capsys.readouterr().err


def test_log_failure_is_reported_not_raised(guard, tmp_path, capsys):
    guard.log(str(tmp_path / "missing"), {"a": 1})
    assert "can't write" in capsys.readouterr().err


def test_scope_survives_a_broken_file(guard, sdir):
    (sdir / ".scope.json").write_text("[1]")
    with guard.scope(str(sdir), "s1") as st:
        st["x"] = 1
    (sdir / ".scope.json").write_text("{bad")
    with guard.scope(str(sdir), None) as st:
        st["y"] = 2
    assert state(sdir, "none") == {"y": 2}


def test_report(guard, sdir, home):
    out = io.StringIO()
    guard.main(["report"], stdout=out)
    assert "0 records" in out.getvalue()
    lines = [{"ts": "2026-01-01T00:00:00Z", "event": "prompt", "type": "pivot"},
             {"event": "prompt", "type": "pivot", "decision": "block", "prompt": "survey everything", "reason": "broader",
              "judge_ms": 9000},
             {"event": "prompt", "type": "ok", "decision": "allow", "judge_ms": 1000},
             {"event": "prompt", "type": "ok", "decision": "allow", "judge_error": True, "judge_ms": 15000},
             {"event": "prompt", "type": "ok", "decision": "allow", "override": True},
             {"event": "tool", "type": "depth", "decision": "deny", "reached": ["a.b.c"], "reason": "outside"},
             {"event": "tool", "type": "loop", "decision": "deny", "tool": "Bash"}]
    with open(sdir / ".quality.jsonl", "w") as fh:
        for l in lines:
            fh.write(json.dumps(dict({"ts": guard.now()}, **l)) + "\n")
        fh.write("garbage\n")
    out = io.StringIO()
    assert guard.main(["report", "--days", "7", str(home / "work_sessions")], stdout=out) == 0
    text = out.getvalue()
    assert "6 records" in text and "judge: 2 calls, median 9.0s" in text and "1 failed" in text
    assert "overrides (force:): 1" in text and "survey everything" in text and "a.b.c" in text and "Loops" in text
    assert "prompt   pivot   block        1" in text


# --- judge profile, journal and review ------------------------------------------------------
def test_judge_profile(guard, home, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(home / ".claude-work"))
    name, env, err = guard.judge_profile(cfg(guard))
    assert (name, err) == ("work", None) and env["CWS_GUARD_JUDGE"] == "1"
    (home / ".claude-personal").mkdir()
    name, env, err = guard.judge_profile(cfg(guard, profile="personal"))
    assert name == "personal" and env["CLAUDE_CONFIG_DIR"] == str(home / ".claude-personal") and err is None
    name, env, err = guard.judge_profile(cfg(guard, profile="nope"))
    assert "not found" in err
    monkeypatch.delenv("CLAUDE_CONFIG_DIR")
    assert guard.judge_profile(cfg(guard))[0] == "default"


def test_a_missing_judge_profile_fails_open(guard, sdir, monkeypatch):
    calls = []
    fake_judge(monkeypatch, guard, {}, calls=calls)
    assert prompt(guard, sdir, "fix the row filter function", cfg(guard, "enforce", profile="nope")) is None
    assert calls == [] and "judge profile dir" in records(sdir)[-1]["reason"]


def test_journal_and_review(guard, sdir, home, monkeypatch):
    root = home / "work_sessions"
    c = cfg(guard, "enforce")
    fake_judge(monkeypatch, guard, {"verdict": "continuation", "literal": "Fix it.", "targets": [], "reason": "first"})
    prompt(guard, sdir, "fix the row filter function", c)
    fake_judge(monkeypatch, guard, {"verdict": "pivot", "literal": "Survey.", "targets": [], "reason": "broader"})
    prompt(guard, sdir, "survey every access method", c)
    fake_judge(monkeypatch, guard, exc=OSError("no claude"))
    prompt(guard, sdir, "then document the result", c)
    j = [json.loads(l) for l in (root / "_audit" / "guard" / "judge.jsonl").read_text().splitlines()]
    assert [d.get("verdict") for d in j] == ["continuation", "pivot", None] and j[2]["error"] == "no claude"
    assert j[1]["goal"] == "fix the row filter on core" and j[1]["scope_before"] == "Fix it." and j[1]["enforced"]
    assert j[1]["folder"].endswith("10-00-00_access-policy") and j[1]["model"] == "haiku"
    assert records(sdir)[1]["judge_id"] == j[1]["id"]
    run = lambda *a: (lambda o: (guard.main(["review", *a], stdout=o), o.getvalue())[1])(io.StringIO())
    listing = run()
    assert "2 decision(s) to review" in listing and j[1]["id"] in listing and j[0]["id"] not in listing
    assert j[0]["id"] in run("--all", "--days", "3")
    assert run(j[1]["id"][:6], "wrong", "a", "follow-up") == "recorded: {} is wrong\n".format(j[1]["id"])
    assert run(j[2]["id"], "right") and "1 decision(s) to review" not in run()
    assert "[wrong]" in run("--all")
    assert "usage" in run(j[1]["id"], "maybe") and "0 decisions match" in run("zzz", "right")
    out = io.StringIO()
    guard.main(["report"], stdout=out)
    assert "judge reviewed: 2 of 3, 1 right, 1 wrong" in out.getvalue() and "(a follow-up)" in out.getvalue()


def test_journal_write_failure_is_reported(guard, sdir, home, capsys):
    (home / "work_sessions" / "_audit").write_text("a file, not a folder")
    guard.apply_verdict(str(sdir), {"sid": "s1", "no": 1, "prompt": "p"}, cfg(guard), None, "x", 1)
    assert "judge journal" in capsys.readouterr().err
    assert guard.read_jsonl(str(home / "missing.jsonl")) == []
