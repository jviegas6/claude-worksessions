"""bin/claude-plan: the plan on disk, the read-only ✨ call, the local server and the CLI."""

import json
import os
import signal
import stat
import subprocess
import threading
import time
import urllib.error
import urllib.request

import pytest

from conftest import load_script


@pytest.fixture
def cp(home):
    return load_script("claude-plan")


@pytest.fixture
def req(home):
    d = home / "work_sessions" / "2026" / "11" / "01" / "10-00-00_some-request"
    d.mkdir(parents=True)
    return d


def plan_doc(n=1):
    return {"ticket": "ABC-1", "title": "t", "goal": "g", "success": "s", "deadline": "",
            "nodes": [{"id": "s{}".format(i), "title": "step", "deps": []} for i in range(n)]}


# --- the plan on disk ---------------------------------------------------------------------

def test_request_dir_inside_root_only(cp, req, home, tmp_path):
    assert cp.request_dir(str(req)) == os.path.realpath(str(req))
    for bad in ("", str(req / "missing"), str(tmp_path)):
        with pytest.raises(ValueError):
            cp.request_dir(bad)


def test_write_read_versions_and_conflicts(cp, req):
    d = str(req)
    assert cp.read_plan(d) == (None, None)
    m1, backup = cp.write_plan(d, plan_doc(1), None)
    assert backup is None and cp.read_plan(d) == (plan_doc(1), m1)
    with pytest.raises(cp.Conflict):          # someone saved since the editor loaded
        cp.write_plan(d, plan_doc(2), None)
    time.sleep(0.01)
    m2, backup = cp.write_plan(d, plan_doc(2), m1)
    assert backup == "plan.v1.json" and json.load(open(req / "plan.v1.json")) == plan_doc(1)
    assert m2 != m1 and len(cp.read_plan(d)[0]["nodes"]) == 2
    (req / "plan.v7.json").write_text("{}")
    assert cp.next_version(d) == 8
    with pytest.raises(cp.Conflict):
        cp.write_plan(d, plan_doc(3), m1)
    with pytest.raises(ValueError):
        cp.write_plan(d, {"nodes": "no"}, m2)


# --- ✨ ---------------------------------------------------------------------------------------

def test_config_dir_follows_the_session_profile(cp, req, home):
    assert cp.config_dir(str(req)) == os.path.join(str(home), ".claude-personal")
    (req / ".session.json").write_text('{"profile": "work"}')
    cp.CA._meta_cache.clear()
    assert cp.config_dir(str(req)) == os.path.join(str(home), ".claude-work")
    other = req.parent / "10-00-01_other"
    other.mkdir()
    cp.CA.CONFIG["CWS_DEFAULT_PROFILE"] = "work"
    assert cp.config_dir(str(other)).endswith(".claude-work")


def test_claude_bin(cp, home, monkeypatch):
    stub = home / "myclaude"
    stub.write_text("#!/bin/sh\n")
    stub.chmod(0o755)
    cp.CA.CONFIG["CWS_CLAUDE_BIN"] = str(stub)
    assert cp.claude_bin() == str(stub)
    cp.CA.CONFIG["CWS_CLAUDE_BIN"] = ""
    monkeypatch.setattr(cp.shutil, "which", lambda name: None)
    with pytest.raises(RuntimeError):
        cp.claude_bin()


def test_clipboard(cp, monkeypatch):
    calls = []
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/x/" + name if name == "wl-copy" else None)
    monkeypatch.setattr(cp.subprocess, "run", lambda cmd, **kw: calls.append((cmd, kw["input"])))
    assert cp.copy_to_clipboard("hi") is True and calls == [(["wl-copy"], "hi")]
    monkeypatch.setattr(cp.shutil, "which", lambda name: None)
    assert cp.copy_to_clipboard("hi") is False


CLAUDE_STUB = """#!/bin/sh
printf '%s\\n' "$@" > "{log}"
echo "$CLAUDE_CONFIG_DIR" > "{log}.env"
pwd > "{log}.cwd"
cat > "{log}.stdin"
[ -e "{fail}" ] && {{ echo "boom" >&2; exit 3; }}
[ -e "{empty}" ] && exit 0
echo '{{"suggestions":[]}}'
"""


@pytest.fixture
def claude(cp, home, monkeypatch):
    log, fail, empty = home / "claude.log", home / "claude.fail", home / "claude.empty"
    stub = home / "claude"
    stub.write_text(CLAUDE_STUB.format(log=log, fail=fail, empty=empty))
    stub.chmod(0o755)
    cp.CA.CONFIG["CWS_CLAUDE_BIN"] = str(stub)
    clip = []
    monkeypatch.setattr(cp, "copy_to_clipboard", lambda text: clip.append(text) or True)
    return {"log": log, "fail": fail, "empty": empty, "clip": clip}


