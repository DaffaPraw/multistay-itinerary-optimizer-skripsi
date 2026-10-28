"""
Peladen antarmuka web untuk optimizer itinerary.

Peladen ini memakai http.server dari pustaka standar, bukan kerangka kerja web.
Alasannya dua. Pertama, kebutuhannya memang kecil, yaitu menyajikan satu halaman
dan beberapa endpoint. Kedua, ketergantungan pihak ketiga pada program ini sengaja
dijaga tetap dua, yaitu openpyxl untuk membaca dataset dan gurobipy untuk MILP,
sehingga program dapat dijalankan penguji tanpa memasang apa pun selain Gurobi.

Pencarian solusi tidak dijalankan di dalam penanganan permintaan, karena satu kali
PSO pada dataset penuh memakan waktu puluhan detik dan akan membuat peramban
menunggu sampai putus. Permintaan optimasi karena itu dimasukkan sebagai pekerjaan
yang dijalankan utas terpisah, lalu halaman menanyakan kemajuannya secara berkala
sampai pekerjaan selesai.

Tahap ini sudah menjalankan optimasi dan melaporkan kemajuannya.
Jadwal harian, peta rute, serta kendali kunci dan tolak menyusul
pada sisi halaman.

Cara pakai:
    python server.py                 lalu buka http://127.0.0.1:8000
    python server.py --porta 8080
"""
import json
import os
import sys
import threading
import time
import traceback
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

# Modul inti berada satu tingkat di atas folder web.
AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AKAR not in sys.path:
    sys.path.insert(0, AKAR)

import clarke_wright as CWS          # noqa: E402
import ors as ORS                    # noqa: E402
import dataset as DS                 # noqa: E402
import model as M                    # noqa: E402
import pso as PSO                    # noqa: E402

STATIS = os.path.join(os.path.dirname(os.path.abspath(__file__)), "statis")
PORTA_BAWAAN = 8000

JENIS = {
    ".html": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
}

# ---------------------------------------------------------------- simpanan
_kunci_data = threading.Lock()
_simpanan_data = {}

# Geometri rute disimpan supaya membuka tab peta berulang kali tidak
# menghabiskan kuota OpenRouteService. Kuncinya rangkaian koordinatnya.
_kunci_geometri = threading.Lock()
_simpanan_geometri = {}

_kunci_kerja = threading.Lock()
_kerja = {}


def ambil_data(kota, kategori, hari, cuaca=DS.CUACA_AKTIF):
    """Memuat dataset sekali untuk setiap kombinasi penyaringan, lalu dipakai ulang.

    Pemuatan membaca berkas Excel dan menyusun matriks seluruh pasangan node,
    sehingga mengulanginya pada setiap permintaan akan membuang waktu pada
    pekerjaan yang hasilnya sama.
    """
    # Jendela aktivitas ikut jadi kunci, sebab rho diambil pada jendela itu saat
    # dataset dimuat. Tanpa itu, mengubah jendela memakai ulang dataset lama.
    # Jendela aktivitas dan saklar cuaca ikut jadi kunci, sebab rho diambil pada
    # jendela itu dan skor terkoreksi s_bar dihitung, keduanya saat dataset dimuat.
    tanda = (tuple(sorted(kota or ())), tuple(sorted(kategori or ())), int(hari),
             DS.JAM_MULAI_AKTIVITAS, DS.JAM_SELESAI_AKTIVITAS, int(cuaca))
    with _kunci_data:
        if tanda in _simpanan_data:
            return _simpanan_data[tanda]
    data = DS.muat_dataset(
        kota_dipilih=list(kota) if kota else None,
        kategori_dipilih=list(kategori) if kategori else None,
        jumlah_hari=int(hari),
        cuaca_aktif=int(cuaca),
    )
    with _kunci_data:
        _simpanan_data[tanda] = data
    return data


