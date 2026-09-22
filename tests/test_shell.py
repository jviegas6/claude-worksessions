"""Behaviour of shell/worksessions.zsh (zsh has no line coverage; these run it for real)."""

import json
import os
import re
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


def test_code_flag_opens_vscode_instead_of_claude(tmp_path):
    (tmp_path / ".claude-work").mkdir()
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "code").write_text('#!/bin/sh\necho "$*" > "$HOME/opened"\n')
    (stub / "claude").write_text('#!/bin/sh\ntouch "$HOME/launched"\n')
    for f in stub.iterdir():
        f.chmod(0o755)
    r = run_new(tmp_path, "-c -p work -t Other -T tooling demo",
                PATH=str(stub) + os.pathsep + os.environ["PATH"])
    assert r.returncode == 0, r.stderr
    meta = next(tmp_path.glob("[0-9]*/*/*/*/.session.json"))
    assert (tmp_path / "opened").read_text().split() == ["-n", str(meta.parent)]
    assert not (tmp_path / "launched").exists()
    d = json.loads(meta.read_text())
    assert d["profile"] == "work" and d["ended_at"] is None


def test_code_flag_needs_the_code_command(tmp_path):
    (tmp_path / ".claude-work").mkdir()
    r = run_new(tmp_path, "-c -p work -t Other -T tooling demo", PATH="/usr/bin:/bin")
    assert r.returncode == 1
    assert "needs VS Code's 'code' command" in r.stderr
    assert not list(tmp_path.glob("[0-9]*"))


def run_wrapper(home, cwd):
    """bin/claude-vscode wrapping a stub claude that reports its config dir and args."""
    stub = home / "stub-claude"
    stub.write_text('#!/bin/sh\necho "${CLAUDE_CONFIG_DIR:-unset} $*"\n')
    stub.chmod(0o755)
    env = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
    env.update(HOME=str(home), PWD=str(cwd))
    return subprocess.run([os.path.join(REPO, "bin", "claude-vscode"), str(stub), "--x", "a b"],
                          cwd=cwd, env=env, capture_output=True, text=True)


@pytest.mark.parametrize("meta,sub,expected", [
    ({"profile": "work"}, "", ".claude-work"),               # the session's profile
    ({"profile": "work"}, "src/deep", ".claude-work"),       # found from a subfolder
    ({"profile": "ops"}, "", "unset"),                       # no ~/.claude-ops: left alone
    ({"profile": "../x"}, "", "unset"),                      # not a profile name
    (None, "", "unset"),                                     # not a request folder
])
def test_vscode_wrapper_follows_the_session_profile(tmp_path, meta, sub, expected):
    (tmp_path / ".claude-work").mkdir()
    folder = tmp_path / "ws" / "2026" / "09" / "22" / "10-00-00_demo"
    (folder / sub).mkdir(parents=True)
    if meta is not None:
        (folder / ".session.json").write_text(json.dumps(meta, indent=2))
    r = run_wrapper(tmp_path, folder / sub)
    assert r.returncode == 0, r.stderr
    cfg, args = r.stdout.strip().split(" ", 1)
    assert cfg == (str(tmp_path / expected) if expected != "unset" else "unset")
    assert args == "--x a b"


def test_vscode_wrapper_without_a_command(tmp_path):
    r = subprocess.run([os.path.join(REPO, "bin", "claude-vscode")], capture_output=True, text=True)
    assert r.returncode == 2 and "claudeProcessWrapper" in r.stderr


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


