# Audit kontrol ponsel empat peran — v479

Audit membaca halaman produksi v478 sebagai Super Admin, Admin, operator
Gudang 1 dan Gudang 2. Sumber halaman: commit 99879c5. Asetnya identik
dengan paket fcbf068. Operator G2 memakai pilihan gudang pada sesi operator;
profil akun tidak diubah. SQL tulis diblokir saat pengambilan snapshot.

Tiga masalah diperbaiki:

- Track grid rincian Pengaturan mengikuti lebar minimum tabel akses sehingga
  kontrol Rincian akses melebar hingga 620 px pada ponsel 320/390 px. Track
  kini minmax(0,1fr), sehingga tabel bergulir di dalam wadahnya sendiri.
- URL aksi tanpa izin tertahan oleh pemeriksaan izin, tetapi pesan memakai
  format keberhasilan “Tersimpan”. Pesan kini memakai format penolakan dan
  menyebut alasan akses. Pemeriksaan izin dan endpoint tidak diubah.
- API pratinjau unit Minta lot belum menerima Super Admin, sehingga formulir
  yang sudah terbuka bisa diarahkan ke halaman masuk saat pratinjau dimuat.
  Izin pratinjau kini mengikuti aksi Minta lot: Super Admin/operator G2;
  Admin dan operator G1 tetap ditolak. Tidak menyetujui atau memindahkan stok.

Paket tampilan sumber f3fd6b4, disinkronkan melalui scripts/sinkron.py.
Nomor aset 479 mematahkan cache perangkat.

Validasi sebelum rilis:

- 82 uji paket/visual dan 14 uji akses/vendor aplikasi lulus.
- Uji lama gagal saat kontrol Rincian akses melebar 620 px pada layar 320 px.
- 736 snapshot URL/peran, 75 spesifikasi aksi untuk tiap peran, 320/390 px:
  2.072 tampilan, termasuk formulir dan penolakan URL aksi.
- 48.808 pemeriksaan posisi kontrol, pada keadaan awal dan rincian dibuka:
  tidak ditemukan kontrol tertutup, melewati lebar layar, atau galat JS.
- 157 kombinasi URL/peran ditolak server dengan HTTP 403; tidak ada tautan
  aksi aktif yang bertentangan dengan izin katalog.
- Tidak ada kiriman bisnis oleh browser audit; proses Minta lot v478 tetap
  dijaga oleh uji regresi pada layar 320 sampai 1440 px.

Batas cakupan: snapshot memakai data yang tersedia. Alias pengalihan,
halaman pelanggan terpisah, isi PDF, dan keadaan transaksi yang belum ada
contoh datanya dicatat terpisah dalam laporan audit. Pratinjau tanpa pilihan
sumber tidak dianggap sebagai pemeriksaan transaksi dengan isian lengkap.
Kanal pembaruan langsung dijeda pada replay agar snapshot stabil.

Tidak ada migrasi, perubahan skema, penambahan izin, atau transaksi uji.
Rollback: revert commit rilis ini lalu redeploy bila kontrol rincian tetap
melebar, penolakan izin tidak bekerja, atau health aplikasi tidak sehat.
