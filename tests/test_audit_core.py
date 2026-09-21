"""bin/claude-audit, lines up to candidate_tasks/leave_days: config, transcripts,
session metadata, time accounting, activity files, the ledger and link scoring."""

import datetime as dt
import json
import math
import os

import pytest


def local(y, mo, d, h=0, mi=0, s=0):
    return dt.datetime(y, mo, d, h, mi, s).astimezone()


def write_json(path, data):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "w") as fh:
        json.dump(data, fh)


def write_jsonl(path, records):
    os.makedirs(os.path.dirname(str(path)), exist_ok=True)
    with open(str(path), "w") as fh:
        for r in records:
            fh.write((r if isinstance(r, str) else json.dumps(r)) + "\n")


# ------------------------------------------------------------------ config

def test_load_config_parses_quoted_bare_comments_and_home(audit, home, monkeypatch):
    conf = home / "c.env"
    conf.write_text(
        '# comment line\n'
        'CWS_A="quoted # not a comment" trailing\n'
        "CWS_B='single'\n"
        'CWS_C=bare value # comment\n'
        'CWS_D=$HOME/x\n'
        'CWS_E="${HOME}/y"\n'
        'not a setting\n')
    monkeypatch.setenv("CWS_CONFIG", str(conf))
    monkeypatch.setenv("CWS_ENV_WINS", "yes")
    monkeypatch.setenv("OTHER", "ignored")
    conf_d = audit.load_config()
    assert conf_d["CWS_A"] == "quoted # not a comment"
    assert conf_d["CWS_B"] == "single"
    assert conf_d["CWS_C"] == "bare value"
    assert conf_d["CWS_D"] == str(home) + "/x"
    assert conf_d["CWS_E"] == str(home) + "/y"
    assert conf_d["CWS_ENV_WINS"] == "yes"
    assert "OTHER" not in conf_d


def test_load_config_env_overrides_file_and_missing_file_is_fine(audit, home, monkeypatch):
    monkeypatch.setenv("CWS_CONFIG", str(home / "missing.env"))
    monkeypatch.setenv("CWS_PROFILES", "one")
    assert audit.load_config() == {"CWS_CONFIG": str(home / "missing.env"), "CWS_PROFILES": "one"}


def test_module_config_comes_from_file(audit, home):
    assert audit.PROFILES == ["personal", "work"]
    assert audit.CONFIG_DIRS == [str(home / ".claude-personal"), str(home / ".claude-work")]
    assert audit.DEFAULT_OUT_DIR == str(home / "work_sessions" / "_audit")


# ------------------------------------------------------------------ small helpers

def test_parse_ts(audit):
    assert audit.parse_ts(None) is None
    assert audit.parse_ts(123) is None
    assert audit.parse_ts("garbage") is None
    ts = audit.parse_ts("2026-09-09T10:00:00Z")
    assert ts.tzinfo is not None
    assert ts == dt.datetime(2026, 9, 9, 10, tzinfo=dt.timezone.utc)


def test_round_up_and_hms(audit):
    assert audit.round_up(0, 1800) == 0
    assert audit.round_up(-5, 1800) == -5
    assert audit.round_up(100, 0) == 100
    assert audit.round_up(1, 1800) == 1800
    assert audit.round_up(1800, 1800) == 1800
    assert audit.round_up(1801, 1800) == 3600
    assert audit.hms(3725.4) == "1:02:05"
    assert audit.hms(0) == "0:00:00"


def test_parse_local(audit):
    assert audit.parse_local(None) is None
    assert audit.parse_local(5) is None
    assert audit.parse_local("nope") is None
    naive = audit.parse_local("2026-09-09T09:00:00")
    assert naive == local(2026, 9, 9, 9)
    z = audit.parse_local("2026-09-09T09:00:00Z")  # Z is dropped: treated as local
    assert z == local(2026, 9, 9, 9)
    aware = audit.parse_local("2026-09-09T09:00:00+00:00")
    assert aware == dt.datetime(2026, 9, 9, 9, tzinfo=dt.timezone.utc)


def test_stable_id_overlaps_week_bounds_at(audit):
    a = audit.stable_id("sub_", "x", 1)
    assert a == audit.stable_id("sub_", "x", 1)
    assert a != audit.stable_id("sub_", "x", 2)
    assert a.startswith("sub_") and len(a) == 14
    assert audit._overlaps(1, 3, 2, 4)
    assert not audit._overlaps(1, 2, 2, 3)
    assert audit.week_bounds(dt.date(2026, 9, 10)) == (dt.date(2026, 9, 7), dt.date(2026, 9, 13))
    assert audit._at(dt.date(2026, 9, 10), 9, 30) == local(2026, 9, 10, 9, 30)


