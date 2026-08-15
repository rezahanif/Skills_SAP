#!/usr/bin/env python3
"""SAP2000 MCP server entrypoint (AiConnect-managed).

Same as `python -m mcp_server.server`, but runnable by the gateway bridge
(`--cmd`) without module-path tricks.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

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
