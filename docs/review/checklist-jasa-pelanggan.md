# Checklist Pesanan Jasa per pelanggan — v392

Hasil lokal 21 Oktober 2026. **55 Lulus, 0 Gagal, 0 Belum diuji pada cakupan checklist di bawah.**
Batas pemeriksaan di luar cakupan lokal dicatat terpisah; tidak dianggap lulus.
Belum dipush/dideploy dan belum mendapat persetujuan penerapan produksi.

## Data, akun, dan bukti

- **C (campuran):** pelanggan Catur Uji 392, JAS-392-001/002/003;
  TRX-392-GABAH_BASAH/KERING/PK; PGR-392-01, LOT-392-1/2,
  PKB-392-01, TRF-20261021-01/02, POL-20261021-01, OUT-20261021-01.
- **S (pemisahan):** fixture `stok_lengkap`, pelanggan jasa dan pelanggan lain,
  lot/proses `LOT-STOK-JASA`, `POL-UJIJ-01`/`POL-STOK-LAIN`, barang pabrik; ID pelanggan adalah
  kunci meskipun nama sama. Nama kode aktual fixture tetap menjadi sumber uji.
- **L (data lama):** GB-J392-UKUR (belum diukur), JAS-LAMA-392 (dibatalkan),
  JAS-BATAL-392 (pesanan kosong), silo dengan beberapa riwayat intake,
  POL-392-RET (retur kepemilikan pabrik sesuai alur lama).
- Akun HTTP uji: **Uji superadmin None**, **Uji admin None**,
  **Uji operator [ID Gudang 1]**, **Uji operator [ID Gudang 2]**;
  dibuat ulang pada database terisolasi setiap uji. Akun layanan adalah
  fixture `pemakai`/`Elfira`, tidak memakai identitas pengguna operasional.
- Browser: **Uji Super 392**, serta mode lihat sebagai Admin, Operator G1/G2.
- **T1:** `tests/pg/test_jasa_pelanggan.py`, seluruh 19 kasus parameterisasi lulus.
- **T2:** `tests/pg/test_jasa_ketaatan.py`, penerimaan, rantai pemilik,
  pengambilan, penutupan, nota, dan penolakan campur; lulus dalam suite penuh.
- **T3:** `tests/pg/test_gabung_jasa.py`, pencampuran dan identitas historis;
  lulus dalam suite penuh.
- **T4:** `tests/pg/test_konsolidasi_stok.py`, `test_stok_produk_jasa.py`,
  `test_stok_karung_jasa.py`, `test_kemas_ulang.py`; lulus dalam suite penuh.
- **T5:** `tests/pg/test_konsolidasi_pekerjaan.py`, tiket, akses dan QC;
  lulus dalam suite penuh.
- **T6:** `tests/test_jasa_navigasi.py` (10 kasus URL aman),
  `tests/test_grup_antrean.py` (termasuk ID penutupan dan filter); lulus.
- **B:** `output/jasa392/browser-matrix-final.json`, PNG ponsel/desktop dua tema,
  `browser-formulir.json`, `browser-peran.json`, `browser-konteks.txt`.
- **N:** `browser-sebelum.json` = `browser-sesudah.json`: 17 tabel/53 baris sama.
- **J:** `campuran.json`: bukti sumber, stok, penerimaan, pengiriman final.
- Laporan lengkap dan pemetaan lama → baru: [jasa-per-pelanggan.md](jasa-per-pelanggan.md).

“Lulus” peran operator berarti **penolakan 403 dipertahankan pada administrasi
Jasa**, bukan membuka akses baru. Halaman operasional tetap memakai izin lama.
Pembanding sebelum–sesudah adalah layanan Stok/operasional lama pada data uji
yang sama, serta snapshot sebelum/sesudah pembacaan. Bukan salinan produksi.

## 1. Pengelompokan pelanggan

