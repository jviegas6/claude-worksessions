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
    """claude-new with its own HOME, returning the finished process (it may fail). Nothing opens it
    unless the test sets CWS_OPEN_CMD, and claude-area doesn't run unless it sets CWS_AFTER_NEW_CMD
    (None removes a variable, for the defaults a config without the line gets)."""
    e = dict(os.environ, CLAUDE_WORK_ROOT=str(root), CWS_CONFIG=os.devnull, ZDOTDIR=str(root),
             HOME=str(root))
    e.setdefault("CWS_AFTER_NEW_CMD", "")
    for k in ("CWS_OPEN", "CWS_OPEN_CMD", "CWS_PROFILES"):
        e.pop(k, None)
    e.update(env)
    e = {k: v for k, v in e.items() if v is not None}
    src = 'source "{}/shell/worksessions.zsh"\nclaude-new {}'.format(REPO, args)
    return subprocess.run(["zsh", "-fc", src], env=e, capture_output=True, text=True,
                          stdin=subprocess.DEVNULL)


def args_stub(tmp_path, name):
    """A command that writes each argument it gets on its own line, in brackets, to ~/<name>.log."""
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    (stub / name).write_text('#!/bin/sh\nfor a in "$@"; do printf "[%s]\\n" "$a"; done > "$HOME/{}.log"\n'.format(name))
    (stub / name).chmod(0o755)
    return str(stub) + os.pathsep + os.environ["PATH"]


def test_open_cmd_is_filled_in_and_run(tmp_path):
    r = run_new(tmp_path, '-t Other -T tooling --prompt "say \'hi\' now" demo',
                CWS_OPEN_CMD="echo OPEN {dir} {prompt}")
    assert r.returncode == 0, r.stderr
    meta = next(tmp_path.glob("[0-9]*/*/*/*/.session.json"))
    assert r.stdout.splitlines()[-1] == "OPEN {} say 'hi' now".format(meta.parent)
    d = json.loads(meta.read_text())
    assert "profile" not in d and d["ended_at"] is None


def test_open_cmd_keeps_each_value_one_argument(tmp_path):
    r = run_new(tmp_path, '-t Other -T tooling --prompt "two  words; \\$HOME" "my demo"',
                CWS_OPEN_CMD="opener --title {title} {prompt} {dir}", PATH=args_stub(tmp_path, "opener"))
    assert r.returncode == 0, r.stderr
    meta = next(tmp_path.glob("[0-9]*/*/*/*/.session.json"))
    assert (tmp_path / "opener.log").read_text().splitlines() == [
        "[--title]", "[my demo]", "[two  words; $HOME]", "[{}]".format(meta.parent)]


def test_empty_open_cmd_prints_the_folder(tmp_path):
    r = run_new(tmp_path, "-t Other -T tooling demo", CWS_OPEN_CMD="", CWS_OPEN="t3")
    assert r.returncode == 0, r.stderr
    meta = next(tmp_path.glob("[0-9]*/*/*/*/.session.json"))
    assert r.stdout.splitlines()[-1] == str(meta.parent)


def test_no_open_cmd_at_all_prints_the_folder(tmp_path):
    r = run_new(tmp_path, "-t Other -T tooling demo")
    assert r.returncode == 0, r.stderr
    meta = next(tmp_path.glob("[0-9]*/*/*/*/.session.json"))
    assert r.stdout.splitlines()[-1] == str(meta.parent)


def t3_stubs(tmp_path):
    """A claude-t3-sync stub that records what it was asked to open."""
    stub = tmp_path / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "claude-t3-sync").write_text('#!/bin/sh\necho "$*" > "$HOME/t3-opened"\n')
    (stub / "claude-t3-sync").chmod(0o755)
    return str(stub) + os.pathsep + os.environ["PATH"]


@pytest.mark.parametrize("env", [{"CWS_OPEN": "t3"},                     # a config from before 3.1
                                 {"CWS_OPEN_CMD": "claude-t3-sync --open {dir} --prompt {prompt}"}])
def test_t3_opens_the_request_in_t3_code(tmp_path, env):
    r = run_new(tmp_path, "-t PROJ-1 -T tooling demo", PATH=t3_stubs(tmp_path), **env)
    assert r.returncode == 0, r.stderr
    meta = next(tmp_path.glob("[0-9]*/*/*/*/.session.json"))
    # no --profile: T3 picks the Claude instance
    assert (tmp_path / "t3-opened").read_text().split() == ["--open", str(meta.parent), "--prompt"]
    assert json.loads(meta.read_text())["ended_at"] is None


def test_t3_with_a_prompt_starts_a_thread(tmp_path):
    r = run_new(tmp_path, '-t Other -T reporting --prompt "/weekly-review 2026-10-26" demo',
                PATH=t3_stubs(tmp_path), CWS_OPEN="t3")
    assert r.returncode == 0, r.stderr
    meta = next(tmp_path.glob("[0-9]*/*/*/*/.session.json"))
    assert (tmp_path / "t3-opened").read_text().strip() == \
        "--open {} --prompt /weekly-review 2026-10-26".format(meta.parent)


