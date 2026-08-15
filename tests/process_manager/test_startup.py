"""Startup + MCP initialization + tool dispatch tests.

Proves the PM lifecycle contract WITHOUT SAP2000: the connector spawns,
initializes MCP over stdio, exposes the expected tools, and dispatches a
tool call through the low-level envelope interceptor (adapter mode) with
the COM-free fake bridge (AICONNECT_FAKE_BRIDGE=1).
"""
import json

from fake_license import SECRET, mcp_initialize, mcp_tools_list, mint, spawn_server, stop

EXPECTED_TOOLS = {
    "connect_sap2000",
    "disconnect_sap2000",
    "get_model_info",
    "execute_sap_function",
    "run_sap_script",
    "list_scripts",
    "load_script",
    "search_api_docs",
    "list_api_categories",
    "query_function_registry",
    "list_registry_categories",
    "register_verified_function",
}


def test_starts_without_sap2000_and_initializes():
    proc = spawn_server()
    try:
        init = mcp_initialize(proc)
        assert init.get("result", {}).get("serverInfo", {}).get("name") == "sap2000"
    finally:
        stop(proc)


def test_exposes_expected_tools():
    proc = spawn_server()
    try:
        mcp_initialize(proc)
        result = mcp_tools_list(proc)
        names = {t["name"] for t in result.get("tools", [])}
        assert names == EXPECTED_TOOLS, f"missing: {EXPECTED_TOOLS - names}"
    finally:
        stop(proc)


def test_tool_dispatch_enveloped():
    """Adapter-mode tool call must return an envelope through the low-level
    interceptor — regression for the FastMCP 3.4.7 wrapped-call failure.
    connect_sap2000 via the fake bridge returns fake-sap2000 → ok envelope."""
    proc = spawn_server(env_extra={
        "AICONNECT_ENABLE": "1",
        "JWT_SECRET": SECRET,
        "MCP_LICENSE_TOKEN": mint(),
    })
    try:
        mcp_initialize(proc)
        assert proc.stdin is not None
        req = {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "connect_sap2000", "arguments": {}},
        }
        proc.stdin.write((json.dumps(req) + "\n").encode())
        proc.stdin.flush()
        resp = json.loads(proc.stdout.readline().decode())
        content = resp["result"]["content"][0]["text"]
        assert '"success":' in content, f"expected envelope, got: {content[:200]}"
    finally:
        stop(proc)


def test_exits_cleanly_on_stdin_close():
    proc = spawn_server()
    mcp_initialize(proc)
    code = stop(proc)
    assert code == 0, f"expected clean exit, got {code}"
