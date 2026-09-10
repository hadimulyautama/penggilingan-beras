---
name: ketelusuran-hulu-hilir
description: "Beras putih WAJIB bisa dirunut ke asal PK-nya (dibeli PKB- atau digiling sendiri LOT-) — syarat pemilik 2026-09-04. Rantai sampai PK sudah terbukti; penyosohan BELUM & sengaja ditunda"
metadata:
  type: project
---

**SYARAT PEMILIK (2026-09-04):** beras putih harus bisa ditelusuri ke asalnya —
**PK dibeli dari mana**, atau **gabah dibeli dari mana** kalau PK itu digiling sendiri.
PK punya DUA asal dan keduanya bisa bercampur dalam satu silo: dibeli luar (`PKB-…`) atau
hasil giling sendiri (`LOT-…`). Desain apa pun harus menampung keduanya.

**PENYOSOHAN SENGAJA DITUNDA.** Pemilik: "penyosohan masih nanti". Jangan garap tanpa
diminta. Ditawarkan 2026-09-04 dan ditolak untuk sekarang — tetapi ONGKOSNYA NAIK seiring
waktu: selama produksi belum punya satu pun penyosohan, tak ada data yang perlu dimigrasi.

**YANG SUDAH TERBUKTI JALAN (sampai PK):**
`LOT-… → milling_process_sources → PGR-…/batch lepas → GB-… → tiket TRX-… → supplier`.
Diuji sungguhan lewat `scripts/telusur_lot.py` (2 batch basah lewat 1 pengeringan + 1 batch
kering langsung, satu silo, 3 supplier berbeda): 22.000 kg utuh, ketiga nama muncul, dan
biaya bahan = jumlah per batch (Rp117,3 jt) bukan satu harga × total (Rp114,4 jt).
**PK TIDAK punya kode sendiri** — ia memakai kode lot gilingnya. Rantai kode:
`TRX- → GB- → PGR- → LOT- (PK) → TRF- → POL- → OUT-`, plus `PKB-` untuk PK luar.

**LUBANGNYA:** `PolishingSiloUsage` hanya mencatat silo + berat, TIDAK mencatat PK dari lot
mana. Jadi beras putih berhenti di "dari Silo A". Ini cacat yang PERSIS SAMA dengan yang
sudah diperbaiki di giling — penunjuk yang tak mendaftar isinya. Bentuk perbaikannya sudah
diketahui: cermin `milling_process_sources` (migrasi 0031), yaitu tabel
`polishing_process_sources` berisi satu baris per sumber PK + beratnya, DISALIN saat
penyosohan mulai (isi silo berubah sesudahnya; berapa yang masuk mesin tak boleh ikut
berubah). Ditambah bagian "Asal PK" di laporan POL-, dan supplier dibaca dari sumber itu —
bukan dari penunjuk tunggal.

**POLA YANG BERULANG DI REPO INI — periksa tiap kali ada "proses mengonsumsi wadah":**
penunjuk tunggal (`proc.drying_lot_id`) benar HANYA selama wadahnya tak boleh dicampur.
Begitu boleh, ia menyebut sumber pertama dan mendiamkan sisanya — diam-diam, dan hasilnya
tetap tampak masuk akal. Sudah dua kali menggigit: HPP (diperbaiki migrasi 0031) dan
laporan supplier (diperbaiki 2026-09-04, lihat `test_isi_giling.py`). **Cacat ini
BERSEMBUNYI kalau semua batch dari supplier/harga yang sama** — karena itu skenario ujinya
wajib memakai supplier & harga yang berbeda-beda.

**STOK PK GUDANG 1 ITU NYATA — hasil giling memang PK.** Dicatat, tetapi DITURUNKAN bukan
disimpan: `tersedia = produced − transferred − dijual`, per `milling_process_id` (= per LOT),
lewat `_pk_breakdown()`. Tampil di Beranda ("STOK PK") dan dirinci per lot & per jenis oleh
`dashboard._stok_pk`. Desain turunan ini benar — tak ada angka kembar yang bisa berselisih.

**JANGAN buru-buru menghapus `PkStockGudang1` & `MillingPkRouting`.** Keduanya memang tak
pernah ditulis/dibaca, dan saya sempat menyarankan menghapusnya — itu terlalu cepat.
Docstring keduanya adalah SATU-SATUNYA catatan tertulis untuk dua aturan yang belum pernah
dibangun: (a) buffer tumpukan PK Gudang 1 **maks 30 ton, dipisah per lot**, dan (b) PK
diarahkan ke **`tumpuk` vs `siap_transfer`**. Stok turunan yang ada sekarang tidak mengenal
keduanya: tak ada batas 30 ton yang ditegakkan, dan tak ada beda antara PK yang menumpuk di
buffer dan yang siap dikirim. Menghapus tabelnya = menghapus jejak dua aturan itu.
**Tanya pemilik dulu apakah keduanya masih berlaku**; kalau tidak berlaku, baru hapus.
(Chip tugas penghapusan sempat dibuat & dijalankan 2026-09-04 lalu sesinya dihapus sebelum
mengubah apa pun — jangan dijalankan ulang tanpa jawaban itu.)

**ATURAN PK GUDANG 1 — dipastikan pemilik 2026-09-05.** Hasil giling OTOMATIS menumpuk &
jadi stok Gudang 1; tak ada tindakan yang perlu dicatat untuk "menumpuk". Pengecualiannya:
saat proses giling PK bisa langsung dibawa ke Gudang 2 — dan itu SUDAH didukung, transfer
tak menuntut giling selesai. **Batas tumpukan 80 ton = batas FISIK LANTAI** (karena itu di
`config.g1_pk_tumpukan_maks_kg`, bukan di halaman Pengaturan). Dilampaui →
DIPERINGATKAN, bukan ditolak: PK sudah keluar dari mesin sebelum siapa pun mengetiknya.
**Yang mencatat pemindahan G1→G2 adalah STAFF, bukan operator** — dipastikan pemilik, dan
gerbangnya sudah tepat begitu (`can_transfer_pk`). Catatan praktis: peran "staff" TIDAK BISA
dibuat lagi lewat aplikasi (pilihannya operator/admin/superadmin), jadi orang yang
mengerjakan ini perlu akun **Admin**; akun "staff" lama tetap berfungsi.
