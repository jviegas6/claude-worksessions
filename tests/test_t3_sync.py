"""bin/claude-t3-sync against a fake T3 Code: its database and a t3 stub that logs its calls."""

import json
import os
import sqlite3
import sys
import time

import pytest

from conftest import load_script

STUB = """#!/bin/sh
echo "$*" >> "{log}"
case "$1 $2" in
  "project add") [ -e "{exists}" ] && {{ echo "ERROR (#2): ProjectAlreadyExistsError: An active project already exists" >&2; exit 1; }} ;;
  "project remove") [ -e "{fail}" ] && {{ echo "ERROR (#2): ProjectLiveServerDeclaredResponseError: rejected" >&2; exit 1; }} ;;
esac
exit 0
"""


@pytest.fixture
def t3(home, monkeypatch):
    """A T3 home with an empty database and a t3 stub; returns a helper object."""
    t3home = home / ".t3"
    (t3home / "userdata").mkdir(parents=True)
    db = t3home / "userdata" / "statev2.sqlite"
    con = sqlite3.connect(str(db))
    con.execute("create table projection_projects (project_id text, title text, workspace_root text, "
                "created_at text, deleted_at text)")
    con.execute("create table orchestration_v2_projection_threads (thread_id text, project_id text, deleted_at text)")
    con.execute("create table orchestration_v2_projection_provider_threads (thread_id text, payload_json text, updated_at text)")
    con.commit()
    con.close()
    log, exists, fail = home / "t3.log", home / "t3.exists", home / "t3.fail"
    stub = home / "t3"
    stub.write_text(STUB.format(log=log, exists=exists, fail=fail))
    stub.chmod(0o755)
    monkeypatch.setenv("CWS_T3_BIN", str(stub))
    monkeypatch.setenv("CWS_T3_HOME", str(t3home))

    class T3:
        root = home / "work_sessions"

        def project(self, folder, title, threads=0, pid=None):
            pid = pid or "p-" + os.path.basename(str(folder))
            con = sqlite3.connect(str(db))
            con.execute("insert into projection_projects values (?, ?, ?, '', null)", (pid, title, str(folder)))
            for i in range(threads):
                con.execute("insert into orchestration_v2_projection_threads values (?, ?, null)", (pid + str(i), pid))
            con.commit()
            con.close()
            return pid

        def request(self, rel, meta, age_days=0):
            d = self.root / rel
            d.mkdir(parents=True)
            (d / ".session.json").write_text(json.dumps(meta))
            when = time.time() - age_days * 86400
            for p in (d / ".session.json", d):
                os.utime(str(p), (when, when))
            return d

        def thread(self, thread_id, session_id=None, deleted=False):
            con = sqlite3.connect(str(db))
            con.execute("insert into orchestration_v2_projection_threads values (?, 'p', ?)",
                        (thread_id, "2026-10-31" if deleted else None))
            payload = {"nativeThreadRef": {"driver": "claudeAgent", "nativeId": session_id}} if session_id else {}
            con.execute("insert into orchestration_v2_projection_provider_threads values (?, ?, '2026-10-30')",
                        (thread_id, json.dumps(payload)))
            con.commit()
            con.close()

        def server(self):
            (t3home / "userdata" / "environment-id").write_text("env-1\n")

        def calls(self):
            return log.read_text().splitlines() if log.exists() else []

        def already_exists(self):
            exists.write_text("")

        def failing_remove(self):
            fail.write_text("")

    return T3()


@pytest.fixture
def sync(t3):
    return load_script("claude-t3-sync")


def test_title_from_session_json(t3, sync):
    d = t3.request("2026/10/30/09-29-38_cost-schema", {"ticket": "PROJ-1", "name": "Cost schema"})
    assert sync.title(str(d)) == "PROJ-1 · 2026-10-30 · Cost schema"
    e = t3.request("2026/10/29/10-00-00_no-meta-name", {"ticket": "Other"})
    assert sync.title(str(e)) == "Other · 2026-10-29 · no-meta-name"


def test_plan_renames_request_projects_only(t3, sync, tmp_path):
    d = t3.request("2026/10/30/09-00-00_a", {"ticket": "PROJ-1", "name": "A"})
    t3.project(d, "09-00-00_a", threads=1)
    done = t3.request("2026/10/30/10-00-00_b", {"ticket": "Other", "name": "B"})
    t3.project(done, "Other · 2026-10-30 · B", threads=1)
    repo = tmp_path / "repo"
    repo.mkdir()
    t3.project(repo, "repo")
    t3.project(t3.root, "work_sessions")
    changes = sync.plan(14)
    assert [(c["action"], c["old"], c.get("new")) for c in changes] == [
        ("rename", "09-00-00_a", "PROJ-1 · 2026-10-30 · A")]