def test_first_prompt_text(audit):
    assert audit.first_prompt_text({"content": "hi"}) == "hi"
    assert audit.first_prompt_text({"content": [{"type": "image"}, "x",
                                                {"type": "text", "text": "yo"}]}) == "yo"
    assert audit.first_prompt_text({"content": [{"type": "text"}]}) == ""
    assert audit.first_prompt_text({"content": [{"type": "image"}]}) == ""
    assert audit.first_prompt_text({}) == ""


# ------------------------------------------------------------------ transcripts

def test_transcript_files_dedupes_and_skips_agents(audit, home):
    p = home / ".claude-personal" / "projects" / "proj"
    write_jsonl(p / "s1.jsonl", [{}])
    write_jsonl(p / "agent-x.jsonl", [{}])
    (p / "notes.txt").write_text("x")
    w = home / ".claude-work" / "projects"
    w.mkdir(parents=True)
    os.symlink(str(p / "s1.jsonl"), str(w / "same.jsonl"))  # same file via the other profile
    files = audit.transcript_files()
    assert files == [os.path.realpath(str(p / "s1.jsonl"))]


def test_transcript_files_none(audit):
    assert audit.transcript_files() == []


def test_session_meta_variants(audit, home):
    assert audit.session_meta("")["profile"] == "unknown"
    d = home / "work_sessions" / "req"
    write_json(d / ".session.json", {"profile": "work", "ticket": " BTPA-1 ", "task_type": " tooling ",
                                     "session_types": {"sid": "permissions"}, "audit": False})
    m = audit.session_meta(str(d))
    assert m == {"profile": "work", "ticket": "BTPA-1", "task_type": "tooling",
                 "session_types": {"sid": "permissions"}, "audit": False}
    assert audit.session_meta(str(d)) is m  # cached
    assert audit.profile_for(str(d)) == "work"

    bad = home / "work_sessions" / "bad"
    bad.mkdir()
    (bad / ".session.json").write_text("{not json")
    assert audit.session_meta(str(bad)) == {"profile": "unknown", "ticket": "", "task_type": "",
                                            "session_types": {}, "audit": True}
    assert audit.session_meta(str(home / "nofolder"))["audit"] is True


def test_session_folder_and_meta_for(audit, home):
    req = home / "work_sessions" / "req"
    write_json(req / ".session.json", {"profile": "work", "ticket": "BTPA-2"})
    write_json(audit.SESSION_FOLDERS_PATH, {"sid-1": str(req)})
    repo = home / "repo"
    repo.mkdir()
    assert audit.session_folder("sid-1") == str(req)
    assert audit.session_folder("other") == ""
    # ran in a folder without metadata -> falls back to the assigned request folder
    assert audit.meta_for(str(repo), "sid-1")["ticket"] == "BTPA-2"
    # no assignment -> the empty meta
    assert audit.meta_for(str(repo), "sid-2")["profile"] == "unknown"
    # own metadata wins
    assert audit.meta_for(str(req), "sid-2")["ticket"] == "BTPA-2"


def test_session_folder_missing_or_bad_file(audit):
    assert audit.session_folder("x") == ""
    audit._session_folders = None
    write_json(audit.SESSION_FOLDERS_PATH, {})
    with open(audit.SESSION_FOLDERS_PATH, "w") as fh:
        fh.write("not json")
    assert audit.session_folder("x") == ""


def test_no_audit_ids(audit, home):
    assert audit.no_audit_ids(str(home / "missing.txt")) == set()
    f = home / "no.txt"
    f.write_text("abc # root session\n\n# only comment\n def \n")
    assert audit.no_audit_ids(str(f)) == {"abc", "def"}


def test_moved_path(audit, home):
    write_json(audit.MOVED_PATH, {"/old/a": "/new/a"})
    assert audit.moved_path("") == ""
    assert audit.moved_path("/old/a") == "/new/a"
    assert audit.moved_path("/old/a/sub") == "/new/a/sub"
    assert audit.moved_path("/old/ab") == "/old/ab"
    assert audit.moved_path("/elsewhere") == "/elsewhere"


def test_moved_path_without_map(audit):
    assert audit.moved_path("/x") == "/x"
    audit._moved = None
    write_json(audit.MOVED_PATH, [])
    with open(audit.MOVED_PATH, "w") as fh:
        fh.write("{bad")
    assert audit.moved_path("/x") == "/x"


