"""claude-search --suggest and what claude-new does with it."""

import datetime as dt
import json
import os
import shutil
import subprocess
import sys

import pytest

from conftest import REPO
from test_shell import run_new, run_new_tty

TODAY = dt.date(2026, 11, 11)


def jira(home, issues):
    p = home / "work_sessions" / "_audit" / "review" / "jira.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(issues))


def issue(key, summary, status="In Progress", mine=True):
    return {"key": key, "summary": summary, "status": status, "updated": "2026-11-01", "mine": mine}


def request(root, days_ago, name, ticket="Other", task_type="", goal=None):
    day = TODAY - dt.timedelta(days=days_ago)
    d = root / "{:%Y/%m/%d}".format(day) / ("10-00-00_" + name.replace(" ", "-"))
    d.mkdir(parents=True, exist_ok=True)
    (d / ".session.json").write_text(json.dumps(
        {"name": name, "goal": goal or name, "ticket": ticket, "task_type": task_type}))


def run_suggest(search, text):
    return search.suggest(text, today=TODAY)


def test_ticket_match_ranks_by_shared_terms(search, home):
    jira(home, [issue("BTPA-1", "Genesys ingestion backfill"), issue("BTPA-2", "Fabric mirror refresh"),
                issue("BTPA-3", "Ingestion of invoices")])
    got = run_suggest(search, "genesys ingestion")
    assert [c["key"] for c in got["tickets"]] == ["BTPA-1", "BTPA-3"]
    assert got["tickets"][0]["strong"] is True      # two shared terms, open
    assert got["tickets"][1]["strong"] is False     # one
    assert got["type"] is None


def test_done_ticket_and_not_mine_are_deprioritised(search, home):
    jira(home, [issue("A-1", "Brainlabs push", status="Done"),
                issue("A-2", "Brainlabs push", mine=False),
                issue("A-3", "Brainlabs push")])
    got = run_suggest(search, "brainlabs push")
    assert [c["key"] for c in got["tickets"]] == ["A-3", "A-2", "A-1"]
    assert got["tickets"][2]["strong"] is False     # closed never gives a hint


def test_max_three_and_ignored_tickets(search, home):
    jira(home, [issue("A-{}".format(i), "Brainlabs push") for i in range(1, 6)])
    ledger = home / "work_sessions" / "_audit" / "review" / "ledger.json"
    ledger.write_text(json.dumps({"ignore_tickets": ["A-1"]}))
    got = run_suggest(search, "brainlabs")
    assert [c["key"] for c in got["tickets"]] == ["A-2", "A-3", "A-4"]


def test_corrupt_ledger_is_ignored(search, home):
    jira(home, [issue("A-1", "Brainlabs push")])
    (home / "work_sessions" / "_audit" / "review" / "ledger.json").write_text("{nope")
    assert [c["key"] for c in run_suggest(search, "brainlabs")["tickets"]] == ["A-1"]


def test_recent_requests_boost_their_ticket(search, home):
    root = home / "work_sessions"
    jira(home, [issue("A-1", "Queue monitoring"), issue("A-2", "Queue monitoring")])
    assert [c["key"] for c in run_suggest(search, "queue")["tickets"]] == ["A-1", "A-2"]
    request(root, 10, "queue check", ticket="A-2")
    request(root, 200, "queue old", ticket="A-1")      # outside the window: no boost
    assert [c["key"] for c in run_suggest(search, "queue")["tickets"]] == ["A-2", "A-1"]


def test_no_overlap_gives_nothing(search, home):
    jira(home, [issue("A-1", "Fabric mirror")])
    request(home / "work_sessions", 5, "invoice export", task_type="tooling")
    assert run_suggest(search, "genesys whatsapp") == {"tickets": [], "type": None}
    assert run_suggest(search, "the of and") == {"tickets": [], "type": None}   # only stopwords


def test_missing_jira_is_empty(search, home):
    assert run_suggest(search, "anything here") == {"tickets": [], "type": None}


def filler(root, n=8):
    """Unrelated typed requests, so that the words under test are not 'common'."""
    for i in range(n):
        request(root, i + 1, "invoice export{}".format(i), task_type="tooling")


