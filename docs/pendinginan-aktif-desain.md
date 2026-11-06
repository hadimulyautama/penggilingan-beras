# Pendinginan aktif

Detail pendinginan aktif memakai empat tab Ringkasan, Bahan, Pengukuran dan
Riwayat sesuai desain riwayat pengeringan. Tombol Nyatakan sudah dingin
ditempatkan dekat status, menggunakan makro dan tindakan katalog asli.
Deskripsi tindakan, konteks lot, parameter kembali kerja, izin dan endpoint
penyimpanan tetap sama. Tidak ada status dingin otomatis berdasarkan waktu.

Panel Bahan, Pengukuran dan Riwayat disalin identik dari detail yang sudah
mempertahankan data pendinginan. Makro bobot, QC asal, pengukuran, waktu,
putaran dan jeda/paginasi tetap asli. Waktu pendinginan sekarang berada di
Riwayat. Bobot basah dan estimasi tidak dianggap sebagai saldo kering terukur.
Alat tes dan indikator mesin tetap merupakan hasil pengeringan, bukan suhu
atau kemajuan pendinginan.

Skrip kontrol bersama riwayat pengeringan ditambah selector root
pendinginan aktif dan penjaga konteks tab untuk tombol di header. Tab, hash,
keyboard, paginasi, panduan dan print tetap memakai kontrol yang sama. Setelah dinyatakan dingin, route aktif tetap beralih ke
riwayat pengeringan melalui alur yang sama. Gabah tetap di dryer; Pindah ke
silo dan Dinginkan lagi menjadi tindakan berikutnya sesuai kondisi asli.
PDF tetap baru tersedia setelah pendinginan selesai.

Tidak ada perubahan layanan, model, skema, formula, API atau handler mutasi.
Pengujian browser memakai formulir asli, memeriksa pembacaan tanpa mutasi,
paginasi dari tab berbeda, penutupan formulir, simpan hanya sekali,
peralihan ke riwayat, silo tetap kosong, PDF, keyboard, hash, fallback GET,
print dan akses operator Gudang 1/penolakan Gudang 2.
