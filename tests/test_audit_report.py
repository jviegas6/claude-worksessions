"""claude-audit views: summary, detail, reconcile, by-type, sessions, propose/apply, CSV and --copy.

Most tests build a small week under a throwaway HOME -- Claude transcripts, a
request folder with .session.json, an activity day file, a ledger and a Jira
cache -- and drive main() the way the command line does. The clock is pinned to
UTC so wall-clock times in the fixtures read the same everywhere.
"""

import csv
import datetime as dt
import json
import os
import subprocess
import sys
import time
import types

import pytest

from conftest import load_script

WEEK = "2026-09-07"            # a Monday
SID_PIPE = "aaaaaaaa-0000-0000-0000-000000000001"
SID_PERM = "aaaaaaaa-0000-0000-0000-000000000002"
SID_TINY = "aaaaaaaa-0000-0000-0000-000000000003"
SID_ROOT = "aaaaaaaa-0000-0000-0000-000000000004"
SID_HIDDEN = "aaaaaaaa-0000-0000-0000-000000000005"


@pytest.fixture
def utc(monkeypatch):
    monkeypatch.setenv("TZ", "UTC")
    time.tzset()
    yield
    monkeypatch.undo()
    time.tzset()


@pytest.fixture
def mod(home, utc):
    return load_script("claude-audit")


# ---------------------------------------------------------------- fixture builders

def stamp(day, hh, mm, ss=0):
    return "2026-09-{:02d}T{:02d}:{:02d}:{:02d}Z".format(day, hh, mm, ss)


def write_transcript(home, sid, cwd, day, start_h, minutes, title=None, prompt="do the thing",
                     cost=None, profile="personal"):
    """A session with a prompt every 10 minutes and activity every minute."""
    d = home / ".claude-{}".format(profile) / "projects" / "proj"
    d.mkdir(parents=True, exist_ok=True)
    recs = []
    for m in range(minutes + 1):
        hh, mm = start_h + m // 60, m % 60
        rec = {"timestamp": stamp(day, hh, mm), "cwd": cwd, "gitBranch": "main", "version": "2.0",
               "promptId": "p{}".format(m // 10)}
        if m % 10 == 0:
            rec.update(type="user", message={"content": prompt if m == 0 else "and then {}".format(m)})
        else:
            rec["type"] = "assistant"
        recs.append(rec)
    if title:
        recs.append({"type": "ai-title", "aiTitle": title})
    if cost:
        recs.append(dict(cost, type="cost-state"))
    (d / (sid + ".jsonl")).write_text("\n".join(json.dumps(r) for r in recs) + "\n")


def request_folder(root, name, **meta):
    d = root / "2026" / "09" / "07" / name
    d.mkdir(parents=True, exist_ok=True)
    (d / ".session.json").write_text(json.dumps(dict({"name": name, "profile": "work"}, **meta)))
    return str(d)


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data))
    return path


LEDGER = {
    "default_task": "BI Migration",
    "leave_task": "Annual Leave",
    "jira_prefixes": ["BTPA"],
    "tasks": [
        {"task": "Data Platform", "tickets": ["BTPA-1"], "default_ticket": "BTPA-1",
         "keywords": ["ingestion", "pipeline"], "comments": {"BTPA-1": "Keep ingestion running"}},
        {"task": "BI Migration", "tickets": ["BTPA-9"], "default_ticket": "BTPA-9",
         "keywords": ["migration", "report"]},
        {"task": "Security", "tickets": ["BTPA-2"], "keywords": ["storage", "access"]},
    ],
}

JIRA = [
    {"key": "BTPA-1", "summary": "Ingestion pipeline failures", "status": "In Progress", "mine": True,
     "updated": "2026-09-08T10:00:00+0000"},
    {"key": "BTPA-2", "summary": "Grant storage access", "status": "Done", "mine": True,
     "updated": "2026-09-08T09:10:00Z"},
    {"key": "BTPA-5", "summary": "Quarterly vendor invoices", "status": "To Do", "mine": True,
     "updated": "2026-09-09T12:00:00Z"},
    {"key": "BTPA-6", "summary": "Ingestion pipeline subtask", "status": "Done", "mine": True,
     "updated": "2026-09-09T12:00:00Z"},
    {"key": "BTPA-7", "summary": "Somebody else's", "status": "To Do", "mine": False,
     "updated": "2026-09-09T12:00:00Z"},
    {"key": "BTPA-8", "summary": "bad stamp", "mine": True, "updated": "not a date"},
    {"key": "BTPA-9", "summary": "BI reports", "mine": True, "updated": ""},
]

ACTIVITY = {
    "events": [
        {"source": "meeting", "start": "2026-09-07T11:00:00", "end": "2026-09-07T11:30:00",
         "title": "Pipeline review BTPA-1", "counterparties": ["a@x.com"], "subject": "Pipeline fix"},
        {"source": "email", "start": "2026-09-07T12:00:00", "title": "RE: Pipeline review",
         "counterparties": "a@x.com", "subject": "Pipeline fix"},
        {"source": "meeting", "start": "2026-09-08T10:00:00", "end": "2026-09-08T10:30:00",
         "title": "Daily stand-up", "detail": "organiser: Jane"},
        {"source": "chat", "start": "2026-09-08T15:00:00", "end": "2026-09-08T15:20:00",
         "title": "Architecture design options chat"},
        {"source": "email", "start": "2026-09-09T09:00:00", "title": "Hypercare after go-live"},
        {"source": "email", "start": "2026-09-09T09:05:00", "title": "Hypercare after go-live"},
        {"source": "personal", "start": "2026-09-08T12:00:00", "end": "2026-09-08T13:00:00",
         "title": "Lunch"},
        {"source": "notice", "start": "2026-09-08T16:00:00", "end": "2026-09-08T17:00:00",
         "title": "Change window"},
        {"source": "leave", "start": "2026-09-11T00:00:00", "end": "2026-09-12T00:00:00",
         "title": "Out of office"},
        {"source": "leave", "start": "2026-09-10T13:00:00", "end": "2026-09-10T17:00:00",
         "title": "Half day"},
    ],
    "subjects": {SID_PIPE: "Pipeline fix"},
}


