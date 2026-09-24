"""The prompt-quality pieces: the 'does not exist' hook and claude-retro."""

import datetime as dt
import io
import json
import os
import time
import types

import pytest

from test_sessions import rec, write_transcript


# --- claude-hook-notfound ---------------------------------------------------------------
def test_hook_speaks_only_on_clear_missing_resources(hook, tmp_path, monkeypatch):
    monkeypatch.setattr(hook.tempfile, "gettempdir", lambda: str(tmp_path))
    say = lambda payload: hook.react(dict(payload, session_id=payload.get("session_id", "s1")))
    a = say({"hook_event_name": "PostToolUseFailure", "error": "[TABLE_OR_VIEW_NOT_FOUND] `a`.`b`.`c`"})
    assert a["hookSpecificOutput"]["hookEventName"] == "PostToolUseFailure"
    assert "TABLE_OR_VIEW_NOT_FOUND" in a["hookSpecificOutput"]["additionalContext"]
    assert "confirm with the user" in a["hookSpecificOutput"]["additionalContext"]
    assert say({"tool_response": {"stdout": "Group sec_x does not exist"}})["hookSpecificOutput"]["hookEventName"] == "PostToolUse"
    for quiet in ({"tool_response": {"stdout": "ls: x: No such file or directory"}},
                  {"tool_response": {"stdout": "HTTP 404 not found"}}, {"tool_response": "all good"}, {}):
        assert say(quiet) is None
    assert say({"tool_output": "ResourceNotFound"}) is not None                         # third time
    assert say({"error": "PRINCIPAL_DOES_NOT_EXIST"}) is None                           # limit reached
    assert say({"session_id": "other", "error": "PRINCIPAL_DOES_NOT_EXIST"}) is not None


def test_hook_state_survives_odd_ids_and_bad_files(hook, tmp_path, monkeypatch):
    monkeypatch.setattr(hook.tempfile, "gettempdir", lambda: str(tmp_path))
    assert hook.state_path("../../etc/x").startswith(str(tmp_path)) and "/.." not in hook.state_path("../x")
    open(hook.state_path("bad"), "w").write("nonsense")
    assert hook.count_and_bump("bad") == 0 and hook.count_and_bump("bad") == 1
    assert hook.count_and_bump(None) == 0
    monkeypatch.setattr(hook.tempfile, "gettempdir", lambda: str(tmp_path / "missing" / "dir"))
    assert hook.count_and_bump("x") == 0                                                 # can't save: still answers


def test_hook_main(hook, tmp_path, monkeypatch):
    monkeypatch.setattr(hook.tempfile, "gettempdir", lambda: str(tmp_path))
    out = io.StringIO()
    assert hook.main(io.StringIO(json.dumps({"session_id": "m", "error": "SCHEMA_NOT_FOUND"})), out) == 0
    assert json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]
    for bad in ("not json", "[1, 2]", json.dumps({"tool_response": "fine"})):
        out = io.StringIO()
        assert hook.main(io.StringIO(bad), out) == 0 and out.getvalue() == ""


# --- claude-retro ------------------------------------------------------------------------
def asst(text=None, tools=()):
    content = ([{"type": "text", "text": text}] if text else []) + [
        {"type": "tool_use", "id": i, "name": n, "input": inp} for i, n, inp in tools]
    return {"type": "assistant", "message": {"content": content}}


def result(tool_id, text, error=False):
    return {"type": "user", "message": {"content": [{"type": "tool_result", "tool_use_id": tool_id, "content": text,
                                                      "is_error": error}]}}


def test_asks_back_tells_questions_from_offers(retro):
    assert retro.asks_back("I checked.\nWhich environment should I use, dev or prod?") == "Which environment should I use, dev or prod?"
    assert retro.asks_back("Done. Shall I open the PR?") is None
    assert retro.asks_back("Want me to build it?") is None
    assert retro.asks_back("All done.") is None
    assert retro.asks_back("Is this ok?") is None                                   # no clarifying cue
    assert retro.asks_back("") is None and retro.asks_back(None) is None


