"""
Menghitung ulang Lampiran 3, simulasi pada dataset rekayasa delapan node.

Lampiran lama memakai fungsi objektif tiga suku tanpa suku kerugian mutu akomodasi
dan tanpa normalisasi, sehingga tidak lagi sesuai dengan Persamaan (2.1). Berkas ini
menyusun ulang dataset rekayasanya dan menjalankan ketiga metode dengan model yang
berlaku sekarang.

Dua penyesuaian terhadap Tabel L3.1 lama:
    1. H1 diberi harga kamar dan skor utilitas. Pada model sekarang malam ke-1 adalah
       malam menjelang hari pertama dan ikut dibayar, sehingga hotel awal tidak dapat
       lagi dibiarkan tanpa harga.
    2. H2 diberi skor utilitas, karena Persamaan (2.1c) membutuhkannya.

Saklar cuaca sengaja dinyalakan di sini, meskipun nilai bawaannya mati, supaya
Persamaan (2.2) tetap dapat diperagakan sebagaimana lampiran versi lama.
"""
import json
import os
import time
from datetime import date

import clarke_wright as CW
import milp_gurobi as MILP
import model as M
import pso as PSO

ANGGARAN = 1_500_000
HARI = 2
BETA = 280.0            # kuota waktu aktivitas harian, Tabel L3.2
MENIT_PER_KM = 10.0     # satu satuan koordinat setara satu kilometer
KBBM, HBBM = 12.0, 10_000.0
CUACA_AKTIF = 1

# id, peran, kota, (x, y), kategori, keterpaparan, skor, tiket atau harga, skor utilitas
NODE = [
    ("H1", "akomodasi", "Semarang",       (0, 0),  "",        "indoor",  None, 400_000, 7.0),
    ("D1", "destinasi", "Semarang",       (1, 3),  "Sejarah", "indoor",  9.0,  20_000,  None),
    ("D2", "destinasi", "Semarang",       (3, 1),  "Sejarah", "mixed",   6.5,  10_000,  None),
    ("D3", "destinasi", "Semarang",       (5, 3),  "Alam",    "outdoor", 8.5,  0,       None),
    ("H2", "akomodasi", "Surakarta/Solo", (10, 0), "",        "indoor",  None, 500_000, 8.5),
    ("D4", "destinasi", "Surakarta/Solo", (9, 2),  "Sejarah", "indoor",  8.8,  15_000,  None),
    ("D5", "destinasi", "Surakarta/Solo", (12, 1), "Alam",    "mixed",   8.0,  0,       None),
    ("D6", "destinasi", "Surakarta/Solo", (11, 4), "Alam",    "outdoor", 6.8,  5_000,   None),
]
RHO = {("Semarang", 1): 0.20, ("Semarang", 2): 0.30,
       ("Surakarta/Solo", 1): 0.50, ("Surakarta/Solo", 2): 0.60}
GAMMA = {"indoor": 0.0, "mixed": 0.5, "outdoor": 1.0}


def bangun():
    node, koor = {}, {}
    P, H = [], []
    for nid, peran, kota, xy, kat, sifat, skor, harga, util in NODE:
        koor[nid] = xy
        node[nid] = {
            "id": nid, "nama": nid, "peran": peran, "kota": kota, "kategori": kat,
            "tier": "", "lat": xy[1], "lon": xy[0], "jam_buka_teks": "",
            "tiket": float(harga) if peran == "destinasi" else 0.0,
            "harga_malam": float(harga) if peran == "akomodasi" else 0.0,
            "durasi": 60.0 if peran == "destinasi" else 0.0,
            "sifat": sifat, "gamma": GAMMA[sifat],
            "rating": 0.0, "skala": 5.0, "ulasan": 0, "mu": 0.0, "pi": 0.0,
            "skor": float(skor if skor is not None else util),
            "sumber_resmi": "", "tier_resmi": "",
        }
        (P if peran == "destinasi" else H).append(nid)

    N = P + H
    delta, t_mat, g = {}, {}, {}
    for a in N:
        for b in N:
            km = ((koor[a][0] - koor[b][0]) ** 2 + (koor[a][1] - koor[b][1]) ** 2) ** 0.5
            delta[a, b] = km
            t_mat[a, b] = round(km * MENIT_PER_KM)
            g[a, b] = km / KBBM * HBBM

    D = list(range(1, HARI + 1))
    rho = {(i, d): RHO[(node[i]["kota"], d)] for i in P for d in D}
    s_bar = {(i, d): node[i]["skor"] * (1.0 - CUACA_AKTIF * node[i]["gamma"] * rho[i, d])
             for i in P for d in D}

    return {
        "data_path": "dataset rekayasa Lampiran 3", "P": P, "H": H, "N": N, "node": node,
        "m": HARI, "D": D, "tanggal": [date(2026, 11, 10), date(2026, 11, 11)],
        "kota": sorted({node[i]["kota"] for i in P}),
        "kategori": sorted({node[i]["kategori"] for i in P}),
        "s": {i: node[i]["skor"] for i in P}, "u": {h: node[h]["skor"] for h in H},
        "s_bar": s_bar, "rho": rho, "gamma": {i: node[i]["gamma"] for i in P},
        "f": {i: node[i]["tiket"] for i in P}, "p": {h: node[h]["harga_malam"] for h in H},
        "tau": {i: node[i]["durasi"] for i in P},
        "jam": {i: (0, 24 * 60) for i in P},
        "delta": delta, "t": t_mat, "g": g,
        "v_ref": 0, "cuaca_aktif": CUACA_AKTIF, "catatan": [],
    }


