#!/usr/bin/env python3
"""stdio <-> Streamable HTTP proxy for the Fabric Core MCP server.

Claude Code cannot use the endpoint's OAuth directly: Microsoft Entra ID does not
support dynamic client registration. This proxy instead borrows the Azure CLI's
signed-in identity, minting a Fabric-scoped token with `az account get-access-token`
and refreshing it as it ages.
"""

import json
import subprocess
import sys
import time
import urllib.error
import urllib.request

URL = "https://api.fabric.microsoft.com/v1/mcp/core"
SCOPE = "https://api.fabric.microsoft.com/.default"
TOKEN_TTL = 45 * 60  # refresh well before the ~60-90 min Entra lifetime

_token = None
_token_at = 0.0
_session_id = None
_protocol_version = None


def log(msg):
    print(f"[fabric-core-proxy] {msg}", file=sys.stderr, flush=True)


def get_token():
    global _token, _token_at
    if _token and time.time() - _token_at < TOKEN_TTL:
        return _token
    proc = subprocess.run(
        ["az", "account", "get-access-token", "--scope", SCOPE,
         "--query", "accessToken", "-o", "tsv"],
        capture_output=True, text=True,
    )
    if proc.returncode != 0 or not proc.stdout.strip():
        raise RuntimeError(
            "could not get a Fabric token from the Azure CLI (run `az login`): "
            + (proc.stderr or "").strip()[:500]
        )
    _token = proc.stdout.strip()
    _token_at = time.time()
    return _token


def post(message):
    global _session_id
    headers = {
        "Authorization": f"Bearer {get_token()}",
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if _session_id:
        headers["Mcp-Session-Id"] = _session_id
    if _protocol_version:
        headers["MCP-Protocol-Version"] = _protocol_version
    req = urllib.request.Request(
        URL, data=json.dumps(message).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        sid = resp.headers.get("Mcp-Session-Id")
        if sid:
            _session_id = sid
        return resp.status, resp.headers.get("Content-Type", ""), resp.read()


def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()


def emit_body(content_type, body):
    """Forward a JSON body, or each data: event of an SSE response."""
    if not body:
        return
    if "text/event-stream" in content_type:
        for line in body.decode("utf-8", "replace").splitlines():
            if line.startswith("data:"):
                payload = line[5:].strip()
                if payload:
                    sys.stdout.write(payload + "\n")
        sys.stdout.flush()
        return
    sys.stdout.write(body.decode("utf-8", "replace").strip() + "\n")
    sys.stdout.flush()


def main():
    global _protocol_version
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            message = json.loads(line)
        except json.JSONDecodeError:
            log(f"skipping unparseable line: {line[:200]}")
            continue

        if message.get("method") == "initialize":
            _protocol_version = message.get("params", {}).get("protocolVersion")

        try:
            status, content_type, body = post(message)
            if status != 202:
                emit_body(content_type, body)
        except Exception as exc:  # noqa: BLE001 - surface everything to the client
            detail = str(exc)
            if isinstance(exc, urllib.error.HTTPError):
                detail = f"HTTP {exc.code}: {exc.read().decode('utf-8', 'replace')[:500]}"
            log(detail)
            msg_id = message.get("id")
            if msg_id is not None:
                emit({"jsonrpc": "2.0", "id": msg_id,
                      "error": {"code": -32000, "message": f"fabric-core proxy: {detail}"}})


if __name__ == "__main__":
    main()
