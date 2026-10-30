"""
Particle Swarm Optimization, metode utama.

Pengodean random key: satu partikel adalah vektor riil 0..1 sepanjang |P| + |H|
ditambah satu kunci pembagi kota. Kunci destinasi menentukan prioritas pemilihan,
kunci akomodasi menentukan hotel mana yang dipakai di kota itu.

Partikel tidak menyimpan itinerary, melainkan prioritas yang diterjemahkan jadi
itinerary. Yang bergerak di ruang pencarian nilai kuncinya, dan itulah yang
mengubah urutan, bukan sebaliknya.

Kota tempat menginap tiap malam dipilih kunci malam tersendiri, terpisah dari
kota destinasi hari itu. Dengan begitu menginap di satu kota sambil berwisata ke
kota lain berada di dalam ruang pencarian.

Hasil opsi A, diputuskan 22 Oktober 2026 dan dipertahankan.

Selisih terhadap optimum Gurobi, rata lima seed:

    subset     sebelum    sesudah
     8 dest    +8,830%    +0,397%
    10 dest    +8,829%    +0,193%
    12 dest    +0,526%    +0,459%

Dataset penuh 90 destinasi, 15 seed:

               sebelum     sesudah
    rata       0,319683    0,319675
    median     0,317593    0,317582
    stdev      0,007523    0,006192
    terbaik    0,311185    0,310677
    terburuk   0,338581    0,332870

Subset 12 nyaris tidak bergeser, dan itu memang diharapkan: optimumnya di situ
berbentuk terbagi dua kota, jadi sudah terwakili sejak dulu. Pada dataset penuh
mutunya tidak berubah sementara sebarannya menyempit.

Persamaan: (2.20) fitness, (2.21) dan (2.22) pembaruan kecepatan dan posisi.
"""

import random
import time
from copy import deepcopy

import model as M


# -- pengaturan --
# Disapu penyetelan.py Percobaan A, dataset penuh, 10 seed per konfigurasi.
# Satu faktor pada satu waktu di sekitar nilai di bawah ini.
#
# Jumlah partikel adalah satu-satunya yang pengaruhnya nyata. Polanya monoton
# 15 -> 0,334006, 20 -> 0,331535, 30 -> 0,328043, 50 -> 0,320288, lalu naik
# lagi pada 80 -> 0,322318. Uji berpasangan pada sepuluh seed yang sama
# memberi 50 partikel unggul pada 8 dari 10 seed, perbaikan rata 2,36 persen,
# t = -2,50 terhadap ambang 2,26. Tipis tetapi searah, dan simpangan bakunya
# ikut mengecil dari 0,008 ke 0,005.
#
# Tetap dipakai 30, bukan 50, karena ongkos waktunya 9,4 detik lawan 5,2 detik.
# Aplikasi web menjalankan tiga profil pada satu permintaan, sehingga pilihan
# itu berarti menunggu 28 detik alih-alih 16 detik untuk perbaikan 2,36 persen.
# Angka 50 tetap dilaporkan pada Bab IV sebagai nilai terbaik yang terukur.
JUMLAH_PARTIKEL = 30

# Tiga tetapan berikut disapu pada rentang yang sama dan selisih antarnilainya
# 0,0005 sampai 0,003, sementara simpangan baku antar seed 0,007. Jadi tidak
# ada nilai yang terbukti lebih baik; seluruhnya tenggelam dalam derau.
# Nilai di bawah ini dipertahankan sebagai nilai lazim pada pustaka PSO.
#
# Iterasi hampir tidak berpengaruh karena SABAR menghentikan lebih dulu:
# pada batas 120 hanya 75,8 iterasi yang benar-benar terpakai.
MAKS_ITERASI = 60
INERSIA = 0.72
C1 = 1.45
C2 = 1.45
SEED = 42


