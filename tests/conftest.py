"""Load bin/claude-audit and bin/claude-search as modules against a throwaway HOME.

Both scripts read their config at import time, so every test gets a fresh import
with HOME, the work root and the config file pointing into tmp_path.
"""

import importlib.machinery
import importlib.util
import os
import sys

import pytest

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
BIN = os.path.join(REPO, "bin")


def load_script(name):
    path = os.path.join(BIN, name)
    mod_name = name.replace("-", "_")
    loader = importlib.machinery.SourceFileLoader(mod_name, path)
    spec = importlib.util.spec_from_loader(mod_name, loader)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = mod
    loader.exec_module(mod)
    return mod


@pytest.fixture
def home(tmp_path, monkeypatch):
    """An empty HOME with a work root and a config file; returns the HOME path."""
    h = tmp_path / "home"
    root = h / "work_sessions"
    root.mkdir(parents=True)
    conf = h / ".config" / "claude-worksessions" / "config.env"
    conf.parent.mkdir(parents=True)
    conf.write_text('CWS_WORK_ROOT="{}"\nCWS_PROFILES="personal work"\n'.format(root))
    for k in list(os.environ):
        if k.startswith("CWS_") or k == "CLAUDE_WORK_ROOT":
            monkeypatch.delenv(k)
    monkeypatch.setenv("HOME", str(h))
    monkeypatch.setenv("CWS_CONFIG", str(conf))
    monkeypatch.setattr(os.path, "expanduser",
                        lambda p, _orig=os.path.expanduser: str(h) + p[1:] if p.startswith("~") else p)
    return h


@pytest.fixture
def audit(home):
    return load_script("claude-audit")


@pytest.fixture
def search(home):
    return load_script("claude-search")


@pytest.fixture
def sessions(home):
    return load_script("claude-sessions")


@pytest.fixture
def deleter(home):
    return load_script("claude-delete")