def test_a_failing_open_cmd_fails_claude_new(tmp_path):
    r = run_new(tmp_path, "-t Other -T tooling demo", CWS_OPEN_CMD="false")
    assert r.returncode == 1
    assert list(tmp_path.glob("[0-9]*/*/*/*/.session.json"))      # the folder is still there


@pytest.mark.parametrize("flag", ["-p work", "-L", "-c", "--code", "--cli", "--t3", "-w", "--work", "-P"])
def test_removed_options_are_rejected(tmp_path, flag):
    r = run_new(tmp_path, flag + " -t Other demo")
    assert r.returncode == 1
    assert "unknown option" in r.stderr
    assert not list(tmp_path.glob("[0-9]*"))


def test_claude_vscode_is_gone():
    assert not os.path.exists(os.path.join(REPO, "bin", "claude-vscode"))


def test_claude_homes_default_and_backward_compat(tmp_path):
    def homes(**env):
        e = dict(os.environ, CWS_CONFIG=os.devnull, HOME=str(tmp_path), ZDOTDIR=str(tmp_path))
        for k in ("CWS_CLAUDE_HOMES", "CWS_PROFILES"):
            e.pop(k, None)
        e.update(env)
        src = 'source "{}/shell/worksessions.zsh"\nprint -r -- "$CWS_CLAUDE_HOMES"'.format(REPO)
        return subprocess.run(["zsh", "-fc", src], env=e, capture_output=True, text=True).stdout.strip()
    assert homes() == str(tmp_path / ".claude")
    assert homes(CWS_PROFILES="personal work") == "{0}/.claude-personal {0}/.claude-work".format(tmp_path)
    assert homes(CWS_CLAUDE_HOMES="~/a ~/b", CWS_PROFILES="x") == "~/a ~/b"


def test_claude_new_no_longer_sets_the_config_dir(tmp_path):
    e = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
    e.update(CWS_CONFIG=os.devnull, HOME=str(tmp_path), ZDOTDIR=str(tmp_path), CWS_PROFILES="personal")
    src = 'source "{}/shell/worksessions.zsh"\nprint -r -- "${{CLAUDE_CONFIG_DIR:-unset}}"'.format(REPO)
    out = subprocess.run(["zsh", "-fc", src], env=e, capture_output=True, text=True).stdout.strip()
    assert out == "unset"


def run_resume(root, args):
    """claude-resume with a stub claude that records its config dir and arguments."""
    stub = root / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "claude").write_text('#!/bin/sh\necho "${CLAUDE_CONFIG_DIR:-unset} $*" > "$HOME/launched"\n')
    (stub / "claude").chmod(0o755)
    e = {k: v for k, v in os.environ.items() if k != "CLAUDE_CONFIG_DIR"}
    e.update(CWS_CONFIG=os.devnull, ZDOTDIR=str(root), HOME=str(root),
             PATH=str(stub) + os.pathsep + os.environ["PATH"])
    src = 'source "{}/shell/worksessions.zsh"\nclaude-resume {}'.format(REPO, args)
    return subprocess.run(["zsh", "-fc", src], env=e, capture_output=True, text=True)


@pytest.mark.parametrize("args,expected", [
    ("--resume abc", "unset --resume abc"),
    ("", "unset --resume"),
    ("-c", "unset -c"),
    ("-- -p hello", "unset -p hello"),
    ("-p hello", "unset -p hello"),          # -p is claude's own again (print mode)
])
def test_claude_resume_passes_everything_to_claude(tmp_path, args, expected):
    r = run_resume(tmp_path, args)
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "launched").read_text().strip() == expected


def test_per_profile_aliases_are_gone(tmp_path):
    out = zsh("alias", tmp_path)
    assert "claude-personal=" not in out and "claude-work=" not in out


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
    conf.write_text('CWS_WORK_ROOT="{}/ws"\nCWS_CLAUDE_HOMES="~/.claude-personal $HOME/.claude-work"\n'.format(tmp_path))
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
    (None, None),
    ("", None),
    ('{"editor.fontSize": 13}', None),
    ('{"claudeCode.claudeProcessWrapper": "/opt/my-wrapper"}', None),          # someone else's: kept
    ('{"claudeCode.claudeProcessWrapper": "HOME/.local/bin/claude-vscode"}',
     "[dry-run] removed claudeCode.claudeProcessWrapper (claude-vscode)"),
    ('{\n  // a comment\n  "editor.fontSize": 13,\n}', None),
    ('{\n  // a comment\n  "claudeCode.claudeProcessWrapper": "HOME/.local/bin/claude-vscode",\n}',
     "isn't plain JSON — remove its claudeCode.claudeProcessWrapper line"),
])
def test_install_takes_out_the_old_vscode_wrapper(tmp_path, os_name, vsdir, settings, expected):
    if settings is not None:
        d = tmp_path / vsdir
        d.mkdir(parents=True)
        (d / "settings.json").write_text(settings.replace("HOME", str(tmp_path)))
    r = dry_install(tmp_path, os_name)
    out = r.stdout + r.stderr
    assert r.returncode == 0, out
    if expected:
        assert expected in out
    else:
        assert "claudeProcessWrapper" not in out
    if settings is not None:   # a dry run changes nothing
        assert (tmp_path / vsdir / "settings.json").read_text() == settings.replace("HOME", str(tmp_path))


