# Regresi alur Console

Pemulihan sandi menolak isian yang tidak valid tanpa memantulkan sandi, cap atau
field tambahan. Model sandi memakai SecretStr; galat validasi pada kedua API
pemulihan disajikan sebagai pesan teks netral yang tetap dibaca UI lama.

Pratinjau bantuan memeriksa seluruh keadaan keamanan akun (versi, status, peran,
identitas dan keanggotaan) tetapi tidak batal semata karena waktu login berubah.
Snapshot dari rilis sebelumnya tetap dapat dipakai dalam umur sepuluh menit
hanya bila hash aslinya utuh dan keadaan keamanan masih cocok. Aktivasi
keanggotaan mensyaratkan perusahaan aktif, dengan kunci induk sebelum akun/
anggota; diagnosis tidak menawarkan tindakan itu bila perusahaan nonaktif.

Calon Admin pertama dapat dicari menurut nama, username atau ID dan dipaginasi
30 hasil per halaman. Sumbernya akun masuk nyata yang aktif, tidak bergantung
pada penetapan ruang transaksi perusahaan. Endpoint tetap memerlukan bearer
Console Super Admin. Akun terpilih diambil tersendiri saat formulir gagal agar
pilihan di luar halaman awal tidak hilang. Pencarian teks diperlakukan literal.

Tidak ada migrasi, seed, backfill, perhitungan ulang stok, perubahan transaksi,
atau modifikasi paket vendored. Seluruh tindakan pemulihan saat pengujian hanya
pada akun fixture PostgreSQL lokal. Uji fingerprint memastikan metadata di luar
tindakan yang diizinkan tetap sama. Peran dan hak fungsi lain dipertahankan.

Validasi: test_console_regresi_alur.py, test_console_monitoring.py, akses dan
login Console, lalu CI lengkap backend serta integrasi Console Chromium/WebKit.
Deploy backend terlebih dahulu; frontend baru memerlukan API calon-admin.
Rollback frontend ke rilis sehat terlebih dahulu, baru backend bila perlu.
Jangan melakukan reset, reaktivasi atau pencabutan sesi akun produksi sebagai
smoke test; periksa health/commit dan gerbang anonim saja.


## Audit peta akses / pusat gangguan lintas perusahaan (15 November 2026)

- Peta dan diagnosis membaca status profil TeraFlow tertaut dengan fungsi yang sama. Profil lama yang namanya sama belum dianggap sebagai profil tertaut nonaktif: login bersama yang sah akan melakukan adopsi/sinkronisasi sesuai mekanisme TeraFlow. Pembacaan Console tidak menautkan atau mengaktifkan profil. Wajib ganti sandi juga dinyatakan konsisten.
- Pencarian ID staf menerima spasi di tepi dan seluruh rentang ID int32 yang sah tanpa mengeksekusi angka di luar rentang sebagai ID SQL.
- Respons kejadian mencantumkan company_id aktual dan respons identitas lokal mencantumkan akun_id. Website memverifikasi isi kartu dan kejadian terhadap konteks tab sebelum menyediakan tautan tindakan.
- Kolektor metadata di kedua aplikasi mencatat GET 401/403. GET normal dan jalur internal/monitoring/kesehatan/SSE tetap mengikuti pengecualian yang ada. Tidak menahan respons untuk menulis statistik. Tidak mengisi ulang kejadian lama atau mengubah transaksi.

Regresi mencakup matriks dua perusahaan dengan hak produk berbeda, pencabutan izin, sidik semua tabel saat pembacaan, pipeline GET ditolak ke pusat gangguan, kesamaan kebijakan peta/diagnosis, serta login TeraFlow pada profil lama nyata melalui interpreter terpisah. Tidak ada migrasi atau perubahan pada writer transaksi, kredensial, penetapan anggota maupun izin produk. Rollback dengan rilis kode sebelumnya.


## Pemulihan profil dan pergantian produk (15 November 2026)

Diagnosis, peta dan pusat gangguan mempertahankan produk melalui fragment
pemulihan. Petunjuk itu tidak memberikan izin. Tujuan masuk memakai hak terkini;
produk yang sudah dicabut tidak dialihkan ke produk lain. Cap tetap sekali
pakai dan hanya disimpan di memori browser setelah fragment dibersihkan.
Pemeriksaan awal bisa dicoba ulang setelah jaringan gagal/timeout. Kata sandi
tidak dikirim ulang otomatis; draf dijaga dan jawaban simpan yang hilang
dijelaskan tanpa mengulang perubahan server.

Profil TeraFlow tertaut yang nonaktif dapat dipulihkan melalui pratinjau dan
konfirmasi Super Admin. Perusahaan, produk, anggota dan peran produk harus masih
mengizinkan. Snapshot mencakup ID/status/versi profil, diperiksa ulang di bawah
kunci akun dan profil. Seluruh sesi lama akun bersama dicabut agar tidak hidup
lagi setelah aktivasi. Hak produk/perusahaan, sandi dan data bisnis tidak ditulis.
Pengujian dua skema memeriksa hak lintas perusahaan, penolakan setelah perubahan
izin/status, idempotensi dan fingerprint transaksi. Pengujian browser nyata
menggunakan PostgreSQL loopback uji, termasuk respons non-JSON, timeout,
penyimpanan sukses dengan balasan hilang, dan cap yang sudah terpakai.

Tidak ada migrasi, backfill atau pemulihan akun produksi. Rilis backend sebelum
Console. Rollback kode frontend lalu backend; tidak ada data yang perlu dibalik.
