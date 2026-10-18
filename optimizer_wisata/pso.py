"""
Particle Swarm Optimization, metode utama.

Pengodean random key: satu partikel adalah vektor riil 0..1 sepanjang |P| + |H|
ditambah satu kunci pembagi kota. Kunci destinasi menentukan prioritas pemilihan,
kunci akomodasi menentukan hotel mana yang dipakai di kota itu.

Partikel tidak menyimpan itinerary, melainkan prioritas yang diterjemahkan jadi
itinerary. Yang bergerak di ruang pencarian nilai kuncinya, dan itulah yang
mengubah urutan, bukan sebaliknya.

Persamaan: (2.20) fitness, (2.21) dan (2.22) pembaruan kecepatan dan posisi.
"""

import random
import time
from copy import deepcopy

import model as M


# -- pengaturan --
JUMLAH_PARTIKEL = 30
MAKS_ITERASI = 60
INERSIA = 0.72
C1 = 1.45
C2 = 1.45
SEED = 42
BATAS_POSISI = (0.0, 1.0)
BATAS_KECEPATAN = (-0.25, 0.25)

# Berhenti lebih awal bila global best tidak membaik selama sekian iterasi.
SABAR = 20


KUNCI_PEMBAGI = "pembagi_kota"


def _kunci_awal(data, rng):
    """Kunci prioritas tiap destinasi, tiap akomodasi, dan titik pembagi kota.

    Kunci pembagi menentukan berapa hari pertama masuk kota pertama. Dibuat
    sebagai kunci sendiri, bukan diturunkan dari rata-rata kunci destinasi, supaya
    jumlah malam di tiap kota ikut dicari optimizer. Biaya akomodasi bergantung
    langsung pada pembagian itu, jadi menurunkannya dari kunci destinasi membuat
    pembagian hari buta terhadap harga hotel.
    """
    kunci = {n: rng.random() for n in data["P"] + data["H"]}
    kunci[KUNCI_PEMBAGI] = rng.random()
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


def _pilih_hotel(data, posisi, kota_hari):
    """Akomodasi tiap malam, dari kunci akomodasi berkunci tertinggi di kota itu.

    Malam d mengikuti kota hari d, jadi wisatawan tidak pindah hotel selama masih
    di kota yang sama.
    """
    node = data["node"]
    hotel = {}
    terbaik_kota = {}
    for k in data["kota"]:
        kandidat = [h for h in data["H"] if node[h]["kota"] == k]
        if kandidat:
            terbaik_kota[k] = max(kandidat, key=lambda h: posisi[h])
    for d in data["D"]:
        hotel[d] = terbaik_kota.get(kota_hari[d])
    return hotel


def _rute_terdekat(data, awal, akhir, destinasi):
    """Menyusun rute satu hari dengan tetangga terdekat."""
    t_mat = data["t"]
    belum = list(destinasi)
    urutan = [awal]
    kini = awal
    while belum:
        nxt = min(belum, key=lambda v: (t_mat[kini, v], v))
        urutan.append(nxt)
        belum.remove(nxt)
        kini = nxt
    urutan.append(akhir)
    return urutan


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
    hotel = _pilih_hotel(data, posisi, kota_hari)

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
        rute = _rute_terdekat(data, hotel[d], hotel[M.malam_akhir(d, m)], isi_hari[d])
        return M.BETA - M.durasi_hari(data, rute, d)

    for kota, daftar_hari in hari_kota.items():
        kandidat = sorted(
            (i for i in data["P"] if node[i]["kota"] == kota and i not in tolak),
            key=prioritas,
        )
        for i in kandidat:
            # hari dengan sisa waktu terbanyak dicoba lebih dulu, supaya muatan merata
            for d in sorted(daftar_hari, key=lambda x: -sisa_waktu(x)):
                calon = _rute_terdekat(data, hotel[d], hotel[M.malam_akhir(d, m)],
                                       isi_hari[d] + [i])
                _, selesai, langgar = M.jadwal_hari(data, calon, d)
                if selesai - M.T_MULAI > M.BETA or selesai > M.T_SELESAI or langgar:
                    continue
                isi_hari[d].append(i)
                break

    for d in data["D"]:
        awal, akhir = hotel[d], hotel[M.malam_akhir(d, m)]
        if awal is None or akhir is None:
            continue
        if isi_hari[d]:
            solusi["rute"][d] = _rute_terdekat(data, awal, akhir, isi_hari[d])
            for i in isi_hari[d]:
                solusi["pilih"][i] = 1
                solusi["hari"][i] = d
        else:
            solusi["rute"][d] = [awal, akhir]

    _perbaiki_kunci(data, solusi, kunci, kota_hari)
    _perbaiki_anggaran(data, solusi, anggaran)
    _perbaiki_kategori(data, solusi, minimum_kategori, kategori_wajib, kota_hari)

    for d in data["D"]:
        urutan = solusi["rute"].get(d) or []
        if len(urutan) >= 2:
            tiba, _, _ = M.jadwal_hari(data, urutan, d)
            solusi["tiba"].update(tiba)
    return solusi


