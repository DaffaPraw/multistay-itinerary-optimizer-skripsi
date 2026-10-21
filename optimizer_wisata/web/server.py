"""
Peladen antarmuka web untuk optimizer itinerary.

Peladen ini memakai http.server dari pustaka standar, bukan kerangka kerja web.
Alasannya dua. Pertama, kebutuhannya memang kecil, yaitu menyajikan satu halaman
dan tiga endpoint. Kedua, ketergantungan pihak ketiga pada program ini sengaja
dijaga tetap dua, yaitu openpyxl untuk membaca dataset dan gurobipy untuk MILP,
sehingga program dapat dijalankan penguji tanpa memasang apa pun selain Gurobi.

Tahap ini baru memuat peladen, penyajian berkas statis, dan modul input
perjalanan. Menjalankan optimasi, halaman hasil, peta, serta kendali kunci dan
tolak belum ada.

Cara pakai:
    python server.py                 lalu buka http://127.0.0.1:8000
    python server.py --porta 8080
"""
import json
import os
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

# Modul inti berada satu tingkat di atas folder web.
AKAR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if AKAR not in sys.path:
    sys.path.insert(0, AKAR)

import dataset as DS                 # noqa: E402
import model as M                    # noqa: E402

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


def ambil_data(kota, kategori, hari):
    """Memuat dataset sekali untuk setiap kombinasi penyaringan, lalu dipakai ulang.

    Pemuatan membaca berkas Excel dan menyusun matriks seluruh pasangan node,
    sehingga mengulanginya pada setiap permintaan akan membuang waktu pada
    pekerjaan yang hasilnya sama.
    """
    tanda = (tuple(sorted(kota or ())), tuple(sorted(kategori or ())), int(hari))
    with _kunci_data:
        if tanda in _simpanan_data:
            return _simpanan_data[tanda]
    data = DS.muat_dataset(
        kota_dipilih=list(kota) if kota else None,
        kategori_dipilih=list(kategori) if kategori else None,
        jumlah_hari=int(hari),
    )
    with _kunci_data:
        _simpanan_data[tanda] = data
    return data

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
        "kuota_menit": M.BETA,
        "mulai_menit": M.T_MULAI,
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
        jalur = urlparse(self.path).path

        if jalur in ("/", "/index.html"):
            self._balas_berkas("index.html")
        elif jalur == "/api/keterangan":
            try:
                self._balas_json(keterangan())
            except Exception as galat:              # noqa: BLE001
                self._balas_json({"galat": str(galat)}, 500)
        elif jalur.startswith("/statis/"):
            self._balas_berkas(jalur[len("/statis/"):])
        else:
            self._balas_json({"galat": "jalur tidak dikenal"}, 404)


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
        print("\nberhenti")
    finally:
        peladen.server_close()


if __name__ == "__main__":
    main()
