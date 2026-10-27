# Detail Stok: Minta lot terlihat di ponsel — v478

Tombol Minta lot sebelumnya berada dalam panel sticky yang terpisah dari
Perbaiki hasil giling dan QC. Dua panel menempati posisi bawah yang sama,
sehingga Minta lot tertutup di ponsel. Seluruh tindakan detail PK kini berada
dalam satu panel yang dapat membungkus tombol ke baris berikutnya.

Izin tetap mengikuti peran: Minta lot aktif bagi Super Admin dan operator
Gudang 2, dinonaktifkan bagi Admin dan operator Gudang 1. Kondisi lot,
status permintaan, dan pemeriksaan endpoint tetap berlaku.

Sumber paket tampilan: fcbf068. Sinkronisasi melalui scripts/sinkron.py;
manifest vendor selaras. Nomor aset naik ke 478 agar cache perangkat berubah.

Validasi sebelum rilis: 65 uji paket/visual dan 10 uji akses/vendor aplikasi
lulus. Uji visual memeriksa tombol tidak tertutup pada awal, tengah, dan
akhir gulir, lebar 320/390/540/1440 px, empat kombinasi peran, dan detail PK
Gudang 1/2. Uji regresi gagal pada templat lama karena Minta lot tertutup.

Tidak ada migrasi, perubahan API, atau transaksi bisnis pada pemeriksaan
visual. Sesudah deploy, respons detail lot produksi dibaca dengan empat
peran lalu dirender memakai aset rilis untuk screenshot dan pemeriksaan
posisi tombol. Pemeriksaan tidak menekan tombol simpan.

Rollback: revert commit rilis ini pada main dan deploy kembali bila detail
Stok gagal dirender, tombol tetap tertutup, atau health tidak sehat. Tidak
memerlukan pemulihan database.