# ---------------------------------------------------------------- penyajian hasil
def _rangkai_hari(data, solusi, d):
    """Menyusun satu hari menjadi daftar perhentian beserta jam dan ruas perjalanannya.

    Setiap perhentian memuat waktu tiba dan waktu berangkat, sedangkan ruas menuju
    perhentian berikutnya memuat waktu tempuh dan jaraknya. Ruas yang melintasi
    batas kota ditandai tersendiri, karena perpindahan antarkota itulah yang
    membedakan masalah ini dari penyusunan itinerary satu kota.
    """
    node, tau = data["node"], data["tau"]
    t_mat, delta = data["t"], data["delta"]
    urutan = solusi["rute"].get(d) or []
    if len(urutan) < 2:
        return {"hari": d, "tanggal": str(data["tanggal"][d - 1]),
                "perhentian": [], "selesai": None, "mulai": M.T_MULAI,
                "kuota": M.BETA, "jarak_km": 0.0, "waktu_tempuh": 0.0}

    tiba, selesai, _ = M.jadwal_hari(data, urutan, d)
    perhentian = []
    for ke, n in enumerate(urutan):
        titik = {
            "id": n,
            "nama": node[n]["nama"],
            "lat": node[n]["lat"],
            "lon": node[n]["lon"],
            "kota": node[n]["kota"],
            "peran": "destinasi" if n in tau else "akomodasi",
        }
        if n in tau:
            titik.update({
                "tiba": tiba[n, d],
                "pergi": tiba[n, d] + tau[n],
                "durasi": tau[n],
                "skor": round(data["s_bar"][n, d], 3),
                "tiket": data["f"][n],
                "kategori": node[n]["kategori"],
                "sifat": node[n].get("sifat") or "",
            })
        else:
            titik["harga_malam"] = data["p"].get(n)
            titik["ujung"] = "awal" if ke == 0 else "akhir"
            titik["tiba"] = None if ke == 0 else selesai
            titik["pergi"] = M.T_MULAI if ke == 0 else None

        if ke < len(urutan) - 1:
            v = urutan[ke + 1]
            titik["ruas"] = {
                "menit": round(t_mat[n, v], 1),
                "km": round(delta[n, v], 2),
                "antarkota": node[n]["kota"] != node[v]["kota"],
                "dari_kota": node[n]["kota"],
                "ke_kota": node[v]["kota"],
            }
        perhentian.append(titik)

    jarak = sum(delta[urutan[k], urutan[k + 1]] for k in range(len(urutan) - 1))
    tempuh = sum(t_mat[urutan[k], urutan[k + 1]] for k in range(len(urutan) - 1))
    return {
        "hari": d,
        "tanggal": str(data["tanggal"][d - 1]),
        "kota": node[urutan[0]]["kota"],
        "perhentian": perhentian,
        "selesai": selesai,
        "mulai": M.T_MULAI,
        "kuota": M.BETA,
        "jarak_km": round(jarak, 2),
        "waktu_tempuh": round(tempuh, 1),
    }


def _tidak_dipilih(data, solusi, anggaran, hasil, tolak):
    """Mendaftar destinasi kandidat yang tidak masuk itinerary beserta alasannya.

    Alasannya disimpulkan dari batasan yang benar-benar dapat diperiksa, bukan
    dikarang. Destinasi yang tiketnya sendiri sudah melampaui sisa anggaran, atau
    yang durasinya tidak muat pada sisa kuota hari mana pun, dapat dinyatakan
    sebab pastinya. Selebihnya dinyatakan apa adanya, yaitu kalah terhadap
    kandidat lain pada penilaian fungsi objektif.
    """
    node, tau, f = data["node"], data["tau"], data["f"]
    terpilih = {i for i, v in solusi["pilih"].items() if v}
    sisa_anggaran = anggaran - hasil["biaya_total"]
    ditolak = set(tolak or ())

    sisa_hari = {}
    for d in data["D"]:
        urutan = solusi["rute"].get(d) or []
        if len(urutan) >= 2:
            _, selesai, _ = M.jadwal_hari(data, urutan, d)
            sisa_hari[d] = (M.T_MULAI + M.BETA) - selesai
        else:
            sisa_hari[d] = M.BETA
    kelonggaran = max(sisa_hari.values()) if sisa_hari else 0.0

    daftar = []
    for i in data["P"]:
        if i in terpilih:
            continue
        if i in ditolak:
            alasan = "ditolak pengguna"
        elif f[i] > sisa_anggaran:
            alasan = "harga tiket melampaui sisa anggaran"
        elif tau[i] > kelonggaran:
            alasan = "durasi kunjungan tidak muat pada sisa kuota waktu"
        else:
            alasan = "kalah skor terhadap kandidat lain"
        daftar.append({
            "id": i, "nama": node[i]["nama"], "kota": node[i]["kota"],
            "kategori": node[i]["kategori"], "skor": round(node[i]["skor"], 2),
            "tiket": f[i], "durasi": tau[i], "alasan": alasan,
        })
    daftar.sort(key=lambda r: -r["skor"])
    return daftar


