# Portal pelanggan

Portal terintegrasi di `/pelanggan`, dengan login `/pelanggan/masuk`.
Desktop dan ponsel memakai URL yang sama. Sidebar ponsel dibuka melalui Menu.
Tema memakai cookie `produksi_terik` serta aset dan token warna produksi.

## Identitas dan batas data

- Kredensial tersimpan di `portal_accounts`, terpisah dari akun staf.
- Cookie `pelanggan_sesi` memakai kunci turunan HMAC khusus; token tidak dapat
  digunakan sebagai sesi operator/admin meskipun cookie diganti namanya.
- ID pelanggan selalu berasal dari akun aktif pada sesi. ID pelanggan lain
  pada URL ditolak, termasuk detail, sumber proses, QC, stok dan PDF.
- Daftar riwayat/QC/retur disaring sebelum batas/paginasi. Sumber lintas pemilik
  yang tidak konsisten ditolak; pengosongan silo membatasi periode asal bahan.
- Router hanya mengizinkan daftar tetap fungsi baca produksi. Tidak ada
  penerusan bebas ke URL/API staf. POST terbatas ke login, logout, dan status
  baca notifikasi pribadi; seluruhnya dilindungi CSRF.
- HTML/PDF bersifat privat dan tidak disimpan cache. Portal tidak mendaftarkan
  service worker atau menyimpan data pelanggan untuk akses luring.

## Komponen dan laporan bersama

`app/web/portal/routes.py` mengotorisasi akses sebelum memanggil pembaca
produksi. Detail memakai templat produksi melalui Jinja overlay per request,
sehingga lingkungan templat staf tidak diubah. Adapter presentasi membuang
kontrol transaksi, mempertahankan filter GET, disclosure, tabel, tautan baca,
rincian retur dan fungsi PDF. Progres dan neraca memakai komponen produksi.

Pengeringan memakai `layar_riwayat.laporan_pengeringan_pdf`, giling memakai
`laporan_giling_pdf` (pembaca dan renderer giling produksi), penyosohan memakai
`layar_sosoh.laporan_sosoh_pdf`/`laporan_sosoh.ambil_data`/`buat_pdf`. Respons dan nama berkas PDF juga dipakai bersama. Tidak ada mesin PDF mockup. Daftar laporan
portal hanya menawarkan proses/nota pelanggan; agregat seluruh pabrik tidak
tersedia di portal.

## Aktivasi

1. Terapkan migrasi `0110_portal_accounts` dalam prosedur deploy aplikasi.
2. Buat akun setelah memastikan ID master pelanggan yang benar:

   ```sh
   # Lokal pada lingkungan aplikasi yang benar
   .venv/bin/python -m scripts.portal_pelanggan buat nama-pengguna --pelanggan-id 123
   # Produksi (terminal interaktif, tidak menaruh sandi di argumen)
   railway ssh --service penggilingan-beras -- python -m scripts.portal_pelanggan buat nama-pengguna --pelanggan-id 123
   ```

   Kata sandi diminta melalui terminal tanpa ditampilkan atau disimpan di
   argumen perintah. Migrasi/startup tidak membuat akun contoh.
3. Berikan URL `/pelanggan/masuk` pada akun pelanggan tersebut.

Reset sandi: `python -m scripts.portal_pelanggan reset-sandi nama-pengguna`.
Penonaktifan: `python -m scripts.portal_pelanggan nonaktifkan nama-pengguna`.
Keduanya menaikkan versi token, sehingga sesi lama tidak berlaku. Perubahan
ikatan pelanggan juga membatalkan token lama karena token menyimpan cap ID
pelanggan. Skrip tidak menyediakan penggantian ikatan pelanggan secara diam-diam.

## Riwayat kepemilikan lama

Transfer produk dan kemasan baru menyimpan atribusi pelanggan di
`portal_ownership_events` dalam transaksi audit yang sama. Atribusi tetap
tersedia setelah seluruh stok berpindah menjadi milik pabrik.

Catatan lama yang tidak memiliki bukti ID pelanggan **tidak ditebak dari nama,
tanggal, berat, atau teks audit**. Catatan tersebut perlu atribusi historis yang
terverifikasi sebelum dapat ditampilkan. Audit internal produksi tetap utuh.

## Validasi

`tests/pg/test_portal_pelanggan.py` menguji akun terpisah, CSRF, pencabutan sesi,
akses silang URL/PDF, sumber campuran, paginasi, pelanggan tanpa data,
notifikasi, dan atribusi transfer setelah pemilik stok berubah. Isi teks dan
stream gambar tiap halaman PDF dibandingkan dengan penyusun produksi.
`tests/test_portal_presentation.py` menjaga fungsi baca saat kontrol transaksi
hilang. Uji PostgreSQL hanya memakai `UJI_PG_URL` loopback bernama `uji_*`.

