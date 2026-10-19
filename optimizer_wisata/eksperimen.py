"""
Percobaan bertingkat untuk membandingkan ketiga metode secara sah.

Alasan berkas ini ada. Perbandingan sekali jalan dengan satu seed pernah memberi
hasil yang bertolak belakang: pada satu percobaan PSO unggul atas Clarke-Wright,
pada percobaan lain justru sebaliknya. Satu seed tidak cukup untuk menyimpulkan
apa pun tentang metode stokastik, sehingga perbandingannya harus diulang banyak kali.

Dua percobaan:

    Percobaan A, akurasi terhadap optimum.
        Beberapa ukuran subset yang masih dapat diselesaikan Gurobi sampai status
        OPTIMAL. MILP dijalankan sekali karena deterministik, Clarke-Wright sekali
        karena juga deterministik, dan PSO diulang untuk banyak seed. Selisih
        terhadap optimum dihitung dengan Persamaan (2.23), dan hanya sah bila MILP
        benar-benar berstatus OPTIMAL.

    Percobaan B, perilaku pada dataset penuh.
        Seluruh destinasi, tanpa MILP karena jumlah variabel arc-nya terlalu besar.
        Yang dibandingkan hanya PSO terhadap Clarke-Wright.

Seluruh seed dicatat pada keluaran, sesuai batasan rancangan pada Bab I.
"""

import json
import os
import statistics as st
import sys
import time
from datetime import datetime

import clarke_wright as CW
import dataset as DS
import milp_gurobi as MILP
import model as M
import pso as PSO


ANGGARAN = 3_000_000
JUMLAH_HARI = 3
SEED_AWAL = 1
JUMLAH_SEED = 30
UKURAN_SUBSET = (8, 10, 12)
MAKS_HOTEL = 4
BATAS_MILP_DETIK = 180
FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hasil")


def sempitkan(data, P, H):
    """Menyempitkan dataset ke subset tertentu supaya ketiga metode memakai kandidat yang sama."""
    sub = dict(data)
    sub["P"], sub["H"], sub["N"] = P, H, P + H
    sub["s"] = {i: data["s"][i] for i in P}
    sub["u"] = {h: data["u"][h] for h in H}
    sub["s_bar"] = {(i, d): data["s_bar"][i, d] for i in P for d in data["D"]}
    sub["f"] = {i: data["f"][i] for i in P}
    sub["p"] = {h: data["p"][h] for h in H}
    sub["tau"] = {i: data["tau"][i] for i in P}
    sub["jam"] = {i: data["jam"][i] for i in P}
    sub["rho"] = {(i, d): data["rho"][i, d] for i in P for d in data["D"]}
    sub["gamma"] = {i: data["gamma"][i] for i in P}
    sub["kota"] = sorted({data["node"][i]["kota"] for i in P})
    return sub


def _rangkum(nilai):
    if not nilai:
        return {}
    return {
        "n": len(nilai),
        "min": round(min(nilai), 6),
        "maks": round(max(nilai), 6),
        "rata": round(st.mean(nilai), 6),
        "median": round(st.median(nilai), 6),
        "stdev": round(st.pstdev(nilai), 6) if len(nilai) > 1 else 0.0,
    }


def percobaan_a(data, bobot, ukuran=UKURAN_SUBSET, jumlah_seed=JUMLAH_SEED):
    print("Percobaan A: akurasi terhadap optimum")
    print("=" * 86)
    hasil = []

    for n_dest in ukuran:
        P, H = MILP.ambil_subset(data, n_dest, MAKS_HOTEL)
        sub = sempitkan(data, P, H)
        print(f"\nsubset {len(P)} destinasi, {len(H)} akomodasi, {sub['m']} hari")

        m_out = MILP.jalankan_milp(data, ANGGARAN, bobot, maks_destinasi=n_dest,
                                   maks_hotel=MAKS_HOTEL, batas_waktu=BATAS_MILP_DETIK)
        status = m_out["status"]
        z_opt = m_out["hasil"]["Z"] if m_out.get("hasil") else None
        print(f"  MILP    : status {status}, Z {z_opt:.6f}" if z_opt is not None
              else f"  MILP    : status {status}, tanpa solusi")

        c_out = CW.jalankan_cws(sub, ANGGARAN, bobot)
        z_cws = c_out["hasil"]["Z"]

        z_pso, waktu_pso, layak_pso = [], [], 0
        for k in range(jumlah_seed):
            seed = SEED_AWAL + k
            p_out = PSO.jalankan_pso(sub, ANGGARAN, bobot, seed=seed)
            z_pso.append(p_out["hasil"]["Z"])
            waktu_pso.append(p_out["runtime"])
            if p_out["hasil"]["layak"]:
                layak_pso += 1

        # Persamaan (2.23). Hanya sah bila MILP mencapai status OPTIMAL.
        def gap(z):
            if status != "OPTIMAL" or not z_opt:
                return None
            return (z - z_opt) / z_opt * 100.0

        r_pso = _rangkum(z_pso)
        baris = {
            "destinasi": len(P),
            "akomodasi": len(H),
            "status_milp": status,
            "Z_milp": round(z_opt, 6) if z_opt is not None else None,
            "runtime_milp": round(m_out["runtime"], 3),
            "Z_cws": round(z_cws, 6),
            "gap_cws": None if gap(z_cws) is None else round(gap(z_cws), 4),
            "runtime_cws": round(c_out["runtime"], 4),
            "Z_pso": r_pso,
            "gap_pso_rata": None if gap(r_pso["rata"]) is None else round(gap(r_pso["rata"]), 4),
            "gap_pso_terbaik": None if gap(r_pso["min"]) is None else round(gap(r_pso["min"]), 4),
            "pso_capai_optimum": sum(1 for z in z_pso if z_opt and abs(z - z_opt) < 1e-9),
            "pso_layak": f"{layak_pso}/{jumlah_seed}",
            "runtime_pso_rata": round(st.mean(waktu_pso), 3),
        }
        hasil.append(baris)

        print(f"  CWS     : Z {z_cws:.6f}"
              + (f", selisih {gap(z_cws):+.3f} persen" if gap(z_cws) is not None else ""))
        print(f"  PSO x{jumlah_seed} : rata {r_pso['rata']:.6f}  stdev {r_pso['stdev']:.6f}  "
              f"terbaik {r_pso['min']:.6f}  terburuk {r_pso['maks']:.6f}")
        if baris["gap_pso_rata"] is not None:
            print(f"            selisih rata {baris['gap_pso_rata']:+.3f} persen, "
                  f"terbaik {baris['gap_pso_terbaik']:+.3f} persen, "
                  f"mencapai optimum {baris['pso_capai_optimum']} dari {jumlah_seed} seed")
    return hasil


