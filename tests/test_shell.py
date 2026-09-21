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
