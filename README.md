# Multistay Itinerary Optimizer

Penyusun rencana perjalanan wisata multi-menginap untuk Semarang dan
Surakarta/Solo, dimodelkan sebagai *Location-Routing Problem* teradaptasi dan
diselesaikan dengan tiga metode: MILP sebagai acuan solusi optimal, Particle
Swarm Optimization sebagai metode utama, dan Clarke-Wright Savings sebagai
heuristik pembanding.

Program skripsi, Teknik Informatika Universitas Tarumanagara.

## Menjalankan

Ketergantungan pihak ketiga sengaja dijaga hanya dua: `openpyxl` untuk membaca
dataset dan `gurobipy` untuk MILP. Selebihnya pustaka standar.

```
pip install openpyxl gurobipy
```

Aplikasi web:

```
python optimizer_wisata/web/server.py --porta 8000
```

lalu buka `http://127.0.0.1:8000`.

Baris perintah:

```
python optimizer_wisata/jalankan.py profil          tiga profil bobot, dataset penuh
python optimizer_wisata/jalankan.py banding         ketiga metode pada subset yang sama
python optimizer_wisata/jalankan.py banding-penuh   ketiganya pada 90 destinasi
python optimizer_wisata/jalankan.py kunci           contoh (2.18a) dan (2.18b)
python optimizer_wisata/jalankan.py pso             satu metode saja
python optimizer_wisata/jalankan.py cws
python optimizer_wisata/jalankan.py milp
```

Perintah metode tunggal menerima `--profil`, `--anggaran`, `--hari`,
`--pengguna`, `--beta`, `--jam-mulai`, dan `--jam-selesai`. PSO menambah
`--partikel`, `--iterasi`, `--inersia`, `--c1`, dan `--c2`; MILP menambah `--n`,
`--hotel`, dan `--batas`.

```
python optimizer_wisata/jalankan.py pso --pengguna 7 --profil hemat --c1 1.8 --c2 1.2
```

Percobaan:

```
python optimizer_wisata/eksperimen.py    akurasi terhadap optimum, 30 seed
python optimizer_wisata/penyetelan.py    penyetelan parameter untuk Bab IV
```

## Isi

| Berkas | Isi |
|---|---|
| `optimizer_wisata/dataset.py` | pemuat 120 node dari Excel, skor (3.1)–(3.5), koreksi cuaca (2.2), matriks jarak |
| `optimizer_wisata/model.py` | objektif (2.1), penalti dan fitness (2.20), validasi, rutin perbaikan bersama |
| `optimizer_wisata/pso.py` | Particle Swarm Optimization, metode utama |
| `optimizer_wisata/clarke_wright.py` | Clarke-Wright Savings, sepuluh langkah |
| `optimizer_wisata/milp_gurobi.py` | MILP dengan Gurobi, acuan solusi optimal |
| `optimizer_wisata/ors.py` | matriks jarak dan geometri rute dari OpenRouteService |
| `optimizer_wisata/jalankan.py` | penggerak utama |
| `optimizer_wisata/eksperimen.py` | percobaan bertingkat, akurasi dan perilaku banyak seed |
| `optimizer_wisata/penyetelan.py` | penyetelan parameter PSO, bobot penalti, profil, cuaca |
| `optimizer_wisata/lampiran_rekayasa.py` | hitung ulang Lampiran 3 pada dataset rekayasa 8 node |
| `optimizer_wisata/gambar_rute.py` | gambar ulang Gambar 2.3, 2.5, dan 2.7 dari hasil |
| `optimizer_wisata/web/` | antarmuka web, peladen `http.server` |

## Model

Node bukan depot dan pelanggan, melainkan **90 destinasi wisata dan 30
akomodasi** di dua kota. Tiap node membawa kota, kategori, koordinat, jam
operasional, harga, durasi kunjungan, dan skor daya tarik.

Perbedaannya dari LRP baku ada tiga. Destinasi **boleh tidak dipilih**, sehingga
yang dicari bukan rute terpendek yang melayani semuanya. Akomodasi dipilih
**per malam**, bukan sekali untuk seluruh perjalanan. Dan yang membatasi muatan
bukan kapasitas kendaraan, melainkan **kuota waktu aktivitas harian**.

Skor daya tarik disusun dari rating dan jumlah ulasan lewat (3.1) sampai (3.5):
rating diseragamkan ke skala lima, dijadikan skor mutu, jumlah ulasan jadi skor
popularitas secara logaritmik, lalu keduanya dirata-ratakan ke rentang 0..10.
Skor itu dikoreksi probabilitas presipitasi hari kunjungan lewat (2.2), dengan
besar koreksi bergantung sifat lokasi: indoor tidak terpengaruh, campuran
separuh, outdoor penuh.

Objektifnya empat suku: kerugian mutu destinasi, kerugian mutu akomodasi, biaya
akomodasi, dan biaya transportasi. Dua suku pertama bersatuan poin skor dan dua
terakhir rupiah, jadi keempatnya **dinormalkan min-max** sebelum dijumlahkan
dengan bobot lambda. Tanpa itu suku rupiah mendominasi dan bobot yang tertulis
tidak benar-benar berlaku.

Bagi PSO dan Clarke-Wright, batasan dipasang sebagai **penalti** pada fitness
(2.20), bukan pembatas keras: anggaran, jam operasional, kuota waktu harian,
kunjungan ganda, cakupan kategori, dan cakupan kota. Bobotnya 10, jauh di atas
rentang Z yang tidak pernah melebihi satu. MILP memasang semuanya sebagai
batasan keras dan tidak memakai penalti sama sekali.

**Ketiga metode menilai solusinya lewat `model.py` yang sama.** Kalau tiap
metode punya rumusnya sendiri, perbedaan hasil bisa berasal dari perbedaan rumus
dan bukan dari kemampuan metodenya. MILP menyusun ulang objektif yang sama dalam
bentuk ekspresi linear Gurobi, memakai batas normalisasi dari `model.py`, lalu
hasilnya dinilai ulang `model.py` secara terpisah sebagai pemeriksaan silang.

## Data jarak

Jarak, waktu tempuh, dan biaya bahan bakar antar node berasal dari **matriks
OpenRouteService**, bukan taksiran koordinat. Seluruh 14.280 pasangan berarah
diambil, karena jaringan jalan tidak simetris: 13.902 di antaranya berbeda
panjang menurut arahnya, dengan selisih terbesar 6,30 km.

Waktu tempuh dikalikan faktor kemacetan, 1,78 di dalam kota dan 1,30 antar kota.
Profil `driving-car` mengembalikan waktu arus bebas tanpa memodelkan kemacetan;
kecepatan tersiratnya terukur 44,5 dan 71,7 km/jam, jauh di atas asumsi 25 dan
55 km/jam yang dipakai proyek ini. Hanya waktu yang dikalikan; jarak dan biaya
bahan bakar tidak.

Matriksnya tersimpan di `optimizer_wisata/hasil/matriks_ors_120.json` dan ikut
dikomit, karena tidak dapat dibangkitkan ulang tanpa kunci API dan kuota. Jalur
cadangan haversine masih ada tetapi tidak pernah terpakai pada percobaan yang
dilaporkan.

Kunci API dibaca dari peubah lingkungan `ORS_API_KEY` atau berkas `~/.ors_key`,
tidak pernah ditulis di dalam kode.

## Catatan

Keluaran percobaan di `optimizer_wisata/hasil/` sengaja tidak dikomit, kecuali
matriks ORS, karena dapat dibangkitkan ulang dari kode. Seed dicatat pada setiap
keluaran supaya hasilnya dapat dihasilkan ulang dan diverifikasi.
