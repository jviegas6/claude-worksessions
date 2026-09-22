"""bin/claude-sessions: one row per session, cwd mapped through moved-folders.json."""

import json
import os
import sys


def rec(kind, content=None, **extra):
    r = {"type": kind}
    if content is not None:
        r["message"] = {"content": content}
    r.update(extra)
    return r


def write_transcript(home, sid, records, project="proj", mtime=None):
    d = home / ".claude-personal" / "projects" / project
    d.mkdir(parents=True, exist_ok=True)
    p = d / (sid + ".jsonl")
    p.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in records) + "\n")
    if mtime is not None:
        os.utime(p, (mtime, mtime))
    return p


def run_main(sessions, monkeypatch, capsys, *argv):
    monkeypatch.setattr(sys, "argv", ["claude-sessions", *argv])
    sessions.main()
    return capsys.readouterr().out


def test_load_audit_falls_back_to_local_bin(sessions, home, monkeypatch):
    real = os.path.join(os.path.dirname(sessions.__spec__.loader.path), "claude-audit")
    local = home / ".local" / "bin"
    local.mkdir(parents=True)
    os.symlink(real, local / "claude-audit")
    isfile = os.path.isfile
    monkeypatch.setattr(os.path, "isfile", lambda p: False if p == real else isfile(p))
    mod = sessions.load_audit()
    assert mod.__spec__.loader.path == str(local / "claude-audit")
    assert callable(mod.moved_path)


def test_first_prompt(sessions):
    assert sessions.first_prompt("  fix the job\nmore detail") == "fix the job"
    assert sessions.first_prompt([{"type": "tool_result"}, {"type": "text", "text": "hi"}]) == "hi"
    assert sessions.first_prompt("<command-name>/clear</command-name>") is None
    assert sessions.first_prompt([{"type": "tool_result"}]) is None
    assert sessions.first_prompt("   ") is None
    assert sessions.first_prompt(None) is None


def test_read_head_skips_meta_sidechain_and_junk(sessions, home):
    p = write_transcript(home, "s1", [
        "not json",
        "[1, 2]",
        rec("user", "caveat", isMeta=True, cwd="/w/a"),
        rec("user", "from a subagent", isSidechain=True),
        rec("user", [{"type": "tool_result"}]),
        rec("user", "the real prompt"),
        rec("user", "second prompt"),
    ])
    assert sessions.read_head(str(p)) == ("/w/a", "the real prompt")


def test_duplicate_transcripts_collapse_and_cwd_is_moved(sessions, home, monkeypatch, capsys):
    root = home / "work_sessions"
    old, new = str(root / "2026-09-14_origin"), str(root / "2026" / "09" / "14" / "09-33-07_origin")
    (root / "_audit").mkdir()
    (root / "_audit" / "moved-folders.json").write_text(json.dumps({old: new}))
    body = [rec("user", "find Origin info", cwd=old)]
    # the move left identical copies under the old and the new project dir
    write_transcript(home, "dup", body, project="old-proj", mtime=1_000)
    write_transcript(home, "dup", body, project="new-proj", mtime=2_000)
    write_transcript(home, "other", [rec("user", "hello", cwd=old + "/sub")], mtime=1_500)
    write_transcript(home, "empty", [rec("assistant", "x")], project="bare-proj", mtime=500)

    rows = sessions.sessions()
    assert [(r[2], r[1]) for r in rows] == [
        ("dup", new), ("other", new + "/sub"), ("empty", "bare-proj")]
    assert rows[0][0] == 2_000
    assert rows[2][3] == "(no prompt)"

    out = run_main(sessions, monkeypatch, capsys)
    assert out.count("  dup  ") == 1
    assert "~/work_sessions/2026/09/14/09-33-07_origin  " in out
    assert "2026-09-14_origin" not in out
    assert "3 session(s)" in out and "claude-resume --resume <session-id>" in out


def test_limit_and_all(sessions, home, monkeypatch, capsys):
    for i in range(3):
        write_transcript(home, "s%d" % i, [rec("user", "p%d" % i, cwd="/x")], mtime=1_000 + i)
    out = run_main(sessions, monkeypatch, capsys, "2")
    assert "  s2  " in out and "  s1  " in out and "  s0  " not in out
    assert "2 session(s)" in out
    assert "3 session(s)" in run_main(sessions, monkeypatch, capsys, "-a")


def test_unreadable_transcript_is_skipped(sessions, home, monkeypatch):
    p = write_transcript(home, "gone", [rec("user", "x", cwd="/x")])
    monkeypatch.setattr(sessions.CA, "transcript_files", lambda: [str(p) + ".missing"])
    assert sessions.sessions() == []


