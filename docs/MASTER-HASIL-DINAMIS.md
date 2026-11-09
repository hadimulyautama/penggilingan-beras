# Master beras dan hasil samping lintas PadiFlow–TeraFlow

Jenis beras dan hasil samping berasal dari Pengaturan. Kode/ID yang sudah ada
menjadi identitas tetap; nama tampil dapat diganti. Jenis baru memperoleh kode
`spek_…` atau `hs_…`, bukan menumpang kode komoditas lama.

## Alur dan kompatibilitas

- Catat hasil, QC beras, penyelesaian proses, neraca, stok, packing beras,
  kepemilikan, riwayat, laporan dan portal membaca master serta jenis historis.
- Jenis nonaktif tidak ditawarkan untuk pekerjaan baru. Proses berjalan yang
  sudah mencatat jenis itu tetap dapat meneruskan hasil/QC. Stok historis tetap
  bisa dipakai melalui alur sah. Jenis yang sudah dipakai tidak dapat dihapus.
- Ukuran dan bentuk hasil samping yang sudah dipakai tidak bisa diganti:
  perubahan itu akan mengubah arti saldo kemasan historis. Nama boleh diganti.
- Hasil samping dikemas otomatis: karung penuh mengikuti ukuran master dan
  sisanya tetap curah. Tidak ada transaksi packing otomatis tambahan. Endpoint
  packing awal manual tetap menolak seluruh hasil samping, termasuk jenis baru.
- Broken mempertahankan buku pembongkaran karung khususnya. Menir, reject,
  bekatul dan jenis baru memakai alokasi sumber umum, termasuk sumber langsung
  `byproduct_stock` dari penerimaan. Pengeluaran, reservasi dan pemindahan silo
  mengikat pool pemilik yang sama. Pembaca tidak menjumlah produksi dua kali.
- Silo dengan daftar penuh bawaan lama mengikuti seluruh komoditas master G2.
  Daftar silo yang sengaja dibatasi tetap dihormati. Penyimpanan dan pemilih
  sumber menghormati gudang kerja operator.
- Kemas ulang dan retur tetap memakai master kemasan/SKU. Jenis baru dapat
  memakai bahan/ukuran kemasan yang tersedia, tanpa merek hasil samping.

## Kontrak timbang

Beras tetap komoditas `BERAS`/`BERAS_MASUK`; spesifikasinya memakai FK standar
beras. Penerimaan meminta spesifikasi aktif atau bawaan yang dipilih admin.
Tidak ada tebakan otomatis mengganti seluruh stok lama ke spesifikasi baru.

Hasil samping memakai kode jenis huruf besar untuk pengiriman dan akhiran
`_MASUK` untuk penerimaan. Alias historis `BROKEN_MASUK` tetap berlaku. TeraFlow
membaca konfigurasi bersama sebagai aturan virtual, tanpa menyisipkan master
atau mengubah tiket lama. Identitas dan aturan setiap tiket tetap disimpan dalam
snapshot. Nama dari master tidak menimpa aturan timbang/tara yang sudah disetel.
Jenis curah tidak diminta mengisi jumlah karung atau tara karung rekaan.

Penguncian master yang sama melindungi administrasi jenis dari pencatatan
hasil/tiket bersamaan. Kiriman silo memakai tanda terima idempoten yang sama
dengan jalur lama; percobaan ulang mengembalikan hasil tersimpan.

## Migrasi dan rilis

`0124_master_hasil` menyiapkan master hasil samping dan melepas enum QC lama.
Nama Sayur hanya menjadi Ekonomis bila masih persis nama bawaan. `0125_samping_sumber`
menambah FK sumber langsung hasil samping ke silo, dengan constraint tepat satu
sumber (proses atau stok langsung). Tidak ada DML ke tabel transaksi, penghitungan
ulang saldo, backfill, penghapusan histori atau transaksi pengganti.

Uji migrasi lokal membandingkan isi 126 tabel transaksi sebelum/sesudah;
semuanya sama (kolom sumber nullable baru diproyeksikan keluar dari perbandingan).
Pemeriksaan Alembic model/skema tidak menemukan operasi upgrade tambahan.

Rilis TeraFlow lebih dahulu, lalu PadiFlow. Jangan menurunkan skema 0125 bila
sumber langsung baru sudah dipakai: downgrade sengaja menolak. Pemulihan kode
harus tetap memahami sumber baru; jangan menghapus transaksi untuk rollback.

## Cakupan pengujian

`test_master_hasil`, `test_master_rantai_dinamis` dan `test_master_samping_rantai`
menjaga perubahan nama/acuan, hapus/nonaktif, izin, balapan, penerimaan, karung dan
sisa tidak genap, packing beras, stok historis, campuran PK/beras/hasil samping,
pemilik pabrik/pelanggan, reservasi dan replay silo. Regresi kedua aplikasi serta
integrasi HTTP memakai database lokal berawalan `uji_`; tidak memakai produksi.
Hasil run lengkap dilaporkan terpisah bersama revisi yang dirilis.
