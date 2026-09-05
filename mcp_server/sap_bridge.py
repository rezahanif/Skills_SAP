"""SAP2000 COM Bridge — Manages connection to a local SAP2000 instance via COM.

Supports two modes:
  - Launch a new SAP2000 instance (given a program path)
  - Attach to an already-running instance

All COM interaction is centralized here. Other modules use this bridge
to obtain SapObject and SapModel references.

Note: comtypes is imported lazily inside _create_helper() so the MCP server
can start on non-Windows platforms (tools/list, registry, docs, sandbox all
work headless); only connect_sap2000 requires real COM.
"""

import logging
import os

from errors import ConnectionFailedError, NotConnectedError

logger = logging.getLogger(__name__)

UNITS_MAP = {
    1: {"name": "lb_in_F", "force": "lb", "length": "in", "temp": "F"},
    2: {"name": "lb_ft_F", "force": "lb", "length": "ft", "temp": "F"},
    3: {"name": "kip_in_F", "force": "kip", "length": "in", "temp": "F"},
    4: {"name": "kip_ft_F", "force": "kip", "length": "ft", "temp": "F"},
    5: {"name": "kN_mm_C", "force": "kN", "length": "mm", "temp": "C"},
    6: {"name": "kN_m_C", "force": "kN", "length": "m", "temp": "C"},
    7: {"name": "kgf_mm_C", "force": "kgf", "length": "mm", "temp": "C"},
    8: {"name": "kgf_m_C", "force": "kgf", "length": "m", "temp": "C"},
    9: {"name": "N_mm_C", "force": "N", "length": "mm", "temp": "C"},
    10: {"name": "N_m_C", "force": "N", "length": "m", "temp": "C"},
    11: {"name": "Ton_mm_C", "force": "Ton", "length": "mm", "temp": "C"},
    12: {"name": "Ton_m_C", "force": "Ton", "length": "m", "temp": "C"},
    13: {"name": "kN_cm_C", "force": "kN", "length": "cm", "temp": "C"},
    14: {"name": "kgf_cm_C", "force": "kgf", "length": "cm", "temp": "C"},
    15: {"name": "N_cm_C", "force": "N", "length": "cm", "temp": "C"},
}