def test_scan_finds_every_signal_and_ties_it_to_the_prompt(retro, home):
    p = write_transcript(home, "s", [
        "junk", "[1]",
        {"type": "user", "isMeta": True, "message": {"content": "caveat"}},
        {"type": "user", "message": {"content": "<command-name>/clear</command-name>"}},
        {"type": "user", "message": {"content": "check table a.b.c"}},
        asst(tools=[("t1", "Bash", {"command": "q"}), ("t2", "Bash", {"command": "r"})]),
        result("t1", "[TABLE_OR_VIEW_NOT_FOUND] a.b.c", True),
        result("t2", "User rejected: the user doesn't want to proceed", True),
        asst(tools=[("t3", "AskUserQuestion", {"questions": [{"question": "Which catalog?"}]})]),
        asst("Which workspace do you mean, dev or prod?"),
        {"type": "user", "message": {"content": "no, I meant the uat one"}},
        asst("Ok. Shall I continue?"),
        {"type": "user", "message": {"content": [{"type": "text", "text": "[Request interrupted by user]"}]}},
        {"type": "user", "message": {"content": "[Request interrupted by user for tool use]"}},
        {"type": "user", "message": {"content": "roll it back please"}},
        {"type": "user", "isSidechain": True, "message": {"content": "no, subagent"}},
        result("unknown", "x" * 3000 + " not found", False),
    ])
    eps, n = retro.scan(str(p))
    assert n == 3
    by = {(e["kind"], e["prompt"]): e for e in eps}
    assert by[("missing data or resource", "check table a.b.c")]["details"][0].startswith('Bash: {"command": "q"}')
    assert ("rejected tool call", "check table a.b.c") in by
    assert by[("clarifying question", "check table a.b.c")]["count"] == 2              # tool + text
    assert by[("correction", "check table a.b.c")]["details"] == ["no, I meant the uat one"]
    assert by[("interrupted", "no, I meant the uat one")]["count"] == 2              # both interruption forms
    assert ("reversal", "no, I meant the uat one") in by
    assert ("interrupted", "roll it back please") not in by


def test_collapse_and_period(retro):
    eps = retro.collapse([("k", "p", "a"), ("k", "p", ""), ("k", "p", "b"), ("k", "p", "c"), ("k", "p", "d"), ("k", "p", "e"), ("j", None, "")])
    assert eps[0] == {"kind": "k", "prompt": "p", "count": 6, "details": ["a", "b", "c", "d"]} and eps[1]["count"] == 1
    today = dt.date(2026, 9, 24)                                                        # a Thursday
    ns = lambda **k: types.SimpleNamespace(**dict({"week": None, "days": 7}, **k))
    assert retro.period(ns(), today) == (dt.date(2026, 9, 18), today)
    assert retro.period(ns(days=1), today) == (today, today)
    assert retro.period(ns(week=""), today) == (dt.date(2026, 9, 14), dt.date(2026, 9, 20))
    assert retro.period(ns(week="2026-09-02"), today) == (dt.date(2026, 8, 31), dt.date(2026, 9, 6))


def old(p, days):
    t = time.time() - days * 86400
    os.utime(p, (t, t))
    return p


def world(home):
    req = home / "work_sessions" / "2026" / "09" / "20" / "10-00-00_demo"
    req.mkdir(parents=True)
    (req / ".session.json").write_text(json.dumps({"name": "demo", "ticket": "PROJ-1"}))
    recent = old(write_transcript(home, "recent", [
        {"type": "user", "cwd": str(req), "message": {"content": "check table a.b.c"}},
        asst(tools=[("t1", "Bash", {"command": "q"})]),
        result("t1", "TABLE_OR_VIEW_NOT_FOUND", True),
        {"type": "user", "message": {"content": "no, I meant x.y.z"}}], project="p1"), 1)
    old(write_transcript(home, "ancient", [rec("user", "hello", cwd=str(req))], project="p1"), 60)
    old(write_transcript(home, "quiet", [rec("user", "just a prompt", cwd=str(req))], project="p1"), 2)
    old(write_transcript(home, "empty", [asst("hi")], project="p1"), 1)
    return req


