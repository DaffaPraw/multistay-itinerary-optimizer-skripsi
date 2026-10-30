"""
Penggerak utama: tiga profil bobot, perbandingan metode, dan penguncian destinasi.

Tiga cara pakai:
    py jalankan.py profil      tiga profil bobot pada dataset penuh, metode PSO
    py jalankan.py banding     PSO, Clarke-Wright, dan MILP pada subset yang sama
    py jalankan.py banding-penuh   ketiganya pada 90 destinasi, batas MILP 6 jam
    py jalankan.py kunci       contoh mengunci dan menolak destinasi lalu menyusun ulang
    py jalankan.py pso         satu metode saja, parameternya dari baris perintah
    py jalankan.py cws         satu metode saja
    py jalankan.py milp        satu metode saja, pada subset

Perintah metode tunggal menerima --profil, --anggaran, --hari, dan --seed. PSO
menambah --partikel, --iterasi, --inersia, --c1, dan --c2; MILP menambah --n,
--hotel, dan --batas. Contoh:

    py jalankan.py pso --seed 7 --profil hemat --c1 1.8 --c2 1.2
    py jalankan.py milp --n 12 --batas 300

Seed dicatat pada setiap keluaran, sesuai batasan rancangan pada Bab I, supaya
hasil yang sama dapat dihasilkan ulang dan diverifikasi.
"""

