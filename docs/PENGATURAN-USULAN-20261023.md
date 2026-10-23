# Pengaturan usulan — 23 Oktober 2026

**Siap untuk tinjauan lokal; belum dipush/deploy.** Perbaikan akses Operator tanpa gudang `be8834c` sudah menjadi dasar cabang ini dan telah dideploy terpisah. Tidak mengubah konfigurasi/data operasional untuk pengujian Pengaturan.

## Hasil dan acuan

Halaman utama memakai empat kelompok dari sisi Usulan mockup desktop/ponsel: Akun & perangkat, Operasional, Pengelolaan, Sistem & koneksi. Desktop memakai dua kolom dan ponsel satu kolom. Identitas dan peran asli akun terlihat; Mode terik langsung tersedia pada halaman utama. Formulir pindah ke halaman rincian tanpa mengganti layanan penulis, validasi atau konfigurasi.

Penataan memakai gaya/token aplikasi dan ikon SVG. Tidak menambahkan kontrol Peran contoh, Belum ada Super Admin, Berdampingan atau Fokus lama. Lihat sebagai dan pilihan gudang yang tersedia adalah fungsi aplikasi sebenarnya, bukan simulasi mockup.

[Galeri tangkapan desktop/ponsel, empat peran dan dua tema](../output/pengaturan404/tinjauan.html). Potret berasal dari HTML respons endpoint dan data uji terisolasi, bukan data operasional. Setiap gambar memiliki bagian atas/bawah. Bagian sebab berhenti juga dibuka melalui keyboard untuk memeriksa input di dalamnya.

## Inventaris dan pemetaan fungsi lama

Inventaris dilakukan sebelum menyunting sumber `app/web/pengaturan.py`, `auth.py`, `lihat_sebagai.py`, `pengguna.py`, `mode_uji.py`, layanan `setelan`, `kledo_sinkron`, identitas/sesi, dan templat bersama lama. Aturan peran tetap memakai peran asli, peran efektif, view dan dependency yang sama.

| Kelompok/halaman | Fungsi yang dipertahankan | Penyimpanan/izin lama |
|---|---|---|
| Utama `/pengaturan` | Mode terik; identitas; pintu sesuai bendera izin; versi | Cookie perangkat `produksi_terik`, bukan DB/global akun |
| Akun & perangkat → `/pengaturan/akun` | Nama, penjelasan dampak pada catatan lama, pintu ganti sandi | `/pengaturan/nama`; validasi nama dan User yang sama |
| `/ganti-sandi` | Sandi lama, baru, pengulangan, sandi awal wajib, pencabutan sesi lama | Paket `hmu_identitas`; versi token/cookie baru tetap mekanisme lama |
| `/pengaturan/peran` | Lihat sebagai atau Kerja di gudang; kembali ke peran/gudang asli | `/lihat-sebagai`; peran asli menentukan izin, hanya turun; gudang efektif di objek lepas dari DB |
| `/pengaturan/sesi` | Keluar/Ganti pengguna menurut jenis sesi, Keluar semua dengan konfirmasi | `/keluar`, `/keluar-semua`; versi token benar-benar dicabut |
| Operasional → `/pengaturan/sebab-berhenti` | Daftar proses dinamis; tambah/buang; batas panjang/duplikasi/minimal | Endpoint dan `setelan.sebab_jeda` lama; Admin ke atas; pengeringan tetap di Alat |
| `/pengaturan/mutu` | Sakelar, borang/pengingat/informasi QC, histori tetap tersimpan | `/pengaturan/fitur-mutu`, sumber `fitur_mutu` lama |
| Pengelolaan → `/pengguna`, detail akun | Orang baru, akun, peran, mode perangkat, reset, aktif/nonaktif | Seluruh POST/validasi lama; `butuh_super` beserta fallback Admin tanpa Super aktif |
| `/pengaturan/alat` | Dryer/silo, kapasitas, target per dryer, sebab pengeringan, filter komoditas, arsip | Seluruh formulir/endpoint lama tetap utuh; tidak membuat konfigurasi pengeringan kedua |
| `/pengaturan/gudang` | Nama, alamat, koordinat, aktif/arsip; perlindungan gudang proses/masih dipakai | Seluruh formulir/endpoint lama tetap utuh |
| Sistem & koneksi → `/pengaturan/kledo` | Pelanggan/vendor, pemicu latar, status dan tombol nonaktif saat sibuk | `kledo_sinkron` dan jadwal lama; Admin ke atas; tidak ada key di state UI |
| `/audit` | Filter, detail, pembatalan yang memang diizinkan; akses Admin tetap ada | Endpoint dan tab Laporan & Riwayat lama; tambahan jalan kembali ke Pengaturan |
| `/pengaturan/sistem` | Batas ubah hanya informasi; versi semua peran; peringatan skema sesuai izin | `BATAS_UNDO` lama menjadi `JAM_BATAS`; `_versi.info`; peringatan hanya `tuan` |
| `/pengaturan/mode-uji` | Hanya mode uji + peran lama; cakupan/perlindungan penghapusan sama | Implementasi `mode_uji` tidak diubah; bukan tindakan umum produksi |

