# Kabar Usulan — bahan tinjauan, 23 Oktober 2026

Status: telah ditinjau dan disetujui pemilik untuk push serta deploy pada 23 Oktober 2026. Migrasi hanya dijalankan di database uji lokal `uji_kabar_20261023`.

## Inventaris sebelum perubahan

- `app/services/kabar.py` membaca `notifications`, penerima `target_role` admin/operator atau NULL, dengan penyaringan jenis menurut gudang kerja. Admin memegang kedua gudang. Jenis tak dikenal tetap mengikuti kontrak penerima lama.
- `/kabar` dahulu memuat tujuh hari terakhir, menyembunyikan `verifikasi_penyosohan`, mendahulukan prioritas merah, lalu otomatis mengubah `notifications.status` dari `baru` ke `dibaca`. Status ini **bersama untuk semua pengguna**, bukan status pribadi.
- `notifications.status` juga dipakai penulis/scheduler untuk penyelesaian dan pencegahan duplikasi. Mengubahnya untuk kebutuhan pembaca berpotensi mengganggu fungsi itu.
- `create_notification` tidak commit sendiri, sehingga tetap mengikuti transaksi pemanggil. Metadata asal yang tersedia adalah `table_name` dan `record_id`.
- Penulis aktif yang ditemukan: scheduler keterlambatan pengeringan; rantai permintaan PK; penerimaan/penolakan PK luar; rantai barang keluar. Modul pembelian gabah dan kemasan masih memiliki import helper, tetapi pemeriksaan sumber tidak menemukan pemanggilan aktif di kedua file tersebut. Histori yang sudah tersimpan tetap dipertahankan.
- Scheduler `app/services/scheduler.py` hanya menulis notifikasi dalam database. Pengiriman Telegram produksi sudah dipensiunkan sebelumnya; perubahan ini tidak menghidupkan kembali atau mematikan kanal apa pun.
- Lonceng desktop dan ponsel sudah ada di `base.html`. Sidebar sebelumnya disembunyikan melalui `PINTU_MATI`; sekarang Kabar juga dimasukkan dalam `MENU_TERSEMBUNYI`, sehingga tidak lagi dirender sebagai item sidebar/menu ponsel. Kunci dan URL lama dipertahankan.
- Tidak ditemukan pengaturan preferensi notifikasi khusus yang aktif di layar Pengaturan. Pengaturan scheduler yang ada tidak diubah.

## Pemetaan ke tampilan baru

| Fungsi/asal lama | Tampilan/perilaku baru |
|---|---|
| Header desktop dan ponsel | Lonceng yang sama membuka `/kabar`; badge kosong disembunyikan tanpa menghilangkan tombol |
| Kunci navigasi `kabar` | Tetap untuk judul/kompatibilitas URL, dikeluarkan dari sidebar |
| Semua `tipe` yang tersimpan | Pilihan Jenis dihasilkan dari data dalam cakupan pengguna; tidak memakai daftar/data contoh mockup |
| Histori tujuh hari | Seluruh histori, 30 baris per halaman; termasuk histori `verifikasi_penyosohan` sebagai pemberitahuan, tanpa menambahkan persetujuan sosoh |
| Urutan prioritas | Tanggal terbaru dahulu, id sebagai pemecah urutan; pengelompokan hari menurut zona pabrik. Prioritas merah tetap terlihat pada penanda |
| GET daftar otomatis dibaca | GET daftar tidak mengubah status; membuka catatan atau tombol Tandai dibaca menyimpan status pribadi |
| Status baca bersama | Tabel tambahan `notification_reads`, kunci `(user_id, notification_id)` |
| Notifikasi proses/pemicu/penerima | Penulis, payload penting, transaksi, scheduler dan pengaturan lama tidak diubah |