@pytest.fixture
def world(home, utc):
    """A worked week; returns a namespace with the paths the tests poke at."""
    root = home / "work_sessions"
    pipe = request_folder(root, "09-00-00_pipeline-fix", ticket="BTPA-1", task_type="job errors",
                          session_types={SID_PIPE: "job errors"})
    perm = request_folder(root, "10-00-00_storage-access", ticket="Other", task_type="permissions")
    hidden = request_folder(root, "11-00-00_private", ticket="Other", audit=False)
    write_transcript(home, SID_PIPE, pipe, 7, 9, 90, title="Fix failed ingestion pipeline",
                     cost={"totalCostUSD": 1.23456, "totalLinesAdded": 12, "totalLinesRemoved": 3,
                           "modelUsage": {"claude-opus-5": {}}})
    write_transcript(home, SID_PERM, perm, 8, 9, 40, title="Grant storage access to the team",
                     profile="work")
    write_transcript(home, SID_TINY, str(root), 9, 14, 3, prompt="quick unrelated note")
    write_transcript(home, SID_ROOT, str(root), 9, 16, 30, title="Migration of BI reports")
    write_transcript(home, SID_HIDDEN, hidden, 9, 8, 30, title="Private thing")
    audit_dir = root / "_audit"
    write_json(audit_dir / "activity" / (WEEK + ".json"), ACTIVITY)
    write_json(audit_dir / "review" / "ledger.json", LEDGER)
    write_json(audit_dir / "review" / "jira.json", JIRA)
    return types.SimpleNamespace(home=home, root=root, audit_dir=audit_dir,
                                 ledger=audit_dir / "review" / "ledger.json")


def run(mod, *argv):
    old = sys.argv
    sys.argv = ["claude-audit"] + list(argv)
    try:
        mod.main()
    finally:
        sys.argv = old


def args_for(mod, **kw):
    base = dict(day=None, week=None, month=None, start=None, end=None, min_subject=10.0,
                util_step=10, round_to=30.0, ledger=None, activity=mod.ACTIVITY_DIR)
    base.update(kw)
    return types.SimpleNamespace(**base)


# ---------------------------------------------------------------- pure helpers

def test_allocate_sums_exactly_and_never_zeroes_worked_rows(mod):
    assert mod.allocate([3, 1, 0], 100, 10) == [80, 20, 0]
    got = mod.allocate([100, 1, 1, 1], 100, 10)
    assert sum(got) == 100 and min(got[:4]) >= 10
    assert mod.allocate([1, 1], 0, 10) == [0, 0]
    assert mod.allocate([0, 0], 100, 10) == [0, 0]
    # more live rows than steps: plain largest remainder, some rows get nothing
    got = mod.allocate([5, 4, 3, 2, 1], 30, 10)
    assert sum(got) == 30 and got[0] == 10 and got[-1] == 0
    # exactly one step each, nothing left to spread
    assert mod.allocate([1, 1, 1], 30, 10) == [10, 10, 10]
    # left over but every row at or under one step: goes to the biggest
    assert mod.allocate([1, 1, 2], 40, 10) == [10, 10, 20]


def test_infer_flags_reads_titles_and_skips_rituals(mod):
    items = [
        {"source": "meeting", "title": "Daily stand-up about security", "_clean": "Daily stand-up"},
        {"source": "claude", "title": "x", "_clean": "Fix pipeline error", "_folder": "/r/runbook",
         "_lines": 5},
        {"source": "claude", "title": "y", "_clean": "more code", "_lines": 5},
        {"source": "email", "title": "z", "_clean": "Hypercare", "detail": "high level design"},
    ]
    flags, note = mod.infer_flags(items)
    assert flags["development"] == "Yes" and flags["prod_support"] == "Yes"
    assert flags["lld"] == "Yes" and flags["hypercare"] == "Yes" and flags["hld"] == "Yes"
    assert flags["ref_arch"] == ""          # only the ritual mentioned security
    assert "code changed" in note and note.count("code changed") == 1


def test_resolve_period_variants_and_errors(mod):
    today = dt.date(2026, 9, 16)
    rp = lambda **kw: mod.resolve_period(args_for(mod, **kw), today)
    assert rp() == ("week", dt.date(2026, 9, 14), dt.date(2026, 9, 20), "week-2026-09-14")
    assert rp(day="today")[1] == today
    assert rp(day="2026-09-01")[3] == "2026-09-01"
    assert rp(month="this")[1:3] == (dt.date(2026, 9, 1), dt.date(2026, 9, 30))
    assert rp(month="2026-12")[1:] == (dt.date(2026, 12, 1), dt.date(2026, 12, 31), "2026-12")
    assert rp(start="2026-09-01", end="2026-09-03")[3] == "2026-09-01_2026-09-03"
    assert rp(start="2026-09-01")[2] == today
    for kw, msg in [({"day": "today", "week": "today"}, "pick one"),
                    ({"start": "2026-09-01", "day": "today"}, "not both"),
                    ({"end": "2026-09-01"}, "--to needs --from"),
                    ({"start": "2026-09-05", "end": "2026-09-01"}, "after --to"),
                    ({"month": "2026-13"}, "bad --month"),
                    ({"day": "yesterday"}, "bad date")]:
        with pytest.raises(SystemExit, match=msg):
            rp(**kw)


