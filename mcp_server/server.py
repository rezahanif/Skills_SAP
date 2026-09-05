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
SAP2000-MCP automates structural analysis and design via local COM (Windows).

Recommended 10-Step Structural Workflow:
1. Connect: connect_sap2000(attach_to_existing=True)
2. Initialize: init_structural_model(units="kN_m_C", template="blank")
3. Materials: define_material(name, material_type="steel"|"concrete", fy_mpa=..., fc_mpa=...)
4. Sections: define_frame_section(name, material, shape_type="I"|"Tube"|"Rectangle"|"Circle", dimensions)
5. Geometry (Arbitrary 3D): batch_create_frames(frames=[{"start": [x1,y1,z1], "end": [x2,y2,z2], "section": ...}])
6. Supports: assign_supports(support_type="fixed"|"pinned"|"roller") — auto-grounds base joints
7. Loading: apply_distributed_load (gravity), apply_wind_load (SNI 1727/ASCE 7), define_response_spectrum (SNI 1726/ASCE 7)
8. Combinations: define_load_combination(name, cases={"DEAD": 1.2, "LIVE": 1.6, ...})
9. Solve & Verify: run_analysis(), run_code_design(code_type="steel"|"concrete"), run_pushover_analysis()
10. Results: get_analysis_results(result_type="reactions"|"displacements"|"modal"|"frame_forces"|"pushover")

Disconnect: disconnect_sap2000(save_model=False, exit_application=False) when finished.
For raw OAPI operations: search_api_docs, query_function_registry, or execute_sap_function.
On errors: query get_error_hints(error_code).
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
    exit_application: bool | None = Field(default=None, description="True = force close SAP2000; False = detach and preserve running instance; None = auto (only close if launched by MCP)."),
) -> dict:
    """Disconnect from SAP2000 and optionally save the current model.

    Always call this when done to release COM resources.
    """
    return bridge.disconnect(save_model=save_model, exit_application=exit_application)


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
    title="Save Model",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
def save_model(
    file_path: str | None = Field(
        default=None,
        description="Target .sdb file path. If omitted, saves to the current file path or managed temporary directory.",
    ),
) -> dict:
    """Save the current SAP2000 model to disk.

    SAP2000 requires the model to be saved before RunAnalysis can be executed.
    Returns: {saved: bool, file_path: str, message: str}.
    """
    return bridge.save_model(file_path=file_path)


@mcp.tool(
    title="Run Analysis",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
def run_analysis() -> dict:
    """Run the finite element structural solver on the active model.

    Automatically saves the model if unsaved, executes the solver,
    and refreshes the 3D GUI view.
    Returns: {success: bool, return_code: int, is_locked: bool, message: str}.
    """
    return bridge.run_analysis()


@mcp.tool(
    title="Set Model Lock",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
)
def set_model_lock(
    locked: bool = Field(
        default=True,
        description="True = lock model; False = unlock model (clears analysis results to allow editing geometry/properties).",
    ),
) -> dict:
    """Lock or unlock the SAP2000 model.

    Set locked=False before attempting to add/modify geometry, materials, or loads
    in a model that has already been solved.
    Returns: {locked: bool, return_code: int, message: str}.
    """
    return bridge.set_model_lock(locked=locked)


@mcp.tool(
    title="Get Analysis Results",
    annotations=ToolAnnotations(readOnlyHint=True),
)
def get_analysis_results(
    result_type: str = Field(
        description='Type of results to query: "reactions" (base shear/gravity/moments), '
        '"displacements" (joint translation/rotation), "modal" (periods/frequencies/mass participation), '
        '"pushover" (capacity curve Vb vs roof displacement), or "frame_forces" (axial/shear/moments).',
    ),
    case_or_combo: str = Field(
        default="DEAD",
        description='Load case or combination name, e.g. "DEAD", "LIVE", "WIND_X", "COMB1", "MODAL".',
    ),
    object_type: str = Field(
        default="base",
        description='Target object category: "base" (reactions), "joint" (displacements), or "frame" (member forces).',
    ),
    object_id: str | None = Field(
        default=None,
        description='Optional specific joint label or frame label (e.g. "1", "30"). If omitted for joint/frame, defaults to the first available.',
    ),
) -> dict:
    """Extract structured finite element analysis results with explicit engineering units.

    Translates raw SAP2000 COM arrays into clean, labeled JSON dictionaries.
    Configures Results.Setup filters automatically.
    Returns: structured result dict with labeled fields and unit names.
    """
    return bridge.get_analysis_results(
        result_type=result_type,
        case_or_combo=case_or_combo,
        object_type=object_type,
        object_id=object_id,
    )


@mcp.tool(
    title="Initialize Structural Model",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True),
)
def init_structural_model(
    units: str = Field(
        default="kN_m_C",
        description='Standard engineering units name, e.g. "kN_m_C", "lb_in_F", "kip_ft_F", "N_mm_C".',
    ),
    template: str = Field(
        default="blank",
        description='Model template type, e.g. "blank" (default).',
    ),
) -> dict:
    """Initialize a clean new SAP2000 structural model with explicit units.

    Unlocks the model, initializes the database with specified units, and creates a blank canvas.
    Returns: {success: bool, units: str, unit_code: int, message: str}.
    """
    return bridge.init_structural_model(units=units, template=template)


