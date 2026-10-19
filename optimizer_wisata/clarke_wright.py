"""
Clarke-Wright Savings, heuristik pembanding.

Kerangka sepuluh langkahnya mengikuti subbab 2.5 proposal, isinya disesuaikan
karena node di sini destinasi wisata dan akomodasi, bukan depot dan pelanggan.

Sepuluh langkah:
     1. Menyaring destinasi dan akomodasi sesuai kota, kategori, dan agama pengguna.
     2. Memilih akomodasi dan subset destinasi berdasarkan rasio skor terkoreksi
        cuaca terhadap durasi kunjungan.
     3. Memeriksa cakupan kategori dan kota, menyisipkan destinasi berskor tertinggi
        dari kategori yang belum terwakili.
     4. Mengalokasikan destinasi terpilih ke hari perjalanan sesuai kuota waktu.
     5. Membentuk rute awal terpisah untuk tiap destinasi dari akomodasi hari itu.
     6. Menghitung nilai penghematan seluruh pasangan destinasi, Persamaan (2.19).
     7. Mengurutkan pasangan menurut penghematan dari besar ke kecil.
     8. Menggabungkan pasangan berpenghematan tertinggi selama batasan terpenuhi.
     9. Mengulangi langkah delapan sampai seluruh pasangan selesai diproses.
    10. Menghitung nilai objektif dan memvalidasi kelayakan solusi akhir.

Kompromi di langkah 2: skor terkoreksi cuaca butuh hari kunjungan, padahal hari
baru ditetapkan di langkah 4. Jadi langkah 2 memakai rata-rata presipitasi
sepanjang perjalanan sebagai pendekatan. Setelah hari ditetapkan skornya dihitung
ulang dengan rho hari itu, dan nilai itulah yang dipakai di langkah 10.

Selisih antara rata-rata dan nilai harian ini salah satu sumber perbedaan hasil
terhadap PSO, yang menetapkan hari dan menilai skor pada hari yang sama.
"""

import time

import dataset as DS
import model as M


def skor_praalokasi(data):
    """Skor terkoreksi memakai rata-rata presipitasi sepanjang perjalanan.

    Hanya untuk langkah 2 dan 3, saat hari kunjungan belum ditetapkan.
    """
    hasil = {}
    for i in data["P"]:
        nilai = [data["rho"][i, d] for d in data["D"]]
        rho_rata = sum(nilai) / len(nilai) if nilai else 0.0
        hasil[i] = DS.skor_terkoreksi(data["s"][i], data["gamma"][i], rho_rata)
    return hasil


def penghematan(data, awal, i, j):
    """Persamaan (2.19). Penghematan waktu bila i dan j digabung dalam satu rute."""
    t = data["t"]
    return t[awal, i] + t[j, awal] - t[i, j]


