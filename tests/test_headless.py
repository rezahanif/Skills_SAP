"""Headless tests for the SAP2000 connector — run WITHOUT SAP2000 and WITHOUT
real COM (comtypes is Windows-only; `from _ctypes import COMError` fails on
Linux). A fake `comtypes` module is injected into sys.modules before importing
the REAL sap_bridge / sap_executor / function_registry code, so the bridge
lifecycle, ByRef convention, executor sandbox, and registry logic are all
exercised against a mocked COM boundary.

These validate the connector boundary — NOT real SAP2000 compatibility.
"""
import json
import os
import sys
import types
from pathlib import Path

FORK = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(FORK / "mcp_server"))

# ── Fake comtypes (Windows-only on real platforms) ──────────────────────
_fake_comtypes = types.ModuleType("comtypes")
_fake_client = types.ModuleType("comtypes.client")


class FakeHelper:
    def GetObject(self, progid):
        return FakeSapObject(progid)

    def CreateObject(self, path):
        return FakeSapObject(path)

    def CreateObjectProgID(self, progid):
        return FakeSapObject(progid)


class FakeFrameObj:
    def Count(self):
        return 7

    def AddByCoord(self, *args):
        return ["FRAME1"] + list(args) + [0]  # ByRef outs..., ret_code last

    def GetNameList(self):
        return [0, ["1", "2", "3"]]

    def SetLoadDistributed(self, *args):
        return 0

    def GetPoints(self, *args):
        return ["1", "2", 0]


class FakePropFrame:
    def SetISection(self, *args):
        return 0

    def SetTube(self, *args):
        return 0

    def SetRectangle(self, *args):
        return 0

    def SetCircle(self, *args):
        return 0

    def SetPipe(self, *args):
        return 0


class FakeDesignSteel:
    def SetCode(self, code):
        return 0

    def SetComboStrength(self, combo, state):
        return 0

    def SetComboAutoGenerate(self, state):
        return 0

    def StartDesign(self):
        return 0

    def GetSummaryResults(self, fid, opt):
        # [num, frame_tuple, ratio_tuple, type_tuple, loc_tuple, combo_tuple]
        return [1, (str(fid),), (0.45,), (1,), (3.5,), ("COMB1",)]


class FakeDesignConcrete:
    def StartDesign(self):
        return 0


class FakePointObj:
    def Count(self):
        return 12

    def GetNameList(self):
        return [0, ["1", "2", "3"]]

    def GetCoordCartesian(self, pt, *args):
        return [0.0, 0.0, 12.0, 0]

    def SetRestraint(self, *args):
        return 0


class FakeAreaObj:
    def Count(self):
        return 3


class FakeFile:
    def NewBlank(self):
        return 0

    def Save(self, path):
        return 0


class FakeAnalyze:
    def RunAnalysis(self):
        return 0


class FakeView:
    def RefreshView(self, win, zoom):
        return 0


class FakeLoadPatterns:
    def GetNameList(self):
        return [0, ["DEAD", "LIVE", "WIND_X"]]

    def Add(self, *args):
        return 0


class FakeRespCombo:
    def GetNameList(self):
        return [0, ["COMB1", "COMB2"]]

    def Add(self, *args):
        return 0

    def SetLoads(self, *args):
        return 0

    def SetCaseList(self, *args):
        return [0, 0]


class FakePropMaterial:
    def SetMaterial(self, *args):
        return 0

    def SetMPIsotropic(self, *args):
        return 0

    def SetWeightAndMass(self, *args):
        return 0

    def SetOSteel_1(self, *args):
        return 0

    def SetOConcrete_1(self, *args):
        return 0

    def SetORebar_1(self, *args):
        return 0

    def AddMaterial(self, *args):
        return 0


class FakeFuncRS:
    def SetUser(self, *args):
        return 0


class FakeFunc:
    FuncRS = FakeFuncRS()


class FakeResponseSpectrum:
    def SetCase(self, *args):
        return 0

    def SetLoads(self, *args):
        return 0


class FakeStaticNonlinear:
    def SetCase(self, *args):
        return 0

    def SetInitialCase(self, *args):
        return 0

    def SetLoads(self, *args):
        return 0

    def SetGeometricNonlinearity(self, *args):
        return 0

    def SetLoadApplication(self, *args):
        return 0

    def SetResultsSaved(self, *args):
        return 0