def test_read_session(audit, home):
    write_json(audit.MOVED_PATH, {"/old": "/new"})
    path = home / "t" / "abc.jsonl"
    write_jsonl(path, [
        "",
        "not json",
        {"type": "user", "timestamp": "2026-09-09T10:05:00Z", "promptId": "p1",
         "cwd": "/old/req", "gitBranch": "main", "version": "2.0",
         "message": {"content": "first real prompt"}},
        {"type": "assistant", "timestamp": "2026-09-09T10:00:00Z", "promptId": "p1",
         "cwd": "/ignored"},  # earlier stamp for the same prompt wins
        {"type": "user", "timestamp": "2026-09-09T10:10:00Z", "promptId": "p2",
         "message": {"content": [{"type": "text", "text": "second prompt"}]}},
        {"type": "user", "isSidechain": True, "message": {"content": "side"}},
        {"type": "user", "isMeta": True, "message": {"content": "meta"}},
        {"type": "user", "message": {"content": "<command-name>x</command-name>"}},
        {"type": "user", "timestamp": "bad"},
        {"type": "ai-title", "aiTitle": "A title"},
        {"type": "ai-title"},
        {"type": "last-prompt", "lastPrompt": "the last"},
        {"type": "last-prompt"},
        {"type": "cost-state", "totalCostUSD": 1.5},
    ])
    s = audit.read_session(str(path))
    assert s["path"] == str(path)
    assert [t.isoformat() for t in s["turns"]] == [
        audit.parse_ts("2026-09-09T10:00:00Z").isoformat(),
        audit.parse_ts("2026-09-09T10:10:00Z").isoformat()]
    assert len(s["stamps"]) == 3 and s["stamps"] == sorted(s["stamps"])
    assert s["cost"] == {"type": "cost-state", "totalCostUSD": 1.5}
    info = s["info"]
    assert info["title"] == "A title"
    assert info["last_prompt"] == "the last"
    assert info["cwd"] == "/new/req"
    assert info["branch"] == "main" and info["version"] == "2.0"
    assert info["opening"] == "first real prompt"
    assert info["prompts"] == ["first real prompt", "second prompt"]


def test_read_session_caps_prompts_and_truncates(audit, home):
    path = home / "t" / "cap.jsonl"
    recs = [{"type": "user", "timestamp": "2026-09-09T10:00:00Z", "message": {"content": "x" * 500}}]
    recs += [{"type": "user", "message": {"content": "p%d" % i}} for i in range(50)]
    write_jsonl(path, recs)
    info = audit.read_session(str(path))["info"]
    assert len(info["prompts"]) == 40
    assert info["prompts"][0] == "x" * 400


def test_read_session_missing_or_empty(audit, home):
    assert audit.read_session(str(home / "nope.jsonl")) is None
    path = home / "t" / "empty.jsonl"
    write_jsonl(path, [{"type": "user", "message": {"content": "no stamps"}}])
    assert audit.read_session(str(path)) is None


# ------------------------------------------------------------------ time accounting

def test_worked_seconds(audit):
    t = lambda m: local(2026, 9, 9, 10) + dt.timedelta(minutes=m)
    assert audit.worked_seconds([t(0)], [], 300, 120) == 0.0
    # one turn: gaps 1 min and 20 min (capped at 5)
    assert audit.worked_seconds([t(0), t(1), t(21)], [t(0)], 300, 120) == 60 + 300
    # activity before the first prompt becomes its own turn; the read gap is capped
    events = [t(0), t(1), t(10), t(11)]
    assert audit.worked_seconds(events, [t(10)], 300, 120) == 60 + 120 + 60
    # read gaps between turns (30 s, then 4 min capped at 2); the last turn has no events
    assert audit.worked_seconds([t(0), t(1)], [t(0), t(0.5), t(5)], 300, 120) == 30 + 120
    # no recorded turns at all
    assert audit.worked_seconds([t(0), t(2)], [], 300, 120) == 120


def test_split_by_day(audit):
    stamps = [local(2026, 9, 9, 23), local(2026, 9, 10, 1)]
    s = {"path": "p", "info": {"x": 1}, "stamps": stamps, "turns": stamps, "cost": {"c": 1}}
    parts = list(audit.split_by_day(s))
    assert [p["stamps"] for p in parts] == [[stamps[0]], [stamps[1]]]
    assert [p["turns"] for p in parts] == [[stamps[0]], [stamps[1]]]
    assert [p["cost"] for p in parts] == [{}, {"c": 1}]


def g(source, start, end=None, worked=0.0, **kw):
    row = {"source": source, "_start": start, "_end": end, "_worked_s": worked}
    row.update(kw)
    return row


