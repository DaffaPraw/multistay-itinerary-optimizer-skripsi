"use strict";

// Halaman menyiapkan permintaan dan menampilkan hasilnya. Seluruh perhitungan
// berjalan di peladen, memakai modul Python yang sama dengan yang dipakai pada
// percobaan, sehingga angka di layar sama dengan angka di Bab IV.

const el = (id) => document.getElementById(id);
const WARNA = ["#a27c57", "#2b3b44", "#2f7d57", "#a8402c", "#5b4a8c"];

let keterangan = null;
let bungkusHasil = null;
let kunciAktif = null;
// Diisi kendali kunci dan tolak pada halaman hasil; sampai itu ada keduanya
// tetap kosong dan permintaan dikirim tanpa penguncian.
let dikunci = new Set();
let ditolak = new Set();

// ------------------------------------------------------------ pembantu
const rupiah = (n) =>
  n === null || n === undefined ? "-" : "Rp" + Math.round(n).toLocaleString("id-ID");

function jam(menit) {
  if (menit === null || menit === undefined) return "-";
  const j = Math.floor(menit / 60), m = Math.round(menit % 60);
  return String(j).padStart(2, "0") + "." + String(m).padStart(2, "0");
}

function durasiTeks(menit) {
  const j = Math.floor(menit / 60), m = Math.round(menit % 60);
  if (j && m) return `${j} jam ${m} mnt`;
  if (j) return `${j} jam`;
  return `${m} mnt`;
}

const angkaDari = (t) => {
  const b = String(t).replace(/[^\d]/g, "");
  return b ? parseInt(b, 10) : 0;
};

const aman = (t) =>
  String(t).replace(/[&<>"]/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function tanggalIndo(iso) {
  const hariNama = ["Minggu", "Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu"];
  const bulanNama = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun",
                     "Jul", "Agu", "Sep", "Okt", "Nov", "Des"];
  const d = new Date(iso + "T00:00:00");
  if (isNaN(d)) return iso;
  return `${hariNama[d.getDay()]}, ${d.getDate()} ${bulanNama[d.getMonth()]}`;
}

// ------------------------------------------------------------ navigasi
function pindah(nama) {
  for (const n of ["beranda", "rencana", "proses", "hasil", "galat"]) {
    el("layar-" + n).classList.toggle("sembunyi", n !== nama);
  }
  document.querySelectorAll(".nav a").forEach((a) => {
    const sasaran = a.dataset.pindah;
    a.classList.toggle("aktif",
      (nama === "beranda" && sasaran === "beranda") ||
      (nama !== "beranda" && sasaran === "rencana"));
  });
  window.scrollTo({ top: 0, behavior: "smooth" });
}

document.addEventListener("click", (e) => {
  const t = e.target.closest("[data-pindah]");
  if (!t) return;
  e.preventDefault();
  pindah(t.dataset.pindah);
});

