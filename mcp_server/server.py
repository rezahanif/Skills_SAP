"""
SAP2000 MCP Server — Entry point.

Exposes tools to the MCP client so it can connect to SAP2000, inspect the model,
and (in later steps) execute functions and scripts.

Transport: stdio (launched by the MCP client).
"""

import logging
import sys
from pathlib import Path

try:
    from mcp.server.fastmcp import FastMCP
    from mcp.server.fastmcp.tools.base import ToolAnnotations
except ImportError:
    try:
        from mcp.server.fastmcp import FastMCP, ToolAnnotations
    except ImportError:
        from mcp_server.fastmcp_mini import FastMCP
        from typing import Any as ToolAnnotations  # stub: no annotations support

# Add mcp_server directory to path so imports work from any cwd
_mcp_server_dir = Path(__file__).parent
if str(_mcp_server_dir) not in sys.path:
    sys.path.insert(0, str(_mcp_server_dir))

from sap_bridge import bridge
from sap_executor import execute_function, run_script
from script_library import list_scripts as _list_scripts, load_script as _load_script
from doc_search import doc_index
from function_registry import registry
from errors import ERROR_HINTS
from prompts import register as register_prompts

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)

# ── Server instructions (agent-facing workflow guidance) ────────────────
# ~200 words: every token is re-read each LLM turn. Cross-cutting workflow
# guidance only — per-tool detail stays in tool descriptions.

SERVER_INSTRUCTIONS = """\
SAP2000-MCP drives SAP2000 structural analysis via local COM (Windows only).

Workflow order: connect_sap2000 first (attach_to_existing=True is the normal \
path), verify with get_model_info, then work, then disconnect_sap2000 when done.

Match the operation to the tool:
- Known API call → execute_sap_function with a dot-path ("SapModel.FrameObj.AddByCoord").
  ByRef outputs come back in output_params; return_value 0 = success.
- Multi-step or computed logic → run_sap_script. The sandbox pre-injects SapModel,
  SapObject, and a `result` dict — write outputs there. No file I/O; allowed imports:
  math, json, datetime, decimal, fractions, collections, itertools, functools, typing.
  Timeout 120 s — split long work into smaller scripts.

Before writing ANY unfamiliar call: search_api_docs for the function name/signature,
then query_function_registry to see if a verified pattern exists. After a successful
novel call, register_verified_function records it for future agents.

On any failure: read error_code + suggested_actions from the envelope, or call
get_error_hints with that code. NOT_CONNECTED → connect first; PATH_NOT_FOUND →
re-search docs; SCRIPT_TIMEOUT → split the script.

Units come back in whatever the model's present units are (get_model_info reports them) \
— do not assume kN/m/in; convert explicitly when mixing sources.\
"""

mcp = FastMCP(
    "sap2000",
    instructions=SERVER_INSTRUCTIONS,
)


# ── Tools ────────────────────────────────────────────────────────────────

from typing import Literal  # noqa: E402

from pydantic import Field  # noqa: E402

AppTarget = Literal["SAP2000"]