@mcp.tool(
    title="Define Material",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
def define_material(
    name: str = Field(
        description='Unique material name, e.g. "A992Fy50", "fc_30MPa", "BJ37", "Rebar_420".',
    ),
    material_type: str = Field(
        default="steel",
        description='Material category: "steel", "concrete", or "rebar".',
    ),
    standard_grade: str | None = Field(
        default=None,
        description='Optional standard library grade identifier, e.g. "A992Fy50", "A36", "4000Psi".',
    ),
    fy_mpa: float | None = Field(
        default=None,
        description="Yield strength Fy in MPa (for steel or rebar, e.g. 345.0 for A992, 240.0 for BJ37).",
    ),
    fu_mpa: float | None = Field(
        default=None,
        description="Ultimate tensile strength Fu in MPa (e.g. 450.0).",
    ),
    fc_mpa: float | None = Field(
        default=None,
        description="Compressive cylinder strength f'c in MPa (for concrete, e.g. 30.0).",
    ),
    e_mpa: float | None = Field(
        default=None,
        description="Modulus of elasticity E in MPa (e.g. 200000.0 for steel; calculated automatically for concrete if omitted).",
    ),
    unit_weight_kn_m3: float | None = Field(
        default=None,
        description="Weight density in kN/m3 (default 78.5 for steel, 24.0 for concrete).",
    ),
) -> dict:
    """Define a structural material with standard presets or custom mechanical properties.

    Sets constitutive properties, elasticity modulus E, Poisson's ratio, and unit weight.
    Returns: {success: bool, material_name: str, material_type: str, mechanical_properties: dict, message: str}.
    """
    return bridge.define_material(
        name=name,
        material_type=material_type,
        standard_grade=standard_grade,
        fy_mpa=fy_mpa,
        fu_mpa=fu_mpa,
        fc_mpa=fc_mpa,
        e_mpa=e_mpa,
        unit_weight_kn_m3=unit_weight_kn_m3,
    )


@mcp.tool(
    title="Define Frame Section",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
def define_frame_section(
    name: str = Field(
        description='Unique cross-section name, e.g. "W14X90", "HSS6X6X3/8", "COL_400X400".',
    ),
    material: str = Field(
        default="A992Fy50",
        description='Material name assigned to this section, e.g. "A992Fy50", "A36", "4000Psi".',
    ),
    shape_type: str = Field(
        default="I",
        description='Cross-section shape category: "I" (wide flange), "Tube" (hollow box/HSS), '
        '"Rectangle" (solid concrete), or "Circle" (pipe/round column).',
    ),
    dimensions: dict = Field(
        default_factory=dict,
        description='Dimensional parameters in model length units. '
        'For "I": {"depth", "flange_width", "flange_thick", "web_thick"}. '
        'For "Tube": {"depth", "width", "thick"}. '
        'For "Rectangle": {"depth", "width"}. '
        'For "Circle": {"diameter"}.',
    ),
) -> dict:
    """Define a structural frame cross-section with automatic shape mapping.

    Unifies SetISection, SetTube, SetRectangle, and SetCircle into a single self-describing tool.
    Returns: {success: bool, section_name: str, shape_type: str, material: str, message: str}.
    """
    return bridge.define_frame_section(
        name=name,
        material=material,
        shape_type=shape_type,
        dimensions=dimensions,
    )


@mcp.tool(
    title="Batch Create Frames",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
def batch_create_frames(
    frames: list[dict] = Field(
        description='List of frame element definitions with arbitrary 3D spatial geometry: '
        '[{"start": [x1, y1, z1], "end": [x2, y2, z2], "section": "COL_400", "label": "optional_id"}, ...]. '
        'Supports orthogonal grids, irregular L-shapes, diagonal braces, slanted columns, and pitched roofs.',
    ),
) -> dict:
    """Create multiple structural frame elements with arbitrary 3D spatial geometry in a single call.

    Eliminates dozens of roundtrips when generating 3D building geometry.
    Returns: {success: bool, created_count: int, failed_count: int, frame_ids: list, message: str}.
    """
    return bridge.batch_create_frames(frames=frames)


@mcp.tool(
    title="Assign Supports",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
def assign_supports(
    joint_ids: list[str] | None = Field(
        default=None,
        description="Optional list of target joint IDs. If omitted, automatically selects and grounds all joints at ground level (Z = minimum Z).",
    ),
    support_type: str = Field(
        default="fixed",
        description='Support restraint preset: "fixed" (all 6 DOFs restrained), "pinned" (3 translations restrained), or "roller" (vertical translation only).',
    ),
    custom_restraints: list[bool] | None = Field(
        default=None,
        description="Optional 6 booleans [U1, U2, U3, R1, R2, R3] when support_type is 'custom'.",
    ),
) -> dict:
    """Assign boundary support conditions (Fixed, Pinned, Roller) to structural foundation joints.

    By default auto-detects all base joints at minimum Z elevation and assigns rigid fixed moment foundations.
    Returns: {success: bool, support_type: str, assigned_count: int, joint_ids: list, message: str}.
    """
    return bridge.assign_supports(
        joint_ids=joint_ids,
        support_type=support_type,
        custom_restraints=custom_restraints,
    )


@mcp.tool(
    title="Apply Distributed Load",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
def apply_distributed_load(
    frame_ids: list[str] = Field(
        description='List of target frame element IDs/labels to load, e.g. ["1", "2", "3"].',
    ),
    load_pattern: str = Field(
        default="DEAD",
        description='Target load pattern name, e.g. "DEAD", "LIVE", "SNOW". Created if it does not exist.',
    ),
    load_value: float = Field(
        default=0.0,
        description='Uniform line load intensity in current model units (e.g. kN/m or kip/ft).',
    ),
    direction: str = Field(
        default="gravity",
        description='Load direction: "gravity" (downwards), "global_z" (upwards), "global_x", or "global_y".',
    ),
) -> dict:
    """Apply uniform distributed line loads across multiple structural frame members.

    Eliminates the need for raw integer direction flags.
    Returns: {success: bool, applied_count: int, frame_ids: list, message: str}.
    """
    return bridge.apply_distributed_load(
        frame_ids=frame_ids,
        load_pattern=load_pattern,
        load_value=load_value,
        direction=direction,
    )


@mcp.tool(
    title="Define Load Combination",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
def define_load_combination(
    name: str = Field(
        description='Unique combination identifier, e.g. "COMB1_1.2D_1.6L", "COMB2_SEIS_X".',
    ),
    combo_type: str = Field(
        default="linear_additive",
        description='Combination formulation: "linear_additive" (factored sum), "envelope" (max/min forces), or "absolute_additive".',
    ),
    cases: dict[str, float] = Field(
        default_factory=dict,
        description='Mapping of load case/pattern names to scale factors, e.g. {"DEAD": 1.2, "LIVE": 1.6}.',
    ),
) -> dict:
    """Define a structural design load combination with factored load cases.

    Configures ultimate strength or serviceability combinations for finite element evaluation and design checks.
    Returns: {success: bool, combo_name: str, combo_type: str, cases_and_factors: dict, message: str}.
    """
    return bridge.define_load_combination(
        name=name,
        combo_type=combo_type,
        cases=cases,
    )


@mcp.tool(
    title="Run Code Design",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
def run_code_design(
    code_type: str = Field(
        default="steel",
        description='Design code module: "steel" (AISC 360 / Eurocode 3) or "concrete" (ACI 318 / Eurocode 2).',
    ),
    design_code: str | None = Field(
        default=None,
        description='Optional design code standard name, e.g. "AISC360_16", "Eurocode_3_2005". Omit for model default.',
    ),
) -> dict:
    """Execute structural code design verification and extract Demand-to-Capacity (D/C) stress ratios.

    Verifies if structural members satisfy building code safety limits (D/C <= 1.0 = PASS).
    Automatically runs finite element analysis first if the model is not solved.
    Returns: {success: bool, design_status: "PASS"|"FAIL", max_dc_ratio: float, critical_member: str, failing_members: list, message: str}.
    """
    return bridge.run_code_design(
        code_type=code_type,
        design_code=design_code,
    )


@mcp.tool(
    title="Apply Wind Load",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
def apply_wind_load(
    wind_speed: float = Field(
        default=38.0,
        description="Basic design wind speed V in m/s (e.g. 38 m/s per Indonesian SNI 1727:2020 / ASCE 7-16).",
    ),
    exposure_category: str = Field(
        default="B",
        description='Surface roughness exposure category: "B" (urban/suburban), "C" (open terrain), or "D" (coastal).',
    ),
    direction: str = Field(
        default="X",
        description='Lateral wind attack direction: "X" or "Y".',
    ),
    building_height: float | None = Field(
        default=None,
        description="Optional total building height in meters. Auto-detected from model joint coordinates if omitted.",
    ),
    building_width: float | None = Field(
        default=None,
        description="Optional windward facade width in meters. Auto-detected if omitted.",
    ),
    importance_factor: float = Field(
        default=1.0,
        description="Wind importance factor I_w (1.0 for Risk Category II).",
    ),
    gust_factor: float = Field(
        default=0.85,
        description="Gust effect factor G (0.85 for rigid structures).",
    ),
    frame_ids: list[str] | None = Field(
        default=None,
        description="Optional explicit list of target frame IDs to receive line load. If omitted, windward facade frames are auto-detected.",
    ),
) -> dict:
    """Calculate and assign code-compliant wind pressure and frame line loads per SNI 1727:2020 / ASCE 7-16.

    Computes velocity pressure qz, applies gust and external pressure coefficients (Cp = +0.8 windward, -0.5 leeward),
    and assigns distributed loads to windward frames under pattern WIND_X or WIND_Y.
    Returns: {success: bool, load_pattern: str, design_pressure_kpa: float, line_load_kn_m: float, applied_frames: list, message: str}.
    """
    return bridge.apply_wind_load(
        wind_speed=wind_speed,
        exposure_category=exposure_category,
        direction=direction,
        building_height=building_height,
        building_width=building_width,
        importance_factor=importance_factor,
        gust_factor=gust_factor,
        frame_ids=frame_ids,
    )


@mcp.tool(
    title="Define Response Spectrum",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
def define_response_spectrum(
    name: str = Field(
        default="SNI_1726_2019",
        description='Unique response spectrum function name, e.g. "SNI_1726_2019", "ASCE7_RS".',
    ),
    standard: str = Field(
        default="SNI_1726_2019",
        description='Design code standard: "SNI_1726_2019" or "ASCE7_16".',
    ),
    site_class: str = Field(
        default="D",
        description='Site soil classification: "A" (hard rock), "B" (rock), "C" (dense soil), "D" (stiff soil/sedang), "E" (soft soil).',
    ),
    ss: float = Field(
        default=0.90,
        description="Mapped MCE_R short-period spectral acceleration parameter S_s (g).",
    ),
    s1: float = Field(
        default=0.40,
        description="Mapped MCE_R 1-second spectral acceleration parameter S_1 (g).",
    ),
    r_factor: float = Field(
        default=8.0,
        description="Response modification coefficient R (e.g. 8.0 for Special Moment Frames).",
    ),
    importance_factor: float = Field(
        default=1.0,
        description="Seismic importance factor I_e (1.0 for Risk Category II).",
    ),
    direction: str = Field(
        default="both",
        description='Response spectrum load case direction: "X", "Y", or "both".',
    ),
    damping: float = Field(
        default=0.05,
        description="Inherent modal damping ratio (default 0.05 = 5%).",
    ),
) -> dict:
    """Generate smooth design response spectrum curves and dynamic load cases per SNI 1726:2019 / ASCE 7-16.

    Calculates site amplification factors (Fa, Fv), design parameters (SDS, SD1), corner periods (T0, Ts),
    registers the smooth spectral curve in SAP2000, and creates scaled dynamic load cases (RS_X, RS_Y) with scale factor g * Ie / R.
    Returns: {success: bool, function_name: str, parameters: dict, load_cases_created: list, message: str}.
    """
    return bridge.define_response_spectrum(
        name=name,
        standard=standard,
        site_class=site_class,
        ss=ss,
        s1=s1,
        r_factor=r_factor,
        importance_factor=importance_factor,
        direction=direction,
        damping=damping,
    )


@mcp.tool(
    title="Run Pushover Analysis",
    annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False),
)
def run_pushover_analysis(
    load_case_name: str = Field(
        default="PUSHOVER_X",
        description='Pushover analysis load case name, e.g. "PUSHOVER_X", "PUSHOVER_Y".',
    ),
    direction: str = Field(
        default="X",
        description='Push direction: "X" or "Y".',
    ),
    target_displacement: float = Field(
        default=0.30,
        description="Target roof monitored displacement in meters (e.g. 0.30 m).",
    ),
    control_joint: str | None = Field(
        default=None,
        description="Control joint ID at the roof. Auto-detected at highest model elevation if None.",
    ),
    initial_gravity_case: str = Field(
        default="PUSH_GRAV",
        description='Nonlinear static gravity pre-load case name, e.g. "PUSH_GRAV".',
    ),
    max_steps: int = Field(
        default=50,
        description="Maximum number of pushover incremental steps to solve and record.",
    ),
) -> dict:
    """Execute nonlinear static pushover analysis and extract capacity curve and ductility metrics.

    Configures nonlinear static gravity pre-load (P-Delta), sets up monotonic displacement-controlled
    lateral push to target roof drift, executes the nonlinear solver, and extracts the full capacity curve (Vb vs Delta_roof).
    Returns: {success: bool, pushover_case: str, max_base_shear_kn: float, max_roof_displacement_m: float, structural_ductility_ratio_mu: float, capacity_curve: list, message: str}.
    """
    return bridge.run_pushover_analysis(
        load_case_name=load_case_name,
        direction=direction,
        target_displacement=target_displacement,
        control_joint=control_joint,
        initial_gravity_case=initial_gravity_case,
        max_steps=max_steps,
    )


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