def test_ask_runs_claude_read_only(cp, req, home, claude):
    assert cp.ask(str(req), "DAG-SUGGEST x") == '{"suggestions":[]}'
    args = claude["log"].read_text().splitlines()
    assert args[:3] == ["-p", "--tools", "Read,Grep,Glob"]
    assert "--strict-mcp-config" in args and "--no-session-persistence" in args
    assert claude["log"].with_suffix(".log.env").read_text().strip() == os.path.join(str(home), ".claude-personal")
    assert os.path.realpath(claude["log"].with_suffix(".log.cwd").read_text().strip()) == os.path.realpath(str(req))
    assert claude["log"].with_suffix(".log.stdin").read_text() == "DAG-SUGGEST x"
    assert claude["clip"] == ['{"suggestions":[]}']


def test_ask_failures(cp, req, claude, monkeypatch):
    claude["fail"].write_text("")
    with pytest.raises(RuntimeError, match="boom"):
        cp.ask(str(req), "DAG-SUGGEST")
    claude["fail"].unlink()
    claude["empty"].write_text("")
    with pytest.raises(RuntimeError, match="no output"):
        cp.ask(str(req), "DAG-SUGGEST")
    claude["empty"].unlink()
    monkeypatch.setattr(cp, "copy_to_clipboard", lambda text: False)
    with pytest.raises(RuntimeError, match="clipboard"):
        cp.ask(str(req), "DAG-SUGGEST")

    def slow(*a, **kw):
        raise subprocess.TimeoutExpired("claude", 1)
    monkeypatch.setattr(cp.subprocess, "run", slow)
    with pytest.raises(RuntimeError, match="more than"):
        cp.ask(str(req), "DAG-SUGGEST")


# --- the server -----------------------------------------------------------------------------

@pytest.fixture
def server(cp):
    srv = cp.http.server.ThreadingHTTPServer(("127.0.0.1", 0), cp.make_handler("tok"))
    t = threading.Thread(target=srv.serve_forever, daemon=True)
    t.start()
    yield "http://127.0.0.1:{}".format(srv.server_address[1])
    srv.shutdown()
    srv.server_close()


def call(url, method="GET", body=None, token="tok"):
    data = body if body is None or isinstance(body, bytes) else json.dumps(body).encode()
    r = urllib.request.Request(url, data=data, method=method, headers={"X-Token": token})
    try:
        with urllib.request.urlopen(r) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if resp.headers["Content-Type"] == "application/json" else raw)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_server_routes(cp, req, server, monkeypatch):
    q = "?dir=" + urllib.request.quote(str(req), safe="")
    status, page = call(server + "/")
    assert status == 200 and b"<title>Plan</title>" in page
    assert call(server + "/health")[1]["ok"] is True
    assert call(server + "/health", token="bad")[0] == 403
    assert call(server + "/plan" + q, token="bad")[0] == 403
    assert call(server + "/nope")[0] == 404 and call(server + "/nope", "POST", b"")[0] == 404
    assert call(server + "/plan?dir=%2Ftmp")[0] == 400

    status, o = call(server + "/plan" + q)
    assert status == 200 and o == {"plan": None, "mtime": None, "name": req.name}
    status, o = call(server + "/plan" + q, "POST", {"base": None, "plan": plan_doc()})
    assert status == 200 and o["backup"] is None
    assert call(server + "/mtime" + q)[1]["mtime"] == o["mtime"]
    assert isinstance(o["mtime"], str)  # a JSON number past 2**53 comes back rounded from JavaScript
    assert call(server + "/plan" + q, "POST", {"base": None, "plan": plan_doc()})[0] == 409
    assert call(server + "/plan" + q, "POST", {"base": o["mtime"], "plan": {}})[0] == 400

    assert call(server + "/ask" + q, "POST", b"hello")[0] == 400
    monkeypatch.setattr(cp, "ask", lambda d, text: "the reply")
    assert call(server + "/ask" + q, "POST", b"DAG-SUGGEST x")[1] == {"ok": True, "reply": "the reply"}

    def broken(d, text):
        raise RuntimeError("no claude")
    monkeypatch.setattr(cp, "ask", broken)
    assert call(server + "/ask" + q, "POST", b"DAG-SUGGEST x") == (502, {"error": "no claude"})


def test_state_file_is_private(cp):
    assert cp.read_state() is None
    cp.write_state({"pid": 1, "port": 2, "token": "t"})
    assert cp.read_state()["token"] == "t"
    assert stat.S_IMODE(os.stat(cp.STATE).st_mode) == 0o600


