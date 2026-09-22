"""bin/claude-search: indexing transcripts, ranking, and the CLI."""

import io
import json
import os
import subprocess
import sys

import pytest


# ---------------------------------------------------------------- helpers

def rec(kind, ts, content=None, **extra):
    r = {"type": kind, "timestamp": ts}
    if content is not None:
        r["message"] = {"content": content}
    r.update(extra)
    return r


def write_transcript(home, sid, records, profile="personal", project="proj"):
    d = home / (".claude-" + profile) / "projects" / project
    d.mkdir(parents=True, exist_ok=True)
    p = d / (sid + ".jsonl")
    p.write_text("\n".join(r if isinstance(r, str) else json.dumps(r) for r in records) + "\n")
    return p


def session_dir(home, name, **meta):
    d = home / "work_sessions" / "2026" / "09" / "21" / name
    d.mkdir(parents=True, exist_ok=True)
    if meta:
        (d / ".session.json").write_text(json.dumps(meta))
    return d


def make_doc(search, sid, title="", prompts="", assistant="", tools="", cwd="/nowhere/x",
             start="2026-09-21T10:00:00+01:00", end="2026-09-21T11:00:00+01:00", worked=1800.0):
    folder = " ".join(cwd.rstrip("/").split("/")[-2:])
    raw = {"title": title, "prompts": prompts, "assistant": assistant, "tools": tools, "folder": folder}
    return {"session_id": sid, "cwd": cwd, "title": title, "start": start, "end": end, "worked": worked,
            "tf": {f: dict(search.terms(t)) for f, t in raw.items()},
            "keys": {f: search.ticket_keys(t) for f, t in raw.items()},
            "snip": {"prompts": prompts, "assistant": assistant}}


def run_main(search, monkeypatch, *argv):
    monkeypatch.setattr(sys, "argv", ["claude-search", *argv])
    search.main()


# ---------------------------------------------------------------- module loading

def test_load_audit_falls_back_to_local_bin(search, home, monkeypatch):
    real = os.path.join(os.path.dirname(search.__spec__.loader.path), "claude-audit")
    local = home / ".local" / "bin"
    local.mkdir(parents=True)
    os.symlink(real, local / "claude-audit")
    isfile = os.path.isfile
    monkeypatch.setattr(os.path, "isfile", lambda p: False if p == real else isfile(p))
    mod = search.load_audit()
    assert mod.__spec__.loader.path == str(local / "claude-audit")
    assert callable(mod.read_session)


# ---------------------------------------------------------------- tokenising

def test_terms_stems_and_drops_noise(search):
    t = search.terms("Firewall rules 2026 the ab BI permissions permissions")
    assert t["fw"] == 1            # synonym
    assert t["rule"] == 1          # stemmed
    assert t["permission"] == 2
    assert t["bi"] == 1            # short but kept
    assert "2026" not in t and "the" not in t and "ab" not in t
    assert search.terms(None) == {}


def test_ticket_keys_dedupes_uppercases_and_denies(search):
    assert search.ticket_keys("btpa-7959 and BTPA-7959, UTF-8, ABC-1") == ["ABC-1", "BTPA-7959"]
    assert search.ticket_keys(None) == []


# ---------------------------------------------------------------- extract

