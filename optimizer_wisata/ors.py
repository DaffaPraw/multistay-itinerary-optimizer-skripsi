"""
Pengambilan matriks jarak dan waktu tempuh dari OpenRouteService.

Memakai endpoint matrix, bukan directions: satu permintaan mengembalikan satu blok
pasangan sekaligus, jadi 14.280 pasangan pada 120 node cukup lima permintaan.

Endpoint directions dipakai terpisah oleh ambil_geometri, yaitu ketika halaman
hasil perlu menggambar rute yang benar-benar dilalui di peta. Itu tidak dipakai
menyusun matriks karena 14.280 pasangan berarti 14.280 permintaan.

Penting: hasilnya tidak simetris. Rute u->v bisa beda panjang dari v->u karena
arah jalan dan larangan putar balik, jadi semua pasangan berarah harus diambil.

Cara pakai:
    python ors.py            mengambil matriks dan menyimpannya ke hasil/
    python ors.py --periksa  memeriksa berkas matriks yang sudah ada

Kunci API dibaca berurutan dari peubah lingkungan ORS_API_KEY, lalu dari berkas
~/.ors_key. Kunci sengaja tidak ditulis di dalam kode supaya tidak ikut terbawa
ketika berkas program dilampirkan pada naskah.
"""
import json
import os
import sys
import time
import urllib.error
import urllib.request

import dataset as DS

# -- pengaturan --
URL = "https://api.openrouteservice.org/v2/matrix/driving-car"
URL_RUTE = "https://api.openrouteservice.org/v2/directions/driving-car/geojson"
PROFIL = "driving-car"

# Batas layanan pada paket gratis adalah 3.500 pasangan berarah per permintaan,
# yaitu jumlah sumber dikali jumlah tujuan. Dengan 120 tujuan, satu blok dibatasi
# 25 sumber sehingga satu permintaan memuat 3.000 pasangan dan masih di bawah batas.
BLOK_SUMBER = 25
BATAS_PASANGAN = 3500

# Jeda antar permintaan. Paket gratis membatasi 40 permintaan per menit.
JEDA_DETIK = 2.0

BERKAS_MATRIKS = DS.BERKAS_MATRIKS_ORS

VERSI_MATRIKS = "ors-driving-car-v1"


def ambil_kunci():
    """Mengambil kunci API dari lingkungan atau dari berkas di folder rumah."""
    kunci = os.environ.get("ORS_API_KEY", "").strip()
    if kunci:
        return kunci
    berkas = os.path.join(os.path.expanduser("~"), ".ors_key")
    if os.path.exists(berkas):
        with open(berkas, encoding="utf8") as f:
            kunci = f.read().strip()
        if kunci:
            return kunci
    raise RuntimeError(
        "Kunci OpenRouteService tidak ditemukan. Setel peubah lingkungan "
        "ORS_API_KEY atau simpan kuncinya pada berkas ~/.ors_key."
    )


def _minta(kunci, lokasi, sumber, tujuan, percobaan=4):
    """Satu permintaan matrix. Mengulang bila layanan menolak karena laju."""
    muatan = json.dumps({
        "locations": lokasi,
        "sources": sumber,
        "destinations": tujuan,
        "metrics": ["distance", "duration"],
        "units": "km",
    }).encode("utf8")
    permintaan = urllib.request.Request(URL, data=muatan, method="POST")
    permintaan.add_header("Authorization", kunci)
    permintaan.add_header("Content-Type", "application/json")
    permintaan.add_header("Accept", "application/json")

    tunggu = JEDA_DETIK
    for ke in range(percobaan):
        try:
            with urllib.request.urlopen(permintaan, timeout=120) as tanggapan:
                return json.loads(tanggapan.read().decode("utf8"))
        except urllib.error.HTTPError as galat:
            isi = galat.read().decode("utf8", "replace")[:300]
            if galat.code in (429, 503) and ke < percobaan - 1:
                tunggu *= 2
                print(f"    layanan menolak sementara ({galat.code}), "
                      f"menunggu {tunggu:.0f} detik")
                time.sleep(tunggu)
                continue
            raise RuntimeError(f"OpenRouteService menolak: {galat.code} {isi}")
        except urllib.error.URLError as galat:
            if ke < percobaan - 1:
                tunggu *= 2
                print(f"    sambungan gagal ({galat.reason}), "
                      f"menunggu {tunggu:.0f} detik")
                time.sleep(tunggu)
                continue
            raise RuntimeError(f"Sambungan ke OpenRouteService gagal: {galat.reason}")
    raise RuntimeError("Permintaan OpenRouteService gagal setelah beberapa percobaan.")


def ambil_geometri(koordinat, percobaan=3):
    """Geometri jalan yang benar-benar dilalui untuk satu rangkaian perhentian.

    Memakai endpoint directions, bukan matrix. Seluruh perhentian satu hari
    dikirim sekali sebagai daftar titik singgah, jadi satu hari cukup satu
    permintaan, bukan satu permintaan per ruas.

    Masukan dan keluaran keduanya [bujur, lintang] mengikuti GeoJSON. Pemanggil
    yang memerlukan [lintang, bujur] membaliknya sendiri.

    Mengembalikan None bila layanan menolak, supaya pemanggil dapat jatuh kembali
    ke garis lurus antar perhentian.
    """
    if len(koordinat) < 2:
        return None
    kunci = ambil_kunci()
    muatan = json.dumps({"coordinates": koordinat}).encode("utf8")
    permintaan = urllib.request.Request(URL_RUTE, data=muatan, method="POST")
    permintaan.add_header("Authorization", kunci)
    permintaan.add_header("Content-Type", "application/json")
    permintaan.add_header("Accept", "application/geo+json")

    tunggu = JEDA_DETIK
    for ke in range(percobaan):
        try:
            with urllib.request.urlopen(permintaan, timeout=60) as tanggapan:
                isi = json.loads(tanggapan.read().decode("utf8"))
            return isi["features"][0]["geometry"]["coordinates"]
        except urllib.error.HTTPError as galat:
            if galat.code in (429, 503) and ke < percobaan - 1:
                tunggu *= 2
                time.sleep(tunggu)
                continue
            return None
        except (urllib.error.URLError, KeyError, IndexError, TimeoutError):
            if ke < percobaan - 1:
                tunggu *= 2
                time.sleep(tunggu)
                continue
            return None
    return None


