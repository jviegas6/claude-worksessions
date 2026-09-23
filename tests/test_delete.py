"""claude-delete and the value check behind it (claude-sessions --json)."""

import io
import json
import os
import sys
import time

import pytest

from test_sessions import rec, tool, write_transcript


def request(home, name, meta=None, files=()):
    d = home / "work_sessions" / "2026" / "09" / "23" / ("10-00-00_" + name)
    d.mkdir(parents=True)
    (d / ".session.json").write_text(json.dumps(meta or {"name": name}))
    for f in files:
        (d / f).parent.mkdir(parents=True, exist_ok=True)
        (d / f).write_text("x")
    return d


def old(p, secs=3600):
    t = time.time() - secs
    os.utime(p, (t, t))
    return p


@pytest.fixture
def world(home, monkeypatch, tmp_path):
    """Sessions of every kind, all older than two minutes unless said."""
    monkeypatch.setenv("CWS_CACHE_DIR", str(tmp_path / "cache"))
    root = home / "work_sessions"
    empty = request(home, "empty-test", {"name": "empty test", "audit": False})
    quiet = request(home, "quiet", {"name": "quiet"})
    made = request(home, "made-files", {"name": "made files"}, files=["out.md"])
    shared = request(home, "shared", {"name": "shared"}, files=["notes.md"])
    skipped = request(home, "skipped", {"name": "skipped", "audit": False}, files=["kept.md"])
    ws = {
        "empty": old(write_transcript(home, "empty-1", [rec("user", "try", cwd=str(empty))], project="p1")),
        "quiet": old(write_transcript(home, "quiet-1", [rec("user", "look", cwd=str(quiet))], project="p2")),
        "made": old(write_transcript(home, "made-1", [rec("user", "make", cwd=str(made)),
                                                      tool("Write", file_path=str(made / "out.md"))], project="p3")),
        "shared-a": old(write_transcript(home, "shared-a", [rec("user", "a", cwd=str(shared)),
                                                            tool("Write", file_path=str(shared / "notes.md"))], project="p4")),
        "shared-b": old(write_transcript(home, "shared-b", [rec("user", "b", cwd=str(shared))], project="p4")),
        "skipped": old(write_transcript(home, "skipped-1", [rec("user", "s", cwd=str(skipped)),
                                                            tool("Write", file_path=str(skipped / "kept.md"))], project="p5")),
        "booked": old(write_transcript(home, "booked-1", [rec("user", "b", cwd=str(quiet))], project="p2")),
        "listed": old(write_transcript(home, "listed-1", [rec("user", "root", cwd=str(root))], project="p6")),
        "live": write_transcript(home, "live-1", [rec("user", "now", cwd=str(quiet))], project="p2"),
    }
    (root / "_audit" / "review").mkdir(parents=True)
    (root / "_audit" / "review" / "ledger.json").write_text(json.dumps({"x": ["booked-1"]}))
    (root / "_audit" / "no-audit.txt").write_text("listed-1  # a root session\n")
    return {"root": root, "empty": empty, "quiet": quiet, "made": made, "shared": shared, "skipped": skipped, "t": ws}


def verdicts(sessions):
    return {e["id"]: e["deletable"] for e in sessions.as_json(sessions.sessions())["sessions"]}


def test_value_check(sessions, world):
    v = verdicts(sessions)
    assert v["empty-1"] == {"ok": True, "why": ["no artifacts", "kept out of the review (-n)"], "blocked": []}
    assert v["quiet-1"]["ok"] and v["quiet-1"]["why"] == ["no artifacts"]              # audited, no files
    assert v["made-1"] == {"ok": False, "why": [], "blocked": ["it has artifacts and counts in the review"]}
    assert v["shared-a"]["ok"] is False                                                 # wrote notes.md
    assert v["shared-b"]["ok"] is True       # folder has files, but a sibling made them; b made none
    assert v["skipped-1"] == {"ok": True, "why": ["kept out of the review (-n)"], "blocked": []}
    assert v["booked-1"]["blocked"] == ["booked in the weekly review"] and not v["booked-1"]["ok"]
    assert v["listed-1"]["why"] == ["no artifacts", "kept out of the review (-n)"]      # no-audit.txt
    assert v["live-1"]["blocked"] == ["active in the last two minutes"]


def test_value_check_without_a_ledger(sessions, world):
    os.remove(world["root"] / "_audit" / "review" / "ledger.json")
    assert verdicts(sessions)["booked-1"]["ok"] is True


def test_find(deleter, world):
    e, entries = deleter.find("empty")
    assert e["id"] == "empty-1" and len(entries) == 9
    with pytest.raises(SystemExit, match="no session 'zzz'"):
        deleter.find("zzz")
    with pytest.raises(SystemExit, match="matches 2 sessions"):
        deleter.find("shared")
    with pytest.raises(SystemExit, match="no session ''"):
        deleter.find("")