def test_subject_seconds(audit):
    t = lambda h, m=0: local(2026, 9, 9, h, m)
    # session work plus a meeting it did not overlap
    grp = [g("claude", t(9), t(10), worked=1000), g("meeting", t(11), t(12)),
           g("meeting", t(9, 30), t(9, 45)),  # overlaps the session: not added
           g("meeting", t(13))]  # no end
    assert audit.subject_seconds(grp, 1800, 120) == audit.round_up(1000 + 3600, 1800)
    # comms only: spans plus capped gaps
    grp = [g("email", t(9)), g("chat", t(9, 1), t(9, 3)), g("email", t(12))]
    assert audit.subject_seconds(grp, 60, 120) == 120 + 60 + 120
    # something else with no time stays zero
    assert audit.subject_seconds([g("personal", t(9), t(10))], 1800, 120) == 0


# ------------------------------------------------------------------ activity file

def test_load_activity_array(audit, home, capsys):
    f = home / "a" / "2026-09-09.json"
    write_json(f, [
        {"source": "meeting", "start": "2026-09-09T09:00:00", "end": "2026-09-09T09:30:00",
         "title": "Stand-up", "counterparties": ["a@x", "b@x"], "detail": "line1\nline2",
         "ref": "http://r", "subject": " Subj "},
        {"source": "email", "start": "2026-09-09T10:00:00", "counterparties": "c@x"},
        {"start": "2026-09-09T11:00:00", "end": "2026-09-09T11:05:00"},
        "not an object",
        {"source": "chat", "start": "bad"},
    ])
    rows, subjects = audit.load_activity(str(f))
    assert subjects == {}
    assert len(rows) == 3
    m, e, o = rows
    assert m["scheduled_h"] == 0.5 and m["elapsed"] == "0:30:00"
    assert m["counterparties"] == "a@x; b@x" and m["detail"] == "line1 line2"
    assert m["_subject"] == "Subj" and m["_key"] == "2026-09-09.json[0]"
    assert m["weekday"] == "Wed" and m["date"] == "2026-09-09"
    assert e["end"] == "" and e["elapsed"] == "" and e["scheduled_h"] == "" and e["counterparties"] == "c@x"
    assert o["source"] == "other" and o["scheduled_h"] == "" and o["elapsed"] == "0:05:00"
    err = capsys.readouterr().err
    assert "activity[3]: not an object" in err and "activity[4]: bad or missing start" in err


def test_load_activity_directory_and_subjects(audit, home):
    d = home / "act"
    write_json(d / "1.json", {"events": [{"source": "email", "start": "2026-09-09T10:00:00"}],
                              "subjects": {"sid": "S"}})
    write_json(d / "2.json", [{"source": "chat", "start": "2026-09-10T10:00:00"}])
    (d / "readme.txt").write_text("x")
    rows, subjects = audit.load_activity(str(d))
    assert [r["source"] for r in rows] == ["email", "chat"]
    assert subjects == {"sid": "S"}


@pytest.mark.parametrize("content, msg", [
    (None, "no .json activity files"),
    ("{bad", "cannot read --activity file"),
    ({"events": "x"}, "must be a JSON array"),
    ({"events": [], "subjects": ["x"]}, "\"subjects\" must be an object"),
])
def test_load_activity_errors(audit, home, content, msg):
    if content is None:
        target = home / "emptydir"
        target.mkdir()
    else:
        target = home / "bad.json"
        target.write_text(content if isinstance(content, str) else json.dumps(content))
    with pytest.raises(SystemExit) as exc:
        audit.load_activity(str(target))
    assert msg in str(exc.value)


# ------------------------------------------------------------------ rows

def make_session(stamps, info=None, cost=None, turns=None, path="/t/sid-123.jsonl"):
    base = {"title": "", "cwd": "", "branch": "b", "version": "v", "last_prompt": "",
            "opening": "", "prompts": []}
    base.update(info or {})
    return {"path": path, "stamps": stamps, "turns": turns if turns is not None else stamps[:1],
            "cost": cost or {}, "info": base}