def test_read_tail_finds_latest_title_and_prompt(sessions, home):
    p = write_transcript(home, "t", [
        rec("ai-title", aiTitle="old title"),
        rec("last-prompt", lastPrompt="old prompt"),
        '{"type": "ai-title", broken',
        '["ai-title"]',
        rec("ai-title", aiTitle="new title"),
        rec("last-prompt", lastPrompt="new prompt"),
        rec("ai-title"),
    ])
    assert sessions.read_tail(str(p)) == ("new title", "new prompt")
    empty = write_transcript(home, "e", [rec("user", "hi")])
    assert sessions.read_tail(str(empty)) == (None, None)


def test_read_tail_reads_the_whole_file_only_when_the_end_lacks_them(sessions, home, monkeypatch):
    monkeypatch.setattr(sessions, "TAIL", 200)
    filler = [rec("assistant", "x" * 50) for _ in range(10)]
    p = write_transcript(home, "t", [rec("ai-title", aiTitle="early")] + filler
                         + [rec("last-prompt", lastPrompt="late")])
    assert sessions.read_tail(str(p)) == ("early", "late")      # title only at the start
    q = write_transcript(home, "u", filler + [rec("ai-title", aiTitle="a"),
                                              rec("last-prompt", lastPrompt="b")])
    reads = []
    real_open = open
    monkeypatch.setattr("builtins.open", lambda f, *a, **k: reads.append(f) or real_open(f, *a, **k))
    assert sessions.read_tail(str(q)) == ("a", "b")
    assert len(reads) == 1                                         # the tail was enough


def test_request_dir(sessions, home):
    root = home / "work_sessions"
    req = root / "2026" / "09" / "22" / "10-00-00_demo"
    (req / "src").mkdir(parents=True)
    (req / ".session.json").write_text("{}")
    bare = root / "2026" / "09" / "21" / "09-00-00_bare"
    (bare / "x").mkdir(parents=True)
    (root / "_audit").mkdir()
    (root / "_audit" / "session-folders.json").write_text(json.dumps({"assigned": str(req)}))
    assert sessions.request_dir(str(req / "src"), "s") == str(req)          # found above cwd
    assert sessions.request_dir(str(bare / "x"), "s") == str(bare)          # no .session.json
    assert sessions.request_dir(str(root), "s") is None                     # the root itself
    assert sessions.request_dir("/elsewhere/repo", "assigned") == str(req)  # assigned by hand
    assert sessions.request_dir("/elsewhere/repo", "s") is None


def test_json_output(sessions, home, monkeypatch, capsys):
    root = home / "work_sessions"
    req = root / "2026" / "09" / "22" / "10-00-00_demo"
    req.mkdir(parents=True)
    (req / ".session.json").write_text(json.dumps({
        "name": "demo work", "profile": "work", "ticket": "BTPA-1", "task_type": "security",
        "session_types": {"b": "permissions"}}))
    bare = root / "2026" / "09" / "21" / "09-00-00_bare"
    bare.mkdir(parents=True)
    (bare / ".session.json").write_text("not json")
    write_transcript(home, "a", [rec("user", "first", cwd=str(req)),
                                 rec("ai-title", aiTitle="Title A"),
                                 rec("last-prompt", lastPrompt="last A")], mtime=3_000)
    write_transcript(home, "b", [rec("user", "other", cwd=str(req))], mtime=2_000)
    write_transcript(home, "c", [rec("assistant", "x", cwd=str(bare))], mtime=1_500)
    write_transcript(home, "d", [rec("user", "root", cwd=str(root))], mtime=1_000)
    write_transcript(home, "gone", [rec("user", "x", cwd="/x")], mtime=500)
    monkeypatch.setattr(sessions, "read_tail",
                        lambda p, real=sessions.read_tail: (_ for _ in ()).throw(OSError)
                        if p.endswith("gone.jsonl") else real(p))

    data = json.loads(run_main(sessions, monkeypatch, capsys, "-a", "--json"))
    assert data["work_root"] == str(root)
    a, b, c, d, gone = data["sessions"]
    assert (a["id"], a["title"], a["first_prompt"], a["last_prompt"]) == ("a", "Title A", "first", "last A")
    assert a["request"] == {"path": str(req), "name": "demo work", "ticket": "BTPA-1",
                            "task_type": "security", "profile": "work"}
    assert b["request"]["task_type"] == "permissions"          # per-session override
    assert c["first_prompt"] is None
    assert c["request"] == {"path": str(bare), "name": "09-00-00_bare", "ticket": "",
                            "task_type": "", "profile": ""}
    assert d["request"] is None and d["in_work_root"] is True
    assert gone["in_work_root"] is False and gone["title"] is None