def test_impact_lines(deleter, world, home):
    e, entries = deleter.find("empty-1")
    lines = deleter.impact(e, entries)
    assert lines[0].startswith("The conversation goes")
    assert "already kept out of the review" in lines[1]
    assert "left no files" in lines[2]
    assert "2026/09/23/10-00-00_empty-test is left empty, so it goes too" in lines[3]
    assert "deleted-sessions bin" in lines[4] and "restored" in lines[4]
    e, entries = deleter.find("quiet-1")
    assert "its time leaves claude-audit" in deleter.impact(e, entries)[1]
    assert not any("goes too" in ln for ln in deleter.impact(e, entries))   # other sessions use it
    e, entries = deleter.find("skipped-1")
    assert "1 file(s) it produced stay where they are, no longer linked to any session: kept.md" in deleter.impact(e, entries)[2]


def test_impact_lists_at_most_six_files_and_outside_paths(deleter, world, home):
    e, entries = deleter.find("skipped-1")
    e = dict(e, artifacts=[str(world["skipped"] / "f{}.md".format(i)) for i in range(8)] + [str(home / "else.py")])
    line = deleter.impact(e, entries)[2]
    assert line.startswith("9 file(s)") and "f5.md and 3 more" in line
    e = dict(e, request=None, artifacts=[str(home / "else.py")])
    assert "~/else.py" in deleter.impact(e, entries)[2]


def test_empty_request_only_inside_the_work_root(deleter, world, home):
    e, entries = deleter.find("empty-1")
    assert deleter.empty_request(e, entries) == str(world["empty"])
    outside = dict(e, request=dict(e["request"], path=str(home / "elsewhere")))
    assert deleter.empty_request(outside, entries) is None
    root = dict(e, request=dict(e["request"], path=str(world["root"])))
    assert deleter.empty_request(root, entries) is None
    assert deleter.empty_request(dict(e, request=None), entries) is None


def test_leftovers_delete_into_the_bin_and_restore(deleter, world, home, monkeypatch, tmp_path):
    monkeypatch.setenv("CWS_TRASH_DIR", str(tmp_path / "bin"))
    cfg = home / ".claude-personal"
    for extra in ["projects/p1/empty-1", "file-history/empty-1", "session-env/empty-1"]:
        (cfg / extra).mkdir(parents=True)
    (cfg / "file-history" / "empty-1" / "v1").write_text("history")
    old(write_transcript(home, "empty-1", [rec("user", "copy", cwd=str(world["empty"]))], project="old-copy"), 7200)
    (home / ".claude-work").mkdir()
    os.symlink(cfg / "projects", home / ".claude-work" / "projects")        # shared: listed once
    found = deleter.leftovers("empty-1")
    assert sorted(os.path.relpath(p, cfg) for p in found) == sorted([
        "file-history/empty-1", "projects/old-copy/empty-1.jsonl", "projects/p1/empty-1",
        "projects/p1/empty-1.jsonl", "session-env/empty-1"])
    (world["root"] / "_config").mkdir()
    (world["root"] / "_config" / "pinned.json").write_text(json.dumps({"sessions": {"empty-1": 1, "x": 2}, "requests": {}}))
    before = {p: open(p).read() if os.path.isfile(p) else None for p in found}

    e, entries = deleter.find("empty-1")
    where = deleter.delete(e, entries)
    assert os.path.dirname(where) == str(tmp_path / "bin") and where.endswith("_empty-1")
    assert not world["empty"].exists() and deleter.leftovers("empty-1") == []
    assert json.loads((world["root"] / "_config" / "pinned.json").read_text())["sessions"] == {"x": 2}
    (m,) = deleter.deleted()
    assert (m["id"], m["title"], m["request"], m["request_path"], m["dir"]) == (
        "empty-1", "try", "empty test", str(world["empty"]), where)
    assert sorted(it["from"] for it in m["items"]) == sorted(found + [str(world["empty"])])
    assert len(os.listdir(os.path.join(where, "items"))) == 6

    # restore: every piece back, bin entry gone
    deleter.restore(deleter.find_deleted("empty"))
    assert world["empty"].is_dir() and (world["empty"] / ".session.json").exists()
    assert {p: open(p).read() if os.path.isfile(p) else None for p in found} == before
    assert (cfg / "file-history" / "empty-1" / "v1").read_text() == "history"
    assert deleter.deleted() == [] and os.listdir(tmp_path / "bin") == []