def percobaan_b(data, bobot, jumlah_seed=10):
    print("\n\nPercobaan B: dataset penuh, tanpa MILP")
    print("=" * 86)
    print(f"{len(data['P'])} destinasi, {len(data['H'])} akomodasi, {data['m']} hari")

    c_out = CW.jalankan_cws(data, ANGGARAN, bobot)
    z_cws = c_out["hasil"]["Z"]
    print(f"  CWS     : Z {z_cws:.6f}, runtime {c_out['runtime']:.3f} detik")

    z_pso, waktu = [], []
    for k in range(jumlah_seed):
        p_out = PSO.jalankan_pso(data, ANGGARAN, bobot, seed=SEED_AWAL + k)
        z_pso.append(p_out["hasil"]["Z"])
        waktu.append(p_out["runtime"])
        print(f"    seed {SEED_AWAL + k:3}  Z {p_out['hasil']['Z']:.6f}  "
              f"{p_out['runtime']:.1f} detik")

    r = _rangkum(z_pso)
    menang = sum(1 for z in z_pso if z < z_cws)
    print(f"  PSO x{jumlah_seed} : rata {r['rata']:.6f}  stdev {r['stdev']:.6f}  "
          f"terbaik {r['min']:.6f}")
    print(f"            mengungguli Clarke-Wright pada {menang} dari {jumlah_seed} seed")
    return {"Z_cws": round(z_cws, 6), "runtime_cws": round(c_out["runtime"], 4),
            "Z_pso": r, "pso_menang": f"{menang}/{jumlah_seed}",
            "runtime_pso_rata": round(st.mean(waktu), 3)}


def main():
    mulai = time.perf_counter()
    cepat = "--cepat" in sys.argv
    bobot = M.PROFIL_BOBOT["seimbang"]
    data = DS.muat_dataset(jumlah_hari=JUMLAH_HARI)

    ukuran = (8, 10) if cepat else UKURAN_SUBSET
    n_seed = 10 if cepat else JUMLAH_SEED
    n_seed_b = 5 if cepat else 10

    print(f"dataset   : {os.path.basename(data['data_path'])}")
    print(f"anggaran  : Rp{ANGGARAN:,}   hari: {JUMLAH_HARI}   profil: Seimbang")
    print(f"seed      : {SEED_AWAL} sampai {SEED_AWAL + n_seed - 1}")
    for c in data["catatan"]:
        print(f"catatan   : {c}")
    print()

    a = percobaan_a(data, bobot, ukuran, n_seed)
    b = percobaan_b(data, bobot, n_seed_b)

    os.makedirs(FOLDER, exist_ok=True)
    cap = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(FOLDER, f"eksperimen_{cap}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"dataset": data["data_path"], "anggaran": ANGGARAN,
                   "hari": JUMLAH_HARI, "profil": "seimbang",
                   "seed_awal": SEED_AWAL, "jumlah_seed": n_seed,
                   "percobaan_a": a, "percobaan_b": b},
                  f, indent=2, ensure_ascii=False, default=str)
    print(f"\nhasil disimpan: {path}")
    print(f"total waktu jalan: {time.perf_counter() - mulai:.1f} detik")


if __name__ == "__main__":
    main()
