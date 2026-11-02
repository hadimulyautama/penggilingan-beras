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

## Detail stok dan proses pelanggan

Detail PK/produk hanya memiliki satu judul dan satu tautan kembali ke Barang
Saya. Stok saat ini dan ringkasan tetap terbuka; mutu, rumus penilaian, asal
bahan, dan rincian kemasan tersedia pada bagian yang dapat dibuka. Angka,
ketidakpastian bobot, catatan, dan penanda perkiraan asal stok tetap berasal
dari pembaca native. Tidak ada perubahan komponen/layar staf.

Detail proses menonjolkan nama proses, nomor referensi, status dan hasil.
Tab bahan/hasil/pengukuran/riwayat tetap memakai GET native dan paginasi tetap
tersedia; tombol ringkasan yang mengulang tab dihilangkan. ID jasa, pemilik
yang berulang, pengaturan mesin dan petunjuk tindakan operator tidak menjadi
isi utama pelanggan. Rincian teknis dapat dibuka tanpa menghilangkan data.

Detail Barang masuk dan Pengambilan barang memakai pembaca Produksi yang
sama, lalu dirapikan hanya untuk pelanggan. Satu tautan kembali mengikuti
menu asal. Tab tidak diulang menjadi tombol di ringkasan; pengambilan selesai
tidak menawarkan tautan ke tampilan perintah lain untuk transaksi yang sama.
Dokumen dikelompokkan dan setiap jenis dokumen ditampilkan sekali. Berat
penerimaan tetap berbeda dari berat pada tiket dan sisa stok. Rencana,
jumlah dimuat/keluar, selisih, berat yang belum diukur, catatan asli dan
penanda catatan timbang lama tetap dipertahankan. Identitas pemilik berulang,
petunjuk operator, panel retur kosong dan ringkasan total berulang disisihkan.
Rincian kiriman bersama tetap dibatasi sebelum HTML dibuat; total/tiket
gabungan milik pelanggan lain tidak masuk halaman pelanggan.

Riwayat proses dan Dokumen memakai daftar yang sama: nama yang mudah dibaca,
kode sekunder, tanggal dari sumber, dan satu tautan utama per catatan. Filter
jenis serta pencarian kode/nama diterapkan setelah cakupan pemilik, sebelum
paginasi 25 baris. Urutan terbaru berdasarkan waktu sumber, bukan jenis atau
nomor urut lintas tabel. Halaman lama tetap dapat dibuka; filter bertahan
ketika berpindah halaman. Alamat daftar serah terima lama membuka katalog
Dokumen yang sama sehingga tidak ada daftar tambahan dengan istilah berbeda.

Dokumen hanya menampilkan rekap utama untuk pesanan gabungan dan bukti yang
dinyatakan tersedia oleh layanan native. Laporan sosoh tanpa rincian bahan
tetap menawarkan hasil HTML, tanpa tautan PDF yang gagal. Pembaca rekap/bukti
memiliki satu tautan kembali ke Dokumen dan satu tombol unduh. Nomor terkait
serta rincian berat dapat dibuka bila diperlukan; bobot, catatan, syarat mutu,
dan PDF resmi tidak dihitung atau disusun ulang oleh lapisan tampilan ini.

Audit alur HP memakai seluruh menu dan detail dengan stok, empat tahap proses,
penerimaan, pengambilan, pengembalian, serta pemeriksaan mutu. HP memakai satu
tombol Menu di navigasi bawah. Menu mempunyai tombol tutup, pemulihan fokus,
Escape dan batas fokus di panel; isi belakang tidak menerima fokus saat menu
terbuka. Menu yang tertutup tidak masuk urutan fokus HP. Pada desktop, sidebar
tetap dapat dipakai setelah perubahan ukuran layar.

Logo tidak diberi bingkai pada pembukaan menu atau klik. Fokus saat membuka
menu diarahkan ke halaman aktif, dan fokus keyboard pada logo ditandai garis
bawah. Tautan kembali dan kontrol utama mempunyai target minimal 44 px.
Tab pembaca native dapat dijangkau dengan tombol arah dan diaktifkan melalui
Enter/Spasi tanpa mengubah pembatasan GET. Halaman mutu serta pengembalian
memakai judul pelanggan, satu tautan kembali dan satu pintu per bagian; nomor
jasa berulang dan petunjuk operator disisihkan. Catatan asli tetap dibaca utuh.

