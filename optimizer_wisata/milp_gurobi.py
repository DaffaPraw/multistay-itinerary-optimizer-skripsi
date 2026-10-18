"""
Mixed Integer Linear Programming dengan Gurobi, acuan solusi optimal.

Formulasinya mengikuti subbab 2.4. Hanya metode ini yang memakai pustaka
penyelesai; PSO dan Clarke-Wright ditulis sendiri supaya perbandingannya adil.

Variabel arc tumbuh |N|^2 dikali jumlah hari, jadi hanya dijalankan pada subset
kecil yang diambil dari destinasi berskor tertinggi per kota. Ukurannya diatur
lewat maks_destinasi dan maks_hotel.

Enam variabel keputusan mengikuti Tabel 2.9, tidak ada tambahan:

    v[i]        biner, 1 jika destinasi i dipilih untuk dikunjungi
    y[i,d]      biner, 1 jika destinasi i dikunjungi pada hari d
    z[h,d]      biner, 1 jika menginap di akomodasi h pada malam ke-d
    x[u,v,d]    biner, 1 jika arc dari u ke v dilalui pada hari d
    a_tiba[i,d] kontinu >= 0, waktu kedatangan di destinasi i pada hari d
    q[i,d]      kontinu >= 0, urutan kunjungan untuk pencegahan subtour

Yang ada di berkas ini baru variabel dan objektif. Batasan (2.6) sampai (2.18)
belum ada, jadi solusi model tahap ini belum bermakna.
"""

import model as M

try:
    import gurobipy as gp
    from gurobipy import GRB
except ImportError as exc:  # pragma: no cover
    raise ImportError("Paket gurobipy dibutuhkan untuk metode MILP.") from exc


BATAS_WAKTU_DETIK = 300
BIG_M = 10_000.0
MAKS_DESTINASI = 12
MAKS_HOTEL = 4


def ambil_subset(data, maks_destinasi=MAKS_DESTINASI, maks_hotel=MAKS_HOTEL):
    """Mengambil subset seimbang antar kota, destinasi dan akomodasi berskor tertinggi."""
    node = data["node"]
    kota = data["kota"]
    per_kota_d = max(1, maks_destinasi // len(kota))
    per_kota_h = max(1, maks_hotel // len(kota))

    P, H = [], []
    for k in kota:
        calon_d = sorted((i for i in data["P"] if node[i]["kota"] == k),
                         key=lambda i: -data["s"][i])
        P.extend(calon_d[:per_kota_d])
        calon_h = sorted((h for h in data["H"] if node[h]["kota"] == k),
                         key=lambda h: data["p"][h])
        H.extend(calon_h[:per_kota_h])
    return sorted(P), sorted(H)


def bangun_model(data, anggaran, bobot, P, H):
    """Model, variabel keputusan, dan fungsi objektif (2.1). Batasan belum dipasang."""
    M.periksa_bobot(bobot)
    u, p, g, s_bar = data["u"], data["p"], data["g"], data["s_bar"]
    D = data["D"]
    N = P + H

    mdl = gp.Model("itinerary_multistay")
    mdl.Params.OutputFlag = 0
    mdl.Params.TimeLimit = BATAS_WAKTU_DETIK

    # Seluruh pasangan berarah pada N. Arc akomodasi ke akomodasi tetap disertakan
    # karena hari tanpa kunjungan menghasilkan arc itu, sesuai subbab 2.4.
    arc = [(a, b) for a in N for b in N if a != b]

    v = mdl.addVars(P, vtype=GRB.BINARY, name="v")
    y = mdl.addVars(P, D, vtype=GRB.BINARY, name="y")
    z = mdl.addVars(H, D, vtype=GRB.BINARY, name="z")
    x = mdl.addVars(arc, D, vtype=GRB.BINARY, name="x")
    a_tiba = mdl.addVars(P, D, lb=0.0, ub=24 * 60, vtype=GRB.CONTINUOUS, name="a")
    q = mdl.addVars(P, D, lb=1.0, ub=max(1, len(P)), vtype=GRB.CONTINUOUS, name="q")

    # ---------------- fungsi objektif, Persamaan (2.1)
    # Biaya tiket masuk sengaja bukan suku objektif. Subbab 2.4 menyatakan tiket
    # menentukan kelayakan anggaran dan bukan peringkat mutu, jadi tempatnya di
    # batasan (2.17).
    suku = {
        "L_P": gp.quicksum(10.0 - gp.quicksum(s_bar[i, d] * y[i, d] for d in D) for i in P),
        "L_H": gp.quicksum((10.0 - u[h]) * z[h, d] for h in H for d in D),
        "C_H": gp.quicksum(p[h] * z[h, d] for h in H for d in D),
        "C_T": gp.quicksum(g[a, b] * x[a, b, d] for (a, b) in arc for d in D),
    }

    # Normalisasi min-max, Persamaan (2.1a) sampai (2.1h). Batasnya konstanta yang
    # diturunkan dari isi dataset dan jumlah hari, bukan dari hasil optimasi, jadi
    # suku ternormalkan tetap linear terhadap variabel keputusan dan modelnya
    # tetap berupa MILP.
    batas = M.batas_komponen(data, anggaran)
    objektif = gp.LinExpr()
    for nama in M.SUKU:
        lo, hi = batas[nama]
        rentang = hi - lo
        if rentang > M.TOLERANSI:
            objektif += bobot[M.BOBOT_SUKU[nama]] * (suku[nama] - lo) / rentang
    mdl.setObjective(objektif, GRB.MINIMIZE)

    return mdl, {"v": v, "y": y, "z": z, "x": x, "a": a_tiba, "q": q}, arc


if __name__ == "__main__":
    import dataset as DS

    d = DS.muat_dataset(jumlah_hari=3)
    P, H = ambil_subset(d)
    mdl, var, arc = bangun_model(d, 3_000_000, M.PROFIL_BOBOT["seimbang"], P, H)

    print("Model MILP itinerary multi-menginap")
    print("=" * 78)
    print(f"subset            : {len(P)} destinasi, {len(H)} akomodasi, {d['m']} hari")
    print(f"arc berarah       : {len(arc):,}")
    for nama, v in var.items():
        print(f"  variabel {nama:7} : {len(v):,}")
    print(f"total variabel    : {sum(len(v) for v in var.values()):,}")

    mdl.optimize()
    print(f"status            : {mdl.Status}")
    print(f"nilai objektif    : {mdl.ObjVal:.6f}")
    print()
    print("PERINGATAN: batasan (2.6) sampai (2.18) belum dipasang, jadi solusi di")
    print("atas belum bermakna. Angka ini hanya memastikan modelnya terbangun.")
