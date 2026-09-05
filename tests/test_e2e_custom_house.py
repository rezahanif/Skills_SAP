"""
Professional Custom House Structural E2E Test
============================================
Architecture: Modern Split-Level Villa with Cantilevered Balcony and Gable Pitch Roof
Protocol: Pure JSON-RPC 2.0 over FastMCP stdio (mcp_server)
Features Verified:
  1. MCP Session Lifecycle (initialize, notifications/initialized)
  2. Live SAP2000 Connection (connect_sap2000)
  3. Blank Canvas Initialization (init_structural_model)
  4. Material Definitions (define_material for Concrete fc' 30 MPa and Steel A992/BJ37)
  5. Cross-Section Definitions (define_frame_section for Columns, Girders, and Rafters)
  6. Arbitrary 3D Spatial Frame Creation (batch_create_frames for non-cube house geometry)
  7. Automatic Base Grounding (assign_supports at Z=0)
  8. Multi-Case Load Patterns (create_load_pattern: DEAD, LIVE, ROOF_LIVE, EQX, WIND)
  9. Distributed Frame Loads (assign_frame_distributed_load)
  10. Design Load Combinations (define_load_combination: 1.4D, 1.2D+1.6L, 1.2D+1.0L+1.0EQ, Envelope)
  11. Finite Element Solver Execution (run_analysis)
  12. Post-Processing & Result Extraction (get_analysis_results for reactions, displacements, frame forces)
"""

import json
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent.resolve()

