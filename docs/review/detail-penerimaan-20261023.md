# Detail penerimaan Barang Masuk

Baseline main 70fa58d. Acuan susunan: bagian USULAN detail-penerimaan-desktop.html dan detail-penerimaan-ponsel.html tanggal 20 Oktober. Data contoh dan kontrol simulasi tidak dibawa ke aplikasi.

## Inventaris dan pemetaan

| Informasi/tindakan lama | Lokasi baru | Sumber tetap |
|---|---|---|
| Jenis/kode tiket, pihak, pemilik pabrik/jasa/campuran | Kepala, Ringkasan, Lokasi & riwayat | tiket dan catatan riwayat; pemilik_penerimaan dihitung pembaca lama dari relasi jasa |
| Bobot diterima dan keterangan belum final/lengkap/diukur | Kepala, Tiket & bobot | bobot_diterima(catatan), tetap mengecualikan ditolak dan tidak menjumlah sebagian |
| Bobot tiket yang belum diterima | Kepala dengan label Bobot tiket saat ini dan penegasan belum menjadi stok | ambil_tiket/SQL_BERAT_TIKET lama, termasuk nota/perkiraan/timbangan |
| Armada/sopir, gudang | Ringkasan, identitas tiket | metadata tiket dan pengelompokan gudang yang sudah dipakai gerbang |
| Tiket terbuka / ditutup paksa beserta alasan | Peringatan di atas tab dan rincian timbang | status asli, tutup_paksa_alasan |
| Tindakan penerimaan gabah dan daftar tujuan langsung, alasan tujuan terkunci | Paling atas Ringkasan | menunggu dari svc.untuk/bagi; b.tombol/post/data/mati/utama persis lama; handler aksi.js sama |
| Form PK luar, jenis, jumlah/ukuran karung, tombol Tolak PK di dalam form | Tindakan Ringkasan membuka formulir lama | b.pilihan/aksi dengan dasar_borang; katalog/endpoint/validasi asli |
| Beras/broken dan informasi operator G2 | Tindakan Ringkasan; kartu informasi untuk yang tidak berhak mencatat | menunggu/izin asli, tidak menambahkan pilihan produk/tujuan/QC |
| Fakta, nota, catatan dan rincian anak kartu lama | Keterangan penerimaan yang dapat dibuka pada Tindakan | macro benda.penuh(ringkas=True) dan penuh_anak asli |
| Semua catatan sumber, kode, bobot, sumber, status, pemilik, waktu/pencatat | Lokasi & riwayat | seluruh catatan; tidak memakai hanya baris pertama atau saldo tersisa |
| QC gabah dua bacaan, biji hijau, densiti, lamur, jumlah pemeriksaan | QC; status ringkas di Ringkasan | hasil_qc, putaran terbaru dan seluruh sebelumnya, fallback catatan lama |
| QC PK parameter kuantitatif/kualitatif, lab, waktu/pencatat/riwayat | QC | hasil_qc dan helper rincian_kualitatif asli; tidak memakai QC proses |
| QC tidak tersedia / belum diperiksa | QC dan Ringkasan | kondisi data asli, tidak mengarang kelas/nilai |
| Kedua timbang, waktu/petugas | Tiket & bobot | rincian_timbang lama, tanpa hitung ulang |
| Bruto, tara truk, netto, karung, total tara, tara lain, berat barang/acuan, selisih/batas/status kontrol | Rincian timbang lengkap yang dapat dibuka | nilai asli Pos Timbang; format tampilan saja |
| Muatan, mutu/merek/kemasan/ukuran, nota, tara per karung, catatan | Tiket & bobot | seluruh timbang.muatan |
| Total partai, semua penimbangan, urutan, berat/waktu/petugas/catatan, penjelasan data lama | Tiket & bobot | timbang.penimbangan; PARTAI tidak ditampilkan sebagai pasangan timbang truk |
| Lokasi, proses, penerimaan PK, pemindahan, tautan Stok menurut pemilik | Lokasi & riwayat; ringkasan lokasi di Ringkasan | rincian_lokasi asli, relasi sumber, tidak menebak dari nama mesin/silo |
| Buka Pekerjaan dan jalur tindak lanjut | Tindakan setelah diterima serta Lokasi & riwayat | alamat lama; tidak menawarkan penerimaan ulang |
| Kembali, parameter buka/nilai, konteks/filter/halaman daftar | Tombol kembali, tautan tab/aksi, URL refresh | konteks_aman lama; tab_href membawa query asli; dasar_borang lama |

## Batas implementasi

Template layar khusus aplikasi dan lima partial, CSS/JS khusus detail. Controller hanya menambah pilihan tab dan pembuat URL baca; gerbang gudang, pembaca data dan layanan transaksi tidak berubah. Tidak mengedit hmu_tampilan/hmu_identitas, konfigurasi, menu, model, API, aturan QC/tujuan, stok atau rumus.

Tindakan ditampilkan langsung dari objek yang sudah diotorisasi, tanpa tabel daftar yang berulang pada detail. Semua payload, status disabled, dan tautan formulir dibandingkan dengan render template lama pada fixture sama. Teks petunjuk PK menjelaskan karung surat jalan dan QC terpisah, tanpa mengubah isian atau validasi. Dialog native tetap di luar panel; tab mengganti visibilitas tanpa membongkar isian. Handler lokal diberi guard; hashchange memakai PINDAH.pasang.

## Pemeriksaan

- 79 regresi asli penerimaan/konsolidasi/tiket/stok/QC/jenis tidak dikenal lulus sebelum perapian tindakan final; seluruh suite PG final dijalankan lagi. Termasuk lima jenis × pabrik/titipan, stok 9.800 kg, penerimaan ulang, tujuan tidak sah, izin G1/G2/admin/superadmin/lihat sebagai, tiket terbuka, QC dinonaktifkan, penolakan/ditutup paksa, perubahan pihak tiket, QC gabah/PK baru/lama dan partai lama.
- 13 kasus baru: sepuluh kombinasi jenis/pemilik dengan empat tab sebelum/sesudah, kesamaan payload dan tautan terhadap render lama, audit tidak bertambah karena GET, bobot/pemilik sumber tidak berubah; beberapa catatan campuran total 11.800 berbeda dari tiket 9.800; partai tiga titik total 600 tanpa pasangan timbang truk; jenis belum dipetakan tetap terbaca.
- 800 tes non-PG lulus. Suite PG penuh dan CI final dicatat pada laporan output setelah hasil akhir tersedia.
- Browser nyata lima lebar × empat tab: tanpa overflow, keyboard, hash lama, refresh. Form PK native mempertahankan jenis/karung saat panel berganti, skrip diulang tidak menggandakan handler, klik ganda satu POST, refresh setelah diterima tidak menawarkan pencatatan ulang.
- Bukti screenshot lengkap semua tab/jenis/kepemilikan sebelum dan sesudah; QC sebelumnya serta rincian timbang dibuka sampai bawah. Tangkapan dari respons aplikasi dan data uji, bukan transaksi operasional.

## Belum diverifikasi dan rollback

Perangkat fisik/Safari/Firefox/pembaca layar belum diuji. Tidak menjalankan transaksi pada data produksi. Cakupan stok/akses mengikuti skenario uji yang disebut, tidak mengklaim seluruh kemungkinan data historis diuji satu per satu. Tidak ada migrasi. Bila perlu rollback, revert commit penyajian melalui commit baru; tidak perlu mengubah transaksi atau stok.
