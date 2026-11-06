"""bin/claude-area: real git in a throwaway HOME; the model call is stubbed."""

import json
import os
import subprocess
import types

import pytest

from conftest import load_script


@pytest.fixture
def area(home):
    conf = home / ".config" / "claude-worksessions" / "config.env"
    conf.write_text(conf.read_text() + 'CWS_AREAS="contact360, ingestion"\n')
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


def test_set_points_the_folder_at_the_area_and_records_it(home, area):
    d = request(home)
    area.main(["--dir", str(d), "ingestion"])
    assert (d / ".git").read_text() == "gitdir: {}\n".format(area.gitdir("ingestion"))
    assert remote(d) == "https://sessions.invalid/sessions/ingestion.git"
    assert meta(d)["area"] == "ingestion"
    assert meta(d)["ticket"] == "Other"


def test_two_requests_in_an_area_share_a_remote_and_toplevels_stay_apart(home, area):
    a, b = request(home, "10-00-00_a"), request(home, "10-05-00_b")
    area.set_area(str(a), "contact360")
    area.set_area(str(b), "contact360")
    assert remote(a) == remote(b)
    top = subprocess.run(["git", "-C", str(a), "rev-parse", "--show-toplevel"], capture_output=True, text=True, check=True)
    assert os.path.realpath(top.stdout.strip()) == os.path.realpath(str(a))


def test_changing_area_only_rewrites_the_pointer(home, area):
    d = request(home)
    (d / "work.txt").write_text("keep")
    area.set_area(str(d), "contact360")
    area.set_area(str(d), "ingestion")
    assert remote(d).endswith("/ingestion.git")
    assert (d / "work.txt").read_text() == "keep"
    assert not (d / ".git.tmp").exists()


def test_none_takes_it_out(home, area):
    d = request(home)
    area.set_area(str(d), "ingestion")
    area.main(["--dir", str(d), "none"])
    assert not (d / ".git").exists()
    assert meta(d)["area"] == "other"
    area.set_area(str(d), "none")           # already out: still fine


def test_unknown_area_lists_the_valid_ones(home, area):
    with pytest.raises(SystemExit, match="contact360, ingestion"):
        area.set_area(str(request(home)), "nope")


def test_a_real_repository_is_left_alone(home, area):
    d = request(home)
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    with pytest.raises(SystemExit, match="own .git"):
        area.set_area(str(d), "ingestion")
    assert (d / ".git").is_dir()


def test_a_foreign_pointer_is_left_alone(home, area):
    d = request(home)
    (d / ".git").write_text("gitdir: /somewhere/else.git\n")
    with pytest.raises(SystemExit, match="own .git"):
        area.set_area(str(d), "none")
    assert (d / ".git").exists()


def test_the_exclude_list_keeps_noise_out_of_snapshots(home, area):
    d = request(home)
    area.set_area(str(d), "ingestion")
    (d / ".scope.json").write_text("{}")
    (d / "big.parquet").write_text("x")
    (d / "notes.md").write_text("x")
    out = subprocess.run(["git", "-C", str(d), "status", "--short"], capture_output=True, text=True, check=True).stdout
    assert "notes.md" in out and "parquet" not in out and "scope" not in out


def test_outside_a_request_folder(home, area):
    with pytest.raises(SystemExit, match="not inside a request folder"):
        area.request_dir(str(home))
    with pytest.raises(SystemExit, match="not inside a request folder"):
        area.request_dir(str(home / "work_sessions"))


def test_subfolder_finds_its_request(home, area):
    d = request(home)
    (d / "sub").mkdir()
    assert area.request_dir(str(d / "sub")) == os.path.realpath(str(d))


def test_pick_follows_the_ticket(home, area, monkeypatch, capsys):
    old = request(home, "09-00-00_old", day="01", ticket="BTPA-1")
    area.set_area(str(old), "contact360")
    d = request(home, ticket="BTPA-1")
    monkeypatch.setattr(area, "from_model", lambda m: pytest.fail("the ticket settles it"))
    area.main(["--dir", str(d), "--pick"])
    assert meta(d)["area"] == "contact360"
    assert "earlier sessions" in capsys.readouterr().out


def test_pick_uses_the_model_for_a_ticketless_request(home, area, monkeypatch, capsys):
    d = request(home)
    monkeypatch.setattr(area, "from_model", lambda m: "ingestion")
    area.pick(str(d))
    assert remote(d).endswith("/ingestion.git")
    assert "name and goal" in capsys.readouterr().out


