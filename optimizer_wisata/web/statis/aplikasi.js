"use strict";

// Halaman menyiapkan permintaan dan menampilkan hasilnya. Seluruh perhitungan
// berjalan di peladen, memakai modul Python yang sama dengan yang dipakai pada
// percobaan, sehingga angka di layar sama dengan angka di Bab IV.

const el = (id) => document.getElementById(id);

let keterangan = null;

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
  for (const n of ["beranda", "rencana", "galat"]) {
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

// ------------------------------------------------------------ pemasangan
// Tanpa ini peramban mengirim formulir secara bawaan, halaman memuat ulang, dan
// isian berpindah ke query string. Penanganan sebenarnya menyusul bersama
// pengiriman permintaan optimasi.
el("formulir").addEventListener("submit", (e) => e.preventDefault());

muatKeterangan().catch((g) =>
  tampilkanGalat("Gagal memuat keterangan dataset.", String(g))
);