def test_summary_weeks_and_period_text(mod):
    d = dt.date
    assert mod.summary_weeks("day", d(2026, 9, 9), d(2026, 9, 9)) == [(d(2026, 9, 9), d(2026, 9, 9))]
    month = mod.summary_weeks("month", d(2026, 9, 1), d(2026, 9, 30))
    assert [m.day for m, _ in month] == [7, 14, 21, 28]
    rng = mod.summary_weeks("range", d(2026, 9, 9), d(2026, 9, 15))
    assert rng == [(d(2026, 9, 7), d(2026, 9, 13)), (d(2026, 9, 14), d(2026, 9, 20))]
    assert mod.period_text("day", d(2026, 9, 9), None) == "Wed 9 Sep 2026"
    assert mod.period_text("week", d(2026, 9, 7), None).startswith("week of Mon 7")
    assert mod.period_text("month", d(2026, 9, 1), None, month) == \
        "September 2026 · weeks starting 7, 14, 21, 28 Sep"
    assert mod.period_text("month", d(2026, 9, 1), None) == "September 2026"
    text = mod.period_text("range", d(2026, 9, 9), d(2026, 9, 15), rng)
    assert "whole weeks Mon 7 Sep 2026 to Sun 20 Sep 2026" in text
    assert "whole weeks" not in mod.period_text("range", d(2026, 9, 7), d(2026, 9, 13), rng[:1])


def test_missing_activity_and_describe_days(mod, tmp_path):
    days = [dt.date(2026, 9, 7) + dt.timedelta(days=i) for i in range(7)]
    f = tmp_path / "one.json"
    f.write_text("[]")
    assert mod.missing_activity(str(f), days) == []
    assert len(mod.missing_activity(str(tmp_path / "nope"), days)) == 5
    (tmp_path / "2026-09-07.json").write_text("[]")
    missing = mod.missing_activity(str(tmp_path), days)
    assert dt.date(2026, 9, 7) not in missing and len(missing) == 4
    assert mod.describe_days(missing) == "Tue 8, Wed 9, Thu 10, Fri 11"
    many = mod.missing_activity(str(tmp_path / "nope"), days + [d + dt.timedelta(days=7) for d in days])
    assert mod.describe_days(many) == "10 weekdays, Mon 07 Sep to Fri 18 Sep"


def test_parse_updated(mod):
    assert mod._parse_updated(None) is None
    assert mod._parse_updated("garbage") is None
    assert mod._parse_updated("2026-09-08T10:00:00.000+0100").hour == 9
    assert mod._parse_updated("2026-09-08T10:00:00Z").hour == 10


def test_target_for_uses_task_default_ticket(mod):
    tasks = {"A": {"default_ticket": "X-1"}}
    assert mod.target_for({"task": "A"}, tasks) == ("A", "X-1")
    assert mod.target_for({"task": "A", "ticket": "X-2"}, tasks) == ("A", "X-2")
    assert mod.target_for({"task": "B", "ticket": "Other"}, tasks) == ("B", "Other")


def test_reconcile_line(mod):
    backing = [{"row_id": "r1", "hours_exact": "1:00:00", "task": "T", "ticket": "", "week": "w"}]
    assert mod.reconcile([{"row_id": "r1", "_exact_s": 3600.0}], backing).startswith(
        "reconciles with the summary: 1.00h in 1 rows")
    bad = mod.reconcile([{"row_id": "r1", "_exact_s": 1800.0}, {"row_id": "zz", "_exact_s": 7200.0}],
                        backing)
    assert "does NOT reconcile" in bad and "w T / - -0.50h" in bad
    assert "2.00h in items the summary leaves out" in bad


def test_copy_rows_success_and_failure(mod, monkeypatch, capsys):
    seen = {}
    monkeypatch.setattr(mod, "clipboard_command", lambda: (["pbcopy"], "utf-8"))

    def fake_run(cmd, input=None, check=None):
        seen["cmd"], seen["input"] = cmd, input.decode()
    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod.copy_rows([{"a": "x\ty", "b": "l1\nl2"}], ["a", "b"], header=["A", "B"])
    assert seen == {"cmd": ["pbcopy"], "input": "A\tB\nx y\tl1 l2"}

    def broken(*a, **k):
        raise OSError("no pbcopy")
    monkeypatch.setattr(mod.subprocess, "run", broken)
    assert mod.copy_rows([{"a": 1}], ["a"]) is False
    assert "could not copy to the clipboard (no pbcopy)" in capsys.readouterr().err

    def failing(*a, **k):
        raise subprocess.CalledProcessError(1, "pbcopy")
    monkeypatch.setattr(mod.subprocess, "run", failing)
    assert mod.copy_rows([{"a": 1}], ["a"]) is False


def test_copy_rows_encodes_for_clip_exe(mod, monkeypatch):
    seen = {}
    monkeypatch.setattr(mod, "clipboard_command", lambda: (["clip.exe"], "utf-16"))
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, input=None, check=None: seen.update(b=input))
    assert mod.copy_rows([{"a": "Conceição"}], ["a"])
    assert seen["b"][:2] in (b"\xff\xfe", b"\xfe\xff")   # BOM, so clip.exe reads it as UTF-16
    assert seen["b"].decode("utf-16") == "Conceição"


def test_copy_rows_without_a_clipboard_tool(mod, monkeypatch, capsys):
    monkeypatch.setattr(mod, "clipboard_command", lambda: (None, None))
    assert mod.copy_rows([{"a": 1}], ["a"]) is False
    assert "no clipboard tool found" in capsys.readouterr().err