def test_install_reads_the_claude_dirs_from_the_config(tmp_path):
    r = dry_install(tmp_path, "mac")
    assert "claude dirs ~/.claude-personal ~/.claude-work" in r.stdout, r.stdout + r.stderr
    assert "[dry-run] ~/.claude-work: keep transcripts 3650 days" in r.stdout
    assert "profile" not in r.stdout.lower()


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


def run_new_tty(root, args, typed, env=None):
    """claude-new on a terminal (a pty), with `typed` already waiting as input."""
    import pty
    master, slave = pty.openpty()
    os.write(master, typed.encode())
    stub = root / "bin"
    stub.mkdir(exist_ok=True)
    (stub / "claude").write_text("#!/bin/sh\nexit 0\n")
    (stub / "claude").chmod(0o755)
    e = {k: v for k, v in os.environ.items() if k not in ("CWS_OPEN", "CWS_OPEN_CMD", "CWS_PROFILES")}
    e.update(CLAUDE_WORK_ROOT=str(root), CWS_CONFIG=os.devnull, ZDOTDIR=str(root), HOME=str(root),
             CWS_AFTER_NEW_CMD="", PATH=str(stub) + os.pathsep + os.environ["PATH"], **(env or {}))
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
    assert meta["audit"] is audit and meta["goal"] == "demo" and meta["done_when"] == ""
    assert ("(no-audit)" in r.stdout) is (not audit)


def test_claude_new_asks_for_goal_and_done_when_only_when_configured(tmp_path):
    (tmp_path / ".claude-personal").mkdir()
    r = run_new_tty(tmp_path, "-a -t Other -T tooling demo", "list the sources\na table of them\n", env={"CWS_ASK_GOAL": "1"})
    assert r.returncode == 0, r.stderr
    meta = json.loads(next(tmp_path.glob("[0-9]*/*/*/*/.session.json")).read_text())
    assert (meta["goal"], meta["done_when"]) == ("list the sources", "a table of them")
    # default: not asked, the name is the goal (the typed lines are never read)
    r = run_new_tty(tmp_path, "-a -t Other -T tooling other", "would be the goal\n")
    assert r.returncode == 0, r.stderr
    metas = sorted(tmp_path.glob("[0-9]*/*/*/*/.session.json"))
    d = json.loads(metas[-1].read_text())
    assert (d["goal"], d["done_when"]) == ("other", "")
    assert "Goal —" not in r.stdout


def test_claude_new_without_a_terminal_counts_the_session(tmp_path):
    (tmp_path / ".claude-personal").mkdir()
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "claude").write_text("#!/bin/sh\nexit 0\n")
    (stub / "claude").chmod(0o755)
    r = run_new(tmp_path, "-t Other -T tooling demo",
                PATH=str(stub) + os.pathsep + os.environ["PATH"])
    assert r.returncode == 0, r.stderr
    assert json.loads(next(tmp_path.glob("[0-9]*/*/*/*/.session.json")).read_text())["audit"] is True


def test_claude_new_prompt_goes_to_the_open_cmd(tmp_path):
    path = args_stub(tmp_path, "opener")
    r = run_new(tmp_path, "-t Other -T tooling --prompt '/weekly-review now' demo", PATH=path,
                CWS_OPEN_CMD="opener {prompt}")
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "opener.log").read_text() == "[/weekly-review now]\n"
    r = run_new(tmp_path, "-t Other -T tooling demo2", PATH=path, CWS_OPEN_CMD="opener {prompt}")
    assert (tmp_path / "opener.log").read_text() == "[]\n"     # no prompt: an empty argument


@pytest.mark.parametrize("args,err", [
    ("--prompt", "--prompt needs the text"),
])
def test_claude_new_prompt_errors(tmp_path, args, err):
    (tmp_path / ".claude-personal").mkdir()
    r = run_new(tmp_path, args)
    assert r.returncode == 1 and err in r.stderr


@pytest.mark.parametrize("settings,expected", [
    (None, "[dry-run] ~/.claude-personal: keep transcripts 3650 days"),
    ('{"model": "x"}', "[dry-run] ~/.claude-personal: keep transcripts 3650 days"),
    ('{"cleanupPeriodDays": true}', "[dry-run] ~/.claude-personal: keep transcripts 3650 days"),
    ('{"cleanupPeriodDays": 30}', "personal: cleanupPeriodDays is 30"),
    ('{"cleanupPeriodDays": 5000}', "personal: transcripts kept 3650+ days"),
    ("{not json", "isn't valid JSON"),
])
def test_install_keeps_transcripts(tmp_path, settings, expected):
    if settings is not None:
        d = tmp_path / ".claude-personal"
        d.mkdir()
        (d / "settings.json").write_text(settings)
    r = dry_install(tmp_path, "mac")
    assert expected in r.stdout + r.stderr
    if settings is not None:
        assert (tmp_path / ".claude-personal" / "settings.json").read_text() == settings   # dry run: unchanged


