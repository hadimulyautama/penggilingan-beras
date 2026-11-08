# Pengemasan hasil samping dan kiriman silo

Aturan operasional final: pengemasan awal broken, menir, reject, dan bekatul
seluruhnya otomatis. Aturan ini menggantikan penawaran packing manual lama.
Operator tetap mencatat hasil produksi, bukan pengemasan awal hasil samping.

## Jalur yang ditutup

- Sumber `Catat packing` (`beras-belum-dikemas`), termasuk query lama
  `hanya_beras=false`, hanya memuat hasil beras.
- `kemasan-untuk` dan katalog borang lama `produk-kemasan` tidak menawarkan
  hasil samping. Tombol packing baru dari detail Stok hanya berlaku untuk beras.
  Pekerjaan dan detail proses memakai sumber beras yang sama.
- `/api/actions/catat-packing` menolak hasil samping pada payload `sumber` maupun
  payload lama `kode_pol` + `produk`, dengan pesan bahwa pengemasannya otomatis.
- Layanan `finished_goods.catat_packing`, pembaca saldo manual dan pratinjau
  memeriksa aturan yang sama sebelum menulis atau membuat SKU.
- `hasil_samping_bisa_dikemas`, cabang saldo manual hasil samping, parameter
  `hanya_beras`, serta cabang tampilan pengemasan nonberas telah dihapus setelah
  pemanggil aplikasi dan tes diperiksa.

## Mekanisme yang dipertahankan

Rumus stok dan aturan kemasan otomatis tidak berubah: broken/menir/reject
50 kg, bekatul 40 kg; karung penuh dibulatkan ke bawah dan sisanya curah.
Hitungan mengikuti hasil, kepemilikan, alokasi/pengiriman, dan pemindahan silo
yang sudah berlaku. Perubahan hasil langsung dibaca sebagai saldo terbaru.
Tidak ada transaksi pengganti, perhitungan ulang massal, penghapusan historis,
atau migrasi skema dalam perubahan ini.

Pengemasan manual beras, Kemas ulang, master SKU dan ukuran kemasan, penerimaan
barang beli luar dari tiket timbang, retur, serta pembaca transaksi historis
(stok, audit, laporan, dan dokumen) tetap digunakan. `_packed_kg`,
`_bekatul_dibukukan`, `_broken_dibukukan`, dan `kombinasi_kemasan` tetap diperlukan
oleh jalur-jalur tersebut. Fixture tes `packing_historis` membuat data lama
secara eksplisit; fixture itu bukan layanan aplikasi atau jalan pintas API.

## Kontrak kiriman hasil samping ke silo

POST `masukkan-broken-silo`, `masukkan-menir-silo`, `masukkan-reject-silo`, dan
endpoint lama `pindah-broken-silo` membutuhkan `kunci_kiriman` acak sepanjang
16–80 karakter (huruf, angka, `_`, `-`). Pengintegrasi membuat satu kunci per
operasi dan mempertahankannya saat mengulang operasi yang sama. Payload tanpa
kunci ditolak sebelum mutasi; buka formulir baru jika masih memakai formulir
lama. Kunci tidak boleh dibuat ulang hanya karena respons terputus.

Server mengikat kunci dengan aksi, isian, dan petugas. Kunci dan isian identik
mengembalikan hasil asli, termasuk ketika sumber sudah habis. Pemakaian kunci
untuk jumlah, sumber, silo, pemilik, aksi, atau petugas lain ditolak. Hak akses
sesi/gudang tetap diperiksa pada setiap permintaan, termasuk replay.

Kunci saldo, mutasi stok, pembongkaran karung, penambahan bahan proses, audit,
dan tanda terima tersimpan atomik. Tanda terima di `peristiwa` hanya bukti
kiriman; tidak menulis proyeksi stok kedua dan tidak memutar ulang mutasi saat
proyeksi dibangun kembali. Tidak ada transaksi lama yang dimodifikasi.

Formulir yang menerima kapabilitas `kiriman_silo_idempoten` membawa kunci ini.
Jika jawaban jaringan hilang, isian tetap utuh dan dibekukan; tombol **Coba
kiriman yang sama** mengulang payload serta kunci asli. Formulir tidak melakukan
POST ulang otomatis. Pergantian sesi tetap menghentikan pengiriman ulang.

## Verifikasi

Tes mencakup endpoint dan layanan manual baru/lama, saldo ganjil, koreksi hasil,
kemasan historis, pemilik, pengiriman/silo, izin, Kemas ulang, replay setelah
stok habis, kunci berbeda/petugas berbeda, balapan, dan rollback audit/tanda
terima. Tes browser memutus respons setelah server commit dan membuktikan
kiriman ulang tidak menggandakan stok. Seluruh data tes berada di database lokal
berawalan `uji_`; tidak memakai transaksi produksi.

Uji browser memakai browser lokal pada ukuran ponsel/desktop. Pengamatan pada
ponsel fisik dan printer, CI GitHub lengkap, serta fitur undo hasil samping ke
silo secara menyeluruh tetap merupakan verifikasi/pekerjaan terpisah.