def seed_pengguna(nomor):
    """Persamaan (3.6). Nomor urut pengguna dipakai langsung sebagai seed.

    Tujuannya bukan keacakan yang lebih baik, melainkan agar satu pengguna
    memperoleh itinerary yang sama setiap kali meminta dengan masukan yang
    sama, sementara dua pengguna berbeda memperoleh titik awal pencarian
    yang berbeda. Tanpa itu seluruh pengguna berbagi satu seed tetap dan
    menerima rekomendasi yang identik.
    """
    nomor = int(nomor)
    if nomor < 1:
        raise ValueError(f"Nomor pengguna harus bilangan bulat positif: {nomor}")
    return nomor
BATAS_POSISI = (0.0, 1.0)
BATAS_KECEPATAN = (-0.25, 0.25)

# Berhenti lebih awal bila global best tidak membaik selama sekian iterasi.
SABAR = 20


KUNCI_PEMBAGI = "pembagi_kota"


def kunci_malam(d):
    """Nama kunci pemilih kota tempat menginap pada malam ke-d."""
    return ("malam", d)


def _kunci_awal(data, rng):
    """Kunci prioritas tiap destinasi, tiap akomodasi, dan titik pembagi kota.

    Kunci pembagi menentukan berapa hari pertama masuk kota pertama. Dibuat
    sebagai kunci sendiri, bukan diturunkan dari rata-rata kunci destinasi, supaya
    jumlah malam di tiap kota ikut dicari optimizer. Biaya akomodasi bergantung
    langsung pada pembagian itu, jadi menurunkannya dari kunci destinasi membuat
    pembagian hari buta terhadap harga hotel.

    Kunci malam, satu untuk tiap malam, memilih kota tempat menginap terlepas
    dari kota destinasi hari itu. Jumlahnya m, bukan |H| x m: yang dipilih kunci
    ini hanya kotanya, sedangkan hotel mana di kota itu tetap ditentukan kunci
    akomodasi. Versi |H| x m sudah pernah dicoba dan memperburuk hasil, karena
    ruang pencariannya membesar tanpa panduan.
    """
    kunci = {n: rng.random() for n in data["P"] + data["H"]}
    kunci[KUNCI_PEMBAGI] = rng.random()
    for d in data["D"]:
        kunci[kunci_malam(d)] = rng.random()
    return kunci


def inisialisasi_partikel(data, jumlah, seed):
    """Membangkitkan kawanan awal: posisi dan kecepatan acak tiap partikel.

    Seed diteruskan ke satu objek Random supaya seluruh pembangkitan dapat
    diulang. Personal best mula-mula diisi posisi awal dengan fitness tak
    hingga, sehingga penilaian pertama pasti memperbaikinya.
    """
    rng = random.Random(seed)
    partikel = []
    for _ in range(jumlah):
        posisi = _kunci_awal(data, rng)
        kecepatan = {n: rng.uniform(*BATAS_KECEPATAN) for n in posisi}
        partikel.append({
            "posisi": posisi,
            "kecepatan": kecepatan,
            "pbest_posisi": dict(posisi),
            "pbest_fitness": float("inf"),
        })
    return partikel


# -- penerjemahan --
def _rencana_kota(data, posisi):
    """Kota untuk setiap hari.

    Dua kota dibagi jadi dua blok hari berurutan supaya wisatawan tidak bolak-balik.

    Batas yang perlu dicatat: tiap kota dijamin dapat minimal satu hari, jadi pola
    menginap di satu kota sambil menjelajah kota lain tidak bisa diwakili pengodean
    ini sama sekali.
    """
    kota = data["kota"]
    m = data["m"]
    if len(kota) == 1:
        return {d: kota[0] for d in data["D"]}

    rata = {}
    for k in kota:
        nilai = [posisi[i] for i in data["P"] if data["node"][i]["kota"] == k]
        rata[k] = sum(nilai) / len(nilai) if nilai else 0.0

    # kota berprioritas lebih tinggi ditempatkan lebih dulu
    urut = sorted(kota, key=lambda k: -rata[k])

    batas = 1 + int(posisi[KUNCI_PEMBAGI] * (m - 1))
    batas = max(1, min(m - 1, batas))
    return {d: (urut[0] if d <= batas else urut[1]) for d in data["D"]}