@pytest.mark.parametrize("platform,wsl,tools,expected", [
    ("darwin", False, set(), (["pbcopy"], "utf-8")),
    ("linux", True, {"clip.exe", "xclip"}, (["clip.exe"], "utf-16")),
    ("linux", True, {"wl-copy"}, (["wl-copy"], "utf-8")),          # WSL without interop
    ("linux", False, {"wl-copy", "xclip"}, (["wl-copy"], "utf-8")),
    ("linux", False, {"xclip"}, (["xclip", "-selection", "clipboard"], "utf-8")),
    ("linux", False, {"xsel"}, (["xsel", "--clipboard", "--input"], "utf-8")),
    ("linux", False, set(), (None, None)),
])
def test_clipboard_command_per_platform(mod, monkeypatch, platform, wsl, tools, expected):
    monkeypatch.setattr(mod.sys, "platform", platform)
    monkeypatch.setattr(mod, "is_wsl", lambda: wsl)
    monkeypatch.setattr(mod.shutil, "which", lambda name: "/bin/" + name if name in tools else None)
    assert mod.clipboard_command() == expected


def test_is_wsl_reads_proc_version(mod, monkeypatch, tmp_path):
    import builtins
    real_open = builtins.open
    for text, expected in (("Linux version 5.15.153.1-microsoft-standard-WSL2", True),
                           ("Linux version 6.8.0-45-generic", False)):
        f = tmp_path / "version"
        f.write_text(text)
        monkeypatch.setattr(builtins, "open",
                            lambda p, *a, **k: real_open(f if p == "/proc/version" else p, *a, **k))
        assert mod.is_wsl() is expected
    monkeypatch.setattr(builtins, "open", lambda p, *a, **k: (_ for _ in ()).throw(OSError()))
    assert mod.is_wsl() is False


def test_write_csv_to_stdout(mod, capsys):
    mod.write_csv("-", [{"a": 1, "b": 2}], ["a", "b"], header=["A", "B"])
    assert capsys.readouterr().out.splitlines() == ["A,B", "1,2"]


def test_by_type_view_groups_by_type(mod):
    rows = mod.by_type_view([
        {"task_type": "permissions", "_worked_s": 3600.0, "ticket": "B-1", "title": "a"},
        {"task_type": "permissions", "_worked_s": 1800.0, "ticket": "", "title": "b"},
        {"task_type": "", "_worked_s": 1800.0, "ticket": "B-2", "title": "c"},
    ])
    assert [(r["task_type"], r["sessions"], r["share"]) for r in rows] == \
        [("permissions", 2, "75%"), ("(no type)", 1, "25%")]
    assert rows[0]["hours_exact"] == "1:30:00" and rows[0]["tickets"] == "B-1"
    assert mod.by_type_view([]) == []


# ---------------------------------------------------------------- apply

def test_apply_decisions_merges_everything(mod, tmp_path, capsys):
    ledger = tmp_path / "review" / "ledger.json"
    mod.save_ledger(str(ledger), dict(mod.empty_ledger(), tasks=[
        {"task": "Keep", "tickets": ["X-1", "X-9"], "comments": {"X-1": "old"}, "note": "drop me"},
        {"task": "Gone"}], reject=[["a", "b"]]))
    decisions = write_json(tmp_path / "d.json", {
        "assign": [{"key": "s1", "subject": " Pipeline fix "}],
        "reject": [["b", "a"], ["d", "c"]],
        "remove_tasks": ["Gone"],
        "ignore_tickets": ["X-9"],
        "tasks": [{"task": "Keep", "tickets": ["X-2"], "comments": {"X-2": "new"}, "note": None,
                   "default_ticket": "X-1"},
                  {"task": "Fresh", "tickets": ["Y-1"], "paths": None}],
        "subjects": [{"subject": "Pipeline fix", "task": "Keep", "ticket": "X-3"},
                     {"subject": "Stuff", "task": "Brand new"},
                     {"subject": "Ignored ticket", "task": "Keep", "ticket": "X-9"},
                     {"subject": "Noise", "task": "(ignore)"}],
        "weeks": {WEEK: {"leave_days": 1, "rows": {"Keep|X-1": {"utilization": 50}}}},
        "jira_prefixes": ["X", "Y"],
        "leave_task": "Holiday",
        "default_task": "Fresh",
    })
    mod.apply_decisions(str(decisions), str(ledger))
    out = capsys.readouterr().out
    assert "1 items linked" in out and "1 links rejected" in out and "1 tasks removed" in out
    assert "2 tasks added" in out and "4 subjects mapped" in out
    got = json.loads(ledger.read_text())
    assert got["assign"]["s1"]["subject"] == "Pipeline fix"
    assert got["reject"] == [["a", "b"], ["c", "d"]]
    keep = next(t for t in got["tasks"] if t["task"] == "Keep")
    assert keep["tickets"] == ["X-1", "X-2", "X-3"] and "note" not in keep
    assert keep["comments"] == {"X-1": "old", "X-2": "new"} and keep["default_ticket"] == "X-1"
    assert {t["task"] for t in got["tasks"]} == {"Keep", "Fresh", "Brand new"}
    assert "paths" not in next(t for t in got["tasks"] if t["task"] == "Fresh")
    assert got["ignore_tickets"] == ["X-9"] and got["jira_prefixes"] == ["X", "Y"]
    assert got["leave_task"] == "Holiday" and got["default_task"] == "Fresh"
    assert got["weeks"][WEEK] == {"leave_days": 1, "rows": {"Keep|X-1": {"utilization": 50}}}

    # a second pass: null clears a row override, known prefixes are not duplicated
    again = write_json(tmp_path / "d2.json", {"weeks": {WEEK: {"rows": {"Keep|X-1": None,
                                                                          "Keep|X-2": {"flags": {}}}}},
                                              "jira_prefixes": ["X"]})
    mod.apply_decisions(str(again), str(ledger))
    got = json.loads(ledger.read_text())
    assert got["weeks"][WEEK]["rows"] == {"Keep|X-2": {"flags": {}}} and got["jira_prefixes"] == ["X", "Y"]

    empty = write_json(tmp_path / "d3.json", {})
    mod.apply_decisions(str(empty), str(ledger))
    assert "no changes" in capsys.readouterr().out