def test_install_writes_retention_keeping_other_settings(tmp_path):
    conf = tmp_path / "ws" / "_config" / "config.env"
    conf.parent.mkdir(parents=True)
    conf.write_text('CWS_WORK_ROOT="{}/ws"\nCWS_PROFILES="personal"\nCWS_INSTALL_YAZI="0"\n'.format(tmp_path))
    link = tmp_path / ".config" / "claude-worksessions" / "config.env"
    link.parent.mkdir(parents=True)
    link.symlink_to(conf)
    prof = tmp_path / ".claude-personal"
    prof.mkdir()
    (prof / "settings.json").write_text('{"model": "opus"}')
    os.chmod(prof / "settings.json", 0o600)
    env = {k: v for k, v in os.environ.items() if not k.startswith("CWS_")}
    env.update(HOME=str(tmp_path), ZDOTDIR=str(tmp_path), CWS_OS="mac", PATH="/usr/bin:/bin")
    r = subprocess.run(["zsh", os.path.join(REPO, "install.sh"), "--yes", "--no-bootstrap"], env=env,
                       capture_output=True, text=True, stdin=subprocess.DEVNULL)
    assert "personal: transcripts kept 3650 days (was Claude Code's default, 30)" in r.stdout, r.stdout + r.stderr
    got = json.loads((prof / "settings.json").read_text())
    assert (got["model"], got["cleanupPeriodDays"]) == ("opus", 3650)
    assert oct(os.stat(prof / "settings.json").st_mode & 0o777) == "0o600"
    assert list(prof.glob("settings.json.bak-*"))


def _fake_claude(tmp_path, log):
    """A `claude` on PATH that records every call (uninstall.sh still removes a leftover plugin)
    and answers `plugin marketplace list` with what it was told to add, like the real one."""
    bindir = tmp_path / "fakebin"
    bindir.mkdir(exist_ok=True)
    f = bindir / "claude"
    f.write_text("""#!/bin/sh
echo "$CLAUDE_CONFIG_DIR $*" >> "{log}"
if [ "$1 $2 $3" = "plugin marketplace add" ]; then echo "$4" > "$CLAUDE_CONFIG_DIR/.mkt-added"; fi
if [ "$1 $2 $3" = "plugin marketplace remove" ]; then rm -f "$CLAUDE_CONFIG_DIR/.mkt-added"; fi
if [ "$1 $2 $3" = "plugin marketplace list" ]; then
  echo "Configured marketplaces:"
  [ -e "$CLAUDE_CONFIG_DIR/.mkt-added" ] && printf '\n  \xe2\x9d\xaf claude-worksessions\n    Source: %s\n' "$(cat "$CLAUDE_CONFIG_DIR/.mkt-added")"
fi
exit 0
""".format(log=log))
    f.chmod(0o755)
    return str(bindir)


