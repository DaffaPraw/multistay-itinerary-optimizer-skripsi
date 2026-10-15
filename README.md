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

Node tidak lagi depot dan pelanggan, melainkan 90 destinasi wisata dan 30
akomodasi di Semarang dan Surakarta. Tiap node membawa kota, kategori,
koordinat, jam operasional, harga, dan durasi kunjungan.

```
python optimizer_wisata/dataset.py
```
