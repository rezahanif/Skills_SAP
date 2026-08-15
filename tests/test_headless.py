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


class FakePointObj:
    def Count(self):
        return 12


class FakeAreaObj:
    def Count(self):
        return 3


class FakeFile:
    def NewBlank(self):
        return 0


class FakeSapModel:
    FrameObj = FakeFrameObj()
    PointObj = FakePointObj()
    AreaObj = FakeAreaObj()
    File = FakeFile()

    def GetModelFilename(self, absolute):
        return "C:/models/test.sdb"

    def GetPresentUnits(self):
        return 6

    def InitializeNewModel(self):
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
    info = fresh_bridge.get_model_info()
    assert info["connected"] is False
    assert "error" in info


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
    r = fresh_bridge.disconnect(save_model=False)
    assert r["disconnected"] is True
    assert obj._exited is True
    assert fresh_bridge.sap_object is None
    assert fresh_bridge.is_connected is False


def test_execute_function_not_connected(fresh_bridge):
    module_bridge.disconnect(save_model=False)
    module_bridge._helper = None
    r = execute_function("SapModel.FrameObj.AddByCoord", [0, 0, 0])
    assert r["success"] is False
    assert "connect_sap2000" in r["error"]


def test_execute_function_byref_convention(fresh_bridge):
    fresh_bridge.connect()
    r = execute_function("SapModel.FrameObj.AddByCoord", [0, 0, 0, "", "F1"])
    assert r["success"] is True
    assert r["return_value"] == 0
    # ByRef outputs precede ret_code; ret_code is ALWAYS last (source convention)
    assert r["output_params"][0] == "FRAME1"


def test_execute_function_bad_path(fresh_bridge):
    fresh_bridge.connect()
    r = execute_function("SapModel.Nonexistent.DoThing", [])
    assert r["success"] is False
    assert "Could not resolve" in r["error"]


def test_execute_function_sapobject_root(fresh_bridge):
    fresh_bridge.connect()
    r = execute_function("SapObject.GetOAPIVersionNumber", [])
    assert r["success"] is True


def test_run_script_blocked_import(fresh_bridge):
    fresh_bridge.connect()
    r = run_script("import os\nresult['x'] = 1")
    assert r["success"] is False
    assert "blocked" in r["error"].lower()


def test_run_script_open_blocked(fresh_bridge):
    fresh_bridge.connect()
    r = run_script("f = open('x.txt', 'w')")
    assert r["success"] is False
    assert "not allowed" in r["error"]


def test_run_script_syntax_error(fresh_bridge):
    fresh_bridge.connect()
    r = run_script("def broken(:")
    assert r["success"] is False
    assert "Syntax error" in r["error"]


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
    module_bridge.disconnect(save_model=False)
    module_bridge._helper = None
    r = run_script("result['x'] = 1")
    assert r["success"] is False


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