def test_apply_decisions_unreadable(mod, tmp_path):
    with pytest.raises(SystemExit, match="cannot read decisions"):
        mod.apply_decisions(str(tmp_path / "missing.json"), str(tmp_path / "l.json"))


# ---------------------------------------------------------------- main(): summary

def test_summary_week_table(mod, world, capsys):
    run(mod, "--week", WEEK)
    out = capsys.readouterr().out
    assert out.startswith("Summary · week of Mon 7 Sep 2026")
    assert "Data Platform" in out and "BTPA-1" in out and "Keep ingestion running" in out
    assert "Annual Leave" in out and "Out of office: Thu 10 (half), Fri 11" in out
    assert "job errors" in out                 # Task Type column
    # the pipeline session plus its meeting and email are one subject on one row
    assert "Private thing" not in out          # audit: false
    assert "not mapped to a task yet" in out   # the storage-access session is undecided


def test_summary_csv_and_breakdown(mod, world, capsys):
    target = world.home / "out" / "s.csv"
    run(mod, "--week", WEEK, "--csv", str(target))
    out = capsys.readouterr().out
    assert str(target) in out and str(target)[:-4] + "_breakdown.csv" in out
    rows = list(csv.DictReader(open(target)))
    assert list(rows[0])[:3] == ["Week", "Task", "Jira Ticket"] and "Task Type" in rows[0]
    by_task = {r["Task"]: r for r in rows}
    assert by_task["Data Platform"]["Meetings & Interactions"] == "Yes"
    assert by_task["Data Platform"]["Development"] == "Yes"
    assert by_task["Data Platform"]["Task Type"] == "job errors"
    assert by_task["Annual Leave"]["Leave"] == "Yes"
    breakdown = list(csv.DictReader(open(str(target)[:-4] + "_breakdown.csv")))
    # unmapped rows are never pasted but still hold their share of the week
    leave = int(by_task["Annual Leave"]["Utilization Perception"].rstrip("%"))
    assert leave == 30 and sum(int(b["utilization"]) for b in breakdown) + leave == 100
    dp = next(b for b in breakdown if b["task"] == "Data Platform")
    assert dp["sessions"] == "1" and dp["meetings"] == "1" and dp["emails"] == "1"
    assert dp["comments_from"] == "task default" and dp["jira_status"] == "In Progress"
    assert any(b["task"] == "(unmapped)" for b in breakdown)


def test_summary_csv_default_path_and_no_type(mod, world, capsys):
    run(mod, "--week", WEEK, "--csv", "--no-type")
    path = os.path.join(mod.DEFAULT_OUT_DIR, "claude-audit_week-{}_summary.csv".format(WEEK))
    assert os.path.exists(path) and os.path.exists(path[:-4] + "_breakdown.csv")
    assert "Task Type" not in open(path).readline()


def test_summary_csv_without_extension_gets_breakdown_suffix(mod, world, capsys):
    target = world.home / "plain"
    run(mod, "--week", WEEK, "--csv", str(target))
    assert (world.home / "plain_breakdown.csv").exists()


def test_summary_csv_to_stdout_sends_messages_to_stderr(mod, world, capsys):
    run(mod, "--week", WEEK, "--csv", "-")
    cap = capsys.readouterr()
    assert cap.out.startswith("Week,Task,Jira Ticket")
    assert cap.err.startswith("Summary · week of")


def test_summary_copy_uses_tracker_columns(mod, world, monkeypatch, capsys):
    pasted = []
    monkeypatch.setattr(mod, "clipboard_command", lambda: (["pbcopy"], "utf-8"))
    monkeypatch.setattr(mod.subprocess, "run", lambda cmd, input=None, check=None: pasted.append(input.decode()))
    run(mod, "--week", WEEK, "--copy")
    out = capsys.readouterr().out
    assert "rows copied -- click the first empty row of the tracker" in out
    first = pasted[0].splitlines()[0].split("\t")
    assert len(first) == len(mod.REVIEW_COLUMNS) and first[0] == WEEK
    run(mod, "--week", WEEK, "--copy", "--with-type")
    assert len(pasted[1].splitlines()[0].split("\t")) == len(mod.REVIEW_COLUMNS_EXT)


def test_summary_week_overrides(mod, world, capsys):
    ledger = json.loads(world.ledger.read_text())
    ledger["weeks"] = {WEEK: {"leave_days": 0, "rows": {
        "Data Platform|BTPA-1": {"utilization": 40, "flags": {"hld": "Yes"}, "comments": "Override text",
                                 "meetings": "Yes"}}}}
    ledger["subjects"] = {mod.stable_id("sub_", "Grant storage access to the team"): {
        "subject": "Grant storage access to the team", "task": "Security", "ticket": "Other"}}
    write_json(world.ledger, ledger)
    target = world.home / "o.csv"
    run(mod, "--week", WEEK, "--csv", str(target))
    rows = {r["Task"]: r for r in csv.DictReader(open(target))}
    assert rows["Data Platform"]["Utilization Perception"] == "40%"
    assert rows["Data Platform"]["Comments"] == "Override text" and rows["Data Platform"]["HLD"] == "Yes"
    assert "Annual Leave" not in rows          # leave_days 0 overrides the detected leave
    assert rows["Security"]["Jira Ticket"] == "Other"
    breakdown = list(csv.DictReader(open(str(target)[:-4] + "_breakdown.csv")))
    dp = next(b for b in breakdown if b["task"] == "Data Platform")
    assert dp["flags_from"] == "evidence + confirmed" and dp["comments_from"] == "week override"