def test_collect_keeps_sessions_in_the_period(retro, home):
    world(home)
    today = dt.date.today()
    sessions, prompts = retro.collect(today - dt.timedelta(days=6), today)
    ids = {s["id"]: s for s in sessions}
    assert set(ids) == {"recent", "quiet"} and prompts == 3
    assert ids["recent"]["request"] == "demo" and ids["recent"]["ticket"] == "PROJ-1"
    assert [e["kind"] for e in ids["recent"]["episodes"]] == ["missing data or resource", "correction"]


def verdict(i, caused=True, conf="high", cause="ambiguous-target"):
    return {"i": i, "prompt_caused": caused, "confidence": conf, "cause": cause, "why": "w{}".format(i),
            "better_prompt": "better {}".format(i), "habit": "name the table"}


def test_judge_calls_claude_once_per_session_and_caches(retro, home, monkeypatch):
    world(home)
    today = dt.date.today()
    sessions, _ = retro.collect(today - dt.timedelta(days=6), today)
    calls = []

    def fake_run(cmd, **kw):
        calls.append((cmd, kw["input"]))
        return types.SimpleNamespace(returncode=0, stdout="Here: " + json.dumps([verdict(0), verdict(1, False)]), stderr="")
    monkeypatch.setattr(retro.subprocess, "run", fake_run)
    msgs = []
    v = retro.judge(sessions, "a data engineer", "sonnet", progress=msgs.append)
    assert len(calls) == 1 and calls[0][0][:4] == ["claude", "-p", "--model", "sonnet"]
    assert "a data engineer" in calls[0][1] and "check table a.b.c" in calls[0][1]
    assert v["recent"][0]["cause"] == "ambiguous-target" and v["quiet"] is None
    assert msgs == ["judging 1 session(s) with Claude (1 cached)…"]
    retro.judge(sessions, "x", "sonnet", progress=msgs.append)                          # cached: no new call
    assert len(calls) == 1 and len(msgs) == 1


def test_judge_one_retries_then_reports_the_error(retro, monkeypatch):
    s = {"id": "s", "title": "t", "request": None, "ticket": None, "day": "d",
         "episodes": [{"kind": "k", "prompt": "p", "count": 1, "details": []}]}
    answers = iter([types.SimpleNamespace(returncode=1, stdout="", stderr="rate limited"),
                    types.SimpleNamespace(returncode=0, stdout="[not json", stderr="")])
    monkeypatch.setattr(retro.subprocess, "run", lambda *a, **k: next(answers))
    assert retro.judge_one(s, "r", "m") == {"error": "[not json"}
    answers = iter([types.SimpleNamespace(returncode=0, stdout='{"a": 1} [{"x": 1}] ', stderr="")])
    monkeypatch.setattr(retro.subprocess, "run", lambda *a, **k: next(answers))
    assert retro.judge_one(s, "r", "m") == [{"x": 1}]                                  # text around the list is fine
    def boom(*a, **k):
        raise retro.subprocess.TimeoutExpired("claude", 1)
    monkeypatch.setattr(retro.subprocess, "run", boom)
    assert "timed out" in retro.judge_one(s, "r", "m")["error"]
    monkeypatch.setattr(retro.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout='[{"i": 0}]', stderr=""))
    assert retro.judge_one(s, "r", "m") == [{"i": 0}]
    monkeypatch.setattr(retro.subprocess, "run", lambda *a, **k: types.SimpleNamespace(returncode=0, stdout='[{"i": 0}', stderr=""))
    assert "error" in retro.judge_one(s, "r", "m")


