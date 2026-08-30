#!/usr/bin/env python3
"""SAP2000 MCP server entrypoint (AiConnect-managed).

Same as `python -m mcp_server.server`, but runnable by the gateway bridge
(`--cmd`) without module-path tricks.
"""
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(_ROOT))

# Vendored dependencies (`stage-python-vendor.py`), shipped inside the package.
#
# The connector used to ship source-only: the package contained this file and
# `mcp_server/` and nothing else, so `import mcp` below failed on any machine that did
# not happen to have the MCP SDK installed system-wide. AI CONNECT bundles the
# INTERPRETER; the connector brings its own LIBRARIES, and this is where they are.
#
# Appended, not inserted: anything the interpreter already resolves — notably the
# host-injected `mcp_license_sdk` — keeps priority, and a developer running from a
# populated virtualenv still gets that environment. `_vendor/` is the floor, not an
# override. Missing directory is not an error: a dev checkout has none.
_VENDOR = _ROOT / "_vendor"
if _VENDOR.is_dir():
    sys.path.append(str(_VENDOR))

from mcp_server.server import mcp  # noqa: E402

if __name__ == "__main__":
    try:
        from mcp_server.aioconnect import ensure_licensed, install_call_interceptor, wrap_tools

        ensure_licensed()
        # FastMCP 3.x: intercept at the low-level call boundary (tools stay
        # untouched — envelope applied post-validation). Fallback: legacy
        # per-tool wrap for fastmcp <3.x.
        if not install_call_interceptor(mcp):
            wrapped = wrap_tools(mcp)
            if wrapped:
                import logging

                logging.getLogger("sap2000").info("aioconnect: wrapped %d tools", wrapped)
    except ImportError:
        pass  # adapter absent → plain upstream server
    mcp.run(transport="stdio")
