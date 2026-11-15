# Aktivasi produk dan akses perusahaan

Console → Perusahaan → Produk & integrasi mengatur PadiFlow dan TeraFlow secara terpisah. Integrasi hanya dapat diaktifkan jika kedua produk aktif. Hak produk pengguna dikelola dari keanggotaan perusahaan → Hak produk, dengan peran Operator atau Admin untuk masing-masing produk. Semua perubahan membutuhkan pratinjau, alasan dan konfirmasi; penyimpanan menghasilkan audit sebelum/sesudah.

Menonaktifkan produk menolak login dan sesi yang sudah terbuka pada permintaan berikutnya. Izin pengguna tetap tersimpan untuk dipulihkan setelah aktivasi. Akun Admin Sistem tetap dapat masuk langsung ke Console untuk memulihkan konfigurasi, sekalipun PadiFlow dinonaktifkan. Peran platform tidak dapat diberikan melalui formulir hak produk.

Migrasi 0133 hanya menambah tiga tabel metadata. Perusahaan lama yang cocok pada kedua penetapan `organisasi_perusahaan_lama` dan `ruang_data_perusahaan` menerima kedua produk dan integrasi dengan kompatibilitas akses lama. Override pengguna yang nonaktif selalu menolak akses. Perusahaan baru tidak mendapat aktivasi atau akses implisit. Hak lokasi/gudang tetap mengikuti fondasi keanggotaan yang tersedia; produk bukan pemilih koneksi atau penyedia ruang operasional baru.

Tidak ada penulisan ulang stok, tiket timbang, proses, alokasi, pengiriman, atau transaksi historis. Pembaca transaksi lama tetap dipertahankan. Ruang operasional terpisah tetap harus disediakan dan diikat melalui konfigurasi server; aktivasi produk di registry tidak mencampurkan data perusahaan lain ke ruang HMU.

## Verifikasi dan urutan rilis

Jalankan workflow uji PadiFlow dengan `cakupan=semua`, workflow TeraFlow dengan revisi PadiFlow pasangan, dan Console Center Chromium/WebKit. Migrasi PadiFlow harus terpasang sebelum gerbang TeraFlow yang membaca tabel baru, kemudian antarmuka Console. Jangan menonaktifkan produk selama rollout parsial.

Pengujian khusus: `tests/pg/test_console_produk.py` meliputi empat kombinasi produk, izin berbeda, pencabutan sesi, API langsung, bukti pratinjau kadaluarsa, Console tetap terbuka, isolasi perusahaan, migrasi perusahaan warisan dan fingerprint transaksi. TeraFlow `tests/pg/test_produk_terpisah.py` meliputi sesi lama, peran master tidak berubah dan integrasi opsional. Website `tests/test_console_products.py` memeriksa pratinjau tanpa tulis, CSRF, draft dan layar 320/390/1440 dua bahasa.

Jika perlu rollback kode, pertahankan metadata dan audit; downgrade migrasi menolak menghapus metadata produk yang sudah digunakan. Jangan menghapus atau mengembalikan transaksi bisnis sebagai bagian rilis akses produk.