import argparse
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
# Batas waktu MILP pada dataset penuh. Pada subset 12 destinasi Gurobi sudah
# memerlukan 82 detik untuk membuktikan optimalitas; pada 90 destinasi jumlah
# variabel arc melonjak dari 768 ke 43.200, jadi batasnya diberi jauh lebih
# longgar supaya yang terukur adalah perilaku penyelesainya, bukan batasnya.
BATAS_MILP_PENUH_DETIK = 6 * 3600
# Pengaman memori untuk percobaan penuh. Pohon branch-and-bound tumbuh tanpa
# batas selama pencarian; pada mesin 16 GB itu berarti proses dapat mati setelah
# berjam-jam tanpa melaporkan apa pun. NodefileStart menumpahkan simpul ke disk
# lebih dulu, SoftMemLimit menghentikan Gurobi dengan rapi sehingga solusi
# terbaik dan batas bawahnya tetap terbaca.
#
# Jalan enam jam yang pertama berhenti dengan sebab "Memory limit reached",
# bukan karena batas waktunya habis. Untuk jalan yang jauh lebih panjang
# ambang luapan diturunkan supaya pohon pencarian pindah ke disk jauh lebih
# awal, dan batas berhentinya dinaikkan sedikit. Disknya 1,6 TB kosong,
# sedangkan memorinya 16 GB, jadi disk memang tempat yang lebih longgar.
NODEFILE_GB = 1.0
BATAS_MEMORI_GB = 9.0
# Pada jalan enam jam itu berkas luapan simpul tetap nol byte, jadi yang
# menghabiskan memori bukan pohon pencarian melainkan pekerjaan tiap utas.
# Mesinnya dua belas utas; dipakai separuh supaya jalan dua puluh empat jam
# punya peluang mencapai batas waktunya, bukan batas memorinya. Hanya dipasang
# pada ukuran penuh, sebab pada subset memori tidak pernah jadi persoalan.
UTAS_PENUH = 6
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
                     maks_destinasi=10, maks_hotel=4, batas_waktu=120,
                     log_berkas=None, nama_catatan="perbandingan_metode",
                     nodefile_gb=None, batas_memori_gb=None, nodefile_dir=None,
                     utas=None):
    """Membandingkan ketiga metode pada himpunan kandidat yang sama.

    Bawaannya memakai subset, karena MILP tidak selesai dalam waktu wajar pada 90
    destinasi. Ketiga metode diberi himpunan kandidat yang persis sama supaya nilai
    objektifnya sebanding.

    Ukuran penuh dapat diminta lewat maks_destinasi dan maks_hotel. Itu dipakai
    sekali untuk mengukur sampai di mana penyelesai eksak masih sanggup, dan
    hasilnya dilaporkan apa adanya termasuk bila berstatus BATAS WAKTU.

    Clarke-Wright dan PSO dijalankan lebih dulu, lalu MILP. Urutan itu tidak
    mengubah tabel, tetapi pada ukuran penuh berarti kedua heuristik sudah
    tercatat sebelum Gurobi dimulai.
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

    heuristik = []
    for fn in (lambda: PSO.jalankan_pso(sub, anggaran, bobot, seed=seed),
               lambda: CW.jalankan_cws(sub, anggaran, bobot)):
        r = _ringkas(sub, fn())
        r["status"] = "heuristik"
        heuristik.append(r)
        print(f"  {r['metode']:<22} Z {r['Z']:.6f}   {r['runtime']:.3f} detik")

    # Dicatat sebelum MILP mulai. Pada ukuran penuh Gurobi dapat berjam-jam, dan
    # kalau prosesnya terhenti kedua baris ini tidak ikut hilang.
    if log_berkas:
        print(f"  pracatat heuristik: {_catat(nama_catatan + '_heuristik', {'seed': seed, 'anggaran': anggaran, 'subset_P': P, 'subset_H': H, 'baris': heuristik})}")
        print(f"  catatan Gurobi    : {log_berkas}")
    print(f"  MILP berjalan, batas waktu {batas_waktu / 3600:.2f} jam ...")

    hasil_milp = MILP.jalankan_milp(data, anggaran, bobot, maks_destinasi=maks_destinasi,
                                    maks_hotel=maks_hotel, batas_waktu=batas_waktu,
                                    log_berkas=log_berkas, nodefile_gb=nodefile_gb,
                                    batas_memori_gb=batas_memori_gb,
                                    nodefile_dir=nodefile_dir, utas=utas)
    r = _ringkas(sub, hasil_milp)
    r["status"] = hasil_milp["status"]
    r["gap_persen"] = round(hasil_milp["gap"] * 100, 4) if hasil_milp.get("gap") is not None else None
    r["jumlah_variabel"] = hasil_milp["jumlah_variabel"]
    r["jumlah_batasan"] = hasil_milp["jumlah_batasan"]
    r["batas_bawah"] = hasil_milp.get("batas_bawah")
    baris = [r] + heuristik
    print()

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
    print()
    print(f"  ukuran model MILP : {baris[0].get('jumlah_variabel')} variabel, "
          f"{baris[0].get('jumlah_batasan')} batasan")

    if hasil_milp["status"] != "OPTIMAL":
        print("\n  Catatan: MILP tidak mencapai status OPTIMAL, sehingga selisih terhadap")
        print("  optimum tidak dapat dihitung dan kolom gap dikosongkan.")

    path = _catat(nama_catatan, {"seed": seed, "anggaran": anggaran,
                                 "hari": sub["m"], "profil": "seimbang",
                                 "batas_waktu_milp": batas_waktu,
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


# ---------------------------------------------------------------- metode tunggal
def jalankan_satu(data, metode, arg):
    """Menjalankan satu metode saja dengan parameter dari baris perintah.

    Berbeda dari mode banding yang selalu menjalankan ketiganya, perintah ini
    dipakai ketika hanya satu metode yang ingin diamati, misalnya ketika menyetel
    parameter PSO. Keluarannya tetap disimpan supaya dapat ditelusuri ulang.
    """
    bobot = M.PROFIL_BOBOT[arg.profil]
    nama = {"pso": "PSO", "cws": "Clarke-Wright Savings", "milp": "MILP Gurobi"}[metode]

    print(f"Metode tunggal: {nama}")
    print("=" * 78)
    print(f"dataset    : {os.path.basename(data['data_path'])}")
    print(f"kandidat   : {len(data['P'])} destinasi, {len(data['H'])} akomodasi")
    print(f"hari       : {data['m']}")
    print(f"anggaran   : Rp{arg.anggaran:,}")
    print(f"profil     : {M.NAMA_PROFIL[arg.profil]}, "
          f"lambda {bobot['lambda1']}/{bobot['lambda2']}/"
          f"{bobot['lambda3']}/{bobot['lambda4']}")

    penilai = data
    if metode == "pso":
        print(f"seed       : {arg.seed}")
        print(f"parameter  : {arg.partikel} partikel, {arg.iterasi} iterasi maks, "
              f"inersia {arg.inersia}, c1 {arg.c1}, c2 {arg.c2}")
        print()
        keluaran = PSO.jalankan_pso(data, arg.anggaran, bobot, seed=arg.seed,
                                    jumlah_partikel=arg.partikel,
                                    maks_iterasi=arg.iterasi,
                                    inersia=arg.inersia, c1=arg.c1, c2=arg.c2,
                                    cetak=True)
    elif metode == "cws":
        print("catatan    : deterministik, seed tidak berpengaruh")
        print()
        keluaran = CW.jalankan_cws(data, arg.anggaran, bobot, cetak=True)
    else:
        import milp_gurobi as MILP

        print(f"subset     : {arg.n} destinasi, {arg.hotel} akomodasi")
        print(f"batas waktu: {arg.batas or 120} detik")
        print()
        keluaran = MILP.jalankan_milp(data, arg.anggaran, bobot,
                                      maks_destinasi=arg.n, maks_hotel=arg.hotel,
                                      batas_waktu=arg.batas or 120,
                                      utas=arg.utas, cetak=True)
        # Dinilai terhadap subset yang dilihat model, bukan dataset penuh, karena
        # batas normalisasi diturunkan dari isi himpunan kandidat.
        penilai = keluaran.get("data_subset") or data

    r = _ringkas(penilai, keluaran)
    r["status"] = keluaran.get("status", "heuristik")
    if keluaran.get("gap") is not None:
        r["gap_persen"] = round(keluaran["gap"] * 100, 4)

    print()
    _tabel([r], ["metode", "status", "Z", "destinasi", "skor_total",
                 "biaya_total", "runtime", "layak"])

    catatan = {"metode": metode, "profil": arg.profil, "anggaran": arg.anggaran,
               "hari": arg.hari, "seed": arg.seed, "baris": [r]}
    if metode == "pso":
        catatan["parameter_pso"] = {"partikel": arg.partikel, "iterasi": arg.iterasi,
                                    "inersia": arg.inersia, "c1": arg.c1, "c2": arg.c2}
    if metode == "milp":
        catatan["subset"] = {"destinasi": arg.n, "akomodasi": arg.hotel,
                             "batas_waktu": arg.batas}
    print(f"\nhasil disimpan: {_catat('metode_' + metode, catatan)}")
    return r


def _baca_argumen():
    """Argumen baris perintah. Perintah lama tetap jalan tanpa tanda tambahan."""
    p = argparse.ArgumentParser(
        prog="jalankan.py",
        description="Penggerak utama optimizer itinerary multi-menginap.")
    p.add_argument("perintah", nargs="?", default="profil",
                   choices=["profil", "banding", "banding-penuh", "kunci",
                            "pso", "cws", "milp"])
    p.add_argument("--profil", default="seimbang", choices=sorted(M.PROFIL_BOBOT),
                   help="profil bobot lambda, bawaan seimbang")
    p.add_argument("--anggaran", type=int, default=ANGGARAN)
    p.add_argument("--hari", type=int, default=JUMLAH_HARI)
    p.add_argument("--seed", type=int, default=SEED)
    p.add_argument("--pengguna", type=int, default=None,
                   help="nomor urut pengguna; seed diturunkan darinya, (3.6)")
    p.add_argument("--beta", type=float, default=None,
                   help="kuota waktu aktivitas harian, menit")
    p.add_argument("--jam-mulai", type=int, default=None, dest="jam_mulai")
    p.add_argument("--jam-selesai", type=int, default=None, dest="jam_selesai")
    p.add_argument("--cuaca", action="store_true",
                   help="menyalakan koreksi cuaca (2.2); bawaannya mati")
    p.add_argument("--partikel", type=int, default=PSO.JUMLAH_PARTIKEL,
                   help="PSO: jumlah partikel")
    p.add_argument("--iterasi", type=int, default=PSO.MAKS_ITERASI,
                   help="PSO: iterasi maksimum")
    p.add_argument("--inersia", type=float, default=PSO.INERSIA)
    p.add_argument("--c1", type=float, default=PSO.C1)
    p.add_argument("--c2", type=float, default=PSO.C2)
    p.add_argument("--n", type=int, default=10,
                   help="MILP: jumlah destinasi kandidat pada subset")
    p.add_argument("--hotel", type=int, default=4,
                   help="MILP: jumlah akomodasi kandidat pada subset")
    p.add_argument("--batas", type=int, default=None,
                   help="MILP: batas waktu penyelesai, detik. Bawaannya 120 detik "
                        "pada subset dan enam jam pada dataset penuh")
    p.add_argument("--utas", type=int, default=None,
                   help="MILP: jumlah utas Gurobi. Bawaannya seluruh utas mesin "
                        "pada subset dan separuhnya pada dataset penuh, sebab "
                        "memori yang terpakai sebanding dengan jumlah utas")
    return p.parse_args()


def main():
    arg = _baca_argumen()
    perintah = arg.perintah
    mulai = time.perf_counter()

    # Ditetapkan sebelum dataset dimuat, sebab rho diambil pada jendela aktivitas
    # dan penyaringan jamnya terjadi saat pemuatan.
    if arg.beta is not None or arg.jam_mulai is not None or arg.jam_selesai is not None:
        waktu = M.atur_waktu(arg.beta, arg.jam_mulai, arg.jam_selesai)
        print(f"waktu      : kuota {waktu['beta']:.0f} menit, jendela "
              f"{waktu['T_MULAI'] // 60}.00 sampai {waktu['T_SELESAI'] // 60}.00")
    if arg.pengguna is not None:
        arg.seed = PSO.seed_pengguna(arg.pengguna)
        print(f"pengguna   : nomor {arg.pengguna}, seed {arg.seed} lewat (3.6)")

    data = DS.muat_dataset(jumlah_hari=arg.hari,
                           cuaca_aktif=1 if arg.cuaca else DS.CUACA_AKTIF)
    if arg.cuaca:
        print('cuaca      : koreksi (2.2) dinyalakan, w = 1')

    if perintah == "profil":
        jalankan_profil(data)
    elif perintah == "banding":
        # Ukuran subset dan batas waktunya ikut baris perintah, sebab Bab IV
        # membandingkan ketiga metode pada beberapa ukuran dataset. Pengaman
        # memori dan berkas luapan dipasang juga di sini, bukan hanya pada
        # ukuran penuh, karena subset besar pun dapat berjam-jam.
        batas = arg.batas or 120
        os.makedirs(FOLDER_HASIL, exist_ok=True)
        jalankan_banding(data, anggaran=arg.anggaran, seed=arg.seed,
                         maks_destinasi=arg.n, maks_hotel=arg.hotel,
                         batas_waktu=batas,
                         log_berkas=os.path.join(FOLDER_HASIL,
                                                 f"gurobi_n{arg.n}.log"),
                         nama_catatan=f"perbandingan_metode_n{arg.n}",
                         nodefile_gb=NODEFILE_GB,
                         batas_memori_gb=BATAS_MEMORI_GB,
                         nodefile_dir=os.path.join(FOLDER_HASIL, "nodefile"),
                         utas=arg.utas)
    elif perintah == "banding-penuh":
        # Seluruh destinasi dan akomodasi. ambil_subset membagi kuota per kota,
        # jadi kuotanya dikalikan jumlah kota supaya tidak ada yang terpotong.
        n_kota = len(data["kota"])
        batas = arg.batas or BATAS_MILP_PENUH_DETIK
        # Namanya menyebut batas waktunya supaya catatan Gurobi dari jalan yang
        # lebih pendek tidak tertimpa jalan yang lebih panjang.
        log = os.path.join(FOLDER_HASIL, f"gurobi_penuh_{batas // 3600}jam.log")
        os.makedirs(FOLDER_HASIL, exist_ok=True)
        jalankan_banding(data, anggaran=arg.anggaran, seed=arg.seed,
                         maks_destinasi=len(data["P"]) * n_kota,
                         maks_hotel=len(data["H"]) * n_kota,
                         batas_waktu=batas,
                         log_berkas=log,
                         nama_catatan="perbandingan_metode_penuh",
                         nodefile_gb=NODEFILE_GB,
                         batas_memori_gb=BATAS_MEMORI_GB,
                         nodefile_dir=os.path.join(FOLDER_HASIL, "nodefile"),
                         utas=arg.utas or UTAS_PENUH)
    elif perintah == "kunci":
        jalankan_kunci(data)
    elif perintah in ("pso", "cws", "milp"):
        jalankan_satu(data, perintah, arg)
    else:
        print(f"Perintah tidak dikenal: {perintah}")
        return 1

    print(f"\ntotal waktu jalan: {time.perf_counter() - mulai:.2f} detik")
    return 0


if __name__ == "__main__":
    sys.exit(main())