def test_install_removes_the_old_hooks_and_installs_no_plugin(tmp_path):
    conf = tmp_path / "ws" / "_config" / "config.env"
    conf.parent.mkdir(parents=True)
    conf.write_text('CWS_WORK_ROOT="{}/ws"\nCWS_PROFILES="personal work"\nCWS_INSTALL_YAZI="0"\n'.format(tmp_path))
    link = tmp_path / ".config" / "claude-worksessions" / "config.env"
    link.parent.mkdir(parents=True)
    link.symlink_to(conf)
    mine = {"type": "command", "command": "my-formatter"}
    bin_ = str(tmp_path / ".local" / "bin")
    old = {"hooks": {
        "PostToolUse": [{"matcher": "Write", "hooks": [mine]},
                        {"matcher": "Bash|mcp__.*", "hooks": [{"type": "command", "command": bin_ + "/claude-hook-notfound", "timeout": 10}]}],
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": bin_ + "/claude-hook-vague", "timeout": 10}]},
                             {"hooks": [{"type": "command", "command": bin_ + "/claude-guard prompt", "timeout": 30}]}],
        "Stop": [{"hooks": [{"type": "command", "command": bin_ + "/claude-guard stop", "timeout": 20}]}]}}
    (tmp_path / ".claude-personal").mkdir()
    (tmp_path / ".claude-personal" / "settings.json").write_text(json.dumps(old))
    # skills in the shared profile belong to the user (e.g. Skillshare): never touched
    own = tmp_path / ".claude-personal" / "skills" / "weekly-review"
    own.mkdir(parents=True)
    (own / "SKILL.md").write_text("mine")
    # claude-plan and claude-vscode links into the checkout, from before 3.0.0 / 3.1.0, are dropped
    os.makedirs(bin_)
    for b in ("claude-plan", "claude-vscode"):
        os.symlink(os.path.join(REPO, "bin", b), os.path.join(bin_, b))
    log = tmp_path / "claude.log"
    env = {k: v for k, v in os.environ.items() if not k.startswith("CWS_")}
    env.update(HOME=str(tmp_path), ZDOTDIR=str(tmp_path), CWS_OS="mac", PATH="/usr/bin:/bin")
    run = lambda *a: subprocess.run(["zsh", os.path.join(REPO, a[0]), *a[1:]], env=env, capture_output=True,
                                    text=True, stdin=subprocess.DEVNULL)
    r = run("install.sh", "--dry-run", "--yes", "--no-bootstrap")
    assert "personal: [dry-run] removed the prompt-quality hooks from settings.json (CWS_HOOKS is off)" in r.stdout
    assert json.loads((tmp_path / ".claude-personal" / "settings.json").read_text()) == old   # dry run: unchanged
    env["PATH"] = _fake_claude(tmp_path, log) + ":/usr/bin:/bin"
    r = run("install.sh", "--yes", "--no-bootstrap")
    assert r.returncode == 0, r.stdout + r.stderr
    # no plugin: install.sh never calls claude plugin
    assert not log.exists() or "plugin" not in log.read_text()
    assert "plugin worksessions" not in r.stdout and "marketplace" not in r.stdout
    # our old hook entries are gone, the user's own stays, retention is kept
    s = json.loads((tmp_path / ".claude-personal" / "settings.json").read_text())
    assert s["hooks"] == {"PostToolUse": [{"matcher": "Write", "hooks": [mine]}]}
    assert s["cleanupPeriodDays"] == 3650
    assert "hooks" not in json.loads((tmp_path / ".claude-work" / "settings.json").read_text())
    assert (own / "SKILL.md").read_text() == "mine" and not list(own.parent.glob("*.bak-*"))
    for b in ("claude-plan", "claude-vscode"):
        assert not os.path.lexists(os.path.join(bin_, b))
        assert "removed {}/{} (no longer part of claude-worksessions)".format(bin_, b) in r.stdout
    # no profile set-up any more: nothing linked between the config dirs, no ~/.claude link
    assert not os.path.islink(tmp_path / ".claude-work" / "projects")
    assert not os.path.lexists(tmp_path / ".claude")
    assert (tmp_path / "ws" / "_config" / "guard-rules.md").read_text().startswith("<!-- claude-guard")
    hook = str(tmp_path / ".local" / "bin" / "claude-hook-notfound")
    assert os.path.islink(hook) and os.path.islink(tmp_path / ".local" / "bin" / "claude-retro")
    # CWS_HOOKS=1: the six entries are written, kept up to date, and never doubled
    conf.write_text(conf.read_text() + 'CWS_HOOKS="1"\n')
    r = run("install.sh", "--yes", "--no-bootstrap")
    assert "personal: added the prompt-quality hooks" in r.stdout, r.stdout + r.stderr
    s = json.loads((tmp_path / ".claude-work" / "settings.json").read_text())
    vague, guard = bin_ + "/claude-hook-vague", bin_ + "/claude-guard"
    assert s["hooks"]["UserPromptSubmit"] == [{"hooks": [{"type": "command", "command": vague, "timeout": 10}]},
                                              {"hooks": [{"type": "command", "command": guard + " prompt", "timeout": 30}]}]
    assert s["hooks"]["Stop"] == [{"hooks": [{"type": "command", "command": guard + " stop", "timeout": 20}]}]
    assert [h["command"] for g in s["hooks"]["PostToolUse"] for h in g["hooks"]] == [bin_ + "/claude-hook-notfound"]
    r = run("install.sh", "--yes", "--no-bootstrap")
    assert "personal: prompt-quality hooks in place" in r.stdout
    assert json.loads((tmp_path / ".claude-personal" / "settings.json").read_text())["hooks"]["PostToolUse"][0]["hooks"] == [mine]
    # uninstall: hooks out, and a plugin left by 2.35-2.38 is removed with its marketplace
    r = run("uninstall.sh")
    assert "removed the prompt-quality hooks from" in r.stdout
    assert "hooks" not in json.loads((tmp_path / ".claude-work" / "settings.json").read_text())
    assert "uninstalled the worksessions plugin from " + str(tmp_path / ".claude-personal") in r.stdout
    assert "removed the claude-worksessions marketplace from " + str(tmp_path / ".claude-work") in r.stdout
    assert not os.path.lexists(hook)


def test_install_warns_on_a_broken_settings_file_for_the_hook(tmp_path):
    (tmp_path / ".claude-personal").mkdir()
    (tmp_path / ".claude-personal" / "settings.json").write_text("{broken")
    r = dry_install(tmp_path, "mac")
    assert "remove them yourself (CWS_HOOKS is off)" in r.stderr


# --- goal / done_when and claude-goal -----------------------------------------------------
def test_claude_new_records_goal_and_done_when(tmp_path):
    (tmp_path / ".claude-personal").mkdir()
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "claude").write_text("#!/bin/sh\nexit 0\n")
    (stub / "claude").chmod(0o755)
    path = str(stub) + os.pathsep + os.environ["PATH"]
    r = run_new(tmp_path, "-t Other -T tooling -g 'list the sources' --done 'a table of sources' demo",
                PATH=path)
    assert r.returncode == 0, r.stderr
    d = json.loads(next(tmp_path.glob("[0-9]*/*/*/*/.session.json")).read_text())
    assert (d["goal"], d["done_when"]) == ("list the sources", "a table of sources")
    shutil.rmtree(next(tmp_path.glob("[0-9]*")))
    r = run_new(tmp_path, "-t Other -T tooling other thing", PATH=path)   # not a terminal: the name
    d = json.loads(next(tmp_path.glob("[0-9]*/*/*/*/.session.json")).read_text())
    assert (d["goal"], d["done_when"]) == ("other thing", "")