Tampilan menyajikan judul jenis, isi peristiwa utuh, referensi objek dan gudang jika diketahui, waktu, serta teks/penanda sudah atau belum dibaca. Mockup pembanding, simulasi peran dan data contoh tidak dimasukkan ke aplikasi. Data pada screenshot berasal dari fixture uji, bukan data produksi.

## Identitas tujuan

Navigasi memakai identitas tabel dan id, tanpa mencocokkan kata dalam judul/pesan.

| Tabel asal | Tujuan |
|---|---|
| `purchase_batches`, `pk_purchase_batches`, `pk_rejections` | Barang Masuk pada id tiket timbang; histori manual tanpa tiket menuju pemeriksaan batch yang bersangkutan |
| `drying_lots` | Detail proses pengeringan/pendinginan saat ini; riwayat jika selesai |
| `milling_process`, `polishing_process` | Detail proses aktif atau riwayat proses sesuai status saat ini |
| `permintaan_pk` | Detail baca `/pekerjaan/permintaan/{id}`, status/bobot/tujuan saat ini dan akses ke Pekerjaan; tidak otomatis membuka atau mengeksekusi persetujuan |
| `internal_transfers` | Riwayat transfer bagi G1/admin; stok intake transfer yang sesuai bagi G2 |
| `outgoing_records` | Detail transaksi Barang Keluar |
| `customer_returns` | Detail retur, tetap dibatasi admin |
| `purchase_batch_qc`, `purchase_batch_qc_samples` | Pemeriksaan gabah pada batch yang benar di Laporan & Riwayat |
| `milling_qc_logs`, `pk_purchase_qc_logs` | Pemeriksaan hasil giling/PK luar yang benar di Laporan & Riwayat |
| Rujukan kosong, objek hilang, tabel tidak dikenali, akses tidak sesuai | Kondisi “Catatan tidak tersedia” tanpa menebak tujuan atau menampilkan detail objek |

Gerbang modul asal tetap berlaku setelah pengalihan. Parameter kembali dibatasi ke URL lokal `/kabar`; tab, jenis, ukuran halaman, batas snapshot dan kursor halaman disimpan dalam URL kembali. Detail proses yang berpindah fase tetap membawa parameter kembali melalui mekanisme navigasi yang tersedia.

## Status baca, badge dan histori

Migrasi tambahan: `0106_kabar_pribadi`, sesudah `0105_selaras_referensi`. Tidak ada perubahan/penghapusan isi tabel notifikasi lama.

- Tanpa penanda pribadi, baca memakai bawaan historis: `notifications.status != 'baru'`. Sesudah pengguna menandai sendiri, penanda pribadi mengalahkan bawaan tersebut.
- Tidak mungkin merekonstruksi siapa yang benar-benar membaca notifikasi sebelum perubahan ini, sebab sistem lama hanya menyimpan satu status bersama. Bawaan historis dipertahankan secara jujur.
- Daftar, jumlah badge, jenis, akses satu notifikasi dan perubahan status menggunakan fungsi cakupan SQL yang sama: peran penerima, gudang kerja, jenis/tabel asal yang diketahui.
- Upsert PostgreSQL menyimpan status hanya pada `user_id` pengguna sesi. Penandaan tidak mengubah status baca pengguna lain.
- Tandai semua memakai `INSERT … SELECT … ON CONFLICT`, meliputi seluruh histori dalam cakupan pengguna, tanpa batas halaman atau filter tampilan.
- `notifications.status` tidak diubah. Membaca tidak menyelesaikan pekerjaan, menerima transfer, menyetujui keputusan, mencatat QC atau mengubah stok.
- Badge menghitung seluruh yang belum dibaca, bukan hanya halaman aktif atau jenis yang sedang dipilih. Halaman Kabar memakai angka yang sama untuk badge dan hitungan tab.
- Polling 20 detik memperbarui angka/warna prioritas, label aksesibel, hitungan tab dan tombol Tandai semua. Ketika daftar berubah, tersedia tautan memuat ulang konteks terbaru. Kegagalan polling mempertahankan angka terakhir; tidak menggantinya dengan nol.
- Pewaktu lama berhenti ketika elemen header diganti oleh navigasi instan; tidak menumpuk pada setiap perpindahan.
- Pagination memakai pasangan tanggal/id dan snapshot id dalam cakupan pengguna. Kabar baru tidak menyisip ke tengah urutan halaman lama; muat terbaru membuka snapshot baru.
- Perubahan status memakai POST dan proteksi sesi/CSRF aplikasi yang tersedia. Tidak ada UI optimistis: keberhasilan baru terlihat setelah server menyimpan. Galat simpan tetap menjadi respons galat.