def test_build_row_with_cost_and_session_type(audit, home):
    req = home / "work_sessions" / "req"
    write_json(req / ".session.json", {"profile": "work", "ticket": "BTPA-9", "task_type": "tooling",
                                       "session_types": {"sid-123": "permissions"}})
    stamps = [local(2026, 9, 9, 10), local(2026, 9, 9, 10, 4)]
    cost = {"totalCostUSD": 1.23456, "totalLinesAdded": 10, "totalLinesRemoved": 2,
            "modelUsage": {"claude-opus-5": {}, "claude-haiku": {}}}
    s = make_session(stamps, info={"cwd": str(req), "opening": "line\nopening " + "y" * 100,
                                   "last_prompt": "last\nprompt", "prompts": ["p1"]}, cost=cost)
    row = audit.build_row(s, 300, 120, 1800)
    assert row["date"] == "2026-09-09" and row["worked_h"] == 0.5
    assert row["worked_exact"] == "0:04:00" and row["elapsed"] == "0:04:00"
    assert row["profile"] == "work" and row["ticket"] == "BTPA-9"
    assert row["task_type"] == "permissions"
    assert row["title"] == ("line opening " + "y" * 100)[:80]
    assert row["cost_usd"] == 1.2346 and row["lines_added"] == 10 and row["lines_removed"] == 2
    assert row["models"] == "haiku, opus-5"
    assert row["last_prompt"] == "last prompt"
    assert row["session_id"] == "sid-123" and row["_lines"] == 10
    assert row["_text"].endswith(" p1")
    assert set(audit.COLUMNS) <= set(row)

    ev = audit.session_as_event(row)
    assert ev["source"] == "claude" and ev["_key"] == "sid-123" and ev["_ticket"] == "BTPA-9"
    assert ev["_task_type"] == "permissions" and ev["detail"] == str(req)


def test_build_row_without_cost_uses_folder_type(audit, home):
    s = make_session([local(2026, 9, 9, 10)], info={"title": "T"})
    row = audit.build_row(s, 300, 120, 1800)
    assert row["title"] == "T" and row["cost_usd"] == "" and row["lines_added"] == ""
    assert row["models"] == "" and row["_lines"] is None and row["task_type"] == ""
    assert row["worked_h"] == 0.0
    assert audit.build_row(make_session([local(2026, 9, 9, 10)]), 300, 120, 1800)["title"] == ""


# ------------------------------------------------------------------ ledger and jira

def test_ledger_roundtrip(audit, home):
    path = str(home / "r" / "ledger.json")
    assert audit.load_ledger(path) == audit.empty_ledger()
    led = audit.empty_ledger()
    led["tasks"] = [{"task": "X"}]
    audit.save_ledger(path, led)
    assert not os.path.exists(path + ".tmp")
    assert audit.load_ledger(path)["tasks"] == [{"task": "X"}]
    with open(path, "w") as fh:
        fh.write("{bad")
    with pytest.raises(SystemExit) as exc:
        audit.load_ledger(path)
    assert "cannot read ledger" in str(exc.value)


def test_load_jira(audit, home):
    assert audit.load_jira(str(home / "none.json")) == []
    f = home / "jira.json"
    write_json(f, [{"key": "A-1"}, {"summary": "no key"}, "str"])
    assert audit.load_jira(str(f)) == [{"key": "A-1"}]


# ------------------------------------------------------------------ text matching

def test_stem_and_tokens(audit):
    assert audit._stem("migrations") == "migr"
    assert audit._stem("pipelines") == "pipeline"
    assert audit._stem("cats") == "cat"  # 3 chars left is allowed
    assert audit._stem("ads") == "ads"   # would leave only 2
    toks = audit.tokens("The Firewall rules for ADB 2026 and uc, BI in KeyVault x")
    assert toks == {"fw", "rule", "databrick", "uc", "bi", "kv"}
    assert audit.tokens(None) == set()


def test_stopwords_include_org(home, monkeypatch):
    import conftest
    monkeypatch.setenv("CWS_ORG", "Acme Corp")
    mod = conftest.load_script("claude-audit")
    assert "acme" in mod.STOPWORDS and mod.tokens("acme widgets") == {"widget"}


def test_jira_keys(audit):
    text = "see BTPA-12 and UTF-8, ABC-3 and SHA-256"
    assert audit.jira_keys(text, set()) == {"BTPA-12", "ABC-3"}
    assert audit.jira_keys(text, {"BTPA"}) == {"BTPA-12"}
    assert audit.jira_keys(None, set()) == set()


def test_idf_and_weighted_overlap(audit):
    docs = [{"a", "common"}, {"b", "common"}, {"c", "common"}, {"d", "common"}, {"e"}, {"f"}]
    idf = audit.idf_table(docs)
    table, n = idf
    assert n == 6 and table["a"] == pytest.approx(math.log(1 + 6))
    assert audit.idf_table([]) == ({}, 1)
    # "common" is in >25% of docs -> never creates a match alone
    assert audit.weighted_overlap({"common", "x"}, {"common", "y"}, idf) == (0.0, [])
    sim, words = audit.weighted_overlap({"a"}, {"a", "b"}, idf)
    assert sim == 1.0 and words == ["a"]
    # explicit base
    sim, _ = audit.weighted_overlap({"a"}, {"a", "b"}, idf, base={"a", "b"})
    assert 0 < sim < 1
    # unseen words carry the max weight
    sim, words = audit.weighted_overlap({"zz"}, {"zz"}, idf)
    assert sim == 1.0 and words == ["zz"]
    # zero-weight base
    assert audit.weighted_overlap({"a"}, {"a"}, idf, base=set()) == (0.0, [])