// ------------------------------------------------------------ keterangan awal
async function muatKeterangan() {
  const r = await fetch("/api/keterangan");
  const isi = await r.json();
  if (!r.ok) throw new Error(isi.galat || "gagal memuat keterangan");
  keterangan = isi;

  el("pilihan-kota").innerHTML = isi.kota.map((k) => `
    <label><input type="checkbox" name="kota" value="${aman(k)}" checked>
      <span>${aman(k)}</span></label>`).join("");

  el("pilihan-kategori").innerHTML = isi.kategori.map((k) => `
    <div class="kategori-item">
      <input type="checkbox" class="kat-centang" value="${aman(k)}">
      <span class="nama-kat">${aman(k)}</span>
      <span class="min-label">Min.</span>
      <span class="mini-cacah">
        <button type="button" data-min="-1">&minus;</button>
        <input type="number" class="kat-min" value="1" min="0" max="9" readonly>
        <button type="button" data-min="1">+</button>
      </span>
    </div>`).join("");

  // Ketiga profil dijalankan sekaligus sebagai perilaku bawaan. Pemilih profil
  // tunggal disediakan pada Pilihan Lanjutan dan hanya dipakai ketika menguji.
  el("profil").innerHTML =
    `<option value="semua" selected>Ketiganya sekaligus</option>` +
    isi.profil.map((p) => `<option value="${p.kunci}">${aman(p.nama)} saja</option>`).join("");
  el("daftar-profil").innerHTML =
    isi.profil.map((p) => `<span class="cip">${aman(p.nama)}</span>`).join("");

  el("tanggal").value = isi.tanggal_awal || "mengikuti data cuaca";
  el("jam-mulai").value = jam(isi.mulai_menit);
  el("jam-selesai").value = jam(isi.mulai_menit + isi.kuota_menit);

  const m = isi.matriks;
  el("keterangan-dataset").textContent =
    `${isi.jumlah_destinasi} destinasi dan ${isi.jumlah_akomodasi} akomodasi. ` +
    (m ? `Jarak dari jaringan jalan OpenRouteService, diambil ${m.diambil}.`
       : "Jarak masih taksiran dari koordinat.");

  el("pita-angka").innerHTML = `
    <div><b>${isi.jumlah_destinasi}</b>destinasi terkurasi</div>
    <div><b>${isi.jumlah_akomodasi}</b>pilihan akomodasi</div>
    <div><b>2</b>kota, Semarang dan Solo</div>
    <div><b>${m ? "14.280" : "-"}</b>pasangan rute jaringan jalan</div>`;

  perbaruiRingkasan();
}

// ------------------------------------------------------------ formulir
function minatTerpilih() {
  const hasil = {};
  document.querySelectorAll(".kategori-item").forEach((d) => {
    const c = d.querySelector(".kat-centang");
    if (c.checked) hasil[c.value] = parseInt(d.querySelector(".kat-min").value, 10) || 0;
  });
  return hasil;
}
function perbaruiRingkasan() {
  const kota = [...document.querySelectorAll('input[name="kota"]:checked')].map((c) => c.value);
  el("r-kota").textContent = kota.length ? kota.join(" & ") : "Menunggu pilihan";
  el("r-hari").textContent = el("hari").value + " Hari";
  el("r-jam").textContent = `${el("jam-mulai").value} - ${el("jam-selesai").value}`;
  el("r-anggaran").textContent = rupiah(angkaDari(el("anggaran").value));

  const minat = minatTerpilih();
  const kunci = Object.keys(minat);
  el("r-fokus").innerHTML = kunci.length
    ? kunci.map((k) => `<span class="cip">${aman(k)} (min ${minat[k]})</span>`).join("")
    : `<span class="cip">Semua kategori</span>`;

  const pilihan = el("profil") ? el("profil").value : "semua";
  const daftar = el("daftar-profil");
  if (daftar && keterangan) {
    const dipakai = pilihan === "semua"
      ? keterangan.profil
      : keterangan.profil.filter((p) => p.kunci === pilihan);
    daftar.innerHTML = dipakai.map((p) => `<span class="cip">${aman(p.nama)}</span>`).join("");
  }

  const n = kota.length;
  el("bantu-kota").textContent = n === 2
    ? "Kedua kota dipilih, sehingga itinerary wajib mencakup keduanya."
    : n === 1 ? "Perjalanan satu kota." : "Pilih sekurang-kurangnya satu kota.";
}

document.addEventListener("input", (e) => {
  if (e.target.id === "anggaran") {
    const n = angkaDari(e.target.value);
    e.target.value = n ? n.toLocaleString("id-ID") : "";
  }
  perbaruiRingkasan();
});
document.addEventListener("change", perbaruiRingkasan);

