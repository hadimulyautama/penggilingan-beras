# Jasa LIST: struktur native tanpa judul transisi

Basis exact `4daaf8f1935a044462d402a9308c0088668dd928`. Terpisah dari
proposal QC `a7ddb4bd`; tidak mengubah root worktree/compiler/registry.

`jasa_pelanggan.html` native tidak mempunyai H1 pada isi daftar. Template shell
sebelumnya menambah H1 Pesanan Jasa yang tidak ada setelah data datang. Patch
menghapus heading itu dan memberi nama region melalui aria-label. Judul dokumen
pada block judul tetap Pesanan Jasa; header aplikasi dan breadcrumb milik base.

Urutan konten utama sekarang kontrol native → jumlah belum dibaca → daftar kartu,
sesuai kontrol → jumlah → daftar pada native. Help cetak/status/retry tetap ada,
tetapi setelah daftar agar bukan sela tambahan antara kontrol dan daftar.
Placeholder mempertahankan header Bahan titipan, susunan baris judul/badge, label
PK dan hasil yang tersedia, tiga label saldo, dan slot Detail pelanggan. Tidak
ada identitas pelanggan, angka stok, ORM, anchor target atau transaksi palsu.
Header Bahan literal mengikuti cabang tanpa baris macro native; tidak membuat
objek d hanya untuk menggambar header. Tabel/thead tidak ditambahkan: keluarga
Jasa LIST memang kartu, bukan tabel. Tidak ada field/tombol baru berizin.

## Context untuk compiler static blueprint milik root

Compile block `isi` dari `app/web/templates/jasa_bertahap.html`, loader app dahulu
lalu hmu_tampilan. Tidak perlu akun, user, kartu, jumlah, halaman, kg, model,
DB, cap CSRF, atau render base untuk blueprint isi.

- `VERSI`: token cap aset milik compiler.
- `tapis`: nilai status sah dari `app/services/jasa_pelanggan.py:STATUS`;
  compiler boleh membaca literal melalui AST tanpa import app. Jangan membuat
  pilihan status atau role baru. Chip status native mengikuti nilai ini.
- `cari`: string pencarian escaped, native maksimum 200 karakter. Compiler
  memakai placeholder yang kemudian diisi runtime aman, bukan nama pelanggan.
- `STATUS_PILIHAN`: literal STATUS otoritatif yang sama.
- `JASA_SHELL.stamp`: token binding baca; bukan otorisasi.
- `JASA_SHELL.url`: token URL reader GET existing. Runtime root harus memasang
  hanya `/api/halaman-bertahap/jasa` dengan query/konteks yang sah.
- `JASA_SHELL.filtered`: bool cari atau tapis, dipakai controller empty-state;
  bukan akses atau jumlah hasil.

Input template: jasa_bertahap.html, _jasa_kontrol.html, _kontrol_halaman.html,
_panduan.html. Asset memakai loader berlapis: jasa-pelanggan.css,
jasa-bertahap.css, jasa-kontrol.css, jasa-kontrol.js, jasa-bertahap.js. Dua script
itu tidak memakai document.currentScript pada source basis ini. Compiler root
harus tetap mengaudit aset/handler GET dan inline/CSP sesuai kontraknya sendiri;
patch tidak mengubah atau menjalankan compiler.

Print disabled masih dipasang builder existing `jasa_bertahap.kerangka`, bukan
oleh template. Compiler yang merender block langsung wajib menonaktifkan seluruh
`[data-js-cetak]` dengan aria-describedby jasa-cetak-alasan, sama seperti builder.
Tidak boleh menganggap render block sudah menjalankan guard can_see_financials.
Descriptor/reader/root tetap harus memeriksa izin native dan konteks segar.

## Posisi yang tetap dapat bergeser

Yang dibuktikan pure: kontrol native identik dan pertama; tidak ada H1 shell;
jumlah langsung mendahului daftar; label/header/card wrapper sesuai native.
Jumlah, panjang nama, bahan per tahap dan kondisi data tetap mengubah tinggi
kartu setelah data; bukan pixel parity. Placeholder tidak menebak baris bahan
atau kondisi. Slot Detail memakai tombol disabled + alasan selama loading,
sedangkan data native menjadi anchor dengan panah. Tidak mengganti anchor nyata
menjadi tombol.

Status/retry/help setelah daftar tetap tambahan shell existing; help cetak
hidden oleh controller setelah sukses, status menjadi daftar selesai dibaca.
Jika integrator ingin menyamakan juga footer/final empty persis, perlu review
controller presentasi terpisah: empty response native berisi blok kosong, tetapi
controller existing menggantinya dengan clone kartu placeholder dan pesan
filtered/unfiltered. Patch ini mempertahankan selectors/semantics itu dan tidak
mengklaim empty-result final sudah sama persis native. Tidak menyentuh writer
atau controller transaksi/perizinan.

5 pure render tests lulus: kontrol sama native dengan/tanpa status/cari,
no-H1/region, urutan, header/card asli, data tidak dibuat, selectors controller
utuh. Test memakai tiny base tanpa sesi/DB; belum browser/390/keyboard/PWA atau
runtime izin. Tidak ada PG/listener/remote/CI/deploy atau global GO.