def test_report_judged_unjudged_trend_and_failures(retro):
    s1 = {"id": "a", "title": "Fix the job", "day": "2026-09-20", "episodes": [
        {"kind": "missing data or resource", "prompt": "check it", "count": 3, "details": ["x"]},
        {"kind": "correction", "prompt": "check it", "count": 1, "details": ["no, I meant"]},
        {"kind": "interrupted", "prompt": "go", "count": 1, "details": []}]}
    s2 = {"id": "b", "title": "Other", "day": "2026-09-21", "episodes": [{"kind": "reversal", "prompt": "p", "count": 1, "details": []}]}
    verdicts = {"a": [verdict(0), verdict(1, conf="medium", cause="assumed-exists"), verdict(2, conf="low")], "b": {"error": "x"}}
    history = [{"from": "2026-09-07", "to": "2026-09-13", "prompts": 80, "per_100_prompts": 5.0},
               {"from": "2026-09-14", "to": "2026-09-20", "prompts": 1, "per_100_prompts": 99}]   # same period: replaced
    text, entry = retro.report(dt.date(2026, 9, 14), dt.date(2026, 9, 20), [s1, s2], 40, verdicts, history)
    assert "**2 sessions, 40 prompts, 4 friction episodes**; **2 traced to the prompt** (5.0 per 100 prompts)." in text
    assert "| missing data or resource | 1 | 1 |" in text and "| interrupted | 1 | 0 |" in text  # low confidence: not counted
    assert "| ambiguous-target | 1 |" in text and "| assumed-exists | 1 |" in text
    assert "- name the table *(×2)*" in text
    assert text.index("(ambiguous-target, high)") < text.index("(assumed-exists, medium)")
    assert "Not judged (Claude call failed): Other" in text
    assert "| 2026-09-07 – 2026-09-13 | 80 | 5.0 |" in text and "| 2026-09-14 – 2026-09-20 | 40 | 5.0 |" in text
    assert entry["by_cause"] == {"assumed-exists": 1, "ambiguous-target": 1}
    plain, e2 = retro.report(dt.date(2026, 9, 14), dt.date(2026, 9, 20), [s1], 40, None, [])
    assert "(not judged" in plain and "## Causes" not in plain and "## Trend" not in plain
    assert e2["prompt_caused"] is None
    empty, _ = retro.report(dt.date(2026, 9, 14), dt.date(2026, 9, 20), [], 0, {}, [])
    assert "0 traced to the prompt" in empty


def test_json_helpers(retro, tmp_path):
    assert retro.load_json(str(tmp_path / "missing.json"), [1]) == [1]
    (tmp_path / "bad.json").write_text("{nope")
    assert retro.load_json(str(tmp_path / "bad.json"), {}) == {}
    retro.save_json(str(tmp_path / "deep" / "x.json"), {"a": 1})
    assert retro.load_json(str(tmp_path / "deep" / "x.json"), None) == {"a": 1}


def test_main_writes_the_report_and_history(retro, home, monkeypatch, capsys):
    world(home)
    monkeypatch.setattr(retro.subprocess, "run", lambda cmd, **kw: types.SimpleNamespace(
        returncode=0, stdout=json.dumps([verdict(0), verdict(1)]), stderr=""))
    assert retro.main(["--days", "7"]) == 0
    out = capsys.readouterr().out
    q = home / "work_sessions" / "_audit" / "quality"
    reports = list(q.glob("*_retro.md"))
    assert len(reports) == 1 and "traced to the prompt" in reports[0].read_text() and "report: " in out
    hist = json.loads((q / "history.json").read_text())
    assert len(hist) == 1 and hist[0]["prompt_caused"] == 2
    assert retro.main(["--days", "7"]) == 0                                            # same period: replaced, not added
    assert len(json.loads((q / "history.json").read_text())) == 1
    other = home / "r.md"
    assert retro.main(["--week", "2026-09-02", "--no-judge", "--out", str(other)]) == 0
    assert "(not judged" in other.read_text() and len(json.loads((q / "history.json").read_text())) == 1
    (q / "history.json").write_text('{"not": "a list"}')
    assert retro.main(["--days", "7"]) == 0
    assert isinstance(json.loads((q / "history.json").read_text()), list)


def test_role_wording(retro, home, monkeypatch):
    world(home)
    seen = []
    monkeypatch.setattr(retro, "judge", lambda s, role, model, progress: seen.append(role) or {})
    retro.CA.CONFIG["CWS_USER_ROLE"] = "an analyst"
    retro.main(["--days", "7", "--out", str(home / "a.md")])
    retro.CA.CONFIG["CWS_USER_ROLE"] = "data engineer"
    retro.main(["--days", "7", "--out", str(home / "b.md")])
    retro.CA.CONFIG.pop("CWS_USER_ROLE")
    retro.main(["--days", "7", "--out", str(home / "c.md")])
    assert seen == ["an analyst", "a data engineer", "an engineer"]