class FakeLoadCases:
    ResponseSpectrum = FakeResponseSpectrum()
    StaticNonlinear = FakeStaticNonlinear()


class FakeResultsSetup:
    def DeselectAllCasesAndCombosForOutput(self):
        return 0

    def SetCaseSelectedForOutput(self, case):
        return 0

    def SetComboSelectedForOutput(self, combo):
        return 0


class FakeResults:
    Setup = FakeResultsSetup()

    def BaseReact(self):
        # [num, loadcase, step, stepnum, Fx, Fy, Fz, Mx, My, Mz]
        return [1, ("COMB1",), ("Type",), (0.0,), (-240.0,), (0.0,), (1500.0,), (0.0,), (-12000.0,), (0.0,)]

    def JointDispl(self, pt, opt):
        # [num, obj, elm, loadcase, step, stepnum, U1, U2, U3, R1, R2, R3]
        return [1, (str(pt),), (str(pt),), ("WIND_X",), ("Step",), (0.0,), (0.0012,), (0.0,), (-0.0001,), (0.0,), (0.0,), (0.0,)]

    def ModalPeriod(self):
        # [num, loadcase, step, mode_num, period, freq, circfreq, eigen]
        return [2, ("MODAL", "MODAL"), ("Mode", "Mode"), (1.0, 2.0), (0.42, 0.33), (2.38, 3.03), (14.9, 19.0), (224.0, 362.0)]

    def FrameForce(self, frame, opt):
        # [num, obj, sta, elm, elmsta, case, step, stepnum, P, V2, V3, T, M2, M3]
        return [1, (str(frame),), (0.0,), ("1-1",), (0.0,), ("COMB1",), ("Step",), (0.0,), (-400.0,), (10.0,), (0.0,), (0.0,), (0.0,), (25.0,)]


class FakeSapModel:
    FrameObj = FakeFrameObj()
    PointObj = FakePointObj()
    AreaObj = FakeAreaObj()
    File = FakeFile()
    Analyze = FakeAnalyze()
    View = FakeView()
    LoadPatterns = FakeLoadPatterns()
    RespCombo = FakeRespCombo()
    Results = FakeResults()
    PropFrame = FakePropFrame()
    PropMaterial = FakePropMaterial()
    DesignSteel = FakeDesignSteel()
    DesignConcrete = FakeDesignConcrete()
    Func = FakeFunc()
    LoadCases = FakeLoadCases()
    _locked = False

    def GetModelFilename(self, absolute):
        return "C:/models/test.sdb"

    def GetPresentUnits(self):
        return 6

    def InitializeNewModel(self, units=6):
        return 0

    def GetModelIsLocked(self):
        return self._locked

    def SetModelIsLocked(self, locked):
        self._locked = locked
        return 0


class FakeSapObject:
    def __init__(self, tag):
        self.tag = tag
        self.SapModel = FakeSapModel()
        self._exited = False

    def GetOAPIVersionNumber(self):
        return 25.0

    def ApplicationStart(self):
        return 0

    def ApplicationExit(self, save):
        self._exited = True
        return 0


_fake_client.CreateObject = lambda progid: FakeHelper() if progid == "SAP2000v1.Helper" else FakeSapObject(progid)
_fake_comtypes.client = _fake_client
_fake_comtypes.CoInitialize = lambda: None
_fake_comtypes.CoUninitialize = lambda: None
sys.modules["comtypes"] = _fake_comtypes
sys.modules["comtypes.client"] = _fake_client

import pytest  # noqa: E402

from sap_bridge import SapBridge, bridge as module_bridge  # noqa: E402
from sap_executor import execute_function, run_script  # noqa: E402
from function_registry import FunctionRegistry  # noqa: E402


@pytest.fixture()
def fresh_bridge():
    b = SapBridge()
    yield b


@pytest.fixture(autouse=True)
def _module_bridge_connected():
    """Tool-level code (execute_function / run_script) uses the module-level
    `bridge` singleton, not per-test instances. Connect it before each test
    that exercises tools; reset afterwards."""
    module_bridge.connect(attach_to_existing=True)
    yield
    module_bridge.disconnect(save_model=False)
    module_bridge._helper = None


def test_bridge_starts_disconnected(fresh_bridge):
    assert fresh_bridge.is_connected is False
    assert fresh_bridge.sap_object is None
    assert fresh_bridge.sap_model is None