def test_pick_with_no_answer_leaves_it_ungrouped(home, area, monkeypatch, capsys):
    d = request(home)
    monkeypatch.setattr(area, "from_model", lambda m: "")
    area.pick(str(d))
    assert not (d / ".git").exists()
    assert meta(d)["area"] == "other"
    assert capsys.readouterr().out == "Area: other\n"


def test_pick_keeps_an_area_already_set(home, area, monkeypatch):
    d = request(home, area="ingestion")
    monkeypatch.setattr(area, "from_model", lambda m: pytest.fail("nothing to choose"))
    area.pick(str(d))


def test_pick_is_silent_with_no_areas_configured(home, capsys):
    mod = load_script("claude-area")
    d = request(home)
    mod.pick(str(d))
    assert "area" not in meta(d) and capsys.readouterr().out == ""


def test_pick_never_stops_claude_new(home, area, monkeypatch, capsys):
    d = request(home)
    subprocess.run(["git", "init", "-q", str(d)], check=True)
    monkeypatch.setattr(area, "from_model", lambda m: "ingestion")
    area.pick(str(d))
    assert "own .git" in capsys.readouterr().err


def run_model(area, monkeypatch, out=None, boom=None):
    calls = {}

    def fake(cmd, **kw):
        calls.update(cmd=cmd, env=kw["env"])
        if boom:
            raise boom
        return types.SimpleNamespace(stdout=out)

    monkeypatch.setattr(area.subprocess, "run", fake)
    return area.from_model({"name": "n", "goal": "g", "profile": "work"}), calls


def test_model_answer_is_used_and_runs_on_the_profile(home, area, monkeypatch):
    got, calls = run_model(area, monkeypatch, json.dumps({"structured_output": {"area": "ingestion"}}))
    assert got == "ingestion"
    assert calls["env"]["CLAUDE_CONFIG_DIR"].endswith(".claude-work")
    assert "--no-session-persistence" in calls["cmd"]


@pytest.mark.parametrize("out", ["", "not json", '{"structured_output": {"area": "made-up"}}', '{"structured_output": "x"}'])
def test_model_bad_answers_mean_no_area(home, area, monkeypatch, out):
    assert run_model(area, monkeypatch, out)[0] == ""


def test_model_timeout_means_no_area(home, area, monkeypatch):
    assert run_model(area, monkeypatch, boom=subprocess.TimeoutExpired("claude", 1))[0] == ""


def test_broken_session_file(home, area):
    d = request(home)
    (d / ".session.json").write_text("[]")
    assert area.read_meta(str(d)) == {}
    (d / ".session.json").write_text("{")
    assert area.read_meta(str(d)) == {}


def test_show(home, area, capsys):
    d = request(home)
    area.set_area(str(d), "ingestion")
    area.main(["--dir", str(d)])
    out = capsys.readouterr().out
    assert "contact360, ingestion" in out and "This request: ingestion" in out
    area.main(["--dir", str(home)])
    assert "This request" not in capsys.readouterr().out


def test_gc(home, area, capsys):
    area.main(["--gc"])
    assert "no data" in capsys.readouterr().out.replace("No area has any data yet", "no data")
    area.set_area(str(request(home)), "ingestion")
    area.main(["--gc"])
    assert "ingestion" in capsys.readouterr().out


def test_git_failure_is_reported(home, area):
    with pytest.raises(SystemExit, match="failed"):
        area.git("--git-dir", "/nonexistent", "gc")


def test_ticket_index_keeps_the_latest_area_and_ignores_other(home, area):
    area.set_area(str(request(home, "09-00-00_a", ticket="BTPA-1")), "contact360")
    area.set_area(str(request(home, "09-05-00_b", ticket="BTPA-1")), "ingestion")
    area.set_area(str(request(home, "09-10-00_c")), "ingestion")
    assert area.read_index() == {"BTPA-1": "ingestion"}
    assert area.from_ticket("BTPA-2") == "" and area.from_ticket(None) == ""


def test_ticket_index_drops_an_area_no_longer_configured(home, area):
    area.remember("BTPA-1", "retired")
    assert area.from_ticket("BTPA-1") == ""


@pytest.mark.parametrize("text", ["[]", "{"])
def test_broken_ticket_index_is_ignored(home, area, text):
    os.makedirs(area.store())
    with open(area.ticket_index(), "w") as fh:
        fh.write(text)
    assert area.read_index() == {}
