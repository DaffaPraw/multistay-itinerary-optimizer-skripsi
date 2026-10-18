"""
Penggerak utama: tiga profil bobot, perbandingan metode, dan penguncian destinasi.

Tiga cara pakai:
    py jalankan.py profil      tiga profil bobot pada dataset penuh, metode PSO
    py jalankan.py banding     PSO, Clarke-Wright, dan MILP pada subset yang sama
    py jalankan.py kunci       contoh mengunci dan menolak destinasi lalu menyusun ulang

Seed dicatat pada setiap keluaran, sesuai batasan rancangan pada Bab I, supaya
hasil yang sama dapat dihasilkan ulang dan diverifikasi.
"""

import json
import os
import sys
import time
from datetime import datetime

import clarke_wright as CW
import dataset as DS
import model as M
import pso as PSO


ANGGARAN = 3_000_000
JUMLAH_HARI = 3
SEED = 42
FOLDER_HASIL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hasil")


def _catat(nama, isi):
    os.makedirs(FOLDER_HASIL, exist_ok=True)
    cap = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = os.path.join(FOLDER_HASIL, f"{nama}_{cap}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(isi, f, indent=2, ensure_ascii=False, default=str)
    return path


def _ringkas(data, keluaran):
    """Ringkasan yang bisa dibandingkan antar metode dan antar profil."""
    solusi, hasil = keluaran.get("solusi"), keluaran.get("hasil")
    if solusi is None or hasil is None:
        return {"metode": keluaran["metode"], "status": keluaran.get("status", "gagal")}
    terpilih = [i for i in data["P"] if solusi["pilih"].get(i)]
    return {
        "metode": keluaran["metode"],
        "Z": round(hasil["Z"], 6),
        "F": round(hasil["F"], 6),
        "L_P": round(hasil["L_P"], 4),
        "L_H": round(hasil["L_H"], 4),
        "C_H": round(hasil["C_H"], 4),
        "C_T": round(hasil["C_T"], 4),
        "destinasi": len(terpilih),
        "skor_total": round(sum(data["s_bar"][i, solusi["hari"][i]] for i in terpilih), 2),
        "biaya_total": round(hasil["biaya_total"]),
        "biaya_akomodasi": round(hasil["biaya_hotel"]),
        "biaya_tiket": round(hasil["biaya_tiket"]),
        "biaya_transport": round(hasil["biaya_transport"]),
        "layak": hasil["layak"],
        "runtime": round(keluaran["runtime"], 3),
        "validasi_ok": keluaran["validasi_ok"],
        "daftar": terpilih,
    }


def _tabel(baris, kolom):
    lebar = {k: max(len(k), max((len(str(b.get(k, ""))) for b in baris), default=0)) for k in kolom}
    print("  " + "  ".join(k.ljust(lebar[k]) for k in kolom))
    print("  " + "  ".join("-" * lebar[k] for k in kolom))
    for b in baris:
        print("  " + "  ".join(str(b.get(k, "")).ljust(lebar[k]) for k in kolom))


# ---------------------------------------------------------------- tiga profil
def jalankan_profil(data, anggaran=ANGGARAN, seed=SEED):
    print("Tiga profil bobot")
    print("=" * 78)
    print(f"dataset    : {os.path.basename(data['data_path'])}")
    print(f"anggaran   : Rp{anggaran:,}")
    print(f"hari       : {data['m']}  ({data['tanggal'][0]} sampai {data['tanggal'][-1]})")
    print(f"seed       : {seed}")
    for c in data["catatan"]:
        print(f"catatan    : {c}")
    print()

    ringkasan = []
    rinci = {}
    for kunci_profil, bobot in M.PROFIL_BOBOT.items():
        keluaran = PSO.jalankan_pso(data, anggaran, bobot, seed=seed)
        r = _ringkas(data, keluaran)
        r["profil"] = M.NAMA_PROFIL[kunci_profil]
        r["bobot"] = f"{bobot['lambda1']:.2f}/{bobot['lambda2']:.2f}/{bobot['lambda3']:.2f}/{bobot['lambda4']:.2f}"
        ringkasan.append(r)
        rinci[kunci_profil] = keluaran

    _tabel(ringkasan, ["profil", "bobot", "Z", "destinasi", "skor_total",
                       "biaya_total", "biaya_akomodasi", "runtime", "layak"])

    print("\nperbedaan destinasi antar profil")
    himpunan = {r["profil"]: set(r["daftar"]) for r in ringkasan}
    nama = list(himpunan)
    irisan = set.intersection(*himpunan.values()) if himpunan else set()
    print(f"  dipilih oleh ketiganya : {len(irisan)} destinasi")
    for a in range(len(nama)):
        for b in range(a + 1, len(nama)):
            beda = himpunan[nama[a]] ^ himpunan[nama[b]]
            print(f"  {nama[a]} vs {nama[b]}: berbeda {len(beda)} destinasi")

    path = _catat("tiga_profil", {"seed": seed, "anggaran": anggaran,
                                  "tanggal": [str(t) for t in data["tanggal"]],
                                  "ringkasan": ringkasan})
    print(f"\nhasil disimpan: {path}")
    return rinci


# ---------------------------------------------------------------- perbandingan
def jalankan_banding(data, anggaran=ANGGARAN, seed=SEED,
                     maks_destinasi=10, maks_hotel=4, batas_waktu=120):
    """Membandingkan ketiga metode pada subset yang sama.

    Pakai subset, bukan dataset penuh, karena MILP tidak selesai dalam waktu wajar
    pada 90 destinasi. Ketiga metode diberi himpunan kandidat yang persis sama
    supaya nilai objektifnya sebanding.
    """
    import milp_gurobi as MILP

    bobot = M.PROFIL_BOBOT["seimbang"]
    P, H = MILP.ambil_subset(data, maks_destinasi, maks_hotel)

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

    print("Perbandingan metode pada subset yang sama")
    print("=" * 78)
    print(f"destinasi kandidat : {len(P)}   akomodasi kandidat : {len(H)}")
    print(f"hari               : {sub['m']}")
    print(f"anggaran           : Rp{anggaran:,}")
    print(f"profil bobot       : Seimbang")
    print(f"seed PSO           : {seed}")
    print()

    baris = []
    hasil_milp = MILP.jalankan_milp(data, anggaran, bobot, maks_destinasi=maks_destinasi,
                                    maks_hotel=maks_hotel, batas_waktu=batas_waktu)
    r = _ringkas(sub, hasil_milp)
    r["status"] = hasil_milp["status"]
    r["gap_persen"] = round(hasil_milp["gap"] * 100, 4) if hasil_milp.get("gap") is not None else None
    baris.append(r)

    for nama, fn in (("PSO", lambda: PSO.jalankan_pso(sub, anggaran, bobot, seed=seed)),
                     ("CWS", lambda: CW.jalankan_cws(sub, anggaran, bobot))):
        keluaran = fn()
        r = _ringkas(sub, keluaran)
        r["status"] = "heuristik"
        baris.append(r)

    # Persamaan (2.23). Selisih terhadap optimum hanya sah bila MILP berstatus OPTIMAL.
    acuan = baris[0]
    if hasil_milp["status"] == "OPTIMAL" and acuan.get("Z"):
        for r in baris[1:]:
            r["gap_persen"] = round((r["Z"] - acuan["Z"]) / acuan["Z"] * 100, 4)
    else:
        for r in baris[1:]:
            r["gap_persen"] = None

    _tabel(baris, ["metode", "status", "Z", "destinasi", "skor_total",
                   "biaya_total", "gap_persen", "runtime", "layak"])

    if hasil_milp["status"] != "OPTIMAL":
        print("\n  Catatan: MILP tidak mencapai status OPTIMAL, sehingga selisih terhadap")
        print("  optimum tidak dapat dihitung dan kolom gap dikosongkan.")

    path = _catat("perbandingan_metode", {"seed": seed, "anggaran": anggaran,
                                          "subset_P": P, "subset_H": H, "baris": baris})
    print(f"\nhasil disimpan: {path}")
    return baris


# ---------------------------------------------------------------- kunci dan tolak
def jalankan_kunci(data, anggaran=ANGGARAN, seed=SEED):
    """Contoh Persamaan (2.18a) dan (2.18b): mengunci dan menolak destinasi."""
    bobot = M.PROFIL_BOBOT["seimbang"]
    node = data["node"]

    print("Penguncian dan penolakan destinasi")
    print("=" * 78)

    awal = PSO.jalankan_pso(data, anggaran, bobot, seed=seed)
    r0 = _ringkas(data, awal)
    terpilih_awal = set(r0["daftar"])

    # dikunci: destinasi berskor tinggi yang justru tidak terpilih pada optimasi pertama
    calon_kunci = sorted((i for i in data["P"] if i not in terpilih_awal),
                         key=lambda i: -data["s"][i])
    kunci = calon_kunci[:2]
    # ditolak: dua destinasi berskor terendah yang terpilih pada optimasi pertama
    tolak = sorted(terpilih_awal, key=lambda i: data["s"][i])[:2]

    print(f"  dikunci : {', '.join(f'{i} {node[i]['nama']}' for i in kunci)}")
    print(f"  ditolak : {', '.join(f'{i} {node[i]['nama']}' for i in tolak)}")
    print()

    ulang = PSO.jalankan_pso(data, anggaran, bobot, kunci=kunci, tolak=tolak, seed=seed)
    r1 = _ringkas(data, ulang)
    r0["tahap"] = "optimasi pertama"
    r1["tahap"] = "sesudah dikunci dan ditolak"

    _tabel([r0, r1], ["tahap", "Z", "destinasi", "skor_total", "biaya_total", "layak", "validasi_ok"])

    terpilih_ulang = set(r1["daftar"])
    print("\n  pemeriksaan batasan")
    for i in kunci:
        print(f"    (2.18a) {i} wajib masuk  : {'TERPENUHI' if i in terpilih_ulang else 'DILANGGAR'}")
    for i in tolak:
        print(f"    (2.18b) {i} wajib keluar : {'TERPENUHI' if i not in terpilih_ulang else 'DILANGGAR'}")

    path = _catat("kunci_tolak", {"seed": seed, "kunci": kunci, "tolak": tolak,
                                  "sebelum": r0, "sesudah": r1})
    print(f"\nhasil disimpan: {path}")
    return r0, r1


def main():
    perintah = sys.argv[1] if len(sys.argv) > 1 else "profil"
    mulai = time.perf_counter()
    data = DS.muat_dataset(jumlah_hari=JUMLAH_HARI)

    if perintah == "profil":
        jalankan_profil(data)
    elif perintah == "banding":
        jalankan_banding(data)
    elif perintah == "kunci":
        jalankan_kunci(data)
    else:
        print(f"Perintah tidak dikenal: {perintah}")
        print("Pilihan: profil, banding, kunci")
        return 1

    print(f"\ntotal waktu jalan: {time.perf_counter() - mulai:.2f} detik")
    return 0


if __name__ == "__main__":
    sys.exit(main())