def test_clean_title_and_label(audit):
    assert audit.clean_title("RE: Fwd: Accepted: Cost  pipeline - review") == "Cost pipeline review"
    assert audit.clean_title(None) == ""
    t = local(2026, 9, 9, 9, 5)
    assert audit.label({"_start": t, "_clean": "Thing", "source": "claude", "_worked_s": 3900}) == \
        "Wed 09:05 claude  Thing (1:05 worked)"
    assert audit.label({"_start": t, "_clean": "Mail", "source": "email"}) == "Wed 09:05 email   Mail"
    assert audit.label({"_start": t, "_clean": "X", "source": "claude"}).endswith("(0:00 worked)")


# ------------------------------------------------------------------ items and links

def item(source, start, title, end=None, **kw):
    it = {"source": source, "title": title, "start": start.strftime("%Y-%m-%d %H:%M:%S"),
          "_start": start, "_end": end}
    it.update(kw)
    return it


def test_prepare_items_subject_precedence(audit):
    t = local(2026, 9, 9, 9)
    led = audit.empty_ledger()
    led["jira_prefixes"] = ["BTPA"]
    led["ignore_tickets"] = ["BTPA-99"]
    confirmed = item("claude", t, "Session one", session_id="s1", _ticket="btpa-5",
                     _folder="/w/req-folder", _text="talks about BTPA-7 and ABC-1")
    led["assign"]["s1"] = {"subject": "Confirmed subj"}
    inferred = item("email", t, "RE: Report", _key="k1")
    same = item("meeting", t, "Stand-up", _subject="Stand-up")
    ignored = item("claude", t, "Other ticket", session_id="s2", _ticket="BTPA-99",
                   _text="BTPA-99")
    other = item("claude", t, "", session_id="s3", _ticket="Other")
    audit.prepare_items([confirmed, inferred, same, ignored, other], {"k1": "Report subj"}, led)

    assert confirmed["_status"] == "confirmed" and confirmed["subject"] == "Confirmed subj"
    assert confirmed["_declared"] == "BTPA-5"
    assert confirmed["_jira"] == {"BTPA-5", "BTPA-7"}
    assert confirmed["_lkey"] == "s1" and "req" in confirmed["_title_tok"] | confirmed["_tok"]
    assert inferred["_status"] == "inferred" and inferred["subject"] == "Report subj"
    assert inferred["_clean"] == "Report" and inferred["_lkey"].startswith("evt_")
    assert same["_status"] == "standalone" and same["subject"] == "Stand-up"
    assert ignored["_declared"] == "" and ignored["_jira"] == set()
    assert other["_declared"] == "" and other["_clean"] == "claude"
    assert confirmed["subject_id"] == audit.stable_id("sub_", "Confirmed subj")


def test_active_near(audit):
    t = lambda m: local(2026, 9, 9, 10) + dt.timedelta(minutes=m)
    assert not audit._active_near([], t(0), t(1))
    assert audit._active_near([t(5)], t(0), t(10))
    assert not audit._active_near([t(5)], t(6), t(10))
    assert not audit._active_near([t(5)], t(0), t(4))


def linked(source, start, end=None, status="standalone", subject="subj", jira=(), tok=(),
           stamps=None, lkey=None, title="t", worked=0):
    return {"source": source, "_start": start, "_end": end, "_status": status, "subject": subject,
            "_jira": set(jira), "_tok": set(tok), "_stamps": stamps, "_lkey": lkey or title,
            "title": title, "_clean": title, "_worked_s": worked}