def test_type_is_the_weighted_majority_with_its_count(search, home):
    root = home / "work_sessions"
    filler(root)
    request(root, 3, "mirror refresh error", task_type="job errors")
    request(root, 4, "mirror capacity", task_type="job errors")
    request(root, 5, "mirror queue", task_type="job errors")
    request(root, 6, "mirror access", task_type="permissions")
    request(root, 7, "mirror untyped")                       # no type: no vote
    request(root, 120, "mirror ancient", task_type="tooling", goal="mirror")   # outside 90 days
    (root / "2026" / "11" / "bad" / "x").mkdir(parents=True)  # junk folders are skipped
    (root / "2026" / "11" / "bad" / "x" / ".session.json").write_text("[]")
    assert run_suggest(search, "mirror")["type"] == {"name": "job errors", "count": 3}


def test_type_needs_three_requests(search, home):
    root = home / "work_sessions"
    filler(root)
    request(root, 3, "mirror refresh error", task_type="job errors")
    request(root, 4, "mirror capacity", task_type="job errors")
    assert run_suggest(search, "mirror")["type"] is None


def test_type_needs_half_of_the_weighted_votes(search, home):
    root = home / "work_sessions"
    filler(root)
    for i, t in enumerate(["job errors"] * 3 + ["permissions"] * 3 + ["security"] * 3):
        request(root, i + 2, "mirror v{}".format(i), task_type=t)
    assert run_suggest(search, "mirror")["type"] is None     # 3 requests, but only a third of the votes


def test_type_ignores_words_every_request_has(search, home):
    root = home / "work_sessions"
    for i in range(6):
        request(root, i + 1, "check thing{}".format(i), task_type="investigation")
    for i in range(3):
        request(root, i + 8, "check grant{}".format(i), task_type="permissions", goal="grant")
    # "check" is in 9 of 9 requests (even in a small corpus): it says nothing; "grant" decides
    assert run_suggest(search, "check grant")["type"] == {"name": "permissions", "count": 3}


def test_cli_text_and_json(search, home, monkeypatch, capsys):
    jira(home, [issue("A-1", "Brainlabs push", mine=False)])
    filler(home / "work_sessions")
    for i in range(3):
        request(home / "work_sessions", 20 + i, "brainlabs{}".format(i), task_type="job errors", goal="brainlabs")
    real = search.suggest
    monkeypatch.setattr(search, "suggest", lambda text: real(text, today=TODAY))
    monkeypatch.setattr(sys, "argv", ["claude-search", "--suggest", "brainlabs"])
    search.main()
    out = capsys.readouterr().out
    assert "ticket  A-1  Brainlabs push  [In Progress] (not mine)" in out
    assert "type    job errors  (3 similar requests)" in out
    monkeypatch.setattr(sys, "argv", ["claude-search", "--suggest", "--json", "brainlabs"])
    search.main()
    assert json.loads(capsys.readouterr().out)["tickets"][0]["key"] == "A-1"


def test_cli_singular_and_empty(search, home, monkeypatch, capsys):
    monkeypatch.setattr(search, "suggest", lambda text: {"tickets": [], "type": {"name": "tooling", "count": 1}})
    monkeypatch.setattr(sys, "argv", ["claude-search", "--suggest", "mirror"])
    search.main()
    assert "(1 similar request)" in capsys.readouterr().out
    monkeypatch.undo()
    monkeypatch.setattr(sys, "argv", ["claude-search", "--suggest", "zzz"])
    search.main()
    assert capsys.readouterr().out == ""


def test_query_still_required_without_suggest(search, home, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["claude-search"])
    with pytest.raises(SystemExit) as exc:
        search.main()
    assert exc.value.code == 2


