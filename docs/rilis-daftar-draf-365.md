# Daftar dan penghapusan draf — versi 365

Daftar draf pribadi berada langsung di Barang Keluar, sebelum perintah terbit.
Pelanggan, jumlah item terisi, dan waktu perubahan ditampilkan. Ketuk kartu
untuk melanjutkan. Draf belum diterbitkan tidak masuk antrean atau reservasi.

Hapus draf meminta konfirmasi pelanggan dan jumlah item. Server memeriksa
pemilik, peran, serta revisi terkini di dalam kunci yang sama dengan simpan dan
penerbitan. Draf terbit tidak dapat dihapus. Ulangan permintaan hapus aman;
tab lama tidak dapat menyimpan atau menerbitkan draf yang sudah dihapus.
Kegagalan jaringan mempertahankan baris dengan tombol coba ulang.

Migrasi 0103 hanya menambah kolom dihapus_pada. Hapus bersifat lunak; tidak
menghapus isi draf, perintah, audit, ataupun stok. Deploy tidak menghapus draf
apa pun. Pemeriksaan aplikasi terbit hanya membaca daftar dan tampilan tombol.
Untuk rollback, pertahankan filter dihapus_pada di server; kode sebelum versi
365 mengabaikan tanda penghapusan dan dapat menawarkan draf tersebut lagi.

Pengujian lokal terisolasi: 131 uji PostgreSQL draf/barang keluar lulus, lalu
15 uji draf diulang dan lulus termasuk tambahan persaingan hapus/penerbitan;
736 pemeriksaan pendukung, 16 uji browser dua tema (320/390/1440 px), dan
4 penjaga sinkronisasi lulus. Enam uji daftar/hapus diulang setelah perapian
pesan kegagalan jaringan dan lulus. Seluruh data contoh ada di lingkungan uji.
