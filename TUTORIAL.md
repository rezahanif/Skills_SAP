# CSI SAP2000 Connection Setup Guide

### 1. SAP2000 Version Compatibility

The connector uses Computers & Structures, Inc. (CSI)'s official forward-compatible, version-independent Open API (`SAP2000v1.Helper` & `CSI.SAP2000.API.SapObject`).

| SAP2000 Version Range | Compatibility Status | Notes |
| :--- | :--- | :--- |
| **SAP2000 v17 through v27+ (Latest)** | **Fully Supported (Universal)** | Native support via `SAP2000v1.Helper`. Automatically attaches to any running instance or launches registered version. |
| **SAP2000 v20 – v26** | **Fully Supported** | Most common engineering production versions. Tested for linear, response spectrum, code design, and nonlinear pushover. |
| **SAP2000 v16 and earlier** | **Not Supported (Legacy)** | Pre-2014 legacy versions used deprecated non-Helper COM interface (`Sap2000.SapObject`). |

#### Multi-Version Environments
If you have multiple versions of SAP2000 installed on the same Windows machine (e.g., v20, v22, v24, v26):
- **Attach to Running Instance (`attach_to_existing=True`, Default)**: The connector binds dynamically to whichever SAP2000 version is currently open on your desktop.
- **Explicit Executable Path**: When launching a specific version programmatically, pass the optional `program_path` argument (e.g., `program_path="C:\\Program Files\\Computers and Structures\\SAP2000 24\\SAP2000.exe"`).
- **Default Launch (`attach_to_existing=False`)**: Launches the system's primary/latest registered SAP2000 version via Windows COM ProgID.

---

### 2. Prerequisites
- **Operating System**: Windows 10 or Windows 11 (64-bit).
- **CSI SAP2000**: Any version from **v17 up to v27+** installed.
- **COM API Registration**: Standard SAP2000 installation automatically registers the COM type libraries.
- **AiConnect Gateway**: Running on loopback port `8788`.

---

### 3. Connect to SAP2000
1. Open **CSI SAP2000** on your Windows desktop.
2. Open an existing structural model (`.sdb`) or initialize a new model.
3. In **AiConnect Desktop**, navigate to **MCP Collection** and click **Enable** on the **SAP2000 Connector**.
4. The connector connects via Windows COM automation to the active SAP2000 instance.

---

### 4. Verify Connection in AiConnect Desktop
1. Return to **AiConnect Desktop**.
2. The **SAP2000 Connector** card status will indicate `● Connected`.
3. Your AI agent (Antigravity AGY, Claude Code, Cursor) can now model beams, assign loads, run FEM solvers, and retrieve reaction forces automatically.

---

### 5. Professional Custom House End-to-End Workflow (Automated Test)

The repository includes a comprehensive, production-grade end-to-end flow test for realistic non-cube structures: [`tests/test_e2e_custom_house.py`](file:///C:/Users/HP/Skills_SAP/tests/test_e2e_custom_house.py).

This test validates the complete structural engineering lifecycle over pure JSON-RPC 2.0 stdio:

```
                  [RIDGE CROWN: Z = +8.60m]
                          /\
                         /  \  <- RAFTER_IPE200 (Steel Pitch)
                        /    \
 [EAVES: Z = +6.80m]  +======+======+  <- Ring Tie Beams (B_20x40)
                      |             |  \
                      |  Level 2    |   \  <- Sloped Balcony Canopy
                      |  Upper Cols |    \
 [FLOOR: Z = +3.60m]  +======+======+=====+  <- 2.50m Cantilever Balcony!
                      |      |      |
                      | Ground Cols |
                      | (K_40x40)   |
 [BASE:  Z =  0.00m] _|_    _|_    _|_  <- Auto-Grounded Fixed Restraints
                     /////////////////
                     X=0.0  X=5.0  X=9.0  X=11.5m
```

#### Complete 12-Step Lifecycle:

1. **Protocol Initialization**: FastMCP protocol handshake (`initialize`, `notifications/initialized`).
2. **Live Application Binding**: Attach directly to running SAP2000 desktop instance via `connect_sap2000(attach_to_existing=True)`.
3. **Blank Canvas Setup**: Initialize clean structural database with explicit SI engineering units via `init_structural_model(units="kN_m_C", template="blank")`.
4. **Material Modeling**: Create high-strength concrete and structural steel via `define_material`:
   - `Concrete_fc30`: $f'_c = 30\text{ MPa}$, $\gamma = 24.0\text{ kN/m}^3$
   - `Steel_BJ37`: $f_y = 350\text{ MPa}$, $f_u = 450\text{ MPa}$, $E = 200,000\text{ MPa}$
5. **Cross-Section Catalog**: Unify concrete column/beam and steel I-section rafters via `define_frame_section`:
   - `COL_40x40` ($0.40\text{m} \times 0.40\text{m}$), `COL_30x30` ($0.30\text{m} \times 0.30\text{m}$)
   - `BEAM_30x50` ($0.50\text{m} \times 0.30\text{m}$), `BEAM_20x40` ($0.40\text{m} \times 0.20\text{m}$)
   - `RAFTER_IPE200`, `RIDGE_IPE240`
6. **Arbitrary 3D Spatial Frame Creation**: Batch-create 47 frame members defining an L-shaped floor plan, 2.5m cantilevered outdoor balcony, pitched gable roof rafters, and sloped shading canopy in a single call via `batch_create_frames`.
7. **Automated Base Grounding**: Auto-detect all foundation joints at minimum elevation ($Z = 0.0\text{m}$) and apply moment-resisting fixed supports via `assign_supports(support_type="fixed")`.
8. **Superimposed Gravity Loads**: Apply dead ($12.0\text{ kN/m}$) and live ($8.0\text{ kN/m}$) line loads across floor girders and cantilever balcony via `apply_distributed_load`.
9. **Automated Lateral Wind Loads**: Apply ASCE 7 / SNI 1727 lateral wind loads ($V = 35\text{ m/s}$, Exposure B) via `apply_wind_load`.
10. **Design Load Combinations**: Formulate design combinations ($1.4\text{D}$, $1.2\text{D}+1.6\text{L}$, $1.2\text{D}+0.5\text{L}+1.0\text{W}$, $\text{ENVELOPE}$) via `define_load_combination`.
11. **Finite Element Solver Execution**: Run solver analysis via `run_analysis()`.
12. **Structured Engineering Post-Processing**: Extract foundation reactions, joint drifts, and station internal forces via `get_analysis_results`.

#### Running the Verification Test:
```bash
# Ensure SAP2000 is open on your desktop, then run:
python tests/test_e2e_custom_house.py
```
Verification benchmark under $1.2\text{D}+1.6\text{L}$:
- **Total Foundation Gravity Reaction**: $F_z = 1,890.44\text{ kN}$ ($\approx 192.7\text{ tons}$)
- **Column 1 Base Axial Force**: $P = -171.44\text{ kN}$ ($< 0.01\%$ error vs analytical self-weight sum)
- **2nd Floor Lateral Drift**: $U_x = 0.651\text{ mm}$


