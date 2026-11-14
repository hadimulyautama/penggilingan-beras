# Login langsung Console

Console menampilkan username dan sandi pada origin Railway sendiri. Server Console
mengirimnya melalui HTTPS ke `/internal/console/masuk`; browser tidak berpindah ke
PadiFlow dan tidak menerima bearer melalui JavaScript. Tidak ada kredensial baru
atau salinan hash sandi di Console.

API memerlukan `X-Console-Login-Key` dari server. `CONSOLE_LOGIN_SECRET` merupakan
kunci acak khusus klien ini (minimal 32 karakter), sama pada PadiFlow dan Console;
berbeda dari kunci cookie dan sandi akun. Masukkan melalui stdin/secret manager,
jangan mencetak atau menyimpan nilainya dalam source. Konfigurasi kosong menutup
endpoint; kunci salah ditolak sebelum badan permintaan divalidasi. Validasi login
tidak menyertakan input/sandi dalam respons galat.

Pemeriksa `hmu_identitas.masuk.periksa_kredensial` tetap menentukan kecocokan dan
status akun/orang. Hanya Super Admin aktif tanpa kewajiban mengganti sandi yang
mendapat sesi Console. Hash/versi/username diperiksa lagi setelah akun dikunci,
supaya reset sandi yang bersamaan tidak memberikan sesi dengan sandi lama.
Sesi memakai model `hmu_console_sessions` dan fungsi penerbitan/penukaran lama:
umur satu jam, pencabutan/versi/peran/status diperiksa setiap permintaan.
Cookie aplikasi harian dan hak pengguna tidak diubah.

Penahanan lima kesalahan per akun+sumber memakai gerbang masuk yang sudah ada,
dengan namespace Console terpisah. Pembukaan penahanan tersimpan tetap mengikuti
generasi layanan monitoring. Selain itu, pembatas Console membatasi tiga proses
verifikasi serentak dan 20 permintaan per sumber per menit; penyimpanan jejak
dibatasi 2.048 sumber. Jejak alamat dibuat HMAC oleh BFF dari X-Real-IP Railway,
bukan alamat mentah atau pilihan browser. Header itu hanya dipercaya pada ingress
Railway; pengembangan lokal memakai alamat koneksi. Ini melindungi kapasitas
operator dari pintu login baru.

BFF memerlukan CSRF sebelum login (cookie bertanda, HttpOnly, Strict, sepuluh
menit), Origin yang cocok, dan penolakan cross-site. Referrer-Policy halaman
formulir same-origin menjaga Origin POST browser. Setelah gagal, username tetap
ada dan sandi kosong. Setelah berhasil, cookie sesi/CSRF dirotasi; nonce masuk
dihapus. Password tidak ditaruh di URL, cookie, cache, storage browser, atau log.
SSO/callback lama dipertahankan untuk sesi yang sudah berjalan, tetapi bukan
jalur tombol masuk baru.

## Rilis

1. Uji unit, PostgreSQL, race reset, peran/status, redaksi, CSRF dan browser.
2. Tetapkan kunci klien pada kedua layanan melalui stdin dengan skip-deploy.
3. Deploy backend terlebih dahulu, tunggu SUCCESS dan periksa health/commit.
4. Deploy Console sesudah backend siap; periksa form dan versi pada HTTPS.
5. Jangan mencoba kredensial akun produksi untuk smoke test. Login benar/salah,
   metadata sesi, pembatasan dan invariansi transaksi diverifikasi pada data uji.

Tidak ada migrasi atau seed. Login sah memperbarui waktu masuk akun dan metadata
sesi saja. Bila perlu rollback, kembalikan frontend Console ke rilis SSO yang
sehat dahulu, baru backend; sesi aplikasi harian tidak perlu diubah.

Uji: `tests/pg/test_console_masuk_langsung.py`, `tests/test_console_pembatas.py`,
`tests/pg/test_console_akses.py`, dan integrasi HTTP/browser
`tests/pg/test_console_website_integrasi.py` dengan interpreter website terpisah.