Beranda ringkas mendahulukan stok dan proses dalam dua panel (berdampingan
di desktop, berurutan di HP). Tiga komoditas pertama terlihat langsung;
komoditas berikutnya dapat dibuka pada Barang lainnya, dengan rincian batch
tetap tersedia. Tiga proses pertama mempunyai satu tautan per proses dan
status yang jelas; proses dijeda didahulukan. Sisa proses dan bahan menunggu
tersedia lewat satu tautan Semua proses. Angka kemajuan hanya ditampilkan
untuk target kadar air asli, tanpa mengubah rasio hasil menjadi persen selesai.

Label total komoditas membedakan hasil timbang dengan angka yang masih
mencakup perkiraan. Peringatan Ada barang belum ditimbang terlihat sebelum
rincian dibuka, dan barang tersebut tidak termasuk angka total yang tersedia.
Berat yang seluruhnya belum diketahui tetap Belum ditimbang, bukan nol.
Nama menu, judul dan tautan kembali memakai penulisan yang sama. Pemasangan
aplikasi dan keluar tersedia di Pengaturan akun agar menu utama lebih ringkas.

Identitas kartu proses menyebut barangnya: pengeringan/pendinginan/penggilingan
untuk gabah, serta penyosohan sesuai komposisi asli per pemakaian silo.
Bahan campuran disebut campuran; sumber yang belum jelas tetap dinyatakan
belum tercatat. Kode tetap menjadi identitas sekunder dan alamat lama berlaku.
Ringkasan detail proses memakai identitas yang sama, berat bahan asli dan
lokasi dari pembaca native, tanpa menggandakan angka utama di statistik.

Petunjuk pelanggan mengikuti status: proses aktif/dijeda ditangani petugas,
proses selesai tidak otomatis berarti siap diambil. Rencana pengambilan
memerlukan konfirmasi petugas. Pembaruan waktu berasal dari proses, catatan
hasil/mutu/pendinginan, jeda dan audit pencatatan/koreksi yang terkait lewat
ID proses atau FK anak yang sudah dibatasi pemilik. Waktu mulai diberi label
tersendiri; waktu buka halaman tidak digunakan. Detail stok agregat belum
memiliki waktu pembaruan menyeluruh sehingga menyatakan waktunya belum
tersedia, bukan memakai tanggal masuk atau waktu proses sebagai pembaruan stok.

Barang saya mempunyai satu ringkasan komoditas dan bagian Karung kosong
tersendiri. Tiga pintasan Rincian stok & karung dihilangkan. Saldo kemasan
kosong dibaca dari stok_kemasan_rinci dengan pelanggan_id sesi (satuan lembar),
tanpa mengubahnya menjadi berat barang. Kombinasi saldo nol tidak ditampilkan;
defisit tetap tampak. Karung berisi ditampilkan bersama barangnya dari
ringkasan karung PK dan baris kemasan produk native, termasuk perkiraannya.

Rincian stok menandai sisa saat ini, berat asal/saat diterima dan jumlah
karung saat diterima secara terpisah. Baris yang belum ditimbang tetap ada,
dikelompokkan tersendiri ketika ada stok terukur. Satu tautan utama per
catatan stok; tautan batch asal yang berbeda tetap tersedia. Berat sementara
tidak diulang dan berat yang belum tersedia tidak menjadi nol.

Detail produk mendahulukan stok saat ini dan kartu kemasan/curah yang dapat
dibaca di HP. Ringkasan total yang berulang dihilangkan; riwayat jumlah dan
perkiraan asal stok tetap dapat dibuka. Peringatan hasil belum final tetap
terlihat di luar lipatan. Detail PK karung mempertahankan sisa, peringatan
penimbangan, catatan penerimaan dan mutu. Perhitungan sumber, FIFO, PDF,
transit, serta tampilan operator tidak diubah. Alamat stok lama tetap dapat
dibaca; judul spesifik dan satu filter lokasi menggantikan tombol kategori
serta tombol gudang yang berulang di portal pelanggan.

