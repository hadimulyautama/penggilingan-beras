# Checklist penerimaan Barang Masuk dan Pekerjaan

**Hasil lokal: 55/55 butir fungsi Lulus. Produksi 1.867 lulus, paket tampilan 391 lulus, audit khusus penerimaan/pembanding lokal 45 lulus; tanpa gagal/galat/dilewati. Belum dipush atau dideploy; menunggu tinjauan pengguna.** Seluruh pengujian menggunakan database lokal terisolasi; data operasional tidak diubah.

Setiap Lulus di bawah merujuk pengujian tertentu, bukan sekadar halaman dapat dibuka. Nama akun dipendekkan pada tabel: “Super Admin” adalah akun sintetis **Uji superadmin**, “Admin” adalah **Uji admin**, operator browser adalah **Uji operator** dengan gudang yang disebut. Elfira/Eka dan Uji adalah akun fixture pengujian, bukan tindakan akun operasional.

Pemetaan 28 konstruktor dan alamat kompatibel: [laporan implementasi](konsolidasi-masuk-pekerjaan.md).

## 1. Penerimaan lima jenis barang

| ID | Butir | Hasil | Akun | Tiket/proses | Bukti sebelum → sesudah | Rujukan |
|---|---|---|---|---|---|---|
| 1.1 | Gabah basah memakai fungsi lama | Lulus | Super Admin | TRX-391-GABAH_BASAH | 0 → 1 batch, 9.800 kg; pabrik ditumpuk, jasa masuk dryer seperti sebelumnya. | E1/E2 |
| 1.2 | Gabah kering memakai perlakuan lama | Lulus | Super Admin | TRX-391-GABAH_KERING | 0 → 1 batch, 9.800 kg; tujuan lama dan pemilik utuh. | E1/E2 |
| 1.3 | PK memakai perlakuan lama | Lulus | Super Admin | TRX-391-BERAS_PK | 0 → 1 PKB + 1 intake tumpukan G2; 9.800 kg; jenis KS. | E1/E2 |
| 1.4 | Beras memakai perlakuan lama | Lulus | Super Admin | TRX-391-BERAS_MASUK | 0 → 1 sumber stok Timbangan, 9.800 kg, Gudang 2 dan pemilik tepat. | E1/E2 |
| 1.5 | Broken memakai perlakuan lama | Lulus | Super Admin | TRX-391-BROKEN_MASUK | 0 → 1 sumber broken Timbangan, 9.800 kg; pemilik dipertahankan. | E1/E2 |
| 1.6 | Perbedaan alur antarjenis dipertahankan | Lulus | Empat peran | Kelima TRX-391-* | Kartu gabah tetap pilihan tujuan; PK tetap jenis PK dan tombol Tolak; beras/broken memakai penerimaan stok lama. Bukan formulir seragam. | E2/E4 |

## 2. Tiket timbang

