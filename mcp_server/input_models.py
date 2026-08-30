"""Typed input models for SAP2000 MCP tools.

Mirrors ltspice-mcp Layer 1: every tool takes a Pydantic model, and the
schema sent to MCP clients is generated from these types (Literal enums,
Field descriptions) rather than hand-written JSON Schema.
"""

from typing import Any, Literal

from pydantic import Field


# ── Shared enum-like constraints ─────────────────────────────────────────
AppName = Literal["SAP2000"]


class ConnectInput(dict):
    """Marker base kept minimal — connect params are two simple fields."""

    program_path: str | None = Field(
        default=None,
        description="Full path to SAP2000.exe. Ignored when attach_to_existing=True. "
        "When None and attach_to_existing=False, the latest installed version is launched via ProgID.",
    )
    attach_to_existing: bool = Field(
        default=True,
        description="True = attach to an already-running SAP2000 instance; "
        "False = launch a new one (needs program_path or an installed version).",
    )


class DisconnectInput(dict):
    save_model: bool = Field(
        default=False,
        description="True = save the model before exiting SAP2000; False = discard unsaved changes.",
    )


class GetModelInfoInput(dict):
    pass


class ExecuteFunctionInput(dict):
    function_path: str = Field(
        description='Dot-path relative to SapModel or SapObject, e.g. "SapModel.FrameObj.AddByCoord" '
        'or "SapObject.ApplicationExit". Must start with "SapModel." or "SapObject." (else SapModel assumed).',
    )
    args: list[Any] | None = Field(
        default=None,
        description="Positional arguments in the API's declared order. ByRef outputs come back as output_params.",
    )
    description: str = Field(
        default="",
        description="Human-readable note about what this call does (recorded in responses and logs).",
    )


class RunScriptInput(dict):
    script: str = Field(
        description="Python source executed in the sandbox. Pre-injected: SapModel, SapObject, result (dict to fill), "
        "sap_temp_dir. Allowed imports: math, json, datetime, decimal, fractions, collections, itertools, functools, typing.",
    )
    description: str = Field(default="", description="What this script does (shown in results/logs).")
    save_as: str | None = Field(
        default=None,
        description="If set, saves the script to the library under this name on success.",
    )


class ListScriptsInput(dict):
    query: str | None = Field(default=None, description="Case-insensitive search over names + descriptions.")
    tag: str | None = Field(default=None, description='Filter by tag, e.g. "loads", "analysis", "results".')


class LoadScriptInput(dict):
    name: str = Field(description="Script name without .py extension, as listed by list_scripts.")


class SearchApiDocsInput(dict):
    query: str = Field(
        description='Keywords describing what you need, e.g. "add frame by coordinates", "run analysis".',
    )
    category: str | None = Field(
        default=None,
        description="Restrict to one category from list_api_categories (e.g. File, Object_Model, Analyze).",
    )


class ListApiCategoriesInput(dict):
    pass


class QueryFunctionRegistryInput(dict):
    function_path: str | None = Field(
        default=None,
        description="Exact dot-path for full detail of one function (e.g. SapModel.FrameObj.AddByCoord).",
    )
    category: str | None = Field(default=None, description="Filter by API category.")
    verified_only: bool = Field(default=False, description="Only return functions marked verified.")
    query: str | None = Field(default=None, description="Keyword search across path/description/signature.")


class ListRegistryCategoriesInput(dict):
    pass


class RegisterVerifiedFunctionInput(dict):
    function_path: str = Field(description='Dot-path like "SapModel.FrameObj.AddByCoord".')
    category: str = Field(description='API category, e.g. "Object_Model", "Properties", "Analyze".')
    description: str = Field(default="", description="What the function does.")
    signature: str = Field(
        default="",
        description='API signature string like "(Name, MatType) -> ret_code". Parsed for parameter docs.',
    )
    wrapper_script: str = Field(default="", description="Wrapper script name (without .py) in scripts/wrappers/.")
    parameter_notes: str = Field(default="", description="Brief parameter documentation.")
    notes: str = Field(default="", description="Extra notes (e.g. ByRef output layout).")


class ListRegistryCategoriesDetailedInput(dict):
    pass


class GetErrorHintsInput(dict):
    error_code: str | None = Field(
        default=None,
        description='Code from a failed call envelope, e.g. "NOT_CONNECTED", "SCRIPT_TIMEOUT", "PATH_NOT_FOUND". '
        "Omit to list all error types.",
    )