## Bukti pemeriksaan

Semua uji database menggunakan PostgreSQL loopback khusus uji. Identitas peran dibentuk sebagai akun/sesi sungguhan dalam database uji, bukan kontrol simulasi mockup.

| Pemeriksaan | Hasil/bukti |
|---|---|
| Seluruh unit aplikasi, kecuali suite PG dan modul Timbangan | **753 lulus**, `output/kabar401/unit.txt` |
| Regresi PG Kabar, permintaan PK, empat langkah, barang keluar, detail proses, retur, riwayat QC | **228 lulus**, `output/kabar401/postgres-regresi.txt` |
| Verifikasi akhir Kabar termasuk QC, zona waktu, kegagalan simpan dan scheduler | **26 lulus**, `output/kabar401/postgres-kabar-final.txt`; sebagian uji berulang dari regresi di atas |
| Sinkronisasi paket tampilan dan penjaga lencana/versi | **29 lulus**, `output/kabar401/unit-penjaga.txt` |
| Chromium, 1440×1000, 390×844 dan 320×740, terang/gelap | Tidak ada overflow horizontal, item Kabar di sidebar, atau galat JavaScript; `pemeriksaan-visual.json` |
| Badge nol/baru, prioritas, kegagalan jaringan, keyboard, target sentuh, navigasi instan | Lulus; target tombol Kabar minimum 44 px; `pemeriksaan-badge.json` |
| Perbedaan sumber | `git diff --check` bersih di Produksi dan Tampilan; helper notifikasi, scheduler dan penulis transaksi tidak diedit |

Perintah regresi utama:

```sh
UJI_PG_URL=postgresql+asyncpg://wahidnurhani@127.0.0.1:5432/uji_kabar_20261023 \
  .venv/bin/python -m pytest -o addopts='' -q \
  tests/pg/test_kabar.py tests/pg/test_kabar_usulan.py \
  tests/pg/test_permintaan_pk.py tests/pg/test_barang_keluar.py \
  tests/pg/test_proses_aktif_detail.py tests/pg/test_permintaan_empat_langkah.py \
  tests/pg/test_retur_integrasi.py tests/pg/test_riwayat_qc_detail.py
```

Untuk merekam HTML pembanding, tambahkan `UJI_KABAR_POTRET=1` pada pengujian `test_permintaan_catatan_saat_ini_dan_potret`.

Pembanding lama/baru memakai akun Admin Uji dan kumpulan 35 peristiwa yang sama. Tampilan lama digambar dari template Git sebelum perubahan; perilaku GET lama yang memutasi status tidak dijalankan agar status awal pembanding tetap sama. Tampilan baru menampilkan 30 baris pertama dan menyediakan halaman selanjutnya. Screenshot browser memakai HTML hasil HTTP aplikasi; API polling/sesi disediakan respons uji pada pemeriksaan visual. Mutasi dan izin diuji terpisah melalui HTTP ASGI dan PostgreSQL nyata. Ini tidak diklaim sebagai uji browser langsung terhadap produksi.

Bukti visual tersedia dalam `output/kabar401/`: `desktop-lama.png`, `desktop-terang.png`, `desktop-gelap.png`, `ponsel-terang.png`, `ponsel-gelap.png`, dan ukuran ponsel kecil. Skrip pemeriksaan browser juga disertakan di folder tersebut.