def test_extract_reads_fields_and_skips_noise(search, home):
    moved_old, moved_new = "/old/place", str(home / "work_sessions" / "new")
    out = home / "work_sessions" / "_audit"
    out.mkdir(parents=True)
    (out / "moved-folders.json").write_text(json.dumps({moved_old: moved_new}))
    p = write_transcript(home, "sid-1", [
        "not json",
        rec("user", "2026-09-21T09:00:00Z", "sidechain words", isSidechain=True, cwd="/elsewhere"),
        rec("user", "2026-09-21T09:00:05Z", "Fix firewall for BTPA-12", cwd=moved_old + "/sub", promptId="p1"),
        rec("user", "2026-09-21T09:00:06Z", "<command>ignored</command>"),
        rec("user", "2026-09-21T09:00:07Z", "meta text", isMeta=True),
        rec("user", "2026-09-21T09:01:00Z", [
            "not a dict",
            {"type": "text", "text": "check subnet routing"},
            {"type": "text", "text": "<system>skip</system>"},
            {"type": "tool_result", "content": "result string output"},
            {"type": "tool_result", "content": [{"text": "listed"}, "junk", {"type": "image"}]},
            {"type": "tool_result"},
        ], promptId="p2"),
        rec("assistant", "2026-09-21T09:02:00Z", [
            "junk", {"type": "text", "text": "The NSG blocks egress"}, {"type": "text"},
            {"type": "tool_use", "input": {"command": "az network nsg list"}},
            {"type": "thinking"},
        ]),
        rec("assistant", "2026-09-21T09:03:00Z", "plain string content ignored"),
        {"type": "ai-title", "aiTitle": "Firewall egress for Databricks"},
    ])
    doc = search.extract(str(p))
    assert doc["session_id"] == "sid-1"
    assert doc["title"] == "Firewall egress for Databricks"
    assert doc["cwd"] == moved_new + "/sub"
    assert doc["snip"]["prompts"] == "Fix firewall for BTPA-12\ncheck subnet routing"
    assert "sidechain" not in doc["snip"]["prompts"] and "meta" not in doc["snip"]["prompts"]
    assert doc["snip"]["assistant"] == "The NSG blocks egress\n"
    assert doc["keys"]["prompts"] == ["BTPA-12"]
    assert "list" in doc["tf"]["tools"] and "nsg" in doc["tf"]["tools"]
    assert doc["tf"]["folder"] == {"sub": 1}          # "new" is a stopword
    assert doc["start"].startswith("2026-09-21") and doc["worked"] > 0


def test_extract_title_falls_back_to_opening_prompt(search, home):
    p = write_transcript(home, "sid-2", [
        rec("user", "2026-09-21T09:00:00Z", "line one\nline two " + "x" * 100, promptId="p"),
        rec("assistant", "2026-09-21T09:00:30Z", [{"type": "text", "text": "ok"}]),
    ])
    doc = search.extract(str(p))
    assert doc["title"].startswith("line one line two")
    assert len(doc["title"]) == 80


def test_extract_returns_none_without_timestamps(search, home):
    p = write_transcript(home, "sid-3", [{"type": "user", "message": {"content": "hi"}}])
    assert search.extract(str(p)) is None


# ---------------------------------------------------------------- index cache

def test_build_index_caches_and_rebuilds(search, home):
    write_transcript(home, "a", [rec("user", "2026-09-21T09:00:00Z", "alpha work", promptId="1")])
    write_transcript(home, "empty", [{"type": "summary"}], profile="work")
    docs, changed = search.build_index()
    assert changed == 2 and [d["session_id"] for d in docs] == ["a"]
    assert json.load(open(search.CACHE))["version"] == search.INDEX_VERSION

    docs, changed = search.build_index()          # nothing new: served from cache ...
    assert changed == 1 and len(docs) == 1        # ... except the doc-less file, re-read each time

    cache = json.load(open(search.CACHE))
    cache["version"] = 0
    json.dump(cache, open(search.CACHE, "w"))
    assert search.build_index()[1] == 2           # old index version: everything re-read

    open(search.CACHE, "w").write("{broken")
    assert search.build_index()[1] == 2


def test_build_index_nothing_changed_does_not_write(search, home):
    assert search.build_index() == ([], 0)
    assert not os.path.exists(search.CACHE)


# ---------------------------------------------------------------- ledger / activity

def test_linked_activity(search, home):
    assert search.linked_activity(search.CA.empty_ledger()) == {}
    act = home / "work_sessions" / "_audit" / "activity"
    act.mkdir(parents=True)
    assert search.linked_activity(search.CA.empty_ledger()) == {}      # dir with no json
    (act / "2026-09-21.json").write_text(json.dumps([
        {"source": "meeting", "start": "2026-09-21T10:00:00", "title": "Firewall review",
         "detail": "egress rules", "counterparties": ["Ana"]},
        {"source": "email", "start": "2026-09-21T11:00:00", "title": "Unlinked"},
    ]))
    rows, _ = search.CA.load_activity(str(act))
    key = search.CA.stable_id("evt_", "meeting", rows[0]["start"], "Firewall review")
    ledger = search.CA.empty_ledger()
    ledger["assign"][key] = {"subject": "Network"}
    got = search.linked_activity(ledger)
    assert list(got) == ["Network"]
    label, text = got["Network"][0]
    assert label == "meeting Firewall review"
    assert "egress rules" in text and "Ana" in text and text.endswith("Firewall review")


