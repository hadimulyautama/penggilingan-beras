# Penataan detail penyosohan — 23 Oktober 2026

## Perubahan dan batas

Detail aktif penyosohan memakai template `detail_sosoh.html`, CSS dan skrip khusus. Template bersama `proses_aktif_detail.html`, formulir, API tindakan, layanan produksi, stok, perhitungan, token konfirmasi dan riwayat selesai tidak diubah oleh perubahan ini. Dua tambahan metadata tampilan membaca awal/sebab jeda dan silo yang masih terikat dari sumber lama.

Acuan: mockup desktop dan ponsel `detail-penyosohan-{desktop,ponsel}.html` di direktori visualisasi 20 Oktober. Susunan mengikuti hero identitas, empat tab, tindakan sesuai status, tiga statistik, neraca dan waktu berdampingan di desktop serta satu kolom di ponsel. Menggunakan kerangka navigasi, tipografi dan token aplikasi yang ada; bukan menyalin bingkai pratinjau atau data contohnya. Kontrol peran/status contoh dan perbandingan tidak disertakan.

## Inventaris sebelum perubahan dan pemetaan

Inventaris diperiksa sebelum penyuntingan pada `proses_aktif_detail.html`, `proses_aktif.rincian`, `_kartu_penyosohan_g2`, macro bahan silo/jeda dan katalog tindakan lama.

| Informasi/tindakan lama | Lokasi baru dan sumber tetap |
|---|---|
| Kode, jenis, gudang, status, pemilik/pesanan jasa, nota jeda, hasil/durasi belum final | Hero di atas semua tab; `d`, identitas pekerjaan dan macro kepemilikan lama |
| Kembali ke Pekerjaan | Tautan paling atas; `kembali_kerja` melalui `konteks_aman` |
| Keadaan, sebab dan mulai jeda | Ringkasan; jeda terbuka lama, waktu aktual dari server |
| Total seluruh komposisi, hasil beras, rendemen | Ringkasan; `kartu.neraca`, statistik lama |
| Beras, seluruh hasil samping, selisih dan persentase neraca | Ringkasan; objek neraca lama, hanya label baris terakhir menjadi “Selisih sementara”; negatif dan peringatan tetap tampil |
| Mulai, durasi efektif, total jeda, silo aktif | Ringkasan singkat; fakta waktu lama dan pemakaian yang sisa akhirnya belum dicatat |
| Semua fakta: pemilik, gudang, mulai proses/fase, pencatat awal, waktu berlalu, efektif, jeda, silo, komposisi, tambahan | Riwayat → Identitas & waktu proses; seluruh `d.fakta`, tanpa pemotongan |
| Silo, komposisi, awal, tambahan, total, sisa, terpakai, status, pemakaian ulang dan asal lot | Bahan & silo → macro bahan silo yang sama; seluruh kelompok pemakaian lama tetap disediakan |
| Sumber warisan/tidak diketahui, catatan sumber | Bahan & silo; bagian sumber lama tetap dirender dan rincian dapat dibuka |
| Total hasil seluruh jenis dan semua spesifikasi tercatat | Hasil → Hasil sosoh keluar; `anak_grup` hasil lama dari seluruh log sah |
| Pertambahan hasil, waktu, pencatat, spek, jumlah/halaman riwayat | Hasil → Riwayat pencatatan hasil sosoh; `_log` lama, 20 entri per halaman |
| Keterbatasan QC hasil sosoh | Hasil → QC hasil penyosohan; teks lama, tanpa tombol/penilaian baru |
| Jeda, lanjut, perubahan kondisi, pembatalan, waktu kejadian/pencatatan, sebab, catatan, keterlambatan dan pagination | Riwayat → macro `riwayat_jeda_blok` lama |
| Catat/perbarui hasil | Utama di Ringkasan saat berjalan; tersedia saat dijeda dan pada tab Hasil; borang/API `hasil_penyosohan` lama |
| Hentikan sementara | Tindakan langsung Ringkasan saat berjalan; borang/API lama |
| Lanjutkan penyosohan | Utama Ringkasan saat dijeda; borang/API serta pratinjau jeda lama |
| Perbarui kondisi jeda | Ringkasan → Pengelolaan proses, saat diizinkan oleh pilihan lama |
| Tambah silo/mix, bebaskan silo, selesaikan penyosohan | Ringkasan → Pengelolaan proses; urutan konfirmasi, parameter otomatis dan izin lama |
| Dialog, pesan kesalahan/berhasil dan perlindungan kirim ganda | Elemen dialog/status serta `aksi.js` lama |

Tidak ada jenis hasil yang dibekukan dalam template baru. Kelompok bahan membaca semua bagian selain hasil; kelompok Hasil membaca bagian hasil dan riwayatnya. Tidak ada filter jenis pada riwayat detail lama yang perlu dipindahkan; pagination lama dipertahankan. Ringkasan tidak memakai daftar log yang dipaginasi.

## URL dan navigasi