document.addEventListener("click", (e) => {
  const cacah = e.target.closest("[data-ubah]");
  if (cacah) {
    const i = el("hari");
    i.value = Math.min(7, Math.max(1, parseInt(i.value, 10) + parseInt(cacah.dataset.ubah, 10)));
    perbaruiRingkasan();
  }
  const mini = e.target.closest("[data-min]");
  if (mini) {
    const i = mini.parentElement.querySelector(".kat-min");
    i.value = Math.min(9, Math.max(0, parseInt(i.value, 10) + parseInt(mini.dataset.min, 10)));
    const c = mini.closest(".kategori-item").querySelector(".kat-centang");
    if (!c.checked) c.checked = true;
    perbaruiRingkasan();
  }
});
function kumpulkan() {
  return {
    kota: [...document.querySelectorAll('input[name="kota"]:checked')].map((c) => c.value),
    minat: minatTerpilih(),
    hari: parseInt(el("hari").value, 10),
    anggaran: angkaDari(el("anggaran").value),
    profil: el("profil").value || "semua",
    metode: el("metode").value,
    seed: parseInt(el("seed").value, 10) || 42,
    kunci: [...dikunci],
    tolak: [...ditolak],
  };
}

// ------------------------------------------------------------ kirim
function tampilkanGalat(pesan, jejak) {
  el("galat-isi").innerHTML =
    `<strong>Gagal menyusun itinerary.</strong><p>${aman(pesan)}</p>` +
    (jejak ? `<pre>${aman(jejak)}</pre>` : "");
  pindah("galat");
}
async function kirim(ev) {
  if (ev) ev.preventDefault();
  const minta = kumpulkan();
  if (!minta.kota.length) return tampilkanGalat("Pilih sekurang-kurangnya satu kota.");
  if (minta.anggaran < 100000)
    return tampilkanGalat("Anggaran terlalu kecil untuk satu malam akomodasi.");

  el("tombol-jalan").disabled = true;
  el("tahap").textContent = "mengirim permintaan";
  el("bilah-isi").style.width = "3%";
  tandaiTahap(0);
  pindah("proses");

  try {
    const r = await fetch("/api/jalankan", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(minta),
    });
    const isi = await r.json();
    if (!r.ok) throw new Error(isi.galat || "peladen menolak permintaan");
    await tunggu(isi.id);
  } catch (g) {
    tampilkanGalat(g.message);
  } finally {
    el("tombol-jalan").disabled = false;
  }
}
function tandaiTahap(ke) {
  [...el("tahap-daftar").children].forEach((li, i) => {
    li.classList.toggle("selesai", i < ke);
    li.classList.toggle("jalan", i === ke);
  });
}
const tidur = (ms) => new Promise((r) => setTimeout(r, ms));
async function tunggu(id) {
  for (;;) {
    await tidur(900);
    const r = await fetch(`/api/status?id=${encodeURIComponent(id)}`);
    const isi = await r.json();
    if (!r.ok) throw new Error(isi.galat || "pekerjaan hilang");

    if (isi.status === "berjalan") {
      el("tahap").textContent = isi.tahap || "berjalan";
      const b = isi.bagian || 0;
      el("bilah-isi").style.width = Math.round(b * 100) + "%";
      tandaiTahap(b < 0.06 ? 0 : b < 0.1 ? 1 : b < 0.98 ? 2 : 3);
      continue;
    }
    if (isi.status === "gagal") return tampilkanGalat(isi.galat, isi.jejak);
    gambarHasil(isi);
    return;
  }
}

