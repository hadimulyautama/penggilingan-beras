# Daftar Barang Keluar dan bantuan alur

Baseline ba6100f. Cakupan hanya template daftar, CSS dan JS khusus panduan; tidak mengubah layanan, endpoint, model, rumus, formulir transaksi atau paket vendor.

## Berkas

pengiriman.html; _pengiriman_pembuka_interaktif.html; _pengiriman_bantuan.html; daftar_pengiriman.css; bantuan_pengiriman.js; test_daftar_pengiriman_rapi.py; dokumen ini.

## Pemetaan informasi dan tindakan

| Sebelumnya | Penyajian baru |
|---|---|
| Judul dan jumlah menunggu pengeluaran/verifikasi | Kepala Barang Keluar dan dua kartu angka dari n_perintah/n_dimuat yang sama |
| Tab Barang Keluar/Barang Retur | Navigasi modul lama, tepat di bawah kepala |
| Buat perintah dan Pengambilan barang jasa | Tindakan primer/sekunder dengan BOLEH_PERINTAH dan alamat lama |
| Bantuan berupa paragraf | Panduan tiga tahap Perintah–Muat–Verifikasi; hanya memilih penjelasan, tidak mengubah status |
| Penjelasan alur cepat | Rincian lipat Di bawah 200 kg, tanpa menambahkan langkah atau aturan |
| Pencarian q, status, sejak | Form GET lama dalam kartu lipat; otomatis terbuka jika filter terisi |
| Draf pribadi | Komponen asli hanya dirender jika ada; setelah hapus terakhir berhasil, indikator kosong asli menyembunyikan kartu |
| Pengiriman aktif | Tabel/kartu asli, dengan judul dan kondisi kosong yang jelas |
| Riwayat | Tabel/kartu asli, semua kolom, tautan tiket/detail dan cursor/filter pagination tetap sama |
| Form transaksi, dialog, CSRF dan sesi | Komponen dan skrip lama, tidak diubah |

Panduan memiliki tab ARIA, panah kiri/kanan, Home/End, fokus, serta satu panel aktif. Tautan bantu mengarah ke formulir/GET filter lama; pembuatan perintah hanya muncul dengan izin yang sama. Tahap Muat menjelaskan tugas operator, tidak menawarkan formulir muat Admin. Skrip memasang handler pada root sekali. CSS hanya berlaku pada daftar, menggunakan tema aplikasi. Detail Pengiriman & Retur tetap memakai layout sebelumnya.

## Pemeriksaan bantuan alur lainnya

- Bantuan pengiriman aktif sudah diganti komponen baru ini. Salinan vendor tidak diedit.
- Bantuan alur retur aktif di retur_daftar.html masih berupa teks; isinya merupakan orientasi singkat, bukan tombol transaksi. Rincian otomatis/manual/tara tetap di pengajuan dan layanan lama. Tidak menambah interaksi atau mengubah retur dalam pekerjaan ini.
- Macro Panduan kerja di _operasional.html dan pemanggil pada berjalan.html, keputusan.html, mutu.html serta template barang_keluar.html merupakan penyajian lama. Jalur berjalan/keputusan/mutu saat ini diarahkan ke Pekerjaan; daftar pengiriman menggunakan pengiriman.html. Template retur.html lama tidak dipakai renderer aktif yang menggunakan retur_daftar.html.
- Penanda tahap pengeringan/pendinginan/transfer PK adalah informasi status; tetap tidak dijadikan tombol perubahan status.
- Teks pengaturan gudang yang menyebut alur produksi bukan komponen bantuan langkah kerja.

## Bukti yang tersedia sebelum merge

- 139 regresi PostgreSQL terarah lulus: barang keluar, draf, detail Pengiriman & Retur, dan dua kasus daftar baru. Pengujian asli menjaga stok saat muat, verifikasi tanpa pengurangan ulang, pembatalan/pembalikan, muatan bersamaan, jasa, tiket, selisih, pagination, hak operator, CSRF, sesi dan idempotensi draf.
- Dua tes baru: daftar kosong tidak merender draf; panduan/filter tetap berizin; daftar terisi mempertahankan tautan edit/hapus/detail; filter tidak mengubah stok 10.000 kg dan tidak mengubah transaksi.
- Browser nyata pada 320/390/768/1440/1920: tiga tahap, satu panel, keyboard, lipatan dan tanpa overflow. Hapus draf dengan revisi lama gagal dan mempertahankan baris/galat; revisi benar menghapus terakhir, menyembunyikan kartu; refresh tidak merender draf. Tepat dua POST untuk dua percobaan, bukan untuk memilih tahap.
- 14 tangkapan penuh desktop/ponsel dari HTML asli respons aplikasi dengan data uji: kosong, terisi, filter, Muat, Verifikasi, operator, dan riwayat terisi. Rincian bantuan/filter dibuka sampai bawah; CSS pemotretan tidak masuk aplikasi.
- 800 tes non-PG lulus; penjaga 34 tes antrean/kelas CSS lulus kembali setelah template final. Delapan navigasi instan melalui tautan panduan dan pencarian GET lulus tanpa POST atau galat. Suite PG penuh, CI dan deployment final dicatat di laporan output setelah selesai.

## Batas dan rollback

Database PostgreSQL uji lokal terpisah; tidak menjalankan transaksi operasional. Belum menguji perangkat fisik, Safari/Firefox atau pembaca layar. Pemeriksaan produksi hanya health, halaman masuk, status deploy dan kecocokan aset. Tidak ada migrasi. Jika daftar gagal dimuat atau akses/alur berubah, revert commit penataan melalui commit baru dan deploy ulang; data transaksi tidak perlu diubah.