| ID | Butir | Hasil | Akun | Tiket/proses | Bukti sebelum → sesudah | Rujukan |
|---|---|---|---|---|---|---|
| 2.1 | Tiket lama ditemukan di Barang Masuk | Lulus | Empat peran | Kelima TRX-391-* | Daftar menunggu lama dipartisi satu-ke-satu; penerimaan keluar dari Pekerjaan. | E2/E7 |
| 2.2 | Identitas, kendaraan, pihak dan bobot mengikuti Pos Timbang | Lulus | Empat peran | Kelima TRX-391-* · B 9911 XY | Seluruh atribut kartu sebelum–sesudah identik; 9.800 kg tetap berasal dari tiket. | E1/E2 |
| 2.3 | Barang masuk dan keluar tidak tercampur | Lulus | Super Admin | Kelima TRX-391-* diuji arah KELUAR | MASUK ditawarkan → setelah arah KELUAR tidak ada di Barang Masuk; detail masuk 404. | E7 |
| 2.4 | Status belum final jelas | Lulus | Super Admin | Kelima TRX-391-* berstatus TERBUKA | Belum final tetap berlabel; tidak berubah menjadi angka final. | E7 |
| 2.5 | Aturan penerimaan sebelum timbang akhir tetap | Lulus | Super Admin | Kelima TRX-391-* TERBUKA | Gabah/PK menerima bobot belum diketahui; beras/broken menolak jika belum ada bobot. Sama dengan aturan sumber lama. | E2/E7 |
| 2.6 | Pembaruan bobot sesudah pencatatan | Lulus | Operator Uji G1 | T-CATUR / T-WIDI | Perkiraan Catur 10.240 → 9.950 kg setelah timbang kedua sementara; total giling 20.880 → 20.590, tetap belum final. Rekonsiliasi final turut diuji. | E5/E7 |
| 2.7 | Tiket terpakai tidak menawarkan penerimaan ganda | Lulus | Super Admin | Kelima TRX-391-* pabrik/jasa | 0 → 1 sumber hidup; pengiriman ulang tetap 1; kartu berpindah ke Diterima. | E1/E8 |
| 2.8 | Penerimaan bertahap/pemecahan yang didukung | Lulus | Super Admin / Admin Elfira | TRX-391-* / LOT-UJI-01 | Alur tiket lama satu catatan hidup per tiket dan tidak menawarkan jumlah terima parsial. Ini tetap demikian. Pemecahan bahan/transfer 2.000 kg dari lot tetap diuji, tanpa menambah penerimaan tiket. | E1/E2/E7 |

## 3. Formulir dan pencatatan

| ID | Butir | Hasil | Akun | Tiket/proses | Bukti sebelum → sesudah | Rujukan |
|---|---|---|---|---|---|---|
| 3.1 | Semua kolom, pilihan, default dan tombol tetap ada | Lulus | Empat peran | Kelima TRX-391-* | Katalog formulir dan kartu identik terhadap snapshot lokal sebelum perubahan pada DB sama. | E2 |
| 3.2 | Tidak ada langkah atau kewajiban baru | Lulus | Empat peran | Kelima TRX-391-* | Endpoint/formulir yang sama; tidak menambah konfirmasi atau syarat timbang akhir. Perbaikan silo hanya memajukan pemeriksaan lama sebelum commit. | E1/E2/E6 |
| 3.3 | Validasi isian, tujuan, bobot, pemilik dan tiket | Lulus | Super Admin + dua operator | TRX-391-* / TRX-391-UJI-TUJUAN3 | Input tidak sah ditolak; silo tidak sah tidak lagi meninggalkan batch; gabah basah jasa tetap tidak boleh ditumpuk. | E6/E7 |
| 3.4 | Efek simpan dan penautan sama | Lulus | Super Admin | Kelima TRX-391-* pabrik/jasa | Sumber 0 → 1, 9.800 kg, lokasi dan jasa_id sesuai; audit tercatat. | E1/E8 |
| 3.5 | Batal formulir tidak mengubah data | Lulus | Super Admin | TRX-391-BERAS_PK/BERAS_MASUK/BROKEN_MASUK | 12 pembatalan: 99 tabel/141 baris identik; Lanjut isi menjaga nilai. | E3 |
| 3.6 | Gagal simpan tidak meninggalkan perubahan sebagian | Lulus | Super Admin | TRX-391-UJI-TUJUAN2 → TUJUAN3 | Sebelum perbaikan HTTP 400 tetapi batch 4 → 5 (Gagal); sesudah HTTP 400, batch 5 → 5 dan sumber tiket 0 (Lulus). Uji transaksi peristiwa/rollback juga tetap dijalankan. | E6/E7 |
| 3.7 | Klik Simpan berulang tidak menggandakan | Lulus | Super Admin | Kelima TRX-391-* | POST ulang dan klik ganda browser: tepat satu sumber hidup dan 9.800 kg per tiket. | E1/E8 |
| 3.8 | Tidak otomatis memulai proses baru | Lulus | Super Admin | Kelima TRX-391-* pabrik/jasa | Jumlah DryingLot, MillingProcess dan PolishingProcess sebelum–sesudah penerimaan sama; penempatan mengikuti fungsi lama. | E1 |