def rangkai_hasil(data, keluaran, anggaran, tolak=None):
    """Mengubah keluaran metode menjadi bentuk yang dapat dibaca halaman."""
    solusi, hasil = keluaran["solusi"], keluaran["hasil"]
    node = data["node"]
    hari = [_rangkai_hari(data, solusi, d) for d in data["D"]]
    return {
        "metode": keluaran["metode"],
        "Z": round(hasil["Z"], 6),
        "F": round(hasil["F"], 6),
        "layak": bool(hasil["layak"]),
        "pesan": list(hasil.get("pesan", [])),
        "komponen": {k: round(hasil[k], 4) for k in ("L_P", "L_H", "C_H", "C_T")},
        "biaya": {
            "tiket": hasil["biaya_tiket"],
            "akomodasi": hasil["biaya_hotel"],
            "transportasi": round(hasil["biaya_transport"]),
            "total": round(hasil["biaya_total"]),
        },
        "jumlah_destinasi": int(sum(solusi["pilih"].values())),
        "destinasi_kandidat": len(data["P"]),
        "total_jarak": round(sum(h["jarak_km"] for h in hari), 2),
        "total_tempuh": round(sum(h["waktu_tempuh"] for h in hari), 1),
        "kota": sorted({h["kota"] for h in hari if h.get("kota")}),
        "akomodasi": [
            {"malam": d, "id": h, "nama": node[h]["nama"] if h else None,
             "harga": data["p"].get(h)}
            for d, h in sorted((solusi.get("hotel") or {}).items())
        ],
        "hari": hari,
        "tidak_dipilih": _tidak_dipilih(data, solusi, anggaran, hasil, tolak),
        "runtime": round(keluaran.get("runtime", 0.0), 3),
        "iterasi": keluaran.get("iterasi_terpakai"),
        "seed": keluaran.get("seed"),
        "validasi_ok": keluaran.get("validasi_ok"),
        "validasi_pesan": keluaran.get("validasi_pesan", []),
    }


