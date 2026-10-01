# Jasa (toll milling) — irisan pertama, 1 Oktober 2026

Spek pemilik: `QA/SPEK-JASA-FINAL-2026-10-01.md` (menggantikan enam pesan jasa
sebelumnya; keenamnya saling mencabut dan **tidak boleh dipakai**).

## Yang menentukan seluruh bentuknya

**Satu-satunya batasan adalah KEPEMILIKAN.** *"multi silo giling dan multi silo
sosoh memungkinkan. yang tidak memungkinkan adalah menggabungkan barang jika
kepemilikan berbeda. itu saja batasannya."*

**Kedalaman FLEKSIBEL, tidak dinyatakan di muka.** *"jika hanya jadi pk dan pk
ternyata keluar berarti hanya sampai pk."* Karena itu TIDAK ADA kolom
`kedalaman` — sampai mana sebuah pesanan diproses dibaca dari di mana barangnya
sekarang berada.

**Tidak ada batasan ton, di mana pun, dan tidak ada hubungannya dengan biaya.**
*"biaya adalah urusan keuangan. app timbangan dan operasional tidak mengurusi
keuangan."* Jadi tabel `jasa` tanpa kolom harga/tarif/total, dan tak ada ambang
yang memicu peringatan apa pun (permintaan angka kapasitas lantai G2 DICABUT).

**Dua bobot yang tidak ada dan tidak akan ada:** susut sekam (bisa terhisap
penyedot debu) dan bobot gabah setelah dikeringkan (butuh flowing scale, belum
ada). Keterbatasan ALAT, bukan kelalaian pencatatan — jadi permanen sampai
mesinnya ada. Konsekuensi yang harus diingat: untuk lot dari gabah BASAH, "isi
silo" dan "bobot masuk giling" adalah bobot BASAH, dan rendemen KS tak sejenis
dengan rendemen KL.

**Bekatul BERALIH milik, bukan hilang jejak.** Miliknya pabrik, boleh dijual,
tetapi asalnya per proses tetap harus terbaca untuk pemilik barangnya.

## Yang SUDAH dikerjakan (irisan pertama — gabah kering)

Migrasi **0064_jasa**: tabel `jasa`; `jasa_id` pada ENAM tabel
(`purchase_batches`, `drying_lots`, `silo_storage`, `milling_process`,
`internal_transfers`, `pk_gudang2_intakes`); `purchase_batches.supplier_id` jadi
nullable + `CHECK ck_purchase_batches_beli_atau_jasa`;
`timbangan_transaksi.jasa_id` (+ `pelanggan_id` idempoten — lihat jebakan di
bawah).

Penjaga `app/services/jasa.py`, dipanggil di pengering, silo G1, giling, silo G2,
dan pemindahan tumpukan G2 — berkunci basis data, bukan pemeriksaan Python saja.
Saringan `jasa_id IS NULL` di seluruh pembaca stok pabrik & laporan pembelian.
Aliran masuk: `purchase.pesanan_jasa_dari_tiket` membuat pesanan saat operator
menerima tiketnya. Uji: `tests/pg/test_jasa_ketaatan.py` (12 uji).

Rinciannya di `CLAUDE.md` bagian "Jasa (toll milling)".

## Irisan KEDUA — sampai beras, ketiga komoditas (migrasi 0065)

Pemilik menegaskan keputusan nomor 1: jasa dari **gabah basah, gabah kering,
DAN beras PK**. Pembatasan "gabah kering saja" di irisan pertama bukan
permintaannya — ia pembatasan sementara karena dua jalur belum utuh. Keduanya
dibangun di irisan ini:

  · `jasa_id` pada LIMA tabel sisanya (`pk_purchase_batches`,
    `polishing_process`, `finished_goods_stock`, `byproduct_stock`,
    `outgoing_records`) + `pk_purchase_batches.supplier_id` nullable + CHECK;
  · `jasa.pemilik_hasil()` — beras/menir/broken/reject kembali, bekatul beralih
    milik; penyosohan mewarisi pemilik dari silonya, dan penjaga penolaknya
    DICABUT bersama ujinya;
  · PK walk-in jasa: penolakan di `create_pk_purchase_dari_timbang` dicabut,
    pesanannya dibuat lewat penolong yang sama dengan gabah;
  · gabah basah jasa WAJIB ke pengering (`tumpukan.tujuan_sah`);
  · saringan stok barang jadi & bekatul; `packaging.py` sengaja TIDAK disaring.

