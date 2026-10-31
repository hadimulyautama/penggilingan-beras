# Portal pelanggan

Portal terintegrasi di `/pelanggan`, dengan login `/pelanggan/masuk`.
Desktop dan ponsel memakai URL yang sama. Identitas dan pengaturan ponsel dibuka melalui Menu.
Tema memakai cookie `produksi_terik` serta aset dan token warna produksi.

## Pengalaman pelanggan (1 November 2026)

Navigasi utama terdiri dari **Beranda**, **Barang masuk**, **Barang Saya**,
**Proses Berjalan**, **Riwayat proses**, **Pengambilan barang**, dan **Dokumen**.
Ponsel menyediakan Beranda, Barang Saya, Proses Berjalan, dan tombol Menu pada
navigasi bawah. Menu membuka seluruh tujuan, identitas, pemasangan aplikasi,
dan keluar. Pilihan tema tetap ada di header.

Beranda menampilkan status, **jumlah per komoditas**, dan progres proses.
Panel Kabar terbaru tidak ditampilkan di beranda. Tombol Barang masuk,
Pengambilan barang, dan Riwayat proses hanya ada pada menu utama. Setiap komoditas dapat
dibuka ke lokasi/batch, kemudian rincian asal, waktu, kendaraan dan halaman
barang yang sama seperti sebelumnya. Halaman Barang Saya memakai susunan
stok yang sama. Halaman Barang Saya hanya memuat stok, lokasi, asal barang,
dan rincian stok/karung; perpindahan ke Pengambilan barang melalui menu utama.

`portal/barang.py` memakai pembaca bobot gabah, sisa tumpukan PK, produk,
serta `hitung_stok_silo` dan `komposisi_bahan_silo` Gudang 2. Otorisasi isi
silo dilakukan sebelum membaca jumlah/asalnya. Jumlah setiap komoditas
hanya menjumlah saldo lokasi yang masih ada; berat batch asal adalah
penelusuran dan tidak dijumlah lagi. Bahan yang belum teridentifikasi dan
berat yang belum diketahui tetap ditandai, tidak ditebak sebagai PK/nol.

Label dan navigasi rincian pelanggan menggunakan bahasa pelanggan; tab audit,
pengelolaan proses, dan petunjuk pencatatan operator tidak ditawarkan sebagai
tugas pelanggan. Isi catatan asli dan angka produksi tetap dipertahankan.

`/pelanggan/ringkasan` dan `/pelanggan/` membuka beranda khusus pelanggan.
`/pelanggan/jasa-saya` memuat progres berjalan dan bahan menunggu proses.
Detail mutu tersedia melalui rincian barang/proses. Halaman ini tidak
mengulang daftar riwayat, stok, penerimaan atau pengambilan. `/pelanggan/riwayat-proses` memuat
proses selesai dengan tanggal, filter jenis dan tautan detail/hasil asli;
pendinginan yang belum selesai tidak masuk riwayat selesai.
`/pelanggan/barang-masuk` hanya menampilkan catatan penerimaan aktual,
termasuk data lama tanpa tiket. Daftarnya memakai komponen yang sama dengan
Produksi (`_daftar_penerimaan.html`): identitas/kode, status, jenis, armada,
bobot diterima, dan waktu penerimaan. Pencarian dan filter jenis diterapkan
sebelum paginasi 25 baris. Metadata tiket hanya dibaca jika ID tiket juga
lolos cakupan pelanggan; bobot berasal dari `bobot_diterima` native.
Tiket antrean, penolakan, dan PK berstatus
baru tidak masuk. Gabah berstatus baru sudah diterima dan tetap ditampilkan.
`/pelanggan/barang-keluar` menjadi menu Pengambilan barang, dengan batas
kepemilikan per `OutgoingItem.jasa_id`; penjualan kepada orang yang sama
bukan pengambilan jasa. Rencana belum dimuat tidak menampilkan berat sebagai
muatan aktual. Daftar, rincian, status, pencarian/filter, dan paginasi pengambilan memakai
pembaca Produksi. Daftar aktif serta riwayat memakai komponen tabel yang
sama dengan Produksi. Muatan kiriman bersama dihitung hanya dari alokasi
pelanggan yang lolos scope; pelanggan lain dan penjualan biasa tidak ikut.
`/pelanggan/barang-saya` memuat jumlah per komoditas dan rincian stok.
Rekap jasa berada di Dokumen, satu rekap per pesanan utama; daftar pesanan
asal yang sudah digabung tidak ditampilkan pada perjalanan jasa.
Dokumen di `/pelanggan/laporan` mempertahankan PDF produksi dan bukti serah terima.
URL detail lama dan tautan tab beranda lama tetap dilayani.

Pembaca `portal/beranda.py` memakai `jasa_pelanggan.pelanggan(...,
read_scope=scope)` dan `berjalan.untuk(..., read_scope=scope)`. Transit tetap
berasal dari `Berjalan.transit`, termasuk pemeriksaan sumber silo/mesin.
Bidang aksi operator tidak diproyeksikan ke kartu pelanggan.

Jumlah per komoditas memakai saldo lokasi yang masih ada. Bobot yang belum
diukur tetap berbeda dari nol; hasil tercatat tidak dianggap izin siap
ambil. Pendinginan yang belum selesai tetap ditampilkan sebagai proses.
Portal memberi tahu bahwa proses dan pencatatan ditangani petugas, tanpa
menagih pelanggan untuk menyelesaikan tugas operator.

