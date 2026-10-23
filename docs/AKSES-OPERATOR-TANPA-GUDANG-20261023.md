# Pembatasan Operator tanpa gudang — 23 Oktober 2026

## Masalah dan perbaikan

Audit produksi pada rilis `6e2fb37` menemukan tiga Operator tanpa gudang dapat membaca tiga riwayat Pengiriman dan membuka detail melalui URL langsung. Profil tersebut juga menerima Kabar Operator tanpa saringan gudang, sementara ringkasan G1/G2 menolaknya.

- **Pengiriman:** pemeriksaan negatif yang hanya menolak view G1 diganti izin positif: Admin ke atas atau Operator dengan gudang kerja G2 yang aktif. Berlaku pada daftar, filter, alias pembuka perintah, dan detail. Penolakan menyarankan memilih gudang kerja. Formulir baru/perintah dan retur tetap memakai izin lamanya.
- **Kabar:** gudang kerja yang tidak diketahui/tidak aktif kini menghasilkan cakupan kosong eksplisit (`P.TANPA`), bukan `None` yang berarti semua gudang. Saringan bersama dipakai daftar, jenis, histori, badge, akses satu kabar, buka catatan dan penandaan pribadi. Daftar kosong dan badge nol berlaku sampai gudang yang sah dipilih; akses ke ID kabar di luar cakupan ditolak 404. Penandaan semua tanpa cakupan tidak mengubah baris apa pun.

Alur `/lihat-sebagai` untuk pilihan gudang tidak diubah. Pilihan G1/G2 tetap berlaku per permintaan tanpa menulis ulang peran atau gudang bawaan. Setelah memilih gudang, Kabar khusus gudang dan Kabar lintas gudang mengikuti aturan yang sama seperti sebelumnya; Pengiriman hanya tersedia di G2 atau untuk Admin ke atas. Kembali ke gudang bawaan yang kosong menutup akses kembali. Admin/Super Admin tetap boleh tanpa gudang bawaan.

Tidak mengubah logika transaksi, pemicu/penerima notifikasi, status historis, stok, formulir, pekerja retur, atau aturan verifikasinya. Tidak ada migrasi/konfigurasi baru. Tidak ada perubahan komponen bersama, sehingga paket tampilan tetap versi 403 tanpa sinkronisasi tambahan.

## Regresi

Regresi baru `tests/pg/test_operator_tanpa_gudang.py`: **12 kasus lulus** di PostgreSQL lokal terisolasi. Mencakup:

- Lima profil nyata di database uji: Operator tanpa gudang, G1, G2, Admin dan Super Admin; URL daftar/detail/filter dan izin retur.
- Daftar/jenis/badge/histori Kabar serta akses ID/cursor dan penandaan baca ditutup tanpa gudang; parameter URL `gudang=g2` tidak memberi izin.
- Memilih G1 → G2 → G1 → gudang bawaan melalui endpoint formulir resmi dengan CSRF; izin dan badge mengikuti pilihan. Profil, stok, transaksi asal dan status baca tidak berubah hanya karena memilih gudang/membuka daftar.
- Gudang G1/G2 nonaktif tidak memberi akses.
- Status baca tersimpan setelah kembali memilih gudang, dan pengguna lain tidak terpengaruh.
- Kabar lintas gudang tetap tersedia pada kedua gudang yang sah; penerima Admin/Super Admin tetap sesuai aturan lama.

Regresi penuh: **2.004 lulus** (579,27 detik). Putaran pertama menemukan satu fixture lama yang menyebut Operator G1 tanpa membuat master gudangnya; fixture diperbaiki agar memakai gudang aktif yang nyata, kemudian seluruh suite dijalankan ulang dan lulus. Unit terpisah serta 12 kasus baru juga lulus. `git diff --check` bersih. Pengujian transaksi hanya dilakukan di database loopback berawalan `uji_`.

## Rilis dan verifikasi produksi

Rilis hanya boleh diteruskan bila regresi lulus. Push ke `origin/main` memicu deployment Railway. Sesudah deployment, ulangi audit GET terbatas untuk sembilan akun yang sama tanpa cookie pilihan gudang/peran dan tanpa mengirim tindakan. Periksa penolakan daftar/detail Pengiriman dan Kabar/badge nol untuk tiga Operator tanpa gudang; hak akun lain tetap sama.

Operator G2 nyata dengan gudang bawaan belum tersedia pada audit sebelumnya. Alur pilihan G2 dibuktikan di lingkungan terisolasi; tidak mengubah profil/kerja akun operasional untuk mengisi matriks produksi.

Pemulihan: bila regresi produksi terdeteksi, utamakan perbaikan lanjutan yang tetap menutup celah ini. Mengembalikan dua pembaca ke rilis sebelumnya akan membuka kembali celah akses, sehingga bukan langkah pemulihan yang aman. Tidak perlu rollback skema.
