# Pencabutan akses dan isolasi metadata Console

Pemeriksaan sesi Console membaca ulang sesi, akun dan pengguna dari database,
termasuk ketika pemanggil memakai kembali AsyncSession yang sudah berisi objek
ORM. Status, peran, versi token, kewajiban mengganti sandi, waktu berlaku dan
pencabutan sesi tidak boleh diambil dari cache lama. Pembacaan otorisasi tidak
mem-flush draf transaksi yang kebetulan berada dalam sesi pemanggil.

Writer master organisasi memeriksa hak pengelola terkini dan mensyaratkan sesi
transaksi bersih. Company yang dikunci writer keanggotaan juga dibaca ulang.
Lokasi yang sudah ada menolak company_id yang berbeda; konteks perusahaan tidak
diam-diam diganti mengikuti ID lokasi yang dikirim.

Penetapan gudang lintas ruang data tetap ditolak. Endpoint pratinjau Console
mengembalikan 403, bukan exception tak tertangani; writer Console mempertahankan
penolakan tersebut. Halaman Console mempertahankan sesi Super Admin yang sah
serta menampilkan alasan ID/EN bila penetapan yang diminta berada di ruang lain.
Tidak ada pelonggaran otorisasi, login atau pencabutan sesi.

Pengujian memakai dua perusahaan dengan nama lokasi/gudang sama, akun yang
haknya dicabut pada koneksi kedua, serta token lama dan draf proses bisnis.
Admin perusahaan tidak memperoleh Console platform, termasuk pengguna berperan
Admin global. Pengaturan perusahaan sendiri tetap bekerja untuk cakupan sah dan
menolak perusahaan lain. Fingerprint dibandingkan untuk operasi yang ditolak.

Tidak ada migrasi, seed, koreksi historis, perubahan akun produksi atau transaksi
produksi. Paket hmu_core/hmu_identitas vendored tidak diubah. Jalankan seluruh CI
backend dan regresi Console Chromium/WebKit sebelum deploy. Rollback hanya kode;
tidak ada perubahan data yang harus dipulihkan. Uji fisik iPhone tidak dicakup.