def test_path_declares_scope(tmp_path):
    (tmp_path / ".claude-personal").mkdir()
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "claude").write_text("#!/bin/sh\nexit 0\n")
    (stub / "claude").chmod(0o755)
    (tmp_path / "repo one").mkdir()
    (tmp_path / "docs").mkdir()
    path = str(stub) + os.pathsep + os.environ["PATH"]
    r = run_new(tmp_path, "-t Other -T tooling --path '{}' --path ~/docs demo".format(tmp_path / "repo one"),
                PATH=path)
    assert r.returncode == 0, r.stderr
    meta = next(tmp_path.glob("[0-9]*/*/*/*/.session.json"))
    d = json.loads(meta.read_text())
    assert d["paths"] == [str(tmp_path / "repo one"), str(tmp_path / "docs")]
    r = run_new(tmp_path, "-t Other -T tooling --path /no/such/dir x", PATH=path)
    assert r.returncode == 1 and "--path needs an existing folder" in r.stderr
    # claude-goal adds paths without re-anchoring, and shows them
    goal = lambda args: zsh('cd "{}" && claude-goal {}'.format(meta.parent, args), tmp_path)
    (tmp_path / "more").mkdir()
    assert goal("--path '{}' --path '{}'".format(tmp_path / "more", tmp_path / "docs")).startswith("paths: ")
    d = json.loads(meta.read_text())
    assert d["paths"][-1] == str(tmp_path / "more") and len(d["paths"]) == 3 and "goal_history" not in d
    assert "paths: " in goal("")
    out = goal("'new goal' --path '{}'".format(tmp_path / "more"))
    assert "goal: demo -> new goal" in out
    with pytest.raises(subprocess.CalledProcessError) as e:
        goal("--path /no/such/dir")
    assert "--path needs an existing folder" in e.value.stderr


def test_claude_goal_shows_and_reanchors(tmp_path):
    d = tmp_path / "2026" / "09" / "26" / "10-00-00_x"
    (d / "sub").mkdir(parents=True)
    (d / ".session.json").write_text(json.dumps({"name": "x", "goal": "fix the filter"}))
    (d / ".scope.json").write_text(json.dumps({"sessions": {"s1": {"literal": "L", "targets": ["t"], "prompt_no": 4,
                                                                 "extensions": 2, "recent": ["p"],
                                                                 "last_answer": "A"}}}))
    goal = lambda args, cwd=d: zsh('cd "{}" && claude-goal {}'.format(cwd, args), tmp_path)
    assert goal("") == "goal: fix the filter\ndone when: (not stated)\n"
    out = goal("survey the access methods --done 'a comparison table'", d / "sub")
    assert out == "goal: fix the filter -> survey the access methods\ndone when: a comparison table\n"
    meta = json.loads((d / ".session.json").read_text())
    assert meta["goal"] == "survey the access methods" and meta["goal_history"][0]["goal"] == "fix the filter"
    assert json.loads((d / ".scope.json").read_text())["sessions"]["s1"] == {"prompt_no": 4, "last_answer": "A"}
    rec = json.loads((d / ".quality.jsonl").read_text())
    assert rec["event"] == "goal" and rec["previous"] == "fix the filter" and rec["initiated_by"] == "user"
    assert goal("--done ''").endswith("done when: (not stated)\n")
    assert json.loads((d / ".session.json").read_text())["goal"] == "survey the access methods"
    with pytest.raises(subprocess.CalledProcessError) as e:
        zsh('cd "{}" && claude-goal x'.format(tmp_path), tmp_path)
    assert "no .session.json here" in e.value.stderr