## 4. Riwayat dan keterhubungan

| ID | Butir | Hasil | Akun | Tiket/proses | Bukti sebelum → sesudah | Rujukan |
|---|---|---|---|---|---|---|
| 4.1 | Belum diterima/Diterima mengikuti pencatatan | Lulus | Super Admin | TRX-391-*; TRX-391-PANJANG-00..27 | Tiket berpindah daftar setelah tersimpan; 28 tiket panjang berpindah tanpa hilang. | E1/E9 |
| 4.2 | Filter kelima jenis tidak mencampur | Lulus | Super Admin | Kelima TRX-391-* | Saringan jenis menampilkan jenis terkait; saringan broken pada 28 penerimaan gabah memberikan keadaan kosong. | E7/E9 |
| 4.3 | Detail terkait tiket, barang, pemilik dan lokasi tepat | Lulus | Super Admin + operator sesuai gudang | Kelima TRX-391-* | Detail 200 dan tautan sumber 200/303; lintas gudang yang tidak berhak 403; tiket keluar 404. Pihak pada tiket dan pemilik sumber dibedakan. | E1/E7 |
| 4.4 | Pabrik, titipan dan pesanan jasa terpisah | Lulus | Super Admin | Kelima TRX-391-* × pabrik/jasa; POL-UJIJ-01 | jasa_id benar pada sumber; koreksi bendera tiket tidak mengganti pemilik di detail; stok ditautkan ke pemilik/pelanggan tepat. | E1/E7 |
| 4.5 | Sesudah diterima tetap dapat ditelusuri | Lulus | Super Admin | TRX-391-BERAS_PK termasuk yang ditolak | Riwayat dan detail tetap ada; tiket ditutup paksa tidak ditawarkan kembali. | E7/E8 |

## 5. Tempat untuk seluruh pekerjaan lama

| ID | Butir | Hasil | Akun | Tiket/proses | Bukti sebelum → sesudah | Rujukan |
|---|---|---|---|---|---|---|
| 5.1 | Semua kartu/tindakan dipetakan | Lulus | Empat peran | 28 konstruktor dalam inventaris | Objek kartu lengkap sebelum–sesudah identik; partisi tidak kehilangan atau menggandakan objek. | E2/E7 |
| 5.2 | Produksi pengeringan, giling, sosoh tersedia | Lulus | Super Admin + operator sesuai gudang | PGR-20261020-01 / LOT-20261020-01 / POL-UJIJ-01 | Tiga proses ditemukan di Berjalan dengan detail/tindakan; hasil giling 0 → 6.000 kg melalui browser. | E4/E7/E10 |
| 5.3 | Permintaan, kirim, terima transfer dan pindah tetap berfungsi | Lulus | Admin Elfira/Eka + operator G1/G2 | LOT-UJI-01 | Transfer mencatat peristiwa dan intake G2 sesuai perilaku otomatis lama; transfer sebagian, balapan dan undo ikut regresi. | E7 |
| 5.4 | Packing dan muatan tetap berfungsi | Lulus | Super Admin + operator G2 | POL-UJIJ-01; perintah fixture test_muat_konfirmasi | Form Kemas jasa tetap memilih proses/beras/pemilik; DB menguji packing dan muatan 80 → 100 → undo 80 tanpa menyamakan perintah dengan aktual. | E7/E10 |
| 5.5 | Seluruh pekerjaan QC belum selesai dapat ditemukan | Lulus | Admin/Super Admin; operator sesuai aturan QC lama | LOT-STOK-PABRIK/JASA/LАIN; PKB-20261020-02 | Meja QC digabung ke jenis QC, QC proses aktif tetap tersedia; pengaturan nonaktif menyembunyikan dan menolak POST. | E2/E7 |
| 5.6 | Seluruh jenis keputusan tetap ditemukan | Lulus | Admin/Super Admin | LOT-UJI-01 / kategori permintaan PK dan koreksi bobot | Kartu meja lama tidak dibangun ulang; alamat kategori/keputusan lama tetap membuka saringan yang sesuai. | E2/E7 |
| 5.7 | Pembatalan dan tindakan pendukung tetap terjangkau | Lulus | Admin/Super Admin + dua operator | GB-20261020-04 / pintasan operator | Penempatan dibatalkan, batch kembali baru; pintasan Catat packing/Bekatul/Undo tetap sesuai peran. | E7/E8 |
| 5.8 | Penerimaan tidak menjadi tugas ganda | Lulus | Empat peran | Kelima TRX-391-* | Ada di Barang Masuk; tidak ada sebagai penerimaan di Pekerjaan. Penempatan/QC sesudah penerimaan adalah tindakan berbeda yang tetap muncul. | E2/E7 |