| No. | Butir | Hasil | Contoh / bukti sebelum–sesudah |
|---|---|---|---|
| 1.1 | Seluruh penerimaan, pesanan, proses dan barang satu pelanggan | Lulus | C, Super Admin/Admin; T1 skenario campuran, J: 3 penerimaan, 3 pesanan, 6 proses, saldo sesuai Stok. B empat tab. |
| 1.2 | Identitas dan riwayat setiap pesanan tetap | Lulus | C, JAS-392-001/002/003 tetap muncul; status Digabung hasil aturan operasional lama tetap ditampilkan, GET tidak menggabungkan. T1,T3,N. |
| 1.3 | Pelanggan lain/pabrik tidak masuk | Lulus | S, Admin; T1 `test_saldo_pelanggan_memakai_pembaca_stok_tanpa_menulis`, T4 filter ID. Nama sama tidak menjadi kunci. |
| 1.4 | Beberapa kondisi dapat muncul bersamaan | Lulus | S + GB-J392-UKUR, T1 `test_koreksi_hasil_dan_beberapa_kondisi_sekaligus`: bahan, proses, PK, hasil sekaligus; bobot kosong tetap kosong. |
| 1.5 | Pelanggan dan catatan historis dapat ditemukan | Lulus | JAS-LAMA-392 dibatalkan; T1 pencarian kode/status, daftar tetap membaca seluruh saldo pelanggan; B filter dan kembali. |

## 2. Banyak penerimaan

| No. | Butir | Hasil | Contoh / bukti sebelum–sesudah |
|---|---|---|---|
| 2.1 | Basah, kering, PK terpisah | Lulus | C, T1,J: tiga tiket → tiga penerimaan terpisah, bukan satu berat gabungan. |
| 2.2 | Tiket, pesanan asal, pemilik, jenis, bobot, tanggal, lokasi | Lulus | C; J memuat metadata sumber, penerimaan 6.000/6.000/5.000 kg; tautan detail asli semuanya HTTP200. B Penerimaan. |
| 2.3 | Tambahan tidak menimpa sebelumnya | Lulus | T2 `test_dua_truk_satu_pesanan_bila_tiketnya_menunjuk`; T1 C tiga penerimaan dan dua proses sosoh tetap ada. |
| 2.4 | Tiket/penerimaan tidak berulang akibat beberapa proses | Lulus | C; T1,J hanya 3 penerimaan meski banyak proses/transfer. Pengelompokan pembaca riwayat berdasarkan tiket; tambahan pending dicegah dengan kode tiket. |
| 2.5 | Sementara/final/belum diukur mengikuti sumber | Lulus | GB-J392-UKUR kg=None dan final=False; T1,T5 tiket terbuka; B Stok memakai “Belum diukur”/“Belum final”, bukan perkiraan. |
| 2.6 | Penerimaan menuju proses yang tercatat | Lulus | C; T1 membuka seluruh tautan penerimaan/lokasi/proses sampai200; J metadata riwayat pembaca Barang Masuk yang sama. |

## 3. Penelusuran proses

| No. | Butir | Hasil | Contoh / bukti sebelum–sesudah |
|---|---|---|---|
| 3.1 | Basah → pengeringan → giling → PK | Lulus | C: tiket basah, GB-392-1, PGR-392-01, LOT-392-1; T1 tautan sumber dan T2 rantai penerimaan operasional. |
| 3.2 | Kering → giling → PK | Lulus | C: tiket kering, GB-392-2, LOT-392-2; T1,T2. Tidak diberi pengeringan fiktif. |
| 3.3 | PK luar → penerimaan asal | Lulus | PKB-392-01 → TRX-392-PK; sumber sosoh4.000 kg menunjuk penerimaan, T1,J,B sumber terbuka. |
| 3.4 | Transfer terlihat | Lulus | TRF-20261021-01/02 dengan sumber giling yang benar; T1 semua href200, J,B. |
| 3.5 | Banyak proses dan banyak sumber tetap didukung | Lulus | C,T1 dua sosoh/pengambilan; T2,T3 dryer/giling multi-silo/pesanan pelanggan sama. Pembaca tidak membatasi satu proses per penerimaan. |
| 3.6 | Hubungan hilang ditandai, tidak ditebak | Lulus | S silo lama; T1 `test_tautan_tidak_menebak_alokasi_silo_lama` dan pemakaian ulang: transfer baru tidak muncul sebagai asal proses pertama. |

## 4. Penyosohan campuran

