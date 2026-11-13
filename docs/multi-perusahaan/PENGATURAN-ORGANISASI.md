# Pengaturan perusahaan, lokasi, dan penetapan gudang lama

## Penempatan yang dipilih

Pintu **Perusahaan & lokasi pabrik** berada di **Pengaturan → Perusahaan &
fasilitas**, sebelum Gudang dan Mesin & line produksi. Urutan mengikuti
hierarki perusahaan → lokasi pabrik → gudang → line. Pintu ini hanya dapat
dibuka Super Admin, sama seperti pengelolaan identitas penerbit dokumen;
pintu darurat pengelolaan akun tidak membuka administrasi organisasi.

| Pilihan penempatan | Penilaian |
|---|---|
| Perusahaan & fasilitas | Dipilih: satu kelompok dengan gudang, silo dan line yang lokasinya akan disiapkan. |
| Pengguna & hak akses | Tepat untuk keanggotaan nanti; tidak tepat sebagai tempat utama struktur fisik perusahaan/pabrik. |
| Operasional | Dipakai aturan bahan, hasil, dan QC; pengelolaan organisasi lebih jarang dan lintas proses. |
| Identitas & logo perusahaan | Tetap khusus identitas penerbit dokumen yang berlaku saat ini; tidak disatukan dengan master organisasi agar perubahan struktur tidak dianggap mengubah dokumen. |

## Yang dapat dikelola

- Daftar/rincian perusahaan, penambahan dan perubahan nama/status.
- Daftar/rincian lokasi pabrik per perusahaan, alamat dan status.
- Kode serta perusahaan induk lokasi tetap setelah dibuat. Tidak ada hapus
  permanen; penonaktifan master yang masih digunakan ditolak.
- Alasan wajib dan audit sebelum/sesudah menyertai perubahan. Formulir usang
  ditolak dan isian pengguna dipertahankan; dua penyimpanan bersamaan hanya
  dapat menghasilkan satu perubahan. Penyimpanan tanpa perubahan tidak
  menambah audit.
- Jejak baru muncul pada Audit dengan label perusahaan/lokasi. Pengelolaan
  organisasi tidak menggeser kandidat pembatalan pekerjaan lantai. Master
  dikoreksi melalui Pengaturan, tanpa layanan undo transaksi.

## Menyiapkan data lama

**Pratinjau penetapan gudang** menerima tujuan lokasi pabrik dan gudang yang
secara eksplisit dipilih pengguna. Hasil menunjukkan penetapan saat ini,
tujuan rencana, status belum ditetapkan/sudah sesuai/berbeda/nonaktif, serta
jumlah silo, dryer dan line yang terhubung melalui ID gudang sebenarnya.
Nama atau kode gudang tidak dipakai untuk menebak perusahaan.

Pratinjau tetap pembacaan GET. Sesudah meninjau tujuan dan setiap gudang,
Super Admin mengisi alasan, menandai pemeriksaan, lalu memilih **Terapkan
penetapan gudang**. Bukti pratinjau HMAC terikat pada akun, daftar ID gudang,
tujuan, snapshot metadata/fasilitas/penetapan saat ini, dan masa berlaku 30
menit. POST tanpa bukti, bukti yang diganti, akun lain, atau pratinjau usang
ditolak. Bukti gagal tidak diganti diam-diam dengan izin yang baru. Perubahan pilihan
di layar menonaktifkan tombol penerapan sampai pilihan kembali sama atau
pratinjau baru dibuat; draf alasan dipertahankan.

Penerapan hanya menambah `hmu_warehouse_sites` untuk gudang aktif yang belum
ditetapkan. Baris yang sudah menunjuk tujuan sama tidak ditulis ulang.
Gudang yang menunjuk perusahaan/lokasi berbeda memblokir seluruh rencana;
pemindahan/koreksi penetapan bukan bagian tahap pemasangan awal ini.
Pilihan nonaktif juga memblokir rencana. Tidak ada penerapan sebagian.

Kunci lokasi → perusahaan mengikuti editor master. Gudang dikunci menurut
ID dengan NO KEY UPDATE untuk menserialisasi penetapan walau baris penghubung
belum ada, sambil membolehkan KEY SHARE pemakaian FK oleh operasi lain.
Semua penetapan dan audit satu transaksi. Pengiriman ulang bukti yang sudah
berhasil menghasilkan respons sukses tanpa baris atau audit ganda. Penyimpanan
berbeda yang bertabrakan wajib meninjau ulang pratinjau.

Audit per gudang mencatat sebelum (belum ditetapkan), sesudah (ID dan nama
perusahaan/lokasi/gudang saat itu), pelaku, waktu, alasan, serta identitas
rencana. Detail lokasi menyajikan **Riwayat penetapan gudang** lengkap dalam
halaman 50 catatan. Nama pada snapshot audit tidak mengikuti penggantian nama
master. Jejak juga tetap muncul pada Audit umum; metadata ini tidak dapat
memakai undo transaksi dan tidak menggeser kandidat pembatalan operator.

Tidak ada migrasi baru atau penerapan saat deploy. Tidak ada pengisian master
atau penetapan otomatis berdasarkan nama/kode gudang. Transaksi historis,
stok, pemilik barang, pengguna, keanggotaan, dan relasi fasilitas tetap utuh.

Jumlah fasilitas tidak diklaim sebagai jumlah transaksi historis yang bisa
dipindahkan. Transaksi dengan sumber lintas gudang/perusahaan, asal yang belum
jelas, dan data tanpa hubungan gudang yang tegas perlu ditinjau tersendiri
sebelum cakupan perusahaan pada transaksi historis diaktifkan. Tidak ada fallback ke perusahaan pertama.

## Batas aktivasi

Mengisi master tidak mengaktifkan operasi perusahaan kedua, pemilihan tenant,
perubahan sesi, atau pemisahan master produk/kontak/kemasan. Alur dan izin
operasional yang sudah berlaku tetap digunakan. Tidak ada migrasi skema baru
pada tahap halaman ini.

## Pengujian

Uji HTTP memakai PostgreSQL loopback khusus uji: pembatasan peran termasuk
mode lihat-sebagai, CSRF, kode tetap, induk nonaktif, payload asing, formulir
usang, balapan dua perubahan, audit lengkap berhalaman, penolakan token/payload
usang, pengiriman ulang, balapan dua tujuan, rollback audit, dan kunci yang
tidak memblokir FK operator. Sidik seluruh tabel di luar dua master
organisasi/audit harus identik pada pengelolaan master. Pada penerapan,
seluruh tabel di luar penghubung penetapan dan audit harus identik; pratinjau harus
menjaga sidik seluruh tabel identik, termasuk tanpa autoflush draf ORM.

Browser memakai server HTTP lokal asli dengan lifespan dimatikan agar tidak
menyalakan bot/scheduler. Profil 320, 390 dan 1440 px menempuh Pengaturan →
tambah perusahaan → tambah lokasi → pratinjau → terapkan → riwayat. Redirect
asli, keterbacaan, pratinjau tanpa mutasi, perubahan pilihan tanpa kehilangan
alasan, serta penetapan hanya setelah tindakan eksplisit diperiksa. CI menjalankannya pada
Chromium dan WebKit/iPhone. Data produksi tidak dipakai untuk simulasi.
