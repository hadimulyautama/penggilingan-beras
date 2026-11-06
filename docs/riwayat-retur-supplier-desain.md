# Detail riwayat retur ke supplier

Detail `/riwayat-retur-supplier/{id}` mengikuti pola detail riwayat proses
untuk desktop dan ponsel: judul, kode, supplier, waktu, status, penerimaan,
tombol operasional, panduan bersama dan empat tab bergaris bawah. Seluruh
informasi memakai konteks server asli, bukan data contoh mockup.

Kartu sumber yang semula di kolom kanan dipindahkan utuh ke Ringkasan.
Kartu tiket terkini dipindahkan utuh ke Timbang & verifikasi, terpisah dari
rekaman pemeriksaan historis. Kartu, kondisi, fakta dan rincian asli tidak
ditulis ulang: setiap barang dan satuan, empat jumlah, total, catatan,
pencatat, waktu, verifikasi, tara, audit tiket yang diizinkan, snapshot stok,
alokasi, karung, perubahan pasca-keluar, audit sebelum/sesudah, dokumen dan
tautan sumber tetap tersedia. Data lama yang tidak lengkap tetap ditandai.

Ringkasan tambahan membedakan total diajukan, keluar awal dan keluar efektif
dari nilai server yang sama. Aktual dimuat tetap terlihat per barang dan
pada total aslinya. Tidak ada penghitungan stok atau jumlah baru di browser.

Panduan memakai `_panduan.html` dan `panduan.css` bersama. Menu dokumen
menampung tautan mutasi stok, tiket TeraFlow, penerimaan asal, jejak dokumen
serta navigasi induk Laporan & Riwayat. Navigasi induk dipindahkan sebagai
node asli; izin dan konteks tautannya tetap. Tanpa JavaScript navigasi induk
dan semua tautan tab server tetap dapat digunakan.

Nama, jumlah dan jalur empat tab tetap: Ringkasan, Timbang & verifikasi,
Stok, Jejak & dokumen. Pergantian tab tetap GET/PINDAH dan mempertahankan
parameter pencarian, filter penerimaan, halaman serta URL yang dapat dimuat
ulang. Tautan `#catatan-keluar` tetap menuju snapshot historis yang benar.

Koreksi pencatatan, pembatalan setelah keluar, lanjut pengajuan/pemeriksaan,
hasil tindakan dan penyelesaian tetap membuka formulir atau halaman asli
dengan kondisi dan izin yang sama. Formulir jumlah/keterangan, verifikasi
manual, alasan, konfirmasi, idempotensi, versi dasar, pemeriksaan tiket,
saldo dan alokasi tetap milik layanan serta renderer yang sudah ada.

Pembatalan administratif tidak menambah stok. Snapshot awal tidak diganti
oleh koreksi atau tiket terkini. Tidak ditambahkan PDF, bukti supplier
menerima barang, mutasi, skema, rumus atau hak akses baru. Halaman daftar
riwayat dan halaman operasional retur lainnya tidak diubah.

Verifikasi lokal:

- Lima uji browser dengan FastAPI dan PostgreSQL: desktop 1440 px dan
  ponsel 390/320 px; seluruh tab, rincian dua barang, tara, panduan, navigasi
  keyboard, konteks filter, snapshot, tautan hash, formulir asli, tiket
  berubah, data lama tidak lengkap, perubahan pasca-keluar dan pembatalan.
- Suite regresi riwayat retur, koreksi, peran/gudang, sidebar dan paket.
- Perbandingan sumber membuktikan seluruh kartu serta ekspresi fakta lama
  tetap identik; endpoint, layanan, macro perubahan dan formulir tidak diubah.
