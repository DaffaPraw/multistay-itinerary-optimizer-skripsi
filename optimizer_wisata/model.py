"""
Inti model: fungsi objektif, penalti, dan pemeriksaan kelayakan.

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
    (2.7a)                       cakupan kategori
    (2.7b)                       cakupan kota
    (2.11), (2.11a)              malam tempat rute harian berakhir
    (2.12)                       kuota waktu aktivitas harian
    (2.14)                       jam operasional destinasi
    (2.15)                       aktivitas selesai sebelum jendela harian tutup
    (2.17)                       batasan anggaran
    (2.18a), (2.18b)             penguncian dan penolakan destinasi
    (2.20)                       fungsi fitness
"""
from copy import deepcopy

import dataset

# -- pengaturan --
# Jendela aktivitas harian [Ts, Te] pada Tabel 2.9, diambil dari dataset supaya
# tidak bisa berbeda dengan jendela yang dipakai saat menghitung rho.
T_MULAI = dataset.JAM_MULAI_AKTIVITAS * 60
T_SELESAI = dataset.JAM_SELESAI_AKTIVITAS * 60
# Kuota waktu aktivitas harian beta, dalam menit. Tabel 2.9 memperlakukannya
# sebagai parameter masukan dan tidak menetapkan nilainya, jadi angka di bawah
# hanya nilai bawaan.
BETA = 600.0


def atur_waktu(beta=None, jam_mulai=None, jam_selesai=None):
    """Menetapkan kuota harian dan jendela aktivitas, naskah paragraf 448.

    Naskah memperlakukan ketiganya sebagai parameter masukan pengguna, bukan
    tetapan program. Nilainya diubah di tingkat modul, bukan dialirkan sebagai
    argumen, karena ketiganya dibaca dari lebih dari dua puluh tempat pada
    model.py, pso.py, milp_gurobi.py, dan peladen web. Pola ini sudah dipakai
    lampiran_rekayasa.py yang menetapkan kuota 280 menit untuk Tabel L3.2.

    PENTING: panggil sebelum muat_dataset. Probabilitas presipitasi rho
    diambil sebagai nilai terbesar pada jendela aktivitas, dan penyaringan
    jamnya terjadi saat dataset dimuat. Mengubah jendela sesudahnya membuat
    rho tidak lagi sesuai jendela yang berlaku.
    """
    global BETA, T_MULAI, T_SELESAI
    if jam_mulai is not None or jam_selesai is not None:
        mulai = int(jam_mulai if jam_mulai is not None else dataset.JAM_MULAI_AKTIVITAS)
        selesai = int(jam_selesai if jam_selesai is not None else dataset.JAM_SELESAI_AKTIVITAS)
        if not 0 <= mulai < selesai <= 24:
            raise ValueError(
                f"Jendela aktivitas tidak masuk akal: {mulai} sampai {selesai}.")
        dataset.JAM_MULAI_AKTIVITAS = mulai
        dataset.JAM_SELESAI_AKTIVITAS = selesai
        T_MULAI = mulai * 60
        T_SELESAI = selesai * 60
    if beta is not None:
        beta = float(beta)
        if beta <= 0:
            raise ValueError(f"Kuota harian harus positif: {beta}")
        if beta > T_SELESAI - T_MULAI:
            raise ValueError(
                f"Kuota harian {beta:.0f} menit melebihi lebar jendela aktivitas "
                f"{T_SELESAI - T_MULAI:.0f} menit, sehingga tidak pernah mengikat.")
        BETA = beta
    return {"beta": BETA, "T_MULAI": T_MULAI, "T_SELESAI": T_SELESAI}

# Persamaan (2.1). Empat bobot kepentingan, jumlahnya wajib satu.
#
# Diperiksa penyetelan.py Percobaan C pada dataset penuh, 10 seed tiap profil.
# Ketiganya benar-benar menggeser pilihan, bukan sekadar menggeser nilai Z:
# hanya 2 dari 90 destinasi yang dipilih oleh ketiga profil. Hemat menekan
# biaya 26 persen dibanding Seimbang, Rp982.366 lawan Rp1.324.488, dengan
# skor hanya 1,5 persen lebih rendah, 190,10 lawan 193,00.
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