def test_install_prints_no_stray_assignments(tmp_path):
    # zsh prints `name=value` when `local` re-declares a set variable; none may leak out.
    conf = tmp_path / "ws" / "_config" / "config.env"
    conf.parent.mkdir(parents=True)
    conf.write_text('CWS_WORK_ROOT="{}/ws"\nCWS_PROFILES="personal work"\n'.format(tmp_path))
    link = tmp_path / ".config" / "claude-worksessions" / "config.env"
    link.parent.mkdir(parents=True)
    link.symlink_to(conf)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CWS_")}
    env.update(HOME=str(tmp_path), ZDOTDIR=str(tmp_path))
    r = subprocess.run(["zsh", os.path.join(REPO, "install.sh"), "--dry-run", "--yes"], env=env,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    stray = [ln for ln in (r.stdout + r.stderr).splitlines()
             if re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", ln)]
    assert stray == []


def dry_install(tmp_path, os_name, path=None, shell="/bin/zsh"):
    """install.sh --dry-run --yes as if on `os_name`, against a throwaway home."""
    conf = tmp_path / "ws" / "_config" / "config.env"
    conf.parent.mkdir(parents=True, exist_ok=True)
    conf.write_text('CWS_WORK_ROOT="{}/ws"\nCWS_PROFILES="personal work"\n'.format(tmp_path))
    link = tmp_path / ".config" / "claude-worksessions" / "config.env"
    link.parent.mkdir(parents=True, exist_ok=True)
    if not link.exists():
        link.symlink_to(conf)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CWS_")}
    env.update(HOME=str(tmp_path), ZDOTDIR=str(tmp_path), CWS_OS=os_name, SHELL=shell)
    if path:
        env["PATH"] = path
    return subprocess.run(["zsh", os.path.join(REPO, "install.sh"), "--dry-run", "--yes"], env=env,
                          capture_output=True, text=True, stdin=subprocess.DEVNULL)


@pytest.mark.parametrize("os_name,vsdir", [
    ("mac", "Library/Application Support/Code/User"),
    ("linux", ".config/Code/User"),
    ("wsl", ".vscode-server/data/Machine"),
])
@pytest.mark.parametrize("settings,expected", [
    (None, "no VS Code settings in"),
    ("", "[dry-run] set claudeCode.claudeProcessWrapper"),
    ('{"editor.fontSize": 13}', "[dry-run] set claudeCode.claudeProcessWrapper"),
    ('{"claudeCode.claudeProcessWrapper": "HOME/.local/bin/claude-vscode"}', "ok claudeCode.claudeProcessWrapper"),
    ('{\n  // a comment\n  "editor.fontSize": 13,\n}', "isn't plain JSON"),
])
def test_install_sets_the_vscode_wrapper(tmp_path, os_name, vsdir, settings, expected):
    if settings is not None:
        d = tmp_path / vsdir
        d.mkdir(parents=True)
        (d / "settings.json").write_text(settings.replace("HOME", str(tmp_path)))
    r = dry_install(tmp_path, os_name)
    assert expected in r.stdout + r.stderr
    if settings is not None:   # a dry run changes nothing
        assert (tmp_path / vsdir / "settings.json").read_text() == settings.replace("HOME", str(tmp_path))


HAS_BREW = any(os.access(p, os.X_OK) for p in (
    "/opt/homebrew/bin/brew", "/usr/local/bin/brew", "/home/linuxbrew/.linuxbrew/bin/brew"))


def stub_tools(tmp_path, *names):
    d = tmp_path / "stubs"
    d.mkdir(exist_ok=True)
    for n in names:
        (d / n).write_text("#!/bin/sh\nexit 0\n")
        (d / n).chmod(0o755)
    return d


@pytest.mark.parametrize("os_name", ["linux", "wsl"])
def test_install_on_linux_plans_the_package_manager(tmp_path, os_name):
    # apt-get is found, fzf is not: the plan names apt, never Homebrew or the Mac tools
    d = stub_tools(tmp_path, "apt-get")
    r = dry_install(tmp_path, os_name, path=str(d) + os.pathsep + "/usr/bin:/bin")
    assert "Prerequisites ({})".format(os_name) in r.stdout
    assert "Command Line Tools" not in r.stdout
    if HAS_BREW:   # Linux with Homebrew uses it, as on a Mac
        assert "Homebrew packages:" in r.stdout and "apt-get" not in r.stdout
    else:
        assert "apt-get packages:" in r.stdout and "fzf" in r.stdout
        assert "Homebrew" not in r.stdout


def test_install_on_linux_without_a_package_manager(tmp_path):
    if HAS_BREW or any(shutil.which(pm, path="/usr/bin:/bin") for pm in ("apt-get", "dnf", "pacman", "zypper")):
        pytest.skip("this machine has a package manager")
    r = dry_install(tmp_path, "linux", path="/usr/bin:/bin")
    assert "no known package manager" in r.stdout


def test_install_warns_when_login_shell_is_not_zsh(tmp_path):
    r = dry_install(tmp_path, "linux", shell="/bin/bash")
    assert "your login shell is /bin/bash" in r.stderr and "chsh -s" in r.stderr
    r = dry_install(tmp_path, "linux", shell="/usr/bin/zsh")
    assert "your login shell" not in r.stderr


def test_install_under_bash_says_it_needs_zsh():
    bash = shutil.which("bash")
    r = subprocess.run([bash, os.path.join(REPO, "install.sh")], capture_output=True, text=True)
    assert r.returncode == 1
    assert "install.sh needs zsh" in r.stderr


@pytest.mark.parametrize("os_name,tool,expected", [
    ("mac", "open", "open ."),
    ("wsl", "explorer.exe", "explorer.exe WINPATH"),
    ("linux", "xdg-open", "xdg-open ."),
])
def test_cws_open_uses_the_desktop_opener(tmp_path, os_name, tool, expected):
    d = tmp_path / "stubs"
    d.mkdir()
    (d / tool).write_text('#!/bin/sh\necho "$(basename "$0") $*" >> "{}/opened"\n'.format(tmp_path))
    (d / tool).chmod(0o755)
    (d / "wslpath").write_text("#!/bin/sh\necho WINPATH\n")
    (d / "wslpath").chmod(0o755)
    env = dict(os.environ, CWS_CONFIG=os.devnull, ZDOTDIR=str(tmp_path), CWS_OS=os_name,
               PATH=str(d) + os.pathsep + os.environ["PATH"])
    src = 'source "{}/shell/worksessions.zsh"\n_cws_open .; sleep 0.3'.format(REPO)
    r = subprocess.run(["zsh", "-fc", src], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "opened").read_text().strip() == expected


def stub_code(tmp_path, listed=""):
    """A `code` that lists `listed` as installed extensions and logs every call."""
    d = tmp_path / "code-stub"
    d.mkdir(exist_ok=True)
    (d / "code").write_text('#!/bin/sh\necho "$*" >> "{}/code.log"\n'
                            'case "$1" in --list-extensions) printf "%s\\n" "{}" ;; esac\n'
                            .format(tmp_path, listed))
    (d / "code").chmod(0o755)
    return str(d) + os.pathsep + "/usr/bin:/bin"


def test_install_plans_the_sidebar_extension(tmp_path):
    version = open(os.path.join(REPO, "VERSION")).read().strip()
    r = dry_install(tmp_path, "mac", path=stub_code(tmp_path))
    assert "[dry-run] install the Work sessions sidebar " + version in r.stdout
    r = dry_install(tmp_path, "mac", path=stub_code(tmp_path, "jviegas6.claude-worksessions@0.1.0"))
    assert "install the Work sessions sidebar {} (have 0.1.0)".format(version) in r.stdout
    r = dry_install(tmp_path, "mac", path=stub_code(tmp_path, "jviegas6.claude-worksessions@" + version))
    assert "ok Work sessions sidebar " + version in r.stdout
    assert "--install-extension" not in (tmp_path / "code.log").read_text()   # dry run
    r = dry_install(tmp_path, "mac", path="/usr/bin:/bin")
    assert "no 'code' command" in r.stdout


@pytest.mark.parametrize("settings,after,message", [
    ('{"a": 1, "claudeCode.claudeProcessWrapper": "HOME/.local/bin/claude-vscode"}', '{"a": 1}', "removed claudeCode"),
    ('{"claudeCode.claudeProcessWrapper": "/other/wrapper"}', None, None),
    ('{\n  // mine\n  "claudeCode.claudeProcessWrapper": "HOME/.local/bin/claude-vscode"\n}', None, "yourself"),
])
def test_uninstall_removes_the_vscode_pieces(tmp_path, settings, after, message):
    d = tmp_path / "Library" / "Application Support" / "Code" / "User"
    d.mkdir(parents=True)
    before = settings.replace("HOME", str(tmp_path))
    (d / "settings.json").write_text(before)
    env = dict(os.environ, HOME=str(tmp_path), ZDOTDIR=str(tmp_path),
               PATH=stub_code(tmp_path, "jviegas6.claude-worksessions"))
    r = subprocess.run(["zsh", os.path.join(REPO, "uninstall.sh")], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    now = (d / "settings.json").read_text()
    if after is None:
        assert now == before
    else:
        assert json.loads(now) == json.loads(after)
    if message:
        assert message in r.stdout
    assert "--uninstall-extension jviegas6.claude-worksessions" in (tmp_path / "code.log").read_text()
    assert "uninstalled the Work sessions sidebar" in r.stdout


def run_new_tty(root, args, typed):
    """claude-new on a terminal (a pty), with `typed` already waiting as input."""
    import pty
    master, slave = pty.openpty()
    os.write(master, typed.encode())
    stub = root / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "claude").write_text("#!/bin/sh\nexit 0\n")
    (stub / "claude").chmod(0o755)
    e = dict(os.environ, CLAUDE_WORK_ROOT=str(root), CWS_CONFIG=os.devnull, ZDOTDIR=str(root),
             HOME=str(root), CWS_PROFILES="personal", CWS_DEFAULT_PROFILE="personal",
             PATH=str(stub) + os.pathsep + os.environ["PATH"])
    src = 'source "{}/shell/worksessions.zsh"\nclaude-new {}'.format(REPO, args)
    try:
        r = subprocess.run(["zsh", "-fc", src], env=e, stdin=slave, capture_output=True, text=True, timeout=20)
    finally:
        os.close(slave)
        os.close(master)
    return r


@pytest.mark.parametrize("args,typed,audit", [
    ("", "\n", True),          # Enter keeps it in the review
    ("", "y\n", True),
    ("", "n\n", False),        # asked, and left out
    ("", "No\n", False),
    ("-n", "", False),         # -n: not asked
    ("-a", "", True),          # -a: not asked
])
def test_claude_new_asks_about_the_review(tmp_path, args, typed, audit):
    (tmp_path / ".claude-personal").mkdir()
    r = run_new_tty(tmp_path, args + " -t Other -T tooling demo", typed)
    assert r.returncode == 0, r.stderr
    meta = json.loads(next(tmp_path.glob("[0-9]*/*/*/*/.session.json")).read_text())
    assert meta["audit"] is audit
    assert ("(no-audit)" in r.stdout) is (not audit)


def test_claude_new_without_a_terminal_counts_the_session(tmp_path):
    (tmp_path / ".claude-personal").mkdir()
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "claude").write_text("#!/bin/sh\nexit 0\n")
    (stub / "claude").chmod(0o755)
    r = run_new(tmp_path, "-p personal -t Other -T tooling demo",
                PATH=str(stub) + os.pathsep + os.environ["PATH"])
    assert r.returncode == 0, r.stderr
    assert json.loads(next(tmp_path.glob("[0-9]*/*/*/*/.session.json")).read_text())["audit"] is True


def test_claude_new_prompt_starts_claude_with_it(tmp_path):
    (tmp_path / ".claude-personal").mkdir()
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "claude").write_text('#!/bin/sh\necho "$# $*" > "$HOME/args"\n')
    (stub / "claude").chmod(0o755)
    path = str(stub) + os.pathsep + os.environ["PATH"]
    r = run_new(tmp_path, "-p personal -t Other -T tooling --prompt '/weekly-review now' demo", PATH=path)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "args").read_text() == "1 /weekly-review now\n"
    r = run_new(tmp_path, "-p personal -t Other -T tooling demo2", PATH=path)
    assert (tmp_path / "args").read_text() == "0 \n"     # no prompt: claude gets no arguments


def test_claude_new_prompt_needs_text(tmp_path):
    r = run_new(tmp_path, "--prompt")
    assert r.returncode == 1 and "--prompt needs the text" in r.stderr


@pytest.mark.parametrize("args,prompt", [("", None), ("--prompt '/weekly-review'", "/weekly-review")])
def test_code_flag_leaves_a_handoff_for_the_sidebar(tmp_path, args, prompt):
    (tmp_path / ".claude-personal").mkdir()
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "code").write_text("#!/bin/sh\nexit 0\n")
    (stub / "code").chmod(0o755)
    hand = tmp_path / "handoff"
    r = run_new(tmp_path, "-c -p personal -t Other -T tooling {} demo".format(args),
                PATH=str(stub) + os.pathsep + os.environ["PATH"], CWS_HANDOFF_DIR=str(hand))
    assert r.returncode == 0, r.stderr
    (note,) = hand.iterdir()
    d = json.loads(note.read_text())
    folder = next(tmp_path.glob("[0-9]*/*/*/*/.session.json")).parent
    assert (d["folder"], d["session"], d["prompt"]) == (str(folder), None, prompt)
    assert d["at"] > 0