## 6. Dua tab Pekerjaan

| ID | Butir | Hasil | Akun | Tiket/proses | Bukti sebelum → sesudah | Rujukan |
|---|---|---|---|---|---|---|
| 6.1 | Perlu tindakan hanya pekerjaan yang dapat ditindak | Lulus | Empat peran | Kartu siap mulai / packing / QC / keputusan | Tombol seluruhnya terkunci tidak menambah lencana; informasi tanpa tindakan masuk Berjalan. | E7 |
| 6.2 | Berjalan memuat proses aktif lengkap | Lulus | Empat peran | PGR-20261020-01 / LOT-20261020-01 / POL-UJIJ-01 | Status, pemilik, progres dan tindakan detail tetap tersedia pada empat tampilan. | E4/E10 |
| 6.3 | Pemicu kartu tetap aturan lama | Lulus | Empat peran | 28 konstruktor inventaris | Pembangun dan seluruh atribut kartu identik; stok tidak diubah menjadi tugas melalui logika baru. | E2 |
| 6.4 | Mulai/perbarui/jeda/lanjut/selesai tetap bekerja | Lulus | Admin/operator yang berhak | LOT-20261020-01 dan proses fixture regresi jeda/silo | Hasil 0 → 6.000 kg melalui browser; suite DB memeriksa waktu jeda, konflik, pembebasan silo dan penyelesaian eksplisit. | E7/E10 |
| 6.5 | Status/lokasi kartu diperbarui sesudah simpan | Lulus | Super Admin | Kelima TRX-391-* / LOT-20261020-01 | Penerimaan berpindah ke Diterima; giling tetap Berjalan dengan 6.000 kg/61,2%; fase selesai mengarah ke riwayat sambil membawa konteks. | E1/E7/E10 |
| 6.6 | Filter jenis pekerjaan dan gudang sesuai | Lulus | Super Admin + operator G1/G2 | LOT-20261020-01 / POL-UJIJ-01 | Giling/Pabrik/G1 menampilkan satu proses yang benar; G1 dan G2 tidak memperoleh proses gudang lain. | E7/E10 |
| 6.7 | Angka tab/lencana sesuai akses, tanpa hitungan ganda | Lulus | Empat peran | Kartu fixture + browser-peran.json | Lencana = tindakan global yang boleh dilakukan; tab mengikuti jenis/pemilik/gudang. Pencarian cepat menampilkan jumlah cocok pada halaman secara terpisah dari total tab. | E7/E10 |
| 6.8 | Proses menunggu waktu tidak menambah tindakan tertunda | Lulus | Empat peran | PGR-20261020-01 | Proses aktif/pendinginan tetap di Berjalan; tidak dijumlahkan ke Perlu tindakan hanya karena menunggu. | E7 |

## 7. Hak akses