## Checklist penerapan

Centang berarti telah diverifikasi dengan bukti yang disebutkan. Kotak kosong menyatakan cakupan yang belum diuji sepenuhnya.

### 1. Akses dan navigasi

- [x] Ikon lonceng membuka Kabar pada desktop dan ponsel — href `/kabar`, render Chromium dan GET HTTP akun uji berhasil.
- [x] Kabar tidak lagi muncul di sidebar maupun menu ponsel — `MENU_TERSEMBUNYI`; pemeriksaan DOM menghasilkan nol tautan Kabar dalam laci.
- [x] URL lama dan tautan notifikasi tetap berfungsi — `/kabar` dipertahankan; gerbang/rute modul asal tidak diganti; uji alamat lama lulus.
- [ ] Setiap kabar membuka catatan asal yang benar — proses pengeringan, giling, permintaan dan QC diuji langsung. **Belum diuji menyeluruh** untuk setiap payload historis pembelian, penyosohan, transfer, pengiriman dan retur melalui tombol Kabar; data historis produksi tidak diakses.
- [x] Kembali dari catatan mempertahankan konteks daftar — HTTP proses dan catatan permintaan membawa tab/jenis/halaman; URL kembali dibatasi lokal.

### 2. Daftar dan filter

- [x] Semua jenis dan histori kabar lama tetap tersedia — tidak ada batas tujuh hari; jenis tak dikenal dan histori sosoh lama diuji.
- [x] Tab Semua dan Belum dibaca bekerja dengan benar — layanan dan HTTP.
- [x] Pilihan Jenis dan kombinasinya dengan status baca menghasilkan daftar yang tepat — uji 38 baris lintas dua jenis.
- [x] Urutan, tanggal, waktu, dan pengelompokan hari benar — timestamp sama, pemecah id, dan pengujian UTC ke WIB melewati tengah malam.
- [x] Pemuatan berikutnya tidak menghilangkan atau menggandakan kabar — 65 baris/3 halaman, timestamp sama dan snapshot saat kabar baru masuk.

### 3. Status baca dan badge

- [x] Jumlah badge cocok dengan kabar belum dibaca dalam cakupan pengguna — admin/operator G1/G2 dan hitungan layanan/HTTP.
- [x] Membuka kabar memperbarui status baca sesuai perilaku yang diterapkan — GET daftar tidak menandai; POST Buka catatan menandai pengguna tersebut.
- [x] Tandai dibaca dan Tandai belum dibaca bekerja serta tersimpan setelah halaman dimuat ulang — sesi database baru dan GET ulang.
- [x] Tandai semua dibaca mencakup seluruh kabar yang dimaksud, bukan hanya halaman pertama — 65 baris, termasuk histori 30 hari.
- [x] Perubahan status baca tidak memengaruhi pengguna lain — dua operator penerima yang sama diuji.
- [x] Badge diperbarui setelah perubahan status dan kedatangan kabar baru — HTTP dan polling Chromium; nol tanpa badge, lonceng tetap aktif.
- [x] Membaca kabar tidak mengubah status pekerjaan, keputusan, QC, pengiriman, atau saldo stok — jalur tulis hanya `notification_reads`; status pengeringan/permintaan/giling dan jumlah QC diperiksa, regresi transaksi/stok terkait lulus.

### 4. Pemicu dan pengiriman

- [ ] Pemicu, penerima, dan kanal notifikasi lama tetap bekerja — penulis tidak diedit; rantai transaksi dan scheduler diuji lokal. **Belum diuji** sebagai proses terjadwal dan kanal eksternal pada lingkungan produksi.
- [x] Satu peristiwa tidak menghasilkan kabar ganda akibat perubahan ini — scheduler telat dipanggil, dibaca, lalu dipanggil ulang tetap satu notifikasi; pemicu transaksi tidak diubah.
- [x] Histori dan pengaturan notifikasi lama tetap dapat digunakan — histori tidak dimigrasi/ditimpa; pengaturan scheduler dipertahankan. Tidak ditemukan layar preferensi notifikasi khusus aktif.
- [x] Kabar yang sudah dibaca tetap tersedia melalui tab Semua — HTTP dan uji histori.