def test_claude_wait_shows_sets_flips_and_clears(tmp_path):
    d = tmp_path / "2026" / "10" / "12" / "10-00-00_x"
    (d / "sub").mkdir(parents=True)
    (d / ".session.json").write_text(json.dumps({"name": "x"}))
    wait = lambda args, cwd=d: zsh('cd "{}" && claude-wait {}'.format(cwd, args), tmp_path)
    assert wait("") == "waiting: nobody\n"
    out = wait("them Ana 'confirm the new IP' --where teams --link https://t/1 --since 2026-10-12T08:00:00Z", d / "sub")
    assert out == "waiting: nobody -> waiting on them: Ana -- confirm the new IP (teams) since 2026-10-12\n"
    meta = json.loads((d / ".session.json").read_text())
    assert meta["waiting"] == {"on": "other", "who": "Ana", "what": "confirm the new IP",
                               "since": "2026-10-12T08:00:00Z", "where": "teams", "link": "https://t/1"}
    # the reply came: flip to me, keeping who, where and link; the old flag goes to the history
    out = wait("me")
    assert out.startswith("waiting on them: Ana -- confirm the new IP (teams) since 2026-10-12 -> waiting on me: Ana -- confirm the new IP (teams) since ")
    meta = json.loads((d / ".session.json").read_text())
    assert meta["waiting"]["on"] == "me" and meta["waiting"]["link"] == "https://t/1"
    assert meta["waiting_history"][0]["on"] == "other" and meta["waiting_history"][0]["until"]
    assert wait("none --note 'IP confirmed and added to the allow-list.'").endswith("-> waiting: nobody\n")
    assert "waiting" not in json.loads((d / ".session.json").read_text())
    # every change went to thread.md, with the note under its heading; the show says how many
    t = (d / "thread.md").read_text()
    assert t.startswith("# x\n\nWho said what, in order.")
    heads = [ln for ln in t.splitlines() if ln.startswith("## ")]
    assert [h.split(" · ", 1)[1] for h in heads] == ["waiting on them: Ana -- confirm the new IP (teams)",
                                       "waiting on me: Ana -- confirm the new IP (teams)", "settled"]
    assert t.endswith("· settled\n\nIP confirmed and added to the allow-list.\n\n")
    assert wait("") == "waiting: nobody\nthread.md: 3 entries\n"
    out = wait("them Ana --note 'Asked again.'")
    assert (d / "thread.md").read_text().count("Asked again.") == 1
    assert wait("--help").startswith("claude-wait [me|them|none]")
    with pytest.raises(subprocess.CalledProcessError) as e:
        wait("sideways")
    assert "must be me, them or none" in e.value.stderr
    with pytest.raises(subprocess.CalledProcessError) as e:
        zsh('cd "{}" && claude-wait me'.format(tmp_path), tmp_path)
    assert "no .session.json here" in e.value.stderr


def test_claude_new_offers_to_continue_in_a_recent_folder_on_the_ticket(tmp_path):
    (tmp_path / ".claude-personal").mkdir()
    import datetime
    today = datetime.datetime.now().strftime("%Y/%m/%d")
    d = tmp_path / today / "09-00-00_first-look"
    d.mkdir(parents=True)
    (d / ".session.json").write_text(json.dumps({"name": "First look", "ticket": "PROJ-1", "profile": "personal"}))
    # Enter takes the offer: no new folder, Claude starts in the old one
    r = run_new_tty(tmp_path, "-t PROJ-1 -T tooling -a second look", "\n")
    assert r.returncode == 0, r.stderr
    assert "PROJ-1 has recent request folders:" in r.stdout and "1) {}/09-00-00_first-look  First look  (today)".format(today) in r.stdout
    assert "2) a new folder" in r.stdout and "continuing in {}/09-00-00_first-look".format(today) in r.stdout
    assert len(list(tmp_path.glob("[0-9]*/*/*/*/.session.json"))) == 1
    # the last number makes a new folder; --new never asks; another ticket never asks; Other never asks
    r = run_new_tty(tmp_path, "-t PROJ-1 -T tooling -a second look", "2\n\n\n")
    assert r.returncode == 0, r.stderr
    assert len(list(tmp_path.glob("[0-9]*/*/*/*/.session.json"))) == 2
    r = run_new_tty(tmp_path, "--new -t PROJ-1 -T tooling -a third", "\n\n")
    assert r.returncode == 0, r.stderr and "recent request folders" not in r.stdout
    assert len(list(tmp_path.glob("[0-9]*/*/*/*/.session.json"))) == 3
    r = run_new_tty(tmp_path, "-t PROJ-2 -T tooling -a other ticket", "\n\n")
    assert r.returncode == 0 and "recent request folders" not in r.stdout
    r = run_new_tty(tmp_path, "-t PROJ-1 -T tooling -a bad pick", "9\n")
    assert r.returncode == 1 and "invalid choice '9'" in r.stderr


def test_continuing_in_a_recent_folder_opens_it_in_t3(tmp_path):
    (tmp_path / ".claude-personal").mkdir()
    import datetime
    d = tmp_path / datetime.datetime.now().strftime("%Y/%m/%d") / "09-00-00_first-look"
    d.mkdir(parents=True)
    (d / ".session.json").write_text(json.dumps({"name": "First look", "ticket": "PROJ-1", "profile": "personal"}))
    stub = tmp_path / "bin"
    stub.mkdir()
    (stub / "claude-t3-sync").write_text('#!/bin/sh\necho "$*" > "$HOME/t3-opened"\n')
    (stub / "claude-t3-sync").chmod(0o755)
    r = run_new_tty(tmp_path, "-t PROJ-1 -T tooling -a second look", "\n", env={"CWS_OPEN": "t3"})
    assert r.returncode == 0, r.stderr
    assert (tmp_path / "t3-opened").read_text().split() == ["--open", str(d), "--prompt"]


def test_recent_folder_age_counts_calendar_days(tmp_path):
    import datetime
    yesterday = datetime.date.today() - datetime.timedelta(days=1)
    d = tmp_path / yesterday.strftime("%Y/%m/%d") / "23-59-59_late"
    d.mkdir(parents=True)
    (d / ".session.json").write_text(json.dumps({"name": "Late", "ticket": "PROJ-7"}))
    out = zsh('_cws_recent_folders PROJ-7 14', tmp_path)
    assert out.strip().endswith("Late  (1d ago)")


