# Daftar riwayat retur ke supplier

Halaman daftar memakai kerangka Riwayat proses yang sama dengan pengeringan,
giling, sosoh dan transfer. Tiga titik ekstensi kosong ditambahkan untuk
kontrol tambahan, isi panduan dan skrip khusus; keluaran empat daftar lama
serta portal tidak diganti. Panduan/filter memakai kerangka dialog bersama.

Desktop menempatkan Filter sejajar dengan field Cari dan tombol Cari.
Ponsel menempatkan Filter di kanan atas. Satu form GET asli dipertahankan:
JavaScript memindahkan node details filter ke dialog dan memberi form=rrs-form
pada kontrol aslinya. Tidak ada duplikasi field. Browser tetap mengirim q,
awal, akhir, status, supplier, gudang dan penerimaan bersama, termasuk ketika
Cari/Enter dipakai. Menutup panel mempertahankan isian. Tanpa skrip khusus,
details tetap berada di form asal dan masih dapat dipakai.

Tabel desktop, kartu ponsel, seluruh field filter, opsi, tautan penerimaan,
detail beserta query, pagination dan reset tetap memakai markup asli.
Rekap hanya ditata menjadi tiga nilai yang sama: jumlah retur, barang keluar
tercatat dan jumlah catatan keluar. Rekap tetap menghitung seluruh hasil
filter, bukan hanya halaman yang terlihat. Snapshot tidak lengkap tetap
memberi total parsial dan peringatan. Gagal membaca tiket, galat muat,
rentang tidak sah dan hasil kosong tetap ditampilkan oleh server.

Tidak ada hitungan domain atau query baru pada JavaScript. Dua belas status,
null yang tidak dianggap nol, jumlah diajukan/aktual/keluar efektif, versi
terkini, pembatalan administratif dan cakupan gudang/penerimaan tetap dibaca
layanan asli. Ukuran halaman tetap 20. Atur ulang filter tetap mempertahankan
batas penerimaan sampai pengguna memilih melihat semua penerimaan yang
berhak dibaca. Detail riwayat, tindakan, layanan, endpoint dan migrasi utuh.

Validasi browser memakai tests/pg/test_daftar_retur_supplier_desain_browser.py
dengan UJI_BROWSER_DAFTAR_RETUR_SUPPLIER=1, lebar 1440/390/320, form ownership,
draf, lima filter, pencarian dengan Enter, context round-trip detail, rekap
lintas halaman, reset dengan penerimaan, galat tanggal, Print sekali, panduan
dan fallback tanpa skrip. Suite browser daftar proses sebelumnya juga
berjalan untuk menguji kompatibilitas kerangka. Suite HTTP/domain retur,
koreksi, navigasi dan paket berjalan pada PostgreSQL lokal terisolasi.
Perubahan ini belum otomatis diterbitkan ke produksi.