def _susun_ulang_hari(data, solusi, d):
    """Menyusun ulang rute hari d dari isi yang sekarang, ujungnya dipertahankan.

    Dipakai sesudah perbaikan membuang destinasi, karena rute yang tinggal
    sebagian urutannya belum tentu masih yang terbaik.
    """
    urutan = solusi["rute"].get(d) or []
    if len(urutan) < 2:
        return
    isi = [n for n in urutan if n in data["tau"]]
    solusi["rute"][d] = _rute_terdekat(data, urutan[0], urutan[-1], isi)


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
                calon = _rute_terdekat(data, urutan[0], urutan[-1], calon_isi)
                _, selesai, langgar = M.jadwal_hari(data, calon, d)
                muat = selesai - M.T_MULAI <= M.BETA and selesai <= M.T_SELESAI and not langgar
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


def _perbaiki_anggaran(data, solusi, anggaran):
    """Membuang destinasi paling tidak efisien sampai biaya total masuk anggaran."""
    f, s_bar = data["f"], data["s_bar"]
    for _ in range(len(data["P"])):
        pen = M.hitung_penalti(data, solusi, anggaran)
        if pen["lebih_anggaran"] <= M.TOLERANSI:
            return
        terpilih = [i for i in data["P"] if solusi["pilih"].get(i)]
        if not terpilih:
            return
        # rasio skor terhadap biaya, yang terkecil dibuang lebih dulu
        keluar = min(terpilih, key=lambda i: s_bar[i, solusi["hari"][i]] / (f[i] + 1.0))
        d = solusi["hari"][keluar]
        solusi["pilih"][keluar] = 0
        solusi["hari"].pop(keluar, None)
        solusi["rute"][d] = [n for n in solusi["rute"][d] if n != keluar]
        _susun_ulang_hari(data, solusi, d)


def _perbaiki_kategori(data, solusi, minimum_kategori, kategori_wajib, kota_hari):
    """Menyisipkan destinasi berskor tertinggi dari kategori yang belum terwakili."""
    if not kategori_wajib:
        return
    node = data["node"]
    minimum_kategori = minimum_kategori or {}
    for kat in kategori_wajib:
        butuh = minimum_kategori.get(kat, 1)
        while True:
            terpilih = [i for i in data["P"] if solusi["pilih"].get(i)]
            ada = sum(1 for i in terpilih if node[i]["kategori"] == kat)
            if ada >= butuh:
                break
            kandidat = [i for i in data["P"]
                        if node[i]["kategori"] == kat and not solusi["pilih"].get(i)]
            if not kandidat:
                break
            masuk = max(kandidat, key=lambda i: data["s"][i])
            hari_cocok = [d for d in data["D"] if kota_hari[d] == node[masuk]["kota"]]
            berhasil = False
            for d in hari_cocok or data["D"]:
                urutan = solusi["rute"].get(d) or []
                if len(urutan) < 2:
                    continue
                isi = [n for n in urutan if n in data["tau"]] + [masuk]
                calon = _rute_terdekat(data, urutan[0], urutan[-1], isi)
                _, selesai, langgar = M.jadwal_hari(data, calon, d)
                if selesai - M.T_MULAI <= M.BETA and selesai <= M.T_SELESAI and not langgar:
                    solusi["rute"][d] = calon
                    solusi["pilih"][masuk] = 1
                    solusi["hari"][masuk] = d
                    berhasil = True
                    break
            if not berhasil:
                break


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
                 seed=SEED, cetak=False, kabar=None):
    """Menjalankan PSO.

    kabar(iterasi, maks, gbest) dipanggil tiap iterasi kalau diberikan. Dipakai
    antarmuka web karena satu kali jalan pada dataset penuh makan puluhan detik.
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
            hasil = M.fitness(data, solusi, anggaran, bobot, minimum_kategori, kategori_wajib)
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
        perbarui_partikel(partikel, gbest_posisi, rng)

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