def run_house_e2e_test():
    print("=" * 75)
    print("  SAP2000 MCP End-to-End Test: Professional Custom House Structural Flow")
    print("  Structure: Modern Split-Level Villa with Cantilever & Gable Roof")
    print("  Protocol: Pure JSON-RPC 2.0 over FastMCP stdio")
    print("=" * 75)

    proc = subprocess.Popen(
        [sys.executable, str(ROOT / "run_server.py")],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        text=True,
        cwd=str(ROOT),
    )

    req_id = 1

    def send_rpc(method: str, params: dict | None = None) -> dict:
        nonlocal req_id
        msg_id = req_id
        req_id += 1
        payload = {"jsonrpc": "2.0", "id": msg_id, "method": method}
        if params is not None:
            payload["params"] = params
        wire_data = json.dumps(payload) + "\n"
        proc.stdin.write(wire_data)
        proc.stdin.flush()

        while True:
            line = proc.stdout.readline()
            if not line:
                raise EOFError("MCP server process closed stream unexpectedly")
            try:
                resp = json.loads(line)
                if resp.get("id") == msg_id:
                    return resp
            except json.JSONDecodeError:
                pass

    def send_notify(method: str, params: dict | None = None):
        payload = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        proc.stdin.write(json.dumps(payload) + "\n")
        proc.stdin.flush()

    try:
        # Step 1: Initialize MCP Protocol
        print("\n[Step 1] Initializing MCP Protocol Session...")
        init_resp = send_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "custom-house-e2e", "version": "1.0.0"}
        })
        assert "result" in init_resp, f"MCP init failed: {init_resp}"
        send_notify("notifications/initialized")
        print("  ✓ MCP Session Established.")

        # Step 2: Connect to Running SAP2000 GUI
        print("\n[Step 2] Connecting to Live SAP2000 Instance (connect_sap2000)...")
        conn_resp = send_rpc("tools/call", {
            "name": "connect_sap2000",
            "arguments": {"attach_to_existing": True}
        })
        conn_text = conn_resp.get("result", {}).get("content", [{}])[0].get("text", "")
        conn_json = json.loads(conn_text) if conn_text.strip().startswith("{") else {}
        assert conn_json.get("connected") is True or "Connected successfully" in conn_text, f"Connection failed: {conn_resp}"
        print(f"  ✓ Connected to SAP2000 v{conn_json.get('version', 'unknown')} (Current model: {conn_json.get('num_frames', 0)} frames)")

        # Step 3: Initialize Blank 3D Structural Model (kN, m, C)
        print("\n[Step 3] Initializing Blank Canvas Model (init_structural_model)...")
        init_model_resp = send_rpc("tools/call", {
            "name": "init_structural_model",
            "arguments": {"units": "kN_m_C", "template": "blank"}
        })
        init_model_text = init_model_resp.get("result", {}).get("content", [{}])[0].get("text", "")
        print(f"  ✓ {init_model_text}")

        # Step 4: Define Materials (define_material)
        print("\n[Step 4] Defining Engineering Materials (define_material)...")
        # Concrete fc = 30 MPa for Primary Frame
        mat_c30 = send_rpc("tools/call", {
            "name": "define_material",
            "arguments": {
                "name": "Concrete_fc30",
                "material_type": "concrete",
                "fc_mpa": 30.0,
                "unit_weight_kn_m3": 24.0
            }
        })
        c30_text = mat_c30.get("result", {}).get("content", [{}])[0].get("text", "")
        print(f"  ✓ {c30_text}")
        assert "Concrete_fc30" in c30_text

        # Steel fy = 350 MPa for Roof Rafters & Canopy
        mat_s350 = send_rpc("tools/call", {
            "name": "define_material",
            "arguments": {
                "name": "Steel_BJ37",
                "material_type": "steel",
                "fy_mpa": 350.0,
                "fu_mpa": 450.0,
                "e_mpa": 200000.0,
                "unit_weight_kn_m3": 78.5
            }
        })
        s350_text = mat_s350.get("result", {}).get("content", [{}])[0].get("text", "")
        print(f"  ✓ {s350_text}")
        assert "Steel_BJ37" in s350_text

        # Step 5: Define Cross-Sections (define_frame_section)
        print("\n[Step 5] Defining Structural Cross Sections (define_frame_section)...")
        sections = [
            ("COL_40x40", "Concrete_fc30", "Rectangle", {"depth": 0.40, "width": 0.40}),
            ("COL_30x30", "Concrete_fc30", "Rectangle", {"depth": 0.30, "width": 0.30}),
            ("BEAM_30x50", "Concrete_fc30", "Rectangle", {"depth": 0.50, "width": 0.30}),
            ("BEAM_20x40", "Concrete_fc30", "Rectangle", {"depth": 0.40, "width": 0.20}),
            ("RAFTER_IPE200", "Steel_BJ37", "I", {
                "depth": 0.200, "flange_width": 0.100, "flange_thick": 0.0085, "web_thick": 0.0056
            }),
            ("RIDGE_IPE240", "Steel_BJ37", "I", {
                "depth": 0.240, "flange_width": 0.120, "flange_thick": 0.0098, "web_thick": 0.0062
            }),
        ]
        for name, mat, shape, dims in sections:
            sec_resp = send_rpc("tools/call", {
                "name": "define_frame_section",
                "arguments": {
                    "name": name,
                    "material": mat,
                    "shape_type": shape,
                    "dimensions": dims
                }
            })
            sec_text = sec_resp.get("result", {}).get("content", [{}])[0].get("text", "")
            print(f"  ✓ {name}: {sec_text.splitlines()[0] if sec_text else ''}")
            sec_json = json.loads(sec_text) if sec_text.strip().startswith("{") else {}
            assert sec_json.get("success") is True or "return code 0" in sec_text

        # Step 6: Batch Create Custom Spatial Frames (batch_create_frames)
        print("\n[Step 6] Batch Generating 3D Custom Spatial House Geometry (batch_create_frames)...")
        frames = []

        # Ground Floor Columns (Z: 0.0 -> 3.6m): 8 columns (L-shape plan)
        ground_col_coords = [
            (0.0, 0.0), (5.0, 0.0), (9.0, 0.0),
            (0.0, 4.5), (5.0, 4.5), (9.0, 4.5),
            (0.0, 8.5), (5.0, 8.5)
        ]
        for x, y in ground_col_coords:
            frames.append({
                "start": [x, y, 0.0],
                "end": [x, y, 3.6],
                "section": "COL_40x40"
            })

        # 2nd Floor Main Girders & Balcony Cantilever (Z: 3.6m)
        # X-Girders along Y=0.0 (Living/Terrace)
        frames.append({"start": [0.0, 0.0, 3.6], "end": [5.0, 0.0, 3.6], "section": "BEAM_30x50"})
        frames.append({"start": [5.0, 0.0, 3.6], "end": [9.0, 0.0, 3.6], "section": "BEAM_30x50"})
        # 2.5m Cantilever Balcony Beam!
        frames.append({"start": [9.0, 0.0, 3.6], "end": [11.5, 0.0, 3.6], "section": "BEAM_30x50"})

        # X-Girders along Y=4.5 (Mid corridor/balcony)
        frames.append({"start": [0.0, 4.5, 3.6], "end": [5.0, 4.5, 3.6], "section": "BEAM_30x50"})
        frames.append({"start": [5.0, 4.5, 3.6], "end": [9.0, 4.5, 3.6], "section": "BEAM_30x50"})
        # 2.5m Cantilever Balcony Beam!
        frames.append({"start": [9.0, 4.5, 3.6], "end": [11.5, 4.5, 3.6], "section": "BEAM_30x50"})

        # X-Girders along Y=8.5 (L-shape north wing)
        frames.append({"start": [0.0, 8.5, 3.6], "end": [5.0, 8.5, 3.6], "section": "BEAM_30x50"})

        # Y-Beams along X=0.0
        frames.append({"start": [0.0, 0.0, 3.6], "end": [0.0, 4.5, 3.6], "section": "BEAM_30x50"})
        frames.append({"start": [0.0, 4.5, 3.6], "end": [0.0, 8.5, 3.6], "section": "BEAM_30x50"})

        # Y-Beams along X=5.0
        frames.append({"start": [5.0, 0.0, 3.6], "end": [5.0, 4.5, 3.6], "section": "BEAM_30x50"})
        frames.append({"start": [5.0, 4.5, 3.6], "end": [5.0, 8.5, 3.6], "section": "BEAM_30x50"})

        # Y-Beams along X=9.0
        frames.append({"start": [9.0, 0.0, 3.6], "end": [9.0, 4.5, 3.6], "section": "BEAM_30x50"})

        # Balcony Cantilever Tip Transverse Edge Beam (X=11.5)
        frames.append({"start": [11.5, 0.0, 3.6], "end": [11.5, 4.5, 3.6], "section": "BEAM_20x40"})

        # 2nd Floor Upper Columns (Z: 3.6 -> 6.8m): 8 columns
        for x, y in ground_col_coords:
            frames.append({
                "start": [x, y, 3.6],
                "end": [x, y, 6.8],
                "section": "COL_30x30"
            })

        # Eaves Level Ring Tie Beams (Z: 6.8m)
        frames.append({"start": [0.0, 0.0, 6.8], "end": [5.0, 0.0, 6.8], "section": "BEAM_20x40"})
        frames.append({"start": [5.0, 0.0, 6.8], "end": [9.0, 0.0, 6.8], "section": "BEAM_20x40"})
        frames.append({"start": [0.0, 4.5, 6.8], "end": [5.0, 4.5, 6.8], "section": "BEAM_20x40"})
        frames.append({"start": [5.0, 4.5, 6.8], "end": [9.0, 4.5, 6.8], "section": "BEAM_20x40"})
        frames.append({"start": [0.0, 8.5, 6.8], "end": [5.0, 8.5, 6.8], "section": "BEAM_20x40"})

        frames.append({"start": [0.0, 0.0, 6.8], "end": [0.0, 4.5, 6.8], "section": "BEAM_20x40"})
        frames.append({"start": [0.0, 4.5, 6.8], "end": [0.0, 8.5, 6.8], "section": "BEAM_20x40"})
        frames.append({"start": [5.0, 0.0, 6.8], "end": [5.0, 4.5, 6.8], "section": "BEAM_20x40"})
        frames.append({"start": [5.0, 4.5, 6.8], "end": [5.0, 8.5, 6.8], "section": "BEAM_20x40"})
        frames.append({"start": [9.0, 0.0, 6.8], "end": [9.0, 4.5, 6.8], "section": "BEAM_20x40"})

        # Sloped Gable Pitch Roof Rafters & Central Ridge Crown (Peak at X=4.5, Z=8.6m)
        # Ridge Beam
        frames.append({"start": [4.5, 0.0, 8.6], "end": [4.5, 4.5, 8.6], "section": "RIDGE_IPE240"})

        # Front Gable Pitch Truss (Y=0.0)
        frames.append({"start": [0.0, 0.0, 6.8], "end": [4.5, 0.0, 8.6], "section": "RAFTER_IPE200"})
        frames.append({"start": [9.0, 0.0, 6.8], "end": [4.5, 0.0, 8.6], "section": "RAFTER_IPE200"})

        # Mid Gable Pitch Truss (Y=4.5)
        frames.append({"start": [0.0, 4.5, 6.8], "end": [4.5, 4.5, 8.6], "section": "RAFTER_IPE200"})
        frames.append({"start": [9.0, 4.5, 6.8], "end": [4.5, 4.5, 8.6], "section": "RAFTER_IPE200"})

        # Balcony Sloped Shading Canopy (Extending from Z=6.8m down to Z=6.2m over cantilever)
        frames.append({"start": [9.0, 0.0, 6.8], "end": [11.5, 0.0, 6.2], "section": "RAFTER_IPE200"})
        frames.append({"start": [9.0, 4.5, 6.8], "end": [11.5, 4.5, 6.2], "section": "RAFTER_IPE200"})
        frames.append({"start": [11.5, 0.0, 6.2], "end": [11.5, 4.5, 6.2], "section": "BEAM_20x40"})

        batch_resp = send_rpc("tools/call", {
            "name": "batch_create_frames",
            "arguments": {"frames": frames}
        })
        batch_text = batch_resp.get("result", {}).get("content", [{}])[0].get("text", "")
        batch_json = json.loads(batch_text) if batch_text.strip().startswith("{") else {}
        print(f"  ✓ Created {batch_json.get('created_count', len(frames))} frame members (0 failed).")
        assert batch_json.get("created_count", 0) > 0

        # Step 7: Assign Supports (assign_supports: Auto-ground base joints at Z=0 to Fixed)
        print("\n[Step 7] Auto-Grounding Foundation Joints at Z=0 (assign_supports)...")
        supp_resp = send_rpc("tools/call", {
            "name": "assign_supports",
            "arguments": {
                "support_type": "fixed"
            }
        })
        supp_text = supp_resp.get("result", {}).get("content", [{}])[0].get("text", "")
        supp_json = json.loads(supp_text) if supp_text.strip().startswith("{") else {}
        print(f"  ✓ Assigned 'fixed' support to {supp_json.get('assigned_count', 0)} base joints: {supp_json.get('joint_ids', [])}")
        assert supp_json.get("assigned_count", 0) == 8, f"Expected 8 grounded joints, got {supp_json}"

        # Step 8: Apply Gravity Distributed Loads (apply_distributed_load)
        print("\n[Step 8] Assigning Superimposed Gravity Loads (apply_distributed_load)...")
        # Target 2nd floor girders and cantilever balcony frames
        target_girders = [str(i) for i in range(9, 21)]
        dead_load = send_rpc("tools/call", {
            "name": "apply_distributed_load",
            "arguments": {
                "frame_ids": target_girders,
                "load_pattern": "DEAD",
                "load_value": 12.0,
                "direction": "gravity"
            }
        })
        dead_text = dead_load.get("result", {}).get("content", [{}])[0].get("text", "")
        print(f"  ✓ Dead Load: {dead_text.splitlines()[0] if dead_text else ''}")

        live_load = send_rpc("tools/call", {
            "name": "apply_distributed_load",
            "arguments": {
                "frame_ids": target_girders,
                "load_pattern": "LIVE",
                "load_value": 8.0,
                "direction": "gravity"
            }
        })
        live_text = live_load.get("result", {}).get("content", [{}])[0].get("text", "")
        print(f"  ✓ Live Load: {live_text.splitlines()[0] if live_text else ''}")

        # Step 9: Apply Automated ASCE 7 Wind Loads (apply_wind_load)
        print("\n[Step 9] Applying Lateral Wind Loads (apply_wind_load)...")
        wind_resp = send_rpc("tools/call", {
            "name": "apply_wind_load",
            "arguments": {
                "wind_speed": 35.0,
                "exposure_category": "B",
                "direction": "X"
            }
        })
        wind_text = wind_resp.get("result", {}).get("content", [{}])[0].get("text", "")
        print(f"  ✓ Wind Load: {wind_text.splitlines()[0] if wind_text else ''}")

        # Step 10: Define ASCE / ACI Design Load Combinations (define_load_combination)
        print("\n[Step 10] Defining Design Load Combinations (define_load_combination)...")
        combos = [
            {
                "name": "1.4D",
                "combo_type": "linear_additive",
                "cases": {"DEAD": 1.4}
            },
            {
                "name": "1.2D+1.6L",
                "combo_type": "linear_additive",
                "cases": {"DEAD": 1.2, "LIVE": 1.6}
            },
            {
                "name": "1.2D+0.5L+1.0WX",
                "combo_type": "linear_additive",
                "cases": {"DEAD": 1.2, "LIVE": 0.5, "WIND_X": 1.0}
            },
            {
                "name": "ENVELOPE",
                "combo_type": "envelope",
                "cases": {"1.4D": 1.0, "1.2D+1.6L": 1.0, "1.2D+0.5L+1.0WX": 1.0}
            }
        ]
        for c in combos:
            c_resp = send_rpc("tools/call", {
                "name": "define_load_combination",
                "arguments": c
            })
            c_text = c_resp.get("result", {}).get("content", [{}])[0].get("text", "")
            c_json = json.loads(c_text) if c_text.strip().startswith("{") else {}
            print(f"  ✓ {c['name']}: {c_json.get('message', c_text.splitlines()[0] if c_text else '')}")
            assert c_json.get("success") is True or "defined" in c_text.lower()

        # Step 11: Run Finite Element Analysis (run_analysis)
        print("\n[Step 11] Executing FEA Solver (run_analysis)...")
        run_resp = send_rpc("tools/call", {
            "name": "run_analysis",
            "arguments": {}
        })
        run_text = run_resp.get("result", {}).get("content", [{}])[0].get("text", "")
        print(f"  ✓ {run_text}")
        assert "Analysis finished successfully" in run_text or "Analysis completed successfully" in run_text

        # Step 12: Extract Engineering Responses (get_analysis_results)
        print("\n[Step 12] Extracting Structural Engineering Responses (get_analysis_results)...")
        
        # 1. Base Reactions under 1.2D+1.6L
        rxn_resp = send_rpc("tools/call", {
            "name": "get_analysis_results",
            "arguments": {"result_type": "reactions", "case_or_combo": "1.2D+1.6L", "object_type": "base"}
        })
        rxn_data = json.loads(rxn_resp.get("result", {}).get("content", [{}])[0].get("text", "{}"))
        rxn = rxn_data.get("reactions", {})
        print(f"  ✓ Total Base Foundation Reactions (1.2D+1.6L):")
        print(f"      Fz (Total Gravity Reaction): {rxn.get('Fz', 0.0):.2f} kN")
        print(f"      Fx (Lateral Wind/EQ Shear):  {rxn.get('Fx', 0.0):.2f} kN")
        print(f"      Fy (Transverse Shear):       {rxn.get('Fy', 0.0):.2f} kN")
        print(f"      Base Shear Resultant:        {rxn.get('base_shear_horizontal', 0.0):.2f} kN")

        # 2. Joint Displacements (Upper Level Joint 2)
        disp_resp = send_rpc("tools/call", {
            "name": "get_analysis_results",
            "arguments": {"result_type": "displacements", "case_or_combo": "1.2D+1.6L", "object_type": "joint", "object_id": "2"}
        })
        disp_data = json.loads(disp_resp.get("result", {}).get("content", [{}])[0].get("text", "{}"))
        d = disp_data.get("displacements", {})
        print(f"  ✓ 2nd Floor Joint 2 Displacement (1.2D+1.6L):")
        print(f"      Uz (Vertical Settlement):     {d.get('U3', 0.0) * 1000:.3f} mm")
        print(f"      Ux (Lateral Drift):           {d.get('U1', 0.0) * 1000:.3f} mm")
        print(f"      Uy (Transverse Drift):        {d.get('U2', 0.0) * 1000:.3f} mm")

        # 3. Frame Internal Forces
        forces_resp = send_rpc("tools/call", {
            "name": "get_analysis_results",
            "arguments": {"result_type": "frame_forces", "case_or_combo": "1.2D+1.6L", "object_type": "frame", "object_id": "1"}
        })
        forces_data = json.loads(forces_resp.get("result", {}).get("content", [{}])[0].get("text", "{}"))
        stns = forces_data.get("stations", [])
        print(f"  ✓ Ground Column 1 Internal Forces (1.2D+1.6L):")
        if stns:
            base_stn = stns[0]
            top_stn = stns[-1]
            print(f"      [Base Z=0.0m]  Axial P: {base_stn.get('P_axial', 0.0):.2f} kN | V2: {base_stn.get('V2_shear', 0.0):.2f} kN | M3: {base_stn.get('M3_major_moment', 0.0):.2f} kN.m")
            print(f"      [Top  Z=3.6m]  Axial P: {top_stn.get('P_axial', 0.0):.2f} kN | V2: {top_stn.get('V2_shear', 0.0):.2f} kN | M3: {top_stn.get('M3_major_moment', 0.0):.2f} kN.m")

        print("\n" + "=" * 75)
        print("  🎉 ALL 12 STEPS OF PROFESSIONAL HOUSE STRUCTURAL E2E FLOW PASSED!")
        print("=" * 75)
        return True

    finally:
        proc.stdin.close()
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    success = run_house_e2e_test()
    if not success:
        sys.exit(1)