⚠ **YANG MASIH TERBUKA, dan ia nyata:** pengambilan barang jasa belum punya
jalur. `outgoing_records.jasa_id` sudah ada kolomnya, tetapi borang barang
keluar belum menawarkan barang jasa kepada pemiliknya — dan memang tak boleh
menawarkannya sebagai PENJUALAN. Jadi beras pelanggan tercatat benar sebagai
miliknya dan tak bisa terjual keliru, tetapi pengambilannya belum bisa dicatat:
stoknya akan tetap berdiri sesudah truknya pergi. Itu lubang PEMBUKUAN, bukan
bahaya — dan ia pekerjaan irisan berikutnya bersama `sisa_jasa()`, aturan
"selesai", layar Jasa, dan notanya.

## Yang BELUM — berurutan

1. **PENGAMBILAN barang jasa** — lihat peringatan di atas. Ini yang paling
   mendesak: tanpanya pesanan tak pernah bisa ditutup.
2. **Sisa & aturan selesai**: SELESAI = pernah ada barang masuk DAN tak ada lagi
   barang ber-`jasa_id` ini di pabrik. Satu penolong `sisa_jasa(jasa_id)`, satu
   sumber untuk kartu maupun pemeriksaan selesai.
4. **Layar Jasa** (menampilkan, bukan menerima) + **nota jasa**: bobot & milik
   saja, tanpa uang; bekatul di LUAR "total kembali", per proses sosoh;
   selisihnya SATU baris yang tidak dirinci dan mengaku tidak diukur terpisah.
5. **Gabah basah**: `IntakeJenis.tujuan_wajib='dryer'` — jalurnya sudah dibaca
   `api.py` tetapi belum pernah diisi satu entri pun. Satu nilai, bukan fitur.
6. **PK walk-in** (`pk_purchase_batches`): Gudang 2 saja.
7. **MILESTONE TERSENDIRI, jangan dicicil**: jasa sosoh BROKEN & MENIR. Rumus
   rendemen penyosohan berpenyebut PK; sosoh broken dengan rumus itu
   menghasilkan angka yang BENTUKNYA rendemen dan ARTINYA bukan — dan seluruh
   pagar kewajaran berdiri di atas angka itu. Jangan menambah medan "jenis
   bahan" penyosohan "sekalian": medan yang tak pernah berubah membuat orang
   berikutnya menyangka jalurnya sudah ada.

## Yang mudah salah

- **Spek D4 keliru satu hal**: `timbangan_transaksi.pelanggan_id` ada di
  PRODUKSI, tetapi lahir dari rantai migrasi repo `timbangan`
  (`0027_pelanggan_transaksi`, tabel versi `alembic_version_timbangan`) — BUKAN
  rantai produksi. Basis data uji `tests/pg/` dibangun dari rantai produksi saja,
  jadi tanpa penjaga idempoten di 0064 setiap uji yang menyentuh tiket gagal
  dengan "column does not exist".
- **`find_or_create_supplier` adalah jebakan**: tiket MASUK tanpa `supplier_id`
  dulu melahirkan pemasok dari `pihak_nama`. Cabang jasa WAJIB diperiksa lebih
  dulu, kalau tidak pelanggan jadi baris `suppliers` dan barang yang tak pernah
  dibeli ikut ke skor pemasok, laporan pembelian, dan HPP.
- **Dua `_lot_suppliers()` memakai INNER JOIN** (silo.py & drying.py). Sudah
  dibetulkan jadi `outerjoin`; kalau salah satu dikembalikan, lot berisi gabah
  jasa menampilkan daftar KOSONG — barisnya hilang, bukan angkanya salah.
- **Tumpukan di app ini ALARM, bukan ruang tunggu** ("ada tumpukan = ada
  pembelian berlebih"). Aturan itu untuk gabah DIBELI. Barang jasa yang menunggu
  giliran bukan kesalahan pembelian — kalimatnya berbeda, kartunya tetap ada.
- **Tanda ⚠️ TERCAMPUR tidak dipakai untuk silo sepemilik**: pencampurannya
  dikehendaki pemilik barangnya, dan tanda seru yang sering salah berhenti
  dibaca.
- **Pagar rendemen jasa MENOLAK, dan hanya batas MUSTAHIL.** Ambang yang lebih
  ketat ("di bawah X% mustahil") tak boleh dipasang untuk lot KS/MIX: penyebutnya
  bobot basah dan kadar airnya tak diukur. Dan jangan mengoreksi bobot dengan
  hitungan kadar air — perkiraan yang tampil seperti hasil ukur adalah kesalahan
  paling mahal di seluruh pekerjaan jasa.

## Satu hal untuk DIKETAHUI, bukan dikerjakan

`g1_pk_tumpukan_maks_kg = 80_000` (`app/config.py`) sudah hidup di jalur produksi
harian. Keputusan "tidak ada batasan ton" diucapkan dalam percakapan tentang
jasa; mencabut pagar yang sedang bekerja di jalur lain harus DIMINTA, bukan
disimpulkan. Dan di sana perilakunya memang sudah bukan penolakan — lantai penuh
DIBERITAHU, bukan ditolak.
