# Pengaturan perusahaan, lokasi, dan pratinjau data lama

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

Pratinjau adalah pembacaan GET. Tidak ada tombol penerapan, endpoint POST,
atau fungsi layanan yang menulis `PenempatanGudang`. Payload tambahan pada
formulir master ditolak; endpoint tebakan penerapan tidak tersedia. Rencana
belum disimpan pada server. Transaksi historis, stok, pemilik barang, pengguna,
keanggotaan, dan relasi fasilitas tidak ditulis ulang.

Jumlah fasilitas tidak diklaim sebagai jumlah transaksi historis yang bisa
dipindahkan. Transaksi dengan sumber lintas gudang/perusahaan, asal yang belum
jelas, dan data tanpa hubungan gudang yang tegas perlu ditinjau tersendiri
sebelum tahap penerapan dirancang. Tidak ada fallback ke perusahaan pertama.

## Batas aktivasi

Mengisi master tidak mengaktifkan operasi perusahaan kedua, pemilihan tenant,
perubahan sesi, atau pemisahan master produk/kontak/kemasan. Alur dan izin
operasional yang sudah berlaku tetap digunakan. Tidak ada migrasi skema baru
pada tahap halaman ini.

## Pengujian

Uji HTTP memakai PostgreSQL loopback khusus uji: pembatasan peran termasuk
mode lihat-sebagai, CSRF, kode tetap, induk nonaktif, payload asing, formulir
usang, balapan dua perubahan, audit, dan penolakan penerapan. Sidik seluruh
tabel di luar dua master organisasi/audit harus identik; pratinjau harus
menjaga sidik seluruh tabel identik, termasuk tanpa autoflush draf ORM.

Browser memakai server HTTP lokal asli dengan lifespan dimatikan agar tidak
menyalakan bot/scheduler. Profil 320, 390 dan 1440 px menempuh Pengaturan →
tambah perusahaan → tambah lokasi → pratinjau; redirect asli, keterbacaan,
dan tidak adanya tombol/POST penerapan diperiksa. CI menjalankannya pada
Chromium dan WebKit/iPhone. Data produksi tidak dipakai untuk simulasi.