Progres berjalan tampil langsung pada Beranda dan Proses Berjalan. Pengeringan
memakai `Baris.maju` (kemajuan menuju target kadar air); penggilingan dan
penyosohan memakai fakta serta hasil sementara dari kartu produksi yang
sama. Rendemen tidak digambar sebagai persentase selesai. Detail progres,
pengukuran, hasil dan jeda tetap dapat dibuka dari setiap kartu.

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
- HTML/PDF bersifat privat dan tidak disimpan cache. Worker portal hanya
  menyediakan pesan umum saat luring; data pelanggan tetap dari jaringan.

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


## Kelola akun melalui Pengaturan

Super Admin membuka **Pengaturan → Kelola pengguna → Pelanggan**
(`/pengguna/pelanggan`). Pilih pelanggan dari kontak Kledo yang sudah
tersinkron, lalu tentukan username dan kata sandi beserta konfirmasinya.
Peran tetap **Pelanggan**. Username tidak boleh berbenturan dengan akun
produksi yang sudah ada. Pembuatan akun tidak menulis `users` atau
`produksi_akun`, sehingga kredensial ini hanya berlaku pada portal pelanggan.

Pemilihan memakai pasangan ID master pelanggan dan ID kontak Kledo, bukan
nama; kontak aktif yang belum tertaut atau tertaut ambigu tidak bisa dipilih.
Kontak diperiksa ulang dan dikunci saat simpan. Gunakan tautan **Perbarui kontak
Kledo** bila kontak baru belum tersinkron. Pengelolaan ini tidak membuat atau
mengubah kontak di Kledo.

Field **Pelanggan dari kontak Kledo** mencari seluruh kontak saat nama diketik,
tanpa berpindah halaman. Hasil juga dapat dicari lewat nomor kontak atau telepon;
20 kecocokan ditampilkan sekaligus dengan petunjuk mempersempit pencarian.
Klik nama atau pilih dengan tombol panah dan Enter. Identitas tersimpan hanya
setelah hasil dipilih; mengubah teks membatalkan pilihan sebelumnya. Endpoint
pencarian wajib Super Admin dan menggunakan `Cache-Control: no-store`.
Jika penyimpanan ditolak, pelanggan yang masih valid dan username tetap terisi,
sedangkan kata sandi harus diketik ulang. Daftar akun memiliki pencarian dan
paginasi tersendiri (20 baris per halaman).
Super Admin dapat mengubah username/kata sandi dan aktif/nonaktif akun. Sesi
lama dicabut melalui `token_version`. Tautan pelanggan tidak dapat diganti pada
akun yang ada; nonaktifkan akun lama dan buat akun baru bila ikatan awal salah.
Kata sandi tidak ditampilkan kembali, disimpan di audit, atau dikirim melalui
URL. Audit tindakan akun tersimpan dalam transaksi yang sama. Akun staf dan
portal tetap memakai tabel, cookie, dan kunci tanda tangan yang terpisah.

Rute GET/POST pengelolaan wajib Super Admin tanpa pengecualian Admin darurat.
Berlaku juga saat sistem belum memiliki Super Admin aktif. Tidak ada migrasi
baru untuk halaman pengelolaan ini; memakai tabel portal dari migrasi 0110.

## Pemasangan PadiFlow Pelanggan

Portal dapat dipasang dari `/pelanggan/masuk` atau tombol **Pasang aplikasi**
di menu pelanggan. Android/desktop yang mendukung menampilkan dialog pemasangan;
Safari iPhone/iPad memakai Bagikan → Tambahkan ke Layar Utama, Safari Mac memakai
File → Tambahkan ke Dock.

Nama aplikasi **PadiFlow Pelanggan**, memakai marka PadiFlow putih dengan latar
oranye. Manifest `/pelanggan/manifest.webmanifest` mempunyai ID dan cakupan
`/pelanggan/`, terpisah dari pemasangan PadiFlow Produksi. Halaman awal
`/pelanggan/` membuka ringkasan saat sesi aktif atau login pelanggan bila belum
masuk. Ikon dibuat ulang melalui `scripts/buat_ikon_pelanggan.py`.

Worker `/pelanggan/sw.js` hanya menaungi portal. Halaman, PDF, dan sesi tidak
disimpan dalam Cache Storage; saat jaringan putus hanya pesan umum yang tampil.
Pemasangan tidak mengubah pembatasan data server maupun akses app internal.

## Perapian fokus halaman

Halaman Proses Berjalan hanya memuat progres aktif dan bahan menunggu proses;
riwayat selesai berada pada menu Riwayat proses. Barang Saya tidak memuat
tombol pengambilan atau proses lain. Dokumen menyediakan buka dokumen dan
unduh PDF tanpa pilihan baca PDF tambahan yang menduplikasi tujuan. Ikon
Kabar di header dihilangkan. Tautan kembali mengikuti konteks stok, riwayat,
proses aktif, penerimaan, pengambilan, atau dokumen, dan tidak ditampilkan ganda.

Laporan sosoh yang belum memiliki rincian pemakaian silo tetap menyediakan
rincian proses. Unduh PDF baru ditawarkan setelah syarat pembaca PDF native
terpenuhi, sehingga tidak ada tombol unduh yang menuju 404.