def area_stubs(tmp_path):
    """claude-area and claude-t3-sync stubs that log, in order, to calls.log: the name, then each
    argument in brackets, so one word holding a space ("[--type data]") shows apart from two."""
    (tmp_path / ".claude-personal").mkdir()
    stub = tmp_path / "bin"
    stub.mkdir()
    log = tmp_path / "calls.log"
    for name in ("claude-area", "claude-t3-sync"):
        p = stub / name
        p.write_text('#!/bin/sh\n{{ printf %s "{}"; for a in "$@"; do printf " [%s]" "$a"; done; echo; }} >> "{}"\n'
                     .format(name, log))
        p.chmod(0o755)
    return "{}:{}".format(stub, os.environ["PATH"]), log


def test_claude_new_picks_the_area_before_t3_sees_the_folder(tmp_path):
    # a config from before 3.1: no CWS_AFTER_NEW_CMD line, so claude-area runs when installed
    path, log = area_stubs(tmp_path)
    r = run_new(tmp_path, '-n --new -t Other -T tooling -g goal "x"', PATH=path, CWS_OPEN="t3",
                CWS_AFTER_NEW_CMD=None)
    assert r.returncode == 0, r.stderr
    lines = log.read_text().splitlines()
    assert lines[0].startswith("claude-area [--dir] ") and lines[0].endswith(" [--pick] [] [--type] []")
    assert lines[1].startswith("claude-t3-sync [--open] ")


def test_claude_new_project_and_type_flags_pass_through(tmp_path):
    path, log = area_stubs(tmp_path)
    r = run_new(tmp_path, '-n --new -t Other -T tooling -g goal -A contact360 -F data "x"', PATH=path,
                CWS_OPEN="t3", CWS_AFTER_NEW_CMD=None)
    assert r.returncode == 0, r.stderr
    assert log.read_text().splitlines()[0].endswith(" [--pick] [contact360] [--type] [data]")


def test_after_new_cmd_is_filled_in_with_separate_arguments(tmp_path):
    path, log = area_stubs(tmp_path)
    r = run_new(tmp_path, '-n --new -t Other -T tooling -A "big project" -F data "x y"', PATH=path,
                CWS_AFTER_NEW_CMD="claude-area {project} --type {type} --title {title}")
    assert r.returncode == 0, r.stderr
    assert log.read_text().splitlines() == ["claude-area [big project] [--type] [data] [--title] [x y]"]


def test_empty_after_new_cmd_runs_nothing(tmp_path):
    path, log = area_stubs(tmp_path)
    r = run_new(tmp_path, '-n --new -t Other -T tooling "x"', PATH=path, CWS_AFTER_NEW_CMD="", CWS_OPEN="t3")
    assert r.returncode == 0, r.stderr
    assert [ln.split()[0] for ln in log.read_text().splitlines()] == ["claude-t3-sync"]


def test_a_failing_after_new_cmd_doesnt_stop_the_open(tmp_path):
    r = run_new(tmp_path, '-n --new -t Other -T tooling "x"', CWS_AFTER_NEW_CMD="false",
                CWS_OPEN_CMD="echo OPENED")
    assert r.returncode == 0, r.stderr
    assert r.stdout.splitlines()[-1] == "OPENED"


def type_session(root):
    d = root / "2026" / "11" / "07" / "13-39-18_pilot"
    d.mkdir(parents=True)
    (d / ".session.json").write_text(json.dumps({"name": "pilot", "task_type": "permissions"}))
    return d


def run_type(root, d, value, request_types="data networking access"):
    env = dict(os.environ, CLAUDE_WORK_ROOT=str(root), CWS_TASK_TYPES="permissions, support",
               CWS_TYPES=request_types, CWS_CONFIG=os.devnull, ZDOTDIR=str(root))
    src = 'source "{}/shell/worksessions.zsh"\ncd "{}"\nclaude-type --folder "{}"'.format(REPO, d, value)
    return subprocess.run(["zsh", "-fc", src], env=env, capture_output=True, text=True)


def test_claude_type_points_a_request_type_to_claude_area(tmp_path):
    d = type_session(tmp_path)
    r = run_type(tmp_path, d, "networking")
    assert r.returncode == 1
    assert "not a task type" in r.stderr and "claude-area --type networking" in r.stderr
    assert json.loads((d / ".session.json").read_text())["task_type"] == "permissions"


def test_claude_type_rejects_an_unknown_type(tmp_path):
    d = type_session(tmp_path)
    r = run_type(tmp_path, d, "banana")
    assert r.returncode == 1 and "claude-area" not in r.stderr


@pytest.mark.parametrize("value", ["support", "Support", "permissions"])
def test_claude_type_accepts_seeded_and_used_types(tmp_path, value):
    d = type_session(tmp_path)
    r = run_type(tmp_path, d, value)
    assert r.returncode == 0, r.stderr
    assert json.loads((d / ".session.json").read_text())["task_type"] == value