def test_summary_day_keeps_only_comment_overrides(mod, world, capsys):
    ledger = json.loads(world.ledger.read_text())
    ledger["weeks"] = {WEEK: {"rows": {"Data Platform|BTPA-1": {"utilization": 10, "comments": "Day text"},
                                       "Other|X": {"utilization": 5}}}}
    write_json(world.ledger, ledger)
    target = world.home / "d.csv"
    run(mod, "--day", WEEK, "--csv", str(target))
    rows = {r["Task"]: r for r in csv.DictReader(open(target))}
    assert rows["Data Platform"]["Comments"] == "Day text"
    assert rows["Data Platform"]["Utilization Perception"] == "100%"
    assert list(csv.reader(open(target)))[0][0] == "Day"


def test_summary_nothing_recorded(mod, home, utc, capsys):
    run(mod, "--week", "2020-01-06")
    out = capsys.readouterr().out
    assert "nothing recorded in this period" in out
    assert "no Teams/calendar/mail data for Mon 6, Tue 7, Wed 8, Thu 9, Fri 10" in out


def test_summary_month_and_range(mod, world, capsys):
    run(mod, "--month", "2026-09")
    out = capsys.readouterr().out
    assert out.startswith("Summary · September 2026 · weeks starting 7, 14, 21, 28 Sep")
    run(mod, "--from", "2026-09-09", "--to", "2026-09-10")
    assert "whole weeks Mon 7 Sep 2026 to Sun 13 Sep 2026" in capsys.readouterr().out


def test_summary_finer_steps_and_auto_mapped_notes(mod, world, capsys):
    run(mod, "--week", WEEK, "--util-step", "50", "--min-subject", "20")
    out = capsys.readouterr().out
    assert "% steps -- too many rows for 50% steps" in out
    assert "small item(s) under 20 min" in out


def test_summary_declared_ticket_maps_without_asking(mod, world, capsys):
    # no default ticket on the task: the declared ticket carries through
    ledger = json.loads(world.ledger.read_text())
    ledger["tasks"][0].pop("default_ticket")
    ledger["tasks"][0].pop("comments")
    write_json(world.ledger, ledger)
    target = world.home / "decl.csv"
    run(mod, "--week", WEEK, "--csv", str(target))
    breakdown = list(csv.DictReader(open(str(target)[:-4] + "_breakdown.csv")))
    dp = next(b for b in breakdown if b["task"] == "Data Platform")
    assert dp["declared"] == "1" and dp["comments_from"] == "subject names"


def test_summary_long_comments_are_cut(mod, world, capsys):
    ledger = json.loads(world.ledger.read_text())
    ledger["tasks"][0].pop("comments")
    write_json(world.ledger, ledger)
    names = {}
    for i in range(6):
        sid = "bbbbbbbb-0000-0000-0000-00000000000{}".format(i)
        title = "Pipeline ingestion subject number {} with quite a long descriptive title".format(i)
        write_transcript(world.home, sid, str(world.root / "2026" / "09" / "07" / "09-00-00_pipeline-fix"),
                         8, 11 + i // 2, 20, title=title)
        names[title] = mod.stable_id("sub_", title)
    ledger["subjects"] = {sid: {"subject": t, "task": "Data Platform", "ticket": "BTPA-1"}
                          for t, sid in names.items()}
    write_json(world.ledger, ledger)
    target = world.home / "long.csv"
    run(mod, "--week", WEEK, "--csv", str(target))
    rows = {r["Task"]: r for r in csv.DictReader(open(target))}
    assert rows["Data Platform"]["Comments"].endswith("...")
    assert len(rows["Data Platform"]["Comments"]) <= 160
    run(mod, "--week", WEEK)
    assert "…" in capsys.readouterr().out   # table cuts to 48 chars on screen


# ---------------------------------------------------------------- main(): other views

def test_detail_view_reconciles_with_summary(mod, world, capsys):
    run(mod, "--week", WEEK, "--detail")
    out = capsys.readouterr().out
    assert out.startswith("Detail · week of Mon 7 Sep 2026")
    assert "reconciles with the summary" in out
    assert "(personal)" in out and "(notice)" in out and "Leave" in out
    assert "(left out" not in out            # the tiny session went to the default task


def test_detail_leaves_out_small_unmatched_items(mod, world, capsys):
    ledger = json.loads(world.ledger.read_text())
    ledger["default_task"] = ""
    write_json(world.ledger, ledger)
    run(mod, "--week", WEEK, "--detail")
    out = capsys.readouterr().out
    assert "(left out: under 10 min)" in out and "reconciles with the summary" in out


def test_detail_csv_has_row_ids_and_types(mod, world, capsys):
    target = world.home / "detail.csv"
    run(mod, "--week", WEEK, "--detail", "--csv", str(target))
    rows = list(csv.DictReader(open(target)))
    assert list(rows[0]) == mod.ACTIVITY_COLUMNS
    meeting = next(r for r in rows if r["title"] == "Pipeline review BTPA-1")
    session = next(r for r in rows if r["session_id"] == SID_PIPE)
    assert meeting["task"] == "Data Platform" and meeting["row_id"] == session["row_id"]
    assert meeting["task_type"] == "job errors"      # inherited from the session
    assert meeting["scheduled"] == "0:30:00" and session["worked"]
    assert session["cost_usd"] == "1.2346"
    assert not (world.home / "detail_breakdown.csv").exists()


def test_detail_copy_hint(mod, world, monkeypatch, capsys):
    monkeypatch.setattr(mod, "clipboard_command", lambda: (["pbcopy"], "utf-8"))
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: None)
    run(mod, "--week", WEEK, "--detail", "--copy")
    assert "paste into any sheet; the first row is the header" in capsys.readouterr().out