def test_booking(search):
    CA = search.CA
    ledger = CA.empty_ledger()
    doc = {"session_id": "s1", "title": "RE: Firewall - review"}
    assert search.booking(doc, ledger, {}) == ("Firewall review", "", "")

    ledger["assign"]["s1"] = {"subject": "Network"}
    ledger["subjects"][CA.stable_id("sub_", "Network")] = {"task": "Infra", "ticket": ""}
    assert search.booking(doc, ledger, {}) == ("Network", "Infra", "Other")
    tasks = {"Infra": {"default_ticket": "BTPA-1"}}
    assert search.booking(doc, ledger, tasks) == ("Network", "Infra", "BTPA-1")
    ledger["subjects"][CA.stable_id("sub_", "Network")]["ticket"] = "BTPA-9"
    assert search.booking(doc, ledger, tasks) == ("Network", "Infra", "BTPA-9")


def test_snippet(search):
    long_pre = "word " * 30
    doc = {"snip": {"prompts": long_pre + "the firewalls are down " + "tail " * 40, "assistant": ""}}
    s = search.snippet(doc, {"firewall"})
    assert s.startswith('you: "…') and s.endswith('…"') and "firewalls" in s
    doc = {"snip": {"prompts": "", "assistant": "subnet ok"}}
    assert search.snippet(doc, {"sub", "subnet"}) == 'claude: "subnet ok"'
    assert search.snippet(doc, set()) == ""
    assert search.snippet(doc, {"zzz"}) == ""


# ---------------------------------------------------------------- ranking

def test_search_words_levels_expansion_and_phrase(search):
    docs = [
        make_doc(search, "strong", title="Login failures on portal", prompts="login failures on portal again"),
        make_doc(search, "related", assistant="the sso token expired " + "filler words " * 40),
        make_doc(search, "tools-only", tools="credentials rotated"),       # expansion ignored in tools
        make_doc(search, "none", title="Cost report"),
    ]
    results, keys = search.search("login failures login", docs, search.CA.empty_ledger(), {}, {})
    assert keys == set()
    ids = [r["doc"]["session_id"] for r in results]
    assert ids[0] == "strong" and "none" not in ids and "tools-only" not in ids
    top = results[0]
    assert top["level"] == "strong"
    assert any(w.startswith("title: ") for w in top["why"])
    assert top["snippet"].startswith("you:")
    rel = next(r for r in results if r["doc"]["session_id"] == "related")
    assert rel["level"] in ("likely", "possible")
    assert "Claude's replies: sso" in rel["why"]
    # phrase bonus
    solo = [make_doc(search, "p", title="x", prompts="login failures")]
    with_phrase = search.search("login failures", solo, search.CA.empty_ledger(), {}, {})[0][0]["score"]
    without = search.search("failures login", solo, search.CA.empty_ledger(), {}, {})[0][0]["score"]
    assert with_phrase == pytest.approx(without + 6.0)


def test_search_levels_possible(search):
    docs = [make_doc(search, "big", title="vnet vnet vnet peering", prompts="vnet peering vnet"),
            make_doc(search, "tiny", assistant="network " + "padding " * 200)]
    res = {r["doc"]["session_id"]: r["level"] for r in
           search.search("vnet", docs, search.CA.empty_ledger(), {}, {})[0]}
    assert res == {"big": "strong", "tiny": "possible"}