def jalankan_cws(data, anggaran, bobot, kunci=None, tolak=None,
                 minimum_kategori=None, kategori_wajib=None, cetak=False):
    """Menjalankan Clarke-Wright Savings, sepuluh langkah subbab 2.5.

    Urutan pengerjaannya tidak sama dengan urutan nomor langkahnya.
    Langkah 3, pemenuhan cakupan kategori, dikerjakan paling akhir karena
    penyisipan destinasi baru perlu tahu kuota waktu mana yang masih
    tersisa, dan itu baru diketahui setelah hari ditetapkan di langkah 4.

    Mengembalikan dict berisi solusi, hasil penilaian, nilai fitness,
    runtime, dan status validasi struktur.
    """
    mulai = time.perf_counter()
    kunci = set(kunci or [])
    tolak = set(tolak or [])
    node, tau = data["node"], data["tau"]

    # ---------- langkah 1: penyaringan sudah dilakukan saat pemuatan dataset
    kandidat = [i for i in data["P"] if i not in tolak]

    # ---------- langkah 2: peringkat berdasarkan rasio skor terkoreksi terhadap durasi
    s_pra = skor_praalokasi(data)
    rasio = {i: s_pra[i] / tau[i] if tau[i] > 0 else 0.0 for i in kandidat}
    # destinasi terkunci diberi prioritas mutlak, Persamaan (2.18a)
    urut = sorted(kandidat, key=lambda i: (0 if i in kunci else 1, -rasio[i], i))

    # ---------- pemilihan akomodasi: termurah relatif terhadap skor utilitasnya,
    # dipilih per kota supaya wisatawan tidak berpindah hotel di kota yang sama
    hotel_kota = {}
    for k in data["kota"]:
        calon = [h for h in data["H"] if node[h]["kota"] == k]
        if calon:
            hotel_kota[k] = min(calon, key=lambda h: data["p"][h] / max(data["u"][h], 1e-9))

    # ---------- langkah 4 bagian pertama: pembagian hari menurut kota
    kota_urut = sorted(data["kota"], key=lambda k: -sum(rasio[i] for i in urut if node[i]["kota"] == k))
    m = data["m"]
    if len(kota_urut) == 1:
        kota_hari = {d: kota_urut[0] for d in data["D"]}
    else:
        batas = max(1, m // 2)
        kota_hari = {d: (kota_urut[0] if d <= batas else kota_urut[1]) for d in data["D"]}

    hotel = {d: hotel_kota.get(kota_hari[d]) for d in data["D"]}

    solusi = M.solusi_kosong(data)
    solusi["hotel"] = hotel

    # ---------- langkah 4 dan 5, dikerjakan per hari
    for d in data["D"]:
        awal, akhir = hotel[d], hotel[M.malam_akhir(d, m)]
        if awal is None or akhir is None:
            continue
        tersedia = [i for i in urut
                    if node[i]["kota"] == kota_hari[d] and not solusi["pilih"][i]]

        # langkah 5: satu rute pulang pergi terpisah untuk tiap destinasi
        milik = {i: idx for idx, i in enumerate(tersedia)}
        segmen = {idx: [i] for idx, i in enumerate(tersedia)}

        # langkah 6 dan 7: penghematan seluruh pasangan, diurutkan menurun.
        # Pasangan berarah, bukan kombinasi, karena matriks waktu tempuh tidak
        # simetris sehingga menggabung i-j tidak sama dengan j-i.
        pasangan = []
        for a in range(len(tersedia)):
            for b in range(len(tersedia)):
                if a == b:
                    continue
                i, j = tersedia[a], tersedia[b]
                pasangan.append((penghematan(data, awal, i, j), i, j))
        pasangan.sort(key=lambda x: (-x[0], x[1], x[2]))

        # langkah 8 dan 9: penggabungan selama seluruh batasan masih terpenuhi
        for nilai, i, j in pasangan:
            if nilai <= 0:
                break
            si, sj = milik.get(i), milik.get(j)
            if si is None or sj is None or si == sj:
                continue
            # hanya ujung yang boleh disambung: i di akhir segmennya, j di awal
            if segmen[si][-1] != i or segmen[sj][0] != j:
                continue
            gabung = segmen[si] + segmen[sj]
            calon = M.rute_tetangga_terdekat(data, awal, akhir, gabung)
            layak, _ = M.hari_muat(data, calon, d)
            if not layak:
                continue
            segmen[si] = gabung
            for n in segmen[sj]:
                milik[n] = si
            del segmen[sj]

        # segmen terpanjang yang masih muat dipakai sebagai rute hari ini
        terbaik, isi_terbaik = None, []
        for idx, isi in segmen.items():
            calon = M.rute_tetangga_terdekat(data, awal, akhir, isi)
            layak, _ = M.hari_muat(data, calon, d)
            if layak and len(isi) > len(isi_terbaik):
                terbaik, isi_terbaik = calon, isi

        # sisa kapasitas hari diisi destinasi berperingkat tertinggi yang masih muat
        if terbaik is None:
            terbaik, isi_terbaik = [awal, akhir], []
        for i in tersedia:
            if i in isi_terbaik:
                continue
            calon = M.rute_tetangga_terdekat(data, awal, akhir, isi_terbaik + [i])
            layak, _ = M.hari_muat(data, calon, d)
            if layak:
                terbaik, isi_terbaik = calon, isi_terbaik + [i]

        solusi["rute"][d] = terbaik
        for i in isi_terbaik:
            solusi["pilih"][i] = 1
            solusi["hari"][i] = d

    # ---------- langkah 3, dikerjakan setelah hari ditetapkan supaya penyisipan
    # kategori tetap memperhatikan kuota waktu yang tersisa
    M.penuhi_kategori(data, solusi, minimum_kategori, kategori_wajib, kota_hari)
    M.pangkas_sampai_anggaran(data, solusi, anggaran)

    for d in data["D"]:
        urutan = solusi["rute"].get(d) or []
        if len(urutan) >= 2:
            tiba, _, _ = M.jadwal_hari(data, urutan, d)
            solusi["tiba"].update(tiba)

    # ---------- langkah 10: penilaian memakai skor terkoreksi per hari yang sebenarnya
    hasil = M.fitness(data, solusi, anggaran, bobot, minimum_kategori, kategori_wajib)
    ok, pesan = M.validasi_solusi(data, solusi, kunci, tolak)

    keluaran = {
        "metode": "Clarke-Wright Savings",
        "solusi": solusi,
        "hasil": hasil,
        "fitness": hasil["F"],
        "runtime": time.perf_counter() - mulai,
        "validasi_ok": ok,
        "validasi_pesan": pesan,
    }
    if cetak:
        M.cetak_itinerary(data, solusi, hasil, judul="Itinerary hasil Clarke-Wright Savings")
        print(f"  runtime            : {keluaran['runtime']:.3f} detik")
        print(f"  validasi struktur  : {'LOLOS' if ok else 'GAGAL'}")
        for p in pesan:
            print(f"    - {p}")
    return keluaran


if __name__ == "__main__":
    d = DS.muat_dataset(jumlah_hari=3)
    jalankan_cws(d, anggaran=3_000_000, bobot=M.PROFIL_BOBOT["seimbang"], cetak=True)