- `/proses-aktif/sosoh/{kode}` dan alias `/proses-sosoh/{kode}` tetap melalui rute dan gerbang lama.
- `buka`, `nilai`, `kembali_kerja` dan parameter halaman tetap diterima. Aksi memakai pembentuk URL formulir lama.
- Tab memakai parameter tambahan `tab_detail`; GET biasa tetap berfungsi tanpa JavaScript. Tautan tab menghapus `buka/nilai` agar formulir yang sudah selesai tidak terbuka lagi, sambil mempertahankan konteks dan parameter halaman.
- Tanpa pilihan tab eksplisit, `halaman_hasil` membuka Hasil dan `halaman_jeda` membuka Riwayat.
- Fragmen `ringkasan-proses`, `tindakan-proses` → Ringkasan; `catatan-proses`, `bagian-1`/bagian sumber → Bahan & silo; bagian hasil, `halaman_hasil`, `kualitas-proses` → Hasil; `riwayat-jeda` → Riwayat. Skrip mencari panel yang memuat ID lama, bukan mengganti/menghapus ID-nya.
- Pendengar hash global dipasang melalui `PINDAH.pasang`; pendengar keyboard terikat elemen halaman. Perpindahan instan tidak menambah pendengar global lama.
- Proses selesai tetap dialihkan oleh rute lama, termasuk respons navigasi instan.

## Bukti pemeriksaan

Semua pengujian memakai klaster PostgreSQL baru di `/tmp/hmu-sosoh-pg`, loopback port 55449, database berawalan `uji_`. Skema dibangun oleh migrasi melalui fixture repository. Tidak memakai database operasional atau akun produksi. Checkout branch terpisah dibuat karena checkout utama sedang dipakai pekerjaan lain; commit hanya berkas tugas ini.

| Pemeriksaan | Hasil |
|---|---|
| Seluruh suite non-Postgres (`--ignore=tests/pg`) | 772 lulus, 6,62 detik pada integrasi main terbaru |
| Seluruh suite PostgreSQL (`tests/pg`) | 1.236 lulus, 453,34 detik; koleksi sebelum pembaruan main Pengaturan/katalog |
| Suite alur terarah pada checkout bersih | 153 lulus, 58,11 detik |
| Pemeriksaan final tab, selisih negatif, akses dan detail proses bersama | 19 lulus; setelah integrasi Pengaturan dan katalog main terbaru: 45 lulus, 23,56 detik |
| Browser langsung, Chromium 1440×1000 dan 390×844 | Empat tab bergantian, satu panel tampil, konteks bertahan, tanpa overflow horizontal |
| Pencatatan hasil saat dijeda | Total 4.400 lalu 4.600 kg; pertambahan terakhir 200 kg; mesin tetap dijeda |
| Klik ganda Simpan | Satu POST per pembaruan; tidak menghasilkan dua pencatatan |
| Lanjutkan | Waktu sekarang, pratinjau kejadian dan konfirmasi asli berhasil |
| Bebaskan silo | Wajib sisa fisik, pratinjau bahan/sisa, konfirmasi; sisa 100 kg tetap terisi dan proses tetap aktif |
| Selesaikan | Pratinjau asli, konfirmasi dan pengalihan `/riwayat-sosoh/1` berhasil |
| Tujuh tautan bagian lama | Panel yang sesuai terbuka pada browser langsung |
| Kesalahan JavaScript alur hasil | Tidak ada; bukti `live-browser.json` |
| Pemeriksaan sumber | Diff tidak mengubah layanan rumus/produksi/stok/API atau template proses lain; `git diff --check` lulus |

Suite terarah mencakup `test_proses_aktif_detail`, `test_bahan_silo_ringkas`, `test_jeda_ux`, `test_silo_selesai_aman`, `test_undo_tutup_sosoh`, `test_alur_proses_ux`, `test_gudang2_operator_pg`, `test_tambah_silo_berjalan`, `test_masukkan_beras_silo`, `test_silo_broken`, `test_riwayat_sosoh` dan `test_sesi_dicabut`. Suite non-Postgres mencakup neraca, kumulatif, CSRF dan sesi. Pengujian baru `test_detail_sosoh_tab` memeriksa tiga peran, gudang efektif melalui cookie, endpoint langsung, pagination 22 catatan, sumber total keseluruhan, ID unik, konteks, formulir lama, prioritas tindakan dijeda dan selisih negatif aktif.

Temuan browser yang diperbaiki: tautan tab semula mempertahankan `buka/nilai`, sehingga borang terbuka ulang setelah simpan. Pengujian sekarang memastikan tautan tab tidak membawa parameter borang. Tautan langsung pembuka formulir tetap diuji.

## Checklist penerimaan

Tanda centang berarti diperiksa melalui kombinasi penelusuran kode, suite alur yang disebutkan, dan browser; bukan klaim semua kombinasi data lapangan dicoba manual.