def test_reconcile_view_both_ways(mod, world, capsys):
    run(mod, "--week", WEEK, "--reconcile")
    out = capsys.readouterr().out
    assert out.startswith("Reconciliation · week of Mon 7 Sep 2026")
    assert "Activities -> tickets" in out and "Tickets -> activities" in out
    assert "not reconciled to a ticket" in out
    assert "BTPA-5" in out and "no activity found" in out     # x: nothing like it
    assert "BTPA-7" not in out                                # not mine
    assert "BTPA-8" not in out                                # unparsable stamp
    assert "probably have their activity booked elsewhere" in out


def test_reconcile_csv(mod, world, capsys):
    target = world.home / "rec.csv"
    run(mod, "--week", WEEK, "--reconcile", "--csv", str(target))
    rows = list(csv.DictReader(open(target)))
    assert list(rows[0]) == mod.RECONCILE_COLUMNS
    tix = {r["ticket"]: r for r in rows if r["side"] == "tickets"}
    assert tix["BTPA-1"]["status"] == "ok" and float(tix["BTPA-1"]["hours"]) > 0
    assert tix["BTPA-5"]["status"] == "x"
    assert tix["BTPA-2"]["status"] == "?" and "Grant storage access" in tix["BTPA-2"]["note"]
    # BTPA-6 looks like the pipeline work, which is booked to BTPA-1 and checks out
    assert "BTPA-6" not in tix and "also covers 1 related: BTPA-6" in tix["BTPA-1"]["note"]


def test_reconcile_without_jira(mod, world, capsys):
    os.remove(world.audit_dir / "review" / "jira.json")
    ledger = json.loads(world.ledger.read_text())
    ledger["subjects"] = {mod.stable_id("sub_", "Grant storage access to the team"): {
        "subject": "Grant storage access to the team", "task": "Security", "ticket": "BTPA-2"}}
    write_json(world.ledger, ledger)
    os.remove(world.audit_dir / "activity" / (WEEK + ".json"))
    for sid in (SID_TINY, SID_ROOT):
        os.remove(world.home / ".claude-personal" / "projects" / "proj" / (sid + ".jsonl"))
    run(mod, "--week", WEEK, "--reconcile")
    out = capsys.readouterr().out
    assert "every activity is reconciled to a ticket or a task" in out
    assert "(none)" in out and "no Jira tickets of yours changed" in out


def test_reconcile_mentions_and_task_vocabulary(mod, world, capsys):
    ledger = json.loads(world.ledger.read_text())
    ledger["tasks"][0]["keywords"].append("lakehouse")
    write_json(world.ledger, ledger)
    jira = JIRA + [
        # no subject shares its words, but the Data Platform task's vocabulary does
        {"key": "BTPA-11", "summary": "Lakehouse hardening", "status": "To Do", "mine": True,
         "updated": "2026-09-12T12:00:00Z"},
        # named by an email in the pipeline subject, which is booked to BTPA-1
        {"key": "BTPA-12", "summary": "Zebra", "status": "To Do", "mine": True,
         "updated": "2026-09-12T12:00:00Z"},
    ]
    write_json(world.audit_dir / "review" / "jira.json", jira)
    act = json.loads(json.dumps(ACTIVITY))
    act["events"].append({"source": "email", "start": "2026-09-07T12:30:00",
                          "title": "About BTPA-12", "subject": "Pipeline fix"})
    write_json(world.audit_dir / "activity" / (WEEK + ".json"), act)
    target = world.home / "rec2.csv"
    run(mod, "--week", WEEK, "--reconcile", "--csv", str(target))
    tix = {r["ticket"]: r for r in csv.DictReader(open(target)) if r["side"] == "tickets"}
    # both look like work booked to BTPA-1, which checks out, so they fold into it
    assert "BTPA-11" not in tix and "BTPA-12" not in tix
    assert "BTPA-11" in tix["BTPA-1"]["note"] and "BTPA-12" in tix["BTPA-1"]["note"]


def test_build_review_ignored_default_ticket_and_small_matches(mod, world):
    """An ignored subject is dropped, an 'Other' ticket takes the task's default, a small
    subject that matches a task goes to it, and with no idf table nothing small is mapped."""
    ledger = json.loads(world.ledger.read_text())
    ledger["subjects"] = {
        mod.stable_id("sub_", "Grant storage access to the team"): {
            "subject": "Grant storage access to the team", "task": "(ignore)", "ticket": "Other"},
        mod.stable_id("sub_", "Migration of BI reports"): {
            "subject": "Migration of BI reports", "task": "BI Migration", "ticket": "Other"},
    }
    write_json(world.ledger, ledger)
    write_transcript(world.home, "dddddddd-0000-0000-0000-000000000001", str(world.root), 10, 8, 4,
                     title="Ingestion pipeline lakehouse note")
    args = args_for(mod, ledger=str(world.ledger), activity=str(world.audit_dir / "activity"))
    first, last = dt.date(2026, 9, 7), dt.date(2026, 9, 13)
    items, led, idf, _ = mod.gather(args, first, last, 300, 120)
    days = mod.workdays(first, last)
    _, detail, report = mod.build_review(items, led, WEEK, days, {}, args, 120, idf)
    assert ("BI Migration", "BTPA-9") in {(d["task"], d["ticket"]) for d in detail}
    assert not any("Grant storage" in d["subjects"] for d in detail)
    small = next(s for s in report["subjects"] if s["name"] == "Ingestion pipeline lakehouse note")
    assert small["mapping"]["task"] == "Data Platform" and small["mapping"]["status"] == "auto"
    _, detail, report = mod.build_review(items, led, WEEK, days, {}, args, 120, None)
    small = next(s for s in report["subjects"] if s["name"] == "Ingestion pipeline lakehouse note")
    assert small["minor"] and small["mapping"] is None
    assert not any("lakehouse note" in d["subjects"] for d in detail)