def test_search_ticket_tiers(search, home):
    CA = search.CA
    declared = session_dir(home, "decl", ticket="btpa-7", profile="work")
    docs = [
        make_doc(search, "declared", title="Something", cwd=str(declared)),
        make_doc(search, "booked", title="Booked thing"),
        make_doc(search, "mentioned", prompts="working on BTPA-7 now"),
        make_doc(search, "passing", assistant="see BTPA-7 later"),
        make_doc(search, "linked", title="Network work"),
        make_doc(search, "summary-words", title="Databricks egress design"),
        make_doc(search, "nothing", title="Unrelated"),
    ]
    ledger = CA.empty_ledger()
    ledger["tasks"] = [{"task": "Infra"}]
    ledger["assign"]["booked"] = {"subject": "Booked"}
    ledger["subjects"][CA.stable_id("sub_", "Booked")] = {"task": "Infra", "ticket": "BTPA-7"}
    ledger["assign"]["linked"] = {"subject": "Network"}
    linked = {"Network": [("meeting Egress sync", "egress chat about BTPA-7 Egress sync"),
                          ("email Other", "nothing here")]}
    jira = {"BTPA-7": {"key": "BTPA-7", "summary": "Databricks egress"}}
    results, keys = search.search("btpa-7", docs, ledger, jira, linked)
    assert keys == {"BTPA-7"}
    by = {r["doc"]["session_id"]: r for r in results}
    assert "nothing" not in by
    assert by["declared"]["level"] == "on ticket"
    assert by["declared"]["why"][0] == "declared BTPA-7 with claude-new"
    assert by["declared"]["profile"] == "work"
    assert by["booked"]["why"][0] == "booked to BTPA-7 in the weekly review"
    assert by["booked"]["doc"]["_task"] == "Infra"
    assert by["mentioned"]["why"][0] == "you mention BTPA-7"
    assert by["passing"]["level"] == "mentioned"
    assert by["linked"]["level"] == "mentioned"
    assert "linked: meeting Egress sync" in by["linked"]["why"]
    assert by["summary-words"]["level"] == "related"
    assert by["summary-words"]["profile"] == "unknown"
    order = [r["level"] for r in results]
    assert order == sorted(order, key=["on ticket", "mentioned", "related"].index)


def test_search_empty(search):
    assert search.search("anything", [], search.CA.empty_ledger(), {}, {}) == ([], set())


# ---------------------------------------------------------------- ai_rank

def _results(search, n):
    docs = [make_doc(search, "s%d" % i, title="login %d" % i, prompts="login") for i in range(n)]
    for d in docs:
        d.update(_ticket="", _task="")
    return [{"doc": d, "why": ["title: login"], "snippet": "", "level": "strong", "score": 1} for d in docs]


def test_ai_rank_orders_by_claude(search, monkeypatch):
    res = _results(search, 3)
    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"], seen["input"] = cmd, kw["input"]
        return subprocess.CompletedProcess(cmd, 0, stdout='Sure: [{"n": 3, "why": "about login"}, {"n": 3},'
                                                           ' {"n": "x"}, {"why": "no n"}, {"n": 99}, {"n": 1}] done')
    monkeypatch.setattr(subprocess, "run", fake_run)
    ranked = search.ai_rank("login", res)
    assert seen["cmd"][:2] == ["claude", "-p"]
    assert "Query: 'login'" in seen["input"] and '"n": 1' in seen["input"]
    assert [r["doc"]["session_id"] for r in ranked] == ["s2", "s0"]
    assert ranked[0]["level"] == "claude"
    assert ranked[0]["why"] == ["about login", "title: login"]
    assert ranked[1]["why"][0] == ""


@pytest.mark.parametrize("behaviour", ["oserror", "nojson", "timeout"])
def test_ai_rank_falls_back(search, monkeypatch, capsys, behaviour):
    res = _results(search, 2)

    def fake_run(cmd, **kw):
        if behaviour == "oserror":
            raise OSError("claude: not found")
        if behaviour == "timeout":
            raise subprocess.TimeoutExpired(cmd, 240)
        return subprocess.CompletedProcess(cmd, 0, stdout="no array here")
    monkeypatch.setattr(subprocess, "run", fake_run)
    assert search.ai_rank("login", res) is res
    assert "Claude ranking unavailable" in capsys.readouterr().err


# ---------------------------------------------------------------- paths / resume

def test_paths_and_resume_cmd(search, home):
    assert search.short(str(home / "a")) == "~/a"
    assert search.shell_path(str(home / "My Docs" / "x(1)")) == r"~/My\ Docs/x\(1\)"
    assert search.shell_path("/opt/a b") == r"/opt/a\ b"
    r = {"profile": "work", "doc": {"cwd": str(home / "w s"), "session_id": "abc"}}
    assert search.launcher(r) == "claude-resume -p work"
    assert search.resume_cmd(r) == r"cd ~/w\ s && claude-resume -p work --resume abc"
    assert search.launcher({"profile": "unknown"}) == "claude"