Ringkasan detail stok mengelompokkan berat stok dan kemasan dalam satu kartu.
Pada satu kelompok dengan berat persis sama dengan total, berat tidak diulang.
Berat tiap kelompok tetap ditampilkan untuk beberapa ukuran/kelompok atau
ketika nilainya berbeda dari total. Ukuran karung selalu berlabel nominal;
tidak ada perkalian ukuran menjadi hasil timbang baru. Jenis bahan kemasan
tersedia pada rincian yang dapat dibuka.

Jumlah karung PK memakai kalimat dari pembaca native, dengan penanda
perkiraan tetap terlihat. Berat pembulatan kedua tidak diulang. Jika berat
belum ditimbang, jumlah karung yang tercatat menjadi angka utama dan
ketidaktersediaan berat dinyatakan jelas. Peringatan penimbangan ditandai
ringkas; alasan, angka penerimaan dan selisih asli tetap tersedia pada catatan.

Penanda hasil sementara tetap terlihat di kartu utama, sementara rincian
penyebab/angkanya dapat dibuka pada Rincian jumlah stok. Waktu stok yang
belum tersedia ada pada Informasi stok; waktu buka halaman tidak dipakai
sebagai pengganti. Petunjuk umum rencana pengambilan ada sekali pada menu
Pengambilan barang, tanpa diulang pada setiap detail stok.

Jumlah karung produk yang dicatat diberi label `tercatat`; hanya baris native
`Kemasan otomatis` yang dilabeli `setara sekitar`. Kategori hasil samping
sendiri tidak cukup untuk menyebut karung perkiraan karena pencatatan kemasan
nyata juga dapat berada dalam kategori yang sama. Curah tetap tanpa jumlah
atau ukuran karung. Kelompok curah dan kemasan ditampilkan terpisah, termasuk
sisa curah perkiraan dari pembagian otomatis. Selisih negatif catatan kemasan
diberi judul Selisih berat, bukan dianggap sebagai barang curah negatif.

Untuk PK, ekuivalen karung memakai pembagi bobot per karung native dari batch
penerimaan. Pecahan tidak lagi dibulatkan menjadi karung utuh di portal:
angka ekuivalen maksimal dua desimal dengan label setara sekitar; sisa positif
di bawah satu karung disebut setara kurang dari satu karung. Ini tidak
menciptakan pencatatan karung fisik atau curah baru. Ukuran nominal tidak
menjadi pembagi bobot aktual. Penjelasan perbedaan jumlah, ukuran, dan berat
dapat dibuka pada kartu tanpa mengulang berat. Berat yang belum tersedia
menampilkan Jumlah karung tercatat dan Berat total belum ditimbang.

Status Berat sementara berada bersama angka berat. Detail stok tidak lagi
menambahkan panel yang hanya menyatakan waktu pembaruan belum tersedia;
metadata waktu proses yang memang tercatat tetap tersedia seperti sebelumnya.
Pemeriksaan mutu stok dikelompokkan dalam satu panel dengan sumber Barang ini
dan Bahan asal dibedakan. Nilai, perhitungan, putaran, catatan, dan tautan
pemeriksaan tetap tersedia; nilainya tidak digabung antarjenis sumber.

Navigasi cepat tetap memakai cache memori tab maksimal delapan halaman selama
30 detik dan selalu mengambil ulang data. Navigasi normal tidak lagi membuat
banner hijau yang menutupi halaman. Jika respons belum tiba setelah 1,2 detik,
status kecil netral muncul di bawah nama akun pada kepala halaman, lalu hilang
ketika selesai. `aria-busy` tetap mengikuti permintaan yang sedang berjalan.
Jika pengguna sudah berinteraksi dengan halaman tersimpan, pembaruan tidak
menimpa interaksi: pemberitahuan dan tombol Muat data terbaru tetap tersedia
secara ringkas di kepala halaman. Kesalahan jaringan dan sesi tetap mengikuti
jalur navigasi utuh yang sudah ada. Status tidak melekat pada halaman cache
atau bertahan sesudah navigasi selesai.
Respons HTML yang persis sama tidak mengganti isi yang sudah ditampilkan atau
memunculkan pemberitahuan pembaruan; rincian terbuka tetap dipertahankan.

