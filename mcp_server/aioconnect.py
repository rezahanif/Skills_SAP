"""AiConnect adapter for the SAP2000 MCP fork (integration layer — the 12
upstream tools are NOT modified).

Reuses the shared Python SDK (connectors/sdk/python):
  1. License gate — startup + per-call check of the token the Process Manager
     injects via MCP_LICENSE_TOKEN (manifest token_env_var).
  2. Response envelope — every registered tool's return is wrapped centrally
     at registration time (ok/fail), so none of the 12 tools need per-tool edits.

Env-gated integration points:
  AICONNECT_ENABLE=1        — install the license gate + envelope wrap
  MCP_LICENSE_TOKEN         — the token to validate
  JWT_SECRET                — token signing secret (default matches gateway dev)

Privilege classification (adaptation plan §7) — the connector exposes:
  READ:        get_model_info, list_scripts, load_script, search_api_docs,
               list_api_categories, query_function_registry, list_registry_categories
  WRITE:       connect_sap2000 (launch/attach), disconnect_sap2000 (save+exit)
  EXECUTION:   execute_sap_function (arbitrary COM API call), run_sap_script
               (arbitrary Python — sandboxed but NOT a security boundary; the
               sandbox restricts imports/open and enforces a 120 s timeout, but
               the worker thread cannot be killed and builtin escapes exist)
  DEVELOPMENT: register_verified_function (mutates scripts/registry.json)

AiConnect adds its own outer boundary (license + envelope) WITHOUT replacing
the source sandbox. run_sap_script / execute_sap_function remain full
EXECUTION privilege from the AiConnect perspective.
"""
import asyncio
import json
import os
import sys
from pathlib import Path

_SDK = Path(__file__).resolve().parents[3] / "sdk" / "python"
# SDK resolution: AICONNECT_SDK_PATH env wins (installed AiConnect SDK,
# keeps the public fork IP-free); else monorepo-relative fallback.
_env_sdk = os.environ.get("AICONNECT_SDK_PATH", "")
_SDK = Path(_env_sdk).resolve() if _env_sdk else Path(__file__).resolve().parents[3] / "sdk" / "python"
if str(_SDK) not in sys.path:
    sys.path.insert(0, str(_SDK))

from mcp_license_sdk import LicenseError, LicenseValidator, fail, ok  # noqa: E402
from mcp_license_sdk import interception  # noqa: E402

CONNECTOR_ID = "sap2000-mcp"


def _enabled() -> bool:
    return os.environ.get("AICONNECT_ENABLE", "") == "1"


def _validate() -> dict:
    """Validate the PM-injected token AND its connector binding.

    The Process Manager mints tokens with subject `connector:<id>` and
    entitlements `[<id>]` (auth.rs::mint). Signature + expiry are checked
    by the SDK; binding is asserted here so a token minted for another
    connector can never authorize this one.
    """
    claims = LicenseValidator(os.environ.get("JWT_SECRET", "dev-secret-change-me")).ensure_licensed()
    if claims.get("sub") != f"connector:{CONNECTOR_ID}":
        raise LicenseError(f"token not bound to {CONNECTOR_ID}")
    scopes = claims.get("entitlements") or claims.get("scopes") or []
    if CONNECTOR_ID not in scopes:
        raise LicenseError(f"token lacks scope {CONNECTOR_ID}")
    return claims


def ensure_licensed() -> None:
    if not _enabled():
        return
    _validate()


def install_call_interceptor(mcp) -> bool:
    """Envelope tools/call via the shared SDK helper (mcp_license_sdk.
    interception) — low-level call_tool re-registration on the mcp-SDK
    FastMCP class; tools stay untouched (fixes the FastMCP 3.4.7
    wrapped-call failure). Returns True when installed; False → caller
    falls back to the legacy per-tool wrap (fastmcp <3.x)."""
    if not _enabled():
        return False
    installed = interception.install_call_interceptor(mcp, _validate, _wrap_result)
    if not installed:
        print("aioconnect: call interceptor not installed — falling back to wrap_tools", file=sys.stderr)
    return installed


def _wrap_result(r):
    if isinstance(r, str):
        text = r.strip()
        if text:
            try:
                return json.dumps(ok(json.loads(text)))
            except json.JSONDecodeError:
                return json.dumps(fail("TOOL_ERROR", "non-JSON tool output"))
        return json.dumps(ok({"result": ""}))
    return json.dumps(ok(r))


async def _call(fn, args, kwargs):
    if asyncio.iscoroutinefunction(fn):
        return await fn(*args, **kwargs)
    return fn(*args, **kwargs)


def _make_sync_wrapper(fn):
    """For SYNC-registered tools: FastMCP freezes is_async at registration, so
    replacing tool.fn with an async wrapper makes FastMCP call it synchronously
    and leak a coroutine. Sync tools get a sync wrapper instead."""
    def _w(*args, **kwargs):
        if not _enabled():
            return fn(*args, **kwargs)
        validator = LicenseValidator(os.environ.get("JWT_SECRET", "dev-secret-change-me"))
        try:
            validator.ensure_licensed()  # per-call recheck
            return _wrap_result(fn(*args, **kwargs))
        except LicenseError as e:
            return json.dumps(fail("LICENSE", str(e)))
        except Exception as e:
            return json.dumps(fail("TOOL_ERROR", str(e)))
    return _w


def _wrap(fn):
    if not asyncio.iscoroutinefunction(fn):
        return _make_sync_wrapper(fn)

    async def _w(*args, **kwargs):
        if not _enabled():
            return await _call(fn, args, kwargs)
        validator = LicenseValidator(os.environ.get("JWT_SECRET", "dev-secret-change-me"))
        try:
            validator.ensure_licensed()  # per-call recheck
            result = await _call(fn, args, kwargs)
            return _wrap_result(result)
        except LicenseError as e:
            return json.dumps(fail("LICENSE", str(e)))
        except Exception as e:
            return json.dumps(fail("TOOL_ERROR", str(e)))
    return _w


def wrap_tools(mcp) -> int:
    """Centrally wrap every registered tool. FastMCP 1.x exposes
    mcp._tool_manager._tools; tolerate a bare registry dict too. Degrades to
    license-only if the internals change."""
    if not _enabled():
        return 0
    registry = None
    for candidate in (getattr(mcp, "_tool_manager", None), getattr(mcp, "_tools", None)):
        if candidate is None:
            continue
        reg = getattr(candidate, "_tools", None) or getattr(candidate, "tools", None)
        if isinstance(reg, dict):
            registry = reg
            break
        if isinstance(candidate, dict) and candidate:
            registry = candidate
            break
    if registry is None:
        print("aioconnect: tool manager not found — envelope wrap skipped", file=sys.stderr)
        return 0
    wrapped = 0
    for name, tool in list(registry.items()):
        fn = getattr(tool, "fn", None) or tool
        if fn is None or getattr(fn, "_aioconnect_wrapped", False):
            continue
        wrapped_fn = _wrap(fn)
        wrapped_fn._aioconnect_wrapped = True
        if hasattr(tool, "fn"):
            tool.fn = wrapped_fn
        else:
            registry[name] = wrapped_fn
        wrapped += 1
    return wrapped