def _pick(search, monkeypatch, answer):
    def fake_input(prompt):
        if isinstance(answer, BaseException):
            raise answer
        return answer
    monkeypatch.setattr("builtins.input", fake_input)


@pytest.mark.parametrize("answer", [EOFError(), KeyboardInterrupt(), "  "])
def test_pick_and_resume_skips(search, monkeypatch, capsys, answer):
    _pick(search, monkeypatch, answer)
    monkeypatch.setattr(os, "execvp", lambda *a: pytest.fail("should not exec"))
    assert search.pick_and_resume([{}]) is None


@pytest.mark.parametrize("answer", ["x", "0", "3"])
def test_pick_and_resume_rejects_bad_choice(search, monkeypatch, answer):
    _pick(search, monkeypatch, answer)
    with pytest.raises(SystemExit, match="no session " + answer):
        search.pick_and_resume([{}, {}])


def test_pick_and_resume_missing_folder(search, monkeypatch, home):
    _pick(search, monkeypatch, "1")
    r = {"profile": "work", "doc": {"cwd": str(home / "gone"), "session_id": "abc"}}
    with pytest.raises(SystemExit, match="folder no longer exists: ~/gone"):
        search.pick_and_resume([r])


@pytest.mark.parametrize("profile,config", [("personal", ".claude-personal"), ("unknown", None)])
def test_pick_and_resume_execs_claude(search, monkeypatch, capsys, home, profile, config):
    here = os.getcwd()
    folder = home / "sess"
    folder.mkdir()
    _pick(search, monkeypatch, "1")
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    calls = []
    monkeypatch.setattr(os, "execvp", lambda f, args: calls.append((f, args)))
    try:
        search.pick_and_resume([{"profile": profile, "doc": {"cwd": str(folder), "session_id": "abc"}}])
        assert os.getcwd() == os.path.realpath(folder)
    finally:
        os.chdir(here)
    assert calls == [("claude", ["claude", "--resume", "abc"])]
    assert os.environ.get("CLAUDE_CONFIG_DIR") == (str(home / config) if config else None)
    assert "--resume abc" in capsys.readouterr().out


# ---------------------------------------------------------------- main

@pytest.fixture
def corpus(search, home):
    """Two indexed sessions in claude-new folders, plus a jira cache."""
    fw = session_dir(home, "10-00-00_firewall", ticket="BTPA-7", profile="work")
    cost = session_dir(home, "11-00-00_cost", profile="personal")
    write_transcript(home, "fw1", [
        rec("user", "2026-09-10T09:00:00Z", "open the firewall for databricks", cwd=str(fw), promptId="1"),
        rec("assistant", "2026-09-10T09:20:00Z", [{"type": "text", "text": "firewall rule added"}], cwd=str(fw)),
        {"type": "ai-title", "aiTitle": "Firewall for Databricks"},
    ])
    write_transcript(home, "cost1", [
        rec("user", "2026-09-15T09:00:00Z", "monthly cost report", cwd=str(cost), promptId="1"),
        rec("assistant", "2026-09-16T09:10:00Z", [{"type": "text", "text": "done"}], cwd=str(cost)),
    ])
    review = home / "work_sessions" / "_audit" / "review"
    review.mkdir(parents=True)
    (review / "jira.json").write_text(json.dumps([{"key": "BTPA-7", "summary": "Egress firewall"}]))
    return home


def test_main_prints_results(search, corpus, monkeypatch, capsys):
    run_main(search, monkeypatch, "firewall", "--no-pick")
    out = capsys.readouterr().out
    assert out.startswith('claude-search "firewall" · 1 of 2 sessions')
    assert "Firewall for Databricks" in out
    assert "not booked yet" in out
    assert "claude-resume -p work --resume fw1" in out
    assert "Thu 10 Sep" in out


@pytest.mark.xfail(strict=True, reason="snippet() matches stems literally; synonyms (firewall -> fw) never match the text")
def test_snippet_for_synonym_word(search):
    doc = make_doc(search, "s", prompts="open the firewall for databricks")
    res = search.search("firewall", [doc], search.CA.empty_ledger(), {}, {})[0]
    assert res[0]["snippet"].startswith('you: "open the firewall')