Halaman Proses berjalan memakai kartu terpisah yang ringkas: nama proses dan
lokasi, status tahap, angka bahan/hasil yang tercatat, progres kadar air bila
tersedia, waktu catatan aktual dan satu tautan detail. Kode serta sumber waktu
ada pada Catatan proses di detail. Petunjuk umum pelanggan cukup sekali pada
halaman; jeda, catatan perhatian dan status yang belum tersedia tetap terlihat.
Status tahap dibedakan (dikeringkan, menunggu dingin, digiling, disosoh), tanpa
mengganti status transaksi atau memasukkan pendinginan ke riwayat terlalu awal.

Bobot proses pelanggan diproyeksikan dari pembaca estimasi/timbang yang sama:
Berat gabah saat masuk, Perkiraan setelah kering atau Berat setelah kering
untuk hasil timbang yang sah. Label perkiraan/belum ditimbang hanya muncul
bersama angka perkiraan; kondisi tanpa estimasi cukup Belum tersedia. Nol
pecahan di ujung dibuang tanpa pembulatan dan tanpa mengganti nilai sumber.
Untuk proses yang masih dikeringkan, tidak ditawarkan estimasi akhir yang
belum dapat dihitung. Catatan yang mendasari estimasi dapat dibuka di detail;
penanda sumber historis/campuran tetap dibawa, tidak dianggap saldo saat ini.

Progres tetap memakai indikator mesin terakhir dan target native, tidak
memakai alat tes sebagai pengganti dan tidak menyatakan rasio hasil sebagai
persentase selesai. Kartu menampilkan satu acuan kadar air dan target;
pengukuran alat tes, putaran, bahan, hasil dan rasio tetap tersedia pada
rincian native. Ringkasan detail berada di luar lipatan. Tab Bahan/Pengukuran/
Hasil/Riwayat dan laporan dipertahankan dalam rincian lanjutan; permintaan
tab tertentu membuka lipatan itu agar panel tujuan langsung dapat dibaca.
Perhitungan, otorisasi, transaksi, stok operator dan PDF tidak diubah.
Alamat proses pelanggan lama `/pelanggan/pekerjaan` memakai daftar ringkas yang
sama. Proses yang sudah selesai tetap mengikuti pengalihan native ke riwayat.
Untuk pendinginan yang sudah dipindah, lokasi mengikuti silo yang tercatat;
jika ada timbang sah, waktu timbang ikut dipertimbangkan sebagai pembaruan
aktual. Tidak ada penggantian waktu dengan jam saat halaman dibuka.

Rincian proses pelanggan membedakan selesainya satu tahap dari keseluruhan
jasa. Hasil pengeringan yang sudah dingin/berada di silo berjudul Hasil
pengeringan gabah, dengan penanda Pengeringan selesai serta lokasi native.
Tahap lain yang selesai memakai nama tahapnya, tanpa otomatis menawarkan
pengambilan hanya karena satu proses ditutup. Menunggu pemindahan tetap
mengikuti keadaan yang tercatat, bukan dianggap sudah dipindah.

Dua kelompok rincian adalah Rincian berat serta Bahan dan riwayat. Kode dan
sumber pembaruan masuk ke kelompok kedua bersama tab native yang dipertahankan.
Statistik berat/hasil berada pada kelompok pertama. Tidak ada lipatan ketiga
untuk catatan yang sama. Pada ringkasan, Gabah basah saat masuk dipasangkan
dengan Perkiraan berat kering atau Berat kering hasil timbang. Penanda Belum
ditimbang cukup sekali; bila perkiraan belum ada, ringkasan menyatakan berat
kering belum ditimbang dan alasannya tersedia di Rincian berat.

Waktu Ditimbang hanya memakai waktu yang tersimpan bersama hasil timbang
sah dari pembaca native. Nilai kosong, salah bentuk atau bukan hasil timbang
sah tidak memperoleh waktu pengganti dari pembaruan proses maupun jam buka.
Ringkasan hasil timbang menampilkan Waktu timbang belum tercatat bila waktu
tersebut tidak tersedia. Pembaruan proses tetap ada pada Bahan dan riwayat,
dengan jenis kejadian dan tanggal aslinya. Seluruh angka, perhitungan, saldo,
riwayat koreksi dan PDF tetap memakai sumber yang sama.
