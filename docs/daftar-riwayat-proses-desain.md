# Kontrol bersama daftar riwayat proses

Daftar pengeringan, penggilingan, penyosohan dan transfer memakai kerangka
`_daftar_riwayat_proses.html`. Judul Riwayat proses, tab jenis bergaris bawah,
Panduan berikon ⓘ, Print dan menu navigasi mengikuti mockup yang disetujui.
Ringkasan menyatukan tiga nilai asli per halaman dalam satu bidang; jumlah,
bobot dan rendemen tetap dibaca dari ekspresi semula, tanpa hitungan baru.
Panduan menjelaskan jenis proses yang sedang dibuka.

Keempat templat daftar hanya mengganti induk dan nama blok. Seluruh markup,
kondisi, ekspresi data, tabel desktop, kartu ponsel, rincian, tautan detail/PDF,
penanda bobot/hasil belum pasti, snapshot penutupan dan tombol kursor tetap
identik dengan basis implementasi. Ringkasan adalah data halaman yang sedang
dibuka, bukan rekap seluruh riwayat. Transfer dibatalkan tetap ditampilkan.

Skrip memindahkan node navigasi induk asli ke dialog serta pilihan jenis ke
area tab. Tautan, penanda aktif, pilihan terkunci, cakupan gudang dan reader
GET tetap milik server. Dialog bawaan dipindah ke luar dialog navigasi agar
panduan induk bisa dibuka tanpa modal bertumpuk. Print memanggil fasilitas
cetak browser yang sama. Tidak menambah pencarian, filter, sortir atau ekspor.
Tanpa skrip penataan, navigasi induk tetap tersedia pada posisi asli.

Portal pelanggan mempertahankan kerangka dan macro header lama melalui
PORTAL_READ_ONLY. Detail proses yang sudah diseragamkan, komponen/paket
bersama, layanan, endpoint, aturan izin dan migrasi tidak diubah. Tidak ada
mutasi data produksi sebagai bagian implementasi ini.

Uji browser lokal `tests/pg/test_daftar_riwayat_proses_desain_browser.py`
dengan UJI_BROWSER_DAFTAR_RIWAYAT_PROSES=1 mencakup lebar 1440/390/320,
keempat daftar, navigasi jenis/induk, panduan lokal/induk, Print sekali per
klik, tautan detail dan laporan, kursor akhir/terbaru, transfer dibatalkan,
operator G1/G2 dan ketiadaan mutasi log saat membaca. Suite riwayat lama,
navigasi/kontrol laporan, portal, paket dan cap aset ikut dijalankan pada
PostgreSQL lokal terisolasi. Perubahan disiapkan untuk persetujuan rilis;
implementasi tidak otomatis menerbitkan ke produksi.