# ---------------------------------------------------------------- pekerjaan
def _jalankan_kerja(kerja_id, permintaan):
    """Menjalankan satu permintaan optimasi pada utas tersendiri."""
    def tahap(teks, bagian):
        with _kunci_kerja:
            _kerja[kerja_id]["tahap"] = teks
            _kerja[kerja_id]["bagian"] = bagian

    try:
        tahap("memeriksa masukan", 0.03)
        anggaran = float(permintaan.get("anggaran") or 3_000_000)
        if anggaran < 100_000:
            raise ValueError("Anggaran terlalu kecil untuk satu malam akomodasi.")
        hari = int(permintaan.get("hari") or 3)
        if not 1 <= hari <= 7:
            raise ValueError("Lama perjalanan di luar rentang satu sampai tujuh hari.")

        # Minat kategori dikirim sebagai pasangan kategori dan jumlah minimum.
        minat = permintaan.get("minat") or {}
        kategori = sorted(minat.keys()) or None
        minimum_kategori = {k: int(v) for k, v in minat.items() if int(v) > 0} or None

        kunci = permintaan.get("kunci") or None
        tolak = permintaan.get("tolak") or None
        if kunci and tolak:
            bentrok = set(kunci) & set(tolak)
            if bentrok:
                raise ValueError(
                    f"Destinasi tidak dapat dikunci sekaligus ditolak: {sorted(bentrok)}")

        tahap("memuat dataset", 0.08)
        # Persamaan (2.2) bersifat opsional. Pengguna yang tidak peduli cuaca
        # memperoleh skor apa adanya; yang peduli memperoleh skor terkoreksi.
        cuaca = 1 if permintaan.get("cuaca") else 0
        data = ambil_data(permintaan.get("kota"), kategori, hari, cuaca)

        if kunci:
            asing = [i for i in kunci if i not in data["P"]]
            if asing:
                raise ValueError(
                    "Destinasi yang dikunci tidak ada pada kandidat setelah "
                    f"penyaringan kota dan kategori: {asing}")

        # Naskah paragraf 448: kuota harian dan jendela aktivitas adalah masukan.
        # Ditetapkan sebelum ambil_data supaya rho memakai jendela yang sama.
        if any(permintaan.get(k) for k in ("beta", "jam_mulai", "jam_selesai")):
            M.atur_waktu(permintaan.get("beta"), permintaan.get("jam_mulai"),
                         permintaan.get("jam_selesai"))

        metode = (permintaan.get("metode") or "pso").lower()
        # Bawaannya menjalankan ketiga profil bobot sekaligus, sesuai rancangan
        # pada Subbab 3.1.3 yang menyatakan Halaman Hasil menyajikan tiga
        # alternatif dan pengguna tidak memilih bobot sendiri. Satu profil
        # tunggal tetap dapat diminta, dan itu dipakai ketika menguji.
        profil_diminta = permintaan.get("profil") or "semua"
        semua_profil = profil_diminta == "semua"
        profil_dipakai = (list(M.PROFIL_BOBOT) if semua_profil else [profil_diminta])
        for pr in profil_dipakai:
            if pr not in M.PROFIL_BOBOT:
                raise ValueError(f"Profil bobot tidak dikenal: {pr}")

        # (3.6) nomor urut pengguna dipakai sebagai seed. Isian seed langsung
        # tetap diterima karena dipakai ketika menguji.
        if permintaan.get("pengguna"):
            seed = PSO.seed_pengguna(permintaan["pengguna"])
        else:
            seed = int(permintaan.get("seed") or PSO.SEED)
        hasil = {}
        langkah = [(pr, mt) for pr in profil_dipakai
                   for mt in (["pso", "cws"] if metode == "banding" else [metode])]

        for ke, (pr, mt) in enumerate(langkah):
            bobot = M.PROFIL_BOBOT[pr]
            dasar = 0.1 + 0.85 * ke / len(langkah)
            lebar = 0.85 / len(langkah)
            label = M.NAMA_PROFIL[pr]

            if mt == "pso":
                def kabar(it, maks, terbaik, dasar=dasar, lebar=lebar, label=label):
                    tahap(f"{label}: iterasi {it} dari {maks}, Z terbaik {terbaik:.4f}",
                          dasar + lebar * it / maks)
                tahap(f"{label}: menyiapkan partikel", dasar)
                keluaran = PSO.jalankan_pso(
                    data, anggaran, bobot, kunci=kunci, tolak=tolak,
                    minimum_kategori=minimum_kategori,
                    seed=seed, kabar=kabar)
            elif mt == "cws":
                tahap(f"{label}: Clarke-Wright Savings", dasar)
                keluaran = CWS.jalankan_cws(
                    data, anggaran, bobot, kunci=kunci, tolak=tolak,
                    minimum_kategori=minimum_kategori)
            else:
                raise ValueError(f"Metode tidak dikenal: {mt}")

            nama = f"{pr}_{mt}" if (semua_profil or metode == "banding") else mt
            hasil[nama] = rangkai_hasil(data, keluaran, anggaran, tolak)
            hasil[nama]["profil"] = label
            hasil[nama]["profil_kunci"] = pr
            hasil[nama]["bobot"] = bobot

        tahap("selesai", 1.0)
        with _kunci_kerja:
            _kerja[kerja_id].update({
                "status": "selesai",
                "hasil": hasil,
                "urutan": list(hasil.keys()),
                "profil": M.NAMA_PROFIL.get(profil_diminta, "Semua profil"),
                "anggaran": anggaran,
                "hari": hari,
                "kunci": kunci or [],
                "tolak": tolak or [],
                "minat": minat,
                "catatan": data.get("catatan", []),
            })
    except Exception as galat:                     # noqa: BLE001
        with _kunci_kerja:
            _kerja[kerja_id].update({
                "status": "gagal",
                "galat": str(galat),
                "jejak": traceback.format_exc(limit=6),
            })