def ambil_matriks(node, lapor=True):
    """Seluruh pasangan berarah, diambil per blok sumber.

    Balikannya: ids, jarak_km, durasi_detik. Dua matriks terakhir daftar bersarang
    menurut urutan ids.
    """
    kunci = ambil_kunci()
    ids = list(node.keys())
    n = len(ids)
    # OpenRouteService menerima koordinat dalam urutan bujur lalu lintang.
    lokasi = [[node[i]["lon"], node[i]["lat"]] for i in ids]
    tujuan = list(range(n))

    if BLOK_SUMBER * n > BATAS_PASANGAN:
        raise RuntimeError(
            f"Satu blok memuat {BLOK_SUMBER * n} pasangan, melewati batas "
            f"{BATAS_PASANGAN}. Kecilkan BLOK_SUMBER."
        )

    jarak = [[None] * n for _ in range(n)]
    durasi = [[None] * n for _ in range(n)]

    blok = [list(range(a, min(a + BLOK_SUMBER, n)))
            for a in range(0, n, BLOK_SUMBER)]
    if lapor:
        print(f"{n} node, {n * (n - 1)} pasangan berarah, "
              f"{len(blok)} permintaan matrix")

    for ke, sumber in enumerate(blok, 1):
        if lapor:
            print(f"  blok {ke}/{len(blok)}: sumber {sumber[0]}-{sumber[-1]} "
                  f"({len(sumber) * n} pasangan)")
        hasil = _minta(kunci, lokasi, sumber, tujuan)
        d_km = hasil.get("distances")
        d_dtk = hasil.get("durations")
        if d_km is None or d_dtk is None:
            raise RuntimeError(f"Tanggapan tidak memuat matriks: {str(hasil)[:300]}")
        for baris, s in enumerate(sumber):
            for kol in range(n):
                jarak[s][kol] = d_km[baris][kol]
                durasi[s][kol] = d_dtk[baris][kol]
        if ke < len(blok):
            time.sleep(JEDA_DETIK)

    kosong = sum(1 for a in range(n) for b in range(n)
                 if a != b and (jarak[a][b] is None or durasi[a][b] is None))
    if lapor:
        print(f"selesai, {kosong} pasangan tidak terjangkau jaringan jalan")

    return {
        "versi": VERSI_MATRIKS,
        "profil": PROFIL,
        "diambil": time.strftime("%Y-%m-%d %H:%M:%S"),
        "satuan": {"jarak": "km", "durasi": "detik"},
        "ids": ids,
        "jarak_km": jarak,
        "durasi_detik": durasi,
        "pasangan_kosong": kosong,
    }


def simpan(matriks, berkas=BERKAS_MATRIKS):
    os.makedirs(os.path.dirname(berkas), exist_ok=True)
    with open(berkas, "w", encoding="utf8") as f:
        json.dump(matriks, f)
    ukuran = os.path.getsize(berkas) / 1_048_576
    print(f"disimpan ke {berkas} ({ukuran:.1f} MB)")


def muat(berkas=BERKAS_MATRIKS):
    """Membaca berkas matriks bila ada. Mengembalikan None bila tidak ada."""
    if not os.path.exists(berkas):
        return None
    with open(berkas, encoding="utf8") as f:
        return json.load(f)


def periksa(berkas=BERKAS_MATRIKS):
    """Meringkas berkas matriks yang sudah tersimpan."""
    m = muat(berkas)
    if m is None:
        print(f"berkas {berkas} belum ada")
        return
    ids = m["ids"]
    n = len(ids)
    jarak = m["jarak_km"]
    durasi = m["durasi_detik"]
    isi = [(a, b) for a in range(n) for b in range(n)
           if a != b and jarak[a][b] is not None]
    asimetris = [abs(jarak[a][b] - jarak[b][a]) for a, b in isi
                 if jarak[b][a] is not None]
    nilai = [jarak[a][b] for a, b in isi]
    print(f"versi      : {m['versi']}")
    print(f"profil     : {m['profil']}")
    print(f"diambil    : {m['diambil']}")
    print(f"node       : {n}")
    print(f"pasangan   : {len(isi)} terisi, {m['pasangan_kosong']} kosong")
    print(f"jarak km   : {min(nilai):.2f} sampai {max(nilai):.2f}, "
          f"rata-rata {sum(nilai) / len(nilai):.2f}")
    beda = [x for x in asimetris if x > 1e-6]
    print(f"asimetri   : {len(beda)} pasangan berbeda arah, "
          f"selisih terbesar {max(asimetris):.2f} km")
    menit = [durasi[a][b] / 60.0 for a, b in isi if durasi[a][b] is not None]
    print(f"durasi min : {min(menit):.1f} sampai {max(menit):.1f} menit")


def main():
    if "--periksa" in sys.argv:
        periksa()
        return
    data_node = DS.muat_node_saja()
    matriks = ambil_matriks(data_node)
    simpan(matriks)
    print()
    periksa()


if __name__ == "__main__":
    main()