| ID | Butir | Hasil | Akun | Tiket/proses | Bukti sebelum → sesudah | Rujukan |
|---|---|---|---|---|---|---|
| 7.1 | Keempat peran diperiksa | Lulus | Super Admin/Admin/Operator G1/Operator G2 | Kelima TRX-391-* dan tiga proses browser | Empat konteks nyata + dua mode lihat sebagai; hasil daftar dibanding dengan sumber lama. | E2/E7/E10 |
| 7.2 | Informasi, lokasi dan tindakan sesuai izin lama | Lulus | Empat peran | Kelima TRX-391-* | G1 menerima gabah; G2 melihat PK sebagai informasi, Admin menangani PK/beras/broken; detail proses mengikuti gudang. | E2/E7 |
| 7.3 | Hak penerimaan, produksi, QC, keputusan, finansial tetap | Lulus | Empat peran | Kelima TRX-391-* / LOT-STOK-PABRIK | Izin endpoint lama dipertahankan; tidak menambah harga pada daftar baru; mutu nonaktif tetap ditolak. | E2/E7 |
| 7.4 | Alamat dan tindakan langsung tetap memeriksa izin | Lulus | Dua operator + lihat sebagai | Kelima TRX-391-* | GET lintas gudang 403; /mutu dan /keputusan tetap 403 untuk operator; POST penerimaan yang tidak berhak ditolak. | E7 |
| 7.5 | Lihat sebagai mengikuti izin operator | Lulus | Super Admin lihat sebagai G1/G2 | Kelima TRX-391-* | Daftar dan hasil penolakan endpoint mengikuti operator efektif, bukan wewenang akun asal. | E7 |

## 8. Navigasi dan dampak lain

| ID | Butir | Hasil | Akun | Tiket/proses | Bukti sebelum → sesudah | Rujukan |
|---|---|---|---|---|---|---|
| 8.1 | Alamat/bookmark/tautan lama kompatibel | Lulus | Empat peran | /aksi, /berjalan, /mutu, /keputusan dan kategori | Buka/ nilai/grup dipertahankan; grup bahan campuran dibedakan menurut tindakan, bukan dipindah utuh. | E2/E7 |
| 8.2 | Konteks detail/simpan/batal tetap | Lulus | Super Admin | LOT-20261020-01 / POL-UJIJ-01 | Kembali membawa Giling/Pabrik/G1; nama Giling yang baru dipilih juga dibawa, termasuk setelah membuka formulir. | E3/E10 |
| 8.3 | Muat ulang/Kembali tidak mengulang pencatatan | Lulus | Super Admin | Riwayat 31 gabah / LOT-20261020-01 | Sesudah navigasi, kembali dan muat ulang, 99 tabel/342 baris identik. | E10 |
| 8.4 | Formulir, tombol, daftar panjang dan kosong di dua ukuran | Lulus | Super Admin; peran dibatasi terpisah | TRX-391-PANJANG-00..27; POL-UJIJ-01 | Matriks empat tampilan, formulir dan pembatalan; riwayat 25+6 baris browser / 25+3 pada fixture terpisah. Tidak ada luapan horizontal. | E3/E4/E9 |
| 8.5 | Saldo/pemilik/lokasi/perhitungan Stok tetap | Lulus | Super Admin + dua operator sesuai izin | Kelima TRX-391-*; LOT-STOK-PABRIK/JASA | Penerimaan tepat 9.800 kg per sumber; stok per pemilik, kategori, sisa/transfer dan audit ikut regresi Stok yang dipertahankan. | E1/E7/E8 |
| 8.6 | Integrasi tiket, jasa, pengiriman dan laporan tetap | Lulus | Super Admin/Admin/operator sesuai fungsi | TRX-391-* / POL-UJIJ-01 / LOT-UJI-01 | Tiket dan jasa_id utuh; regresi pengiriman serta PDF giling/pengeringan/sosoh membandingkan angka/detail/riwayat jeda. | E7 |
| 8.7 | Audit/notifikasi/pembatalan tetap | Lulus | Super Admin/Admin/Operator Uji | GB-20261020-04 / LOT-UJI-01 | Pencatat dan jejak transaksi tetap ada; undo penempatan dan transfer tidak menghapus riwayat; notifikasi sesuai gudang diuji. | E7/E8 |