def test_restore_refuses_when_a_place_is_taken(deleter, world, monkeypatch, tmp_path):
    monkeypatch.setenv("CWS_TRASH_DIR", str(tmp_path / "bin"))
    e, entries = deleter.find("quiet-1")
    deleter.delete(e, entries)
    write_transcript(world["root"].parent, "quiet-1", [rec("user", "new")], project="p2")   # something is back there
    with pytest.raises(SystemExit, match="can't restore, already there: .*quiet-1.jsonl"):
        deleter.restore(deleter.find_deleted("quiet-1"))
    assert len(deleter.deleted()) == 1                                                      # nothing moved


def test_bin_listing_lookup_and_purge(deleter, world, monkeypatch, tmp_path):
    monkeypatch.setenv("CWS_TRASH_DIR", str(tmp_path / "bin"))
    assert deleter.deleted() == []                                                          # no bin yet
    for sid in ("quiet-1", "empty-1"):
        e, entries = deleter.find(sid)
        deleter.delete(e, entries)
    (tmp_path / "bin" / "junk").mkdir()                                                     # no manifest
    (tmp_path / "bin" / "bad").mkdir()
    (tmp_path / "bin" / "bad" / "manifest.json").write_text("[1]")
    assert [m["id"] for m in deleter.deleted()] == ["empty-1", "quiet-1"]                   # newest first
    with pytest.raises(SystemExit, match="no deleted session 'zzz'"):
        deleter.find_deleted("zzz")
    with pytest.raises(SystemExit, match="no deleted session ''"):
        deleter.find_deleted("")
    for sid in ("shared-a", "shared-b"):                    # two entries sharing a prefix
        deleter.put_in_bin(deleter.find(sid)[0], [])
    with pytest.raises(SystemExit, match="matches 2 deleted sessions"):
        deleter.find_deleted("shared")
    deleter.purge(deleter.find_deleted("quiet"))
    assert "quiet-1" not in [m["id"] for m in deleter.deleted()]
    monkeypatch.delenv("CWS_TRASH_DIR")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "xdg"))
    assert deleter.bin_dir() == str(tmp_path / "xdg" / "claude-worksessions" / "trash")


def test_bin_folder_names_never_clash(deleter, world, monkeypatch, tmp_path):
    monkeypatch.setenv("CWS_TRASH_DIR", str(tmp_path / "bin"))
    monkeypatch.setattr(deleter.time, "strftime", lambda f: "20260923-120000")
    e, entries = deleter.find("quiet-1")
    a = deleter.put_in_bin(e, [])
    b = deleter.put_in_bin(e, [])
    assert a != b and os.path.basename(b).startswith("20260923-120000_quiet-1-")


def test_unpin_is_quiet_without_pins(deleter, world):
    assert deleter.unpin("nope") is False                                           # no file
    (world["root"] / "_config").mkdir()
    (world["root"] / "_config" / "pinned.json").write_text("{bad")
    assert deleter.unpin("nope") is False
    (world["root"] / "_config" / "pinned.json").write_text(json.dumps({"sessions": {}}))
    assert deleter.unpin("nope") is False


def run(deleter, monkeypatch, capsys, *argv, stdin=None, tty=False):
    if stdin is not None:
        monkeypatch.setattr(sys, "stdin", io.StringIO(stdin))
    monkeypatch.setattr(sys.stdin, "isatty", lambda: tty, raising=False)
    rc = deleter.main(list(argv))
    return rc, capsys.readouterr().out