def _kota_menginap(data, posisi):
    """Kota tempat menginap tiap malam, dari kunci malam masing-masing.

    Terpisah dari kota destinasi hari itu. Inilah yang membuat pola menginap di
    satu kota sambil berwisata ke kota lain dapat diwakili.
    """
    kota = data["kota"]
    if len(kota) == 1:
        return {d: kota[0] for d in data["D"]}
    hasil = {}
    for d in data["D"]:
        k = int(posisi[kunci_malam(d)] * len(kota))
        hasil[d] = kota[min(k, len(kota) - 1)]
    return hasil


def _pilih_hotel(data, posisi, kota_menginap):
    """Akomodasi tiap malam: kotanya dari kunci malam, hotelnya dari kunci akomodasi.

    Kota tempat menginap tidak lagi mengikuti kota destinasi hari itu, sehingga
    pengguna boleh tidur di satu kota sambil berwisata ke kota lain, dan boleh
    berganti hotel antar malam.
    """
    node = data["node"]
    hotel = {}
    terbaik_kota = {}
    for k in data["kota"]:
        kandidat = [h for h in data["H"] if node[h]["kota"] == k]
        if kandidat:
            terbaik_kota[k] = max(kandidat, key=lambda h: posisi[h])
    for d in data["D"]:
        hotel[d] = terbaik_kota.get(kota_menginap[d])
    return hotel


def _panjang_rute(data, urutan):
    t_mat = data["t"]
    return sum(t_mat[urutan[k], urutan[k + 1]] for k in range(len(urutan) - 1))


def terjemahkan(data, posisi, anggaran, kunci=None, tolak=None,
                minimum_kategori=None, kategori_wajib=None):
    """Kunci partikel jadi itinerary lengkap, lalu diperbaiki.

    Perbaikan dulu baru penilaian. Menilai solusi mentah akan menghukum partikel
    atas pelanggaran yang sebenarnya masih bisa diatasi, jadi partikel menjauh
    dari wilayah yang justru menjanjikan.
    """
    kunci = set(kunci or [])
    tolak = set(tolak or [])
    node = data["node"]

    kota_hari = _rencana_kota(data, posisi)
    hotel = _pilih_hotel(data, posisi, _kota_menginap(data, posisi))

    solusi = M.solusi_kosong(data)
    solusi["hotel"] = hotel

    # Persamaan (2.18b): destinasi yang ditolak tidak boleh masuk daftar kandidat.
    # Persamaan (2.18a): destinasi terkunci diberi prioritas tertinggi mutlak.
    def prioritas(i):
        return (0 if i in kunci else 1, -posisi[i])

    # Hari dikelompokkan menurut kota, lalu destinasi disebarkan ke seluruh hari
    # kota tersebut, bukan mengisi hari satu per satu sampai penuh. Kalau diisi
    # satu per satu, hari pertama menghabiskan seluruh destinasi kota itu dan hari
    # berikutnya bisa benar-benar kosong.
    m = data["m"]
    hari_kota = {}
    for d in data["D"]:
        if hotel[d] is not None and hotel[M.malam_akhir(d, m)] is not None:
            hari_kota.setdefault(kota_hari[d], []).append(d)

    isi_hari = {d: [] for d in data["D"]}

    def sisa_waktu(d):
        if not isi_hari[d]:
            return M.BETA
        rute = M.rute_tetangga_terdekat(data, hotel[d], hotel[M.malam_akhir(d, m)], isi_hari[d])
        return M.BETA - M.durasi_hari(data, rute, d)

    for kota, daftar_hari in hari_kota.items():
        kandidat = sorted(
            (i for i in data["P"] if node[i]["kota"] == kota and i not in tolak),
            key=prioritas,
        )
        for i in kandidat:
            # hari dengan sisa waktu terbanyak dicoba lebih dulu, supaya muatan merata
            for d in sorted(daftar_hari, key=lambda x: -sisa_waktu(x)):
                calon = M.rute_tetangga_terdekat(data, hotel[d], hotel[M.malam_akhir(d, m)],
                                       isi_hari[d] + [i])
                _, selesai, langgar = M.jadwal_hari(data, calon, d)
                if selesai - M.T_MULAI > M.BETA or langgar:
                    continue
                isi_hari[d].append(i)
                break

    for d in data["D"]:
        awal, akhir = hotel[d], hotel[M.malam_akhir(d, m)]
        if awal is None or akhir is None:
            continue
        if isi_hari[d]:
            solusi["rute"][d] = M.rute_tetangga_terdekat(data, awal, akhir, isi_hari[d])
            for i in isi_hari[d]:
                solusi["pilih"][i] = 1
                solusi["hari"][i] = d
        else:
            solusi["rute"][d] = [awal, akhir]

    _perbaiki_kunci(data, solusi, kunci, kota_hari)
    M.pangkas_sampai_anggaran(data, solusi, anggaran)
    M.penuhi_kategori(data, solusi, minimum_kategori, kategori_wajib, kota_hari)

    for d in data["D"]:
        urutan = solusi["rute"].get(d) or []
        if len(urutan) >= 2:
            tiba, _, _ = M.jadwal_hari(data, urutan, d)
            solusi["tiba"].update(tiba)
    return solusi


