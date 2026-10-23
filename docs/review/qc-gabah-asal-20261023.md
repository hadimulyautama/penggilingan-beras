# QC gabah asal sampai lot PK — 23 Oktober 2026

## Lingkup dan inventaris sebelum perubahan

- QC gabah tersimpan pada PurchaseBatchQc dan PurchaseBatchQcSample: dua bacaan kadar air per pencatatan, lamur/jumlah sak (gabah basah), biji hijau, densiti, waktu dan pencatat. Header lama tanpa sampel tetap ada.
- Asal bahan proses aktif sudah ditelusuri lewat batch lot pengeringan dan MillingProcessSource; proses giling lama mempunyai penunjuk langsung batch/lot. Pemakaian silo tidak boleh diganti dengan isi silo saat ini.
- Pengeringan dan pendinginan: tabel Asal bahan gabah belum memuat rincian QC; laporan lama sudah membaca QC gabah.
- Penggilingan: tab Hasil & QC berisi QC PK (enam komponen), bukan QC gabah asal. Kedua pencatatan harus tetap berbeda.
- Stok lot PK G1 berasal dari MillingProcess; lot transfer G2 melalui intake → InternalTransfer → MillingProcess. PK beli luar tidak selalu mempunyai keterkaitan batch gabah.
- Semua formulir, tindakan, skor/rendemen, penutupan, stok, laporan PDF dan gerbang akses sudah ada. Perubahan ini hanya memperluas informasi baca pada halaman yang telah diotorisasi.

## Pemetaan baru

| Tahap | Lokasi rincian QC gabah asal | Hubungan sumber |
|---|---|---|
| Pengeringan | Tab Bahan, sesudah daftar batch | DryingLotBatch |
| Pendinginan, sudah dingin, sudah di silo | Tab Bahan, sesudah daftar batch | Lot yang sama, termasuk melalui URL riwayat |
| Giling aktif/jeda | Tab Bahan & silo | Batch sumber MillingProcessSource / sumber proses lama |
| Riwayat giling selesai | Kartu QC gabah asal, sebelum tautan laporan | Sumber proses giling yang tersimpan |
| Lot PK G1 | Kartu QC gabah asal pada detail stok | Kode proses giling |
| Lot PK transfer G2 | Kartu QC gabah asal pada detail stok | Intake → transfer → proses giling |

Satu kartu per batch, seluruh catatan sampel tetap tersedia. Pemakaian sumber berulang tidak menggandakan kartu. Tidak ada rata-rata antarbatch, penilaian baru, salinan QC, penulisan stok, perubahan validasi, atau endpoint tindakan baru. Nilai yang tidak diketahui tetap berupa keterangan, bukan nol. Lamur untuk gabah kering diberi keterangan tidak berlaku. QC warisan tanpa sampel diberi label data lama; angka sampel tidak direka.

Sakelar fitur Mutu & QC tetap dipatuhi. Pengguna mengikuti izin halaman asal, termasuk operator G2 yang memang sudah berhak membaca mutu PK transfer, tetapi tidak memperoleh akses riwayat proses G1. Label identitas dryer yang kosong menjadi “Mode dryer belum tercatat”.

## Berkas

- app/services/qc_gabah_asal.py: pembaca data asli serta hubungan PK asal.
- app/services/proses_aktif.py: metadata QC pada bagian batch dan label mode dryer.
- app/web/layar_riwayat.py dan layar_stok.py: memasok informasi setelah pemeriksaan akses lama.
- app/web/templates/_qc_gabah_asal.html: komponen rincian baca, native details untuk keyboard.
- _detail_pengeringan_bagian.html, _detail_giling_bagian.html dan riwayat_detail.html: penempatan komponen.
- stok_pk_dengan_qc_asal.html: memperluas template stok lama; rincian QC dipindah ke grid setelah daftar batch melalui skrip lokal sekali-render, tanpa pendengar global. Tanpa JavaScript, kartu tetap terbaca di bawah rincian stok. Tidak menyunting paket vendored.
- tests/pg/test_qc_gabah_asal.py: lima skenario integrasi baru.
- Tiga assertion tes navigasi lama diperbarui mengikuti perubahan main 894b463 dan f22c150 (tab Pekerjaan bersama, penghapusan tombol kembali berulang, dan pemindahan penyaring gudang ke helper yang dipakai bersama). Tidak ada perubahan implementasi navigasi pada pekerjaan ini.

## Pemeriksaan

- Lima skenario baru: tiga peran menempuh pengeringan → pendinginan → dingin → silo → giling → lot PK; dua skenario tambahan untuk transfer G2, gabah kering, header lama, fitur mati dan sumber berulang.
- Catatan QC1 24%/25%, QC2 26%/27% tetap tampil per pencatatan; bukan angka pengeringan 16% atau indikator mesin18%.
- Perbandingan sebelum/sesudah GET menguji jumlah catatan QC, kadar air batch, bobot batch, seluruh hasil kumulatif dan identitas/status sumber silo tetap sama.
- Alur giling selesai memakai layanan lama dan hasil akhir6400kg; stok membaca hasil tersebut. Tidak ada QC hasil giling palsu dari QC gabah.
- Gabah kering13,25%/14,75% tetap terbaca setelah transfer; lamur tidak dipaksakan. Header lama tanpa sampel menampilkan belum tercatat. PK luar tanpa asal menampilkan keterbatasan sumber.
- Akses operator G1/Admin/Super Admin diuji; operator G2 tetap ditolak403 dari riwayat pengeringan/giling G1, dan tetap boleh membaca QC asal pada PK transfer yang diizinkan.
- Browser Chromium hidup:15 kombinasi tiga halaman × lima lebar320/390/768/1440/1920; klik berulang dan keyboard Space rincian QC, tanpa overflow atau galat JavaScript.
- Tangkapan penuh46 gambar dari respons asli setiap fase fixture yang disimpan saat alur berjalan. Arsip respons dirender dengan aset aplikasi lokal, seluruh rincian dibuka; permintaan API latar diblokir khusus proses potret karena fixture berpindah fase. Uji interaksi terpisah memakai aplikasi hidup dan sesi fixture lokal. Tidak ada perubahan CSS capture atau pemblokiran API di aplikasi produksi.
- Semua pengujian basis data memakai PostgreSQL loopback dengan nama uji_; tidak mengubah data operasional.

## Batas verifikasi

Perangkat Android/iOS fisik, Safari/Firefox, pembaca layar dan seluruh variasi data operasional belum diuji. Asal batch yang tidak tersimpan tidak direkonstruksi dengan perkiraan; tampil belum dapat ditelusuri. Laporan asli tidak diubah. Tidak ada migrasi atau konfigurasi fitur yang diubah.

Hasil akhir suite, CI, merge/deploy, log dan galeri lengkap tersedia pada laporan output/qc-gabah-asal/laporan-pemeriksaan.md.
