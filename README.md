# Multistay Itinerary Optimizer

Titik awal: penyelesai Location-Routing Problem dari tugas mata kuliah.

Tiga metode yang nantinya dipakai ulang untuk penyusunan itinerary wisata:

| Berkas | Metode |
|---|---|
| `optimizer/greedy_clarke_wright_v2.py` | Clarke-Wright Savings |
| `optimizer/pso_v2.py` | Particle Swarm Optimization |
| `optimizer/mtz_gurobi_solver_v2.py` | Miller-Tucker-Zemlin, diselesaikan Gurobi |
| `optimizer/dataloader_v2.py` | pemuat instance |

Pada bentuk ini depot dipilih dari kandidat, pelanggan wajib dilayani semua, dan
kapasitas kendaraan membatasi muatan per rute.

## Adaptasi ke itinerary wisata

`optimizer_wisata/` menampung versi yang sedang dikerjakan. Yang sudah ada baru
pemuat datanya; penyelesainya masih di `optimizer/`.

| Berkas | Isi |
|---|---|
| `optimizer_wisata/dataset.py` | pemuat node wisata dari `data/*.xlsx` |
| `optimizer_wisata/model.py` | representasi solusi dan fungsi objektif (2.1) |

Node tidak lagi depot dan pelanggan, melainkan 90 destinasi wisata dan 30
akomodasi di Semarang dan Surakarta. Tiap node membawa kota, kategori,
koordinat, jam operasional, harga, durasi kunjungan, dan skor daya tarik.

Skor disusun dari rating dan jumlah ulasan lewat persamaan (3.1) sampai (3.5):
rating diseragamkan ke skala lima, dijadikan skor mutu, jumlah ulasan jadi skor
popularitas secara logaritmik, lalu keduanya dirata-ratakan ke rentang 0..10.

Skor itu lalu dikoreksi probabilitas presipitasi hari kunjungan lewat persamaan
(2.2). Besarnya koreksi bergantung sifat lokasi: indoor tidak terpengaruh,
campuran separuh, outdoor penuh. Koreksinya dikendalikan saklar `cuaca_aktif`
yang bawaannya 0, yaitu mati.

Jarak, waktu tempuh, dan biaya bahan bakar antar node disusun `bangun_matriks`.
Jaraknya masih ditaksir dari koordinat, yaitu haversine dikali 1,3, dan masih
perlu diganti hasil layanan rute sebelum percobaan akhir.

Objektifnya empat suku: kerugian mutu destinasi, kerugian mutu akomodasi, biaya
akomodasi, dan biaya transportasi. Dua suku pertama bersatuan poin skor dan dua
terakhir rupiah, jadi keempatnya dinormalkan min-max dulu sebelum dijumlahkan
dengan bobot lambda. Tanpa normalisasi suku rupiah akan mendominasi dan bobot
yang tertulis tidak benar-benar berlaku.

```
python optimizer_wisata/dataset.py
```
