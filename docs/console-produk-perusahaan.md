# Aktivasi produk dan akses perusahaan

Console → Perusahaan → Produk & integrasi mengatur PadiFlow dan TeraFlow secara terpisah. Integrasi hanya dapat diaktifkan jika kedua produk aktif. Hak produk pengguna dikelola dari keanggotaan perusahaan → Hak produk, dengan peran Operator atau Admin untuk masing-masing produk. Semua perubahan membutuhkan pratinjau, alasan dan konfirmasi; penyimpanan menghasilkan audit sebelum/sesudah.

Menonaktifkan produk menolak login dan sesi yang sudah terbuka pada permintaan berikutnya. Izin pengguna tetap tersimpan untuk dipulihkan setelah aktivasi. Akun Admin Sistem tetap dapat masuk langsung ke Console untuk memulihkan konfigurasi, sekalipun PadiFlow dinonaktifkan. Peran platform tidak dapat diberikan melalui formulir hak produk.

Migrasi 0133 hanya menambah tiga tabel metadata. Perusahaan lama yang cocok pada kedua penetapan `organisasi_perusahaan_lama` dan `ruang_data_perusahaan` menerima kedua produk dan integrasi dengan kompatibilitas akses lama. Override pengguna yang nonaktif selalu menolak akses. Perusahaan baru tidak mendapat aktivasi atau akses implisit. Pengguna lintas perusahaan selalu memerlukan izin produk eksplisit, sehingga peran master dari perusahaan lain tidak diwariskan. Hak lokasi/gudang tetap mengikuti fondasi keanggotaan yang tersedia; produk bukan pemilih koneksi atau penyedia ruang operasional baru.

Tidak ada penulisan ulang stok, tiket timbang, proses, alokasi, pengiriman, atau transaksi historis. Pembaca transaksi lama tetap dipertahankan. Ruang operasional terpisah tetap harus disediakan dan diikat melalui konfigurasi server; aktivasi produk di registry tidak mencampurkan data perusahaan lain ke ruang HMU.

## Verifikasi dan urutan rilis

Jalankan workflow uji PadiFlow dengan `cakupan=semua`, workflow TeraFlow dengan revisi PadiFlow pasangan, dan Console Center Chromium/WebKit. Migrasi PadiFlow harus terpasang sebelum gerbang TeraFlow yang membaca tabel baru, kemudian antarmuka Console. Jangan menonaktifkan produk selama rollout parsial.

Pengujian khusus: `tests/pg/test_console_produk.py` meliputi empat kombinasi produk, izin berbeda, pencabutan sesi, API langsung, bukti pratinjau kadaluarsa, Console tetap terbuka, isolasi perusahaan, migrasi perusahaan warisan dan fingerprint transaksi. TeraFlow `tests/pg/test_produk_terpisah.py` meliputi sesi lama, peran master tidak berubah dan integrasi opsional. Website `tests/test_console_products.py` memeriksa pratinjau tanpa tulis, CSRF, draft dan layar 320/390/1440 dua bahasa.

Jika perlu rollback kode, pertahankan metadata dan audit; downgrade migrasi menolak menghapus metadata produk yang sudah digunakan. Jangan menghapus atau mengembalikan transaksi bisnis sebagai bagian rilis akses produk.

## Audit alur perusahaan satu produk

Direktori, statistik identitas, diagnosis dan pemulihan akun memeriksa keanggotaan pada perusahaan ruang operasional. Akun hanya milik perusahaan lain tidak tampil sebagai akun lokal dan tidak dapat diaktifkan/dipulihkan dari konteks yang salah. Anggota nonaktif tetap dapat didiagnosis; akun tanpa anggota hanya mengikuti kompatibilitas ruang warisan terverifikasi. Kredensial platform tetap dikelola sebagai akun sistem.

Diagnosis profil TeraFlow lama memakai grant produk dan status pengguna terbaru, termasuk saat objek ORM pernah dimuat. Produk yang tidak digunakan, perusahaan nonaktif, akun nonaktif dan izin produk yang belum aktif ditampilkan sebagai keadaan yang berbeda. Filter monitoring produk yang sudah tidak aktif dapat dihapus tanpa mengganti perusahaan/periode.

Sesudah pemulihan sandi, tautan masuk hanya menuju produk yang diaktifkan dan diizinkan bagi pengguna tersebut. Akun platform dapat kembali ke login langsung Console; origin eksternal harus berupa HTTPS yang valid tanpa userinfo, path tambahan, query atau fragment. Jika tak ada tujuan yang sesuai, pengguna diminta menghubungi Admin Sistem. Reset sandi tidak menambah hak atau mengaktifkan produk.