def test_score_link_signals(audit):
    t = lambda m: local(2026, 9, 9, 10) + dt.timedelta(minutes=m)
    idf = audit.idf_table([{"x"}, {"y"}, {"z"}, {"w"}, {"v"}])
    stamps = [t(0), t(30)]
    s = linked("claude", t(0), status="inferred", subject="S", jira={"A-1"}, tok={"x"},
               stamps=stamps)

    e = linked("meeting", t(-10), t(5), subject="S", jira={"A-1"}, tok={"x"})
    score, why = audit.score_link(s, e, idf)
    assert score == 1.0
    assert why[0] == "both mention A-1" and "grouped together by the daily recap" in why
    assert any(w.startswith("shared words") for w in why) and why[-1] == "session active during the meeting"

    plain = dict(s, _jira=set(), _status="standalone", _tok=set())
    # meeting ended 10 min before the session began
    s2 = dict(plain, _stamps=[t(20), t(30)])
    assert audit.score_link(s2, linked("meeting", t(0), t(10)), idf) == \
        (0.2, ["session started 10 min after the meeting"])
    # meeting began right after activity
    assert audit.score_link(plain, linked("meeting", t(35), t(60)), idf) == \
        (0.15, ["meeting began right after session activity"])
    assert audit.score_link(plain, linked("meeting", t(200), t(260)), idf) == (0.0, [])

    assert audit.score_link(plain, linked("email", t(10)), idf) == \
        (0.15, ["email sent while the session was active"])
    s3 = dict(plain, _stamps=[t(60), t(90)])
    assert audit.score_link(s3, linked("email", t(20)), idf) == \
        (0.1, ["email sent 40 min before the session"])
    assert audit.score_link(plain, linked("email", t(80)), idf) == \
        (0.1, ["email sent 50 min after the session"])
    assert audit.score_link(plain, linked("email", t(200)), idf) == (0.0, [])

    assert audit.score_link(plain, linked("chat", t(35), t(36)), idf) == \
        (0.15, ["chat while the session was active"])
    assert audit.score_link(plain, linked("chat", t(100)), idf) == (0.0, [])
    # no stamps: falls back to the start
    nostamps = dict(plain, _stamps=None)
    assert audit.score_link(nostamps, linked("chat", t(0)), idf)[0] == 0.15


def test_link_subject(audit):
    s = {"_status": "standalone", "subject": "s", "_clean": "clean"}
    e = {"_status": "inferred", "subject": "e"}
    assert audit.link_subject(s, e) == "e"
    assert audit.link_subject(dict(s, _status="confirmed"), e) == "s"
    assert audit.link_subject(s, dict(e, _status="standalone")) == "clean"


def test_candidate_links(audit):
    t = lambda m: local(2026, 9, 9, 10) + dt.timedelta(minutes=m)
    idf = audit.idf_table([{"a"}, {"b"}, {"c"}, {"d"}, {"e"}])
    stamps = [t(0), t(30)]
    s1 = linked("claude", t(0), t(30), jira={"A-1"}, stamps=stamps, lkey="s1", worked=600)
    s2 = linked("claude", t(0), t(30), stamps=stamps, lkey="s2", worked=600)
    short = linked("claude", t(0), jira={"A-1"}, stamps=stamps, lkey="short", worked=60)
    # two mails in one subject -> one candidate carrying both events
    m1 = linked("email", t(10), subject="thread", jira={"A-1"}, lkey="m1")
    m2 = linked("email", t(15), subject="thread", jira={"A-1"}, lkey="m2")
    reply = linked("meeting", t(5), t(10), title="Accepted: Review", jira={"A-1"}, lkey="r")
    far = linked("email", t(60 * 40), jira={"A-1"}, subject="far", lkey="far")
    weak = linked("chat", t(500), subject="weak", lkey="weak")
    items = [s1, s2, short, m2, m1, dict(m1), reply, far, weak]
    cands = audit.candidate_links(items, {}, idf)
    assert len(cands) == 1
    c = cands[0]
    assert c["session"] is s1  # s2 pairs with the thread more weakly: the stronger pairing wins
    assert [e["_lkey"] for e in c["events"]] == ["m1", "m2"]
    assert c["score"] == 0.75


def test_candidate_links_skips_rejected_and_decided(audit):
    t = lambda m: local(2026, 9, 9, 10) + dt.timedelta(minutes=m)
    idf = audit.idf_table([{"a"}])
    s = linked("claude", t(0), t(30), jira={"A-1"}, stamps=[t(0), t(30)], lkey="s", worked=600,
               subject="S")
    rejected = linked("email", t(10), subject="rej", jira={"A-1"}, lkey="rej")
    same = linked("email", t(10), subject="S", status="confirmed", jira={"A-1"}, lkey="same")
    other = linked("email", t(10), subject="O", status="confirmed", jira={"A-1"}, lkey="other")
    led = {"reject": [["s", "rej"]]}
    assert [c["events"][0]["_lkey"] for c in audit.candidate_links([s, rejected, same, other], led, idf)] == ["other"]
    decided = dict(s, _status="confirmed")
    assert audit.candidate_links([decided, other], {}, idf) == []