### 5. Hak akses

- [x] Setiap peran diuji menggunakan akun sebenarnya — akun dan sesi database uji untuk operator, admin, superadmin; gudang G1/G2. Akun produksi bernama belum digunakan.
- [x] Daftar dan jumlah badge tidak membocorkan data di luar cakupan akses — uji peran/gudang serta snapshot id yang dibatasi cakupan.
- [x] Penandaan status baca dibatasi pada kabar pengguna yang berwenang — POST untuk notifikasi admin/G1 dari G2 ditolak 404, tanpa baris status baca tercipta.
- [x] Catatan tujuan tetap mengikuti hak akses modul asal — gerbang sebelum navigasi ditambah gerbang rute asal; regresi detail proses, QC, pengiriman/retur.
- [x] URL langsung dan API menolak akses yang tidak diizinkan — pengujian HTTP peran/gudang dan CSRF; rute Kabar memeriksa ulang penerima dan detail permintaan memeriksa gudang kerja.
- [x] Catatan yang dihapus atau tidak lagi dapat diakses ditangani dengan jelas — rujukan hilang/tidak dikenal diujikan; tidak membocorkan isi objek.

### 6. Tampilan dan keandalan

- [x] Desktop dan ponsel mengikuti mockup usulan — susunan Kabar, tab, Jenis, kelompok hari, status dan aksi; memakai kerangka aplikasi yang sudah dikonsolidasikan.
- [x] Ikon, badge, teks, filter, dan tombol tidak terpotong atau bertumpuk — pemeriksaan visual enam kombinasi ukuran/tema dan batas elemen.
- [x] Tema terang/gelap, fokus keyboard, dan target sentuh dapat digunakan — Chromium, fokus Tab dan tinggi minimum tombol Kabar 44 px.
- [ ] Kondisi kosong, semua sudah dibaca, memuat, dan gagal ditangani dengan benar — kosong/semua dibaca serta gagal simpan/jaringan diuji; pemuatan memakai navigasi server aplikasi yang ada. **Belum diuji** dengan jaringan ponsel lambat nyata dan iOS Safari/PWA.
- [x] Kegagalan memperbarui status baca tidak ditampilkan seolah berhasil — simulasi kegagalan server memberi 500 dan jumlah belum dibaca tetap; polling gagal mempertahankan angka terakhir.
- [x] Modul lain dan hasil konsolidasi sebelumnya tetap berfungsi — unit aplikasi 753 dan regresi PG terkait 228 lulus. Modul Timbangan tersendiri tidak termasuk pengujian tahap ini.

## Keterbatasan dan langkah tinjauan

- Belum diuji menggunakan akun/data produksi, perangkat fisik, Safari iOS/PWA atau jaringan gudang nyata.
- Histori baca pribadi sebelum migrasi tidak tersedia; status bersama lama dipakai sebagai bawaan. Tidak ada klaim bahwa bawaan itu membuktikan tiap orang pernah membaca.
- Notifikasi lama tanpa identitas asal tetap dapat dibaca; tujuan yang tidak dapat dipastikan menampilkan kondisi tidak tersedia. Tidak dilakukan penebakan judul atau pembuatan notifikasi pengganti.
- Pemetaan lengkap setiap payload historis perlu sampel data berizin pada tahap penerimaan berikutnya. Tidak ada perubahan pada alur transaksi sumber.
- Kode memerlukan migrasi tambahan sebelum kelak dijalankan bersama database yang belum memilikinya. Migrasi produksi dijalankan entrypoint ketika rilis yang disetujui dimulai.
- Rilis disetujui melalui push `main` Produksi yang terhubung deploy otomatis.