def _perbaiki_kunci(data, solusi, kunci, kota_hari):
    """Memaksa destinasi terkunci masuk, menggeser destinasi berskor terendah bila perlu."""
    node = data["node"]
    for i in kunci:
        if solusi["pilih"].get(i):
            continue
        hari_cocok = [d for d in data["D"] if kota_hari[d] == node[i]["kota"]]
        if not hari_cocok:
            hari_cocok = list(data["D"])
        disisipkan = False
        for d in hari_cocok:
            urutan = solusi["rute"].get(d) or []
            if len(urutan) < 2:
                continue
            isi = [n for n in urutan if n in data["tau"]]
            calon_isi = isi + [i]
            while True:
                calon = M.rute_tetangga_terdekat(data, urutan[0], urutan[-1], calon_isi)
                _, selesai, langgar = M.jadwal_hari(data, calon, d)
                muat = selesai - M.T_MULAI <= M.BETA and not langgar
                if muat or len(calon_isi) <= 1:
                    break
                # buang destinasi berskor terendah yang tidak terkunci
                buang = [x for x in calon_isi if x != i and x not in kunci]
                if not buang:
                    break
                keluar = min(buang, key=lambda x: data["s_bar"][x, d])
                calon_isi.remove(keluar)
                solusi["pilih"][keluar] = 0
                solusi["hari"].pop(keluar, None)
            if muat:
                solusi["rute"][d] = calon
                solusi["pilih"][i] = 1
                solusi["hari"][i] = d
                disisipkan = True
                break
        if not disisipkan:
            # dibiarkan tidak terpilih, penalti pada fitness yang akan menandainya
            continue


# -- Persamaan (2.21) dan (2.22) --
def perbarui_partikel(partikel, gbest_posisi, rng, inersia=INERSIA, c1=C1, c2=C2):
    """r1 dan r2 diundi ulang untuk setiap dimensi pada setiap iterasi.

    Inilah sebabnya setiap kunci bergerak dengan besar yang berbeda meskipun
    menghadap pbest dan gbest yang sama.
    """
    lo, hi = BATAS_POSISI
    vlo, vhi = BATAS_KECEPATAN
    for p in partikel:
        for n in p["posisi"]:
            r1, r2 = rng.random(), rng.random()
            v = (
                inersia * p["kecepatan"][n]
                + c1 * r1 * (p["pbest_posisi"][n] - p["posisi"][n])
                + c2 * r2 * (gbest_posisi[n] - p["posisi"][n])
            )
            v = max(vlo, min(vhi, v))
            p["kecepatan"][n] = v
            p["posisi"][n] = max(lo, min(hi, p["posisi"][n] + v))