def mulai_kerja(permintaan):
    kerja_id = uuid.uuid4().hex[:12]
    with _kunci_kerja:
        _kerja[kerja_id] = {"status": "berjalan", "tahap": "menyiapkan",
                            "bagian": 0.0, "dibuat": time.time()}
    utas = threading.Thread(target=_jalankan_kerja, args=(kerja_id, permintaan),
                            daemon=True)
    utas.start()
    return kerja_id


def geometri_rute(hari):
    """Geometri jalan untuk tiap hari, diambil dari OpenRouteService.

    Masukan daftar per hari berisi [bujur, lintang] tiap perhentian. Keluaran
    daftar per hari berisi [lintang, bujur] mengikuti urutan yang sama, siap
    dipakai Leaflet.

    Hari yang gagal diambil dikembalikan sebagai None, dan halaman menggambar
    garis lurus antar perhentian sebagai gantinya. Peta yang kurang tepat lebih
    baik daripada peta yang kosong.
    """
    hasil = []
    for titik in hari:
        if not titik or len(titik) < 2:
            hasil.append(None)
            continue
        kunci = json.dumps(titik, separators=(",", ":"))
        with _kunci_geometri:
            tersimpan = _simpanan_geometri.get(kunci)
        if tersimpan is not None:
            hasil.append(tersimpan)
            continue
        garis = ORS.ambil_geometri(titik)
        if garis is None:
            # Kegagalan tidak disimpan. Kalau layanannya yang sedang bermasalah,
            # menyimpan None berarti hari itu selamanya digambar garis lurus
            # selama peladen hidup.
            hasil.append(None)
            continue
        balik = [[t[1], t[0]] for t in garis]
        with _kunci_geometri:
            _simpanan_geometri[kunci] = balik
        hasil.append(balik)
    return hasil


# ---------------------------------------------------------------- keterangan
def _tanggal_awal():
    """Tanggal pertama yang tersedia pada data cuaca, dipakai sebagai awal perjalanan."""
    try:
        return str(ambil_data(None, None, 1)["tanggal"][0])
    except Exception:                               # noqa: BLE001
        return ""


def keterangan():
    """Pilihan yang tersedia pada formulir, diambil dari dataset itu sendiri."""
    node = DS.muat_node_saja()
    destinasi = {k: v for k, v in node.items() if v["peran"] == "destinasi"}
    akomodasi = {k: v for k, v in node.items() if v["peran"] == "akomodasi"}
    kategori = sorted({v["kategori"]
                       for v in destinasi.values()})
    matriks = DS._muat_matriks_ors()
    return {
        "kota": sorted({v["kota"] for v in node.values()}),
        "kategori": kategori,
        "jumlah_destinasi": len(destinasi),
        "jumlah_akomodasi": len(akomodasi),
        "profil": [{"kunci": k, "nama": M.NAMA_PROFIL[k], "bobot": v}
                   for k, v in M.PROFIL_BOBOT.items()],
        "matriks": None if matriks is None else {
            "versi": matriks["versi"], "diambil": matriks["diambil"],
            "node": len(matriks["ids"]),
        },
        "cuaca_bawaan": DS.CUACA_AKTIF,
        "kuota_menit": M.BETA,
        "mulai_menit": M.T_MULAI,
        "selesai_menit": M.T_SELESAI,
        "tanggal_awal": _tanggal_awal(),
        "destinasi": [
            {"id": k, "nama": v["nama"], "kota": v["kota"],
             "kategori": v["kategori"],
             "skor": round(v["skor"], 2), "lat": v["lat"], "lon": v["lon"]}
            for k, v in sorted(destinasi.items())
        ],
    }