| No. | Butir | Hasil | Contoh / bukti sebelum–sesudah |
|---|---|---|---|
| 4.1 | Seluruh sumber PK aktual | Lulus | C POL-20261021-01, sumber TRF01/TRF02/PKB01; T1,J,B sumber tiga baris. |
| 4.2 | Bobot terpakai setiap sumber tepat | Lulus | C 2.500/3.500/4.000 kg, dibaca dari penggunaan silo terukur dengan sumber tunggal tidak ambigu; T1,J. |
| 4.3 | Total sumber cocok bahan proses | Lulus | C 2.500+3.500+4.000=10.000 kg; T1 assertion, J. |
| 4.4 | Sebagian hanya mengurangi aktual | Lulus | C sumber 3.000/4.000/5.000 → sisa500/500/1.000; T1,J, layanan Stok yang sama. |
| 4.5 | Hasil/susut sesuai catatan | Lulus | C hasil9.700, bahan10.000, susut300; T1. Proses belum final tidak diberi susut perkiraan. |
| 4.6 | Hasil campuran dihitung sekali | Lulus | C tiga pesanan, saldo beras4.500 dan samping3.200; satu panggilan stok_produk dengan semuaID, T1,J. |
| 4.7 | Tidak membagi hasil secara perkiraan | Lulus | C hasil milik proses/pelanggan; UI tidak menampilkan pembagian per tiket. T1 saldo pelanggan, B Proses/Stok. |
| 4.8 | Izin pencampuran tidak meluas | Lulus | T2,T3 campur pabrik+jasa/pelanggan berbeda ditolak; pelanggan sama mengikuti aturan gabung lama. Semua lulus suite penuh. |

## 5. Sisa stok pelanggan

| No. | Butir | Hasil | Contoh / bukti sebelum–sesudah |
|---|---|---|---|
| 5.1 | Bahan, PK, beras dan hasil samping bersamaan | Lulus | T1 koreksi + beberapa kondisi sekaligus; C saldo tiga jenis bersamaan, B Ringkasan/Stok. |
| 5.2 | Bahan terpakai tidak tersedia lagi | Lulus | C PK hanya2.000 tersedia,10.000 diolah tidak masuk saldo tersedia; T1,J. |
| 5.3 | PK yang sudah menjadi hasil tidak dihitung lagi | Lulus | C,T1: PK2.000, beras4.500, samping3.200 terpisah, bukan PK12.000 ditambah hasil. |
| 5.4 | Jenis/lot/lokasi/pemilik cocok Stok | Lulus | C LOT1/2 Gudang1 masing500 dan PKB Gudang2 1.000; S pembaca stok_produk5000 danPK3500 sama persis, T1,T4,J. |
| 5.5 | Curah, kemasan, sisa rebag tidak ganda | Lulus | T1 rebag100→80kemasan+20curah; saldo pelanggan5000 tetap; T4 regresi kemas ulang, pemilik dan karung. |
| 5.6 | Tidak ada total lintas tahap | Lulus | T1 rute tidak mengandung total ton lama; B Ringkasan tiga angka terpisah. T2 `test_sisa_jasa_tidak_pernah_dijumlah_jadi_satu_angka`. |
| 5.7 | Saldo pelanggan tidak diklaim per pesanan | Lulus | T1 teks “Saldo per pelanggan; tidak dibagi per pesanan”, B Stok; nota dan pesanan tetap referensi asli. |

## 6. Pengambilan, retur, perubahan

| No. | Butir | Hasil | Contoh / bukti sebelum–sesudah |
|---|---|---|---|
| 6.1 | Pengambilan sebagian/berulang sesuai aktual | Lulus | C 6.500→4.500 setelah2.000; T1 dua sosoh dan dua pengambilan, T2 pengambilan tidak mengurangi pabrik. |
| 6.2 | Beras diambil tidak mengurangi PK/samping | Lulus | C PK2.000 dan samping3.200 tetap; T1,J. |
| 6.3 | Retur/koreksi/pembatalan mengikuti aturan lama | Lulus | T1 koreksi5.000→4.800; balik verifikasi+muat4.500→6.500; retur lama tetap pabrik dan tidak menambah titipan. Tidak mengubah aturan retur. |
| 6.4 | Riwayat asal dan retur terpisah, bisa ditelusuri | Lulus | T1 retur membuka `/retur/{id}`200; ditampilkan terpisah dari pengiriman, dengan “Pengeluaran asal belum tertaut” bila FK tidak tersedia; tidak mengarang pasangan. |
| 6.5 | Ringkasan setelah perubahan konsisten | Lulus | T1 membaca ulang setelah koreksi, balik muat, rebag, retur dan pengambilan kedua; sama sumber Stok, bukan cache saldo baru. |

## 7. Keterhubungan halaman