Angka 45 uji khusus memuat sebagian uji yang juga ada dalam suite Produksi, sehingga tidak dijumlahkan sebagai 45 uji unik tambahan.

## Rujukan bukti

- **E1:** `terima-*.json` — 10 kombinasi penerimaan, dengan data sebelum/sesudah, pemilik, lokasi, proses dan audit.
- **E2:** `paritas-*.json`, `inventaris-kartu.json`, dan snapshot `sebelum/` — kartu/katalog empat peran dibanding pada DB sama.
- **E3:** `form-browser.json`, `browser-batal-sebelum.json`, `browser-batal-sesudah.json` — 12 pembatalan; 99 tabel/141 baris identik.
- **E4:** `browser.json`, `gabah-browser.json`, `browser-berjalan-akhir.json` dan galeri pada laporan — ponsel/desktop terang/gelap.
- **E5:** suite `tests/pg/test_timbang_kedua_sementara.py`, `test_bobot_belum_final.py`, `test_kontrak_timbangan.py` — rekonsiliasi sumber bobot dan status sementara/final.
- **E6:** `tujuan-tidak-sah-sebelum.json`, `tujuan-tidak-sah-sesudah.json`, `tujuan-tidak-sah-silo*.json` — kegagalan parsial yang direproduksi dan diperbaiki.
- **E7:** `produksi-final.xml` dan `checklist-penerimaan.xml`; termasuk suite peristiwa/transfer, QC, keputusan, jeda, packing, muat, stok, notifikasi, undo, dan PDF. Nama test tertera di XML dan merujuk fixture yang disebut.
- **E8:** `browser-simpan.json`, `browser-saldo-audit.json`, `browser-simpan-sesudah.json` — penerimaan browser dan efek audit.
- **E9:** `daftar-panjang.json`, `browser-panjang.json`, `panjang-*.png` — data fixture dan data browser berbeda, sehingga jumlah halaman keduanya ditulis terpisah.
- **E10:** `browser-peran.json`, `navigasi-tidak-mengubah-data.json`, `navigasi-panjang-*.json`; uji `test_tindakan_detail_mempertahankan_konteks_pekerjaan` dan empat uji browser paket `test_saring_kerja` mencakup penerusan filter baru ke tautan/formulir.

Semua berkas bukti berada di [folder hasil lokal](../../output/konsolidasi-kerja391/). Uji PDF menghasilkan artefak tersendiri di `output/audit-pdf-20261019/perbaikan354/`.

## Yang belum diverifikasi / bukan klaim Lulus

| Pemeriksaan di luar bukti fungsi di atas | Status | Batas |
|---|---|---|
| Perangkat ponsel fisik dan jaringan gudang sesungguhnya | Belum diuji | Ponsel diuji melalui viewport browser 390×844. |
| Beban volume riwayat operasional besar | Belum diuji | Diuji 28 penerimaan tambahan dan dua halaman, bukan beban produksi. |
| Pencocokan saldo terhadap database operasional | Belum diuji | Sengaja tidak mengakses atau mengubah data operasional. Pembanding saldo menggunakan data uji yang sama. |

Penerimaan tiket parsial bukan fungsi yang ditambahkan: alur lama memakai satu penerimaan hidup per tiket. Pembatalan gabah tetap membatalkan langkah terakhir (misalnya penempatan), bukan otomatis menghapus penerimaan. Pencarian cepat adalah pencarian pada halaman yang sedang ditampilkan; total tab mengikuti jenis/pemilik/gudang dan jumlah cocok ditampilkan terpisah.

**Keputusan penerapan tetap menunggu tinjauan pengguna.**