// ------------------------------------------------------------ hasil
function gambarHasil(bungkus) {
  bungkusHasil = bungkus;
  const nama = bungkus.urutan || Object.keys(bungkus.hasil);
  if (!kunciAktif || !bungkus.hasil[kunciAktif]) kunciAktif = nama[0];

  const bar = el("profil-bar");
  bar.classList.toggle("sembunyi", nama.length < 2);
  if (nama.length >= 2) {
    const terbaik = nama.reduce((a, b) =>
      bungkus.hasil[b].Z < bungkus.hasil[a].Z ? b : a);
    bar.innerHTML = nama.map((n) => {
      const h = bungkus.hasil[n];
      return `<button type="button" class="profil-kartu" data-profil="${n}">
        <span class="pk-nama">${aman(h.profil)} &middot; ${aman(h.metode)}</span>
        <span class="pk-z">${h.Z.toFixed(4)}</span>
        <span class="pk-rinci">${h.jumlah_destinasi} destinasi &middot;
          ${rupiah(h.biaya.total)}</span>
        ${n === terbaik ? '<span class="pk-tandai">nilai objektif terkecil</span>' : ""}
      </button>`;
    }).join("");
    bar.querySelectorAll("[data-profil]").forEach((b) =>
      b.addEventListener("click", () => { kunciAktif = b.dataset.profil; gambarSatu(); }));
  }

  pindah("hasil");
  gambarSatu();
}
function gambarSatu() {
  const b = bungkusHasil, h = b.hasil[kunciAktif];

  el("profil-bar").querySelectorAll("[data-profil]").forEach((x) =>
    x.classList.toggle("aktif", x.dataset.profil === kunciAktif));

  // ---------------------------------------------------- pita dan kepala
  const pita = el("pita-berhasil");
  pita.classList.toggle("gagal", !h.layak);
  el("pita-judul").textContent = h.layak
    ? "Itinerary berhasil dibuat" : "Itinerary belum memenuhi seluruh batasan";
  el("pita-teks").textContent = h.layak
    ? `Disusun dengan ${h.metode} pada profil ${h.profil}.`
    : "Beberapa batasan masih dilanggar. Rinciannya ada pada catatan di bawah.";
  el("hasil-sub").textContent =
    `Eksplorasi ${h.kota.join(" & ")} · ${b.hari} hari · profil ${h.profil}`;

  // ---------------------------------------------------- kartu statistik
  const sisa = b.anggaran - h.biaya.total;
  el("statistik").innerHTML = `
    <div class="stat">
      <div class="ikon">&#128197;</div><div class="label">Durasi</div>
      <div class="nilai">${b.hari} Hari</div>
      <div class="catat">${h.hari.length ? tanggalIndo(h.hari[0].tanggal) : ""} &ndash;
        ${h.hari.length ? tanggalIndo(h.hari[h.hari.length - 1].tanggal) : ""}</div>
    </div>
    <div class="stat">
      <div class="ikon">&#128506;</div><div class="label">Total jarak</div>
      <div class="nilai">${h.total_jarak.toFixed(0)} km</div>
      <div class="catat">waktu tempuh ${durasiTeks(h.total_tempuh)}</div>
    </div>
    <div class="stat">
      <div class="ikon">&#128205;</div><div class="label">Destinasi</div>
      <div class="nilai">${h.jumlah_destinasi} Lokasi</div>
      <div class="catat">dari ${h.destinasi_kandidat} kandidat</div>
    </div>
    <div class="stat ${sisa >= 0 ? "" : "buruk"}">
      <div class="ikon">&#128181;</div><div class="label">Estimasi biaya</div>
      <div class="nilai">${rupiah(h.biaya.total)}</div>
      <div class="catat">${sisa >= 0 ? "sisa " + rupiah(sisa)
                                     : "melampaui " + rupiah(-sisa)}</div>
    </div>`;

  gambarBiaya(h);
  gambarTeknis(h);
}