def test_cli(deleter, world, home, monkeypatch, capsys, tmp_path):
    monkeypatch.setenv("CWS_TRASH_DIR", str(tmp_path / "bin"))
    rc, out = run(deleter, monkeypatch, capsys, "made-1", stdin="")
    assert rc == 1 and "Can't delete it: it has artifacts and counts in the review." in out
    rc, out = run(deleter, monkeypatch, capsys, "quiet-1", "--check", stdin="")
    assert rc == 0 and "It may go: no artifacts." in out and "its time leaves" in out
    rc, out = run(deleter, monkeypatch, capsys, "quiet-1", "--json", stdin="")
    d = json.loads(out)
    assert rc == 0 and d["deletable"] and d["request"] == "quiet" and d["folder"] is None
    rc, out = run(deleter, monkeypatch, capsys, "made-1", "--json", stdin="")
    assert rc == 1 and json.loads(out)["blocked"]
    rc, out = run(deleter, monkeypatch, capsys, "listed-1", "--json", stdin="")
    assert json.loads(out)["request"] is None
    rc, out = run(deleter, monkeypatch, capsys, "quiet-1", stdin="")               # no terminal, no --yes
    assert rc == 1 and "run with --yes" in out
    rc, out = run(deleter, monkeypatch, capsys, "quiet-1", stdin="n\n", tty=True)
    assert rc == 1 and "Not deleted." in out
    rc, out = run(deleter, monkeypatch, capsys, "quiet-1", stdin="y\n", tty=True)
    assert rc == 0 and "Moved to the bin. Undo: claude-delete --restore quiet-1" in out
    rc, out = run(deleter, monkeypatch, capsys, "empty-1", "--yes", stdin="")
    assert rc == 0 and not world["empty"].exists()

    rc, out = run(deleter, monkeypatch, capsys, "--list", stdin="")
    assert rc == 0 and "empty-1  try  (empty test, deleted" in out and "2 deleted session(s)" in out
    rc, out = run(deleter, monkeypatch, capsys, "--list", "--json", stdin="")
    assert [m["id"] for m in json.loads(out)] == ["empty-1", "quiet-1"]
    rc, out = run(deleter, monkeypatch, capsys, "--restore", "empty", stdin="")
    assert rc == 0 and "Restored empty-1  try (2 item(s) put back)." in out and world["empty"].exists()
    rc, out = run(deleter, monkeypatch, capsys, "--purge", "quiet", stdin="")      # no terminal
    assert rc == 1 and "Not deleted." in out
    rc, out = run(deleter, monkeypatch, capsys, "--purge", "quiet", stdin="y\n", tty=True)
    assert rc == 0 and "Deleted for good: 1 session(s)." in out
    rc, out = run(deleter, monkeypatch, capsys, "--empty", "--yes", stdin="")
    assert rc == 0 and "The bin is empty." in out
    for sid in ("listed-1", "empty-1"):
        run(deleter, monkeypatch, capsys, sid, "--yes", stdin="")
    rc, out = run(deleter, monkeypatch, capsys, "--empty", "--yes", stdin="")
    assert rc == 0 and "Deleted for good: 2 session(s)." in out
    rc, out = run(deleter, monkeypatch, capsys, "--list", stdin="")
    assert "0 deleted session(s)" in out
    with pytest.raises(SystemExit):
        run(deleter, monkeypatch, capsys, stdin="")                                 # nothing to do


def test_load_sessions_falls_back_to_local_bin(deleter, home, monkeypatch):
    real = os.path.join(os.path.dirname(deleter.__spec__.loader.path), "claude-sessions")
    local = home / ".local" / "bin"
    local.mkdir(parents=True)
    os.symlink(real, local / "claude-sessions")
    isfile = os.path.isfile
    monkeypatch.setattr(os.path, "isfile", lambda p: False if p == real else isfile(p))
    assert deleter.load_sessions().__spec__.loader.path == str(local / "claude-sessions")


def test_running_sessions_from_records_and_command_lines(sessions, home, monkeypatch):
    d = home / ".claude-personal" / "sessions"
    d.mkdir(parents=True)
    (d / "1.json").write_text(json.dumps({"pid": os.getpid(), "sessionId": "open-rec"}))
    (d / "2.json").write_text(json.dumps({"pid": 999999999, "sessionId": "dead-rec"}))
    (d / "3.json").write_text("{bad")
    (d / "4.json").write_text(json.dumps({"sessionId": "no-pid"}))
    (d / "5.key").write_text("x")
    uid = "b39404a5-300c-45e8-908b-86e1966e8f7e"
    other = "11111111-2222-3333-4444-555555555555"
    ps = "\n".join([
        "  101 claude --resume {}".format(uid),                                        # the Claude CLI
        "  102 /Users/x/.local/share/claude/versions/2.1.281 --resume " + other,        # by its real path
        "  103 python3 /Users/x/.local/bin/claude-delete {} --json".format(uid.replace("b3", "c3")),
        "  104 vim " + other.replace("1", "9"),
        "  {} python3 claude-delete {}".format(os.getpid(), uid.replace("b3", "d3")),   # this very check
        "  nonsense line",
    ])
    monkeypatch.setattr(sessions.subprocess, "run", lambda *a, **k: type("R", (), {"stdout": ps})())
    assert sessions.running_sessions() == {"open-rec", uid, other}
    monkeypatch.setattr(sessions.subprocess, "run", lambda *a, **k: (_ for _ in ()).throw(OSError()))
    assert sessions.running_sessions() == {"open-rec"}


def test_alive(sessions, monkeypatch):
    assert sessions.alive(os.getpid()) and not sessions.alive(999999999)
    monkeypatch.setattr(sessions.os, "kill", lambda p, s: (_ for _ in ()).throw(PermissionError()))
    assert sessions.alive(1)


def test_open_session_is_blocked_even_when_idle(sessions, world, monkeypatch):
    monkeypatch.setattr(sessions, "running_sessions", lambda: {"quiet-1"})
    v = verdicts(sessions)
    assert v["quiet-1"] == {"ok": False, "why": ["no artifacts"], "blocked": ["open in a running Claude session"]}