def test_load_sessions_falls_back_to_local_bin(retro, home, monkeypatch):
    real = os.path.join(os.path.dirname(retro.__spec__.loader.path), "claude-sessions")
    local = home / ".local" / "bin"
    local.mkdir(parents=True)
    os.symlink(real, local / "claude-sessions")
    isfile = os.path.isfile
    monkeypatch.setattr(os.path, "isfile", lambda p: False if p == real else isfile(p))
    assert retro.load_sessions().__spec__.loader.path == str(local / "claude-sessions")


def test_hook_quotes_the_error_line_as_text(hook, tmp_path, monkeypatch):
    monkeypatch.setattr(hook.tempfile, "gettempdir", lambda: str(tmp_path))
    ctx = lambda p, s: hook.react(dict(p, session_id=s))["hookSpecificOutput"]["additionalContext"]
    assert "(Error: Group sec_x does not exist)" in ctx(
        {"tool_response": {"stdout": "line one\nError: Group sec_x does not exist\nmore", "stderr": "", "interrupted": False}}, "a")
    assert "([TABLE_OR_VIEW_NOT_FOUND] The table `a`.`b` cannot be found.)" in ctx(
        {"error": "[TABLE_OR_VIEW_NOT_FOUND] The table `a`.`b` cannot be found."}, "b")
    assert "(Container logs does not exist)" in ctx(
        {"tool_response": [{"type": "text", "text": "Container logs does not exist"}, 3]}, "c")
    assert "(SCHEMA_NOT_FOUND)" in ctx({"tool_output": "SCHEMA_NOT_FOUND"}, "d")


# --- claude-hook-vague ------------------------------------------------------------------
@pytest.mark.parametrize("prompt,expected", [
    ("can you check which users or SP are now without access?", True),
    ("validate if permissions are there", True),
    ("create a power point presentation with those findings", True),
    ("check sales_prod.bronze.orders for duplicates", False),          # dotted / snake_case name
    ("fix the job in ~/Repos/x", False),                                    # path
    ("investigate PROJ-123 please", False),                                 # ticket
    ("check the storage account in prod", False),                           # environment
    ("look at https://example.com/x", False),                               # URL
    ("check `the thing`", False),                                           # quoted
    ("yes, check it", False),                                               # a reply
    ("/weekly-review now", False),                                          # a command
    ("what time is it", False),                                             # no action
    ("fix it", False),                                                      # too short to judge
    ("check " + "word " * 45, False),                                       # long: probably specified
    ("", False),
    (None, False),
])
def test_vague_prompts(vaguehook, prompt, expected):
    assert vaguehook.vague(prompt) is expected


def test_vague_hook_only_on_the_first_prompts(vaguehook, tmp_path, monkeypatch):
    monkeypatch.setattr(vaguehook.tempfile, "gettempdir", lambda: str(tmp_path))
    ask = lambda p, s="s1": vaguehook.react({"session_id": s, "prompt": p})
    a = ask("validate if permissions are there")
    assert a["hookSpecificOutput"]["hookEventName"] == "UserPromptSubmit"
    assert "ask one or two short questions" in a["hookSpecificOutput"]["additionalContext"]
    assert ask("check sales_prod.bronze.orders") is None                 # 2nd prompt, but specific
    assert ask("validate if permissions are there") is None                  # 3rd prompt: not looked at
    assert ask("validate if permissions are there", "s2") is not None        # a new session
    open(tmp_path / "claude-hook-vague-bad.count", "w").write("x")
    assert ask("validate if permissions are there", "bad") is not None
    monkeypatch.setattr(vaguehook.tempfile, "gettempdir", lambda: str(tmp_path / "missing"))
    assert ask("validate if permissions are there", "s3") is not None       # can't save the count: still works


def test_vague_hook_main(vaguehook, tmp_path, monkeypatch):
    monkeypatch.setattr(vaguehook.tempfile, "gettempdir", lambda: str(tmp_path))
    out = io.StringIO()
    assert vaguehook.main(io.StringIO(json.dumps({"session_id": "m", "prompt": "validate if permissions are there"})), out) == 0
    assert json.loads(out.getvalue())["hookSpecificOutput"]["additionalContext"]
    for bad in ("not json", "[1]", json.dumps({"session_id": "n", "prompt": "yes"})):
        out = io.StringIO()
        assert vaguehook.main(io.StringIO(bad), out) == 0 and out.getvalue() == ""