| No. | Butir | Hasil | Contoh / bukti sebelum–sesudah |
|---|---|---|---|
| 7.1 | Barang Masuk pelanggan tepat | Lulus | C, pelanggan_id1 di URL; T1 metadata dan semua href; T5 riwayat tiket; B Penerimaan. |
| 7.2 | Pekerjaan proses/formulir lama | Lulus | T1 `/pekerjaan?pelanggan_id=...`200; penyaringan sesudah izin; T5 seluruh aksi lama; B form pengambilan dari pelanggan terkunci. |
| 7.3 | Stok pelanggan/jenis/lokasi tepat | Lulus | T1 ketiga tabStok dan detail; tautan PK G1 memakai kodeLOT, G2 memakaiIDintake; B konteks. |
| 7.4 | Pengiriman/pengambilan/retur tepat | Lulus | C,T1 semua href200; daftar pengiriman disaring melalui jasa_id item keIDpelanggan, sebelum limit; B pengambilan pelanggan terkunci. |
| 7.5 | Tautan tidak menulis transaksi/tugas/saldo | Lulus | T1 snapshot GET; N 17tabel/53baris identik sesudah browser/form/Batal/peran. |
| 7.6 | Kembali mempertahankan konteks | Lulus | B Stok→lotLOT-392-2→Kembali pelanggan→muat ulang tetap tabstok,cariCatur,statusberjalan,halaman1; T6 URL aman, filter tindakan per pesanan. |

## 8. Fungsi lama dan akses

| No. | Butir | Hasil | Contoh / bukti sebelum–sesudah |
|---|---|---|---|
| 8.1 | Inventaris seluruh fungsi lama | Lulus | Tabel pemetaan laporan: daftar/status/catatan/umur/nota/tutup/batal/pembuatan melalui timbang/penerimaan/stok/QC/packing/rebag/transfer/pengambilan/audit/notifikasi. |
| 8.2 | Buat/form/validasi/dokumen/audit/notifikasi | Lulus | T2 pesanan lahir saat penerimaan, nota, larangan stok/pemilik; T1 nota tiappesanan200, tindakan layanan aktual; suite penuh 1896 termasuk audit/notifikasi/pembatalan. B form dibuka lalu Batal; tidak menguji kiriman integrasi eksternal langsung. |
| 8.3 | Tutup/batal tetap per pesanan | Lulus | JAS-BATAL-392 saja dibatalkan; pesanan aktif pemilik sama tidak berubah, saldo tetap; penutupan bersaldo ditolak. T1,T2,T6 tautan nilaiID7, konteksfiltertetap. |
| 8.4 | Empat peran | Lulus | T1 parameter4peran; Super/Admin200, OperatorG1/G2403 sesuai haklama. B browser Super dan lihatsebagaiAdmin/G1/G2. |
| 8.5 | Gudang/finansial/kewenangan tetap | Lulus | T1,T4,T5 akseslama/baru dan pemisahangudang; gerbang Jasa can_see_financials tidak berubah; nota tetap tanpa angka uang. |
| 8.6 | Alamat langsung tetap berizin | Lulus | T1 empat tab, nota, pelanggan tidak ada404, tabsalah422; Operator403 walaupun mengetikURL. T5 aksi langsung tidak memperluas izin. |
| 8.7 | Lihat sebagai, alamatlama, responsif | Lulus | T1 dua lihatsebagai403, `/jasa/{id}`303 ke pelanggan, nota200; T4 aliasStok; B20tampilan tanpa luapan di390×844/1440×900 dua tema. |

## 9. Skenario wajib

| No. | Butir | Hasil | Contoh / bukti sebelum–sesudah |
|---|---|---|---|
| 9.1 | Hasil9.700 +susut300 =bahan10.000 | Lulus | C POL-20261021-01; T1 assertion danJ. |
| 9.2 | PK akhir2.000 | Lulus | C500+500+1.000; T1,J,B. |
| 9.3 | Beras akhir4.500 | Lulus | C6.500−2.000, pengiriman status selesai; T1,J,B. |
| 9.4 | Hasil samping akhir3.200 | Lulus | C1.000broken+200menir+2.000bekatul; T1,J,B. |
| 9.5 | Saldo/sumber sesuai Stok, proses, Pengiriman | Lulus | C,T1 membuka semua tautan sumber/stok/proses/pengiriman/nota200; J saldo dan rujukan asli. Tidak ada alokasi hasil proporsional. |

## Tidak termasuk klaim lulus di atas

**Belum diuji:** ponsel fisik, volume produksi sebenarnya, layanan eksternal
langsung, dan pascadeploy. Data historis yang memang tidak menyimpan alokasi
lot/tautan pengeluaran-retur tetap **belum tersedia** pada tampilan, bukan
“dilengkapi” oleh algoritme perkiraan. Hal itu sudah diuji sebagai keadaan
khusus (3.6/4.7/6.4); tidak berarti hubungan historisnya kini lengkap.

Perubahan produksi harus tetap menunggu tinjauan pengguna.
