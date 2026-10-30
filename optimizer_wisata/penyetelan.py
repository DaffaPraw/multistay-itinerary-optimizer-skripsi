"""
Penyetelan parameter untuk Bab IV.

Alasan berkas ini ada. Komentar pada model.py menyatakan nilai tiap profil bobot
ditetapkan lewat pengujian awal Bab IV, dan nilai parameter PSO di kepala pso.py
juga tertulis tanpa dasar yang terukur. Pernyataan itu perlu ditopang angka, bukan
sekadar ditulis.

Empat percobaan:

    Percobaan A, parameter PSO.
        Disapu satu faktor pada satu waktu di sekitar nilai bawaan, bukan grid
        penuh. Grid penuh atas lima faktor akan memerlukan ratusan kali jalan
        sementara pengaruh antarfaktornya tidak ditanyakan naskah. Tiap
        konfigurasi diulang beberapa seed karena PSO stokastik.

    Percobaan B, bobot penalti lambda 5 sampai lambda 10.
        Pengalinya disapu pada dua anggaran: longgar dan ketat. Pada anggaran
        longgar batasan jarang mengikat sehingga bobot penalti hampir tidak
        berpengaruh; yang menentukan adalah anggaran ketat. Yang diukur bukan
        hanya Z melainkan berapa seed yang menghasilkan solusi layak.

    Percobaan C, tiga profil bobot.
        Membuktikan ketiganya benar-benar menggeser pilihan destinasi, bukan
        hanya menggeser nilai Z. Ditutup penilaian silang: tiap solusi dinilai
        di bawah ketiga fungsi objektif, untuk memeriksa apakah setiap run
        benar-benar memenangkan objektifnya sendiri.

    Percobaan D, skenario cuaca.
        Saklar w dinyalakan dan dimatikan. Naskah memperlakukan w sebagai
        parameter masukan, bukan variabel keputusan, jadi yang diukur adalah
        pengaruhnya terhadap pilihan destinasi.

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
import model as M
import pso as PSO


ANGGARAN = 3_000_000
ANGGARAN_KETAT = 1_200_000
# Di bawah biaya alami solusi mana pun, sehingga seluruh partikel melanggar dan
# bobot penalti benar-benar menentukan solusi mana yang dianggap paling tidak buruk.
ANGGARAN_MUSTAHIL = 700_000
JUMLAH_HARI = 3
SEED_AWAL = 1
JUMLAH_SEED = 10
# Kuota aktivitas harian untuk skenario skripsi, dalam menit. Naskah
# menyebut angka ini sebagai setelan percobaan, jadi dipatok di sini dan
# tidak diambil dari nilai bawaan model.py, yang seluruh lebar jendela.
BETA_SKENARIO = 600.0
FOLDER = os.path.join(os.path.dirname(os.path.abspath(__file__)), "hasil")


def _rangkum(nilai):
    if not nilai:
        return {}
    return {
        "n": len(nilai),
        "min": round(min(nilai), 6),
        "maks": round(max(nilai), 6),
        "rata": round(st.mean(nilai), 6),
        "stdev": round(st.pstdev(nilai), 6) if len(nilai) > 1 else 0.0,
    }


def _jalan_pso(data, bobot, n_seed, anggaran=ANGGARAN, hitung_langgar=False, **tambahan):
    """Beberapa seed pada satu konfigurasi. Mengembalikan ringkasan Z dan kelayakan.

    hitung_langgar menyalakan pencacah berapa persen evaluasi selama pencarian
    menghasilkan solusi yang melanggar batasan. Angka itu yang menentukan apakah
    bobot penalti punya kesempatan berpengaruh sama sekali.
    """
    z, waktu, layak, iterasi = [], [], 0, []
    langgar = eval_total = 0
    asli = M.fitness
    if hitung_langgar:
        def _pantau(dt, sl, ag, bb, mk=None, kw=None, bp=None):
            nonlocal langgar, eval_total
            h = asli(dt, sl, ag, bb, mk, kw, bp)
            eval_total += 1
            if not h["layak"]:
                langgar += 1
            return h
        M.fitness = _pantau
    for k in range(n_seed):
        out = PSO.jalankan_pso(data, anggaran, bobot, seed=SEED_AWAL + k, **tambahan)
        z.append(out["hasil"]["Z"])
        waktu.append(out["runtime"])
        iterasi.append(out["iterasi_terpakai"])
        if out["hasil"]["layak"]:
            layak += 1
    M.fitness = asli
    hasil = {"Z": _rangkum(z), "layak": f"{layak}/{n_seed}", "layak_n": layak,
             "runtime_rata": round(st.mean(waktu), 3),
             "iterasi_rata": round(st.mean(iterasi), 1)}
    if hitung_langgar and eval_total:
        hasil["persen_evaluasi_melanggar"] = round(langgar / eval_total * 100, 2)
    return hasil


# ---------------------------------------------------------------- percobaan A
def percobaan_a(data, bobot, n_seed):
    """Parameter PSO, satu faktor pada satu waktu di sekitar nilai bawaan."""
    print("Percobaan A: parameter PSO")
    print("=" * 92)
    bawaan = {"inersia": PSO.INERSIA, "c1": PSO.C1, "c2": PSO.C2,
              "jumlah_partikel": PSO.JUMLAH_PARTIKEL, "maks_iterasi": PSO.MAKS_ITERASI}
    print(f"bawaan: inersia {bawaan['inersia']}, c1 {bawaan['c1']}, c2 {bawaan['c2']}, "
          f"{bawaan['jumlah_partikel']} partikel, {bawaan['maks_iterasi']} iterasi, "
          f"{n_seed} seed per konfigurasi")

    sapuan = [
        ("inersia", [{"inersia": v} for v in (0.4, 0.5, 0.6, 0.72, 0.85, 0.95)]),
        ("c1 dan c2", [{"c1": a, "c2": b} for a, b in
                       ((2.0, 0.9), (1.8, 1.2), (1.45, 1.45), (1.2, 1.8), (0.9, 2.0))]),
        ("jumlah partikel", [{"jumlah_partikel": v} for v in (15, 20, 30, 50, 80)]),
        ("maks iterasi", [{"maks_iterasi": v} for v in (30, 45, 60, 90, 120)]),
    ]

    hasil = []
    for nama_faktor, nilai_nilai in sapuan:
        print(f"\n-- {nama_faktor}")
        print(f"   {'konfigurasi':<34} {'Z rata':>10} {'stdev':>10} {'Z terbaik':>11} "
              f"{'layak':>7} {'iter':>6} {'detik':>7}")
        for ubah in nilai_nilai:
            r = _jalan_pso(data, bobot, n_seed, **ubah)
            label = ", ".join(f"{k}={v}" for k, v in ubah.items())
            tanda = "  <- bawaan" if all(bawaan[k] == v for k, v in ubah.items()) else ""
            print(f"   {label:<34} {r['Z']['rata']:>10.6f} {r['Z']['stdev']:>10.6f} "
                  f"{r['Z']['min']:>11.6f} {r['layak']:>7} {r['iterasi_rata']:>6.1f} "
                  f"{r['runtime_rata']:>7.2f}{tanda}")
            hasil.append({"faktor": nama_faktor, "ubah": ubah, "bawaan": not tanda == "", **r})
    return hasil


# ---------------------------------------------------------------- percobaan B
def percobaan_b(data, bobot, n_seed):
    """Bobot penalti lambda 5 sampai lambda 10, pada tiga tingkat keketatan anggaran."""
    print("\n\nPercobaan B: bobot penalti lambda 5 sampai lambda 10")
    print("=" * 92)
    print(f"bawaan seluruhnya 10,0. Tiga anggaran: longgar Rp{ANGGARAN:,}, "
          f"ketat Rp{ANGGARAN_KETAT:,}, mustahil Rp{ANGGARAN_MUSTAHIL:,}.")
    print("Kolom melanggar adalah persen evaluasi selama pencarian yang menghasilkan")
    print("solusi melanggar batasan. Bobot penalti hanya dapat berpengaruh bila kolom")
    print("itu tidak nol, dan hanya menentukan hasil bila solusi layak tidak terjangkau.")

    hasil = []
    for nama_anggaran, nilai_anggaran in (("longgar", ANGGARAN),
                                          ("ketat", ANGGARAN_KETAT),
                                          ("mustahil", ANGGARAN_MUSTAHIL)):
        print(f"\n-- anggaran {nama_anggaran}, Rp{nilai_anggaran:,}")
        print(f"   {'bobot':>8} {'Z rata':>10} {'stdev':>10} {'Z terbaik':>11} "
              f"{'layak':>8} {'melanggar':>11}")
        for w in (0.1, 1.0, 5.0, 10.0, 50.0, 200.0):
            bp = {f"lambda{k}": w for k in range(5, 11)}
            r = _jalan_pso(data, bobot, n_seed, anggaran=nilai_anggaran,
                           hitung_langgar=True, bobot_penalti=bp)
            tanda = "  <- bawaan" if w == 10.0 else ""
            print(f"   {w:>8.1f} {r['Z']['rata']:>10.6f} {r['Z']['stdev']:>10.6f} "
                  f"{r['Z']['min']:>11.6f} {r['layak']:>8} "
                  f"{r.get('persen_evaluasi_melanggar', 0):>10.2f}%{tanda}")
            hasil.append({"anggaran": nama_anggaran, "nilai_anggaran": nilai_anggaran,
                          "bobot_penalti": w, "bawaan": w == 10.0, **r})
    return hasil


# ---------------------------------------------------------------- percobaan C
def percobaan_c(data, n_seed):
    """Tiga profil bobot. Yang diperiksa bukan hanya Z, melainkan pilihan destinasinya."""
    print("\n\nPercobaan C: tiga profil bobot")
    print("=" * 92)
    print("Z antarprofil TIDAK sebanding, sebab lambda-nya berbeda sehingga fungsi")
    print("objektifnya pun berbeda. Yang dibandingkan isi solusinya.")
    print(f"\n   {'profil':<22} {'lambda':<26} {'Z rata':>10} {'dest':>6} {'skor':>8} "
          f"{'biaya':>12}")

    hasil, terpilih = [], {}
    sol_simpan = {pr: [] for pr in M.PROFIL_BOBOT}
    layak_simpan = {pr: [] for pr in M.PROFIL_BOBOT}
    for pr, bobot in M.PROFIL_BOBOT.items():
        z, dest, skor, biaya = [], [], [], []
        for k in range(n_seed):
            out = PSO.jalankan_pso(data, ANGGARAN, bobot, seed=SEED_AWAL + k)
            h, sol = out["hasil"], out["solusi"]
            ter = [i for i in data["P"] if sol["pilih"].get(i)]
            z.append(h["Z"])
            dest.append(len(ter))
            skor.append(sum(data["s_bar"][i, sol["hari"][i]] for i in ter))
            biaya.append(h["biaya_total"])
            sol_simpan[pr].append(sol)
            layak_simpan[pr].append(bool(h['layak']))
            if k == 0:
                terpilih[pr] = set(ter)
        lam = "/".join(str(bobot[f"lambda{i}"]) for i in range(1, 5))
        print(f"   {M.NAMA_PROFIL[pr]:<22} {lam:<26} {st.mean(z):>10.6f} "
              f"{st.mean(dest):>6.1f} {st.mean(skor):>8.2f} {st.mean(biaya):>12,.0f}")
        hasil.append({"profil": pr, "nama": M.NAMA_PROFIL[pr], "bobot": bobot,
                      "Z": _rangkum(z), "destinasi_rata": round(st.mean(dest), 1),
                      "skor_rata": round(st.mean(skor), 2),
                      "biaya_rata": round(st.mean(biaya))})

    nama = list(terpilih)
    semua = set.intersection(*terpilih.values())
    print(f"\n   destinasi yang dipilih KETIGA profil: {len(semua)} dari {len(data['P'])}")
    for a in range(len(nama)):
        for b in range(a + 1, len(nama)):
            beda = terpilih[nama[a]] ^ terpilih[nama[b]]
            print(f"   {M.NAMA_PROFIL[nama[a]]} vs {M.NAMA_PROFIL[nama[b]]}: "
                  f"berbeda {len(beda)} destinasi")

    # Penilaian silang. Tiap solusi dinilai di bawah ketiga fungsi objektif.
    # Diagonalnya seharusnya menang, sebab solusi itu memang hasil optimasi
    # objektif tersebut. Bila kalah, run itu berhenti di optimum lokal yang
    # lebih buruk daripada solusi yang kebetulan ditemukan run lain.
    #
    # Hanya seed yang ketiga solusinya layak yang dihitung, sebab Z tidak
    # memuat penalti sehingga solusi melanggar bisa tampak unggul.
    print('\n   Penilaian silang solusi terhadap ketiga fungsi objektif')
    kalah = {pr: 0 for pr in nama}
    rinci, sah = [], 0
    for k in range(n_seed):
        if not all(layak_simpan[pr][k] for pr in nama):
            continue
        sah += 1
        for pr in nama:
            z = {ps: M.nilai_objektif(data, sol_simpan[ps][k], ANGGARAN,
                                      M.PROFIL_BOBOT[pr])['Z'] for ps in nama}
            juara = min(z, key=z.get)
            if juara == pr:
                continue
            kalah[pr] += 1
            rinci.append({'seed': SEED_AWAL + k, 'objektif': pr,
                          'dikalahkan_oleh': juara,
                          'Z_sendiri': round(z[pr], 6),
                          'Z_penantang': round(z[juara], 6)})
    for pr in nama:
        print(f'   objektif {M.NAMA_PROFIL[pr]:<22} kalah oleh solusi run lain'
              f' pada {kalah[pr]} dari {sah} seed')
    if rinci:
        print(f'\n   {"seed":>6} {"objektif":<22} {"dikalahkan oleh":<22}'
              f' {"Z sendiri":>11} {"Z penantang":>12}')
        for r in rinci:
            print(f'   {r["seed"]:>6} {M.NAMA_PROFIL[r["objektif"]]:<22}'
                  f' {M.NAMA_PROFIL[r["dikalahkan_oleh"]]:<22}'
                  f' {r["Z_sendiri"]:>11.6f} {r["Z_penantang"]:>12.6f}')

    return {"baris": hasil, "irisan_ketiga": len(semua),
            "terpilih": {k: sorted(v) for k, v in terpilih.items()},
            "silang": {"seed_sah": sah, "kalah": kalah, "rinci": rinci}}


# ---------------------------------------------------------------- percobaan D
def percobaan_d(bobot, n_seed, hari):
    """Skenario cuaca. Saklar w adalah parameter masukan, bukan variabel keputusan."""
    print("\n\nPercobaan D: skenario cuaca")
    print("=" * 92)
    print("w = 0 mengabaikan cuaca, w = 1 menerapkan koreksi (2.2) penuh.")
    contoh = DS.muat_dataset(jumlah_hari=hari, cuaca_aktif=0)
    rho = list(contoh["rho"].values())
    print(f"Sebaran rho pada dataset ini: min {min(rho):.4f}, rata {st.mean(rho):.4f}, "
          f"maks {max(rho):.4f}.")
    print(f"Karena gamma paling besar 1, penurunan skor terbesar yang mungkin pada "
          f"w = 1 hanya {max(rho) * 100:.1f} persen.")
    print(f"\n   {'w':>4} {'skor rata dataset':>19} {'Z rata':>10} {'dest':>6} "
          f"{'skor terpilih':>14} {'destinasi berubah':>19}")

    hasil, terpilih = [], {}
    for w in (0, 1):
        data = DS.muat_dataset(jumlah_hari=hari, cuaca_aktif=w)
        rata_dataset = st.mean(data["s_bar"].values())
        z, dest, skor = [], [], []
        for k in range(n_seed):
            out = PSO.jalankan_pso(data, ANGGARAN, bobot, seed=SEED_AWAL + k)
            sol = out["solusi"]
            ter = [i for i in data["P"] if sol["pilih"].get(i)]
            z.append(out["hasil"]["Z"])
            dest.append(len(ter))
            skor.append(sum(data["s_bar"][i, sol["hari"][i]] for i in ter))
            if k == 0:
                terpilih[w] = set(ter)
        beda = "-" if w == 0 else str(len(terpilih[0] ^ terpilih[1]))
        print(f"   {w:>4} {rata_dataset:>19.4f} {st.mean(z):>10.6f} {st.mean(dest):>6.1f} "
              f"{st.mean(skor):>14.2f} {beda:>19}")
        hasil.append({"w": w, "skor_rata_dataset": round(rata_dataset, 4),
                      "Z": _rangkum(z), "destinasi_rata": round(st.mean(dest), 1),
                      "skor_rata": round(st.mean(skor), 2)})

    print(f"\n   destinasi yang pilihannya berubah: {len(terpilih[0] ^ terpilih[1])}")
    return {"baris": hasil, "destinasi_berubah": len(terpilih[0] ^ terpilih[1])}


def main():
    mulai = time.perf_counter()
    cepat = "--cepat" in sys.argv
    n_seed = 3 if cepat else JUMLAH_SEED
    # Tiap percobaan bisa dijalankan sendiri, misalnya "penyetelan.py c",
    # supaya satu tabel Bab IV dapat dibangkitkan ulang tanpa mengulang
    # seluruh sapuan yang memakan waktu puluhan menit.
    semua = ("a", "b", "c", "d")
    pilih = tuple(h for h in semua if h in sys.argv[1:]) or semua
    bobot = M.PROFIL_BOBOT["seimbang"]
    # Sebelum pemuatan, sebab rho diambil pada jendela aktivitas.
    M.atur_waktu(beta=BETA_SKENARIO)
    data = DS.muat_dataset(jumlah_hari=JUMLAH_HARI)

    print(f"dataset   : {os.path.basename(data['data_path'])}")
    print(f"kandidat  : {len(data['P'])} destinasi, {len(data['H'])} akomodasi")
    print(f"kuota     : {M.BETA:.0f} menit, jendela "
          f"{M.T_MULAI // 60}.00 sampai {M.T_SELESAI // 60}.00")
    print(f"anggaran  : Rp{ANGGARAN:,}   hari: {JUMLAH_HARI}")
    print(f"seed      : {SEED_AWAL} sampai {SEED_AWAL + n_seed - 1}")
    print()

    a = percobaan_a(data, bobot, n_seed) if "a" in pilih else None
    b = percobaan_b(data, bobot, n_seed) if "b" in pilih else None
    c = percobaan_c(data, n_seed) if "c" in pilih else None
    d = percobaan_d(bobot, n_seed, JUMLAH_HARI) if "d" in pilih else None

    os.makedirs(FOLDER, exist_ok=True)
    cap = datetime.now().strftime("%Y%m%d_%H%M%S")
    tanda = "" if pilih == semua else "_" + "".join(pilih)
    path = os.path.join(FOLDER, f"penyetelan{tanda}_{cap}.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"dataset": data["data_path"], "anggaran": ANGGARAN,
                   "anggaran_ketat": ANGGARAN_KETAT, "hari": JUMLAH_HARI,
                   "seed_awal": SEED_AWAL, "jumlah_seed": n_seed,
                   "bawaan_pso": {"inersia": PSO.INERSIA, "c1": PSO.C1, "c2": PSO.C2,
                                  "partikel": PSO.JUMLAH_PARTIKEL,
                                  "iterasi": PSO.MAKS_ITERASI},
                   "percobaan_a": a, "percobaan_b": b,
                   "percobaan_c": c, "percobaan_d": d},
                  f, indent=2, ensure_ascii=False, default=str)
    print(f"\nhasil disimpan: {path}")
    print(f"total waktu jalan: {time.perf_counter() - mulai:.1f} detik")
    return 0


if __name__ == "__main__":
    sys.exit(main())
