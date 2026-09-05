"""
Professional Structural Engineering Showcase Script for CSI SAP2000
-------------------------------------------------------------------
Features:
- Live attachment to interactive SAP2000 GUI on Windows
- Parametric 3D Steel Space Frame with Chevron (Inverted-V) Bracing
- ASTM A992 Grade 50 Steel & AISC Profiles (W14x90 columns, W16x40/W12x26 beams, HSS6x6 braces)
- ASCE 7-16 Gravity (Dead, Live) & Lateral Wind Load distribution
- LRFD Load Combinations (1.4D, 1.2D+1.6L, 1.2D+0.5L+1.0W, Envelope)
- Full Finite Element Solver Execution
- Result Extraction: Base Reactions, Roof Lateral Drift, Frame Force Envelopes
- Live GUI 3D Refresh
"""

import os
import sys
import ctypes

def set_desktop_default():
    if sys.platform == "win32":
        try:
            user32 = ctypes.windll.user32
            hDesk = user32.OpenDesktopW("Default", 0, False, 0x1FF)
            if hDesk:
                user32.SetThreadDesktop(hDesk)
                return True
        except Exception as e:
            print(f"Warning: SetThreadDesktop failed: {e}")
    return False

def run_showcase():
    set_desktop_default()
    import comtypes.client

    print("[1/7] Connecting to running SAP2000 instance...")
    helper = comtypes.client.CreateObject("SAP2000v1.Helper")
    try:
        import comtypes.gen.SAP2000v1 as sap_gen
        helper = helper.QueryInterface(sap_gen.cHelper)
    except Exception:
        pass

    set_desktop_default()
    sap_object = helper.GetObject("CSI.SAP2000.API.SapObject")
    if sap_object is None:
        # Fallback via PID
        import subprocess
        out = subprocess.check_output(
            ["tasklist", "/fi", "imagename eq SAP2000.exe", "/fo", "csv", "/nh"],
            text=True, stderr=subprocess.DEVNULL
        )
        for line in out.strip().splitlines():
            parts = [p.strip(' "') for p in line.split(',')]
            if len(parts) >= 2 and parts[0].lower() == "sap2000.exe":
                pid = int(parts[1])
                print(f"  Found SAP2000 PID {pid}, attaching via GetObjectProcess...")
                sap_object = helper.GetObjectProcess("CSI.SAP2000.API.SapObject", pid)
                if sap_object:
                    break

    if sap_object is None:
        raise RuntimeError("Could not connect to running SAP2000 instance!")

    sap_model = sap_object.SapModel
    version = sap_model.GetVersion()
    print(f"  Connected successfully to SAP2000 v{version[0]}!")

    # 1. Initialize Blank Model (Units: 6 = kN_m_C)
    print("\n[2/7] Initializing new 3D structural model (Units: kN, m, C)...")
    sap_model.SetModelIsLocked(False)
    sap_model.InitializeNewModel(6)
    sap_model.File.NewBlank()

    # 2. Define Materials (ASTM A992 Grade 50 Structural Steel)
    print("\n[3/7] Defining Structural Materials & AISC Cross Sections...")
    # MatType: 1 = Steel
    mat_name = "A992_Gr50"
    ret = sap_model.PropMaterial.SetMaterial(mat_name, 1)
    # E = 200,000,000 kN/m2 (200 GPa), nu = 0.30, thermal coeff = 1.17e-5
    sap_model.PropMaterial.SetMPIsotropic(mat_name, 200000000.0, 0.30, 0.0000117)
    # Fy = 344738 kN/m2 (50 ksi = 345 MPa), Fu = 448159 kN/m2 (65 ksi = 450 MPa)
    sap_model.PropMaterial.SetOSteel_1(mat_name, 344738.0, 448159.0, 379212.0, 492975.0, 1, 2, 0.0, 0.0, 0.0, 0.0)

    # AISC Frame Profiles:
    # W14x90 (Columns): depth=0.356, flange_w=0.368, flange_th=0.0180, web_th=0.0112
    col_prop = "W14X90"
    sap_model.PropFrame.SetISection(col_prop, mat_name, 0.356, 0.368, 0.0180, 0.0112, 0.368, 0.0180)

    # W16x40 (X-Dir Primary Girders): depth=0.406, flange_w=0.178, flange_th=0.0128, web_th=0.0077
    bm_x_prop = "W16X40"
    sap_model.PropFrame.SetISection(bm_x_prop, mat_name, 0.406, 0.178, 0.0128, 0.0077, 0.178, 0.0128)

    # W12x26 (Y-Dir Secondary Beams): depth=0.310, flange_w=0.165, flange_th=0.0097, web_th=0.0058
    bm_y_prop = "W12X26"
    sap_model.PropFrame.SetISection(bm_y_prop, mat_name, 0.310, 0.165, 0.0097, 0.0058, 0.165, 0.0097)

    # HSS6x6x3/8 (Chevron Bracing): tube 0.1524m x 0.1524m x 0.0095m
    brk_prop = "HSS6X6X3/8"
    sap_model.PropFrame.SetTube(brk_prop, mat_name, 0.1524, 0.1524, 0.0095, 0.0095)
    print("  Created sections: W14x90 (Cols), W16x40 (Main Girders), W12x26 (Beams), HSS6x6x3/8 (Bracing)")

    # 3. Parametric Geometry
    print("\n[4/7] Generating Parametric 3D Geometry (4 Stories, 2x1 Bays, Chevron Braced)...")
    # Coordinates (meters)
    x_coords = [0.0, 6.0, 12.0]  # 2 bays of 6m
    y_coords = [0.0, 6.0]        # 1 bay of 6m
    z_stories = [0.0, 3.5, 7.0, 10.5, 14.0] # 4 stories of 3.5m

    col_count = 0
    beam_x_count = 0
    beam_y_count = 0
    brace_count = 0

    # A. Create Columns
    for x in x_coords:
        for y in y_coords:
            for s in range(len(z_stories) - 1):
                z1 = z_stories[s]
                z2 = z_stories[s + 1]
                sap_model.FrameObj.AddByCoord(x, y, z1, x, y, z2, "", col_prop)
                col_count += 1

    # B. Create Beams at each elevated level
    for s in range(1, len(z_stories)):
        z = z_stories[s]
        # X-Girders
        for y in y_coords:
            for i in range(len(x_coords) - 1):
                x1 = x_coords[i]
                x2 = x_coords[i + 1]
                sap_model.FrameObj.AddByCoord(x1, y, z, x2, y, z, "", bm_x_prop)
                beam_x_count += 1
        # Y-Beams
        for x in x_coords:
            for j in range(len(y_coords) - 1):
                y1 = y_coords[j]
                y2 = y_coords[j + 1]
                sap_model.FrameObj.AddByCoord(x, y1, z, x, y2, z, "", bm_y_prop)
                beam_y_count += 1

    # C. Create Inverted-V (Chevron) Bracing on outer frames (Y=0 and Y=6)
    # Bay 1 (X=0 to 6) and Bay 2 (X=6 to 12)
    for y in [0.0, 6.0]:
        for s in range(len(z_stories) - 1):
            z_low = z_stories[s]
            z_high = z_stories[s + 1]
            
            # Bay 1 Chevron (Apex at X=3.0)
            sap_model.FrameObj.AddByCoord(0.0, y, z_low, 3.0, y, z_high, "", brk_prop)
            sap_model.FrameObj.AddByCoord(6.0, y, z_low, 3.0, y, z_high, "", brk_prop)
            brace_count += 2
            
            # Bay 2 Chevron (Apex at X=9.0)
            sap_model.FrameObj.AddByCoord(6.0, y, z_low, 9.0, y, z_high, "", brk_prop)
            sap_model.FrameObj.AddByCoord(12.0, y, z_low, 9.0, y, z_high, "", brk_prop)
            brace_count += 2

    print(f"  Model Geometry Created: {col_count} columns, {beam_x_count} X-girders, {beam_y_count} Y-beams, {brace_count} Chevron braces.")
    total_frames = col_count + beam_x_count + beam_y_count + brace_count
    print(f"  Total Frame Elements: {total_frames}")

    # D. Assign Fixed Foundation Restraints at Z=0
    # Restraints: [U1, U2, U3, R1, R2, R3] -> all True for fully fixed
    fixed_restraint = [True, True, True, True, True, True]
    all_points = sap_model.PointObj.GetNameList()
    fixed_count = 0
    for pt in all_points[1]:
        coord = sap_model.PointObj.GetCoordCartesian(pt)
        if abs(coord[2]) < 1e-4:  # Z ~ 0.0
            sap_model.PointObj.SetRestraint(pt, fixed_restraint, 0)
            fixed_count += 1
    print(f"  Assigned fixed support restraints to {fixed_count} foundation base joints.")

    # 4. Define Load Patterns & Apply Loads (ASCE 7-16)
    print("\n[5/7] Defining Load Patterns and Applying Distributed/Lateral Forces...")
    # DEAD pattern already exists. Add LIVE and WIND_X
    # Pattern types: 1 = Dead, 3 = Live, 6 = Wind
    sap_model.LoadPatterns.Add("LIVE", 3, 0.0, True)
    sap_model.LoadPatterns.Add("WIND_X", 6, 0.0, True)

    # Apply Floor Distributed Gravity Loads to all horizontal beams
    # Dead superimposed load = 4.0 kN/m, Live load = 7.5 kN/m
    # Direction: 10 = Gravity (positive downwards)
    all_frames = sap_model.FrameObj.GetNameList()
    floor_beam_count = 0
    for f in all_frames[1]:
        pt1, pt2, _ = sap_model.FrameObj.GetPoints(f)
        c1 = sap_model.PointObj.GetCoordCartesian(pt1)
        c2 = sap_model.PointObj.GetCoordCartesian(pt2)
        if abs(c1[2] - c2[2]) < 1e-4 and c1[2] > 0.1: # Horizontal elevated beam
            # DEAD superimposed load (4 kN/m)
            sap_model.FrameObj.SetLoadDistributed(f, "DEAD", 1, 10, 0.0, 1.0, 4.0, 4.0, "Global", True, True, 0)
            # LIVE load (7.5 kN/m)
            sap_model.FrameObj.SetLoadDistributed(f, "LIVE", 1, 10, 0.0, 1.0, 7.5, 7.5, "Global", True, True, 0)
            floor_beam_count += 1
    print(f"  Applied gravity loads (4 kN/m Dead, 7.5 kN/m Live) across {floor_beam_count} floor beams.")

    # Apply Lateral Wind Point Forces to Windward Joints (X = 0)
    # Story 1 (3.5m): 30 kN, Story 2 (7.0m): 50 kN, Story 3 (10.5m): 70 kN, Story 4 (14.0m): 90 kN
    story_wind = {3.5: 30.0, 7.0: 50.0, 10.5: 70.0, 14.0: 90.0}
    wind_joint_count = 0
    for pt in all_points[1]:
        coord = sap_model.PointObj.GetCoordCartesian(pt)
        if abs(coord[0]) < 1e-4: # X = 0 (windward face)
            for sz, f_wind in story_wind.items():
                if abs(coord[2] - sz) < 1e-3:
                    # Point force: [Fx, Fy, Fz, Mx, My, Mz]
                    # Split force equally between Y=0 and Y=6 columns (each gets half)
                    sap_model.PointObj.SetLoadForce(pt, "WIND_X", [f_wind / 2.0, 0.0, 0.0, 0.0, 0.0, 0.0], False, "Global", 0)
                    wind_joint_count += 1
    print(f"  Applied lateral wind story shear forces at {wind_joint_count} windward column joints.")

    # 5. Define LRFD Design Load Combinations
    print("\n[6/7] Creating ASCE 7 / AISC LRFD Load Combinations...")
    # Combo Type: 0 = Linear Add, 1 = Envelope
    combos = [
        ("COMB1_1.4D", 0, [("DEAD", 1.4)]),
        ("COMB2_1.2D+1.6L", 0, [("DEAD", 1.2), ("LIVE", 1.6)]),
        ("COMB3_1.2D+0.5L+1.0W", 0, [("DEAD", 1.2), ("LIVE", 0.5), ("WIND_X", 1.0)]),
        ("COMB4_0.9D+1.0W", 0, [("DEAD", 0.9), ("WIND_X", 1.0)]),
    ]
    for cname, ctype, cases in combos:
        sap_model.RespCombo.Add(cname, ctype)
        for casename, sf in cases:
            sap_model.RespCombo.SetCaseList(cname, 0, casename, sf)

    # Design Envelope
    sap_model.RespCombo.Add("DESIGN_ENVELOPE", 1) # Envelope type
    for cname, _, _ in combos:
        sap_model.RespCombo.SetCaseList("DESIGN_ENVELOPE", 1, cname, 1.0)
    print("  Created combos: COMB1 (1.4D), COMB2 (1.2D+1.6L), COMB3 (1.2D+0.5L+1.0W), COMB4 (0.9D+1.0W), DESIGN_ENVELOPE")

    # 6. Save Model File & Run Analysis
    save_dir = r"C:\Users\HP\Skills_SAP"
    save_path = os.path.join(save_dir, "Structural_Showcase_Tower.sdb")
    print(f"\n[7/7] Saving model to '{save_path}' and running solver...")
    sap_model.File.Save(save_path)

    # Execute Solver
    ret = sap_model.Analyze.RunAnalysis()
    if ret == 0:
        print("  >>> Solver completed successfully with 0 errors! <<<")
    else:
        print(f"  Solver returned code: {ret}")

    # Refresh 3D GUI View
    sap_model.View.RefreshView(0, False)

    # 7. Extract Structural Results
    print("\n" + "="*70)
    print("           STRUCTURAL ENGINEERING ANALYSIS RESULTS SUMMARY")
    print("="*70)

    # A. Base Reactions under COMB3 (Wind load combination)
    sap_model.Results.Setup.DeselectAllCasesAndCombosForOutput()
    sap_model.Results.Setup.SetComboSelectedForOutput("COMB3_1.2D+0.5L+1.0W")
    res_rxn = sap_model.Results.BaseReact()
    # res_rxn returns: [NumberResults, LoadCase, StepType, StepNum, Fx, Fy, Fz, Mx, My, Mz, ...]
    if len(res_rxn) >= 10 and res_rxn[0] > 0:
        fx = res_rxn[4][0]
        fy = res_rxn[5][0]
        fz = res_rxn[6][0]
        my = res_rxn[8][0]
        print(f"  Base Reactions (COMB3: 1.2D + 0.5L + 1.0W):")
        print(f"    - Total Base Shear (Fx):      {abs(fx):>10.2f} kN (Overturning resisting)")
        print(f"    - Total Gravity Weight (Fz):  {fz:>10.2f} kN")
        print(f"    - Total Overturning Moment:   {abs(my):>10.2f} kN*m")

    # B. Roof Lateral Displacement (Drift)
    sap_model.Results.Setup.DeselectAllCasesAndCombosForOutput()
    sap_model.Results.Setup.SetCaseSelectedForOutput("WIND_X")
    roof_pt = None
    for pt in all_points[1]:
        coord = sap_model.PointObj.GetCoordCartesian(pt)
        if abs(coord[0] - 12.0) < 0.01 and abs(coord[1] - 6.0) < 0.01 and abs(coord[2] - 14.0) < 0.01:
            roof_pt = pt
            break

    if roof_pt:
        disp_res = sap_model.Results.JointDispl(roof_pt, 0)
        # disp_res: [NumberResults, Obj, Elm, LoadCase, StepType, StepNum, U1, U2, U3, R1, R2, R3]
        if len(disp_res) >= 9 and disp_res[0] > 0:
            ux = disp_res[6][0] * 1000.0  # to mm
            height_mm = 14.0 * 1000.0
            drift_ratio = (ux / height_mm) if height_mm > 0 else 0.0
            print(f"\n  Lateral Drift Verification (WIND_X Serviceability):")
            print(f"    - Roof Node:                  Joint #{roof_pt} at (12m, 6m, 14m)")
            print(f"    - Roof Lateral Deflection:    {ux:>10.3f} mm")
            print(f"    - Building Drift Ratio:       1 / {int(1.0/drift_ratio) if drift_ratio > 0 else 'N/A'}")
            allowable_ratio = 1.0 / 400.0
            status = "PASS (Well within H/400 limit)" if drift_ratio <= allowable_ratio else "CHECK REQUIRED"
            print(f"    - ASCE 7 Serviceability Check:{status:>32}")

    # C. Dynamic Modal Natural Frequencies & Periods
    sap_model.Results.Setup.DeselectAllCasesAndCombosForOutput()
    sap_model.Results.Setup.SetCaseSelectedForOutput("MODAL")
    modal_res = sap_model.Results.ModalPeriod()
    # modal_res: [NumberResults, LoadCase, StepType, StepNum, Period, Frequency, CircFreq, EigenVal]
    if len(modal_res) >= 6 and modal_res[0] > 0:
        print(f"\n  Dynamic Modal Characteristics (Free Vibration Modes):")
        for m in range(min(4, modal_res[0])):
            period = modal_res[4][m]
            freq = modal_res[5][m]
            print(f"    - Mode {m+1}: Period T = {period:6.3f} s  |  Natural Frequency f = {freq:6.3f} Hz")

    # D. First Story Column Demand (COMB2: 1.2D + 1.6L)
    sap_model.Results.Setup.DeselectAllCasesAndCombosForOutput()
    sap_model.Results.Setup.SetComboSelectedForOutput("COMB2_1.2D+1.6L")
    f_res = sap_model.Results.FrameForce("1", 0)
    # f_res: [NumberResults, Obj, ObjSta, Elm, ElmSta, LoadCase, StepType, StepNum, P, V2, V3, T, M2, M3]
    if len(f_res) >= 14 and f_res[0] > 0:
        p_axial = abs(f_res[8][0])
        m_major = abs(f_res[13][0])
        print(f"\n  Critical Base Column Demand (Frame #1, COMB2: 1.2D + 1.6L):")
        print(f"    - Factored Axial Force (Pu):  {p_axial:>10.2f} kN")
        print(f"    - Factored Bending Moment (Mu):{m_major:>10.2f} kN*m")

    print("="*70)
    print("\nLive model is active in SAP2000! You can inspect the 3D geometry, deformed shape, and moment diagrams directly on screen.")

if __name__ == "__main__":
    try:
        run_showcase()
    except Exception as exc:
        print(f"\n[ERROR] Execution failed: {exc}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