class SapBridge:
    """Wrapper around the SAP2000 COM connection."""

    def __init__(self):
        self._sap_object = None
        self._sap_model = None
        self._helper = None
        self._launched_by_us = False

    # ------------------------------------------------------------------
    # Public properties
    # ------------------------------------------------------------------

    @property
    def sap_object(self):
        """Return the current cOAPI SapObject, or None if not connected."""
        return self._sap_object

    @property
    def sap_model(self):
        """Return the current cSapModel, or None if not connected."""
        return self._sap_model

    @property
    def is_connected(self) -> bool:
        """True when we hold a live SapObject reference."""
        return self._sap_object is not None

    # ------------------------------------------------------------------
    # Connection helpers
    # ------------------------------------------------------------------

    def _ensure_desktop(self):
        """Ensure current thread is attached to the interactive Default desktop.

        When run inside background services or runner environments (e.g. exebox),
        the thread desktop may differ from the user's interactive 'Default' desktop.
        Connecting to the Default desktop allows the COM ROT and GetObject to locate
        the user's running desktop SAP2000 instance.
        """
        import sys
        if sys.platform == "win32":
            try:
                import ctypes
                user32 = ctypes.windll.user32
                DESKTOP_ALL = 0x1FF
                hDeskDefault = user32.OpenDesktopW("Default", 0, False, DESKTOP_ALL)
                if hDeskDefault:
                    user32.SetThreadDesktop(hDeskDefault)
            except Exception:
                pass

    def _create_helper(self):
        """Instantiate the SAP2000 COM helper once.

        comtypes is imported here (not at module top) so the server can run
        headless on non-Windows platforms; COM is only required for
        connect_sap2000.
        """
        self._ensure_desktop()
        if self._helper is None:
            import comtypes.client

            self._helper = comtypes.client.CreateObject("SAP2000v1.Helper")
            try:
                import comtypes.gen.SAP2000v1 as sap_gen
                self._helper = self._helper.QueryInterface(sap_gen.cHelper)
            except Exception:
                pass

    def connect(
        self,
        program_path: str | None = None,
        attach_to_existing: bool = True,
    ) -> dict:
        """
        Connect to SAP2000.

        Parameters
        ----------
        program_path : str | None
            Full path to SAP2000.exe.  Ignored when *attach_to_existing* is True.
            When None and attach_to_existing is False, the latest installed
            version is launched via ProgID.
        attach_to_existing : bool
            If True, attach to an already-running SAP2000 instance.

        Returns
        -------
        dict  {connected, version, model_path, units, error}
        """
        if self.is_connected:
            return {
                "connected": True,
                "message": "Already connected to SAP2000.",
                **self._model_summary(),
            }

        self._create_helper()

        try:
            if attach_to_existing:
                self._ensure_desktop()
                self._sap_object = self._helper.GetObject(
                    "CSI.SAP2000.API.SapObject"
                )
                if self._sap_object is None:
                    # Fallback: check if SAP2000.exe process exists and try GetObjectProcess
                    try:
                        import subprocess
                        out = subprocess.check_output(
                            ["tasklist", "/fi", "imagename eq SAP2000.exe", "/fo", "csv", "/nh"],
                            text=True, stderr=subprocess.DEVNULL
                        )
                        for line in out.strip().splitlines():
                            parts = [p.strip(' "') for p in line.split(',')]
                            if len(parts) >= 2 and parts[0].lower() == "sap2000.exe":
                                pid = int(parts[1])
                                self._sap_object = self._helper.GetObjectProcess("CSI.SAP2000.API.SapObject", pid)
                                if self._sap_object is not None:
                                    break
                    except Exception:
                        pass

                if self._sap_object is None:
                    raise ConnectionFailedError(
                        "Unable to attach to running SAP2000 instance (GetObject returned None). "
                        "Ensure SAP2000 is running and not running with differing administrator/UAC elevation levels.",
                        details={"attach_to_existing": True},
                    )
                self._launched_by_us = False
                logger.info("Attached to existing SAP2000 instance.")
            elif program_path:
                self._sap_object = self._helper.CreateObject(program_path)
                if self._sap_object is None:
                    raise ConnectionFailedError(
                        f"Unable to launch SAP2000 from {program_path}.",
                        details={"program_path": program_path},
                    )
                self._launched_by_us = True
                self._sap_object.ApplicationStart()
                logger.info("Started SAP2000 from %s", program_path)
            else:
                self._sap_object = self._helper.CreateObjectProgID(
                    "CSI.SAP2000.API.SapObject"
                )
                if self._sap_object is None:
                    raise ConnectionFailedError("Unable to launch SAP2000 via ProgID.")
                self._launched_by_us = True
                self._sap_object.ApplicationStart()
                logger.info("Started latest installed SAP2000 via ProgID.")

            self._sap_model = self._sap_object.SapModel
            return {"connected": True, **self._model_summary()}

        except ConnectionFailedError:
            self._sap_object = None
            self._sap_model = None
            raise
        except Exception as exc:
            self._sap_object = None
            self._sap_model = None
            logger.exception("Failed to connect to SAP2000.")
            raise ConnectionFailedError(
                str(exc),
                details={
                    "attach_to_existing": attach_to_existing,
                    "program_path": program_path,
                },
            ) from exc

    def disconnect(self, save_model: bool = False, exit_application: bool | None = None) -> dict:
        """
        Disconnect from SAP2000 and optionally save the model.

        Setting references to None releases COM resources.
        Only exits the application if it was launched by us or exit_application=True.
        """
        if not self.is_connected:
            return {"disconnected": True, "message": "Was not connected."}

        should_exit = exit_application if exit_application is not None else self._launched_by_us
        try:
            if should_exit:
                self._sap_object.ApplicationExit(save_model)
            else:
                logger.info("Preserving attached SAP2000 instance; releasing COM reference.")
        except Exception as exc:
            logger.warning("ApplicationExit raised: %s", exc)
        finally:
            self._sap_model = None
            self._sap_object = None
            self._launched_by_us = False
            logger.info("Disconnected from SAP2000 (save=%s).", save_model)

        return {"disconnected": True, "saved": save_model}

    def get_model_info(self) -> dict:
        """
        Return a summary of the current connection and model state.

        Useful for the agent to verify state before/after executing scripts.
        """
        if not self.is_connected:
            raise NotConnectedError(
                "Not connected to SAP2000.",
                details={"operation": "get_model_info"},
            )
        return {"connected": True, **self._model_summary()}

    def save_model(self, file_path: str | None = None) -> dict:
        """Save the active model to disk.

        If file_path is omitted or empty, saves to the current file path
        or a managed default 'Structural_Model.sdb' in the working directory.
        """
        if not self.is_connected:
            raise NotConnectedError("Not connected to SAP2000.", details={"operation": "save_model"})

        target_path = file_path
        if not target_path:
            try:
                curr = self._sap_model.GetModelFilename(True)
                if curr and not curr.endswith("(Untitled)"):
                    target_path = curr
            except Exception:
                pass

        if not target_path:
            import tempfile
            target_path = os.path.join(tempfile.gettempdir(), "SAP2000_Model.sdb")

        ret = self._sap_model.File.Save(target_path)
        return {
            "saved": ret == 0,
            "file_path": target_path,
            "return_code": ret,
            "message": "Model saved successfully." if ret == 0 else f"File.Save returned code {ret}",
        }

    def run_analysis(self) -> dict:
        """Run the finite element solver on the active model.

        Ensures the model is saved first, runs analysis, and refreshes the view.
        """
        if not self.is_connected:
            raise NotConnectedError("Not connected to SAP2000.", details={"operation": "run_analysis"})

        # SAP2000 mandates model file is saved before running analysis
        try:
            curr = self._sap_model.GetModelFilename(True)
            if not curr or curr.endswith("(Untitled)"):
                self.save_model()
        except Exception:
            self.save_model()

        ret = self._sap_model.Analyze.RunAnalysis()
        try:
            self._sap_model.View.RefreshView(0, False)
        except Exception:
            pass

        is_locked = False
        try:
            is_locked = bool(self._sap_model.GetModelIsLocked())
        except Exception:
            pass

        return {
            "success": ret == 0,
            "return_code": ret,
            "is_locked": is_locked,
            "message": "Analysis completed successfully." if ret == 0 else f"RunAnalysis returned code {ret}",
        }

    def set_model_lock(self, locked: bool) -> dict:
        """Set the locked state of the model.

        Unlocking (locked=False) deletes analysis results and allows editing geometry.
        """
        if not self.is_connected:
            raise NotConnectedError("Not connected to SAP2000.", details={"operation": "set_model_lock"})

        ret = self._sap_model.SetModelIsLocked(locked)
        curr_locked = False
        try:
            curr_locked = bool(self._sap_model.GetModelIsLocked())
        except Exception:
            curr_locked = locked

        return {
            "locked": curr_locked,
            "return_code": ret,
            "message": f"Model lock state set to {curr_locked}.",
        }

    def get_analysis_results(
        self,
        result_type: str,
        case_or_combo: str,
        object_type: str = "base",
        object_id: str | None = None,
    ) -> dict:
        """Extract structured analysis results with units and labeled fields.

        Parameters
        ----------
        result_type : "reactions" | "displacements" | "modal" | "frame_forces"
        case_or_combo : Name of the load case or load combination (e.g. "DEAD", "COMB1")
        object_type : "base" | "joint" | "frame"
        object_id : Specific joint or frame label (required for displacements and frame_forces)
        """
        if not self.is_connected:
            raise NotConnectedError("Not connected to SAP2000.", details={"operation": "get_analysis_results"})

        # Configure results setup
        try:
            self._sap_model.Results.Setup.DeselectAllCasesAndCombosForOutput()
            self._sap_model.Results.Setup.SetCaseSelectedForOutput(case_or_combo)
            self._sap_model.Results.Setup.SetComboSelectedForOutput(case_or_combo)
        except Exception as e:
            logger.warning("Failed to configure Results.Setup: %s", e)

        units_info = self.get_model_info().get("units_detail", {})
        force_unit = units_info.get("force", "Force")
        length_unit = units_info.get("length", "Length")
        moment_unit = f"{force_unit}*{length_unit}"

        rtype = result_type.lower()
        if rtype == "reactions" or (rtype == "base" and object_type == "base"):
            res = self._sap_model.Results.BaseReact()
            if not res or len(res) < 10 or res[0] <= 0:
                return {"result_type": "reactions", "case_or_combo": case_or_combo, "count": 0, "results": []}

            fx = float(res[4][0])
            fy = float(res[5][0])
            fz = float(res[6][0])
            mx = float(res[7][0])
            my = float(res[8][0])
            mz = float(res[9][0])

            return {
                "result_type": "reactions",
                "case_or_combo": case_or_combo,
                "count": 1,
                "units": {"force": force_unit, "moment": moment_unit},
                "reactions": {
                    "Fx": fx,
                    "Fy": fy,
                    "Fz": fz,
                    "Mx": mx,
                    "My": my,
                    "Mz": mz,
                    "base_shear_horizontal": float((fx**2 + fy**2)**0.5),
                    "total_vertical_gravity": fz,
                },
            }

        elif rtype == "displacements" or object_type == "joint":
            if not object_id:
                # Default to first joint if omitted
                pts = self._sap_model.PointObj.GetNameList()
                object_id = pts[1][0] if (pts and len(pts) > 1 and len(pts[1]) > 0) else "1"

            res = self._sap_model.Results.JointDispl(str(object_id), 0)
            if not res or len(res) < 9 or res[0] <= 0:
                return {"result_type": "displacements", "joint": str(object_id), "case_or_combo": case_or_combo, "count": 0, "results": []}

            u1 = float(res[6][0])
            u2 = float(res[7][0])
            u3 = float(res[8][0])
            r1 = float(res[9][0]) if len(res) > 9 else 0.0
            r2 = float(res[10][0]) if len(res) > 10 else 0.0
            r3 = float(res[11][0]) if len(res) > 11 else 0.0

            return {
                "result_type": "displacements",
                "joint": str(object_id),
                "case_or_combo": case_or_combo,
                "count": 1,
                "units": {"translation": length_unit, "rotation": "rad"},
                "displacements": {
                    "U1": u1,
                    "U2": u2,
                    "U3": u3,
                    "R1": r1,
                    "R2": r2,
                    "R3": r3,
                    "resultant_translation": float((u1**2 + u2**2 + u3**2)**0.5),
                },
            }

        elif rtype == "modal":
            res = self._sap_model.Results.ModalPeriod()
            if not res or len(res) < 6 or res[0] <= 0:
                return {"result_type": "modal", "count": 0, "modes": []}

            sum_ux = 0.0
            sum_uy = 0.0
            try:
                mres = self._sap_model.Results.ModalParticipatingMassRatios()
                if mres and len(mres) >= 10 and mres[0] > 0:
                    sum_ux = float(mres[8][-1])
                    sum_uy = float(mres[9][-1])
            except Exception:
                pass

            num_modes = res[0]
            modes = []
            for i in range(num_modes):
                mode_num = int(res[3][i]) if len(res) > 3 else (i + 1)
                period = float(res[4][i]) if len(res) > 4 else 0.0
                freq = float(res[5][i]) if len(res) > 5 else 0.0
                circ_freq = float(res[6][i]) if len(res) > 6 else 0.0
                eigen = float(res[7][i]) if len(res) > 7 else 0.0
                modes.append({
                    "mode": mode_num,
                    "period_s": period,
                    "frequency_hz": freq,
                    "circular_freq_rad_s": circ_freq,
                    "eigenvalue": eigen,
                })

            return {
                "result_type": "modal",
                "count": len(modes),
                "cumulative_mass_ux": round(sum_ux, 4),
                "cumulative_mass_uy": round(sum_uy, 4),
                "sni_90_percent_compliant": (sum_ux >= 0.90 and sum_uy >= 0.90),
                "modes": modes,
            }

        elif rtype == "pushover":
            pts = self._sap_model.PointObj.GetNameList()
            roof_pt = object_id if object_id else (pts[1][-1] if (pts and len(pts) > 1 and len(pts[1]) > 0) else "1")

            rxn = self._sap_model.Results.BaseReact()
            disp = self._sap_model.Results.JointDispl(str(roof_pt), 0)

            curve = []
            num_steps = rxn[0] if (rxn and len(rxn) > 0) else 0
            for i in range(num_steps):
                step_no = int(rxn[3][i]) if len(rxn) > 3 else (i + 1)
                vb = abs(float(rxn[4][i])) if len(rxn) > 4 else 0.0
                u_roof = abs(float(disp[6][i])) if (disp and len(disp) > 6 and len(disp[6]) > i) else 0.0
                curve.append({
                    "step": step_no,
                    "displacement": round(u_roof, 5),
                    "base_shear": round(vb, 2),
                })

            max_vb = max([p["base_shear"] for p in curve]) if curve else 0.0
            max_disp = max([p["displacement"] for p in curve]) if curve else 0.0

            return {
                "result_type": "pushover",
                "case_or_combo": case_or_combo,
                "roof_control_joint": str(roof_pt),
                "total_steps": len(curve),
                "units": {"displacement": length_unit, "base_shear": force_unit},
                "max_base_shear": max_vb,
                "max_roof_displacement": max_disp,
                "capacity_curve": curve,
            }

        elif rtype == "frame_forces" or object_type == "frame":
            if not object_id:
                frames = self._sap_model.FrameObj.GetNameList()
                object_id = frames[1][0] if (frames and len(frames) > 1 and len(frames[1]) > 0) else "1"

            res = self._sap_model.Results.FrameForce(str(object_id), 0)
            if not res or len(res) < 14 or res[0] <= 0:
                return {"result_type": "frame_forces", "frame": str(object_id), "case_or_combo": case_or_combo, "count": 0, "stations": []}

            num_stations = res[0]
            stations = []
            for i in range(num_stations):
                sta_dist = float(res[2][i]) if len(res) > 2 else 0.0
                p = float(res[8][i]) if len(res) > 8 else 0.0
                v2 = float(res[9][i]) if len(res) > 9 else 0.0
                v3 = float(res[10][i]) if len(res) > 10 else 0.0
                t = float(res[11][i]) if len(res) > 11 else 0.0
                m2 = float(res[12][i]) if len(res) > 12 else 0.0
                m3 = float(res[13][i]) if len(res) > 13 else 0.0
                stations.append({
                    "station_distance": sta_dist,
                    "P_axial": p,
                    "V2_shear": v2,
                    "V3_shear": v3,
                    "T_torsion": t,
                    "M2_minor_moment": m2,
                    "M3_major_moment": m3,
                })

            return {
                "result_type": "frame_forces",
                "frame": str(object_id),
                "case_or_combo": case_or_combo,
                "count": len(stations),
                "units": {"force": force_unit, "moment": moment_unit, "distance": length_unit},
                "stations": stations,
            }

        else:
            raise ValueError(f"Unsupported result_type: '{result_type}'. Use 'reactions', 'displacements', 'modal', or 'frame_forces'.")

    def init_structural_model(self, units: str = "kN_m_C", template: str = "blank") -> dict:
        """Initialize a clean new model with explicit units and template."""
        if not self.is_connected:
            raise NotConnectedError("Not connected to SAP2000.", details={"operation": "init_structural_model"})

        reverse_units = {v["name"].lower(): k for k, v in UNITS_MAP.items()}
        reverse_units.update({"kn_m_c": 6, "lb_in_f": 1, "kip_in_f": 3, "kip_ft_f": 4, "n_mm_c": 9, "n_m_c": 10})
        unit_code = reverse_units.get(units.lower().strip(), 6)

        try:
            self._sap_model.SetModelIsLocked(False)
        except Exception:
            pass

        try:
            cur_file = self._sap_model.GetModelFilename(True)
            if cur_file and os.path.exists(cur_file):
                self._sap_model.File.Save(cur_file)
        except Exception:
            pass

        self._sap_model.InitializeNewModel(unit_code)
        ret_new = self._sap_model.File.NewBlank()
        try:
            self._sap_model.View.RefreshView(0, False)
        except Exception:
            pass

        return {
            "success": ret_new == 0,
            "units": units,
            "unit_code": unit_code,
            "template": template,
            "message": f"Initialized new blank structural model with units {units}.",
        }

    def define_material(
        self,
        name: str,
        material_type: str = "steel",
        standard_grade: str | None = None,
        fy_mpa: float | None = None,
        fu_mpa: float | None = None,
        fc_mpa: float | None = None,
        e_mpa: float | None = None,
        unit_weight_kn_m3: float | None = None,
    ) -> dict:
        """Define a structural material with standard library presets or custom mechanical properties.

        Parameters
        ----------
        name : Unique material name (e.g. "A992Fy50", "fc_30MPa", "BJ37", "Rebar_420").
        material_type : "steel", "concrete", or "rebar".
        standard_grade : Optional standard grade identifier from CSI database (e.g. "A992Fy50", "A36", "4000Psi").
        fy_mpa : Yield strength in MPa (for steel/rebar, e.g. 345.0 for A992, 240.0 for BJ37, 420.0 for Rebar).
        fu_mpa : Ultimate tensile strength in MPa (e.g. 450.0).
        fc_mpa : Concrete compressive cylinder strength in MPa (e.g. 30.0).
        e_mpa : Modulus of elasticity in MPa (e.g. 200000.0 for steel, 25742.0 for 30 MPa concrete).
        unit_weight_kn_m3 : Material weight density in kN/m3 (e.g. 78.5 for steel, 24.0 for normal-weight concrete).
        """
        if not self.is_connected:
            raise NotConnectedError("Not connected to SAP2000.", details={"operation": "define_material"})

        mtype = material_type.lower().strip()
        mat_codes = {"steel": 1, "concrete": 2, "rebar": 6, "aluminum": 4, "coldformed": 5}
        mat_code = mat_codes.get(mtype, 1)

        ret = -1
        if standard_grade:
            try:
                ret = self._sap_model.PropMaterial.AddMaterial(
                    name, mat_code, "United States", standard_grade, standard_grade, name
                )
            except Exception:
                ret = -1

        if ret != 0:
            ret = self._sap_model.PropMaterial.SetMaterial(name, mat_code)
            if mtype == "steel":
                e_val = (e_mpa or 200000.0) * 1000.0
                self._sap_model.PropMaterial.SetMPIsotropic(name, e_val, 0.3, 1.17e-5)
                uw = unit_weight_kn_m3 or 78.5
                self._sap_model.PropMaterial.SetWeightAndMass(name, 1, float(uw))
                fy_val = (fy_mpa or 345.0) * 1000.0
                fu_val = (fu_mpa or ((fy_mpa or 345.0) * 1.3)) * 1000.0
                try:
                    self._sap_model.PropMaterial.SetOSteel_1(
                        name, fy_val, fu_val, fy_val * 1.1, fu_val * 1.1, 1, 2, 0.02, 0.15, -0.1
                    )
                except Exception:
                    pass

            elif mtype == "concrete":
                fc = fc_mpa or 30.0
                e_val = (e_mpa or (4700.0 * (fc ** 0.5))) * 1000.0
                self._sap_model.PropMaterial.SetMPIsotropic(name, e_val, 0.2, 9.9e-6)
                uw = unit_weight_kn_m3 or 24.0
                self._sap_model.PropMaterial.SetWeightAndMass(name, 1, float(uw))
                fc_val = fc * 1000.0
                try:
                    self._sap_model.PropMaterial.SetOConcrete_1(
                        name, fc_val, False, 0.0, 1, 2, 0.002, 0.0035, -0.1
                    )
                except Exception:
                    pass

            elif mtype == "rebar":
                fy_val = (fy_mpa or 420.0) * 1000.0
                fu_val = (fu_mpa or 620.0) * 1000.0
                self._sap_model.PropMaterial.SetMPIsotropic(name, 200000.0 * 1000.0, 0.3, 1.17e-5)
                try:
                    self._sap_model.PropMaterial.SetORebar_1(
                        name, fy_val, fu_val, fy_val * 1.1, fu_val * 1.1, 1, 2, 0.02, 0.12, -0.1
                    )
                except Exception:
                    pass

        return {
            "success": ret == 0,
            "material_name": name,
            "material_type": mtype,
            "standard_grade": standard_grade,
            "mechanical_properties": {
                "fy_mpa": fy_mpa or (345.0 if mtype == "steel" else (420.0 if mtype == "rebar" else None)),
                "fc_mpa": fc_mpa or (30.0 if mtype == "concrete" else None),
                "e_mpa": e_mpa or (200000.0 if mtype in ["steel", "rebar"] else (round(4700.0 * ((fc_mpa or 30.0) ** 0.5), 1))),
                "unit_weight_kn_m3": unit_weight_kn_m3 or (78.5 if mtype == "steel" else 24.0),
            },
            "message": f"Defined {mtype} material '{name}' with return code {ret}.",
        }

    def define_frame_section(self, name: str, material: str, shape_type: str, dimensions: dict) -> dict:
        """Define a structural frame cross-section with automatic shape mapping."""
        if not self.is_connected:
            raise NotConnectedError("Not connected to SAP2000.", details={"operation": "define_frame_section"})

        stype = shape_type.lower().strip()
        ret = -1

        if stype in ["i", "wide_flange", "w", "i_section"]:
            t3 = float(dimensions.get("depth", 0.35))
            t2 = float(dimensions.get("flange_width", 0.20))
            tf = float(dimensions.get("flange_thick", 0.015))
            tw = float(dimensions.get("web_thick", 0.010))
            t2b = float(dimensions.get("bottom_flange_width", t2))
            tfb = float(dimensions.get("bottom_flange_thick", tf))
            ret = self._sap_model.PropFrame.SetISection(name, material, t3, t2, tf, tw, t2b, tfb)

        elif stype in ["tube", "box", "hss"]:
            t3 = float(dimensions.get("depth", 0.15))
            t2 = float(dimensions.get("width", dimensions.get("depth", 0.15)))
            tf = float(dimensions.get("thick", 0.010))
            tw = float(dimensions.get("thick", 0.010))
            ret = self._sap_model.PropFrame.SetTube(name, material, t3, t2, tf, tw)

        elif stype in ["rectangle", "rectangular", "rect"]:
            t3 = float(dimensions.get("depth", 0.40))
            t2 = float(dimensions.get("width", 0.30))
            ret = self._sap_model.PropFrame.SetRectangle(name, material, t3, t2)

        elif stype in ["circle", "circular", "round", "pipe"]:
            dia = float(dimensions.get("diameter", 0.30))
            if "thick" in dimensions:
                thick = float(dimensions["thick"])
                ret = self._sap_model.PropFrame.SetPipe(name, material, dia, thick)
            else:
                ret = self._sap_model.PropFrame.SetCircle(name, material, dia)

        else:
            raise ValueError(f"Unsupported shape_type '{shape_type}'. Supported: 'I', 'Tube', 'Rectangle', 'Circle'")

        return {
            "success": ret == 0,
            "section_name": name,
            "material": material,
            "shape_type": shape_type,
            "dimensions": dimensions,
            "message": f"Defined section '{name}' ({shape_type}) with return code {ret}.",
        }

    def batch_create_frames(
        self,
        frames: list[dict],
    ) -> dict:
        """Create multiple structural frame elements with arbitrary 3D spatial geometry.

        Supports ANY building morphology: orthogonal grids, irregular L-shapes, diagonal bracing,
        slanted/inclined columns, cantilevers, pitched roof rafters, and non-orthogonal facades.

        Parameters
        ----------
        frames : List of frame dictionaries:
            [
                {
                    "start": [x1, y1, z1],
                    "end": [x2, y2, z2],
                    "section": "COL_400X400",  # Cross-section name
                    "label": "C1"              # Optional user-assigned member label
                },
                ...
            ]
        """
        if not self.is_connected:
            raise NotConnectedError("Not connected to SAP2000.", details={"operation": "batch_create_frames"})

        created_frames = []
        failed_count = 0

        for f in frames:
            p1 = f.get("start", [0.0, 0.0, 0.0])
            p2 = f.get("end", [0.0, 0.0, 1.0])
            sec = f.get("section", "Default")
            lbl = str(f.get("label", ""))

            x1, y1, z1 = float(p1[0]), float(p1[1]), float(p1[2])
            x2, y2, z2 = float(p2[0]), float(p2[1]), float(p2[2])

            try:
                ret = self._sap_model.FrameObj.AddByCoord(
                    x1, y1, z1, x2, y2, z2, "", sec, lbl
                )
                if ret and (ret[-1] == 0 or ret[-1] == 1):
                    assigned_name = str(ret[0]) if ret[0] else (lbl or f"FRAME_{len(created_frames)+1}")
                    created_frames.append(assigned_name)
                else:
                    failed_count += 1
            except Exception as e:
                logger.warning("FrameObj.AddByCoord failed for %s -> %s: %s", p1, p2, e)
                failed_count += 1

        try:
            self._sap_model.View.RefreshView(0, False)
        except Exception:
            pass

        return {
            "success": len(created_frames) > 0,
            "created_count": len(created_frames),
            "failed_count": failed_count,
            "frame_ids": created_frames,
            "message": f"Successfully created {len(created_frames)} frame members in SAP2000 ({failed_count} failed).",
        }

    def assign_supports(
        self,
        joint_ids: list[str] | None = None,
        support_type: str = "fixed",
        custom_restraints: list[bool] | None = None,
    ) -> dict:
        """Assign boundary support restraints (Fixed, Pinned, Roller) to structural joints.

        Parameters
        ----------
        joint_ids : Explicit list of joint labels to restrain. If omitted or None,
                    automatically detects and restrains all joints at ground level (minimum Z elevation).
        support_type : Boundary condition preset:
                       - "fixed": All 6 DOFs restrained [U1, U2, U3, R1, R2, R3] (moment foundation).
                       - "pinned": Translations restrained [U1, U2, U3], rotations free.
                       - "roller": Vertical translation only [U3] restrained.
                       - "custom": Uses the 6 booleans supplied in custom_restraints.
        custom_restraints : List of 6 booleans [U1, U2, U3, R1, R2, R3] (used when support_type='custom').
        """
        if not self.is_connected:
            raise NotConnectedError("Not connected to SAP2000.", details={"operation": "assign_supports"})

        stype = support_type.lower().strip()
        if stype == "fixed":
            rest_list = [True, True, True, True, True, True]
        elif stype == "pinned":
            rest_list = [True, True, True, False, False, False]
        elif stype == "roller":
            rest_list = [False, False, True, False, False, False]
        elif stype == "custom" and custom_restraints and len(custom_restraints) == 6:
            rest_list = [bool(x) for x in custom_restraints]
        else:
            rest_list = [True, True, True, True, True, True]

        target_joints = []
        if joint_ids is not None:
            target_joints = [str(j) for j in joint_ids]
        else:
            try:
                pts_res = self._sap_model.PointObj.GetNameList()
                pts = list(pts_res[1]) if (pts_res and len(pts_res) > 1 and pts_res[1]) else []
                coords = []
                for p in pts:
                    c = self._sap_model.PointObj.GetCoordCartesian(str(p), 0.0, 0.0, 0.0)
                    if c and len(c) >= 3:
                        coords.append((str(p), float(c[2])))
                if coords:
                    min_z = min([z for _, z in coords])
                    target_joints = [p for p, z in coords if abs(z - min_z) < 0.05]
            except Exception as e:
                logger.warning("Auto base joint detection note: %s", e)

        try:
            self._sap_model.SetModelIsLocked(False)
        except Exception:
            pass

        assigned = []
        for j in target_joints:
            try:
                ret = self._sap_model.PointObj.SetRestraint(str(j), rest_list, 0)
                if ret == 0 or (isinstance(ret, (list, tuple)) and ret[-1] == 0):
                    assigned.append(str(j))
            except Exception:
                pass

        try:
            self._sap_model.View.RefreshView(0, False)
        except Exception:
            pass

        return {
            "success": len(assigned) > 0,
            "support_type": stype,
            "restraints": rest_list,
            "assigned_count": len(assigned),
            "joint_ids": assigned,
            "message": f"Assigned '{stype}' supports to {len(assigned)} joints at base level.",
        }

    def apply_distributed_load(
        self,
        frame_ids: list[str],
        load_pattern: str = "DEAD",
        load_value: float = 0.0,
        direction: str = "gravity",
    ) -> dict:
        """Apply uniform distributed line load to multiple frame members."""
        if not self.is_connected:
            raise NotConnectedError("Not connected to SAP2000.", details={"operation": "apply_distributed_load"})

        try:
            pats = self._sap_model.LoadPatterns.GetNameList()
            pat_names = list(pats[1]) if (pats and len(pats) > 1 and pats[1]) else []
            if load_pattern not in pat_names:
                ptype = 1 if load_pattern.upper() == "DEAD" else 3
                self._sap_model.LoadPatterns.Add(load_pattern, ptype, 0.0, True)
        except Exception:
            pass

        dir_map = {"gravity": 10, "global_z": 6, "global_x": 4, "global_y": 5}
        dir_code = dir_map.get(direction.lower().strip(), 10)

        applied = []
        for fid in frame_ids:
            ret = self._sap_model.FrameObj.SetLoadDistributed(
                str(fid), load_pattern, 1, dir_code, 0.0, 1.0, float(load_value), float(load_value), "Global", True, True, 0
            )
            if ret == 0:
                applied.append(str(fid))

        return {
            "success": len(applied) > 0,
            "applied_count": len(applied),
            "frame_ids": applied,
            "load_pattern": load_pattern,
            "load_value": load_value,
            "direction": direction,
            "message": f"Applied distributed load of {load_value} in direction '{direction}' on {len(applied)} frames.",
        }

    def define_load_combination(
        self,
        name: str,
        combo_type: str = "linear_additive",
        cases: dict[str, float] | None = None,
    ) -> dict:
        """Define a structural design load combination with factored load cases.

        Parameters
        ----------
        name : Unique combination name (e.g. "COMB1_1.2D_1.6L", "COMB2_SEIS_X").
        combo_type : Combination type:
                     - "linear_additive": Standard factored sum (e.g. 1.2D + 1.6L).
                     - "envelope": Peak maximum/minimum envelope across member forces.
                     - "absolute_additive": Absolute sum of member forces.
                     - "srss": Square root of sum of squares.
        cases : Mapping of load pattern/case names to scale factors,
                e.g. {"DEAD": 1.2, "LIVE": 1.6} or {"DEAD": 1.2, "LIVE": 1.0, "RS_X": 1.0}.
        """
        if not self.is_connected:
            raise NotConnectedError("Not connected to SAP2000.", details={"operation": "define_load_combination"})

        ctype_map = {
            "linear_additive": 0,
            "linear": 0,
            "additive": 0,
            "envelope": 1,
            "absolute_additive": 2,
            "absolute": 2,
            "srss": 3,
            "range_additive": 4,
        }
        ctype_code = ctype_map.get(combo_type.lower().strip(), 0)

        try:
            self._sap_model.SetModelIsLocked(False)
        except Exception:
            pass

        ret = self._sap_model.RespCombo.Add(name, ctype_code)

        added_cases = {}
        if cases:
            for cname, factor in cases.items():
                try:
                    ret_load = self._sap_model.RespCombo.SetCaseList(name, 0, str(cname), float(factor))
                    if ret_load == 0 or (isinstance(ret_load, (list, tuple)) and ret_load[-1] == 0):
                        added_cases[str(cname)] = float(factor)
                except Exception as e:
                    logger.warning("Failed setting load case %s in combo %s: %s", cname, name, e)

        return {
            "success": ret == 0,
            "combo_name": name,
            "combo_type": combo_type,
            "type_code": ctype_code,
            "cases_and_factors": added_cases,
            "message": f"Defined load combination '{name}' ({combo_type}) with {len(added_cases)} factored cases.",
        }

    def run_code_design(self, code_type: str = "steel", design_code: str | None = None) -> dict:
        """Run structural code design verification and extract Demand/Capacity ratios."""
        if not self.is_connected:
            raise NotConnectedError("Not connected to SAP2000.", details={"operation": "run_code_design"})

        if not bool(self._sap_model.GetModelIsLocked()):
            self.run_analysis()

        ctype = code_type.lower().strip()
        if ctype == "steel":
            ds = self._sap_model.DesignSteel
            if design_code:
                try:
                    ds.SetCode(design_code)
                except Exception:
                    pass

            try:
                combos = self._sap_model.RespCombo.GetNameList()
                if combos and len(combos) > 1 and combos[1]:
                    for c in combos[1]:
                        ds.SetComboStrength(c, True)
                else:
                    ds.SetComboAutoGenerate(True)
            except Exception:
                pass

            ret = ds.StartDesign()
            try:
                self._sap_model.View.RefreshView(0, False)
            except Exception:
                pass

            frames = self._sap_model.FrameObj.GetNameList()
            frame_names = list(frames[1]) if (frames and len(frames) > 1 and frames[1]) else []

            max_ratio = 0.0
            crit_frame = None
            crit_combo = ""
            results_list = []
            failing_members = []

            for fid in frame_names:
                sum_res = ds.GetSummaryResults(str(fid), 0)
                if sum_res and len(sum_res) >= 6 and sum_res[0] > 0:
                    ratio = float(sum_res[2][0])
                    combo = str(sum_res[5][0]) if len(sum_res) > 5 else ""
                    results_list.append({"frame": str(fid), "dc_ratio": ratio, "combo": combo})
                    if ratio > max_ratio:
                        max_ratio = ratio
                        crit_frame = str(fid)
                        crit_combo = combo
                    if ratio > 1.0:
                        failing_members.append(str(fid))

            status = "PASS" if (max_ratio <= 1.0 and len(results_list) > 0) else ("FAIL" if max_ratio > 1.0 else "NO_RESULTS")
            return {
                "success": ret == 0,
                "code_type": "steel",
                "design_status": status,
                "max_dc_ratio": round(max_ratio, 4),
                "critical_member": crit_frame,
                "critical_combination": crit_combo,
                "total_members_checked": len(results_list),
                "failing_members_count": len(failing_members),
                "failing_members": failing_members[:10],
                "message": f"Steel design check {status}: Maximum D/C ratio = {round(max_ratio, 4)} on Member {crit_frame}.",
            }

        elif ctype == "concrete":
            dc = self._sap_model.DesignConcrete
            ret = dc.StartDesign()
            return {
                "success": ret == 0,
                "code_type": "concrete",
                "message": f"Concrete frame design completed with return code {ret}.",
            }

        else:
            raise ValueError(f"Unsupported code_type '{code_type}'. Use 'steel' or 'concrete'.")

    def apply_wind_load(
        self,
        wind_speed: float = 38.0,
        exposure_category: str = "B",
        direction: str = "X",
        building_height: float | None = None,
        building_width: float | None = None,
        importance_factor: float = 1.0,
        gust_factor: float = 0.85,
        frame_ids: list[str] | None = None,
    ) -> dict:
        """Calculate and apply structural wind load per SNI 1727:2020 / ASCE 7-16.

        Parameters
        ----------
        wind_speed : Basic wind speed V in m/s (e.g. 38 m/s per Indonesian SNI 1727:2020).
        exposure_category : Surface roughness category ("B", "C", or "D"). Default "B" (urban/suburban).
        direction : Lateral wind direction ("X" or "Y").
        building_height : Optional total building height in meters. Auto-detected from coordinates if omitted.
        building_width : Optional windward facade width in meters. Auto-detected if omitted.
        importance_factor : Risk category factor I_w (default 1.0 for Risk Category II).
        gust_factor : Gust-effect factor G (default 0.85 for rigid buildings).
        frame_ids : Specific list of frame labels to receive wind load. If None, auto-selects windward perimeter frames.
        """
        if not self.is_connected:
            raise NotConnectedError("Not connected to SAP2000.", details={"operation": "apply_wind_load"})

        dir_clean = direction.upper().strip()
        if dir_clean not in ["X", "Y"]:
            raise ValueError(f"Unsupported direction '{direction}'. Must be 'X' or 'Y'.")

        exp = exposure_category.upper().strip()
        if exp not in ["B", "C", "D"]:
            exp = "B"

        pts_info = []
        try:
            pts_res = self._sap_model.PointObj.GetNameList()
            pts = list(pts_res[1]) if (pts_res and len(pts_res) > 1 and pts_res[1]) else []
            for p in pts:
                coord = self._sap_model.PointObj.GetCoordCartesian(str(p), 0.0, 0.0, 0.0)
                if coord and len(coord) >= 3:
                    pts_info.append({"name": str(p), "x": float(coord[0]), "y": float(coord[1]), "z": float(coord[2])})
        except Exception as e:
            logger.warning("Could not query joint coordinates: %s", e)

        max_z = max([p["z"] for p in pts_info]) if pts_info else 12.0
        h = building_height if building_height is not None else max_z

        if exp == "B":
            zg, alpha = 365.76, 7.0
        elif exp == "C":
            zg, alpha = 274.32, 9.5
        else:
            zg, alpha = 213.36, 11.5

        z_eval = max(4.57, min(h, zg))
        kz = 2.01 * ((z_eval / zg) ** (2.0 / alpha))
        kzt = 1.0
        kd = 0.85

        qz_pa = 0.613 * kz * kzt * kd * (wind_speed ** 2) * importance_factor
        qz_kpa = qz_pa / 1000.0

        cp_windward = 0.8
        cp_leeward = -0.5
        net_cp = cp_windward - cp_leeward
        design_pressure = qz_kpa * gust_factor * net_cp

        pat_name = f"WIND_{dir_clean}"
        try:
            pats = self._sap_model.LoadPatterns.GetNameList()
            pat_names = list(pats[1]) if (pats and len(pats) > 1 and pats[1]) else []
            if pat_name not in pat_names:
                self._sap_model.LoadPatterns.Add(pat_name, 6, 0.0, True)
        except Exception:
            pass

        target_frames = []
        if frame_ids is not None:
            target_frames = [str(f) for f in frame_ids]
        else:
            try:
                frames_res = self._sap_model.FrameObj.GetNameList()
                all_frames = list(frames_res[1]) if (frames_res and len(frames_res) > 1 and frames_res[1]) else []
                if pts_info and all_frames:
                    coord_dict = {p["name"]: p for p in pts_info}
                    if dir_clean == "X":
                        min_coord = min([p["x"] for p in pts_info])
                        for f in all_frames:
                            pts_f = self._sap_model.FrameObj.GetPoints(str(f), "", "")
                            if pts_f and len(pts_f) >= 2:
                                p1, p2 = str(pts_f[0]), str(pts_f[1])
                                if p1 in coord_dict and p2 in coord_dict:
                                    c1, c2 = coord_dict[p1], coord_dict[p2]
                                    if abs(c1["x"] - min_coord) < 0.05 and abs(c2["x"] - min_coord) < 0.05:
                                        if abs(c1["z"] - c2["z"]) < 0.05 and c1["z"] > 0.1:
                                            target_frames.append(str(f))
                    else:
                        min_coord = min([p["y"] for p in pts_info])
                        for f in all_frames:
                            pts_f = self._sap_model.FrameObj.GetPoints(str(f), "", "")
                            if pts_f and len(pts_f) >= 2:
                                p1, p2 = str(pts_f[0]), str(pts_f[1])
                                if p1 in coord_dict and p2 in coord_dict:
                                    c1, c2 = coord_dict[p1], coord_dict[p2]
                                    if abs(c1["y"] - min_coord) < 0.05 and abs(c2["y"] - min_coord) < 0.05:
                                        if abs(c1["z"] - c2["z"]) < 0.05 and c1["z"] > 0.1:
                                            target_frames.append(str(f))
            except Exception as e:
                logger.warning("Auto perimeter frame detection note: %s", e)

        applied_count = 0
        trib_height = 3.5
        line_load = design_pressure * trib_height
        dir_code = 4 if dir_clean == "X" else 5

        for fid in target_frames:
            try:
                ret = self._sap_model.FrameObj.SetLoadDistributed(
                    str(fid), pat_name, 1, dir_code, 0.0, 1.0, float(line_load), float(line_load), "Global", True, True, 0
                )
                if ret == 0:
                    applied_count += 1
            except Exception:
                pass

        return {
            "success": True,
            "load_pattern": pat_name,
            "standard": "SNI 1727:2020 / ASCE 7-16",
            "exposure_category": exp,
            "direction": dir_clean,
            "wind_speed_m_s": wind_speed,
            "velocity_pressure_kpa": round(qz_kpa, 4),
            "design_pressure_kpa": round(design_pressure, 4),
            "tributary_height_m": trib_height,
            "line_load_kn_m": round(line_load, 3),
            "applied_frames_count": applied_count,
            "applied_frames": target_frames,
            "message": f"Applied {pat_name} wind line load ({round(line_load, 3)} kN/m) to {applied_count} frames.",
        }

    def define_response_spectrum(
        self,
        name: str = "SNI_1726_2019",
        standard: str = "SNI_1726_2019",
        site_class: str = "D",
        ss: float = 0.90,
        s1: float = 0.40,
        r_factor: float = 8.0,
        importance_factor: float = 1.0,
        direction: str = "both",
        damping: float = 0.05,
    ) -> dict:
        """Generate smooth response spectrum function & load cases per SNI 1726:2019 / ASCE 7-16.

        Parameters
        ----------
        name : Name of the response spectrum function (e.g. "SNI_1726_2019").
        standard : Standard code specification ("SNI_1726_2019" or "ASCE7_16").
        site_class : Site classification soil profile ("A", "B", "C", "D", "E"). Default "D" (Tanah Sedang).
        ss : Short-period MCE_R spectral acceleration parameter S_s (g).
        s1 : 1-second MCE_R spectral acceleration parameter S_1 (g).
        r_factor : Response modification coefficient R (e.g. 8.0 for Special Moment Frame).
        importance_factor : Seismic importance factor I_e (default 1.0 for Risk Category II).
        direction : Direction to configure load cases: "X", "Y", or "both".
        damping : Critical damping ratio (default 0.05 = 5%).
        """
        if not self.is_connected:
            raise NotConnectedError("Not connected to SAP2000.", details={"operation": "define_response_spectrum"})

        sc = site_class.upper().strip()
        if sc not in ["A", "B", "C", "D", "E"]:
            sc = "D"

        fa_table = {
            "A": [(0.25, 0.8), (0.50, 0.8), (0.75, 0.8), (1.00, 0.8), (1.25, 0.8)],
            "B": [(0.25, 0.9), (0.50, 0.9), (0.75, 0.9), (1.00, 0.9), (1.25, 0.9)],
            "C": [(0.25, 1.3), (0.50, 1.3), (0.75, 1.2), (1.00, 1.2), (1.25, 1.2)],
            "D": [(0.25, 1.6), (0.50, 1.4), (0.75, 1.2), (1.00, 1.1), (1.25, 1.0)],
            "E": [(0.25, 2.4), (0.50, 1.7), (0.75, 1.3), (1.00, 1.0), (1.25, 0.9)],
        }
        fv_table = {
            "A": [(0.10, 0.8), (0.20, 0.8), (0.30, 0.8), (0.40, 0.8), (0.50, 0.8)],
            "B": [(0.10, 0.8), (0.20, 0.8), (0.30, 0.8), (0.40, 0.8), (0.50, 0.8)],
            "C": [(0.10, 1.5), (0.20, 1.5), (0.30, 1.5), (0.40, 1.5), (0.50, 1.5)],
            "D": [(0.10, 2.4), (0.20, 2.2), (0.30, 2.0), (0.40, 1.9), (0.50, 1.8)],
            "E": [(0.10, 4.2), (0.20, 3.3), (0.30, 2.8), (0.40, 2.4), (0.50, 2.2)],
        }

        def _interp(pts, val):
            if val <= pts[0][0]:
                return pts[0][1]
            if val >= pts[-1][0]:
                return pts[-1][1]
            for i in range(len(pts) - 1):
                x0, y0 = pts[i]
                x1, y1 = pts[i + 1]
                if x0 <= val <= x1:
                    return y0 + (y1 - y0) * (val - x0) / (x1 - x0)
            return pts[-1][1]

        fa = _interp(fa_table[sc], ss)
        fv = _interp(fv_table[sc], s1)

        sms = fa * ss
        sm1 = fv * s1
        sds = (2.0 / 3.0) * sms
        sd1 = (2.0 / 3.0) * sm1

        t0 = 0.2 * sd1 / sds if sds > 0 else 0.05
        ts = sd1 / sds if sds > 0 else 0.50
        tl = 4.0

        periods = [0.0, 0.05, 0.10, round(t0, 4), round((t0 + ts) / 2.0, 4), round(ts, 4)]
        t_curr = ts + 0.1
        while t_curr <= tl + 0.01:
            periods.append(round(t_curr, 4))
            t_curr += 0.2
        periods.extend([round(tl, 4), round(tl + 1.0, 4), round(tl + 2.0, 4)])
        periods = sorted(list(set(periods)))

        sa_vals = []
        for t in periods:
            if t < t0:
                sa = sds * (0.4 + 0.6 * t / t0) if t0 > 0 else sds
            elif t <= ts:
                sa = sds
            elif t <= tl:
                sa = sd1 / t if t > 0 else sds
            else:
                sa = (sd1 * tl) / (t ** 2) if t > 0 else sds
            sa_vals.append(round(sa, 5))

        ret_func = self._sap_model.Func.FuncRS.SetUser(name, len(periods), periods, sa_vals, damping)

        scale_factor = round(9.80665 * float(importance_factor) / float(r_factor), 5)

        created_cases = []
        dir_choice = direction.lower().strip()
        cases_to_build = []
        if dir_choice in ["x", "both"]:
            cases_to_build.append((f"RS_X", "U1"))
        if dir_choice in ["y", "both"]:
            cases_to_build.append((f"RS_Y", "U2"))

        for cname, dof in cases_to_build:
            try:
                self._sap_model.LoadCases.ResponseSpectrum.SetCase(cname)
                self._sap_model.LoadCases.ResponseSpectrum.SetLoads(
                    cname, 1, [dof], [name], [scale_factor], ["Global"], [0.0]
                )
                created_cases.append(cname)
            except Exception as e:
                logger.warning("Failed setting ResponseSpectrum case %s: %s", cname, e)

        return {
            "success": ret_func == 0 or len(created_cases) > 0,
            "function_name": name,
            "standard": standard,
            "site_class": sc,
            "parameters": {
                "Ss": ss,
                "S1": s1,
                "Fa": round(fa, 3),
                "Fv": round(fv, 3),
                "SMS": round(sms, 4),
                "SM1": round(sm1, 4),
                "SDS": round(sds, 4),
                "SD1": round(sd1, 4),
                "T0_sec": round(t0, 4),
                "Ts_sec": round(ts, 4),
                "TL_sec": tl,
                "R_factor": r_factor,
                "importance_factor": importance_factor,
                "scale_factor_m_s2": scale_factor,
            },
            "num_curve_points": len(periods),
            "load_cases_created": created_cases,
            "message": f"Defined Response Spectrum '{name}' ({standard} Site Class {sc}, SDS={round(sds, 3)}g, SD1={round(sd1, 3)}g) with load cases {created_cases}.",
        }

    def run_pushover_analysis(
        self,
        load_case_name: str = "PUSHOVER_X",
        direction: str = "X",
        target_displacement: float = 0.30,
        control_joint: str | None = None,
        initial_gravity_case: str = "PUSH_GRAV",
        max_steps: int = 50,
    ) -> dict:
        """Configure and execute nonlinear static pushover analysis.

        Parameters
        ----------
        load_case_name : Pushover load case identifier (e.g. "PUSHOVER_X").
        direction : Push lateral direction ("X" or "Y").
        target_displacement : Target roof monitored displacement in meters (e.g. 0.30 m).
        control_joint : Monitoring roof joint ID. Auto-detected at max building height if None.
        initial_gravity_case : Non-linear gravity pre-load case name (e.g. "PUSH_GRAV").
        max_steps : Maximum number of incremental load steps to save (default 50).
        """
        if not self.is_connected:
            raise NotConnectedError("Not connected to SAP2000.", details={"operation": "run_pushover_analysis"})

        dir_clean = direction.upper().strip()
        dof_code = 1 if dir_clean == "X" else 2
        load_dir = "UX" if dir_clean == "X" else "UY"

        try:
            self._sap_model.SetModelIsLocked(False)
        except Exception:
            pass

        ctrl_pt = str(control_joint) if control_joint else None
        if not ctrl_pt:
            try:
                pts_res = self._sap_model.PointObj.GetNameList()
                pts = list(pts_res[1]) if (pts_res and len(pts_res) > 1 and pts_res[1]) else []
                best_z = -1e9
                for p in pts:
                    c = self._sap_model.PointObj.GetCoordCartesian(str(p), 0.0, 0.0, 0.0)
                    if c and len(c) >= 3 and float(c[2]) > best_z:
                        best_z = float(c[2])
                        ctrl_pt = str(p)
            except Exception:
                ctrl_pt = "1"
        if not ctrl_pt:
            ctrl_pt = "1"

        # 1. Setup Nonlinear Static Gravity Case
        try:
            self._sap_model.LoadCases.StaticNonlinear.SetCase(initial_gravity_case)
            pats_res = self._sap_model.LoadPatterns.GetNameList()
            pats = list(pats_res[1]) if (pats_res and len(pats_res) > 1 and pats_res[1]) else []
            load_types = []
            load_names = []
            sf_list = []
            if "DEAD" in pats:
                load_types.append("Load")
                load_names.append("DEAD")
                sf_list.append(1.0)
            if "LIVE" in pats:
                load_types.append("Load")
                load_names.append("LIVE")
                sf_list.append(0.25)
            if not load_types:
                load_types.append("Load")
                load_names.append(pats[0] if pats else "DEAD")
                sf_list.append(1.0)

            self._sap_model.LoadCases.StaticNonlinear.SetLoads(
                initial_gravity_case, len(load_types), load_types, load_names, sf_list
            )
            self._sap_model.LoadCases.StaticNonlinear.SetGeometricNonlinearity(initial_gravity_case, 2)
            self._sap_model.LoadCases.StaticNonlinear.SetResultsSaved(initial_gravity_case, False, 1, 1, False)
        except Exception as e:
            logger.warning("Configuring gravity case %s note: %s", initial_gravity_case, e)

        # 2. Setup Lateral Pushover Case
        try:
            self._sap_model.LoadCases.StaticNonlinear.SetCase(load_case_name)
            self._sap_model.LoadCases.StaticNonlinear.SetInitialCase(load_case_name, initial_gravity_case)
            self._sap_model.LoadCases.StaticNonlinear.SetLoads(
                load_case_name, 1, ["Accel"], [load_dir], [1.0]
            )
            self._sap_model.LoadCases.StaticNonlinear.SetLoadApplication(
                load_case_name, 2, 2, float(target_displacement), 1, dof_code, str(ctrl_pt), ""
            )
            self._sap_model.LoadCases.StaticNonlinear.SetResultsSaved(
                load_case_name, True, 5, int(max_steps), False
            )
            self._sap_model.LoadCases.StaticNonlinear.SetGeometricNonlinearity(load_case_name, 2)
        except Exception as e:
            logger.warning("Configuring pushover case %s note: %s", load_case_name, e)

        # 3. Save & Run Analysis
        self.save_model()
        self.run_analysis()

        # 4. Extract Capacity Curve Results
        results = self.get_analysis_results(
            result_type="pushover",
            case_or_combo=load_case_name,
            object_id=str(ctrl_pt),
        )

        curve = results.get("capacity_curve", [])
        v_max = results.get("max_base_shear", 0.0)
        d_max = results.get("max_roof_displacement", 0.0)

        ductility = 1.0
        v_yield = v_max
        d_yield = d_max
        if len(curve) >= 3:
            k0 = curve[1]["base_shear"] / max(curve[1]["displacement"], 1e-6)
            for pt in curve[1:]:
                if pt["displacement"] > 0:
                    secant_k = pt["base_shear"] / pt["displacement"]
                    if secant_k < 0.70 * k0 and pt["base_shear"] >= 0.5 * v_max:
                        v_yield = pt["base_shear"]
                        d_yield = pt["displacement"]
                        break
            if d_yield > 1e-6:
                ductility = round(d_max / d_yield, 2)

        return {
            "success": results.get("total_steps", 0) > 0,
            "pushover_case": load_case_name,
            "control_joint": str(ctrl_pt),
            "direction": dir_clean,
            "target_displacement_m": target_displacement,
            "steps_computed": results.get("total_steps", 0),
            "max_base_shear_kn": v_max,
            "max_roof_displacement_m": d_max,
            "idealized_yield_shear_kn": v_yield,
            "idealized_yield_disp_m": d_yield,
            "structural_ductility_ratio_mu": ductility,
            "capacity_curve": curve,
            "message": f"Pushover analysis completed: Vb_max = {v_max} kN, Roof Disp = {d_max} m, Ductility mu = {ductility}.",
        }

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _model_summary(self) -> dict:
        """Gather rich model info from the live SapModel."""
        info: dict = {}
        try:
            info["model_path"] = self._sap_model.GetModelFilename(True)
        except Exception:
            info["model_path"] = None

        try:
            info["version"] = self._sap_object.GetOAPIVersionNumber()
        except Exception:
            info["version"] = None

        try:
            unit_code = self._sap_model.GetPresentUnits()
            info["units"] = unit_code
            info["units_detail"] = UNITS_MAP.get(unit_code, {"name": f"code_{unit_code}", "force": "unknown", "length": "unknown", "temp": "unknown"})
        except Exception:
            info["units"] = None
            info["units_detail"] = None

        try:
            info["is_locked"] = bool(self._sap_model.GetModelIsLocked())
        except Exception:
            info["is_locked"] = False

        try:
            ret_frame = self._sap_model.FrameObj.Count()
            info["num_frames"] = ret_frame if isinstance(ret_frame, int) else ret_frame[0]
        except Exception:
            info["num_frames"] = None

        try:
            ret_point = self._sap_model.PointObj.Count()
            info["num_points"] = ret_point if isinstance(ret_point, int) else ret_point[0]
        except Exception:
            info["num_points"] = None

        try:
            ret_area = self._sap_model.AreaObj.Count()
            info["num_areas"] = ret_area if isinstance(ret_area, int) else ret_area[0]
        except Exception:
            info["num_areas"] = None

        try:
            pats = self._sap_model.LoadPatterns.GetNameList()
            info["load_patterns"] = list(pats[1]) if (pats and len(pats) > 1 and pats[1]) else []
        except Exception:
            info["load_patterns"] = []

        try:
            combos = self._sap_model.RespCombo.GetNameList()
            info["load_combos"] = list(combos[1]) if (combos and len(combos) > 1 and combos[1]) else []
        except Exception:
            info["load_combos"] = []

        return info


# Module-level singleton so the MCP server and executor share one bridge.
bridge = SapBridge()