def test_main_ticket_search_shows_jira_title(search, corpus, monkeypatch, capsys):
    run_main(search, monkeypatch, "BTPA-7", "--no-pick")
    out = capsys.readouterr().out
    assert out.startswith('claude-search "BTPA-7" (Egress firewall) · 1 of 2 sessions')
    assert "on ticket" in out and "declared BTPA-7 with claude-new" in out


def test_main_multi_day_span_and_booked(search, corpus, monkeypatch, capsys):
    CA = search.CA
    ledger = CA.empty_ledger()
    ledger["assign"]["cost1"] = {"subject": "Costs"}
    ledger["subjects"][CA.stable_id("sub_", "Costs")] = {"task": "FinOps", "ticket": "BTPA-3"}
    CA.save_ledger(CA.LEDGER_PATH, ledger)
    run_main(search, monkeypatch, "cost", "--no-pick")
    out = capsys.readouterr().out
    assert "FinOps / BTPA-3" in out
    assert "-16 Sep" in out                     # end on another day shows its date
    assert "snippet" not in out


def test_main_nothing_found(search, corpus, monkeypatch, capsys):
    run_main(search, monkeypatch, "kubernetes")
    assert "nothing found" in capsys.readouterr().out


def test_main_ai_judged_none(search, corpus, monkeypatch, capsys):
    monkeypatch.setattr(subprocess, "run",
                        lambda cmd, **kw: subprocess.CompletedProcess(cmd, 0, stdout="[]"))
    run_main(search, monkeypatch, "firewall", "--ai")
    assert "judged none to be about this" in capsys.readouterr().out


def test_main_date_filters_and_bad_date(search, corpus, monkeypatch, capsys):
    run_main(search, monkeypatch, "firewall", "--from", "2026-09-11", "--no-pick")
    assert "0 of 1 sessions" in capsys.readouterr().out
    run_main(search, monkeypatch, "cost", "--to", "2026-09-14", "--no-pick")
    assert "0 of 1 sessions" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="bad date"):
        run_main(search, monkeypatch, "cost", "--from", "yesterday")


def test_main_csv_stdout_and_file(search, corpus, monkeypatch, capsys, tmp_path):
    run_main(search, monkeypatch, "firewall", "--csv")
    lines = capsys.readouterr().out.splitlines()
    assert lines[0].startswith("rank,level,score,session_id")
    assert lines[1].startswith("1,strong,") and "fw1" in lines[1]
    target = tmp_path / "out.csv"
    run_main(search, monkeypatch, "firewall", "--csv", str(target))
    assert capsys.readouterr().out.strip() == str(target)
    assert "Firewall for Databricks" in target.read_text()


def test_main_many_indexed_and_all_and_limit(search, home, monkeypatch, capsys):
    for i in range(7):
        write_transcript(home, "s%d" % i, [
            rec("user", "2026-09-1%dT09:00:00Z" % i, "vnet peering %s" % ("vnet " * (20 * i)), promptId="1")])
    run_main(search, monkeypatch, "vnet", "--all", "--limit", "3", "--no-pick")
    cap = capsys.readouterr()
    assert "(indexed 7 sessions)" in cap.err
    assert "3 of 7 sessions" in cap.out


def test_main_ticket_filter_caps_mentions(search, home, monkeypatch, capsys):
    for i in range(5):
        write_transcript(home, "m%d" % i, [
            rec("user", "2026-09-1%dT09:00:00Z" % i, "hello", promptId="1"),
            rec("assistant", "2026-09-1%dT09:05:00Z" % i, [{"type": "text", "text": "see ABC-1"}])])
    run_main(search, monkeypatch, "ABC-1", "--no-pick")
    assert "3 of 5 sessions" in capsys.readouterr().out


def test_main_offers_resume_on_tty(search, corpus, monkeypatch, capsys):
    class TTY(io.StringIO):
        def isatty(self):
            return True
    monkeypatch.setattr(sys, "stdin", TTY())
    monkeypatch.setattr(sys.stdout, "isatty", lambda: True, raising=False)
    picked = []
    monkeypatch.setattr(search, "pick_and_resume", picked.append)
    run_main(search, monkeypatch, "firewall")
    assert len(picked) == 1 and picked[0][0]["doc"]["session_id"] == "fw1"
