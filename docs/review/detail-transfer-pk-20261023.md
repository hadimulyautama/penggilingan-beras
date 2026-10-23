# Inventaris detail transfer PK — 23 Oktober 2026

Inventaris ini disusun sebelum perubahan tampilan.

## Sumber dan batas

- Detail lama `/riwayat-transfer/{id}` membaca KartuTransfer (kode, proses asal, pemilik/jasa, bobot catatan, tujuan master, waktu dan status termasuk dibatalkan). Admin dan operator Gudang1 memakai `_is_g1_operator`; G2 tidak memperoleh riwayat penuh.
- Koreksi POST lama: CSRF, bobot dasar, angka nonnegatif, alasan, penjaga hilir, rollback, pengulangan pemeriksaan setelah gagal, isian tetap ada, pesan berhasil, link pengganti dari respons lama. Formulir dan endpoint dipertahankan.
- PermintaanPk: diminta/disetujui/dikirim/selesai/ditolak/gugur, empat bobot terpisah, waktu dan aktor masing-masing tahap, tujuan dan silo master, sebab serta internal_transfer_id. Data lama boleh tidak mempunyai bobot permintaan.
- Katalog actions_menu menentukan izin formulir; layanan minta/setujui/kirim/tutup_admin/tolak dan seluruh endpoint lama tetap menjadi pelaksana. Pengiriman memindahkan stok sekali, bukan persetujuan/penutupan.
- Transfer langsung memakai create_internal_transfer dan arti bobot kosong tetap seluruh saldo tersedia. Operator tidak memperoleh hak transfer langsung.
- Saldo bersumber dari helper yang sama (hasil terverifikasi/hasil kumulatif terakhir, retur relevan, transfer terkirim, barang keluar). Bobot historis catatan berbeda dari saldo sekarang.
- Audit ActivityLog dan Peristiwa menyimpan pembatalan/alasan. Tidak semua data mempunyai foreign key dari transfer pengganti ke asal. Hubungan yang tidak tersimpan tidak boleh ditebak berdasarkan waktu/berat; catatan proses yang sama diberi label terkait, bukan dipastikan pengganti.
- Penjaga koreksi dan daftar catatan hilir lama tetap digunakan. Tutup dengan bobot sama tidak diberi penjaga koreksi baru.
- Tidak ada PDF detail transfer lama; tidak akan ditambahkan.

## Pemetaan tampilan

| Informasi/tindakan | Lokasi baru |
|---|---|
| Kode transfer/permintaan, kode giling, pemilik, jasa, dua status | Identitas tetap di atas empat tab |
| Tahap permintaan, bobot catatan, saldo saat ini, tindakan, asal/tujuan, empat bobot | Ringkasan |
| Sumber giling, komponen saldo dari helper, kepemilikan, jenis PK, tujuan master | Bahan & tujuan |
| Empat bobot, waktu/aktor, selisih final-muatan jika tersedia, status/sebab | Permintaan |
| Identitas lengkap, waktu/pencatat, audit/peristiwa, pembatalan, catatan terkait | Riwayat |
| Koreksi lama, bobot dasar, konfirmasi ulang dan isian gagal | Formulir lama pada rincian koreksi; diakses dari tindakan saat ini |
| Penghalang koreksi dan tautan catatan hilir | Tindakan saat ini dan Riwayat |
| Setujui/tolak/kirim/tutup | Formulir lama dengan konteks otomatis ID permintaan |
| Transfer tanpa permintaan | Empat tab tetap tersedia, penjelasan tidak ada permintaan tertaut |

Seluruh skenario dan checklist penerimaan akan dicatat setelah implementasi dan pengujian nyata. Status belum dinyatakan lulus pada tahap inventaris ini.

## Implementasi dan pemeriksaan awal

- URL lama riwayat dan POST koreksi dipertahankan; detail permintaan baru `/permintaan-pk/{id}` hanya diberikan kepada pembaca G1 yang berhak. G1 sebelum persetujuan tetap403; G2 tetap memantau lewat kartu lama dan ditolak dari detail penuh.
- Daftar tindakan memakai ID yang diizinkan actions_menu dan status permintaan asli. API serta layanan transaksi tidak diubah. Penutupan bobot sama tidak diberi penjaga koreksi baru.
- URL tab setelah POST gagal dinormalisasi ke URL detail GET; draft, bobot dasar, pemeriksaan ulang, CSRF dan konteks kembali tetap dipertahankan.
- Tautan detail ditambahkan pada kartu permintaan Pekerjaan yang sudah tersedia bagi pembaca tersebut, dengan template pewaris; paket tampilan dan menu utama tidak disunting.
- Empat tab desktop, dua baris dua kolom pada ponsel mengikuti container mockup. Tindakan utama, rute gudang dan empat bobot mengikuti urutan usulan. Tidak ada kontrol simulasi.
- Format bobot memakai helper presisi aplikasi; saldo memakai pending_transfer_kg dan komponen helper transfer asli. Status transfer yang dibatalkan berbeda dari status permintaan.
- Data yang tidak tertaut diberi label tidak ada permintaan tertaut. Catatan dari proses yang sama tidak dipastikan sebagai pengganti tanpa hubungan tersimpan. Pesan pengganti dari keberhasilan POST lama tetap tersedia.

## Bukti uji

