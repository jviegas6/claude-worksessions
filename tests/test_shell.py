"""Behaviour of shell/worksessions.zsh (zsh has no line coverage; these run it for real)."""

import json
import os
import shutil
import subprocess

import pytest

from conftest import REPO

pytestmark = pytest.mark.skipif(shutil.which("zsh") is None, reason="zsh not installed")


def zsh(script, root, types="permissions, job errors, documentation, support"):
    env = dict(os.environ, CLAUDE_WORK_ROOT=str(root), CWS_TASK_TYPES=types,
               CWS_CONFIG=os.devnull, ZDOTDIR=str(root))
    src = 'source "{}/shell/worksessions.zsh"\n'.format(REPO)
    return subprocess.run(["zsh", "-fc", src + script], env=env, capture_output=True,
                          text=True, check=True).stdout


def make_session(root, day, name, task_type):
    d = root / "2026" / "09" / day / ("10-00-00_" + name)
    d.mkdir(parents=True)
    (d / ".session.json").write_text(json.dumps({"name": name, "task_type": task_type}))


def test_task_types_lists_used_then_unused_seeds(tmp_path):
    for i, t in enumerate(["a", "b", "c", "d", "e", "f", "g", "h", "permissions"]):
        make_session(tmp_path, "{:02d}".format(i + 1), "s" + str(i), t)
    out = zsh("_cws_task_types", tmp_path).split()
    # newest folder first, then seeds not already used; nothing dropped
    assert out[:9] == ["permissions", "h", "g", "f", "e", "d", "c", "b", "a"]
    assert out[9:] == ["job", "errors", "documentation", "support"]


def test_menu_shows_every_type_past_eight(tmp_path):
    for i, t in enumerate("abcdefgh"):
        make_session(tmp_path, "{:02d}".format(i + 1), "s" + str(i), t)
    # the loop claude-new prints the menu with
    out = zsh('local -a types=("${(@f)$(_cws_task_types)}"); i=1\n'
              'for t in $types; do printf "%d) %s\\n" $i "$t"; (( i++ )); done', tmp_path)
    lines = out.splitlines()
    assert len(lines) == 12
    assert lines[-1] == "12) support"


def test_claude_new_menu_is_not_capped():
    src = open(os.path.join(REPO, "shell", "worksessions.zsh")).read()
    assert "types[1,8]" not in src


def run_new(root, args, **env):
    """claude-new with its own HOME, returning the finished process (it may fail)."""
    e = dict(os.environ, CLAUDE_WORK_ROOT=str(root), CWS_CONFIG=os.devnull, ZDOTDIR=str(root),
             HOME=str(root), CWS_PROFILES="personal work ops", CWS_DEFAULT_PROFILE="personal",
             CWS_SHARED_PROFILE="personal", **env)
    src = 'source "{}/shell/worksessions.zsh"\nclaude-new {}'.format(REPO, args)
    return subprocess.run(["zsh", "-fc", src], env=e, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


def test_list_profiles_shows_every_configured_profile(tmp_path):
    (tmp_path / ".claude-personal").mkdir()
    (tmp_path / ".claude-work").mkdir()
    r = run_new(tmp_path, "-L", CWS_PROFILE_work_DESC="gateway",
                CWS_PROFILE_work_BASE_URL="https://gw.example.com")
    assert r.returncode == 0
    lines = r.stdout.splitlines()
    assert [ln.split()[0] for ln in lines] == ["personal", "work", "ops"]
    assert "default shared" in lines[0]
    assert "gateway  [https://gw.example.com]" in lines[1]
    assert "(no ~/.claude-ops)" in lines[2]


def test_profile_flag_takes_any_configured_name(tmp_path):
    (tmp_path / ".claude-ops").mkdir()
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "claude").write_text('#!/bin/sh\necho "$CLAUDE_CONFIG_DIR" > "$HOME/launched"\n')
    (stub / "claude").chmod(0o755)
    r = run_new(tmp_path, "-p ops -t Other -T tooling demo",
                PATH=str(stub) + os.pathsep + os.environ["PATH"])
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "launched").read_text().strip() == str(tmp_path / ".claude-ops")
    meta = next(tmp_path.glob("[0-9]*/*/*/*/.session.json"))
    assert json.loads(meta.read_text())["profile"] == "ops"


