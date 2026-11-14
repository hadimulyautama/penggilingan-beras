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