TeraFlow tetap mengaudit semua penolakan login. Penolakan izin setelah sandi yang benar tidak ditambahkan ke hitungan sandi salah, agar pemulihan produk/izin lewat Console tidak meninggalkan penahanan login. Penebakan sandi tetap dibatasi dengan aturan nama+IP yang sama.

Pengujian memakai PostgreSQL loopback dan data fiktif: perusahaan nonwarisan PadiFlow saja/TeraFlow saja, akun perusahaan lain, cap/pratinjau lama setelah perubahan keanggotaan, grant nonaktif, status cache, origin tidak valid, dan pemulihan sesi tanpa perubahan peran master. Tidak ada migrasi atau backfill transaksi pada audit ini.


### Pencabutan keanggotaan pada akses kompatibilitas

Keanggotaan perusahaan yang dinonaktifkan menolak akses kedua produk,
termasuk akun lama yang belum memiliki override produk. Pemeriksaan sesi,
diagnosis Console dan tujuan login setelah pemulihan sandi memakai kebijakan
bersama yang sama. Keanggotaan dibaca ulang; cache ORM tidak boleh menunda
pencabutan. Akun platform tetap memakai kewenangan platform, dan akun lama
yang belum mempunyai penetapan anggota tetap mengikuti kompatibilitas HMU.

Mengaktifkan kembali keanggotaan melalui pratinjau/audit Console memulihkan
izin tersimpan, tanpa menambah grant atau mengubah peran master. Tidak ada
migrasi, perubahan keanggotaan otomatis, atau penulisan transaksi produksi.
Uji mencakup pencabutan melalui API Console, cookie PadiFlow/TeraFlow lama,
diagnosis, pemulihan, serta keanggotaan yang dicabut pada sesi ORM lain.


### Pengguna beberapa perusahaan dan pratinjau hak produk

Izin eksplisit disimpan per perusahaan dan produk. Pengguna yang mempunyai
keanggotaan lain (termasuk nonaktif) tidak memakai fallback warisan; Console
menawarkan Operator, Admin, atau Tanpa akses, dan server menolak payload
warisan lama tanpa menghapus grant yang ada. Tidak ada perubahan izin otomatis.

Bukti pratinjau menyertakan kelayakan warisan, peran master dan status pengguna.
Perubahan konteks tersebut mewajibkan pratinjau baru. Writer anggota dan izin
produk memakai urutan kunci perusahaan -> pengguna -> anggota agar perubahan
bersamaan dari perusahaan berbeda tidak menghilangkan akses yang sah.
Seluruh pilihan produk divalidasi sebelum satu grant ORM pun diubah.

Uji mencakup satu pengguna dengan peran produk berbeda pada dua perusahaan,
penolakan payload lama, pratinjau usang, perubahan bersamaan, serta pencabutan
keanggotaan/produk di satu perusahaan tanpa mengubah izin perusahaan lain atau
transaksi bisnis. Tidak ada migrasi, backfill, atau koreksi transaksi produksi.


Penambahan keanggotaan perusahaan kedua ditolak bila masih ada izin warisan
yang sedang berlaku melalui keanggotaan asal. Pesan menyebut perusahaan dan
produk yang perlu ditetapkan eksplisit terlebih dahulu. Setelah penetapan
eksplisit disimpan, penugasan kedua dapat dilanjutkan; operator asal tetap
diizinkan dan perusahaan baru tidak mendapat izin produk otomatis.


### Konteks pemulihan akun lintas perusahaan

Pratinjau pemulihan sandi, pengakhiran sesi dan aktivasi akun bersama
menyertakan seluruh keanggotaan serta izin produk pengguna. Penambahan,
pencabutan atau perubahan izin pada perusahaan lain mewajibkan pratinjau baru
sebelum tindakan global diterapkan. Tidak ada izin yang disalin atau
dipulihkan otomatis. Akun portal/profil tanpa pengguna bersama tetap lokal.

Aktivasi satu keanggotaan dan pembukaan penahanan tetap terikat perusahaan
asal; perubahan izin perusahaan lain tidak menghambat bantuan lokal ini.
Halaman pemulihan publik hanya menerima identitas tampilan yang sudah ada,
tanpa daftar keanggotaan/perizinan perusahaan lain. Cap yang sudah diterbitkan
tetap sekali pakai; mengganti sandi tidak mengaktifkan kembali izin produk
yang dicabut sesudah cap diterbitkan. Tidak ada migrasi atau backfill.

Audit umum menyimpan identitas lokal dan sidik cakupan; nama, keanggotaan dan
izin perusahaan lain hanya tersedia dalam pratinjau Console Sistem.