def test_script_runs_end_to_end(tmp_path):
    root = tmp_path / "work"
    jira_dir = root / "_audit" / "review"
    jira_dir.mkdir(parents=True)
    (jira_dir / "jira.json").write_text(json.dumps([issue("BTPA-9", "Genesys ingestion backfill")]))
    env = dict(os.environ, HOME=str(tmp_path), CWS_CONFIG=os.devnull, CLAUDE_WORK_ROOT=str(root))
    r = subprocess.run([sys.executable, os.path.join(REPO, "bin", "claude-search"), "--suggest", "--json",
                        "genesys ingestion"], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert json.loads(r.stdout)["tickets"][0]["key"] == "BTPA-9"


# ---------------------------------------------------------------- claude-new

pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")


def seed(root, weak=False):
    (root / "_audit" / "review").mkdir(parents=True)
    issues = [issue("BTPA-9", "Genesys ingestion backfill"), issue("BTPA-5", "Genesys api", mine=False)]
    if weak:
        issues = [issue("BTPA-7", "Genesys api")]       # one shared word with "genesys ingestion"
    (root / "_audit" / "review" / "jira.json").write_text(json.dumps(issues))
    day = dt.date.today() - dt.timedelta(days=3)
    names = [("genesys load", t) for t in ["job errors", "job errors", "job errors", "permissions"]]
    names += [("invoice export {}".format(i), "tooling") for i in range(8)]
    for i, (n, t) in enumerate(names):
        d = root / "{:%Y/%m/%d}".format(day) / "10-00-{:02d}_{}".format(i, n.replace(" ", "-"))
        d.mkdir(parents=True)
        (d / ".session.json").write_text(json.dumps({"name": n, "goal": n, "ticket": "Other", "task_type": t}))


def created(root):
    metas = sorted(root.glob("[0-9]*/*/*/*/.session.json"), key=lambda p: p.parent.name)
    return [json.loads(m.read_text()) for m in metas if m.parent.name[9:].startswith(("genesys-ingestion", "zzz", "backfill"))]


def test_enter_takes_the_suggested_ticket_and_type(tmp_path):
    seed(tmp_path)
    r = run_new_tty(tmp_path, "-n genesys ingestion", "\n\n")
    assert r.returncode == 0, r.stderr
    assert "1) BTPA-9  Genesys ingestion backfill  [In Progress]" in r.stdout
    assert "Suggested: job errors (3 similar requests)" in r.stdout
    meta = created(tmp_path)[0]
    assert (meta["ticket"], meta["task_type"]) == ("BTPA-9", "job errors")


def test_enter_means_other_when_the_top_candidate_is_weak(tmp_path):
    seed(tmp_path, weak=True)
    r = run_new_tty(tmp_path, "-n genesys ingestion", "\n\n")
    assert r.returncode == 0, r.stderr
    assert "1) BTPA-7  Genesys api" in r.stdout and "Jira ticket [Other]" in r.stderr
    assert created(tmp_path)[0]["ticket"] == "Other"
    r = run_new_tty(tmp_path, "-n --new genesys ingestion", "1\n\n")      # a number still picks it
    assert [m["ticket"] for m in created(tmp_path)].count("BTPA-7") == 1


def test_number_other_and_own_words_still_work(tmp_path):
    seed(tmp_path)
    r = run_new_tty(tmp_path, "-n genesys ingestion", "2\ntooling\n")
    assert r.returncode == 0, r.stderr
    meta = created(tmp_path)[0]
    assert (meta["ticket"], meta["task_type"]) == ("BTPA-5", "tooling")
    r = run_new_tty(tmp_path, "-n --new genesys ingestion", "Other\n-\n")
    assert r.returncode == 0, r.stderr
    meta = [m for m in created(tmp_path) if m["ticket"] == "Other"][0]
    assert meta["task_type"] == ""


def test_no_candidates_keeps_the_old_prompt(tmp_path):
    r = run_new_tty(tmp_path, "-n zzz unrelated", "Other\ntooling\n")
    assert r.returncode == 0, r.stderr
    assert "Ticket candidates" not in r.stdout and "Suggested" not in r.stdout
    assert created(tmp_path)[0]["ticket"] == "Other"


def test_explicit_other_gets_a_hint_and_never_blocks(tmp_path):
    seed(tmp_path)
    r = run_new(tmp_path, "-t Other -T tooling genesys ingestion")
    assert r.returncode == 0, r.stderr
    assert r.stderr.count("hint: maybe BTPA-9 — Genesys ingestion backfill") == 1
    assert created(tmp_path)[0]["ticket"] == "Other"


def test_weak_candidate_gives_no_hint(tmp_path):
    seed(tmp_path)
    r = run_new(tmp_path, "-t Other -T tooling backfill")
    assert r.returncode == 0, r.stderr
    assert "hint:" not in r.stderr


def test_real_ticket_given_runs_no_suggestion(tmp_path):
    seed(tmp_path)
    r = run_new(tmp_path, "-t ABC-1 -T tooling genesys ingestion")
    assert r.returncode == 0, r.stderr
    assert "hint:" not in r.stderr