# Persamaan (2.20). Bobot penalti lambda 5 sampai lambda 10.
# Nilainya sengaja jauh lebih besar daripada rentang Z, yang tidak pernah melebihi
# satu karena keempat komponennya ternormalkan. Dengan begitu keuntungan terbesar
# yang bisa diperoleh dari melanggar suatu batasan selalu lebih kecil daripada penaltinya.
#
# Disapu penyetelan.py Percobaan B pada tiga tingkat keketatan anggaran, 10 seed.
# Seluruh bobot mulai 1,0 ke atas memberi hasil identik sampai enam angka
# desimal, baik pada anggaran longgar, ketat, maupun mustahil. Hanya 0,1 yang
# menyimpang, dan di situ pencarian berani masuk wilayah melanggar lebih jauh.
#
# Jadi 10,0 bukan hasil optimasi melainkan satu titik pada dataran luas. Yang
# perlu dipenuhi hanya cukup besar, bukan nilai tertentu. Pada anggaran
# Rp700.000 tidak satu pun dari 10 seed menghasilkan solusi layak berapa pun
# bobotnya, sebab penalti tidak dapat membuat masalah yang mustahil jadi mungkin.
BOBOT_PENALTI = {
    "lambda5": 10.0,    # pelampauan anggaran
    "lambda6": 10.0,    # pelanggaran jam operasional
    "lambda7": 10.0,    # pelampauan kuota waktu harian
    "lambda8": 10.0,    # kunjungan ganda
    "lambda9": 10.0,    # kategori belum terwakili
    "lambda10": 10.0,   # kota belum terwakili
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


# -- penalti (2.20) --
def hitung_penalti(data, solusi, anggaran, minimum_kategori=None, kategori_wajib=None):
    """Menghitung keenam jenis pelanggaran pada Persamaan (2.20)."""
    P, D = data["P"], data["D"]
    node, f, tau = data["node"], data["f"], data["tau"]
    pilih, rute = solusi["pilih"], solusi["rute"]
    terpilih = [i for i in P if pilih.get(i)]

    pesan = []

    # biaya total, Persamaan (2.17): tiket, akomodasi, bahan bakar
    k = komponen_objektif(data, solusi)
    biaya_tiket = sum(f[i] for i in terpilih)
    biaya_total = biaya_tiket + k["biaya_hotel"] + k["biaya_transport"]
    lebih_anggaran = max(0.0, biaya_total - anggaran)
    if lebih_anggaran > TOLERANSI:
        pesan.append(f"Anggaran terlampaui sebesar Rp{lebih_anggaran:,.0f}.")

    # jam operasional (2.14), kuota waktu harian (2.12), dan batas tutup
    # jendela aktivitas (2.15)
    langgar_jam = 0
    langgar_kuota = 0
    for d in D:
        urutan = rute.get(d) or []
        if len(urutan) < 2:
            continue
        _, selesai, jam_langgar = jadwal_hari(data, urutan, d)
        langgar_jam += jam_langgar
        # Pemakaian dihitung dari awal sampai akhir hari, jadi waktu menunggu
        # jam buka ikut terhitung. Lebih ketat daripada bunyi (2.12) yang hanya
        # menjumlah durasi kunjungan dan waktu tempuh, tetapi menunggu di depan
        # gerbang memang memakai hari pengguna.
        pakai = selesai - T_MULAI
        if pakai > BETA + TOLERANSI:
            langgar_kuota += 1
            pesan.append(f"Hari {d} memakai {pakai:.0f} menit, melebihi kuota {BETA:.0f} menit.")
        if selesai > T_SELESAI + TOLERANSI:
            langgar_kuota += 1
            pesan.append(f"Hari {d} selesai pukul {selesai / 60:.2f}, melewati jam selesai aktivitas.")
    if langgar_jam:
        pesan.append(f"{langgar_jam} kunjungan berada di luar jam operasional destinasi.")

    # kunjungan ganda: satu destinasi muncul lebih dari sekali di seluruh rute
    muncul = {}
    for d in D:
        for n in (rute.get(d) or []):
            if n in tau:
                muncul[n] = muncul.get(n, 0) + 1
    langgar_ganda = sum(c - 1 for c in muncul.values() if c > 1)
    if langgar_ganda:
        pesan.append(f"{langgar_ganda} destinasi dikunjungi lebih dari satu kali.")

    # cakupan kategori, Persamaan (2.7a)
    langgar_kategori = 0
    if kategori_wajib:
        minimum_kategori = minimum_kategori or {}
        for kat in kategori_wajib:
            butuh = minimum_kategori.get(kat, 1)
            ada = sum(1 for i in terpilih if node[i]["kategori"] == kat)
            if ada < butuh:
                langgar_kategori += butuh - ada
                pesan.append(f"Kategori {kat} baru terwakili {ada} dari {butuh}.")

    # Cakupan kota, Persamaan (2.7b). Yang dihitung hanya destinasi; akomodasi
    # tidak membuat sebuah kota dianggap terkunjungi, karena menginap bukan
    # berwisata.
    langgar_kota = 0
    for kota in data["kota"]:
        if not any(node[i]["kota"] == kota for i in terpilih):
            langgar_kota += 1
            pesan.append(f"Kota {kota} tidak terwakili satu destinasi pun.")

    return {
        "biaya_tiket": biaya_tiket,
        "biaya_total": biaya_total,
        "lebih_anggaran": lebih_anggaran,
        "N_operasional": langgar_jam,
        "N_waktu": langgar_kuota,
        "N_ganda": langgar_ganda,
        "N_kategori": langgar_kategori,
        "N_kota": langgar_kota,
        "pesan": pesan,
    }


def fitness(data, solusi, anggaran, bobot, minimum_kategori=None, kategori_wajib=None,
            bobot_penalti=None):
    """Persamaan (2.20). Nilai objektif ditambah seluruh penalti.

    Penting: pelampauan anggaran dibagi anggaran dulu. Tanpa itu sukunya bersatuan
    rupiah sementara Z tidak bersatuan, jadi tidak bisa dijumlahkan bermakna.
    """
    bp = bobot_penalti or BOBOT_PENALTI
    k = nilai_objektif(data, solusi, anggaran, bobot)
    pen = hitung_penalti(data, solusi, anggaran, minimum_kategori, kategori_wajib)

    F = (
        k["Z"]
        + bp["lambda5"] * (pen["lebih_anggaran"] / anggaran if anggaran > 0 else 0.0)
        + bp["lambda6"] * pen["N_operasional"]
        + bp["lambda7"] * pen["N_waktu"]
        + bp["lambda8"] * pen["N_ganda"]
        + bp["lambda9"] * pen["N_kategori"]
        + bp["lambda10"] * pen["N_kota"]
    )

    hasil = {**k, **pen, "F": F}
    hasil["layak"] = (
        pen["lebih_anggaran"] <= TOLERANSI
        and pen["N_operasional"] == 0
        and pen["N_waktu"] == 0
        and pen["N_ganda"] == 0
        and pen["N_kategori"] == 0
        and pen["N_kota"] == 0
    )
    return hasil


# -- validasi solusi --
def validasi_solusi(data, solusi, kunci=None, tolak=None):
    """Konsistensi struktur solusi, terpisah dari penilaian mutunya.

    Penalti menilai seberapa baik; ini memeriksa apakah bentuknya masuk akal
    sebagai itinerary, misalnya rute hari d berawal dan berakhir di akomodasi
    yang benar.
    """
    galat = []
    P, D, m = data["P"], data["D"], data["m"]
    pilih, hari, hotel, rute = solusi["pilih"], solusi["hari"], solusi["hotel"], solusi["rute"]

    for d in D:
        if hotel.get(d) is None:
            galat.append(f"Malam {d} tidak punya akomodasi.")
        elif hotel[d] not in data["H"]:
            galat.append(f"Akomodasi malam {d} bukan kandidat yang sah: {hotel[d]}.")

    for d in D:
        urutan = rute.get(d)
        if not urutan:
            galat.append(f"Hari {d} tidak punya rute.")
            continue
        if urutan[0] != hotel.get(d):
            galat.append(f"Hari {d} tidak berawal dari akomodasi malam {d}.")
        akhir = malam_akhir(d, m)
        if urutan[-1] != hotel.get(akhir):
            galat.append(f"Hari {d} tidak berakhir pada akomodasi malam {akhir}.")

    terpilih = {i for i in P if pilih.get(i)}
    di_rute = {n for d in D for n in (rute.get(d) or []) if n in data["tau"]}
    if terpilih != di_rute:
        hanya_pilih = sorted(terpilih - di_rute)
        hanya_rute = sorted(di_rute - terpilih)
        if hanya_pilih:
            galat.append(f"Destinasi dipilih tetapi tidak ada di rute: {hanya_pilih}.")
        if hanya_rute:
            galat.append(f"Destinasi ada di rute tetapi tidak ditandai dipilih: {hanya_rute}.")

    for i in terpilih:
        if i not in hari:
            galat.append(f"Destinasi {i} dipilih tetapi tidak punya hari kunjungan.")
        elif rute.get(hari[i]) is None or i not in rute[hari[i]]:
            galat.append(f"Destinasi {i} ditandai hari {hari[i]} tetapi tidak ada di rute hari itu.")

    # Persamaan (2.18a) dan (2.18b)
    for i in (kunci or []):
        if i not in terpilih:
            galat.append(f"Destinasi terkunci {i} tidak masuk itinerary.")
    for i in (tolak or []):
        if i in terpilih:
            galat.append(f"Destinasi yang ditolak {i} masih masuk itinerary.")

    return not galat, galat


# -- rutin bersama CWS dan PSO --
# Ditaruh di sini, bukan disalin ke tiap metode, supaya keduanya memperbaiki
# solusi dengan cara yang sama persis. Kalau salinannya terpisah dan menyimpang,
# sebagian selisih hasil antar metode akan berasal dari perbedaan cara
# memperbaiki, bukan dari kemampuan pencariannya.
def rute_tetangga_terdekat(data, awal, akhir, isi):
    """Mengurutkan isi satu hari dengan tetangga terdekat, ujungnya tetap.

    Awal dan akhir adalah akomodasi dan posisinya tidak digeser.
    """
    t_mat = data["t"]
    belum = list(isi)
    urutan = [awal]
    kini = awal
    while belum:
        nxt = min(belum, key=lambda v: (t_mat[kini, v], v))
        urutan.append(nxt)
        belum.remove(nxt)
        kini = nxt
    urutan.append(akhir)
    return urutan


def hari_muat(data, urutan, d):
    """Apakah rute hari d masih layak, beserta waktu selesainya.

    Tiga hal diperiksa sekaligus: kuota waktu harian (2.12), batas tutup jendela
    aktivitas (2.15), dan jam operasional destinasi (2.14).
    """
    _, selesai, langgar = jadwal_hari(data, urutan, d)
    muat = (selesai - T_MULAI <= BETA and selesai <= T_SELESAI and langgar == 0)
    return muat, selesai


def susun_ulang_hari(data, solusi, d):
    """Menyusun ulang rute hari d dari isi yang sekarang, ujungnya dipertahankan."""
    urutan = solusi["rute"].get(d) or []
    if len(urutan) < 2:
        return
    isi = [n for n in urutan if n in data["tau"]]
    solusi["rute"][d] = rute_tetangga_terdekat(data, urutan[0], urutan[-1], isi)


def _ujung_rute_ikut_hotel(data, solusi):
    """Menyusun ulang seluruh rute supaya ujungnya mengikuti akomodasi yang berlaku.

    Dipanggil sesudah akomodasi diganti. Rute hari d berawal di akomodasi malam d
    dan berakhir di akomodasi malam berikutnya, jadi mengganti satu malam
    menyentuh dua hari sekaligus.
    """
    m = data["m"]
    for d in data["D"]:
        urutan = solusi["rute"].get(d) or []
        if len(urutan) < 2:
            continue
        awal = solusi["hotel"].get(d)
        akhir = solusi["hotel"].get(malam_akhir(d, m))
        if awal is None or akhir is None:
            continue
        isi = [n for n in urutan if n in data["tau"]]
        solusi["rute"][d] = rute_tetangga_terdekat(data, awal, akhir, isi)


def ganti_akomodasi_lebih_murah(data, solusi, anggaran):
    """Mengganti akomodasi dengan yang lebih murah di kota yang sama (2.17).

    Dicoba sebelum destinasi dibuang, karena akomodasi yang mendominasi biaya.
    Membuang destinasi dulu bisa menghabiskan seluruh itinerary dan tetap
    melampaui anggaran, sebab harga kamar tidak pernah ikut berkurang.

    Penggantian yang membuat salah satu hari tidak lagi muat dibatalkan, karena
    akomodasi yang lebih murah dapat berada jauh dari destinasi hari itu.
    """
    node, harga = data["node"], data["p"]
    for _ in range(len(data["D"]) * max(1, len(data["H"]))):
        pen = hitung_penalti(data, solusi, anggaran)
        if pen["lebih_anggaran"] <= TOLERANSI:
            return
        calon = []
        for d in data["D"]:
            kini = solusi["hotel"].get(d)
            if kini is None:
                continue
            for h in data["H"]:
                if h != kini and node[h]["kota"] == node[kini]["kota"] and harga[h] < harga[kini]:
                    calon.append((harga[kini] - harga[h], d, h))
        if not calon:
            return
        calon.sort(key=lambda x: (-x[0], x[1], x[2]))

        diterima = False
        for _hemat, d, h in calon:
            uji = deepcopy(solusi)
            uji["hotel"][d] = h
            _ujung_rute_ikut_hotel(data, uji)
            if all(hari_muat(data, uji["rute"][x], x)[0]
                   for x in data["D"] if len(uji["rute"].get(x) or []) >= 2):
                solusi["hotel"] = uji["hotel"]
                solusi["rute"] = uji["rute"]
                diterima = True
                break
        if not diterima:
            return


def _biaya_tanpa_destinasi(data, solusi):
    """Biaya yang tersisa seandainya seluruh destinasi dibuang.

    Yaitu harga kamar seluruh malam ditambah bahan bakar perpindahan antar
    akomodasi. Inilah lantai biaya yang tidak dapat diturunkan dengan membuang
    destinasi, berapa pun banyaknya.
    """
    kosong = deepcopy(solusi)
    for i in data["P"]:
        kosong["pilih"][i] = 0
    kosong["hari"] = {}
    m = data["m"]
    for d in data["D"]:
        awal = kosong["hotel"].get(d)
        akhir = kosong["hotel"].get(malam_akhir(d, m))
        kosong["rute"][d] = [awal, akhir] if awal and akhir else []
    k = komponen_objektif(data, kosong)
    return k["biaya_hotel"] + k["biaya_transport"]


def pangkas_sampai_anggaran(data, solusi, anggaran):
    """Membuang destinasi paling tidak efisien sampai biaya masuk anggaran (2.17).

    Yang dibuang lebih dulu adalah destinasi dengan rasio skor terhadap harga
    tiket terkecil, yaitu yang paling sedikit memberi mutu per rupiah. Rute hari
    yang bersangkutan disusun ulang sesudahnya, karena urutan yang tersisa belum
    tentu masih yang terbaik.

    Penggantian akomodasi ke yang lebih murah dicoba lebih dulu, karena harga
    kamar mendominasi biaya dan membuang destinasi saja tidak pernah
    menguranginya.
    """
    f, s_bar = data["f"], data["s_bar"]

    # Akomodasi hanya ditinjau ulang bila membuang seluruh destinasi pun tidak
    # cukup. Dengan begitu jalur lama tidak berubah sama sekali pada kasus yang
    # memang sudah bisa diselesaikan dengan membuang destinasi saja.
    if _biaya_tanpa_destinasi(data, solusi) > anggaran + TOLERANSI:
        ganti_akomodasi_lebih_murah(data, solusi, anggaran)

    for _ in range(len(data["P"])):
        pen = hitung_penalti(data, solusi, anggaran)
        if pen["lebih_anggaran"] <= TOLERANSI:
            return
        terpilih = [i for i in data["P"] if solusi["pilih"].get(i)]
        if not terpilih:
            break
        keluar = min(terpilih, key=lambda i: s_bar[i, solusi["hari"][i]] / (f[i] + 1.0))
        d = solusi["hari"][keluar]
        solusi["pilih"][keluar] = 0
        solusi["hari"].pop(keluar, None)
        solusi["rute"][d] = [n for n in solusi["rute"][d] if n != keluar]
        susun_ulang_hari(data, solusi, d)

    # Dicoba sekali lagi di akhir. Penggantian akomodasi yang tadi ditolak karena
    # harinya masih penuh bisa jadi layak sesudah destinasi berkurang.
    if hitung_penalti(data, solusi, anggaran)["lebih_anggaran"] > TOLERANSI:
        ganti_akomodasi_lebih_murah(data, solusi, anggaran)


def penuhi_kategori(data, solusi, minimum_kategori, kategori_wajib, kota_hari):
    """Menyisipkan destinasi berskor tertinggi dari kategori yang belum terwakili (2.7a).

    Hari yang dicoba lebih dulu adalah hari yang kotanya cocok dengan destinasi
    itu. Kalau tidak ada hari yang masih muat, penyisipan dihentikan dan penalti
    pada fitness yang akan menandainya.
    """
    if not kategori_wajib:
        return
    node = data["node"]
    minimum_kategori = minimum_kategori or {}
    for kat in kategori_wajib:
        butuh = minimum_kategori.get(kat, 1)
        while True:
            terpilih = [i for i in data["P"] if solusi["pilih"].get(i)]
            if sum(1 for i in terpilih if node[i]["kategori"] == kat) >= butuh:
                break
            calon = [i for i in data["P"]
                     if node[i]["kategori"] == kat and not solusi["pilih"].get(i)]
            if not calon:
                break
            masuk = max(calon, key=lambda i: data["s"][i])
            hari_cocok = [x for x in data["D"] if kota_hari[x] == node[masuk]["kota"]]
            berhasil = False
            for d in hari_cocok or data["D"]:
                urutan = solusi["rute"].get(d) or []
                if len(urutan) < 2:
                    continue
                isi = [n for n in urutan if n in data["tau"]] + [masuk]
                baru = rute_tetangga_terdekat(data, urutan[0], urutan[-1], isi)
                muat, _ = hari_muat(data, baru, d)
                if muat:
                    solusi["rute"][d] = baru
                    solusi["pilih"][masuk] = 1
                    solusi["hari"][masuk] = d
                    berhasil = True
                    break
            if not berhasil:
                break


def solusi_kosong(data):
    """Solusi kosong yang bentuknya sudah benar.

    Belum memilih destinasi maupun akomodasi, jadi tidak layak. Dipakai
    sebagai titik awal yang diisi bertahap oleh setiap metode.
    """
    return {
        "pilih": {i: 0 for i in data["P"]},
        "hari": {},
        "hotel": {d: None for d in data["D"]},
        "rute": {d: [] for d in data["D"]},
        "tiba": {},
    }


def _jam(menit):
    """Menit sejak tengah malam jadi teks jam.

    Dibulatkan dulu; tanpa itu 1079,6 tercetak sebagai 17:60, bukan 18:00.
    """
    total = int(round(menit))
    return f"{total // 60:02d}:{total % 60:02d}"


def cetak_itinerary(data, solusi, hasil, judul="Itinerary"):
    """Mencetak itinerary per hari beserta ringkasan biaya dan kelayakannya.

    Tiap destinasi ditampilkan dengan waktu tiba, durasi, skor terkoreksi
    cuaca, dan harga tiket; akomodasi ditandai terpisah. Ringkasannya memuat
    keempat suku objektif, rincian biaya, nilai fitness, dan daftar batasan
    yang dilanggar bila ada.
    """
    node, tau = data["node"], data["tau"]
    print(judul)
    print("=" * 78)
    for d in data["D"]:
        urutan = solusi["rute"].get(d) or []
        tanggal = data["tanggal"][d - 1]
        print(f"\nHari {d}  ({tanggal})")
        if len(urutan) < 2:
            print("  tidak ada kunjungan")
            continue
        tiba, selesai, _ = jadwal_hari(data, urutan, d)
        for n in urutan:
            if n in tau:
                print(f"    {_jam(tiba[n, d])}  {node[n]['nama'][:38]:38} "
                      f"{tau[n]:4.0f} mnt  skor {data['s_bar'][n, d]:5.2f}  Rp{data['f'][n]:>9,.0f}")
            else:
                print(f"           [{node[n]['nama'][:38]:38}]  akomodasi")
        print(f"    selesai {_jam(selesai)}, "
              f"pemakaian {selesai - T_MULAI:.0f} dari {BETA:.0f} menit")

    print("\nringkasan")
    print(f"  destinasi terpilih : {sum(solusi['pilih'].values())} dari {len(data['P'])}")
    print(f"  Z                  : {hasil['Z']:.6f}")
    print(f"  L_P, L_H           : {hasil['L_P']:.4f}, {hasil['L_H']:.4f}")
    print(f"  C_H, C_T           : {hasil['C_H']:.4f}, {hasil['C_T']:.4f}")
    print(f"  biaya tiket        : Rp{hasil['biaya_tiket']:,.0f}")
    print(f"  biaya akomodasi    : Rp{hasil['biaya_hotel']:,.0f}")
    print(f"  biaya transportasi : Rp{hasil['biaya_transport']:,.0f}")
    print(f"  biaya total        : Rp{hasil['biaya_total']:,.0f}")
    print(f"  fitness F          : {hasil['F']:.6f}")
    print(f"  layak              : {'YA' if hasil['layak'] else 'TIDAK'}")
    for p in hasil["pesan"]:
        print(f"    - {p}")
