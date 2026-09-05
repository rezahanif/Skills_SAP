"""MCP prompts: workflow starters for common SAP2000 tasks.

Mirrors ltspice-mcp's prompts.py — each prompt returns one user message
describing the canonical tool pipeline for a task. Human-facing discovery
surface; tool descriptions and SERVER_INSTRUCTIONS remain the agent's
primary orientation channel.
"""

from mcp.server.fastmcp.prompts.base import UserMessage


def _msg(text: str) -> list[UserMessage]:
    return [UserMessage(content=text)]


def register(mcp) -> None:
    """Register all prompts on the given FastMCP instance."""

    @mcp.prompt(
        name="build_model",
        description="Create a new SAP2000 model from a text description of the structure",
    )
    def build_model(description: str) -> list[UserMessage]:
        return _msg(
            f"Build a SAP2000 model for: {description}\n"
            "Workflow:\n"
            "1. connect_sap2000 (attach_to_existing=True) and get_model_info to confirm state & units\n"
            "2. If model is locked: call set_model_lock(locked=False) to allow geometry definition\n"
            "3. Generate structural members via run_sap_script or execute_sap_function\n"
            "4. Call save_model to persist the model file to disk\n"
            "5. Call run_analysis to execute the finite element solver\n"
            "6. Call get_analysis_results to verify equilibrium and displacements"
        )

    @mcp.prompt(
        name="run_analysis",
        description="Run a structural analysis on the current model and report results",
    )
    def run_analysis(analysis_type: str) -> list[UserMessage]:
        return _msg(
            f"Run a {analysis_type} analysis on the current model.\n"
            "Workflow:\n"
            "1. connect_sap2000 -> get_model_info (confirm connected + element counts)\n"
            "2. Call save_model to ensure model is saved\n"
            "3. Call run_analysis tool (executes solver and updates locked state)\n"
            "4. Call get_analysis_results(result_type='reactions', case_or_combo='DEAD') to verify\n"
            "5. Report key numbers with units from get_analysis_results output"
        )

    @mcp.prompt(
        name="extract_results",
        description="Pull specific results (displacements, reactions, forces) from a completed analysis",
    )
    def extract_results(what: str) -> list[UserMessage]:
        return _msg(
            f"Extract {what} from the current model.\n"
            "Workflow:\n"
            "1. connect_sap2000 -> get_model_info (verify is_locked=True)\n"
            "2. Call get_analysis_results with result_type ('reactions', 'displacements', 'modal', or 'frame_forces')\n"
            "3. Specify case_or_combo and object_id if querying specific joints or frames\n"
            "4. Read the structured, typed results dictionary with explicit units"
        )

    @mcp.prompt(
        name="debug_failed_call",
        description="Diagnose why a SAP2000 tool call failed and recover",
    )
    def debug_failed_call(error_code: str, detail: str) -> list[UserMessage]:
        return _msg(
            f"A call failed with code {error_code}: {detail}\n"
            "Recovery:\n"
            "1. get_error_hints with that error_code\n"
            "2. NOT_CONNECTED -> connect_sap2000 then retry\n"
            "3. PATH_NOT_FOUND -> search_api_docs for the correct path; check SapModel./SapObject. prefix\n"
            "4. API_RETURN_CODE -> read output_params/details; verify argument order against docs\n"
            "5. SCRIPT_TIMEOUT -> split the script; afterwards get_model_info to check model integrity"
        )

    @mcp.prompt(
        name="verify_and_register",
        description="Verify a novel API call works, then register it for future reuse",
    )
    def verify_and_register(function_path: str, args_hint: str) -> list[UserMessage]:
        return _msg(
            f"Verify the API call {function_path} (args hint: {args_hint}).\n"
            "Workflow:\n"
            "1. search_api_docs for its signature and parameter notes\n"
            "2. execute_sap_function with minimal safe args\n"
            "3. If return_value == 0: register_verified_function with the real signature,\n"
            "   parameter_notes on units/order, notes on anything surprising\n"
            "4. If it failed: record WHY in notes so the next agent doesn't retry blind"
        )