def test_get_model_info_not_connected(fresh_bridge):
    import pytest
    from errors import NotConnectedError

    with pytest.raises(NotConnectedError):
        fresh_bridge.get_model_info()


def test_disconnect_when_not_connected(fresh_bridge):
    r = fresh_bridge.disconnect()
    assert r["disconnected"] is True


def test_connect_attaches_to_existing(fresh_bridge):
    r = fresh_bridge.connect(attach_to_existing=True)
    assert r["connected"] is True
    assert r["version"] == 25.0
    assert r["model_path"] == "C:/models/test.sdb"
    assert r["num_frames"] == 7
    assert r["num_points"] == 12
    assert r["num_areas"] == 3


def test_connect_idempotent(fresh_bridge):
    fresh_bridge.connect()
    r = fresh_bridge.connect()
    assert r["connected"] is True
    assert "Already connected" in r.get("message", "")


def test_disconnect_releases_references(fresh_bridge):
    fresh_bridge.connect()
    obj = fresh_bridge.sap_object
    r = fresh_bridge.disconnect(save_model=False, exit_application=True)
    assert r["disconnected"] is True
    assert obj._exited is True
    assert fresh_bridge.sap_object is None
    assert fresh_bridge.is_connected is False


def test_execute_function_not_connected(fresh_bridge):
    import pytest
    from errors import NotConnectedError

    module_bridge.disconnect(save_model=False)
    module_bridge._helper = None
    with pytest.raises(NotConnectedError):
        execute_function("SapModel.FrameObj.AddByCoord", [0, 0, 0])


def test_execute_function_byref_convention(fresh_bridge):
    fresh_bridge.connect()
    r = execute_function("SapModel.FrameObj.AddByCoord", [0, 0, 0, "", "F1"])
    assert r["success"] is True
    assert r["return_value"] == 0
    # ByRef outputs precede ret_code; ret_code is ALWAYS last (source convention)
    assert r["output_params"][0] == "FRAME1"


def test_execute_function_bad_path(fresh_bridge):
    import pytest
    from errors import PathResolveError

    fresh_bridge.connect()
    with pytest.raises(PathResolveError) as exc_info:
        execute_function("SapModel.Nonexistent.DoThing", [])
    assert "Could not resolve" in str(exc_info.value)
    assert exc_info.value.details["function_path"] == "SapModel.Nonexistent.DoThing"


def test_execute_function_sapobject_root(fresh_bridge):
    fresh_bridge.connect()
    r = execute_function("SapObject.GetOAPIVersionNumber", [])
    assert r["success"] is True


def test_run_script_blocked_import(fresh_bridge):
    import pytest
    from errors import ScriptExecutionError

    fresh_bridge.connect()
    with pytest.raises(ScriptExecutionError) as exc_info:
        run_script("import os\nresult['x'] = 1")
    assert "blocked" in str(exc_info.value).lower()


def test_run_script_open_blocked(fresh_bridge):
    import pytest
    from errors import ScriptExecutionError

    fresh_bridge.connect()
    with pytest.raises(ScriptExecutionError) as exc_info:
        run_script("f = open('x.txt', 'w')")
    assert "not allowed" in str(exc_info.value)


def test_run_script_syntax_error(fresh_bridge):
    import pytest
    from errors import ScriptSyntaxError

    fresh_bridge.connect()
    with pytest.raises(ScriptSyntaxError) as exc_info:
        run_script("def broken(:")
    assert "Syntax error" in str(exc_info.value)
    assert exc_info.value.details["line"] is not None


def test_run_script_success_injects_references(fresh_bridge):
    fresh_bridge.connect()
    r = run_script(
        "result['frame_count'] = SapModel.FrameObj.Count()\n"
        "result['n'] = 2 + 2\n"
        "import math\n"
        "result['pi'] = math.pi"
    )
    assert r["success"] is True
    assert r["result"]["frame_count"] == 7
    assert r["result"]["n"] == 4
    assert abs(r["result"]["pi"] - 3.14159) < 1e-4


def test_run_script_not_connected(fresh_bridge):
    import pytest
    from errors import NotConnectedError

    module_bridge.disconnect(save_model=False)
    module_bridge._helper = None
    with pytest.raises(NotConnectedError):
        run_script("result['x'] = 1")


