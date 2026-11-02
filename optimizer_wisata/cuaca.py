"""Probabilitas presipitasi harian dari Open-Meteo, untuk tanggal pilihan pengguna.

Alasan berkas ini ada. Lembar Weather_Features_14d pada dataset Excel hanya
memuat empat belas hari, 5 sampai 18 Agustus 2026, sehingga tanggal perjalanan
tidak dapat dipilih pengguna. Modul ini mengambil data cuaca hidup supaya
pemilih tanggal pada aplikasi web dapat bekerja untuk tanggal mana pun.

Open-Meteo tidak memerlukan kunci API untuk pemakaian non-komersial, jadi tidak
ada rahasia yang perlu disimpan.

Yang diambil peluang hujan TERBESAR sepanjang hari, yaitu peubah harian
precipitation_probability_max, bukan rata-ratanya. Rata-rata akan meredam hujan
yang terpusat beberapa jam, padahal hujan tiga jam sudah cukup merusak
kunjungan luar ruang sehari.

Semula modul ini menarik data per jam lalu mengambil nilai terbesar pada
jendela aktivitas. Keduanya diukur sama pada 15 dari 16 hari, dengan rata-rata
selisih 0,1 poin dan selisih terbesar 2 poin, sebab hujan di kedua kota hampir
selalu memuncak pada siang hari sehingga puncak sehari penuh jatuh di dalam
jendela 08.00 sampai 20.00. Data harian dipakai karena lebih sederhana dan
jauh lebih ringan.

Akibat yang perlu diketahui: peluang harian tidak mengikuti jendela aktivitas.
Bila penggunanya mempersempit jendela, peluang yang dipakai tetap puncak sehari
penuh dan karena itu dapat melebih-lebihkan.

Lembar Excel pada dataset tidak terpengaruh. Ia tetap dibaca per jam lalu
diambil nilai terbesar pada jendela, sebagaimana diuraikan naskah, sehingga
seluruh percobaan Bab IV tetap dapat diulang.

Percobaan skripsi TIDAK memakai modul ini. Bab IV tetap dipatok pada snapshot
Excel supaya angkanya dapat diulang orang lain; data hidup berubah setiap hari
dan akan membuat hasil percobaan tidak dapat direproduksi.
"""
import io
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta

# Ramalan Open-Meteo menjangkau kira-kira enam belas hari ke depan. Tanggal yang
# lebih lampau diambil dari arsipnya, yang tertinggal beberapa hari dari hari ini.
URL_RAMALAN = "https://api.open-meteo.com/v1/forecast"
URL_ARSIP = "https://archive-api.open-meteo.com/v1/archive"
URL_SEASONAL = "https://seasonal-api.open-meteo.com/v1/seasonal"
HARI_RAMALAN_MAKS = 16
# Seasonal Forecast API, terukur 184 hari pada pengujian langsung.
HARI_SEASONAL_MAKS = 184

# Ambang hari hujan pada sumber seasonal, dalam milimeter. Disetel dengan
# membandingkan keluarannya terhadap klimatologi dua puluh tahun pada
# definisi yang sama: pada nilai ini selisih rata-ratanya +0,017 dengan
# korelasi 0,680, sedangkan ambang yang lebih kecil membuatnya jenuh
# mendekati satu.
AMBANG_HUJAN_MM = 1.0

# Memakai ramalan biasa untuk tanggal yang masih terjangkau olehnya. Ramalan
# biasa menyediakan peluang hujan yang sesungguhnya, bukan turunan ensemble,
# sehingga lebih tajam pada rentang itu. Disetel False bila seluruh tanggal
# ingin memakai satu sumber yang sama.
PAKAI_RAMALAN_DEKAT = True
ZONA = "Asia/Jakarta"
WAKTU_HABIS = 12

BERKAS_SIMPANAN = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                               "hasil", "simpanan_cuaca.json")
# Ramalan berubah sepanjang hari, jadi simpanannya tidak boleh berlaku selamanya.
UMUR_SIMPANAN_DETIK = 6 * 3600


class GalatCuaca(Exception):
    """Pengambilan cuaca gagal. Pemanggil diharapkan jatuh ke sumber cadangan."""


def _muat_simpanan():
    try:
        with io.open(BERKAS_SIMPANAN, encoding="utf8") as f:
            return json.load(f)
    except (OSError, ValueError):
        # Simpanan hilang atau rusak bukan galat: cukup diambil ulang.
        return {}


def _tulis_simpanan(simpanan):
    try:
        os.makedirs(os.path.dirname(BERKAS_SIMPANAN), exist_ok=True)
        with io.open(BERKAS_SIMPANAN, "w", encoding="utf8") as f:
            json.dump(simpanan, f, indent=1)
    except OSError:
        # Gagal menulis simpanan tidak boleh menggagalkan permintaannya.
        pass


