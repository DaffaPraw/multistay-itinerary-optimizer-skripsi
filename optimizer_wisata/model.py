"""
Inti model: representasi solusi dan fungsi objektif.

Dipakai bersama PSO, CWS, dan MILP supaya ketiganya dinilai dengan rumus yang
sama persis. Kalau tiap metode menghitung objektifnya sendiri, perbedaan hasil
bisa berasal dari perbedaan rumus, bukan dari kemampuan metodenya.

Representasi solusi:
    pilih  : {i: 0 atau 1}       destinasi i masuk itinerary, variabel v pada model
    hari   : {i: d}              hari kunjungan destinasi terpilih, variabel y
    hotel  : {d: h} untuk d di D, akomodasi malam ke-d, variabel z
                                 Malam ke-d adalah malam menjelang hari ke-d.
    rute   : {d: [node, ...]}    urutan node hari d, diawali hotel malam d dan
                                 diakhiri hotel malam d+1, variabel x. Hari
                                 terakhir kembali ke hotel malam m.
    tiba   : {(i, d): menit}     waktu kedatangan, variabel a

Persamaan yang diterapkan di berkas ini:
    (2.1), (2.1a) sampai (2.1h)  fungsi objektif ternormalkan min-max
    (2.11), (2.11a)              malam tempat rute harian berakhir

Penalti batasan dan fungsi fitness belum ada di sini.
"""
import dataset

# -- pengaturan --
T_MULAI = 8 * 60      # Tabel 2.9, jam mulai aktivitas harian
T_SELESAI = 20 * 60   # jam selesai aktivitas harian
BETA = 600.0          # kuota waktu aktivitas harian dalam menit

# Persamaan (2.1). Empat bobot kepentingan, jumlahnya wajib satu.
# Nilai setiap profil ditetapkan lewat pengujian awal Bab IV.
PROFIL_BOBOT = {
    "hemat":     {"lambda1": 0.15, "lambda2": 0.10, "lambda3": 0.45, "lambda4": 0.30},
    "seimbang":  {"lambda1": 0.30, "lambda2": 0.20, "lambda3": 0.30, "lambda4": 0.20},
    "maksimal":  {"lambda1": 0.45, "lambda2": 0.30, "lambda3": 0.15, "lambda4": 0.10},
}

NAMA_PROFIL = {
    "hemat": "Hemat",
    "seimbang": "Seimbang",
    "maksimal": "Maksimal Pengalaman",
}

TOLERANSI = 1e-9


def malam_akhir(d, m):
    """Malam tempat rute hari ke-d berakhir, (2.11) dan (2.11a).

    Hari d berangkat dari akomodasi malam d dan berakhir di malam d+1. Hari
    terakhir tidak punya malam berikutnya, jadi kembali ke tempat berangkatnya.
    """
    return d + 1 if d < m else m


def periksa_bobot(bobot):
    """Bobot objektif wajib tidak negatif dan berjumlah satu, sesuai Persamaan (2.1)."""
    nilai = [bobot["lambda1"], bobot["lambda2"], bobot["lambda3"], bobot["lambda4"]]
    if any(v < 0 for v in nilai):
        raise ValueError(f"Bobot objektif tidak boleh negatif: {bobot}")
    if abs(sum(nilai) - 1.0) > 1e-6:
        raise ValueError(f"Bobot objektif harus berjumlah satu, sekarang {sum(nilai):.6f}")


# -- perhitungan waktu --
def jadwal_hari(data, urutan, d):
    """Waktu tiba, waktu selesai, dan jumlah pelanggaran jam operasional.

    Urutan sudah memuat hotel di awal dan akhir. Tiba sebelum jam buka berarti
    menunggu, dan waktu tunggunya ikut dihitung sebagai pemakaian kuota hari.
    """
    t_mat, tau, jam = data["t"], data["tau"], data["jam"]
    sekarang = float(T_MULAI)
    tiba = {}
    langgar_jam = 0

    for k in range(len(urutan) - 1):
        u, v = urutan[k], urutan[k + 1]
        sekarang += t_mat[u, v]
        if v in tau:      # v adalah destinasi, bukan akomodasi
            buka, tutup = jam[v]
            if sekarang < buka:
                sekarang = float(buka)        # menunggu sampai buka
            tiba[v, d] = sekarang
            if sekarang + tau[v] > tutup + TOLERANSI:
                langgar_jam += 1
            sekarang += tau[v]

    return tiba, sekarang, langgar_jam


def durasi_hari(data, urutan, d):
    _, selesai, _ = jadwal_hari(data, urutan, d)
    return selesai - T_MULAI