def test_plan_removes_only_empty_idle_projects_nobody_waits_on(t3, sync):
    idle = t3.request("2026/09/01/09-00-00_idle", {"ticket": "Other", "name": "idle"}, age_days=30)
    t3.project(idle, "Other · 2026-09-01 · idle")
    busy = t3.request("2026/09/02/09-00-00_busy", {"ticket": "Other", "name": "busy"}, age_days=30)
    t3.project(busy, "Other · 2026-09-02 · busy", threads=2)
    waits = t3.request("2026/09/03/09-00-00_waits", {"ticket": "Other", "name": "waits",
                                                     "waiting": {"on": "other", "who": "Ana"}}, age_days=30)
    t3.project(waits, "Other · 2026-09-03 · waits")
    recent = t3.request("2026/09/04/09-00-00_recent", {"ticket": "Other", "name": "recent"}, age_days=2)
    t3.project(recent, "Other · 2026-09-04 · recent")
    changes = sync.plan(14)
    assert [(c["action"], os.path.basename(c["path"])) for c in changes] == [("remove", "09-00-00_idle")]
    assert sync.plan(31) == []


def test_recent_transcript_keeps_a_project(t3, sync, home):
    d = t3.request("2026/09/01/09-00-00_talked", {"ticket": "Other", "name": "talked"}, age_days=30)
    t3.project(d, "Other · 2026-09-01 · talked")
    enc = "".join(ch if ch.isalnum() else "-" for ch in os.path.realpath(str(d)))
    tdir = home / ".claude-personal" / "projects" / enc
    tdir.mkdir(parents=True)
    (tdir / "s1.jsonl").write_text("{}\n")
    assert sync.plan(14) == []


def test_dry_run_calls_nothing_apply_logs_and_undo_restores(t3, sync, capsys):
    a = t3.request("2026/10/30/09-00-00_a", {"ticket": "PROJ-1", "name": "A"})
    pa = t3.project(a, "old a", threads=1)
    b = t3.request("2026/09/01/09-00-00_b", {"ticket": "Other", "name": "B"}, age_days=40)
    pb = t3.project(b, "old b")

    assert sync.main([]) == 0
    out = capsys.readouterr().out
    assert "1 rename(s), 1 removal(s)" in out
    assert t3.calls() == []

    assert sync.main(["--apply"]) == 0
    assert t3.calls() == ["project rename {} PROJ-1 · 2026-10-30 · A".format(pa),
                          "project remove {}".format(pb)]
    undo = list((t3.root / "_audit" / "t3").glob("sync-*.jsonl"))
    assert len(undo) == 1
    assert [json.loads(ln)["action"] for ln in undo[0].read_text().splitlines()] == ["rename", "remove"]

    assert sync.main(["--undo", str(undo[0])]) == 0
    assert t3.calls()[2:] == ["project add {} --title old b".format(b),
                              "project rename {} old a".format(a)]


def test_limit_and_failures(t3, sync, capsys):
    for i in range(3):
        d = t3.request("2026/09/0{}/09-00-00_x{}".format(i + 1, i), {"ticket": "Other", "name": "x"}, age_days=40)
        t3.project(d, "x")
    t3.failing_remove()
    assert sync.main(["--apply", "--limit", "2"]) == 1
    assert len(t3.calls()) == 2
    assert "failed: ERROR (#2): ProjectLiveServerDeclaredResponseError" in capsys.readouterr().err
    assert not list((t3.root / "_audit" / "t3").glob("*.jsonl"))   # nothing made, nothing to undo


def test_open_adds_with_title_then_opens(t3, sync):
    d = t3.request("2026/10/30/11-00-00_new", {"ticket": "PROJ-2", "name": "New"})
    sync.main(["--open", str(d)])
    real = os.path.realpath(str(d))
    assert t3.calls() == ["project add {} --title PROJ-2 · 2026-10-30 · New".format(real),
                          "app {}".format(real)]


def test_open_retitles_an_existing_project(t3, sync):
    d = t3.request("2026/10/30/11-00-00_old", {"ticket": "PROJ-3", "name": "Old"})
    t3.already_exists()
    sync.main(["--open", str(d)])
    real = os.path.realpath(str(d))
    assert t3.calls()[1:] == ["project rename {} PROJ-3 · 2026-10-30 · Old".format(real), "app {}".format(real)]


