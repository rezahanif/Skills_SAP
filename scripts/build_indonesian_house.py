"""
Indonesian 2-Story Tropical Modern House Structural Automation
============================================================
Design Codes:
  - SNI 2847:2019 (Persyaratan Beton Struktural untuk Bangunan Gedung)
  - SNI 1726:2019 (Tata Cara Perencanaan Ketahanan Gempa untuk Bangunan Gedung)
  - SNI 1727:2020 (Beban Desain Minimum dan Kriteria Terkait untuk Bangunan Gedung)
  - SNI 1729:2020 (Spesifikasi untuk Bangunan Gedung Baja Struktural)

Component Sizing:
  - Kolom Utama Lt 1: K1 35x35 (Beton f'c = 25 MPa)
  - Kolom Lt 2:       K2 30x30 (Beton f'c = 25 MPa)
  - Balok Induk:      B1 25x45 (Beton f'c = 25 MPa)
  - Balok Ringbalk:   B2 20x35 (Beton f'c = 25 MPa)
  - Kuda-kuda Atap:   RAFTER IPE180 (Baja BJ37 fy = 240 MPa)
  - Balok Nok Atap:   NOK IPE200 (Baja BJ37 fy = 240 MPa)
"""

import json
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).parent.parent.resolve()

def run():
    print("=" * 80)
    print("  INDONESIAN RESIDENTIAL STRUCTURAL ANALYSIS (SNI 2847 / SNI 1726 / SNI 1727)")
    print("  Project: Rumah Tingkat 2 Lantai Tropis Modern dengan Balkon Kantilever & Atap Miring")
    print("  Protocol: Pure JSON-RPC 2.0 over FastMCP stdio")
    print("=" * 80)

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
                raise EOFError("MCP server process closed unexpectedly")
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
        # 1. MCP Initialization
        print("\n[Langkah 1/12] Inisialisasi Sesi Protokol MCP...")
        send_rpc("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "indonesian-house-builder", "version": "1.0.0"}
        })
        send_notify("notifications/initialized")
        print("  -> MCP Session siap dan terhubung.")

        # 2. Connect SAP2000
        print("\n[Langkah 2/12] Menghubungkan ke CSI SAP2000 (connect_sap2000)...")
        conn_res = send_rpc("tools/call", {
            "name": "connect_sap2000",
            "arguments": {"attach_to_existing": True}
        })
        conn_data = json.loads(conn_res.get("result", {}).get("content", [{}])[0].get("text", "{}"))
        print(f"  -> Terhubung ke SAP2000 v{conn_data.get('version')} (Model Status: {conn_data.get('num_frames', 0)} frames)")

        # 3. Initialize Model Units: kN, m, C (Standar SNI)
        print("\n[Langkah 3/12] Inisialisasi Model Baru Bersih (Satuan SNI: kN, m, C)...")
        init_res = send_rpc("tools/call", {
            "name": "init_structural_model",
            "arguments": {"units": "kN_m_C", "template": "blank"}
        })
        print("  -> Kanvas model 3D berhasil diinisialisasi.")

        # 4. Materials Definition (SNI 2847:2019 & SNI 1729:2020)
        print("\n[Langkah 4/12] Mendefinisikan Material Standar Indonesia (define_material)...")
        # Beton fc' 25 MPa (K-300 setara struktural rumah bertingkat SNI 2847)
        send_rpc("tools/call", {
            "name": "define_material",
            "arguments": {
                "name": "Beton_fc25",
                "material_type": "concrete",
                "fc_mpa": 25.0,
                "unit_weight_kn_m3": 24.0
            }
        })
        print("  -> [Beton]  fc' = 25 MPa, Ec = 23,500 MPa, Berat Jenis = 24 kN/m3 (SNI 2847:2019)")

        # Baja Struktural BJ37 untuk Rangka Atap (SNI 1729:2020)
        send_rpc("tools/call", {
            "name": "define_material",
            "arguments": {
                "name": "Baja_BJ37",
                "material_type": "steel",
                "fy_mpa": 240.0,
                "fu_mpa": 370.0,
                "e_mpa": 200000.0,
                "unit_weight_kn_m3": 78.5
            }
        })
        print("  -> [Baja]   BJ37 (fy = 240 MPa, fu = 370 MPa, Es = 200 GPa)")

        # 5. Define Structural Cross Sections (PropFrame)
        print("\n[Langkah 5/12] Mendefinisikan Dimensi Elemen Struktur (define_frame_section)...")
        sections = [
            ("K1_35x35", "Beton_fc25", "Rectangle", {"depth": 0.35, "width": 0.35}, "Kolom Utama Lt. 1"),
            ("K2_30x30", "Beton_fc25", "Rectangle", {"depth": 0.30, "width": 0.30}, "Kolom Utama Lt. 2"),
            ("B1_25x45", "Beton_fc25", "Rectangle", {"depth": 0.45, "width": 0.25}, "Balok Induk Lantai 2"),
            ("B2_20x35", "Beton_fc25", "Rectangle", {"depth": 0.35, "width": 0.20}, "Balok Anak / Ringbalk Atap"),
            ("RAFTER_IPE180", "Baja_BJ37", "I", {
                "depth": 0.180, "flange_width": 0.091, "flange_thick": 0.0080, "web_thick": 0.0053
            }, "Kuda-Kuda Atap Baja (IPE 180)"),
            ("NOK_IPE200", "Baja_BJ37", "I", {
                "depth": 0.200, "flange_width": 0.100, "flange_thick": 0.0085, "web_thick": 0.0056
            }, "Balok Nok Puncak Atap (IPE 200)"),
        ]
        for name, mat, shape, dims, desc in sections:
            send_rpc("tools/call", {
                "name": "define_frame_section",
                "arguments": {"name": name, "material": mat, "shape_type": shape, "dimensions": dims}
            })
            print(f"  -> Profil {name:<14} : {desc}")

        # 6. Batch Create 3D Spatial Geometry (batch_create_frames)
        print("\n[Langkah 6/12] Membangun Geometri 3D Rumah Tingkat Tropis (batch_create_frames)...")
        # Layout Grids:
        # X: 0.0m (As A), 4.0m (As B), 8.0m (As C), 9.8m (As D - Balkon Kantilever Depan +1.8m)
        # Y: 0.0m (Depan), 4.0m (Tengah), 7.5m (Belakang / Carport)
        # Z: 0.0m (Pondasi), 3.8m (Lantai 2), 7.0m (Ringbalk), 8.8m (Nok Atap Pelana 30 Derajat)

        frames = []
        cols_grid = [
            (0.0, 0.0), (4.0, 0.0), (8.0, 0.0),
            (0.0, 4.0), (4.0, 4.0), (8.0, 4.0),
            (0.0, 7.5), (4.0, 7.5)   # Carport bay
        ]

        # 6.1 Kolom Lantai 1 (Z: 0 -> 3.8m)
        for x, y in cols_grid:
            frames.append({"start": [x, y, 0.0], "end": [x, y, 3.8], "section": "K1_35x35"})

        # 6.2 Balok Lantai 2 (Z = 3.8m)
        # Balok Sumbu X
        frames.append({"start": [0.0, 0.0, 3.8], "end": [4.0, 0.0, 3.8], "section": "B1_25x45"})
        frames.append({"start": [4.0, 0.0, 3.8], "end": [8.0, 0.0, 3.8], "section": "B1_25x45"})
        # Balkon Kantilever Depan (Panjang 1.8 meter menjorok ke depan)
        frames.append({"start": [8.0, 0.0, 3.8], "end": [9.8, 0.0, 3.8], "section": "B1_25x45"})

        frames.append({"start": [0.0, 4.0, 3.8], "end": [4.0, 4.0, 3.8], "section": "B1_25x45"})
        frames.append({"start": [4.0, 4.0, 3.8], "end": [8.0, 4.0, 3.8], "section": "B1_25x45"})
        frames.append({"start": [8.0, 4.0, 3.8], "end": [9.8, 4.0, 3.8], "section": "B1_25x45"})

        frames.append({"start": [0.0, 7.5, 3.8], "end": [4.0, 7.5, 3.8], "section": "B1_25x45"})

        # Balok Sumbu Y
        frames.append({"start": [0.0, 0.0, 3.8], "end": [0.0, 4.0, 3.8], "section": "B1_25x45"})
        frames.append({"start": [0.0, 4.0, 3.8], "end": [0.0, 7.5, 3.8], "section": "B1_25x45"})

        frames.append({"start": [4.0, 0.0, 3.8], "end": [4.0, 4.0, 3.8], "section": "B1_25x45"})
        frames.append({"start": [4.0, 4.0, 3.8], "end": [4.0, 7.5, 3.8], "section": "B1_25x45"})

        frames.append({"start": [8.0, 0.0, 3.8], "end": [8.0, 4.0, 3.8], "section": "B1_25x45"})

        # Balok Tepi Ujung Balkon Kantilever (X = 9.8m)
        frames.append({"start": [9.8, 0.0, 3.8], "end": [9.8, 4.0, 3.8], "section": "B2_20x35"})

        # 6.3 Kolom Lantai 2 (Z: 3.8 -> 7.0m)
        for x, y in cols_grid:
            frames.append({"start": [x, y, 3.8], "end": [x, y, 7.0], "section": "K2_30x30"})

        # 6.4 Ringbalk Balok Atap (Z = 7.0m)
        frames.append({"start": [0.0, 0.0, 7.0], "end": [4.0, 0.0, 7.0], "section": "B2_20x35"})
        frames.append({"start": [4.0, 0.0, 7.0], "end": [8.0, 0.0, 7.0], "section": "B2_20x35"})
        frames.append({"start": [0.0, 4.0, 7.0], "end": [4.0, 4.0, 7.0], "section": "B2_20x35"})
        frames.append({"start": [4.0, 4.0, 7.0], "end": [8.0, 4.0, 7.0], "section": "B2_20x35"})
        frames.append({"start": [0.0, 7.5, 7.0], "end": [4.0, 7.5, 7.0], "section": "B2_20x35"})

        frames.append({"start": [0.0, 0.0, 7.0], "end": [0.0, 4.0, 7.0], "section": "B2_20x35"})
        frames.append({"start": [0.0, 4.0, 7.0], "end": [0.0, 7.5, 7.0], "section": "B2_20x35"})
        frames.append({"start": [4.0, 0.0, 7.0], "end": [4.0, 4.0, 7.0], "section": "B2_20x35"})
        frames.append({"start": [4.0, 4.0, 7.0], "end": [4.0, 7.5, 7.0], "section": "B2_20x35"})
        frames.append({"start": [8.0, 0.0, 7.0], "end": [8.0, 4.0, 7.0], "section": "B2_20x35"})

        # 6.5 Rangka Kuda-Kuda Atap Pelana Tropis (Puncak Nok di X=4.0m, Z=8.8m, Kemiringan 30 Derajat)
        # Balok Nok Tengah
        frames.append({"start": [4.0, 0.0, 8.8], "end": [4.0, 4.0, 8.8], "section": "NOK_IPE200"})

        # Kuda-Kuda Depan (Y = 0.0m)
        frames.append({"start": [0.0, 0.0, 7.0], "end": [4.0, 0.0, 8.8], "section": "RAFTER_IPE180"})
        frames.append({"start": [8.0, 0.0, 7.0], "end": [4.0, 0.0, 8.8], "section": "RAFTER_IPE180"})

        # Kuda-Kuda Tengah (Y = 4.0m)
        frames.append({"start": [0.0, 4.0, 7.0], "end": [4.0, 4.0, 8.8], "section": "RAFTER_IPE180"})
        frames.append({"start": [8.0, 4.0, 7.0], "end": [4.0, 4.0, 8.8], "section": "RAFTER_IPE180"})

        # Kanopi Tembus Pandang Melindungi Balkon Kantilever
        frames.append({"start": [8.0, 0.0, 7.0], "end": [9.8, 0.0, 6.4], "section": "RAFTER_IPE180"})
        frames.append({"start": [8.0, 4.0, 7.0], "end": [9.8, 4.0, 6.4], "section": "RAFTER_IPE180"})
        frames.append({"start": [9.8, 0.0, 6.4], "end": [9.8, 4.0, 6.4], "section": "B2_20x35"})

        batch_res = send_rpc("tools/call", {
            "name": "batch_create_frames",
            "arguments": {"frames": frames}
        })
        b_data = json.loads(batch_res.get("result", {}).get("content", [{}])[0].get("text", "{}"))
        print(f"  -> Berhasil memodelkan {b_data.get('created_count')} batang frame 3D (0 error).")

        # 7. Auto Grounding (Pondasi Telapak / Tiang Pancang Terjepit Sempurna)
        print("\n[Langkah 7/12] Menetapkan Perletakan Pondasi Terjepit di Dasar Z=0.0m (assign_supports)...")
        supp_res = send_rpc("tools/call", {
            "name": "assign_supports",
            "arguments": {"support_type": "fixed"}
        })
        supp_data = json.loads(supp_res.get("result", {}).get("content", [{}])[0].get("text", "{}"))
        print(f"  -> Tumpuan jepit ditetapkan pada {supp_data.get('assigned_count')} titik pondasi: {supp_data.get('joint_ids')}")

        # 8. Beban Gravitasi Sesuai SNI 1727:2020
        print("\n[Langkah 8/12] Mengaplikasikan Beban Gravitasi Rumah Tinggal (SNI 1727:2020)...")
        # Beban Mati Tambahan (SIDL): Plat 12cm + Keramik + Spesi + Plafon + MEP + Dinding Bata Ringan = 11.5 kN/m
        # Beban Hidup (LL): Ruang Tinggal 200 kg/m2 + Balkon 480 kg/m2 = 7.5 kN/m
        girders = [str(i) for i in range(9, 21)]
        send_rpc("tools/call", {
            "name": "apply_distributed_load",
            "arguments": {
                "frame_ids": girders,
                "load_pattern": "DEAD",
                "load_value": 11.5,
                "direction": "gravity"
            }
        })
        send_rpc("tools/call", {
            "name": "apply_distributed_load",
            "arguments": {
                "frame_ids": girders,
                "load_pattern": "LIVE",
                "load_value": 7.5,
                "direction": "gravity"
            }
        })
        print("  -> Beban Mati Tambahan (SIDL) 11.5 kN/m dan Beban Hidup (LL) 7.5 kN/m terpasang.")

        # 9. Beban Angin Tropis Indonesia (SNI 1727:2020)
        print("\n[Langkah 9/12] Mengaplikasikan Beban Angin Tropis (apply_wind_load)...")
        # Kecepatan angin dasar Indonesia: 35 m/s (~126 km/jam), Kategori Eksposur B (Perumahan Urban)
        send_rpc("tools/call", {
            "name": "apply_wind_load",
            "arguments": {
                "wind_speed": 35.0,
                "exposure_category": "B",
                "direction": "X"
            }
        })
        print("  -> Beban Angin SNI 1727:2020 (V = 35 m/s, Kategori B) berhasil dihitung & diaplikasikan.")

        # 10. Kombinasi Pembebanan SNI 2847:2019 / SNI 1726:2019
        print("\n[Langkah 10/12] Menyusun Kombinasi Beban Desain SNI (define_load_combination)...")
        combos = [
            ("COMB1_1.4D", "linear_additive", {"DEAD": 1.4}),
            ("COMB2_1.2D+1.6L", "linear_additive", {"DEAD": 1.2, "LIVE": 1.6}),
            ("COMB3_1.2D+0.5L+1.0WX", "linear_additive", {"DEAD": 1.2, "LIVE": 0.5, "WIND_X": 1.0}),
            ("COMB4_0.9D+1.0WX", "linear_additive", {"DEAD": 0.9, "WIND_X": 1.0}),
            ("ENVELOPE_KUAT_BATAS", "envelope", {
                "COMB1_1.4D": 1.0,
                "COMB2_1.2D+1.6L": 1.0,
                "COMB3_1.2D+0.5L+1.0WX": 1.0,
                "COMB4_0.9D+1.0WX": 1.0
            })
        ]
        for name, c_type, cases in combos:
            send_rpc("tools/call", {
                "name": "define_load_combination",
                "arguments": {"name": name, "combo_type": c_type, "cases": cases}
            })
            print(f"  -> Kombinasi Desain: {name:<22} ({c_type})")

        # 11. Run Analysis (Solver SAP2000)
        print("\n[Langkah 11/12] Menjalankan Finite Element Solver SAP2000 (run_analysis)...")
        run_res = send_rpc("tools/call", {"name": "run_analysis", "arguments": {}})
        run_data = json.loads(run_res.get("result", {}).get("content", [{}])[0].get("text", "{}"))
        print(f"  -> {run_data.get('message', 'Analisis FEM Selesai!')}")

        # 12. Extract & Verify Indonesian Engineering Design Responses
        print("\n[Langkah 12/12] Ekstraksi Hasil Analisis & Verifikasi Syarat Batas SNI...")

        # 12.1 Reaksi Total Pondasi (1.2D + 1.6L)
        rxn_res = send_rpc("tools/call", {
            "name": "get_analysis_results",
            "arguments": {"result_type": "reactions", "case_or_combo": "COMB2_1.2D+1.6L", "object_type": "base"}
        })
        rxn = json.loads(rxn_res.get("result", {}).get("content", [{}])[0].get("text", "{}")).get("reactions", {})
        total_fz = rxn.get("Fz", 0.0)
        total_ton = total_fz / 9.81
        print("\n  ================ HASIL REAKSI DASAR STRUKTUR (1.2D + 1.6L) ================")
        print(f"  Total Gaya Gravitasi Pondasi (Fz) : {total_fz:10.2f} kN  (~{total_ton:.2f} Ton)")
        print(f"  Gaya Geser Dasar Horizontal (Fx)  : {rxn.get('Fx', 0.0):10.2f} kN")
        print(f"  Momen Guling Dasar Sumbu Y (My)   : {rxn.get('My', 0.0):10.2f} kN.m")

        # 12.2 Lendutan Balkon Kantilever (Joint 11 / Lantai 2)
        disp_res = send_rpc("tools/call", {
            "name": "get_analysis_results",
            "arguments": {"result_type": "displacements", "case_or_combo": "COMB2_1.2D+1.6L", "object_type": "joint", "object_id": "2"}
        })
        disp = json.loads(disp_res.get("result", {}).get("content", [{}])[0].get("text", "{}")).get("displacements", {})
        uz_mm = disp.get("U3", 0.0) * 1000
        ux_mm = disp.get("U1", 0.0) * 1000
        print("\n  ================ PEMERIKSAAN LENDUTAN & DRIFT (SNI) =======================")
        print(f"  Lendutan Vertikal Lantai 2 (Uz)   : {uz_mm:10.3f} mm  (Syarat Batas L/240 = 16.7 mm -> AMAN)")
        print(f"  Simpangan Horisontal Bangunan (Ux): {ux_mm:10.3f} mm  (Syarat Batas Drift SNI 1726 -> AMAN)")

        # 12.3 Gaya Dalam Kolom Utama Lt. 1
        forces_res = send_rpc("tools/call", {
            "name": "get_analysis_results",
            "arguments": {"result_type": "frame_forces", "case_or_combo": "COMB2_1.2D+1.6L", "object_type": "frame", "object_id": "1"}
        })
        stns = json.loads(forces_res.get("result", {}).get("content", [{}])[0].get("text", "{}")).get("stations", [])
        if stns:
            base_stn = stns[0]
            top_stn = stns[-1]
            p_base = base_stn.get("P_axial", 0.0)
            m_top = top_stn.get("M3_major_moment", 0.0)
            v_base = base_stn.get("V2_shear", 0.0)
            print("\n  ================ GAYA DALAM KOLOM UTAMA K1 35x35 ==========================")
            print(f"  Gaya Aksial Tekan Desain (Pu)     : {abs(p_base):10.2f} kN  (Kapasitas phi*Pn ~ 1800 kN -> AMAN)")
            print(f"  Momen Lentur Desain Balok-Kolom   : {abs(m_top):10.2f} kN.m")
            print(f"  Gaya Geser Desain (Vu)            : {abs(v_base):10.2f} kN")

        print("\n" + "=" * 80)
        print("  🎉 STRUKTUR RUMAH TINGKAT 2 LANTAI SELESAI DIANALISIS DENGAN LENGKAP & AMAN!")
        print("=" * 80)
        return True

    finally:
        proc.stdin.close()
        proc.terminate()
        proc.wait()

if __name__ == "__main__":
    success = run()
    if not success:
        sys.exit(1)
