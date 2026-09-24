"""mcp/configure.py: questions → config.env → each profile's mcpServers."""

import importlib.util
import json
import os
import stat

import pytest

from conftest import REPO


def load():
    spec = importlib.util.spec_from_file_location("mcp_configure", os.path.join(REPO, "mcp", "configure.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


CATALOG = {
    "inputs": {"org": "Your organisation", "tok": "API token for Example"},
    "questions": [
        {"key": "CWS_MCP_EMAIL", "ask": "Email provider?", "choices": [
            {"id": "m365", "label": "Microsoft 365", "connector": "Microsoft 365"},
            {"id": "none", "label": "None"}]},
        {"key": "CWS_MCP_GIT", "ask": "Git provider?", "choices": [
            {"id": "ado", "label": "Azure DevOps", "servers": ["ado"]},
            {"id": "example", "label": "Example", "servers": ["example"]},
            {"id": "none", "label": "None"}]},
        {"key": "CWS_MCP_CLOUD", "ask": "Cloud?", "multi": True, "choices": [
            {"id": "a", "label": "A", "servers": ["a-server", "shared"]},
            {"id": "b", "label": "B", "servers": ["shared"], "note": "B is set up by hand"},
            {"id": "b2", "label": "B again", "note": "B is set up by hand"},
            {"id": "none", "label": "None"}]},
    ],
    "servers": {
        "ado": {"config": {"type": "stdio", "command": "{{npx}}", "args": ["-y", "@azure-devops/mcp", "{{org}}"]}},
        "example": {"config": {"type": "http", "url": "https://example.test/mcp",
                               "headers": {"Authorization": "Bearer {{secret:tok}}"}}},
        "a-server": {"config": {"type": "stdio", "command": "{{python}}", "args": ["{{repo}}/mcp/x.py"]}},
        "shared": {"config": {"type": "http", "url": "https://shared.test/mcp"}},
    },
}


@pytest.fixture
def mcp():
    return load()


@pytest.fixture
def conf(tmp_path):
    p = tmp_path / "config.env"
    p.write_text('CWS_ORG="Contoso"\n')
    return p


def feeder(*lines):
    it = iter(lines)
    return lambda prompt="": next(it)


def test_real_catalog_is_consistent(mcp):
    cat = mcp.load_catalog()
    keys = set()
    for q in cat["questions"]:
        assert q["key"].startswith("CWS_MCP_") and q["key"] not in keys
        keys.add(q["key"])
        ids = [c["id"] for c in q["choices"]]
        assert "none" in ids and len(ids) == len(set(ids))
        for c in q["choices"]:
            for s in c.get("servers", []):
                assert s in cat["servers"], s
    for name, server in cat["servers"].items():
        for secret, key in mcp.PLACEHOLDER.findall(json.dumps(server["config"])):
            assert key in ("repo", "npx", "python") or key in cat["inputs"], (name, key)
    # nothing company-specific: every address is a vendor's own, or a placeholder
    vendors = ("mcp.atlassian.com", "api.githubcopilot.com", "mcp.notion.com", "mcp.linear.app",
               "learn.microsoft.com", "knowledge-mcp.global.api.aws", "mcp.context7.com")
    for name, server in cat["servers"].items():
        url = server["config"].get("url")
        if url:
            host = url.split("/")[2]
            assert host in vendors or "{{" in host, (name, host)


def test_config_read_and_write(mcp, conf):
    mcp.set_config(str(conf), "CWS_MCP_GIT", "ado")
    mcp.set_config(str(conf), "CWS_MCP_GIT", 'ex "q"')
    assert mcp.read_config(str(conf)) == {"CWS_ORG": "Contoso", "CWS_MCP_GIT": 'ex \\"q\\'}
    assert conf.read_text().count("CWS_MCP_GIT") == 1
    new = conf.parent / "new.env"
    mcp.set_config(str(new), "A", "1")
    assert new.read_text() == 'A="1"\n'
    noeol = conf.parent / "noeol.env"
    noeol.write_text('X="1"')
    mcp.set_config(str(noeol), "Y", "2")
    assert noeol.read_text() == 'X="1"\nY="2"\n'
    assert mcp.read_config(str(conf.parent / "missing.env")) == {}


def test_ask_saves_answers_and_needed_values(mcp, conf):
    out = []
    names = mcp.ask(CATALOG, str(conf), read=feeder("1", "9", "1", "1 2 4", "", "contoso"), write=out.append)
    cfg = mcp.read_config(str(conf))
    assert (cfg["CWS_MCP_EMAIL"], cfg["CWS_MCP_GIT"], cfg["CWS_MCP_CLOUD"]) == ("m365", "ado", "a b")   # "none" dropped
    assert cfg["CWS_MCP_ORG"] == "contoso"
    assert names == ["ado", "a-server", "shared"]
    assert "  pick one number from the list" in out and "  needed by a server you chose" in out
    # asked again: saved answers are the defaults
    out.clear()
    mcp.ask(CATALOG, str(conf), read=feeder("", "", "", ""), write=out.append)
    assert mcp.read_config(str(conf))["CWS_MCP_CLOUD"] == "a b"
    assert mcp.read_config(str(conf))["CWS_MCP_ORG"] == "contoso"
    # a fresh config defaults to "none"
    fresh = conf.parent / "fresh.env"
    mcp.ask(CATALOG, str(fresh), read=feeder("", "", "x", "4"), write=out.append)
    assert mcp.read_config(str(fresh)) == {"CWS_MCP_EMAIL": "none", "CWS_MCP_GIT": "none", "CWS_MCP_CLOUD": "none"}
    assert "  pick numbers from the list" in out


def test_selected_and_show(mcp, conf):
    out = []
    mcp.show(CATALOG, str(conf), write=out.append)
    assert "(not answered)" in out[0] and out[-1] == "servers: none"
    for k, v in [("CWS_MCP_EMAIL", "m365"), ("CWS_MCP_GIT", "example"), ("CWS_MCP_CLOUD", "a b b2")]:
        mcp.set_config(str(conf), k, v)
    names, notes = mcp.selected(CATALOG, mcp.read_config(str(conf)))
    assert names == ["example", "a-server", "shared"]
    assert notes == ["connect in claude.ai (Settings > Connectors): Microsoft 365", "B is set up by hand"]
    out.clear()
    mcp.show(CATALOG, str(conf), write=out.append)
    assert "Microsoft 365" in out[0] and "A, B, B again" in out[2]
    assert out[-2:] == ["connect in claude.ai (Settings > Connectors): Microsoft 365", "B is set up by hand"]


def test_fill_and_existing_secrets(mcp):
    vals = {"org": "o", "tok": "T"}
    assert mcp.fill({"a": ["x-{{org}}", 1], "b": "Bearer {{secret:tok}}"}, vals) == {"a": ["x-o", 1], "b": "Bearer T"}
    assert mcp.fill({"a": "{{missing}}"}, vals) is None
    assert mcp.fill(["{{missing}}"], vals) is None
    server = CATALOG["servers"]["example"]
    have = {"type": "http", "url": "https://example.test/mcp", "headers": {"Authorization": "Bearer abc123"}}
    assert mcp.existing_secrets(server, have) == {"tok": "abc123"}
    assert mcp.existing_secrets(server, None) == {}
    assert mcp.existing_secrets(server, {"headers": {"Authorization": "Bearer "}}) == {}
    assert mcp.existing_secrets(server, {"headers": {"Authorization": "Basic x"}}) == {}
    listy = {"config": {"args": ["--token={{secret:tok}}"]}}
    assert mcp.existing_secrets(listy, {"args": ["--token=zz"]}) == {"tok": "zz"}


def profile(tmp_path, name, servers=None, mode=0o600, raw=None):
    d = tmp_path / (".claude-" + name)
    d.mkdir()
    f = d / ".claude.json"
    f.write_text(raw if raw is not None else json.dumps({"numStartups": 3, "mcpServers": servers or {}}))
    os.chmod(f, mode)
    return d


def test_apply_adds_updates_removes_and_keeps_hand_made_servers(mcp, conf, tmp_path, monkeypatch):
    monkeypatch.setattr(mcp, "tool_paths", lambda: {"repo": "/r", "npx": "/bin/npx", "python": "/bin/python3"})
    for k, v in [("CWS_MCP_EMAIL", "m365"), ("CWS_MCP_GIT", "ado"), ("CWS_MCP_CLOUD", "a"), ("CWS_MCP_ORG", "acme")]:
        mcp.set_config(str(conf), k, v)
    mine = {"gateway": {"type": "http", "url": "https://gw.test"}}
    p1 = profile(tmp_path, "personal", dict(mine, example={"type": "http", "url": "old"},
                                            shared={"type": "http", "url": "https://shared.test/mcp"}))
    p2 = profile(tmp_path, "work", mode=0o644)
    out = []
    mcp.apply(CATALOG, str(conf), [str(p1), str(p2)], write=out.append)
    d1 = json.loads((p1 / ".claude.json").read_text())
    assert d1["numStartups"] == 3 and d1["mcpServers"]["gateway"] == mine["gateway"]       # untouched
    assert "example" not in d1["mcpServers"]                                              # not chosen: removed
    assert d1["mcpServers"]["ado"] == {"type": "stdio", "command": "/bin/npx", "args": ["-y", "@azure-devops/mcp", "acme"]}
    assert d1["mcpServers"]["a-server"]["args"] == ["/r/mcp/x.py"]
    assert out[0] == "personal: added ado; removed example; added a-server"
    assert out[1] == "work: added ado; added a-server; added shared"
    assert out[-1] == "connect in claude.ai (Settings > Connectors): Microsoft 365"
    assert stat.S_IMODE(os.stat(p1 / ".claude.json").st_mode) == 0o600
    assert stat.S_IMODE(os.stat(p2 / ".claude.json").st_mode) == 0o644                    # mode kept
    assert json.loads((p1 / ".claude.json.bak-mcp").read_text())["mcpServers"]["example"] == {"type": "http", "url": "old"}
    out.clear()
    mcp.apply(CATALOG, str(conf), [str(p1)], write=out.append)
    assert out[0] == "personal: MCP servers up to date (ado, a-server, shared)"


def test_apply_secrets_are_asked_kept_or_skipped(mcp, conf, tmp_path):
    mcp.set_config(str(conf), "CWS_MCP_GIT", "example")
    asked = []
    p1 = profile(tmp_path, "personal", {"example": {"type": "http", "url": "https://example.test/mcp",
                                                    "headers": {"Authorization": "Bearer keep-me"}}})
    p2 = profile(tmp_path, "work")
    p3 = profile(tmp_path, "ops")
    answers = iter(["new-token", None])
    out = []
    mcp.apply(CATALOG, str(conf), [str(p1), str(p2), str(p3)], write=out.append,
              ask_secret=lambda s, k, prompt: asked.append((s, k, prompt)) or next(answers))
    assert json.loads((p1 / ".claude.json").read_text())["mcpServers"]["example"]["headers"]["Authorization"] == "Bearer keep-me"
    assert json.loads((p2 / ".claude.json").read_text())["mcpServers"]["example"]["headers"]["Authorization"] == "Bearer new-token"
    assert "example" not in json.loads((p3 / ".claude.json").read_text())["mcpServers"]
    assert asked == [("example", "tok", "API token for Example")] * 2                         # not for p1: it had one
    assert "ops: example needs a value that wasn't given -- skipped (./install.sh --mcp)" in out
    assert "new-token" not in (conf).read_text()                                              # never in config.env


def test_apply_dry_run_unanswered_missing_and_broken_profiles(mcp, conf, tmp_path):
    out = []
    p = profile(tmp_path, "personal")
    assert mcp.apply(CATALOG, str(conf), [str(p)], write=out.append) == 0
    assert out == ["MCP servers: not set up yet -- run ./install.sh --mcp to choose them"]
    mcp.set_config(str(conf), "CWS_MCP_CLOUD", "b")
    out.clear()
    before = (p / ".claude.json").read_text()
    mcp.apply(CATALOG, str(conf), [str(p)], dry=True, write=out.append)
    assert out == ["personal: [dry-run] added shared", "B is set up by hand"]
    assert (p / ".claude.json").read_text() == before
    fresh = tmp_path / ".claude-new"
    fresh.mkdir()
    bad = profile(tmp_path, "bad", raw="{nope")
    out.clear()
    mcp.apply(CATALOG, str(conf), [str(fresh), str(bad)], write=out.append)
    assert json.loads((fresh / ".claude.json").read_text())["mcpServers"] == {"shared": {"type": "http", "url": "https://shared.test/mcp"}}
    assert stat.S_IMODE(os.stat(fresh / ".claude.json").st_mode) == 0o600
    assert "bad: " in out[1] and "isn't valid JSON" in out[1]


def test_inputs_needed_and_tool_paths(mcp):
    assert mcp.inputs_needed(CATALOG, ["ado", "example", "a-server"]) == {"org": "Your organisation"}
    t = mcp.tool_paths()
    assert t["repo"] == REPO and t["npx"] and t["python"]


def test_main(mcp, conf, tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(mcp, "load_catalog", lambda: CATALOG)
    assert mcp.main([]) == 2 and "configure.py ask" in capsys.readouterr().err
    assert mcp.main(["apply", str(conf)]) == 2
    assert mcp.main(["show", str(conf)]) == 0 and "servers: none" in capsys.readouterr().out
    monkeypatch.setattr("builtins.input", feeder("1", "3", "4"))
    assert mcp.main(["ask", str(conf)]) == 0
    mcp.set_config(str(conf), "CWS_MCP_GIT", "example")
    p = profile(tmp_path, "personal")
    monkeypatch.setattr(mcp.sys.stdin, "isatty", lambda: True, raising=False)
    import getpass
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "sekret")
    assert mcp.main(["apply", str(conf), str(p)]) == 0
    assert json.loads((p / ".claude.json").read_text())["mcpServers"]["example"]["headers"]["Authorization"] == "Bearer sekret"
    p2 = profile(tmp_path, "work")
    assert mcp.main(["apply", str(conf), str(p2), "--yes"]) == 0                             # --yes: no prompt, skipped
    assert "example" not in json.loads((p2 / ".claude.json").read_text())["mcpServers"]
    assert mcp.main(["apply", str(conf), "--dry-run"]) == 0


def test_apply_keeps_settings_the_catalog_does_not_manage(mcp, conf, tmp_path):
    mcp.set_config(str(conf), "CWS_MCP_CLOUD", "b")
    p = profile(tmp_path, "personal", {"shared": {"type": "http", "url": "https://old.test/mcp",
                                                  "oauth": {"clientId": "abc"}, "headers": {"X-Extra": "1"}}})
    mcp.apply(CATALOG, str(conf), [str(p)], write=lambda s: None)
    assert json.loads((p / ".claude.json").read_text())["mcpServers"]["shared"] == {
        "type": "http", "url": "https://shared.test/mcp", "oauth": {"clientId": "abc"}, "headers": {"X-Extra": "1"}}
    assert mcp.merge({"h": {"a": 1, "b": 2}}, {"h": {"a": 9}}) == {"h": {"a": 9, "b": 2}}
    assert mcp.merge(None, {"x": 1}) == {"x": 1} and mcp.merge({"x": 1}, "str") == "str"