def main():
    M.BETA = BETA
    import dataset as DS
    DS.KECEPATAN_ANTARKOTA_KMJAM = 60.0 / MENIT_PER_KM   # 6 km per jam pada skala rekayasa
    DS.KBBM, DS.HBBM = KBBM, HBBM

    data = bangun()
    bobot = M.PROFIL_BOBOT["seimbang"]

    print("=" * 84)
    print("SKOR TERKOREKSI CUACA, Persamaan (2.2) dengan saklar menyala")
    print("=" * 84)
    print("  node  sifat      skor  gamma   rho h1   s h1   rho h2   s h2")
    for i in data["P"]:
        n = data["node"][i]
        print(f"  {i:5} {n['sifat']:8} {n['skor']:>5.1f} {n['gamma']:>6.1f} "
              f"{data['rho'][i, 1]:>8.2f} {data['s_bar'][i, 1]:>6.2f} "
              f"{data['rho'][i, 2]:>8.2f} {data['s_bar'][i, 2]:>6.2f}")

    print()
    print("=" * 84)
    print("BATAS TIAP SUKU, Persamaan (2.1b), (2.1d), (2.1f), dan (2.1h)")
    print("=" * 84)
    batas = M.batas_komponen(data, ANGGARAN)
    for k in M.SUKU:
        lo, hi = batas[k]
        print(f"  {k:5} minimum {lo:>12,.2f}   maksimum {hi:>12,.2f}   rentang {hi - lo:>12,.2f}")

    hasil = {}
    t0 = time.time()
    hasil["Mixed Integer Linear Programming"] = (
        MILP.jalankan_milp(data, ANGGARAN, bobot, batas_waktu=120), time.time() - t0)
    t0 = time.time()
    hasil["Clarke-Wright Savings"] = (CW.jalankan_cws(data, ANGGARAN, bobot), time.time() - t0)
    t0 = time.time()
    hasil["Particle Swarm Optimization"] = (
        PSO.jalankan_pso(data, ANGGARAN, bobot, seed=42), time.time() - t0)

    z_opt = M.nilai_objektif(
        data, hasil["Mixed Integer Linear Programming"][0]["solusi"], ANGGARAN, bobot)["Z"]

    print()
    print("=" * 84)
    print("TABEL L3.7 BARU, nilai fungsi objektif")
    print("=" * 84)
    print("  metode                                 L_P    L_H         C_H       C_T"
          "         Z     gap")
    ringkas = {}
    for nama, (out, detik) in hasil.items():
        h = M.nilai_objektif(data, out["solusi"], ANGGARAN, bobot)
        gap = (h["Z"] - z_opt) / abs(z_opt) * 100 if z_opt else 0.0
        print(f"  {nama:34} {h['L_P']:>7.2f} {h['L_H']:>6.2f} {h['C_H']:>11,.0f} "
              f"{h['C_T']:>9,.0f} {h['Z']:>9.5f} {gap:>6.2f}%")
        ringkas[nama] = {
            "L_P": h["L_P"], "L_H": h["L_H"], "C_H": h["C_H"], "C_T": h["C_T"],
            "topi": h["topi"], "Z": h["Z"], "gap_persen": gap, "detik": detik,
            "rute": {str(d): out["solusi"]["rute"][d] for d in data["D"]},
            "hotel": {str(d): out["solusi"]["hotel"][d] for d in data["D"]},
            "pilih": [i for i in data["P"] if out["solusi"]["pilih"].get(i)],
        }

    print()
    print("=" * 84)
    print("TABEL L3.3 SAMPAI L3.5 BARU, rute tiap metode")
    print("=" * 84)
    for nama, (out, _) in hasil.items():
        sol = out["solusi"]
        print(f"\n  {nama}")
        for d in data["D"]:
            print(f"    hari {d}: " + " -> ".join(sol["rute"][d]))
        print("    akomodasi: " + ", ".join(f"malam {d} = {sol['hotel'][d]}" for d in data["D"]))
        print(f"    tidak dipilih: {sorted(set(data['P']) - set(ringkas[nama]['pilih']))}")

    berkas = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hasil", "lampiran3_baru.json")
    with open(berkas, "w", encoding="utf-8") as fh:
        json.dump({"batas": {k: list(v) for k, v in batas.items()},
                   "anggaran": ANGGARAN, "hari": HARI, "beta": BETA,
                   "cuaca_aktif": CUACA_AKTIF, "hasil": ringkas}, fh, indent=2, ensure_ascii=False)
    print(f"\n  tersimpan: {berkas}")


if __name__ == "__main__":
    main()
