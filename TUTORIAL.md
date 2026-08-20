# CSI SAP2000 Connection Setup Guide

### 1. Prerequisites
- CSI SAP2000 (v20 through v25) installed on your Windows machine.
- SAP2000 COM API registered (done automatically during standard SAP2000 installation).
- AiConnect Gateway running on loopback port `8788`.

### 2. Connect to SAP2000
1. Open **CSI SAP2000** on your Windows desktop.
2. Open an existing structural model (`.sdb`) or initialize a new model.
3. In **AiConnect Desktop**, navigate to **MCP Collection** and click **Enable** on the **SAP2000 Connector**.
4. The connector connects via Windows COM automation to the active SAP2000 instance.

### 3. Verify Connection in AiConnect Desktop
1. Return to **AiConnect Desktop**.
2. The **SAP2000 Connector** card status will indicate `● Connected`.
3. Your AI agent (Antigravity AGY, Claude Code, Cursor) can now model beams, assign loads, run FEM solvers, and retrieve reaction forces automatically.