### A. Informasi dan navigasi
- [x] Empat tab tersedia desktop dan ponsel.
- [x] Identitas, pemilik, gudang, status jelas.
- [x] Seluruh informasi lama dipetakan ke tab.
- [x] Sumber, spesifikasi dan riwayat tetap tersedia.
- [x] Kembali ke Pekerjaan mempertahankan konteks.
- [x] Kontrol pratinjau tidak masuk produksi.

### B. Perhitungan
- [x] Total bahan memakai seluruh komposisi yang didukung layanan lama.
- [x] Hasil beras/samping dan rendemen memakai rumus lama.
- [x] Selisih aktif ditandai sementara.
- [x] Peringatan hasil melebihi bahan dan nilai negatif dipertahankan.
- [x] Kondisi belum diketahui tidak diganti nol pada template.
- [x] Pagination tidak mengubah total seluruh catatan; tidak ada filter baru.
- [x] Tidak ada rumus baru atau angka statis mockup.

### C. Bahan dan silo
- [x] Awal, tambahan, total, sisa dan status tersedia.
- [x] Asal bahan tidak dihitung ulang sebagai tambahan.
- [x] Seluruh pemakaian ulang dapat ditelusuri.
- [x] Isi sesudah pelepasan tidak mengganti sumber proses lama.
- [x] Pemeriksaan mix atas pemilik dan saldo tetap berlaku.
- [x] Penambahan/pemakaian ulang mengikuti layanan lama.

### D. Hasil produksi
- [x] Seluruh jenis dan spek lama tersedia.
- [x] Formulir menerima total kumulatif.
- [x] Pertambahan benar; 4.400 → 4.600 menghasilkan 200 kg.
- [x] Total baru/kirim ulang tidak menggandakan hasil atau stok.
- [x] Riwayat menampilkan pertambahan, waktu, spek dan pencatat.
- [x] Koreksi/pembatalan dan dampak stok mempertahankan mekanisme lama.

### E. Jeda dan waktu
- [x] Hentikan, lanjut dan perubahan kondisi tetap berfungsi.
- [x] Hasil tetap dapat dicatat saat dijeda sesuai izin.
- [x] Perubahan kondisi tidak melanjutkan mesin.
- [x] Waktu aktual dan alasan terlambat tetap divalidasi.
- [x] Kejadian dan pencatatan dibedakan.
- [x] Durasi efektif dan total jeda memakai sumber lama.
- [x] Riwayat dan penanda pembatalan tersedia.

### F. Pembebasan dan penyelesaian
- [x] Pembebasan meminta sisa fisik dan pratinjau.
- [x] Pembebasan tidak menutup proses.
- [x] Sisa nol/kosong dan bersisa dibedakan.
- [x] Penyelesaian mempertahankan syarat lama.
- [x] Konfirmasi memeriksa cuplikan terbaru dan kirim ulang.
- [x] Proses selesai membuka detail riwayat yang benar.

### G. QC dan hak akses
- [x] Informasi QC yang tersedia tetap dipertahankan.
- [x] Tidak ada fungsi QC baru dari mockup.
- [x] Produksi tidak disajikan sebagai pengukuran QC.
- [x] Admin, Super Admin dan operator diuji.
- [x] Gudang kerja efektif menentukan akses operator.
- [x] Endpoint langsung menolak pengguna tanpa izin.

### H. Integrasi dan regresi
- [x] URL lama, buka/nilai dan konteks kembali tetap berfungsi.
- [x] Fragmen lama membuka panel/rincian sesuai.
- [x] Pagination dan tab mempertahankan konteks.
- [x] Navigasi instan tidak menumpuk pendengar.
- [x] Formulir tidak terkirim/tercatat dua kali.
- [x] CSRF dan perubahan sesi tetap dijaga.
- [x] Detail pengeringan, pendinginan dan giling lulus regresi.
- [x] Uji memakai lingkungan terisolasi tanpa data operasional.
- [x] Suite repository relevan telah dijalankan.

## Tangkapan dan batas verifikasi

Tangkapan browser aplikasi langsung tersimpan lokal di `produksi/output/detail-sosoh/`: `desktop-ringkasan.png`, `ponsel-ringkasan.png`, serta pasangan `desktop/ponsel-{bahan,hasil,riwayat,jeda}.png`. `live-browser.json` mencatat jumlah POST kumulatif dan tidak adanya galat JS; `finish-browser.json` mencatat pratinjau dan pengalihan akhir. Berkas sesi/token uji tidak disertakan dalam commit.

Belum diverifikasi: perangkat ponsel fisik, Safari/iOS, seluruh ukuran layar dan seluruh kombinasi data operasional. Tidak menulis data produksi untuk pengujian. Bukti visual memakai Chromium pada dua ukuran di atas; suite layanan/API mendukung klaim stok, waktu, perhitungan dan izin. Daftar lengkap suite PostgreSQL dikoleksi sebelum pembaruan main Pengaturan/katalog; pemeriksaan integrasi final diulang setelah perubahan remote itu dimasukkan.
