# Fondasi Console website dan Pengaturan perusahaan sendiri

Keputusan pemilik 13 November 2026: sementara Console Center berada pada
website, akses Super Admin. Pengelolaan lintas perusahaan berada di Console;
Pengaturan harian hanya untuk perusahaan sendiri setelah konteks tenant siap.
Website tetap tidak terhubung langsung ke database. API administrasi dipisahkan
menurut tujuan sesi, bukan memakai hak admin konten website atau token operator.

## Identitas dan batas layanan

`RuangAdministrasi(user_id, company_id=None)` hanya dibuat gerbang Console dari
sesi Super Admin yang diverifikasi ulang setiap permintaan. Layanan memeriksa
lagi Super Admin aktual, status orang dan perusahaan. Tidak ada fallback Admin
saat belum ada Super Admin. Pintu belum aktif tanpa callback website HTTPS sah.

`RuangAdministrasi(user_id, company_id=...)` disediakan untuk Pengaturan
perusahaan sendiri. Layanan menolak perusahaan lain, anggota nonaktif dan
anggota selain Admin. Hak baru dan hak lama sasaran harus berada dalam cakupan
lokasi/gudang yang dikelola pelaku; tidak boleh mengangkat peran platform.
Admin perusahaan terakhir tidak boleh mencabut dirinya dari Pengaturan. Console
menjadi jalur pemulihan. Keanggotaan baru sementara ditambahkan oleh Console;
undangan dan pembuktian kepemilikan akun belum diaktifkan.

Objek ruang bukan token autentikasi. Jangan menerima user_id/mode dari badan
permintaan. Peran/status perusahaan tidak disalin ke User.role/status atau
ProduksiAkun, sehingga perubahan satu perusahaan tidak mencabut akses di
perusahaan lain maupun sesi operator lama.

## Model akses

Keanggotaan → akses lokasi → semua gudang eksplisit ATAU gudang terpilih.
FK gabungan memastikan anggota, lokasi, penempatan gudang dan perusahaan sama.
Tidak ada fallback berdasarkan nama g1/g2, gudang bawaan atau perusahaan pertama.
`konteks_kerja` bersama membaca aturan ini, tanpa autoflush dan tanpa menulis.
Belum ada gerbang transaksi harian yang memakai konteks tenant baru.

Writer mengunci perusahaan agar penambahan/perubahan bersamaan terserialisasi,
memvalidasi setiap relasi, memeriksa sidik formulir, lalu menyimpan anggota,
izin serta audit dalam satu transaksi. No-op/pengiriman ulang tidak menambah
audit. Pembacaan daftar dibatch, dibatasi 200, serta dapat dicari. Audit
berhalaman 50; sebelum/sesudah lengkap tetap tersedia. Jejak metadata tidak
menggeser kandidat undo operator.

## Sesi Console

PadiFlow menerbitkan kode sekali pakai dua menit dengan PKCE dari sesi Super
Admin. Website memeriksa state, menukar kode lewat backchannel, kemudian
menyimpan cookie Console bertanda yang terpisah dari CMS. Token acak sesi
hanya disimpan sebagai hash pada `hmu_console_sessions`, berlaku satu jam.
Setiap API memeriksa akun, orang, token_version, wajib ganti sandi dan peran
terbaru. Logout hanya mencabut sesi Console. Semua respons API bersifat
private/no-store. Website tidak diberi nilai DATABASE_URL atau kunci sesi pabrik.

## Migrasi dan batas rilis

0130 (PadiFlow sebagai runner metadata bersama) hanya menambah tabel izin,
sesi Console, serta unique/FK metadata. Tidak ada backfill anggota/izin atau
perubahan data transaksi. Downgrade menolak data terisi; rollback kode tidak
menghapus identitas, izin maupun audit. TeraFlow hanya menerima paket bersama,
tidak menjalankan DDL duplikat. Website tidak mempunyai runner migrasi pabrik.

Aktivasi tenant pada sesi, gudang kerja, master barang/kontak, stok, transaksi,
portal, cache, tugas latar dan antrean luring tetap tahap terpisah. Konfigurasi
perusahaan kedua belum mengklaim isolasi transaksi lama. Alur operator tetap
memakai gerbang yang telah berjalan sampai tahap aktivasi teruji tersendiri.
