# Katalog Pekerjaan v404

Akses Catat pekerjaan lain pindah dari sidebar ke kepala Pekerjaan. Katalog menjadi halaman turunan `/pekerjaan/catat-lain`; navigasi kembali membawa tab, jenis, pencarian, gudang, kepemilikan dan pelanggan. Pekerjaan tetap dua tab dan hitungannya tidak mencakup katalog.

## Pemetaan

| ID | Lokasi akhir |
|---|---|
| beli_kemasan | Katalog → Stok & kemasan |
| transfer_pk | Katalog → Pemindahan bahan |
| rekonsiliasi_timbang | Katalog → Pencocokan data |
| auto_taut_keluar | Katalog → Pencocokan data |
| masukkan_beras_silo | Stok → detail produk sesuai izin lama |
| tutup_jasa | Detail Pesanan Jasa |
| batalkan_jasa | Detail Pesanan Jasa |
| undo | Pintasan operator G1/G2 |
| catat_packing, catat_bekatul | Pintasan operator G2 dan kartu terkait |
| QC dan tindakan proses lain | Kartu/halaman asal yang sudah ada |

Tiga duplikat hanya ditandai `kartu`; spesifikasi, picker, endpoint dan pemeriksaan izin tetap dikirim bagi peran sah. Fungsi bisnis tidak dihapus. Petunjuk Beli karung diperbaiki agar tidak lagi menyebut harga; isian harga tidak ditambahkan.

URL `/aksi-lain` beserta `buka`, `nilai` dan parameter sumber tetap ditangani. Pesanan diverifikasi sebelum dialihkan ke pelanggan pemiliknya. Stok titipan hanya dipetakan bila nomor pesanan dapat diverifikasi. Konteks tidak lengkap menampilkan petunjuk dan tautan ke halaman asal. Operator tetap melalui gerbang lama; kueri dipertahankan. Tujuan kembali dibatasi ke Pekerjaan.

Sumber tampilan berubah di repo Tampilan, versi 404, lalu disinkronkan dengan skrip resminya. Salinan vendored tidak diedit langsung. Tidak ada kode JS formulir, transaksi stok, migrasi, model atau perhitungan PK dalam commit ini.

## Pemisahan perubahan PK

Checkout lokal juga berisi pekerjaan PK yang terpisah, termasuk tindakan `sesuaikan_stok_pk_lama`. Seluruh implementasi, pengelompokan, migrasi, perubahan model dan perbaikan JOIN milik pekerjaan tersebut tetap di luar commit katalog. Katalog tetap merender tindakan sah lain secara generik bila fitur itu kemudian diterbitkan.

## Verifikasi

Snapshot isi commit diuji terpisah dari perubahan PK lokal. Suite HTTP katalog memeriksa dua tab, konteks kembali, empat tindakan katalog, spesifikasi duplikat, deep link pabrik/titipan/jasa, konteks kosong, peran dan gudang efektif. Pembelian karung benar-benar menambah stok pabrik 13 lembar; CSRF dan jumlah nol diuji. Audit master lengkap memeriksa HTTP Pekerjaan.

Semua transaksi pengujian menggunakan PostgreSQL sementara dengan database berawalan `uji_` pada loopback. Tidak mengubah data operasional. Tangkapan dan hasil pengujian checkout gabungan sebelumnya tetap tersedia secara lokal; tidak disertakan karena memuat fitur PK terpisah.

Hasil snapshot index tanpa perubahan PK: **772 uji non-PostgreSQL lulus**, **225 uji PostgreSQL lulus**. `git diff --cached --check` lulus. Paket Tampilan sebelumnya lulus 398 pengujian dan manifest sumber/vendor tetap selaras.
