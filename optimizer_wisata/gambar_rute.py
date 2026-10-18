"""
Menggambar ulang Gambar 2.3, 2.5, dan 2.7, yaitu ilustrasi rute dataset rekayasa.

Gambar lama melukiskan rute sebelum model diubah, sehingga tidak lagi sesuai dengan
Tabel L3.3 sampai L3.5. Berkas ini menggambar ulang ketiganya langsung dari hasil
yang tersimpan, supaya gambar dan tabel tidak dapat lagi berselisih.
"""
import json
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, FancyArrowPatch

KOOR = {"H1": (0, 0), "D1": (1, 3), "D2": (3, 1), "D3": (5, 3),
        "H2": (10, 0), "D4": (9, 2), "D5": (12, 1), "D6": (11, 4)}
KOTA = {"H1": "Semarang", "H2": "Solo"}
WARNA = {1: "#0070C0", 2: "#ED7D31"}
ABU = "#A6A6A6"
BERKAS = {"Mixed Integer Linear Programming": "gambar_2_3_milp.png",
          "Clarke-Wright Savings": "gambar_2_5_cws.png",
          "Particle Swarm Optimization": "gambar_2_7_pso.png"}
JARI = 0.42


def gambar(nama, rute, dipakai, keluar):
    fig, ax = plt.subplots(figsize=(7.4, 3.3), dpi=300)
    ax.set_aspect("equal")
    ax.axis("off")

    for hari, urutan in rute.items():
        w = WARNA[int(hari)]
        for a, b in zip(urutan, urutan[1:]):
            (x1, y1), (x2, y2) = KOOR[a], KOOR[b]
            dx, dy = x2 - x1, y2 - y1
            panjang = (dx * dx + dy * dy) ** 0.5
            if panjang < 1e-9:
                continue
            ux, uy = dx / panjang, dy / panjang
            ax.add_patch(FancyArrowPatch(
                (x1 + ux * JARI, y1 + uy * JARI), (x2 - ux * JARI, y2 - uy * JARI),
                arrowstyle="-|>", mutation_scale=11, linewidth=1.5, color=w,
                shrinkA=0, shrinkB=0, zorder=1))

    for n, (x, y) in KOOR.items():
        w = dipakai.get(n, ABU)
        ax.add_patch(Circle((x, y), JARI, facecolor="white", edgecolor=w,
                            linewidth=1.8, zorder=2))
        ax.text(x, y, n, ha="center", va="center", fontsize=6.4,
                color="#404040", zorder=3)
        if n in KOTA:
            ax.text(x, y - JARI - 0.42, KOTA[n], ha="center", va="top",
                    fontsize=6.4, fontweight="bold", color="#262626")

    for i, (hari, w) in enumerate(sorted(WARNA.items())):
        ax.add_patch(plt.Rectangle((13.4, 3.55 - i * 0.62), 0.78, 0.34,
                                   facecolor=w, edgecolor="none",
                                   transform=ax.transData, zorder=3))
        ax.text(14.35, 3.72 - i * 0.62, f"hari {hari}", va="center",
                fontsize=6.4, color="#404040")

    ax.set_xlim(-1.1, 16.4)
    ax.set_ylim(-1.5, 4.9)
    fig.savefig(keluar, bbox_inches="tight", pad_inches=0.04, transparent=False)
    plt.close(fig)
    print(f"  {nama:34} -> {os.path.basename(keluar)}")


def main():
    akar = os.path.dirname(os.path.abspath(__file__))
    h = json.load(open(os.path.join(akar, "hasil", "lampiran3_baru.json"), encoding="utf-8"))
    tujuan = os.path.join(akar, "hasil", "gambar")
    os.makedirs(tujuan, exist_ok=True)
    for nama, r in h["hasil"].items():
        dipakai = {}
        for hari, urutan in r["rute"].items():
            for n in urutan:
                dipakai.setdefault(n, WARNA[int(hari)])
        gambar(nama, r["rute"], dipakai, os.path.join(tujuan, BERKAS[nama]))


if __name__ == "__main__":
    main()