# ---------------------------------------------------------------- penangan HTTP
class Penangan(BaseHTTPRequestHandler):
    server_version = "OptimizerItinerary/1.0"

    def log_message(self, format, *args):           # noqa: A002
        # Catatan bawaan terlalu berisik karena halaman menanya status berkala.
        if "/api/status" not in self.path:
            sys.stderr.write(f"  {self.command} {self.path}\n")

    # -------------------------------------------------- pembantu
    def _balas_json(self, muatan, kode=200):
        isi = json.dumps(muatan, ensure_ascii=False).encode("utf8")
        self.send_response(kode)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(isi)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(isi)

    def _balas_berkas(self, nama):
        jalur = os.path.normpath(os.path.join(STATIS, nama))
        if not jalur.startswith(STATIS) or not os.path.isfile(jalur):
            self._balas_json({"galat": "berkas tidak ditemukan"}, 404)
            return
        with open(jalur, "rb") as f:
            isi = f.read()
        ext = os.path.splitext(jalur)[1].lower()
        self.send_response(200)
        self.send_header("Content-Type", JENIS.get(ext, "application/octet-stream"))
        self.send_header("Content-Length", str(len(isi)))
        # Tanpa ini peramban menyimpan halaman dan skrip, sehingga perubahan tidak
        # terlihat sampai muat ulang paksa. Berkasnya kecil dan peladennya lokal.
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(isi)

    # -------------------------------------------------- GET
    def do_GET(self):                               # noqa: N802
        bagian = urlparse(self.path)
        jalur = bagian.path

        if jalur in ("/", "/index.html"):
            self._balas_berkas("index.html")
        elif jalur == "/api/keterangan":
            try:
                self._balas_json(keterangan())
            except Exception as galat:              # noqa: BLE001
                self._balas_json({"galat": str(galat)}, 500)
        elif jalur == "/api/status":
            kerja_id = (parse_qs(bagian.query).get("id") or [""])[0]
            with _kunci_kerja:
                kerja = _kerja.get(kerja_id)
                salinan = dict(kerja) if kerja else None
            if salinan is None:
                self._balas_json({"galat": "pekerjaan tidak ditemukan"}, 404)
            else:
                self._balas_json(salinan)
        elif jalur.startswith("/statis/"):
            self._balas_berkas(jalur[len("/statis/"):])
        else:
            self._balas_json({"galat": "jalur tidak dikenal"}, 404)

    # -------------------------------------------------- POST
    def do_POST(self):                              # noqa: N802
        jalur = urlparse(self.path).path
        if jalur not in ("/api/jalankan", "/api/geometri"):
            self._balas_json({"galat": "jalur tidak dikenal"}, 404)
            return
        panjang = int(self.headers.get("Content-Length") or 0)
        if panjang > 1_000_000:
            self._balas_json({"galat": "permintaan terlalu besar"}, 413)
            return
        try:
            permintaan = json.loads(self.rfile.read(panjang).decode("utf8") or "{}")
        except json.JSONDecodeError as galat:
            self._balas_json({"galat": f"muatan bukan JSON: {galat}"}, 400)
            return
        if jalur == "/api/geometri":
            try:
                self._balas_json({"hari": geometri_rute(permintaan.get("hari") or [])})
            except Exception as galat:              # noqa: BLE001
                self._balas_json({"galat": str(galat)}, 500)
            return
        self._balas_json({"id": mulai_kerja(permintaan)}, 202)


def main():
    porta = PORTA_BAWAAN
    if "--porta" in sys.argv:
        porta = int(sys.argv[sys.argv.index("--porta") + 1])
    peladen = ThreadingHTTPServer(("127.0.0.1", porta), Penangan)
    print(f"Optimizer itinerary berjalan di http://127.0.0.1:{porta}")
    print("Tekan Ctrl+C untuk berhenti.")
    try:
        peladen.serve_forever()
    except KeyboardInterrupt:
        print("\nperhenti")
    finally:
        peladen.server_close()


if __name__ == "__main__":
    main()
