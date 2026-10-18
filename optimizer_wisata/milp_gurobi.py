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

Selain keenam itu ada satu variabel bantu, selesai[d], yang mencatat waktu
selesai hari d. Bukan variabel keputusan dan tidak ada di Tabel 2.9; dipakai
semata untuk melinearkan batasan kuota waktu harian (2.12), karena "akhir hari"
tidak dapat dinyatakan linear tanpa variabel penampung.
"""

import time

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


def bangun_model(data, anggaran, bobot, P, H, kunci=None, tolak=None,
                 minimum_kategori=None, kategori_wajib=None):
    """Model lengkap: variabel, objektif (2.1), dan batasan (2.6) sampai (2.18)."""
    M.periksa_bobot(bobot)
    kunci = set(kunci or [])
    tolak = set(tolak or [])
    node, tau, f = data["node"], data["tau"], data["f"]
    u, p, g, s_bar = data["u"], data["p"], data["g"], data["s_bar"]
    t_mat, jam = data["t"], data["jam"]
    D, m = data["D"], data["m"]
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

    # ---------------- (2.6) destinasi dipilih berarti dikunjungi tepat satu hari.
    # Batasan inilah yang membedakan model ini dari Location-Routing Problem
    # klasik, karena tidak seluruh titik wajib dilayani.
    mdl.addConstrs((gp.quicksum(y[i, d] for d in D) == v[i] for i in P), name="c26")

    # ---------------- (2.7a) cakupan kategori
    if kategori_wajib:
        minimum_kategori = minimum_kategori or {}
        for kat in kategori_wajib:
            anggota = [i for i in P if node[i]["kategori"] == kat]
            if anggota:
                mdl.addConstr(
                    gp.quicksum(v[i] for i in anggota) >= minimum_kategori.get(kat, 1),
                    name=f"c27a_{kat}")

    # ---------------- (2.7b) cakupan kota, sekurangnya satu destinasi per kota.
    # Akomodasi tidak dihitung; menginap bukan berwisata.
    for k in data["kota"]:
        anggota = [i for i in P if node[i]["kota"] == k]
        if anggota:
            mdl.addConstr(gp.quicksum(v[i] for i in anggota) >= 1, name=f"c27b_{k}")

    # ---------------- (2.8) tepat satu akomodasi tiap malam
    mdl.addConstrs((gp.quicksum(z[h, d] for h in H) == 1 for d in D), name="c28")

    # ---------------- (2.9a) derajat masuk destinasi sama dengan status kunjungan
    mdl.addConstrs(
        (gp.quicksum(x[a, i, d] for a in N if (a, i) in arc) == y[i, d] for i in P for d in D),
        name="c29a")
    # ---------------- (2.9b) derajat keluar destinasi sama dengan status kunjungan
    mdl.addConstrs(
        (gp.quicksum(x[i, b, d] for b in N if (i, b) in arc) == y[i, d] for i in P for d in D),
        name="c29b")

    # ---------------- (2.10) hari d berangkat dari akomodasi malam d
    mdl.addConstrs(
        (gp.quicksum(x[h, b, d] for b in N if (h, b) in arc) == z[h, d] for h in H for d in D),
        name="c210")
    # ---------------- (2.11) dan (2.11a) hari d berakhir pada akomodasi malam
    # berikutnya, kecuali hari terakhir yang kembali ke akomodasi malam m
    mdl.addConstrs(
        (gp.quicksum(x[a, h, d] for a in N if (a, h) in arc) == z[h, M.malam_akhir(d, m)]
         for h in H for d in D),
        name="c211")

    # ---------------- (2.13) perambatan waktu di sepanjang rute, linearisasi big-M
    for d in D:
        for i in P:
            for j in P:
                if i == j or (i, j) not in arc:
                    continue
                mdl.addConstr(
                    a_tiba[j, d] >= a_tiba[i, d] + tau[i] + t_mat[i, j] - BIG_M * (1 - x[i, j, d]),
                    name=f"c213_{i}_{j}_{d}")
        # keberangkatan dari akomodasi malam itu
        for h in H:
            for j in P:
                if (h, j) not in arc:
                    continue
                mdl.addConstr(
                    a_tiba[j, d] >= M.T_MULAI + t_mat[h, j] - BIG_M * (1 - x[h, j, d]),
                    name=f"c213h_{h}_{j}_{d}")

    # ---------------- (2.14) jam buka dan jam tutup destinasi
    for i in P:
        buka, tutup = jam[i]
        for d in D:
            mdl.addConstr(a_tiba[i, d] >= buka - BIG_M * (1 - y[i, d]), name=f"c214a_{i}_{d}")
            mdl.addConstr(a_tiba[i, d] + tau[i] <= tutup + BIG_M * (1 - y[i, d]),
                          name=f"c214b_{i}_{d}")

    # ---------------- (2.16) pencegahan subtour Miller-Tucker-Zemlin.
    # Bekerja bersamaan dengan (2.13) dan tidak saling menggantikan: (2.13)
    # melacak akumulasi waktu, (2.16) melacak urutan kunjungan.
    for d in D:
        for i in P:
            for j in P:
                if i == j or (i, j) not in arc:
                    continue
                mdl.addConstr(q[j, d] >= q[i, d] + 1 - len(P) * (1 - x[i, j, d]),
                              name=f"c216_{i}_{j}_{d}")

    # ---------------- (2.12) kuota waktu aktivitas harian, dan (2.15) seluruh
    # aktivitas selesai sebelum jendela aktivitas harian berakhir
    selesai = mdl.addVars(D, lb=0.0, ub=24 * 60, vtype=GRB.CONTINUOUS, name="selesai")
    for d in D:
        for i in P:
            for h in H:
                if (i, h) not in arc:
                    continue
                mdl.addConstr(
                    selesai[d] >= a_tiba[i, d] + tau[i] + t_mat[i, h] - BIG_M * (1 - x[i, h, d]),
                    name=f"c212a_{i}_{h}_{d}")
        mdl.addConstr(selesai[d] - M.T_MULAI <= M.BETA, name=f"c212b_{d}")
        mdl.addConstr(selesai[d] <= M.T_SELESAI, name=f"c215_{d}")
        for i in P:
            mdl.addConstr(a_tiba[i, d] <= M.T_SELESAI + BIG_M * (1 - y[i, d]),
                          name=f"c215a_{i}_{d}")

    # ---------------- (2.17) total biaya tiket, akomodasi, dan bahan bakar
    # tidak melampaui anggaran
    mdl.addConstr(
        gp.quicksum(f[i] * v[i] for i in P)
        + gp.quicksum(p[h] * z[h, d] for h in H for d in D)
        + gp.quicksum(g[a, b] * x[a, b, d] for (a, b) in arc for d in D)
        <= anggaran,
        name="c217")

    # ---------------- (2.18a) dan (2.18b) penguncian dan penolakan destinasi
    for i in P:
        if i in kunci:
            mdl.addConstr(v[i] == 1, name=f"c218a_{i}")
        if i in tolak:
            mdl.addConstr(v[i] == 0, name=f"c218b_{i}")

    return mdl, {"v": v, "y": y, "z": z, "x": x, "a": a_tiba, "q": q}, arc


def _rekonstruksi(data, vr, P, H, arc):
    """Menyusun ulang itinerary dari nilai variabel keputusan."""
    D = data["D"]
    solusi = M.solusi_kosong(data)

    for d in D:
        for h in H:
            if vr["z"][h, d].X > 0.5:
                solusi["hotel"][d] = h
                break

    for i in P:
        if vr["v"][i].X > 0.5:
            solusi["pilih"][i] = 1
            for d in D:
                if vr["y"][i, d].X > 0.5:
                    solusi["hari"][i] = d
                    solusi["tiba"][i, d] = vr["a"][i, d].X

    for d in D:
        keluar = {}
        for (a, b) in arc:
            if vr["x"][a, b, d].X > 0.5:
                keluar[a] = b
        awal = solusi["hotel"][d]
        akhir = solusi["hotel"][M.malam_akhir(d, data["m"])]
        urutan = [awal]
        kini = awal
        # jumlah langkah dibatasi supaya arc yang tidak konsisten tidak membuat putaran tak hingga
        for _ in range(len(P) + 2):
            if kini not in keluar:
                break
            kini = keluar[kini]
            urutan.append(kini)
            if kini == akhir:
                break
        solusi["rute"][d] = urutan if len(urutan) >= 2 else [awal, akhir]
    return solusi


def jalankan_milp(data, anggaran, bobot, kunci=None, tolak=None,
                  minimum_kategori=None, kategori_wajib=None,
                  maks_destinasi=MAKS_DESTINASI, maks_hotel=MAKS_HOTEL,
                  batas_waktu=BATAS_WAKTU_DETIK, cetak=False):
    mulai = time.perf_counter()
    P, H = ambil_subset(data, maks_destinasi, maks_hotel)

    # dataset disempitkan ke subset supaya penilaian memakai himpunan yang sama
    sub = dict(data)
    sub["P"], sub["H"], sub["N"] = P, H, P + H
    sub["s"] = {i: data["s"][i] for i in P}
    sub["u"] = {h: data["u"][h] for h in H}
    sub["s_bar"] = {(i, d): data["s_bar"][i, d] for i in P for d in data["D"]}
    sub["f"] = {i: data["f"][i] for i in P}
    sub["p"] = {h: data["p"][h] for h in H}
    sub["tau"] = {i: data["tau"][i] for i in P}
    sub["jam"] = {i: data["jam"][i] for i in P}
    sub["kota"] = sorted({data["node"][i]["kota"] for i in P})

    mdl, vr, arc = bangun_model(sub, anggaran, bobot, P, H, kunci, tolak,
                                minimum_kategori, kategori_wajib)
    mdl.Params.TimeLimit = batas_waktu
    mdl.optimize()

    status = mdl.Status
    nama_status = {
        GRB.OPTIMAL: "OPTIMAL",
        GRB.TIME_LIMIT: "BATAS WAKTU",
        GRB.INFEASIBLE: "TIDAK LAYAK",
        GRB.INF_OR_UNBD: "TIDAK LAYAK ATAU TIDAK TERBATAS",
    }.get(status, str(status))

    keluaran = {
        "metode": "MILP Gurobi",
        "status": nama_status,
        "subset_P": P,
        "subset_H": H,
        "runtime": time.perf_counter() - mulai,
        "jumlah_variabel": mdl.NumVars,
        "jumlah_batasan": mdl.NumConstrs,
    }

    if mdl.SolCount == 0:
        keluaran.update({"solusi": None, "hasil": None, "fitness": float("inf"),
                         "gap": None, "validasi_ok": False,
                         "validasi_pesan": ["Gurobi tidak menemukan satu pun solusi."]})
        if cetak:
            print(f"MILP Gurobi: {nama_status}, tidak ada solusi.")
        return keluaran

    solusi = _rekonstruksi(sub, vr, P, H, arc)
    hasil = M.fitness(sub, solusi, anggaran, bobot, minimum_kategori, kategori_wajib)
    ok, pesan = M.validasi_solusi(sub, solusi, kunci, tolak)

    keluaran.update({
        "solusi": solusi,
        "hasil": hasil,
        "fitness": hasil["F"],
        "objektif_gurobi": mdl.ObjVal,
        "batas_bawah": mdl.ObjBound,
        "gap": mdl.MIPGap,      # Persamaan (2.23)
        "validasi_ok": ok,
        "validasi_pesan": pesan,
        "data_subset": sub,
    })

    if cetak:
        M.cetak_itinerary(sub, solusi, hasil, judul="Itinerary hasil MILP Gurobi")
        print(f"  status             : {nama_status}")
        print(f"  objektif Gurobi    : {mdl.ObjVal:.6f}")
        print(f"  batas bawah        : {mdl.ObjBound:.6f}")
        print(f"  optimality gap     : {mdl.MIPGap * 100:.4f} persen")
        print(f"  variabel, batasan  : {mdl.NumVars:,} dan {mdl.NumConstrs:,}")
        print(f"  runtime            : {keluaran['runtime']:.3f} detik")
        print(f"  validasi struktur  : {'LOLOS' if ok else 'GAGAL'}")
        for x in pesan:
            print(f"    - {x}")
    return keluaran


if __name__ == "__main__":
    import dataset as DS

    d = DS.muat_dataset(jumlah_hari=2)
    jalankan_milp(d, anggaran=3_000_000, bobot=M.PROFIL_BOBOT["seimbang"],
                  maks_destinasi=10, maks_hotel=4, batas_waktu=120, cetak=True)