// ---------------------------------------------------------- tab jadwal
function gambarBiaya(h) {
  const k = h.komponen, b = h.biaya;
  el("isi-biaya").innerHTML = `
    <div class="kartu-blok">
      <h2 class="blok-judul">Rincian biaya</h2>
      <table class="tabel">
        <tr><th>Pos</th><th class="angka">Jumlah</th></tr>
        <tr><td>Tiket masuk destinasi</td><td class="angka">${rupiah(b.tiket)}</td></tr>
        <tr><td>Akomodasi ${h.akomodasi.length} malam</td>
            <td class="angka">${rupiah(b.akomodasi)}</td></tr>
        <tr><td>Transportasi</td><td class="angka">${rupiah(b.transportasi)}</td></tr>
        <tr class="jumlah"><td>Total</td><td class="angka">${rupiah(b.total)}</td></tr>
      </table>
    </div>
    <div class="kartu-blok">
      <h2 class="blok-judul">Akomodasi per malam</h2>
      <table class="tabel">
        <tr><th>Malam</th><th>Akomodasi</th><th class="angka">Harga</th></tr>
        ${h.akomodasi.map((a) => `<tr><td>Malam ${a.malam}</td>
          <td>${aman(a.nama || "-")}</td>
          <td class="angka">${rupiah(a.harga)}</td></tr>`).join("")}
      </table>
    </div>
    <div class="kartu-blok">
      <h2 class="blok-judul">Komponen fungsi objektif</h2>
      <table class="tabel">
        <tr><th>Komponen</th><th>Lambang</th><th class="angka">Nilai asli</th></tr>
        <tr><td>Total skor destinasi</td><td>L<sub>P</sub></td>
            <td class="angka">${k.L_P.toFixed(4)}</td></tr>
        <tr><td>Total skor akomodasi</td><td>L<sub>H</sub></td>
            <td class="angka">${k.L_H.toFixed(4)}</td></tr>
        <tr><td>Biaya akomodasi</td><td>C<sub>H</sub></td>
            <td class="angka">${rupiah(k.C_H)}</td></tr>
        <tr><td>Biaya transportasi</td><td>C<sub>T</sub></td>
            <td class="angka">${rupiah(k.C_T)}</td></tr>
        <tr class="jumlah"><td>Nilai objektif</td><td>Z</td>
            <td class="angka">${h.Z.toFixed(6)}</td></tr>
      </table>
      <p class="bantu">Keempat komponen dinormalkan min-max lebih dahulu, sehingga Z
        tidak bersatuan dan selalu berada antara nol dan satu. Nilai pada tabel ini
        adalah nilai asli sebelum dinormalkan.</p>
    </div>`;
}
function gambarTeknis(h) {
  const bo = h.bobot || {};
  el("teknis-isi").innerHTML = `
    <table class="tabel">
      <tr><td>Metode</td><td class="angka">${aman(h.metode)}</td></tr>
      <tr><td>Profil bobot</td><td class="angka">${aman(h.profil)}</td></tr>
      <tr><td>Bobot &lambda;<sub>1</sub>..&lambda;<sub>4</sub></td>
        <td class="angka">${[bo.lambda1, bo.lambda2, bo.lambda3, bo.lambda4]
          .map((v) => (v === undefined ? "-" : v.toFixed(2))).join(" / ")}</td></tr>
      <tr><td>Nilai objektif Z</td><td class="angka">${h.Z.toFixed(6)}</td></tr>
      <tr><td>Nilai fitness F</td><td class="angka">${h.F.toFixed(6)}</td></tr>
      ${h.iterasi ? `<tr><td>Iterasi terpakai</td>
        <td class="angka">${h.iterasi}</td></tr>` : ""}
      ${h.seed !== null && h.seed !== undefined
        ? `<tr><td>Seed</td><td class="angka">${h.seed}</td></tr>` : ""}
      <tr><td>Waktu komputasi</td><td class="angka">${h.runtime.toFixed(2)} detik</td></tr>
      <tr><td>Validasi struktur solusi</td>
        <td class="angka">${h.validasi_ok ? "lolos" : "gagal"}</td></tr>
    </table>
    ${(h.validasi_pesan || []).length
      ? `<p class="bantu">${h.validasi_pesan.map(aman).join("<br>")}</p>` : ""}`;
}

// ------------------------------------------------------------ pemasangan
el("formulir").addEventListener("submit", kirim);

muatKeterangan().catch((g) =>
  tampilkanGalat("Gagal memuat keterangan dataset.", String(g))
);
