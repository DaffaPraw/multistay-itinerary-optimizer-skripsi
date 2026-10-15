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