def test_bind_moves_to_a_free_port(cp, monkeypatch):
    seen = []

    def fake(addr, handler):
        seen.append(addr[1])
        if len(seen) < 3:
            raise OSError("in use")
        return "srv"
    monkeypatch.setattr(cp.http.server, "ThreadingHTTPServer", fake)
    assert cp.bind(9000) == "srv" and seen == [9000, 9001, 9002]
    monkeypatch.setattr(cp.http.server, "ThreadingHTTPServer", lambda a, h: (_ for _ in ()).throw(OSError()))
    with pytest.raises(SystemExit):
        cp.bind(9000)


def test_serve_until_sigterm(cp, monkeypatch):
    cp.CA.CONFIG["CWS_PLAN_PORT"] = "0"

    def stop_when_up():
        for _ in range(100):
            state = cp.read_state()
            if state and cp.alive(state):
                os.kill(os.getpid(), signal.SIGTERM)
                return
            time.sleep(0.05)
    old = signal.getsignal(signal.SIGTERM)
    threading.Thread(target=stop_when_up, daemon=True).start()
    try:
        cp.serve()
    finally:
        signal.signal(signal.SIGTERM, old)
    assert cp.read_state() is None


def test_alive(cp, server):
    port = int(server.rsplit(":", 1)[1])
    assert cp.alive(None) is False
    assert cp.alive({"port": port, "token": "tok"}) is True
    assert cp.alive({"port": port, "token": "bad"}) is False


def test_ensure_server(cp, monkeypatch):
    up = {"pid": 1, "port": 1, "token": "t"}
    monkeypatch.setattr(cp, "read_state", lambda: up)
    monkeypatch.setattr(cp, "alive", lambda s: True)
    assert cp.ensure_server() is up

    started = []
    answers = iter([False, False, True])
    monkeypatch.setattr(cp, "alive", lambda s: next(answers))
    monkeypatch.setattr(cp.subprocess, "Popen", lambda args, **kw: started.append(args))
    assert cp.ensure_server() is up and started[0][-1] == "--serve"

    monkeypatch.setattr(cp, "alive", lambda s: False)
    with pytest.raises(SystemExit, match="did not start"):
        cp.ensure_server(wait=0.3)


def test_url_and_open(cp, monkeypatch):
    assert cp.url_for({"port": 8765, "token": "T"}, "/a b") == "http://127.0.0.1:8765/?dir=%2Fa%20b#T"
    opened = []
    monkeypatch.setattr(cp.shutil, "which", lambda name: "/x" if name == "xdg-open" else None)
    monkeypatch.setattr(cp.subprocess, "run", lambda cmd, **kw: opened.append(cmd))
    assert cp.open_url("u") is True and opened == [["xdg-open", "u"]]
    monkeypatch.setattr(cp.shutil, "which", lambda name: None)
    assert cp.open_url("u") is False


def test_stop(cp, monkeypatch, capsys):
    cp.stop()
    assert "not running" in capsys.readouterr().out
    cp.write_state({"pid": 123, "port": 1, "token": "t"})
    cp.stop()                                   # stale: the file goes
    assert cp.read_state() is None
    killed = []
    cp.write_state({"pid": 123, "port": 1, "token": "t"})
    monkeypatch.setattr(cp, "alive", lambda s: True)
    monkeypatch.setattr(cp.os, "kill", lambda pid, sig: killed.append((pid, sig)))
    cp.stop()
    assert killed == [(123, signal.SIGTERM)] and "stopped" in capsys.readouterr().out


def test_main(cp, req, monkeypatch, capsys):
    monkeypatch.setattr(cp, "ensure_server", lambda: {"port": 1, "token": "T"})
    opened = []
    monkeypatch.setattr(cp, "open_url", lambda url: opened.append(url) or True)

    cp.main(["--help"])
    assert "claude-plan [DIR]" in capsys.readouterr().out
    cp.main(["--url", str(req)])
    assert capsys.readouterr().out.startswith("http://127.0.0.1:1/?dir=") and opened == []
    cp.main([str(req)])
    assert len(opened) == 1
    monkeypatch.chdir(req)
    cp.main([])
    assert len(opened) == 2
    monkeypatch.setattr(cp, "open_url", lambda url: False)
    cp.main([str(req)])
    assert "no browser opener" in capsys.readouterr().out
    with pytest.raises(SystemExit, match="work root"):
        cp.main(["/tmp"])

    ran = []
    monkeypatch.setattr(cp, "serve", lambda: ran.append("serve"))
    monkeypatch.setattr(cp, "stop", lambda: ran.append("stop"))
    cp.main(["--serve"])
    cp.main(["--stop"])
    assert ran == ["serve", "stop"]