@mcp.tool(
    title="Connect SAP2000",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
def connect_sap2000(
    program_path: str | None = Field(
        default=None,
        description="Full path to SAP2000.exe. Ignored when attach_to_existing=True. "
        "When None and attach_to_existing=False, latest installed version is launched via ProgID.",
    ),
    attach_to_existing: bool = Field(
        default=True,
        description="True = attach to an already-running SAP2000 instance (normal path); "
        "False = launch a new one.",
    ),
) -> dict:
    """Connect to a local SAP2000 instance.

    By default attaches to an already-running SAP2000. Set
    attach_to_existing=False to launch a new instance instead.

    Returns: connected, version, model_path, units, num_frames,
    num_points, num_areas.
    """
    return bridge.connect(
        program_path=program_path,
        attach_to_existing=attach_to_existing,
    )


@mcp.tool(
    title="Disconnect SAP2000",
    annotations=ToolAnnotations(destructiveHint=True),
)
def disconnect_sap2000(
    save_model: bool = Field(default=False, description="True = save the model before exit; False = discard unsaved changes."),
) -> dict:
    """Disconnect from SAP2000 and optionally save the current model.

    Always call this when done to release COM resources.
    """
    return bridge.disconnect(save_model=save_model)


@mcp.tool(
    title="Get Model Info",
    annotations=ToolAnnotations(readOnlyHint=True),
)
def get_model_info() -> dict:
    """Get current SAP2000 connection status and model summary.

    Returns: connected, version, model_path, units, num_frames,
    num_points, num_areas. Use this to verify state before or after
    running scripts — especially after a SCRIPT_TIMEOUT, where an
    orphaned thread may have mutated the model.
    """
    return bridge.get_model_info()


@mcp.tool(
    title="Execute SAP Function",
    annotations=ToolAnnotations(readOnlyHint=False),
)
def execute_sap_function(
    function_path: str = Field(
        description='Dot-path relative to SapModel or SapObject, e.g. "SapModel.FrameObj.AddByCoord" '
        'or "SapObject.ApplicationExit". Prefix with SapModel. or SapObject. (else SapModel assumed).',
    ),
    args: list | None = Field(
        default=None,
        description="Positional arguments in the API's declared order. ByRef outputs come back as output_params "
        "(ret_code is ALWAYS last in the returned tuple).",
    ),
    description: str = Field(default="", description="Human-readable note about what this call does."),
) -> dict:
    """Execute any SAP2000 API function by its dot-path.

    Returns: {success, return_value, output_params (if any), description}.

    SAP2000 convention: return_value 0 = success, nonzero raises
    API_RETURN_CODE with details. Use search_api_docs first to find the
    correct name/signature for unfamiliar functions.
    """
    return execute_function(
        function_path=function_path,
        args=args or [],
        description=description,
    )


@mcp.tool(
    title="Run SAP Script",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
)
def run_sap_script(
    script: str = Field(
        description="Python source executed in the sandbox. Pre-injected: SapModel, SapObject, result (dict to fill), "
        "sap_temp_dir. Write outputs into `result`. Allowed imports: math, json, datetime, decimal, fractions, "
        "collections, itertools, functools, typing. No file I/O.",
    ),
    description: str = Field(default="", description="What this script does (shown in results/logs)."),
    save_as: str | None = Field(
        default=None,
        description="If set and the script succeeds, saves it to scripts/{save_as}.py for reuse via list_scripts/load_script.",
    ),
) -> dict:
    """Execute a Python script against the connected SAP2000 instance.

    Sandbox: only safe modules allowed; no file I/O; no os/subprocess/sys;
    120-second timeout (SCRIPT_TIMEOUT on breach — the worker thread cannot
    be killed, so verify model state with get_model_info afterwards).

    Returns: {success, stdout, stderr, result, execution_time_s, saved_path}.

    Workflow: search_api_docs → generate script → run → read `result` →
    register_verified_function for any novel call that worked.
    """
    return run_script(script=script, description=description, save_as=save_as)


@mcp.tool(
    title="List Scripts",
    annotations=ToolAnnotations(readOnlyHint=True),
)
def list_scripts(
    query: str | None = Field(default=None, description="Case-insensitive search over names and descriptions."),
    tag: str | None = Field(default=None, description='Filter by tag, e.g. "loads", "analysis", "results".'),
) -> list[dict]:
    """List saved SAP2000 scripts in the library.

    Returns: [{name, description, created, status, tags, path}].
    Use this to find existing scripts before generating a new one.
    """
    return _list_scripts(query=query, tag=tag)


@mcp.tool(
    title="Load Script",
    annotations=ToolAnnotations(readOnlyHint=True),
)
def load_script(
    name: str = Field(description="Script name without .py extension, as listed by list_scripts."),
) -> dict:
    """Load a saved script by name from the library.

    Returns: {name, description, script_code, metadata}.
    Retrieve, modify, re-execute via run_sap_script.
    """
    return _load_script(name=name)


@mcp.tool(
    title="Search API Docs",
    annotations=ToolAnnotations(readOnlyHint=True),
)
def search_api_docs(
    query: str = Field(
        description='Keywords describing what you need, e.g. "add frame by coordinates", '
        '"run analysis", "get joint displacement results".',
    ),
    category: str | None = Field(
        default=None,
        description='Restrict to one category from list_api_categories, e.g. "File", "Object_Model", "Analyze".',
    ),
) -> list[dict]:
    """Search SAP2000 API documentation for functions matching a query.

    Returns: [{file, category, function_name, syntax, signature,
    parameters, remarks, example_snippet}].

    ALWAYS use this before writing scripts or calling execute_sap_function
    with an unfamiliar function — it returns exact names, parameter order,
    and conventions.
    """
    return doc_index.search(query=query, category=category)


@mcp.tool(
    title="List API Categories",
    annotations=ToolAnnotations(readOnlyHint=True),
)
def list_api_categories() -> list[dict]:
    """List all available SAP2000 API documentation categories.

    Returns: [{category, sections}] — section counts per category.
    Use to explore the API surface before searching.
    """
    return doc_index.list_categories()


@mcp.tool(
    title="Query Function Registry",
    annotations=ToolAnnotations(readOnlyHint=True),
)
def query_function_registry(
    function_path: str | None = Field(
        default=None,
        description="Exact dot-path for full detail of ONE function (e.g. SapModel.FrameObj.AddByCoord).",
    ),
    category: str | None = Field(default=None, description="Filter by API category."),
    verified_only: bool = Field(default=False, description="Return only functions marked verified."),
    query: str | None = Field(default=None, description="Keyword search across path/description/signature."),
) -> dict:
    """Query the registry of verified SAP2000 API functions.

    Use BEFORE generating a script: verified entries carry working call
    patterns and pitfalls discovered by earlier runs.

    Modes: no args = registry summary; function_path = one full detail;
    category/query/verified_only = filtered list.
    """
    if function_path:
        return registry.get_function(function_path)

    if category or query or verified_only:
        functions = registry.list_functions(
            category=category,
            verified_only=verified_only,
            query=query,
        )
        return {"count": len(functions), "functions": functions}

    return registry.get_summary()


@mcp.tool(
    title="Register Verified Function",
    annotations=ToolAnnotations(readOnlyHint=False),
)
def register_verified_function(
    function_path: str = Field(description='Dot-path like "SapModel.FrameObj.AddByCoord".'),
    category: str = Field(description='API category, e.g. "Object_Model", "Properties", "Analyze".'),
    description: str = Field(default="", description="What the function does."),
    signature: str = Field(
        default="",
        description='Signature string like "(Name, MatType) -> ret_code". Required for parameter parsing.',
    ),
    wrapper_script: str = Field(default="", description="Wrapper script name (without .py) in scripts/wrappers/."),
    parameter_notes: str = Field(default="", description="Brief parameter documentation."),
    notes: str = Field(default="", description="Extra notes (e.g. ByRef output layout)."),
) -> dict:
    """Register or update a verified SAP2000 API function in the registry.

    Call this after successfully running a script that uses a new API
    function. If wrapper_script is provided, it links the function to its
    wrapper in scripts/wrappers/.

    Returns: {registered, function_path, is_new}.
    """
    result = registry.register_function(
        function_path=function_path,
        category=category,
        description=description,
        signature=signature,
        wrapper_script=wrapper_script,
        parameter_notes=parameter_notes,
        notes=notes,
    )
    # Also mark as verified since this tool is for verified functions
    registry.mark_verified(function_path)
    return result


@mcp.tool(
    title="List Registry Categories",
    annotations=ToolAnnotations(readOnlyHint=True),
)
def list_registry_categories() -> list[dict]:
    """List API categories with counts of registered vs verified functions.

    Use this to see coverage of the function registry — which categories
    have been explored and which still need work.

    Returns: [{category, registered, verified}].
    """
    summary = registry.get_summary()
    categories = summary.get("categories", {})

    return [
        {
            "category": cat,
            "registered": counts["registered"],
            "verified": counts["verified"],
        }
        for cat, counts in sorted(categories.items())
    ]


@mcp.tool(
    title="Get Error Hints",
    annotations=ToolAnnotations(readOnlyHint=True),
)
def get_error_hints(
    error_code: str | None = Field(
        default=None,
        description='Code from a failed call envelope, e.g. "NOT_CONNECTED", "SCRIPT_TIMEOUT", '
        '"PATH_NOT_FOUND", "API_RETURN_CODE". Omit to list all error types.',
    ),
) -> dict:
    """Get recovery hints for a SAP2000 error code, or all error types.

    Returns: dict with hint and recovery actions. Use this after any failed
    tool call to decide the next step.
    """
    if error_code:
        key = error_code.lower()
        hint = ERROR_HINTS.get(key)
        if hint:
            return {"error_code": key, **hint}
        return {"error_code": error_code, "hint": "No hints available for this error code"}
    return {"error_types": list(ERROR_HINTS.keys()), "hints": ERROR_HINTS}


# ── Prompts (workflow starters) ──────────────────────────────────────────
register_prompts(mcp)


# ── Run ──────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    try:
        from aioconnect import ensure_licensed, wrap_tools

        ensure_licensed()
        wrapped = wrap_tools(mcp)
        if wrapped:
            logger.info("aioconnect: wrapped %d tools", wrapped)
    except ImportError:
        pass  # adapter absent → run as plain upstream server
    mcp.run(transport="stdio")