def test_candidate_links_keeps_higher_score_for_same_key(audit):
    t = lambda m: local(2026, 9, 9, 10) + dt.timedelta(minutes=m)
    idf = audit.idf_table([{"a"}])
    s = linked("claude", t(0), t(30), jira={"A-1"}, stamps=[t(0), t(30)], lkey="s", worked=600)
    weaker = linked("email", t(200), subject="th", jira={"A-1"}, lkey="e1")   # 0.6
    stronger = linked("email", t(10), subject="th", jira={"A-1"}, lkey="e2")  # 0.75
    cands = audit.candidate_links([s, weaker, stronger], {}, idf)
    assert len(cands) == 1 and cands[0]["score"] == 0.75
    assert cands[0]["why"][-1] == "email sent while the session was active"


# ------------------------------------------------------------------ tasks

def test_task_vocab_and_jira_match(audit):
    led = audit.empty_ledger()
    led["subjects"] = {"x": {"subject": "Firewall rules", "task": "Net"}, "y": {"subject": "Other"}}
    assert audit.task_vocab({"task": "Net", "keywords": ["subnet"]}, led) == {"net", "subnet", "fw", "rule"}
    idf = audit.idf_table([{"fw"}, {"subnet"}, {"a"}, {"b"}, {"c"}])
    issues = [{"key": "A-1", "summary": "fw subnet"}, {"key": "A-2", "summary": "fw"},
              {"key": "A-3"}]
    best = audit.jira_match({"fw"}, issues, idf)
    assert best["key"] == "A-2" and best["sim"] == 1.0 and best["words"] == ["fw"]
    assert audit.jira_match({"zzz"}, issues, idf) is None


def test_candidate_tasks(audit):
    led = audit.empty_ledger()
    led["tasks"] = [
        {"task": "Ticketed", "tickets": ["A-1"]},
        {"task": "By words", "keywords": ["firewall"]},
        {"task": "Via jira", "tickets": ["A-5"]},
        {"task": "Nothing"},
    ]
    idf = audit.idf_table([{"fw"}, {"a"}, {"b"}, {"c"}, {"d"}])
    group = [{"source": "claude", "_title_tok": {"fw", "subnet"}, "_jira": {"A-1"},
              "_folder": "/home/repos/proj/x"},
             {"source": "email", "_title_tok": set(), "_jira": set()}]
    issues = [{"key": "A-5", "summary": "fw subnet"}]
    ranked, jira = audit.candidate_tasks({"group": group, "name": "Firewall change"}, led, issues, idf)
    assert jira["key"] == "A-5"
    names = [r["task"] for r in ranked]
    assert names[0] == "Ticketed" and ranked[0]["ticket"] == "A-1" and ranked[0]["score"] == 0.7
    assert len(ranked) == 3 and "Nothing" not in names
    by = {r["task"]: r for r in ranked}
    assert by["Via jira"]["ticket"] == "A-5" and by["Via jira"]["why"][0].startswith("matches A-5")
    assert by["By words"]["why"] == ["keywords: fw"] and by["By words"]["score"] == 0.3


def test_candidate_tasks_ticket_fallbacks(audit):
    led = audit.empty_ledger()
    led["tasks"] = [{"task": "P", "paths": ["proj"], "default_ticket": "A-9"},
                    {"task": "Q", "paths": ["proj"], "tickets": ["B-2"]},
                    {"task": "R", "paths": ["proj"]}]
    idf = audit.idf_table([{"a"}])
    group = [{"source": "claude", "_title_tok": set(), "_jira": set(), "_folder": "/x/proj"}]
    ranked, jira = audit.candidate_tasks({"group": group, "name": ""}, led, [], idf)
    assert jira is None
    assert {r["task"]: r["ticket"] for r in ranked} == {"P": "A-9", "Q": "B-2", "R": "Other"}
    assert ranked[0]["why"] == ["session under .../proj"]
    # an unregistered key in the group becomes the ticket
    group[0]["_jira"] = {"Z-1", "Y-1"}
    ranked, _ = audit.candidate_tasks({"group": group, "name": ""}, led, [], idf)
    assert {r["ticket"] for r in ranked} == {"Y-1"}


def test_leave_days(audit):
    days = [dt.date(2026, 9, 7), dt.date(2026, 9, 8), dt.date(2026, 9, 9)]
    items = [
        {"source": "leave", "_start": local(2026, 9, 7, 0), "_end": local(2026, 9, 8, 13)},
        {"source": "leave", "_start": local(2026, 9, 7, 10), "_end": local(2026, 9, 7, 11)},  # overlap
        {"source": "leave", "_start": local(2026, 9, 9, 9)},  # instant
        {"source": "meeting", "_start": local(2026, 9, 9, 9), "_end": local(2026, 9, 9, 17)},
    ]
    assert audit.leave_days(items, days) == [(dt.date(2026, 9, 7), 1.0), (dt.date(2026, 9, 8), 0.5)]