# -- Persamaan (2.1) --
def komponen_objektif(data, solusi):
    """Empat komponen objektif pada satuan aslinya, belum dinormalkan.

        L_P, L_H : kerugian mutu destinasi dan akomodasi, poin skor
        C_H, C_T : biaya akomodasi dan transportasi, rupiah
    """
    P, D = data["P"], data["D"]
    s_bar, u, p, g = data["s_bar"], data["u"], data["p"], data["g"]
    pilih, hari, hotel, rute = solusi["pilih"], solusi["hari"], solusi["hotel"], solusi["rute"]

    # kerugian mutu destinasi. Destinasi yang tidak dipilih menyumbang 10 penuh,
    # yaitu skor maksimum yang tidak terpakai.
    L_P = 0.0
    for i in P:
        diperoleh = s_bar[i, hari[i]] if pilih.get(i) and i in hari else 0.0
        L_P += 10.0 - diperoleh

    # kerugian mutu akomodasi, atas seluruh malam menginap
    L_H = sum(10.0 - u[hotel[d]] for d in D if hotel.get(d) is not None)

    C_H = sum(p[hotel[d]] for d in D if hotel.get(d) is not None)

    C_T = 0.0
    for d, urutan in rute.items():
        for k in range(len(urutan) - 1):
            C_T += g[urutan[k], urutan[k + 1]]

    return {
        "L_P": L_P,
        "L_H": L_H,
        "C_H": C_H,
        "C_T": C_T,
        "biaya_hotel": C_H,
        "biaya_transport": C_T,
    }


def batas_komponen(data, anggaran=None):
    """Batas tiap suku objektif, Persamaan (2.1b) sampai (2.1h).

    Diturunkan dari isi dataset dan jumlah hari, bukan dari hasil optimasi, jadi
    nilainya tetap dan bisa ditulis sebagai konstanta di laporan.

        L_P : terkecil bila setiap destinasi dikunjungi pada hari terbaiknya,
              terbesar bila tidak satu pun destinasi dipilih
        L_H : terkecil bila akomodasi berskor tertinggi dipakai setiap malam,
              terbesar bila akomodasi berskor terendah dipakai setiap malam
        C_H : terkecil bila akomodasi termurah dipakai setiap malam, terbesar bila
              akomodasi termahal dipakai setiap malam tetapi dipotong anggaran,
              karena solusi yang melanggar (2.17) tidak sah sehingga batas di atas
              anggaran tidak pernah dapat dicapai
        C_T : terkecil nol bila tidak ada perpindahan, terbesar bila seluruh kuota
              waktu harian dipakai berkendara pada kecepatan antarkota

    Banyaknya malam sama dengan banyaknya hari, yaitu m, karena malam ke-d adalah
    malam menjelang hari ke-d dan setelah hari terakhir pengguna langsung pulang.
    """
    P, D, m = data["P"], data["D"], data["m"]
    s_bar, u, p = data["s_bar"], data["u"], data["p"]

    lp_min = sum(10.0 - max(s_bar[i, d] for d in D) for i in P)
    lp_maks = 10.0 * len(P)

    lh_min = m * (10.0 - max(u.values()))
    lh_maks = m * (10.0 - min(u.values()))

    ch_min = m * min(p.values())
    ch_maks = m * max(p.values())
    if anggaran is not None:
        ch_maks = min(ch_maks, float(anggaran))

    # kuota waktu harian diubah menjadi jarak maksimum yang mungkin ditempuh
    km_maks = len(D) * (BETA / 60.0) * dataset.KECEPATAN_ANTARKOTA_KMJAM
    ct_min = 0.0
    ct_maks = km_maks / dataset.KBBM * dataset.HBBM

    return {
        "L_P": (lp_min, lp_maks),
        "L_H": (lh_min, lh_maks),
        "C_H": (ch_min, ch_maks),
        "C_T": (ct_min, ct_maks),
    }


SUKU = ("L_P", "L_H", "C_H", "C_T")
BOBOT_SUKU = {"L_P": "lambda1", "L_H": "lambda2", "C_H": "lambda3", "C_T": "lambda4"}


def normalisasi_komponen(komponen, batas):
    """Persamaan (2.1a), (2.1c), (2.1e), (2.1g). Min-max tiap suku.

        X_topi = (X - X_min) / (X_max - X_min)

    Hasilnya tanpa satuan, 0..1, supaya suku poin skor dan suku rupiah bisa
    dijumlahkan setara. Dipotong ke 0..1 supaya pembulatan yang sedikit melampaui
    batas tidak membuat Z keluar rentang.
    """
    topi = {}
    for k in SUKU:
        lo, hi = batas[k]
        rentang = hi - lo
        nilai = (komponen[k] - lo) / rentang if rentang > TOLERANSI else 0.0
        topi[k] = min(max(nilai, 0.0), 1.0)
    return topi


def nilai_objektif(data, solusi, anggaran, bobot):
    """Persamaan (2.1). Jumlah berbobot empat suku ternormalkan.

        Z = l1*L_P_topi + l2*L_H_topi + l3*C_H_topi + l4*C_T_topi

    Tiap suku 0..1 dan jumlah bobot 1, jadi Z juga 0..1.

    Lambda di sini bobot kepentingan pengguna, bukan pengali penyetara satuan;
    penyetaraan satuan sudah dikerjakan normalisasi.
    """
    periksa_bobot(bobot)
    k = komponen_objektif(data, solusi)
    batas = batas_komponen(data, anggaran)
    topi = normalisasi_komponen(k, batas)
    k["Z"] = sum(bobot[BOBOT_SUKU[nama]] * topi[nama] for nama in SUKU)
    k["topi"] = topi
    k["batas"] = batas
    return k


def solusi_kosong(data):
    return {
        "pilih": {i: 0 for i in data["P"]},
        "hari": {},
        "hotel": {d: None for d in data["D"]},
        "rute": {d: [] for d in data["D"]},
        "tiba": {},
    }
