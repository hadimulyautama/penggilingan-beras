# Perapian detail penerimaan: tiga temuan visual

Baseline main 83acc01 (termasuk komponen portal yang masuk bersamaan). Tidak mengubah controller, layanan, API, model, stok, konfigurasi akses, rumus, formulir atau JavaScript transaksi.

1. Kepala: mengurangi padding/jarak judul/bobot. Teks Pemilik catatan: Milik pabrik yang berulang tidak ditampilkan pada kepala; badge Milik pabrik serta seluruh catatan di riwayat tetap ada. Identitas pihak tiket tetap terpisah, pemilik jasa/campuran tetap disebut lengkap.
2. Kartu: menghapus padding internal judul/fakta/timbang yang terwarisi dari kartu vendor, karena kartu detail sudah memiliki padding sendiri. Mengurangi margin judul–isi, paragraf bantuan dan ringkasan; tidak memotong rincian atau mengubah nilai.
3. Tombol: menghapus margin horizontal bawaan terima-lanjutan pada tombol Buka Pekerjaan. Tombol ponsel mengisi ruang dalam kartu, bukan ditambah margin di luar lebar 100%. Pada lebar 320/390/768 px, inset terukur kiri dan kanan sama-sama 17 px (padding 16 + border 1).

CSS tetap khusus detail; URL aset menggunakan rapi=2 agar perangkat mengambil perapian terbaru.

## Kompatibilitas komponen dan CI

Baseline pembaruan portal menimbulkan dua kegagalan tes ikon: base memilih ikon dari kunci halaman dan mengabaikan kolom ikon TAB. Diperbaiki dari sumber repo tampilan, bukan mengedit vendor tangan: macro menerima ikon konfigurasi, alias konfigurasi asli memakai SVG portal, ikon khusus tetap memakai nilainya. Pengujian ikon bernama kini memeriksa hasil SVG macro, bukan keberadaan cabang inline dalam base; tes penggantian ikon TAB yang sama tetap dipertahankan tanpa pelonggaran.

Sumber paket dinaikkan ke 416. Rilis disinkronkan melalui scripts/sinkron.py dari snapshot sumber rilis terisolasi berbasis paket 414 yang sudah masuk main, dengan perubahan sumber ikon/base/versi saja. Ini mencegah tersalinnya fitur katalog Pekerjaan yang masih dikerjakan di working tree sumber. Perbaikan yang sama tersedia pada berkas sumber komponen. Manifest vendor dibentuk skrip resmi; file sumber lain tidak disalin dari working tree yang belum selesai.

## Verifikasi lokal sebelum merge

- 800 tes non-PG final lulus, termasuk kompatibilitas ikon, manifest, kelas CSS dan interaksi layar.
- 92 regresi PG penerimaan/tab/stok/tiket/QC/jenis belum dikenal lulus di database uji terisolasi. Data pabrik/titipan, bobot sebelum/sesudah, payload tindakan lama, kepemilikan, tujuan, penolakan, idempotensi dan akses diuji melalui layanan lama.
- Browser nyata 320/390/768/1440/1920: seluruh tab, satu panel aktif, tanpa overflow; geometri tombol ponsel sejajar; keyboard, refresh dan hash lama tetap berfungsi. Delapan navigasi daftar–detail tanpa POST. Isian form PK tetap ada saat panel berganti; klik ganda satu POST dan tidak menawarkan penerimaan ulang.
- 170 tangkapan penuh, semua tab dari kelima jenis sebelum/sesudah dan pabrik/titipan, ditambah campuran, partai serta jenis belum dikenal. Rincian pada panel aktif dibuka sampai bawah; CSS pemotretan tidak masuk aplikasi.
- CI penuh dan deploy dicatat di laporan output setelah hasil akhir tersedia.

Perangkat fisik, Safari/Firefox dan pembaca layar belum diuji. Tidak menjalankan transaksi pada data operasional. Tidak ada migrasi.