def test_unknown_database_stops_with_a_message(t3, sync, home):
    db = home / ".t3" / "userdata" / "statev2.sqlite"
    db.unlink()
    con = sqlite3.connect(str(db))
    con.execute("create table other (x)")
    con.commit()
    con.close()
    with pytest.raises(SystemExit) as e:
        sync.plan(14)
    assert "not what this version knows" in str(e.value)


def test_missing_t3_command(t3, sync, monkeypatch, home):
    monkeypatch.setitem(sync.CA.CONFIG, "CWS_T3_BIN", str(home / "nope"))
    monkeypatch.setattr(sync.shutil, "which", lambda name: None)
    monkeypatch.setattr(sync, "HOME", str(home / "elsewhere"))
    with pytest.raises(SystemExit) as e:
        sync.t3_bin()
    assert "t3 command not found" in str(e.value)


def test_no_database_yet(t3, sync, home):
    (home / ".t3" / "userdata" / "statev2.sqlite").unlink()
    with pytest.raises(SystemExit) as e:
        sync.plan(14)
    assert "open T3 Code once" in str(e.value)


def test_unreadable_session_json_still_gets_a_title(t3, sync):
    d = t3.request("2026/10/30/12-00-00_broken", {})
    (d / ".session.json").write_text("{not json")
    assert sync.title(str(d)) == "? · 2026-10-30 · broken"


@pytest.mark.parametrize("fail_on, message", [("project add", "could not add"), ("app", "could not open")])
def test_open_reports_what_failed(t3, sync, home, fail_on, message):
    d = t3.request("2026/10/30/13-00-00_x", {"ticket": "Other", "name": "x"})
    stub = home / "t3"
    stub.write_text('#!/bin/sh\ncase "$*" in "{}"*) echo "ERROR (#2): Boom" >&2; exit 1;; esac\nexit 0\n'.format(fail_on))
    with pytest.raises(SystemExit) as e:
        sync.main(["--open", str(d)])
    assert message in str(e.value) and "Boom" in str(e.value)


def test_nothing_to_do(t3, sync, capsys):
    d = t3.request("2026/10/30/14-00-00_ok", {"ticket": "Other", "name": "ok"})
    t3.project(d, "Other · 2026-10-30 · ok", threads=1)
    assert sync.main([]) == 0
    assert "already match" in capsys.readouterr().out


def test_thread_for_native_and_imported_sessions(t3, sync):
    t3.thread("th-1", session_id="sess-a")
    t3.thread("import:claudeAgent:sess-b")
    t3.thread("th-gone", session_id="sess-c", deleted=True)
    assert sync.thread_for("sess-a") == "th-1"
    assert sync.thread_for("sess-b") == "import:claudeAgent:sess-b"
    assert sync.thread_for("sess-c") is None and sync.thread_for("nope") is None


def test_open_thread_opens_its_link(t3, sync, monkeypatch, capsys):
    t3.thread("import:claudeAgent:sess-b")
    t3.server()
    opened = []
    monkeypatch.setattr(sync.subprocess, "run", lambda cmd, check: opened.append(cmd))
    assert sync.main(["--thread", "sess-b"]) == 0
    link = "t3code://threads/env-1/import%3AclaudeAgent%3Asess-b"
    assert opened == [[("open" if sys.platform == "darwin" else "xdg-open"), link]]
    assert link in capsys.readouterr().out


def test_open_thread_falls_back_to_the_project(t3, sync, capsys):
    d = t3.request("2026/10/30/15-00-00_q", {"ticket": "Other", "name": "q"})
    sync.main(["--thread", "sess-x", "--fallback", str(d)])
    real = os.path.realpath(str(d))
    assert t3.calls()[-1] == "app {}".format(real)
    assert "No T3 thread for session sess-x" in capsys.readouterr().out


def test_open_thread_without_a_thread_or_a_server(t3, sync, home):
    with pytest.raises(SystemExit, match="no T3 Code thread"):
        sync.open_thread("sess-x")
    t3.thread("th-1", session_id="sess-a")
    with pytest.raises(SystemExit, match="environment id not found"):
        sync.open_thread("sess-a")
    (home / ".t3" / "userdata" / "statev2.sqlite").unlink()
    assert sync.thread_for("sess-a") is None


def test_thread_for_unknown_database(t3, sync, home):
    db = home / ".t3" / "userdata" / "statev2.sqlite"
    db.unlink()
    con = sqlite3.connect(str(db))
    con.execute("create table other (x)")
    con.commit()
    con.close()
    with pytest.raises(SystemExit, match="not what this version knows"):
        sync.thread_for("sess-a")
