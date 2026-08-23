"""Typed error hierarchy for the SAP2000 connector.

Mirrors officemcp/errors.py: every error carries a machine-readable
``error_code``, a one-line ``hint``, and a ``recovery`` list of concrete
next actions. The tool boundary (server.py) converts these into
structured fail envelopes; unexpected exceptions become generic errors.

Error codes are stable identifiers — agents match on them, never on
message text.
"""

from typing import Any


class SAPError(Exception):
    """Base class for typed SAP2000 errors."""

    error_code: str = "sap_error"
    hint: str = ""
    recovery: list[str] = []

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.details = details or {}

    def to_payload(self) -> dict:
        """Structured payload for the fail envelope."""
        return {
            "error_code": self.error_code,
            "message": self.message,
            "hint": self.hint,
            "recovery": self.recovery,
            "details": self.details,
        }


class NotConnectedError(SAPError):
    """Operation attempted before connect_sap2000."""

    error_code = "not_connected"
    hint = "The bridge holds no live SAP2000 COM reference."
    recovery = [
        "Call connect_sap2000(attach_to_existing=True) to attach to a running instance",
        "Or call connect_sap2000(attach_to_existing=False, program_path=...) to launch one",
        "Call get_model_info afterwards to verify the connection",
    ]


class ConnectionFailedError(SAPError):
    """connect_sap2000 could not attach or launch SAP2000."""

    error_code = "connection_failed"
    hint = "COM attach/launch failed — SAP2000 may not be installed or not registered."
    recovery = [
        "Verify SAP2000 is installed and the version registers 'CSI.SAP2000.API.SapObject'",
        "Try attach_to_existing=True if an instance is already running",
        "Provide program_path pointing at SAP2000.exe when launching fresh",
        "Confirm this is running on Windows (COM required)",
    ]


class PathResolveError(SAPError):
    """execute_sap_function could not resolve the dot-path on the COM object."""

    error_code = "path_not_found"
    hint = "The function path does not exist on SapModel/SapObject."
    recovery = [
        "Call search_api_docs to find the correct function name",
        "Call query_function_registry to check verified paths",
        "Check prefix: paths must start with SapModel. or SapObject.",
    ]


class APIReturnCodeError(SAPError):
    """SAP2000 API returned a nonzero return code."""

    error_code = "api_return_code"
    hint = "SAP2000 API convention: 0 = success, nonzero = failure."
    recovery = [
        "Check the function's documentation for the specific code meaning",
        "Verify argument types and ordering via search_api_docs",
        "Inspect output_params — ByRef outputs may carry partial results",
    ]


class ScriptSyntaxError(SAPError):
    """run_sap_script failed to parse the script."""

    error_code = "script_syntax"
    hint = "The script contains Python syntax errors."
    recovery = [
        "Fix the reported line number",
        "Remember: only allowlisted imports work in the sandbox (math, json, datetime...)",
        "No file I/O — write outputs into the pre-injected `result` dict",
    ]


class ScriptTimeoutError(SAPError):
    """run_sap_script exceeded the sandbox timeout."""

    error_code = "script_timeout"
    hint = "Scripts are killed at the timeout; the worker thread cannot be forcibly terminated."
    recovery = [
        "Break long work into smaller scripts run sequentially",
        "Reduce iteration counts or model size in the script",
        "WARNING: the orphaned thread may still mutate the model — verify state with get_model_info",
    ]


class ScriptExecutionError(SAPError):
    """Script raised an exception during execution."""

    error_code = "script_execution"
    hint = "The script raised an unhandled exception at runtime."
    recovery = [
        "Read stderr in the response for the traceback",
        "Check variable names — SapModel, SapObject, result are pre-injected",
        "Wrap risky API calls in try/except inside the script and record failures in `result`",
    ]


# Stable-code → human guidance map (mirrors officemcp ERROR_HINTS).
ERROR_HINTS: dict[str, dict[str, Any]] = {
    cls.error_code: {"hint": cls.hint, "recovery": cls.recovery}
    for cls in (
        NotConnectedError,
        ConnectionFailedError,
        PathResolveError,
        APIReturnCodeError,
        ScriptSyntaxError,
        ScriptTimeoutError,
        ScriptExecutionError,
    )
}