def _unduh(url, parameter):
    alamat = url + "?" + urllib.parse.urlencode(parameter, doseq=True)
    try:
        with urllib.request.urlopen(alamat, timeout=WAKTU_HABIS) as jawaban:
            return json.loads(jawaban.read().decode("utf8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as galat:
        raise GalatCuaca("Open-Meteo tidak dapat dihubungi: %s" % galat) from galat


def _harian(titik, mulai, selesai, lampau):
    """Satu permintaan per titik, mengembalikan daftar tanggal dan peluang hujan."""
    lat, lon = titik
    parameter = {
        "latitude": "%.4f" % lat,
        "longitude": "%.4f" % lon,
        "start_date": mulai.isoformat(),
        "end_date": selesai.isoformat(),
        "timezone": ZONA,
    }
    if lampau:
        # Arsip tidak menyediakan peluang hujan, hanya curah hujan sesungguhnya.
        # Curah hujan diubah menjadi peluang pada _ke_peluang.
        parameter["daily"] = "precipitation_sum"
        kunci = "precipitation_sum"
    else:
        parameter["daily"] = "precipitation_probability_max"
        kunci = "precipitation_probability_max"
    j = _unduh(URL_ARSIP if lampau else URL_RAMALAN, parameter)
    harian = j.get("daily") or {}
    waktu = harian.get("time") or []
    nilai = harian.get(kunci) or []
    if not waktu or len(waktu) != len(nilai):
        raise GalatCuaca("Jawaban Open-Meteo tidak memuat data harian yang utuh.")
    return waktu, nilai, lampau


def _seasonal(titik, mulai, selesai):
    """Peluang hujan harian dari ensemble seasonal, per tanggal.

    Seasonal hanya memberi curah hujan milimeter, tetapi memberinya untuk lima
    puluh anggota ensemble sekaligus. Peluang disusun sebagai pecahan anggota
    yang meramalkan hujan melebihi AMBANG_HUJAN_MM. Itu peluang sejati: ia
    menjawab berapa bagian dari kemungkinan yang dijelajahi model berakhir
    dengan hari hujan.
    """
    lat, lon = titik
    # forecast_days pada seasonal dihitung dari HARI INI, bukan dari tanggal
    # mulai, sehingga yang diminta harus menjangkau sampai tanggal selesai.
    jangkau = (selesai - date.today()).days + 1
    parameter = {
        "latitude": "%.4f" % lat,
        "longitude": "%.4f" % lon,
        "daily": "precipitation_sum",
        "forecast_days": max(1, min(jangkau, HARI_SEASONAL_MAKS)),
        "timezone": ZONA,
    }
    j = _unduh(URL_SEASONAL, parameter)
    harian = j.get("daily") or {}
    waktu = harian.get("time") or []
    anggota = sorted(k for k in harian if "member" in k)
    if not waktu or not anggota:
        raise GalatCuaca(
            "Jawaban seasonal Open-Meteo tidak memuat anggota ensemble.")

    hasil = {}
    for i, teks in enumerate(waktu):
        nilai = [harian[k][i] for k in anggota if harian[k][i] is not None]
        if not nilai:
            continue
        hasil[teks] = sum(1 for v in nilai
                          if v > AMBANG_HUJAN_MM) / len(nilai)
    if not hasil:
        raise GalatCuaca("Seasonal Open-Meteo tidak memberi satu hari pun.")
    return hasil


def _ke_peluang(nilai, lampau):
    """Menormalkan jawaban Open-Meteo menjadi peluang 0 sampai 1.

    Ramalan sudah berupa persen. Arsip hanya memuat curah hujan milimeter,
    sehingga dipakai aturan sederhana: hari yang hujannya terukur dianggap
    berpeluang satu, yang kering berpeluang nol. Aturan itu kasar, dan
    karenanya tanggal lampau sebaiknya tidak dipakai untuk perencanaan.
    """
    if nilai is None:
        return None
    if lampau:
        return 1.0 if float(nilai) > 0.0 else 0.0
    return max(0.0, min(1.0, float(nilai) / 100.0))


def ambil_rho(titik_kota, tanggal_mulai, jumlah_hari, pakai_simpanan=True):
    """Peluang hujan terbesar sepanjang hari, per kota per tanggal.

    titik_kota  pemetaan nama kota ke pasangan (lat, lon)
    kembalian   pasangan (peluang, sumber). Peluang berupa pemetaan
                (nama kota, datetime.date) ke nilai 0 sampai 1. Sumber
                bernilai 'ramalan', 'arsip', atau 'seasonal'.

    Sumbernya dikembalikan sebab keandalan ketiganya jauh berbeda, dan
    pemanggil perlu dapat menyampaikannya kepada pengguna.

    Bentuk kembaliannya sama dengan yang disusun dataset.py dari lembar Excel,
    sehingga keduanya dapat dipertukarkan.
    """
    if isinstance(tanggal_mulai, str):
        tanggal_mulai = datetime.strptime(tanggal_mulai, "%Y-%m-%d").date()
    if isinstance(tanggal_mulai, datetime):
        tanggal_mulai = tanggal_mulai.date()
    jumlah_hari = int(jumlah_hari)
    if jumlah_hari < 1:
        raise ValueError("Jumlah hari harus sekurang-kurangnya satu.")
    tanggal_selesai = tanggal_mulai + timedelta(days=jumlah_hari - 1)

    # Sumbernya dipilih menurut jarak tanggalnya. Arsip untuk yang sudah lewat;
    # ramalan biasa untuk yang masih terjangkau olehnya, sebab ia memberi peluang
    # hujan yang sesungguhnya; seasonal untuk sisanya sampai enam bulan.
    hari_ini = date.today()
    lampau = tanggal_selesai < hari_ini - timedelta(days=5)
    batas_ramalan = hari_ini + timedelta(days=HARI_RAMALAN_MAKS)
    if lampau:
        sumber = "arsip"
    elif PAKAI_RAMALAN_DEKAT and tanggal_selesai <= batas_ramalan:
        sumber = "ramalan"
    else:
        sumber = "seasonal"

    if sumber == "seasonal" and tanggal_selesai > hari_ini + timedelta(
            days=HARI_SEASONAL_MAKS):
        raise ValueError(
            "Tanggal selesai %s melewati jangkauan Open-Meteo, yaitu %d hari "
            "dari hari ini."
            % (tanggal_selesai.isoformat(), HARI_SEASONAL_MAKS))

    simpanan = _muat_simpanan() if pakai_simpanan else {}
    sekarang = time.time()
    hasil = {}
    berubah = False

    for kota, titik in titik_kota.items():
        # Jam tidak lagi ikut jadi kunci, sebab peluang harian tidak
        # bergantung pada jendela aktivitas.
        tanda = "|".join((kota, "%.4f,%.4f" % titik, tanggal_mulai.isoformat(),
                          tanggal_selesai.isoformat(), sumber))
        simpan = simpanan.get(tanda)
        if simpan and sekarang - simpan.get("pada", 0) < UMUR_SIMPANAN_DETIK:
            for teks, nilai in simpan["nilai"].items():
                hasil[kota, date.fromisoformat(teks)] = nilai
            continue

        if sumber == "seasonal":
            per_tanggal = _seasonal(titik, tanggal_mulai, tanggal_selesai)
        else:
            waktu, nilai, dari_arsip = _harian(titik, tanggal_mulai,
                                               tanggal_selesai, lampau)
            per_tanggal = {}
            for tgl_teks, mentah in zip(waktu, nilai):
                peluang = _ke_peluang(mentah, dari_arsip)
                if peluang is not None:
                    per_tanggal[tgl_teks] = peluang
        # Seasonal selalu dimulai hari ini, jadi tanggal di luar rentang yang
        # diminta dibuang supaya pemeriksaan kelengkapan di bawah tetap sah.
        per_tanggal = {t: v for t, v in per_tanggal.items()
                       if tanggal_mulai <= date.fromisoformat(t) <= tanggal_selesai}
        if len(per_tanggal) < jumlah_hari:
            raise GalatCuaca(
                "Open-Meteo hanya memberi %d dari %d hari untuk %s."
                % (len(per_tanggal), jumlah_hari, kota))
        for teks, nilai_maks in per_tanggal.items():
            hasil[kota, date.fromisoformat(teks)] = nilai_maks
        simpanan[tanda] = {"pada": sekarang, "nilai": per_tanggal}
        berubah = True

    if berubah and pakai_simpanan:
        _tulis_simpanan(simpanan)
    return hasil, sumber


def titik_dari_node(node):
    """Titik tengah tiap kota, dihitung dari koordinat node dataset itu sendiri.

    Dipakai supaya koordinat kota tidak perlu dituliskan tangan di dalam kode,
    dan ikut berubah bila datasetnya berganti.
    """
    kumpul = {}
    for v in node.values():
        kumpul.setdefault(v["kota"], []).append((v["lat"], v["lon"]))
    return {k: (sum(a for a, _ in t) / len(t), sum(b for _, b in t) / len(t))
            for k, t in kumpul.items()}


if __name__ == "__main__":
    import sys

    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import dataset as DS

    titik = titik_dari_node(DS.muat_node_saja())
    mulai = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    hari = int(sys.argv[2]) if len(sys.argv) > 2 else 3
    print("titik kota:")
    for k, t in titik.items():
        print("  %-16s %.4f, %.4f" % (k, t[0], t[1]))
    print()
    rho = ambil_rho(titik, mulai, hari)
    print("rho, peluang hujan terbesar sepanjang hari:")
    for (kota, tgl) in sorted(rho, key=lambda x: (x[1], x[0])):
        print("  %-16s %s  %.4f" % (kota, tgl.isoformat(), rho[kota, tgl]))
