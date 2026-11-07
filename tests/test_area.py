"""bin/claude-area: real git in a throwaway HOME; the model call and t3 are stubbed."""

import csv
import json
import os
import subprocess
import types

import pytest

from conftest import load_script


@pytest.fixture
def area(home):
    stub = home / "t3-stub"
    stub.write_text('#!/bin/sh\necho "$*" >> "{}"\n[ -e "{}" ] && {{ cat "{}" >&2; exit 1; }}\nexit 0\n'.format(
        home / "t3.log", home / "t3-fail", home / "t3-fail"))
    stub.chmod(0o755)
    conf = home / ".config" / "claude-worksessions" / "config.env"
    conf.write_text(conf.read_text() + 'CWS_PROJECTS="contact360, new-data-sources"\n'
                    'CWS_TYPES="data access investigation"\nCWS_T3_BIN="{}"\n'.format(stub))
    return load_script("claude-area")


def request(home, name="10-00-00_x", day="06", **meta):
    d = home / "work_sessions" / "2026" / "11" / day / name
    d.mkdir(parents=True)
    (d / ".session.json").write_text(json.dumps(dict({"name": "x", "ticket": "Other", "profile": "personal"}, **meta)))
    return d


def remote(path):
    return subprocess.run(["git", "-C", str(path), "remote", "get-url", "origin"], capture_output=True,
                          text=True, check=True).stdout.strip()


def meta(path):
    return json.loads((path / ".session.json").read_text())


def test_a_project_is_one_heading_whatever_the_type(home, area):
    a, b = request(home, "10-00-00_a"), request(home, "10-05-00_b")
    area.place(str(a), "contact360", "data")
    area.place(str(b), "contact360", "access")
    assert remote(a) == remote(b) == "https://sessions.invalid/sessions/contact360.git"
    assert meta(a)["project"] == "contact360" and meta(a)["front"] == "data"
    assert meta(a)["ticket"] == "Other"


def test_ad_hoc_has_a_heading_per_type(home, area):
    a, b = request(home, "10-00-00_a"), request(home, "10-05-00_b")
    assert area.place(str(a), "ad-hoc", "data") == "ad-hoc/data"
    area.place(str(b), "ad-hoc", "access")
    assert remote(a) == "https://sessions.invalid/ad-hoc/data.git"
    assert remote(b) == "https://sessions.invalid/ad-hoc/access.git"