-7 skenario integrasi baru: dua peran Admin/Super Admin menjalankan empat API lama; koreksi gagal dan nol; pagination; penghalang koreksi dan penutupan bobot sama; ditolak/gugur dan permintaan lama.
-82 tes regresi terarah lulus (riwayat, permintaan, empat tahap, koreksi, sesi, peristiwa dan neraca PK). Seluruh791 tes non-PostgreSQL lulus.
- Browser nyata menjalankan minta G2 → setujui Admin → kirim G1 → tutup Admin dengan tepat4 POST. Pilihan lot/permintaan otomatis dan tujuan master tetap memakai formulir generik asli.
- Uji angka: stok awal6000kg; diminta4400; disetujui5000 tidak memindahkan stok; muatan4600 membuat saldoG1=1400 danG2=4600; final4400 membatalkan transfer4600 dan membuat pengganti4400 sehinggaG1=1600 danG2=4400. Bobot muatan4600 tetap tersimpan. Muatan5001 di atas persetujuan ditolak. Pengiriman ulang ditolak.
- Koreksi nol membatalkan tanpa pengganti; koreksi gagal menyimpan draft dan tidak mengubah stok. Saat PK sudah dipoles, koreksi bobot ditolak tetapi penutupan dengan bobot sama6000 tetap berhasil tanpa transfer tambahan.
-40 kombinasi Admin/G1 × lima lebar320/390/768/1440/1920 × empat tab lulus tanpa overflow/ID ganda. Ukuran tab konsisten. Keyboard Home/ArrowRight, fragmen lama/pembukaan koreksi, dan8 perpindahan instan lulus.
- Galeri102 tangkapan penuh mencakup seluruh tab dan status diminta/disetujui/dikirim/selesai, catatan dibatalkan/pengganti, tanpa permintaan, ditolak/gugur, penghalang dan gagal koreksi.
- Lingkungan terisolasi PostgreSQL loopback uji_giling_detail/uji_giling_browser; tidak mengubah data operasional.

## Batas verifikasi

Hubungan asal–pengganti atau permintaan historis yang tidak pernah disimpan tidak direkonstruksi berdasarkan kemiripan waktu/berat. Data tersebut tetap dapat ditelusuri sebagai catatan proses yang sama dengan keterangan keterbatasan. Perangkat fisik Android/iOS, Safari/Firefox, dan pembaca layar belum diuji. Tidak ada PDF baru.

Hasil akhir suite penuh, checklist penerimaan per kelompok, CI/deploy dan tautan galeri dicatat pada output/detail-transfer-pk/laporan-pemeriksaan.md setelah selesai.

## Verifikasi final

Seluruh1344 tes PostgreSQL lulus (569,61 detik) dan791 tes non-PostgreSQL lulus: total2135. Tidak ada perubahan pada layanan transfer/permintaan, model, perhitungan produksi/stok, atau API tindakan.

Pergantian tab lokal mempertahankan DOM formulir yang sudah diotorisasi server, termasuk bobot dasar lama dan kewajiban pemeriksaan ulang, tanpa menyimpan draft lintas sesi. Browser membuktikan POST gagal422, lalu empat tab, nilai/alasan/baseline tetap utuh, checkbox pemeriksaan tetap wajib, dan koreksi sah dengan klik ganda menghasilkan satu POST. Semua pengiriman/penutupan/koreksi tetap melalui endpoint lama. Refresh/pagination tetap membaca server.

Koreksi lanjutan dari4400 ke4300 setelah permintaan selesai menghasilkan saldoG1=1700 danG2=4300. Bobot historis permintaan tetap diminta4400, disetujui5000, dimuat4600, final4400. Catatan4600 dan4400 dibatalkan; catatan4300 aktif. Tautan pengganti dari respons POST dapat dibuka. Tampilan efektif Admin sebagai operatorG2 ditolak403 dari detail, sebagai operatorG1 dapat membaca tanpa formulir koreksi.

### Checklist penerimaan (berdasarkan kode dan uji nyata)

- [x] Tampilan/kelengkapan: empat tab, identitas, dua status, legacy/permintaan kosong, desktop/ponsel; galeri lengkap serta uji40 kombinasi.
- [x] Permintaan/pengiriman: empat langkah asli, persetujuan tanpa perpindahan, penolakan/gugur bersebab, muatan kurang boleh/lebih ditolak, stok berpindah sekali dan dapat digunakan sebelum tutup. Tidak ada tahap penerimaan baru.
- [x] Bobot/penutupan: empat bobot terpisah, muatan tidak ditimpa, bobot sama tanpa transfer baru, bobot berbeda dengan pembatalan/pengganti, penutupan bobot sama saat koreksi terhalang, arti bobot kosong transfer langsung tetap layanan lama.
- [x] Koreksi/riwayat: asal dibatalkan tetap terbaca, pengganti tujuan sama, nol tanpa pengganti, alasan/baseline/periksa ulang dan rollback tetap lama, draft gagal utuh, penghalang berlink dan catatan terkait dapat dibuka, bobot historis tidak diubah.
- [x] Stok/kepemilikan: sumber helper produksi/retur/transfer/barang keluar tidak diganti, empat bobot bukan empat transaksi, transfer batal tidak dihitung aktif, saldo dua gudang konsisten, master/kapasitas/pemilik tetap dijaga; race/idempotensi memakai suite layanan asli.
- [x] Hak akses/navigasi: hak meminta/ACC/kirim/tutup/langsung/koreksi dipisah oleh katalog dan backend lama; gudang efektif, tiga peran, URL/API, konteks kembali, fragment, refresh/pagination/instant serta klik ganda diperiksa.
- [ ] Perangkat fisik Android/iOS, Safari/Firefox, pembaca layar dan seluruh variasi data operasional belum diuji; tidak dinyatakan lulus.

Hubungan historis asal–pengganti yang tidak tersimpan tetap diberi keterangan keterbatasan; tidak dibuat penghubung palsu.