def test_profile_flag_rejects_unknown_name(tmp_path):
    r = run_new(tmp_path, "-p nope -t Other demo")
    assert r.returncode == 1
    assert "unknown profile 'nope'" in r.stderr
    assert "personal work ops" in r.stderr


def test_profile_flag_needs_a_value(tmp_path):
    r = run_new(tmp_path, "-p -t Other demo")
    assert r.returncode == 1
    assert "-p needs a profile name" in r.stderr


@pytest.mark.parametrize("flag", ["-w", "--work", "--personal", "-P"])
def test_old_profile_shortcuts_are_gone(tmp_path, flag):
    r = run_new(tmp_path, flag + " demo")
    assert r.returncode == 1
    assert "unknown option" in r.stderr


def run_resume(root, args):
    """claude-resume with a stub claude that records its config dir and arguments."""
    stub = root / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "claude").write_text('#!/bin/sh\necho "$CLAUDE_CONFIG_DIR $*" > "$HOME/launched"\n')
    (stub / "claude").chmod(0o755)
    e = dict(os.environ, CWS_CONFIG=os.devnull, ZDOTDIR=str(root), HOME=str(root),
             CWS_PROFILES="personal work ops", CWS_DEFAULT_PROFILE="personal",
             PATH=str(stub) + os.pathsep + os.environ["PATH"])
    src = 'source "{}/shell/worksessions.zsh"\nclaude-resume {}'.format(REPO, args)
    return subprocess.run(["zsh", "-fc", src], env=e, capture_output=True, text=True)


@pytest.mark.parametrize("args,expected", [
    ("-p ops --resume abc", ".claude-ops --resume abc"),
    ("-p ops", ".claude-ops --resume"),
    ("", ".claude-personal --resume"),
    ("-c", ".claude-personal -c"),
    ("-p ops -- -p hello", ".claude-ops -p hello"),
])
def test_claude_resume_picks_profile_and_passes_the_rest(tmp_path, args, expected):
    for p in ("personal", "ops"):
        (tmp_path / (".claude-" + p)).mkdir()
    r = run_resume(tmp_path, args)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "launched").read_text().strip() == str(tmp_path) + "/" + expected


def test_claude_resume_rejects_unknown_profile(tmp_path):
    r = run_resume(tmp_path, "-p nope --resume abc")
    assert r.returncode == 1
    assert "claude-resume: unknown profile 'nope'" in r.stderr
    assert not (tmp_path / "launched").exists()


def test_claude_resume_needs_the_config_dir(tmp_path):
    r = run_resume(tmp_path, "-p work")
    assert r.returncode == 1
    assert "config dir" in r.stderr


def test_per_profile_aliases_are_gone(tmp_path):
    out = zsh("alias", tmp_path)
    assert "claude-personal=" not in out and "claude-work=" not in out


@pytest.mark.parametrize("profiles,ok", [("personal my_work", True), ("personal my-work", False)])
def test_install_rejects_dashed_profile_names(tmp_path, profiles, ok):
    # CWS_PROFILE_<name>_DESC / _BASE_URL can't hold a dash, so such a profile's
    # settings would be silently dropped; install.sh must refuse it instead.
    conf = tmp_path / "ws" / "_config" / "config.env"
    conf.parent.mkdir(parents=True)
    conf.write_text('CWS_WORK_ROOT="{}/ws"\nCWS_PROFILES="{}"\n'.format(tmp_path, profiles))
    link = tmp_path / ".config" / "claude-worksessions" / "config.env"
    link.parent.mkdir(parents=True)
    link.symlink_to(conf)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CWS_")}
    env.update(HOME=str(tmp_path), ZDOTDIR=str(tmp_path))
    r = subprocess.run(["zsh", os.path.join(REPO, "install.sh"), "--dry-run", "--yes"], env=env,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    if ok:
        assert "profiles   personal my_work" in r.stdout
    else:
        assert r.returncode == 1
        assert "profile 'my-work' in CWS_PROFILES is not valid" in r.stderr
