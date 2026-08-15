"""Shared helpers for the Process Manager compatibility suite.

Mints real HS256 JWTs with the same claim shape as apps/gateway/src/auth.rs
(audit §8: missing / invalid / valid token, no external service). Also
provides a minimal MCP-over-stdio client for lifecycle tests.
"""
import base64
import hashlib
import hmac
import json
import os
import select
import subprocess
import sys
import time
from pathlib import Path

CONNECTOR_ROOT = Path(__file__).resolve().parent.parent.parent
RUN_SERVER = CONNECTOR_ROOT / "run_server.py"
SECRET = "0123456789abcdef0123456789abcdef"

CONNECTOR_ID = "sap2000-mcp"

# The shared AiConnect SDK is NOT vendored in this repo (IP boundary). Point
# AICONNECT_SDK_PATH at the installed SDK; dev default = aiconnector monorepo.
DEFAULT_SDK = "/project/aiconnector/connectors/sdk/python"


def mint(entitlements=None, subject=None, ttl=600, secret=SECRET):
    """Mint a token exactly like gateway auth.rs::mint (HS256)."""
    def b64(b):
        return base64.urlsafe_b64encode(b).rstrip(b"=")

    now = int(time.time())
    header = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode())
    payload = b64(json.dumps({
        "sub": subject or f"connector:{CONNECTOR_ID}",
        "iat": now,
        "exp": now + ttl,
        "entitlements": entitlements or [CONNECTOR_ID],
    }).encode())
    sig = b64(hmac.new(secret.encode(), header + b"." + payload, hashlib.sha256).digest())
    return f"{header.decode()}.{payload.decode()}.{sig.decode()}"


def spawn_server(env_extra=None, interpreter=None):
    """Spawn run_server.py the way the Process Manager does.

    The gateway spawn inherits the parent environment (tokio Command
    default), so this harness inherits os.environ and overrides what the
    test needs. The connector must not depend on IDE/developer extras —
    the clean-environment case is covered explicitly in test_env.py.
    """
    env = dict(os.environ)
    env["PYTHONPATH"] = str(CONNECTOR_ROOT)
    env.setdefault("AICONNECT_SDK_PATH", DEFAULT_SDK)
    env["AICONNECT_FAKE_BRIDGE"] = "1"
    if env_extra:
        env.update(env_extra)
    return subprocess.Popen(
        [interpreter or sys.executable, str(RUN_SERVER)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=env,
    )


def _wait_ready(proc, marker=b"starting up", timeout=25.0):
    """Wait until the server logs its readiness marker on stderr, or exits.

    QGIS's server.py boots slowly (3300-line module + client imports); an
    initialize written before the stdio loop is ready can be lost. Waiting
    on the stderr marker makes spawn deterministic. Fail-closed tests
    (missing/invalid token) exit before the marker — returns False fast.
    """
    import select
    import time

    deadline = time.time() + timeout
    buf = b""
    while time.time() < deadline:
        if proc.poll() is not None:
            return False
        ready, _, _ = select.select([proc.stderr], [], [], 0.2)
        if ready:
            chunk = proc.stderr.read(4096)
            if not chunk:
                break
            buf += chunk
            if marker in buf:
                return True
    return marker in buf


def spawn_server_wait(env_extra=None, interpreter=None):
    """spawn_server + readiness wait (used by the spawn-based suites)."""
    proc = spawn_server(env_extra=env_extra, interpreter=interpreter)
    _wait_ready(proc)
    return proc


def recv_json(proc, timeout=15.0):
    """Read one newline-delimited JSON-RPC message from the child stdout."""
    assert proc.stdout is not None
    line = proc.stdout.readline()
    if not line:
        return None
    return json.loads(line.decode())


def _drain_stdout(proc):
    """Read all currently-available stdout (non-blocking), discarding it."""
    if proc.stdout is None:
        return
    while True:
        ready, _, _ = select.select([proc.stdout], [], [], 0)
        if not ready:
            break
        chunk = proc.stdout.read(4096)
        if not chunk:
            break


def mcp_initialize(proc, attempts=15, wait=1.0):
    """Perform MCP initialize + notifications/initialized, return result.

    Retry-with-drain: the server's stdio loop attaches a moment after spawn;
    an initialize written too early can be lost. Each attempt drains stale
    stdout (duplicate initialize responses from earlier writes), rewrites
    the request, and waits up to `wait` seconds for a response.
    """
    assert proc.stdin is not None
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "pm-compat-test", "version": "0"},
        },
    }
    for _ in range(attempts):
        _drain_stdout(proc)
        proc.stdin.write((json.dumps(req) + "\n").encode())
        proc.stdin.flush()
        ready, _, _ = select.select([proc.stdout], [], [], wait)
        if ready:
            line = proc.stdout.readline()
            if line:
                resp = json.loads(line.decode())
                if resp.get("id") == 1:
                    proc.stdin.write((json.dumps({
                        "jsonrpc": "2.0",
                        "method": "notifications/initialized",
                    }) + "\n").encode())
                    proc.stdin.flush()
                    return resp
    raise AssertionError("no initialize response")


def mcp_tools_list(proc):
    """List tools after initialize; returns the result payload."""
    assert proc.stdin is not None
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    proc.stdin.write((json.dumps(req) + "\n").encode())
    proc.stdin.flush()
    resp = recv_json(proc)
    assert resp and resp.get("id") == 2, f"no tools/list response: {resp}"
    return resp.get("result", {})


def stop(proc):
    """Close stdin (EOF → FastMCP stdio exits cleanly), wait, return code."""
    try:
        if proc.stdin:
            proc.stdin.close()
    except BrokenPipeError:
        pass
    try:
        return proc.wait(timeout=10)
    except subprocess.TimeoutExpired:
        proc.kill()
        return proc.wait()