Kelompok yang tidak mempunyai fungsi tersedia disembunyikan. Sistem & koneksi tetap menawarkan Informasi versi kepada Operator karena versi sebelumnya juga tersedia untuk semua peran. Admin tetap dapat membuka Audit walau Pengelolaan disembunyikan setelah Super Admin tersedia.

## Integrasi dan keamanan

Tambahan GET rincian memakai pemeriksaan izin server. POST tetap ke URL lama dan menerima field opsional `kembali_pengaturan`, terbatas pada daftar alamat rincian resmi. Tanpa field tersebut, tujuan lama tetap berlaku. Sandi awal wajib tidak menerima tujuan kembali yang melewati alur wajib. Semua formulir memakai CSRF lama.

Pilihan gudang dan samaran tetap memakai endpoint/cookie lama; tidak mengubah `users.role` atau gudang utama. Pemilihan terlihat kembali pada selector setelah reload. Handler baru tidak ditambahkan; navigasi/formulir memakai mekanisme aplikasi yang sama. Tidak menyimpan sandi pada state UI atau log.

Perubahan komponen dikerjakan pada sumber repo tampilan (checkout `retur-work/tampilan`), versi **404**, commit **`b546fdb`**, lalu disinkronkan melalui `scripts/sinkron.py ../produksi`. Salinan vendored tidak disunting langsung. Tidak ada migrasi, variabel lingkungan atau perubahan nilai konfigurasi yang diperlukan.

## Bukti pengujian

- Suite produksi penuh dengan perubahan Pengaturan: **2.023 lulus**, 647,15 detik.
- Tambahan pengujian pengelolaan/Mode uji: **8 lulus**, 5,46 detik; ditambahkan setelah koleksi suite penuh. Angka ini terpisah dari 2.023.
- Regresi akhir gabungan: **50 lulus**, 28,25 detik; mencakup seluruh 27 kasus baru Pengaturan, identitas, perpindahan gudang, kunci sinkron Kledo dan 12 kasus perbaikan akses. Juga memeriksa batas panjang sebab dan pengeringan tetap dikelola di Alat.
- Seluruh repo tampilan: **398 lulus**, 353,17 detik. Pemeriksaan paket/manifest akhir: **32 lulus**.
- Bukti visual: **104 kombinasi** halaman/peran/tema/perangkat lulus overflow, target sentuh, fokus input dan keyboard rincian terlipat.
- Navigasi instan: **6 siklus** pergi/kembali rincian, lalu **satu POST** untuk satu klik Simpan; respons sepenuhnya fixture lokal. Pengujian POST dan penyimpanan nyata terpisah memakai HTTP + PostgreSQL uji.
- Database pengujian hanya loopback berawalan `uji_`; tidak melakukan tindakan operasional di produksi. Jadwal/layanan eksternal tidak dipicu untuk membuat bukti tampilan.
- Migrasi dari database lokal kosong dan `alembic check` lulus: **No new upgrade operations detected**. `git diff --check` bersih.

## Checklist penerimaan

Centang berikut berarti diperiksa pada kode dan/atau pengujian terisolasi yang disebutkan, bukan seluruh kombinasi sudah dicoba pada akun operasional. Koneksi nyata yang belum dicoba dinyatakan terpisah.

### A. Susunan dan tampilan

- [x] Kelompok sesuai Usulan — HTML endpoint dan potret desktop/ponsel.
- [x] Mode terik langsung terlihat — potret serta POST cookie perangkat.
- [x] Tindakan sesuai peran tersedia di desktop/ponsel — matriks lima profil dan potret empat peran.
- [x] Halaman rincian memiliki jalan kembali — GET rincian, pengguna/akun, alat, gudang, sandi dan Audit.
- [x] Kontrol pratinjau mockup tidak masuk aplikasi — inspeksi dan assertion respons.
- [x] Formulir lama lengkap — dipertahankan di partial; pengguna/alat/gudang tidak diringkas menjadi contoh mockup.

### B. Akun dan perangkat

- [x] Nama dan validasi — pendek/duplikat/normalisasi/tersimpan/reload.
- [x] Sandi lama dan pengulangan — salah ditolak, perubahan sah tersimpan.
- [x] Sandi awal wajib dan sesi — POST sebelum ganti ditolak; cookie baru berlaku dan sesi lama ditolak.
- [x] Mode terik per perangkat — dua klien akun sama tetap berbeda.
- [x] Keluar/Ganti pengguna/Keluar semua — label memakai `sesi_pendek`, POST nyata di DB uji.
- [x] Pencabutan seluruh sesi — klien kedua menerima 401; keluar satu perangkat tidak memutus klien lain.

### C. Peran dan gudang kerja

