# Perintah barang keluar — rilis 363

- `/barang-keluar/baru` membuka halaman editor, bukan modal. Perubahan disimpan
  otomatis sebagai draf pribadi; daftar draf dapat dibuka dari Barang Keluar.
- Pelanggan dan barang boleh belum lengkap ketika menjadi draf. Nama barang,
  merek, kemasan, dan satuan tetap terlihat. Armada boleh menyusul.
- **Terbitkan perintah** memvalidasi ulang pelanggan, jumlah, kepemilikan, stok
  tersedia, reservasi, dan tiket; kemudian membuka detail perintah. Draf tidak
  masuk antrean atau mereservasi stok. Perintah tidak memotong stok aktual.
- Revisi dan kunci transaksi mencegah dua tab menimpa draf. Pengiriman ulang
  simpan/penerbitan tidak menggandakan perintah. Konflik mempertahankan isian
  dan memperlihatkan draf server sebagai pembanding. Token sesi menjaga
  identitas pembuka; perpindahan halaman memakai penjagaan isian belum disimpan.
- Setelah timbang kedua, callback Timbangan memverifikasi dan menutup pengiriman
  hanya jika muatan sudah dinyatakan selesai dan selisih berat barang **setelah
  tara** maksimal ±0,2% dari total muatan aktual (±20 kg per 10 ton; tanpa batas
  minimum 100 kg). Berat/tara harus lengkap dan sah. Di luar batas ditahan untuk
  pemeriksaan manual. Ambang pemeriksaan manual tidak berubah.
- Callback ulang aman dan audit menyebut verifikasi otomatis serta petugas.
  Muatan aktual dan stok tidak disesuaikan ke angka timbang.
- Seluruh kartu aktif membuka detail ketika diketuk; tombol pembuka tambahan
  dihapus. Tindakan pada perintah terbit tetap dilakukan dari detail.

## Migrasi dan pemulihan

`0102_draf_keluar` hanya menambah tabel draf; tidak memperbarui catatan atau
stok operasional. Tidak ada pemrosesan ulang pengiriman lama saat deploy.
Jika editor/penerbitan gagal setelah rilis, kembalikan aplikasi ke commit
sebelumnya dan pertahankan tabel draf untuk pemulihan; jangan menjatuhkan tabel
atau membatalkan pengiriman operasional. Rollback kode menghentikan pemakaian
editor baru tanpa menghapus draf tersimpan.

## Batas pemulihan

Draf tersimpan tersedia di server. Saat jaringan gagal, perubahan yang belum
tersimpan dipertahankan di tab dengan tombol coba lagi dan peringatan sebelum
meninggalkan halaman. Menutup paksa aplikasi sebelum status Tersimpan dapat
menghilangkan perubahan yang belum terkirim; tidak ada salinan lokal lintas akun.
Verifikasi otomatis bergantung pada callback timbang kedua. Jika callback gagal
karena jaringan, pengiriman tetap menunggu verifikasi dan dapat diperiksa manual;
tidak ada pekerjaan latar yang mengubah pengiriman lama.

## Hasil pengujian sebelum rilis

- Seluruh suite PostgreSQL: 996 lulus, database `uji_draf364` pada
  `127.0.0.1:55442`, 409,84 detik. Termasuk draf parsial, dua tab, pengiriman
  ulang, akun berganti, penerbitan tanpa armada, stok, kepemilikan, dan callback
  verifikasi bersamaan serta batas ±0,2%.
- Seluruh pemeriksaan Produksi di luar PostgreSQL: 736 lulus.
- Seluruh paket tampilan: 325 lulus. Setelah perapian terakhir, 12 uji editor
  dan tautan kartu diulang dan lulus (320/390/1440 px, terang/gelap).
- Dua pemeriksaan stok lama diselaraskan dengan penamaan variabel bobot pada
  kode terkini; rumus stok tidak diubah.