def jalankan_pso(data, anggaran, bobot, kunci=None, tolak=None,
                 minimum_kategori=None, kategori_wajib=None,
                 jumlah_partikel=JUMLAH_PARTIKEL, maks_iterasi=MAKS_ITERASI,
                 seed=SEED, cetak=False, kabar=None,
                 inersia=INERSIA, c1=C1, c2=C2, bobot_penalti=None):
    """Menjalankan PSO.

    kabar(iterasi, maks, gbest) dipanggil tiap iterasi kalau diberikan. Dipakai
    antarmuka web karena satu kali jalan pada dataset penuh makan puluhan detik.

    bobot_penalti menggantikan lambda 5 sampai lambda 10 pada (2.20). Dipakai
    percobaan penyetelan untuk mengukur seberapa besar penalti perlu dibuat.

    inersia, c1, dan c2 diteruskan ke perbarui_partikel. Ketiganya dibuat parameter
    supaya penyetelan parameter dapat menyapu beberapa nilai dalam satu kali jalan,
    tanpa menyunting konstanta modul dan menjalankan ulang.
    """
    mulai = time.perf_counter()
    rng = random.Random(seed)
    partikel = inisialisasi_partikel(data, jumlah_partikel, seed)

    gbest_posisi = dict(partikel[0]["posisi"])
    gbest_solusi = None
    gbest_hasil = None
    gbest_fitness = float("inf")
    riwayat = []
    tanpa_perbaikan = 0

    for iterasi in range(maks_iterasi):
        for p in partikel:
            solusi = terjemahkan(data, p["posisi"], anggaran, kunci, tolak,
                                 minimum_kategori, kategori_wajib)
            hasil = M.fitness(data, solusi, anggaran, bobot, minimum_kategori,
                              kategori_wajib, bobot_penalti)
            F = hasil["F"]
            if F < p["pbest_fitness"]:
                p["pbest_fitness"] = F
                p["pbest_posisi"] = dict(p["posisi"])
            if F < gbest_fitness - 1e-12:
                gbest_fitness = F
                gbest_posisi = dict(p["posisi"])
                gbest_solusi = deepcopy(solusi)
                gbest_hasil = hasil
                tanpa_perbaikan = 0

        riwayat.append(gbest_fitness)
        if kabar is not None:
            kabar(iterasi + 1, maks_iterasi, gbest_fitness)
        tanpa_perbaikan += 1
        if tanpa_perbaikan > SABAR:
            break
        perbarui_partikel(partikel, gbest_posisi, rng, inersia, c1, c2)

    ok, pesan_validasi = M.validasi_solusi(data, gbest_solusi, kunci, tolak)
    keluaran = {
        "metode": "PSO",
        "solusi": gbest_solusi,
        "hasil": gbest_hasil,
        "fitness": gbest_fitness,
        "riwayat": riwayat,
        "iterasi_terpakai": len(riwayat),
        "runtime": time.perf_counter() - mulai,
        "seed": seed,
        "validasi_ok": ok,
        "validasi_pesan": pesan_validasi,
    }
    if cetak:
        cetak_hasil(data, keluaran)
    return keluaran


def cetak_hasil(data, keluaran):
    """Mencetak itinerary hasil PSO beserta jumlah iterasi, seed, dan runtime.
    """
    M.cetak_itinerary(data, keluaran["solusi"], keluaran["hasil"],
                      judul=f"Itinerary hasil {keluaran['metode']}")
    print(f"  iterasi terpakai   : {keluaran['iterasi_terpakai']}")
    print(f"  seed               : {keluaran['seed']}")
    print(f"  runtime            : {keluaran['runtime']:.3f} detik")
    print(f"  validasi struktur  : {'LOLOS' if keluaran['validasi_ok'] else 'GAGAL'}")
    for p in keluaran["validasi_pesan"]:
        print(f"    - {p}")


if __name__ == "__main__":
    import dataset as DS

    d = DS.muat_dataset(jumlah_hari=3)
    jalankan_pso(d, anggaran=3_000_000, bobot=M.PROFIL_BOBOT["seimbang"], cetak=True)