def test_run_script_auto_registers_api_functions(fresh_bridge, tmp_path):
    import sap_executor

    reg = FunctionRegistry(tmp_path / "registry.json")
    sap_executor.function_registry = reg
    try:
        fresh_bridge.connect()
        r = run_script(
            "ret = SapModel.InitializeNewModel()\nresult['ret'] = ret\n"
            "ret = SapModel.File.NewBlank()\nresult['ret2'] = ret"
        )
        assert r["success"] is True
        assert "SapModel.InitializeNewModel" in r["registered_functions"]
        detail = reg.get_function("SapModel.InitializeNewModel")
        assert detail.get("verified") is True
    finally:
        sap_executor.function_registry = __import__("function_registry").registry


def test_sandbox_is_restrictive_not_secure(fresh_bridge):
    """Documented finding: import/open are blocked, but full builtins (exec,
    eval, object.__subclasses__) remain reachable — the sandbox is a
    convenience guardrail, NOT a security boundary. AiConnect treats
    run_sap_script as full EXECUTION privilege."""
    fresh_bridge.connect()
    r = run_script("result['exec_available'] = callable(exec)")
    assert r["success"] is True
    assert r["result"]["exec_available"] is True


def test_registry_pure_python(tmp_path):
    reg = FunctionRegistry(tmp_path / "registry.json")
    r = reg.register_function(
        function_path="SapModel.FrameObj.AddByCoord",
        category="Object_Model",
        description="Add frame by coordinates",
        signature="(x1, y1, z1, x2, y2, z2, Name) -> ret_code",
    )
    assert r["is_new"] is True
    detail = reg.get_function("SapModel.FrameObj.AddByCoord")
    assert detail["signature"].startswith("(x1")
    reg.mark_verified("SapModel.FrameObj.AddByCoord")
    assert reg.get_summary()["total_verified"] == 1


def test_high_level_workflow_tools(fresh_bridge):
    b = fresh_bridge
    b.connect()

    # 1. Enhanced get_model_info
    info = b.get_model_info()
    assert info["connected"] is True
    assert info["units"] == 6
    assert info["units_detail"]["name"] == "kN_m_C"
    assert info["is_locked"] is False
    assert "DEAD" in info["load_patterns"]
    assert "COMB1" in info["load_combos"]

    # 2. save_model
    save_res = b.save_model("C:/test_run.sdb")
    assert save_res["saved"] is True
    assert save_res["file_path"] == "C:/test_run.sdb"

    # 3. run_analysis
    ana_res = b.run_analysis()
    assert ana_res["success"] is True

    # 4. set_model_lock
    lock_res = b.set_model_lock(True)
    assert lock_res["locked"] is True
    assert b.get_model_info()["is_locked"] is True

    unlock_res = b.set_model_lock(False)
    assert unlock_res["locked"] is False

    # 5. get_analysis_results (reactions)
    rxn = b.get_analysis_results(result_type="reactions", case_or_combo="COMB1")
    assert rxn["count"] == 1
    assert rxn["reactions"]["Fx"] == -240.0
    assert rxn["reactions"]["Fz"] == 1500.0
    assert rxn["units"]["force"] == "kN"

    # 6. get_analysis_results (displacements)
    disp = b.get_analysis_results(result_type="displacements", case_or_combo="WIND_X", object_id="12")
    assert disp["count"] == 1
    assert disp["displacements"]["U1"] == 0.0012
    assert disp["units"]["translation"] == "m"

    # 7. get_analysis_results (modal)
    modal = b.get_analysis_results(result_type="modal", case_or_combo="MODAL")
    assert modal["count"] == 2
    assert modal["modes"][0]["period_s"] == 0.42

    # 8. get_analysis_results (frame_forces)
    forces = b.get_analysis_results(result_type="frame_forces", case_or_combo="COMB1", object_id="1")
    assert forces["count"] == 1
    assert forces["stations"][0]["P_axial"] == -400.0
    assert forces["stations"][0]["M3_major_moment"] == 25.0


