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

