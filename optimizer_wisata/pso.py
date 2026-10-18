"""
Particle Swarm Optimization, metode utama.

Pengodean random key: satu partikel adalah vektor riil 0..1 sepanjang |P| + |H|
ditambah satu kunci pembagi kota. Kunci destinasi menentukan prioritas pemilihan,
kunci akomodasi menentukan hotel mana yang dipakai di kota itu.

Partikel tidak menyimpan itinerary, melainkan prioritas yang diterjemahkan jadi
itinerary. Yang bergerak di ruang pencarian nilai kuncinya, dan itulah yang
mengubah urutan, bukan sebaliknya.

Yang ada di berkas ini baru pengodean dan penerjemahan. Perbaikan solusi,
pembaruan kecepatan (2.21) dan posisi (2.22), serta kalang swarm belum ada.
"""

import random

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
    """Kunci partikel jadi itinerary lengkap."""
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

    for d in data["D"]:
        urutan = solusi["rute"].get(d) or []
        if len(urutan) >= 2:
            tiba, _, _ = M.jadwal_hari(data, urutan, d)
            solusi["tiba"].update(tiba)
    return solusi


if __name__ == "__main__":
    import dataset as DS

    d = DS.muat_dataset(jumlah_hari=3)
    bobot = M.PROFIL_BOBOT["seimbang"]
    anggaran = 3_000_000

    kawanan = inisialisasi_partikel(d, JUMLAH_PARTIKEL, SEED)
    print(f"{JUMLAH_PARTIKEL} partikel, {len(kawanan[0]['posisi'])} kunci per partikel")
    print(f"seed {SEED}\n")

    nilai = []
    for k, p in enumerate(kawanan, start=1):
        solusi = terjemahkan(d, p["posisi"], anggaran)
        hasil = M.fitness(d, solusi, anggaran, bobot)
        ok, _ = M.validasi_solusi(d, solusi)
        nilai.append((hasil["F"], hasil["Z"], hasil["layak"], ok,
                      sum(solusi["pilih"].values())))

    layak = sum(1 for v in nilai if v[2])
    print(f"partikel layak        : {layak} dari {len(nilai)}")
    print(f"struktur solusi lolos : {sum(1 for v in nilai if v[3])} dari {len(nilai)}")
    print(f"F terbaik             : {min(v[0] for v in nilai):.6f}")
    print(f"F terburuk            : {max(v[0] for v in nilai):.6f}")
    print(f"Z terbaik             : {min(v[1] for v in nilai):.6f}")
    print(f"destinasi terpilih    : {min(v[4] for v in nilai)} sampai {max(v[4] for v in nilai)}")
