# Detail riwayat pengeringan

Riwayat pengeringan yang sudah selesai pendinginannya memakai template khusus
`riwayat_pengeringan_detail.html`. Empat tab tetap Ringkasan, Bahan,
Pengukuran dan Riwayat, menggunakan kelas visual riwayat bersama `.rhs`.
Pendinginan aktif memakai template `detail_pendinginan_aktif.html` dengan kontrol bersama dan alur transaksi semula.

Route hanya mengganti nama template. Konteks asli, izin, cakupan lokasi,
pengalihan fase aktif, API, perhitungan, PDF, dan mutasi tidak diubah.
Panel Bahan, Pengukuran serta Riwayat disalin utuh; blok Waktu pendinginan
dipindahkan dari ringkasan ke Riwayat tanpa mengubah nilai atau labelnya.
Ringkasan memperjelas identitas/status, bahan basah, alat tes terakhir,
lokasi gabah, bobot estimasi/terukur dan tindakan sesuai keadaan asli.

Komponen bobot bersama tetap membedakan bobot basah, estimasi awal dan
hasil flowing scale, termasuk catatan sumber gabungan. Tombol Catat hasil
timbang flowing scale tetap mengikuti izin dan tahap silo. Pencatatannya
membuka formulir asli dengan referensi, alasan, konfirmasi seluruh lot,
pratinjau, pemeriksaan status dan penyimpanan yang sama. Tidak mengubah
penerimaan, stok atau lokasi gabah.

Makro tindakan dan pantauan asli, QC gabah asal, seluruh bacaan, putaran
pendinginan, riwayat jeda, catatan, paginasi serta PDF dipertahankan. Nilai
alat tes dan indikator mesin beserta waktunya tidak saling menggantikan.
Data lama yang tidak lengkap tetap diberi keterangan.

Tab lokal memakai node panel yang sama. Tautan GET/query/hash lama tetap
tersedia sebagai fallback. Skrip menyesuaikan tab pada tautan paginasi dan
tindakan ke panel asalnya, agar query dari halaman awal tidak membuka panel
lain setelah berpindah tab. Konteks kembali kerja dan semua parameter lain
tetap dipertahankan. Panduan memakai komponen bersama dan navigasi induk
Laporan & Riwayat tersedia melalui menu dengan node/tautan aslinya.

Print detail menampilkan seluruh panel. Pengujian memakai browser dan
PostgreSQL lokal, formulir/API asli, desktop serta ponsel, sumber dan QC,
paginasi lintas tab, pintu tindakan, kondisi sebelum/sesudah pindah ke silo,
catatan flowing scale, PDF, hash/fallback, print dan peralihan fase aktif.
