# Kontrol Pengiriman bersama

Barang Keluar dan Barang Retur menggunakan makro `kontrol_pengiriman` dalam `hmu_tampilan/templates/_pengiriman_kontrol.html`, kelas `.pengiriman-kontrol`, serta aset `pengiriman-kontrol.css` dan `pengiriman-kontrol.js`. Jangan membuat salinan header, bentuk tab, menu ponsel, atau tombol Panduan/Print per tab.

Pemanggil menyediakan empat slot: `tindakan`, `alat`, `cakupan`, dan `panel`. Tombol, izin, filter, dan isi Panduan tetap sesuai alur halaman. `filter=true` hanya digunakan halaman yang mendukung filter; tanpa filter, tab tetap memakai bentuk dan posisi yang sama. Panduan memakai makro `.pd-panduan` bersama.

Data, tabel, detail, paginasi dan layanan transaksi tidak menjadi bagian dari kontrol. Barang Retur mempertahankan pengajuan, tiket, data lama belum terhubung, pemeriksaan, bobot, selisih, riwayat, pesan, dan tautan ke pengiriman asal.