- [x] Pilihan Lihat sebagai mengikuti peran asli — bendera dan penjepit lama.
- [x] Tidak dapat memilih peran lebih tinggi — unit peran dan POST Operator mencoba Super Admin.
- [x] Peran asli tetap utuh — pemeriksaan row User setelah memilih.
- [x] Operator memilih gudang — endpoint resmi G1/G2.
- [x] Gudang utama tidak berubah — pemeriksaan row User dan regresi gudang lama.
- [x] Kembali ke gudang/peran asli — opsi kosong, cookie serta selector kembali sesuai.

### D. Pengelolaan

- [x] Orang, akun, peran, akses aplikasi — POST pendaftaran/akun/detail, matriks pintu aplikasi identitas lama.
- [x] Reset dan aktif/nonaktif — hash berubah, status akun/master selaras; pemutusan sesi dan perlindungan akun tertinggi diuji regresi identitas.
- [x] Admin sementara tanpa Super — halaman pengguna/alat/gudang 200.
- [x] Setelah Super ada — pintu hilang bagi Admin dan URL langsung 403; Audit tetap 200.
- [x] Dryer/silo/target/sebab pengeringan — POST tambah/edit/arsip dan konfigurasi lama; formulir lengkap tetap di Alat.
- [x] Gudang/geotag — angka salah/rentang ditolak, koma lokal diterima, edit nama/alamat/koordinat tersimpan.
- [x] Perlindungan gudang — gudang G1/G2 dan gudang yang dipakai User tidak dapat dihapus.

### E. Operasional dan QC

- [x] Proses sesuai cakupan — `_proses_view` lama diuji untuk semua view; Operator tidak membuka setelan Admin.
- [x] Validasi sebab — duplikat/minimal satu/panjang lama dipertahankan dan diuji POST.
- [x] Tidak ada konfigurasi pengeringan kedua — tidak menambah model/kunci; pengeringan kembali ke Alat.
- [x] Sakelar QC memakai layanan lama — nilai DB dan keadaan tampilan setelah reload.
- [x] Mematikan tidak menghapus QC — baris pemeriksaan nyata tetap satu.
- [x] Menyalakan kembali membaca data lama — rata QC dan nilainya tetap sama.

### F. Koneksi, audit, informasi

- [x] Sinkron manual dan integrasi jadwal — layanan dan jadwal tidak diubah; rutin diuji dengan respons Kledo tiruan. Koneksi eksternal nyata belum diuji.
- [x] Status belum tersambung/berjalan/selesai/gagal — empat respons endpoint terisolasi.
- [x] Tidak memulai sinkron ganda — regresi kunci pemicu bersamaan dan tombol sibuk lama.
- [x] Audit sesuai izin — Admin biasa masih memiliki pintu dan GET, formulir/filter lama tidak diubah.
- [x] Batas ubah berasal dari `BATAS_UNDO`, bukan angka contoh.
- [x] Batas tetap tidak dapat diedit — tidak ada formulir batas atau sumber konfigurasi baru.
- [x] Versi/peringatan skema — regresi versi lama dan rincian baru; informasi bukan teks contoh.
- [x] Mode uji hanya kondisi/peran sah — enam kombinasi mode/peran pada GET, tanpa menjalankan penghapusan operasional.

### G. Keamanan dan regresi

- [x] Semua peran sah serta Operator G1/G2/tanpa gudang — matriks HTTP dengan akun DB uji nyata.
- [x] URL langsung ditolak tanpa izin — GET rincian dan POST setelan Admin.
- [x] Izin server tetap ada — dependency POST lama dan guard GET baru, bukan visibilitas saja.
- [x] URL/parameter/pesan/kembali — endpoint lama tetap ada; tujuan detail diizinkan dan alamat luar diabaikan.
- [x] CSRF/validasi/sesi — kiriman tanpa CSRF 403, sandi/versi token dan sesi dicabut benar.
- [x] Navigasi berulang tanpa kiriman ganda — enam siklus dan satu POST teramati.
- [x] Konfigurasi tersimpan setelah reload — nama, sebab, QC serta cookie tema.
- [x] Tidak menimpa data/konfigurasi dengan contoh — tidak ada migrasi, seed produksi atau perubahan layanan konfigurasi.
- [x] Pengujian terisolasi — DB loopback `uji_`, browser seluruhnya fixture lokal.
- [x] Pemeriksaan repo relevan — suite penuh, paket tampilan, manifest, pemeriksaan skema dan diff.

## Keterbatasan

- Pengaturan belum dideploy; belum diuji memakai akun operasional di produksi. Jangan menyamakan tangkapan fixture dengan potret produksi.
- Sinkron Kledo nyata serta eksekusi jadwal tengah malam pada layanan produksi belum dijalankan; uji memakai respons tiruan dan pemeriksaan bahwa jadwal/layanan lama tidak berubah.
- Tidak menguji penghapusan data operasional melalui Mode uji. Pengujian penghapusan lama hanya berjalan di lingkungan terisolasi.
- Potret dan navigasi diuji memakai Chromium; belum ada pengujian langsung pada iPhone/Safari atau perangkat fisik.
- Regresi bukan jaminan setiap kombinasi data historis; tidak menyatakan semua fungsi aman hanya berdasarkan build/tampilan.