def test_toplevel_stays_the_request_folder(home, area):
    a = request(home)
    area.place(str(a), "contact360", "data")
    top = subprocess.run(["git", "-C", str(a), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
    assert os.path.realpath(top.stdout.strip()) == os.path.realpath(str(a))


def test_changing_only_the_pointer(home, area, capsys):
    d = request(home)
    (d / "work.txt").write_text("keep")
    area.place(str(d), "ad-hoc", "data")
    area.main(["--dir", str(d), "contact360"])
    assert remote(d).endswith("/sessions/contact360.git")
    assert meta(d)["front"] == "data"
    assert (d / "work.txt").read_text() == "keep" and not (d / ".git.tmp").exists()
    assert "Thread title: [data] x" in capsys.readouterr().out


def test_type_alone_keeps_the_project(home, area, capsys):
    d = request(home, ticket="BTPA-1")
    area.place(str(d), "contact360", "data")
    area.main(["--dir", str(d), "--type", "access"])
    assert meta(d)["project"] == "contact360" and meta(d)["front"] == "access"
    assert "Thread title: [access] BTPA-1 · x" in capsys.readouterr().out


def test_type_alone_on_an_unplaced_request_is_ad_hoc(home, area):
    d = request(home)
    area.main(["--dir", str(d), "--type", "access"])
    assert remote(d).endswith("/ad-hoc/access.git")


def test_project_alone_on_an_unplaced_request_uses_the_fallback_type(home, area):
    d = request(home)
    area.place(str(d), "contact360")
    assert meta(d)["front"] == "investigation"


def test_none_takes_it_out(home, area, capsys):
    d = request(home)
    area.place(str(d), "contact360", "data")
    area.main(["--dir", str(d), "none"])
    assert not (d / ".git").exists()
    assert "project" not in meta(d) and "front" not in meta(d)
    area.clear(str(d))          # already out: still fine


def test_an_old_area_key_is_dropped(home, area):
    d = request(home, area="governance-access")
    area.place(str(d), "ad-hoc", "access")
    assert "area" not in meta(d)


@pytest.mark.parametrize("project,front,match", [("nope", "data", "contact360, new-data-sources, ad-hoc"),
                                                  ("ad-hoc", "nope", "data, access, investigation")])
def test_unknown_names_list_the_valid_ones(home, area, project, front, match):
    with pytest.raises(SystemExit, match=match):
        area.place(str(request(home)), project, front)


def test_a_real_repository_is_left_alone(home, area):
    d = request(home)
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    with pytest.raises(SystemExit, match="own .git"):
        area.place(str(d), "ad-hoc", "data")
    assert (d / ".git").is_dir()


def test_a_foreign_pointer_is_left_alone(home, area):
    d = request(home)
    (d / ".git").write_text("gitdir: /somewhere/else.git\n")
    with pytest.raises(SystemExit, match="own .git"):
        area.clear(str(d))
    assert (d / ".git").exists()


def test_the_exclude_list_keeps_noise_out_of_snapshots(home, area):
    d = request(home)
    area.place(str(d), "ad-hoc", "data")
    (d / ".scope.json").write_text("{}")
    (d / "big.parquet").write_text("x")
    (d / "export.csv").write_text("x")
    (d / "notes.md").write_text("x")
    out = subprocess.run(["git", "-C", str(d), "status", "--short"], capture_output=True, text=True, check=True).stdout
    assert "notes.md" in out and "parquet" not in out and "csv" not in out and "scope" not in out


def test_outside_a_request_folder(home, area):
    with pytest.raises(SystemExit, match="not inside a request folder"):
        area.request_dir(str(home))
    with pytest.raises(SystemExit, match="not inside a request folder"):
        area.request_dir(str(home / "work_sessions"))


def test_subfolder_finds_its_request(home, area):
    d = request(home)
    (d / "sub").mkdir()
    assert area.request_dir(str(d / "sub")) == os.path.realpath(str(d))


def test_pick_takes_the_project_from_the_ticket_and_the_type_from_the_model(home, area, monkeypatch, capsys):
    area.place(str(request(home, "09-00-00_old", day="01", ticket="BTPA-1")), "contact360", "data")
    d = request(home, ticket="BTPA-1")
    monkeypatch.setattr(area, "from_model", lambda m: ("new-data-sources", "access"))
    area.main(["--dir", str(d), "--pick"])
    assert meta(d)["project"] == "contact360" and meta(d)["front"] == "access"
    assert capsys.readouterr().out == "Group: sessions/contact360\n"


def test_pick_uses_the_model_for_a_ticketless_request(home, area, monkeypatch, capsys):
    d = request(home)
    monkeypatch.setattr(area, "from_model", lambda m: ("ad-hoc", "data"))
    area.pick(str(d))
    assert remote(d).endswith("/ad-hoc/data.git")


def test_pick_with_no_answer_falls_back(home, area, monkeypatch, capsys):
    d = request(home)
    monkeypatch.setattr(area, "from_model", lambda m: ("", ""))
    area.pick(str(d))
    assert remote(d).endswith("/ad-hoc/investigation.git")


def test_pick_with_both_given_asks_nobody(home, area, monkeypatch):
    d = request(home)
    monkeypatch.setattr(area, "from_model", lambda m: pytest.fail("nothing to choose"))
    area.main(["--dir", str(d), "--pick", "contact360", "--type", "data"])
    assert meta(d)["project"] == "contact360"


def test_pick_keeps_a_request_already_placed(home, area, monkeypatch):
    d = request(home, project="contact360", front="data")
    monkeypatch.setattr(area, "from_model", lambda m: pytest.fail("nothing to choose"))
    area.pick(str(d))


def test_pick_is_silent_with_no_types_configured(home, capsys):
    mod = load_script("claude-area")
    d = request(home)
    mod.pick(str(d))
    assert "project" not in meta(d) and capsys.readouterr().out == ""


def test_pick_never_stops_claude_new(home, area, monkeypatch, capsys):
    d = request(home)
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    monkeypatch.setattr(area, "from_model", lambda m: ("ad-hoc", "data"))
    area.pick(str(d))
    assert "own .git" in capsys.readouterr().err


def run_model(area, monkeypatch, out=None, boom=None):
    calls = {}

    def fake(cmd, **kw):
        calls.update(cmd=cmd, env=kw["env"], stdin=kw["stdin"])
        if boom:
            raise boom
        return types.SimpleNamespace(stdout=out)

    monkeypatch.setattr(area.subprocess, "run", fake)
    return area.from_model({"name": "n", "goal": "g", "profile": "work"}), calls


def test_model_answer_is_used_and_runs_on_the_profile(home, area, monkeypatch):
    got, calls = run_model(area, monkeypatch, json.dumps({"structured_output": {"project": "contact360", "type": "data"}}))
    assert got == ("contact360", "data")
    assert calls["env"]["CLAUDE_CONFIG_DIR"].endswith(".claude-work")
    assert calls["stdin"] == subprocess.DEVNULL


@pytest.mark.parametrize("out", ["", "not json", '{"structured_output": "x"}',
                                 '{"structured_output": {"project": "made-up", "type": "made-up"}}'])
def test_model_bad_answers_mean_nothing_chosen(home, area, monkeypatch, out):
    assert run_model(area, monkeypatch, out)[0] == ("", "")


def test_model_timeout_means_nothing_chosen(home, area, monkeypatch):
    assert run_model(area, monkeypatch, boom=subprocess.TimeoutExpired("claude", 1))[0] == ("", "")


def test_broken_session_file(home, area):
    d = request(home)
    (d / ".session.json").write_text("[]")
    assert area.read_meta(str(d)) == {}
    (d / ".session.json").write_text("{")
    assert area.read_meta(str(d)) == {}


def test_show(home, area, capsys):
    d = request(home)
    area.main(["--dir", str(d)])
    assert "This request: (ungrouped)" in capsys.readouterr().out
    area.place(str(d), "ad-hoc", "access")
    area.main(["--dir", str(d)])
    out = capsys.readouterr().out
    assert "contact360, new-data-sources, ad-hoc" in out and "This request: ad-hoc/access" in out
    area.main(["--dir", str(home)])
    assert "This request" not in capsys.readouterr().out


def test_gc(home, area, capsys):
    area.main(["--gc"])
    assert "Nothing stored" in capsys.readouterr().out
    area.place(str(request(home)), "ad-hoc", "data")
    area.main(["--gc"])
    assert "ad-hoc/data" in capsys.readouterr().out


def test_git_failure_is_reported(home, area):
    with pytest.raises(SystemExit, match="failed"):
        area.git("--git-dir", "/nonexistent", "gc")


def test_ticket_index_keeps_the_latest_project_and_skips_ad_hoc(home, area):
    area.place(str(request(home, "09-00-00_a", ticket="BTPA-1")), "contact360", "data")
    area.place(str(request(home, "09-05-00_b", ticket="BTPA-1")), "new-data-sources", "data")
    area.place(str(request(home, "09-10-00_c", ticket="BTPA-2")), "ad-hoc", "data")
    area.place(str(request(home, "09-15-00_d")), "contact360", "data")
    assert area.read_index() == {"BTPA-1": "new-data-sources"}
    assert area.from_ticket("BTPA-2") == "" and area.from_ticket(None) == ""


def test_ticket_index_drops_a_project_no_longer_configured(home, area):
    area.remember("BTPA-1", "retired")
    assert area.from_ticket("BTPA-1") == ""


@pytest.mark.parametrize("text", ["[]", "{"])
def test_broken_ticket_index_is_ignored(home, area, text):
    os.makedirs(area.store())
    with open(area.ticket_index(), "w") as fh:
        fh.write(text)
    assert area.read_index() == {}


def test_first_use_adds_a_hidden_anchor_once(home, area):
    area.place(str(request(home, "10-00-00_a")), "contact360", "data")
    area.place(str(request(home, "10-05-00_b")), "contact360", "access")
    folder = os.path.join(area.store(), "anchors", "sessions--contact360")
    assert (home / "t3.log").read_text().splitlines() == ["project add {} --title sessions/contact360".format(folder)]
    assert remote(folder).endswith("/sessions/contact360.git")


def test_anchors_covers_every_heading_and_an_existing_project_counts(home, area):
    (home / "t3-fail").write_text("ProjectAlreadyExistsError")
    area.main(["--anchors"])
    calls = (home / "t3.log").read_text()
    assert len(calls.splitlines()) == 5
    assert "--title sessions/new-data-sources" in calls and "--title ad-hoc/investigation" in calls
    assert os.path.exists(os.path.join(area.store(), "anchors", "ad-hoc--data", ".t3-added"))


def test_t3_failure_does_not_stop_it_and_is_retried(home, area, capsys):
    (home / "t3-fail").write_text("server down")
    d = request(home)
    area.place(str(d), "ad-hoc", "data")
    assert remote(d).endswith("/ad-hoc/data.git")
    assert "no T3 heading yet: server down" in capsys.readouterr().err
    (home / "t3-fail").unlink()
    area.place(str(d), "ad-hoc", "data")
    assert len((home / "t3.log").read_text().splitlines()) == 2


def test_t3_missing_is_only_a_warning(home, area, monkeypatch, capsys):
    monkeypatch.setattr(area, "t3_command", lambda: "/nonexistent/t3")
    area.ensure_anchor("ad-hoc/data")
    assert "no T3 heading yet" in capsys.readouterr().err


def test_t3_command_falls_back_to_its_home(home):
    mod = load_script("claude-area")
    assert mod.t3_command().endswith(os.path.join(".t3", "bin", "t3")) or mod.shutil.which("t3")


def write_list(path, rows):
    with open(path, "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=["project", "type", "folder"])
        w.writeheader()
        w.writerows(rows)


def test_backfill_dry_run_changes_nothing(home, area, capsys):
    d = request(home)
    lst = home / "list.csv"
    write_list(lst, [{"project": "contact360", "type": "data", "folder": str(d)}, {"project": "", "type": "", "folder": "x"}])
    area.main(["--backfill", str(lst)])
    assert not (d / ".git").exists()
    out = capsys.readouterr().out
    assert "sessions/contact360" in out and "1 requests. Nothing changed" in out


def test_backfill_apply_then_undo(home, area, capsys):
    a, b, gone = request(home, "10-00-00_a"), request(home, "10-05-00_b", project="contact360", front="data"), home / "gone"
    bad = request(home, "10-10-00_c")
    lst = home / "list.csv"
    write_list(lst, [{"project": "contact360", "type": "data", "folder": str(a)},
                     {"project": "ad-hoc", "type": "access", "folder": str(b)},
                     {"project": "ad-hoc", "type": "access", "folder": str(gone)},
                     {"project": "nope", "type": "data", "folder": str(bad)}])
    area.main(["--backfill", str(lst), "--apply"])
    captured = capsys.readouterr()
    assert remote(a).endswith("/sessions/contact360.git")
    assert meta(b)["project"] == "contact360"           # placed since the list was made: kept
    assert "no project 'nope'" in captured.err
    assert "Placed 1 of 4" in captured.out
    log = captured.out.split("--undo ")[1].strip()
    area.main(["--undo", log])
    assert not (a / ".git").exists() and "project" not in meta(a)