Hasil verifikasi lokal 23 Oktober 2026: 241 pengujian PostgreSQL dan 51
pengujian unit lulus. Pengujian keamanan portal terakhir (16 kasus) juga
lulus setelah pemeriksaan nonce CSRF dan waktu cetak PDF distabilkan.
Browser memeriksa 248 keadaan halaman ditambah 32 keadaan pada lebar
320/390/768/1440 piksel; 124 pemeriksaan halaman/tema tidak menemukan
kontras teks di bawah ambang yang diuji. Sidebar, pencarian, filter gudang,
unduh/bagikan PDF dan status baca notifikasi diuji lewat interaksi browser.
Bukti tampilan tersimpan di `output/portal-production-validation/`.
Ponsel diuji melalui viewport Chromium; belum diuji pada perangkat fisik.
Catatan di atas merupakan verifikasi lokal sebelum rilis produksi.


## Rilis produksi 23 Oktober 2026

Integrasi disusun di atas commit produksi `43a166d934dc189cf9c6b7b94451b9f9c8ed9576`,
bukan mengganti produksi dengan checkout portal yang lebih lama. Komponen tampilan
rilis ini v427; detail/tab produksi terbaru dipertahankan. Berkas provisioning
akun ikut dimasukkan ke image agar akun dapat diaktifkan melalui SSH interaktif.

Pra-migrasi: skema produksi `0109_pk_penyesuaian_stok`. Migrasi `0110` hanya
menambahkan tiga tabel portal; `lock_timeout=5s` dan `statement_timeout=60s`
berlaku lokal dalam transaksi. Kegagalan menggulung balik transaksi, dan
entrypoint menolak menjalankan aplikasi jika migrasi tetap gagal.

Cadangan sebelum migrasi dibuat langsung pada volume Postgres-NPz3, tidak
disalurkan ke laptop: `/var/lib/postgresql/data/portal-backups/sebelum-0110-20261023.dump`
(izin 0600, 4.467.339 byte, SHA-256
`9b97116059ecc502764d4b1f75553b508d67ea12c8af9f788bdc5d2dd92993e0`).
Daftar dan seluruh isi arsip dibaca melalui `pg_restore` di server. Snapshot
Railway tidak tersedia pada paket saat ini; cadangan ini satu volume dengan DB,
sehingga merupakan perlindungan migrasi logis, bukan pemulihan kehilangan volume.

Baseline sebelum rilis: deployment `10e31e2b-d890-4b9a-a7fa-61c366457206`
(commit `74cc0be`). **Jangan langsung menjalankan image lama itu setelah 0110**:
entrypoint Alembic-nya belum mengenali revisi baru. Cabang pemulihan kompatibel
`pemulihan/portal-pelanggan-0110` (commit `1be8999`) mempertahankan aplikasi
baseline, file migrasi 0110, dan deklarasi tiga model portal tanpa router
pelanggan. `alembic check`, impor aplikasi dan `alembic upgrade head` diuji
terhadap skema 0110. Bila perlu, buat commit pemulihan baru ke main dari
perbedaan cabang tersebut setelah memeriksa perubahan produksi yang masuk
sesudah rilis. Tabel portal tetap ada. Jangan downgrade berisi atau restore
seluruh database bersama setelah transaksi operasional baru tercatat. Pemulihan
DB hanya dilakukan jika diperlukan, dengan menilai transaksi setelah cadangan.

Tidak membuat akun contoh atau menautkan akun ke pelanggan sungguhan secara
sembarang. Aktivasi akun memerlukan identitas master pelanggan terverifikasi.


Pembaruan produksi yang datang selama verifikasi (`589abd0`, penghapusan akses
cepat Beranda) digabungkan tanpa mengubah kode portal yang diuji. Baseline
rollback terakhir adalah deployment commit tersebut, bukan baseline awal.
Pemeriksaan tambahan: 2.193 regresi lokal lulus, 21 uji keamanan/presentasi
lanjutan lulus, 248 tampilan dan tab GET desktop/ponsel lulus, 124 pemeriksaan
kontras lulus. Uji cookie TLS proxy tambahan juga lulus. CI rilis memeriksa
seluruh suite terhadap database PostgreSQL kosong sebelum promosi.


Pemeriksaan kontras diperluas ke 120 keadaan panel detail yang dipilih melalui
tab; tidak ada temuan pada ambang yang diperiksa. Cookie sesi/CSRF portal
memakai Secure pada Railway meskipun koneksi internal ASGI berupa HTTP setelah
TLS berakhir di proxy.

Pembaruan lanjutan `74cc0be` (infografis Beranda, v426) juga dipertahankan; paket
portal memakai v427 untuk mencegah cache aset lama. Cabang pemulihan ikut
mempertahankan perubahan Beranda ini.


CI kandidat aplikasi `7926c25` lulus seluruh tahapan:
https://github.com/hadimulyautama/penggilingan-beras/actions/runs/39971056458
Perubahan setelah kandidat itu hanya penggabungan pembaruan Beranda yang sudah
terbit, nomor aset v427, manifest dan catatan rilis; kode aplikasi, Dockerfile,
dependensi dan migrasi identik. Penjaga paket dan tampilan/PDF terkait lulus
ulang setelah penggabungan.

Cadangan terakhir tepat sebelum promosi:
`/var/lib/postgresql/data/portal-backups/sebelum-0110-final-20261023.dump`,
4.467.340 byte, izin 0600, SHA-256
`1a9f1380a86310a6c21f08b133d88b666c021f8f9fe035a9b8735d887c4cdde5`.
Seluruh arsip diverifikasi dengan `pg_restore --file=/dev/null` di server.