def test_by_type_and_sessions_views(mod, world, capsys):
    run(mod, "--week", WEEK, "--by-type")
    out = capsys.readouterr().out
    assert out.startswith("By task type · week of Mon 7 Sep 2026 · 4 sessions")
    assert "job errors" in out and "permissions" in out and "(no type)" in out
    run(mod, "--week", WEEK, "--sessions")
    out = capsys.readouterr().out
    assert out.startswith("Sessions · week of Mon 7 Sep 2026 · 4 sessions")
    assert "BTPA-1" in out and "Grant storage access" in out
    target = world.home / "sessions.csv"
    run(mod, "--week", WEEK, "--sessions", "--csv", str(target))
    rows = list(csv.DictReader(open(target)))
    assert list(rows[0]) == mod.COLUMNS and len(rows) == 4


def test_no_audit_file_hides_sessions(mod, world, capsys):
    (world.audit_dir / "no-audit.txt").write_text("# hide the root session\n{}\n".format(SID_ROOT))
    run(mod, "--week", WEEK, "--sessions")
    out = capsys.readouterr().out
    assert "3 sessions" in out and "Migration of BI reports" not in out


def test_single_activity_file(mod, world, capsys):
    run(mod, "--week", WEEK, "--detail", "--activity",
        str(world.audit_dir / "activity" / (WEEK + ".json")))
    out = capsys.readouterr().out
    assert "Pipeline review BTPA-1" in out and "no Teams/calendar/mail data" not in out


# ---------------------------------------------------------------- main(): propose / apply / misc

def test_propose_writes_proposals(mod, world, capsys):
    run(mod, "--week", WEEK, "--propose", "--min-subject", "5")
    out = capsys.readouterr().out
    path = world.audit_dir / "review" / "proposals_{}.json".format(WEEK)
    assert out.startswith("Week of {}".format(WEEK)) and str(path) in out
    assert "Leave detected: Thu 10 (half), Fri 11" in out
    prop = json.loads(path.read_text())
    assert prop["week"] == WEEK and prop["jira_tickets_known"] == 7
    assert prop["counts"]["claude"] == 4 and prop["counts"]["leave"] == 2
    subjects = {t["subject"]: t for t in prop["tasks"]}
    perm = subjects["Grant storage access to the team"]
    assert perm["suggestion"]["task"] == "Security" and perm["tier"] in ("likely", "possible")
    assert "TASK MAPPING" in out
    assert prop["minor"]["count"] >= 1 and "mapped automatically" in out


def test_propose_links_and_unknowns(mod, world, capsys):
    # no default task, and a session nothing in the registry describes
    ledger = json.loads(world.ledger.read_text())
    ledger["default_task"] = ""
    write_json(world.ledger, ledger)
    write_transcript(world.home, "cccccccc-0000-0000-0000-000000000001", str(world.root), 8, 14, 60,
                     title="Architecture design options for lakehouse")
    run(mod, "--week", WEEK, "--propose")
    out = capsys.readouterr().out
    prop = json.loads((world.audit_dir / "review" / "proposals_{}.json".format(WEEK)).read_text())
    assert any(t["tier"] == "unknown" for t in prop["tasks"])
    assert "TASK MAPPING - no idea, needs you" in out
    assert prop["links"], "the chat during the design session should be proposed as a link"
    link = prop["links"][0]
    assert link["id"][0] in "LP" and link["events"]
    assert "CORRELATIONS" in out and "<->" in out


def test_propose_jira_match_is_shown(mod, world, capsys):
    run(mod, "--week", WEEK, "--propose")
    out = capsys.readouterr().out
    assert 'Jira: BTPA-2 "Grant storage access"' in out


def test_propose_needs_a_week(mod, world):
    with pytest.raises(SystemExit, match="--propose works on one week"):
        run(mod, "--day", WEEK, "--propose")


def test_apply_via_main_then_stop_or_continue(mod, world, capsys):
    decisions = write_json(world.home / "dec.json", {"leave_task": "PTO"})
    run(mod, "--apply", str(decisions))
    out = capsys.readouterr().out
    assert out.startswith("ledger updated") and "Summary" not in out
    run(mod, "--apply", str(decisions), "--week", WEEK)
    out = capsys.readouterr().out
    assert "ledger updated" in out and "PTO" in out


def test_schema_and_mutually_exclusive_views(mod, capsys):
    run(mod, "--schema")
    assert "--activity expects a JSON array" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="pick --detail or --reconcile"):
        run(mod, "--detail", "--reconcile")


def test_help_all_shows_advanced_options(mod, capsys):
    with pytest.raises(SystemExit):
        run(mod, "--help")
    assert "--propose" not in capsys.readouterr().out
    with pytest.raises(SystemExit):
        run(mod, "--help-all")
    out = capsys.readouterr().out
    assert "--propose" in out and "advanced -- used by the weekly-review skill" in out