def test_advanced_engineering_tools(fresh_bridge):
    b = fresh_bridge
    b.connect()

    # 1. init_structural_model
    init_res = b.init_structural_model(units="kN_m_C", template="blank")
    assert init_res["success"] is True
    assert init_res["unit_code"] == 6

    # 2. define_frame_section (I-Shape & Tube)
    sec_w = b.define_frame_section(
        name="W14X90",
        material="A992Fy50",
        shape_type="I",
        dimensions={"depth": 0.356, "flange_width": 0.368, "flange_thick": 0.018, "web_thick": 0.011}
    )
    assert sec_w["success"] is True
    assert sec_w["shape_type"] == "I"

    sec_hss = b.define_frame_section(
        name="HSS6X6X3/8",
        material="A992Fy50",
        shape_type="Tube",
        dimensions={"depth": 0.152, "width": 0.152, "thick": 0.0095}
    )
    assert sec_hss["success"] is True

    # 3. apply_distributed_load
    load_res = b.apply_distributed_load(
        frame_ids=["1", "2"],
        load_pattern="LIVE",
        load_value=8.5,
        direction="gravity"
    )
    assert load_res["success"] is True
    assert load_res["applied_count"] == 2

    # 4. run_code_design (Steel AISC 360 D/C Ratios)
    design_res = b.run_code_design(code_type="steel")
    assert design_res["success"] is True
    assert design_res["design_status"] == "PASS"
    assert design_res["max_dc_ratio"] == 0.45
    assert design_res["critical_member"] == "1"


def test_new_registered_structural_tools(fresh_bridge):
    b = fresh_bridge
    b.connect()

    # 1. apply_wind_load
    wind_res = b.apply_wind_load(
        wind_speed=38.0,
        exposure_category="B",
        direction="X",
        frame_ids=["1", "2"],
    )
    assert wind_res["success"] is True
    assert wind_res["load_pattern"] == "WIND_X"
    assert wind_res["applied_frames_count"] == 2
    assert wind_res["design_pressure_kpa"] > 0

    # 2. define_response_spectrum
    rs_res = b.define_response_spectrum(
        name="SNI_1726_2019",
        standard="SNI_1726_2019",
        site_class="D",
        ss=0.90,
        s1=0.40,
        r_factor=8.0,
        direction="both",
    )
    assert rs_res["success"] is True
    assert rs_res["function_name"] == "SNI_1726_2019"
    assert "RS_X" in rs_res["load_cases_created"]
    assert "RS_Y" in rs_res["load_cases_created"]
    assert rs_res["parameters"]["SDS"] > 0

    # 3. run_pushover_analysis
    push_res = b.run_pushover_analysis(
        load_case_name="PUSHOVER_X",
        direction="X",
        target_displacement=0.30,
        control_joint="1",
        initial_gravity_case="PUSH_GRAV",
    )
    assert push_res["pushover_case"] == "PUSHOVER_X"
    assert push_res["direction"] == "X"


def test_complete_structural_lifecycle_tools(fresh_bridge):
    b = fresh_bridge
    b.connect()

    # 1. define_material (Steel & Concrete)
    mat_steel = b.define_material(name="A992Fy50", material_type="steel", fy_mpa=345.0)
    assert mat_steel["success"] is True
    assert mat_steel["material_name"] == "A992Fy50"

    mat_conc = b.define_material(name="fc_30MPa", material_type="concrete", fc_mpa=30.0)
    assert mat_conc["success"] is True
    assert mat_conc["material_type"] == "concrete"

    # 2. batch_create_frames (arbitrary 3D coordinates, non-cube)
    frames_input = [
        {"start": [0.0, 0.0, 0.0], "end": [0.0, 0.0, 3.5], "section": "COL_1", "label": "C1"},
        {"start": [0.0, 0.0, 3.5], "end": [5.0, 2.5, 3.5], "section": "BEAM_1", "label": "B1"},
        {"start": [5.0, 2.5, 0.0], "end": [5.0, 2.5, 3.5], "section": "COL_1", "label": "C2"},
    ]
    batch_res = b.batch_create_frames(frames=frames_input)
    assert batch_res["success"] is True
    assert batch_res["created_count"] == 3

    # 3. assign_supports (Fixed boundary condition)
    supp_res = b.assign_supports(joint_ids=["1", "2"], support_type="fixed")
    assert supp_res["success"] is True
    assert supp_res["support_type"] == "fixed"
    assert supp_res["restraints"] == [True, True, True, True, True, True]

    # 4. define_load_combination (Factored 1.2D + 1.6L)
    combo_res = b.define_load_combination(
        name="COMB1_1.2D_1.6L",
        combo_type="linear_additive",
        cases={"DEAD": 1.2, "LIVE": 1.6}
    )
    assert combo_res["success"] is True
    assert combo_res["combo_name"] == "COMB1_1.2D_1.6L"
    assert combo_res["cases_and_factors"]["DEAD"] == 1.2


