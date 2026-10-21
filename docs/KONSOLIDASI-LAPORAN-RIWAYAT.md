# Konsolidasi Laporan & Riwayat

Status: v399 telah diizinkan pengguna untuk push dan deploy setelah seluruh
pemeriksaan lulus. Hasil pemeriksaan lokal tercatat di bawah; pemeriksaan
CI dan aplikasi produksi menjadi gerbang rilis berikutnya.
Inventaris dibuat sebelum perubahan dengan acuan v397 (`7926083`).

## Batas perubahan

Satu pintu sidebar, empat tab, pilihan jenis di area utama. URL operasional
lama tetap digunakan, termasuk detail, PDF, API laporan, POST koreksi dan
pembatalan. Tidak ada agregasi tahap baru, perubahan layanan saldo atau skema.
Mockup dipakai untuk susunan, bukan data, rumus atau kewenangan.

## Inventaris dan pemetaan lengkap

| Fungsi lama | Lokasi baru | Perilaku yang dipertahankan |
|---|---|---|
| `/laporan` | Laporan | Tujuh pilihan di bawah, sesuai `daftar_untuk`; isi dimuat dari API lama di lembar laporan |
| Menunggu verifikasi | Laporan | `pending_verifikasi`, tanpa periode; laporan kerja |
| Riwayat produksi | Laporan | `produksi`; hari ini, kemarin, minggu ini, bulan ini, 30 hari, semua |
| Jam kedatangan gabah | Laporan | `jam_kedatangan`, tanpa periode; laporan kerja |
| Pembelian gabah | Laporan | `pembelian_gabah`, berperiode; hak informasi finansial |
| Rapor supplier | Laporan | `supplier`, hak informasi finansial |
| Rekap bulanan | Laporan | `rekap_bulanan`, hak informasi finansial |
| Analisa musiman | Laporan | `musiman`, hak informasi finansial |
| `/riwayat-pengeringan` | Proses → Pengeringan | Terbaru dahulu, 30/kursor `sebelum`, bahan basah/final, KA target/terakhir, waktu, silo, pemilik dan asal batch |
| `/riwayat-giling` | Proses → Penggilingan | Terbaru dahulu, 30/kursor; bahan, PK, rendemen, mutu, tersedia/ditransfer, pemilik, asal dan riwayat silo |
| `/riwayat-sosoh` | Proses → Penyosohan | Terbaru dahulu, 30/kursor; bahan, hasil per jenis, samping, susut, pemilik dan sumber campuran; tidak menjumlah lintas tahap |
| `/riwayat-transfer` | Proses → Transfer | Terbaru dahulu, 30/kursor; sumber/tujuan, kirim/terima/selisih, status dan pemilik |
| Detail empat proses | Proses → catatan jenis yang sama | Semua fakta, jejak jeda, asal, riwayat penggunaan ulang silo, tautan QC dan referensi lama |
| Koreksi giling, sosoh, transfer | Detail Proses | Form, angka awal, alasan, snapshot konflik, penghalang hilir, pemulihan gagal dan POST lama; admin sesuai gerbang lama |
| Lihat/bagikan/unduh PDF pengeringan, giling, sosoh | Detail Proses → laporan | Halaman laporan, PDF inline dan `unduh=1`; isi/rumus/jeda/sumber lama. Transfer tidak memiliki PDF khusus pada v397 |
| `/riwayat-qc/gabah-basah` | QC → Gabah basah | QC Gudang 1, parameter sampel dan seluruh putaran |
| `/riwayat-qc/gabah-kering` | QC → Gabah kering | QC Gudang 1, parameter sampel dan seluruh putaran |
| `/riwayat-qc/pk-hasil-giling` | QC → PK hasil giling | QC Gudang 1, skor dan kategori kualitas lama |
| `/riwayat-qc/pk-luar` | QC → PK luar | QC Gudang 2, skor dan kategori kualitas lama |
| `/riwayat-qc/beras-hasil-sosoh` | QC → Beras hasil sosoh | QC Gudang 2, parameter dan putaran lama |
| Detail QC `/{referensi}` | QC → catatan terkait | Query detail sebelum batas daftar, seluruh putaran, pemeriksa/waktu, asal/plat, aturan skor; referensi lama tidak terhalang batas 200 |
| Daftar QC | QC → jenis terkait | Batas 200 pencatatan terbaru mengikuti perilaku lama; tanpa filter tanggal/pencarian/pagination baru |
| `/audit` | Audit | Rentang 48 jam/24 jam/semua, kelompok lama, pencarian kode/pemasok/isi; 200 catatan, hitungan keseluruhan lama |
| Pratinjau terakhir dan `/audit/batalkan` | Audit | `log_id`, batas waktu, dukungan tindakan dan dependensi, alasan terkunci, pesan hasil, filter saat kembali; tidak menambah kewenangan |
| Tautan List audit di Pengaturan | Audit melalui alamat lama | Tetap berfungsi dan dijaga `butuh_admin` |

Daftar proses tidak memiliki filter tanggal, pencarian atau pengurutan bebas
pada v397. QC tidak memiliki formulir edit di halaman riwayat; tindakan QC
operasional tetap berada di Pekerjaan/formulir lama. Tidak ditambahkan fitur
baru dengan nama filter/formulir yang seolah sudah ada. Jumlah pada statistik
proses/QC tetap cakupan halaman lama, bukan klaim total semua halaman.

## Gerbang lama

| Peran efektif | Laporan | Proses | QC | Audit |
|---|---|---|---|---|
| Super Admin / Admin | Semua sesuai `boleh_lihat` | Empat jenis | Lima jenis | `butuh_admin` |
| Operator Gudang 1 | Tiga laporan kerja | Pengeringan, penggilingan, transfer | Gabah basah/kering, PK hasil giling | Ditolak |
| Operator Gudang 2 | Tiga laporan kerja | Penyosohan | PK luar, beras hasil sosoh | Ditolak |

Hak memakai peran efektif dan gudang aktif, termasuk “lihat sebagai”. Daftar
tab/jenis bukan pengganti gerbang GET, PDF, API, POST koreksi atau undo.

## Rencana bukti

- Database khusus `uji_laporan398_browser`, salinan dari simulasi lokal;
  pengujian integrasi memakai database terpisah `uji_jasa392`.
- Snapshot sumber v397 dan data sebelum ada di `output/laporan398/sebelum/`.
- Bandingkan data/akun/periode/kursor/filter sama; API dan reader lama
  dibanding sebelum–sesudah. Dokumen dan tindakan melalui uji regresi lama.
- Empat akun uji riil lokal, mode lihat sebagai, URL langsung/API, serta
  ponsel/desktop dua tema. Hasil per butir dilengkapi setelah dijalankan.
- Tidak deploy/push sebelum tinjauan pengguna.

## Hasil implementasi

- Menu sidebar tunggal **Laporan & Riwayat**, ikon SVG monokrom padanan
  `chart-no-axes-combined`, ukuran 20 px dan stroke 1,9 mengikuti ikon SVG
  aplikasi. Penanda aktif mengikuti halaman daftar, detail dan laporan PDF.
- Tab **Laporan / Proses / QC / Audit**; jenis proses/QC hanya yang diizinkan
  gerbang lama. Judul daftar tetap **Riwayat Proses** dan **Riwayat QC**.
- URL lama tetap menjadi sumber halaman. `/laporan-riwayat` adalah pintu
  pengalihan, bukan reader atau salinan data kedua. Query/kursor diteruskan.
- Navigasi tab/jenis memakai tautan asli dan navigasi utuh supaya URL,
  tombol Back serta inisialisasi lembar laporan tidak saling mendahului.
- Statistik daftar dipadatkan; tabel desktop dan daftar ponsel lama tetap
  dipakai; audit mendapat tabel desktop. Detail memanfaatkan seluruh lebar
  area utama. Tabel yang lebih lebar bergulir di wadahnya.
- Filter audit diberi nama aksesibel dan `autocomplete=off`, agar pencarian
  yang dipulihkan melalui Back sesuai URL yang digunakan.
- Nama pencatat QC gabah dan hasil giling kini dibaca dari `input_by` yang
  sudah ada. Tidak menebak nama petugas dari penerima atau pemeriksaan lain.
- Pesan gagal laporan berbahasa Indonesia; **Tutup** tetap aktif saat offline.
  Pengecualian offline hanya diberikan pada tombol baca-saja ini. Tombol
  pencatatan tetap mengikuti pengaman jaringan semula.
- Halaman PDF pengeringan/giling/sosoh menyatakan kegagalan memuat dokumen
  dengan jelas dan tetap menyediakan pemulihan/tautan lama.
- Sumber komponen bersama di `tampilan/`, versi dinaikkan ke **399**, lalu
  disinkronkan melalui `scripts/sinkron.py`; salinan vendored tidak diedit.

## Data dan akun penguji

Database browser: `uji_laporan398_browser` pada loopback port 55443, salinan
simulasi lokal. Database integrasi: `uji_jasa392`, terpisah dari browser.
Tidak ada koneksi/tindakan pencatatan terhadap database operasional.

| Akun uji yang benar-benar masuk melalui browser | Peran/gudang | Hasil |
|---|---|---|
| `lap398_superadmin` | Super Admin | 7 laporan, 4 proses, 5 jenis QC, Audit |
| `lap398_admin` | Admin | 7 laporan, 4 proses, 5 jenis QC, Audit |
| `lap398_g1` | Operator Gudang 1 | 3 laporan kerja, pengeringan/giling/transfer, 3 QC G1; Audit dan laporan uang ditolak |
| `lap398_g2` | Operator Gudang 2 | 3 laporan kerja, sosoh, 2 QC G2; Audit, giling G1 dan laporan uang ditolak |

Contoh pada pembandingan dan browser:

- Pelanggan **Catur Uji 392**, pesanan **JAS-392-001**.
- Pengeringan **PGR-392-01**, giling **LOT-392-1 / LOT-392-2**, transfer
  **TRF-20261021-01 / TRF-20261021-02**, sosoh **POL-20261021-01**.
- QC **GB-394-GULIR-22**, tiket **TRX-394-GULIR-22**, dua putaran;
  uji integrasi **GB-QC-BASAH / GB-QC-KERING** lima putaran dan
  **LOT-QC-DETAIL** tiga putaran, termasuk data di luar batas daftar.
- Bahan penggilingan 12.000 kg → PK 7.000 kg pada dua proses; hasil sosoh
  beras 6.500 kg dan samping 3.200 kg; pengeluaran 2.000 kg. Nilai setiap
  tahap tetap terpisah, sama dengan pembanding, bukan satu total gabungan.

## Bukti yang dapat diulang

Semua berkas berikut relatif terhadap repo `produksi/`:

| Bukti | Isi |
|---|---|
| `output/laporan398/sebelum.json` | 57 pemeriksaan URL/API/PDF × 4 akun, reader empat proses dan audit, hash 99 tabel sebelum perubahan |
| `output/laporan398/sesudah.json`, `paritas.json` | Pembandingan pertama: seluruh 99 tabel dan semua hasil baca identik |
| `output/laporan398/final.json`, `paritas-final.json` | Pembandingan akhir: reader, akses, isi laporan API dan PDF tetap identik; 98 tabel identik, hanya `produksi_akun` berubah karena login uji (`terakhir_login`) |
| `output/laporan398/pg-final.xml` | **106 uji integrasi terkait lulus**, tanpa skip/error/failure |
| `output/laporan398/regresi-modul.xml` | **81 uji regresi Stok, Barang Masuk/Pekerjaan, Jasa lulus**, tanpa skip/error/failure |
| `output/laporan398/nonpg-final.xml` | **753 uji non-PostgreSQL Produksi lulus**, tanpa skip/error/failure |
| `output/laporan398/tampilan-final.xml` | **398 uji paket tampilan lulus**, tanpa skip/error/failure |
| `output/laporan398/pdf-final.xml` | Pemeriksaan tambahan setelah penyelarasan pesan gagal PDF |
| `output/laporan398/browser/matrix.json` | Browser 390×844 / 1440×1000, empat tab × dua tema, akun, laporan yang dibuka |
| `output/laporan398/browser/pdf-gagal.json` | Empat halaman laporan, tiga jenis proses, HTTP 503 yang sengaja disimulasikan pada endpoint PDF; pesan pemulihan terlihat |
| `output/laporan398/browser/*-*.png` | Tangkapan layar daftar, detail, akun dan kegagalan lokal |

PDF dibandingkan melalui teks setiap halaman. Hanya waktu **Dicetak** yang
dinormalisasi; tanggal/waktu proses, QC, jeda, angka, satuan, sumber dan
identitas tetap dibandingkan penuh. Tidak ada pengecualian angka laporan.

## Checklist serah terima

**Lulus** berarti butir diuji pada fungsi/cakupan yang memang tersedia di
v397. Fitur yang sebelumnya tidak ada disebutkan secara eksplisit, bukan
ditambahkan diam-diam atau diklaim sudah tersedia.

| Butir | Hasil | Bukti dan batas cakupan |
|---|---|---|
| 1.1 Empat halaman/fungsi mendapat lokasi | Lulus | Pemetaan lengkap di atas; 4 tab browser |
| 1.2 Menu/tab/tindakan sesuai izin | Lulus | Empat akun browser, `test_laporan_navigasi`, 228 pemeriksaan sebelum–sesudah |
| 1.3 Ikon dan menu aktif | Lulus | SVG 20 px, tangkapan layar dua tema; aktif di daftar/detail |
| 1.4 URL lama, query, bookmark, referensi notifikasi | Lulus | Rute lama tidak dihapus; GET lama tetap cocok; gateway meneruskan kursor dan query audit |
| 1.5 Detail lalu kembali | Lulus | Jenis/induk lama tetap benar; tautan kembali asli dan Back; perilaku kembali ke halaman daftar terbaru tidak diubah menjadi filter baru |
| 2.1 Seluruh filter lama | Lulus | Enam periode laporan; audit rentang/kelompok/cari; kursor proses tetap |
| 2.2 Filter hanya digabung jika bermakna sama | Lulus | Filter masing-masing tab tetap terpisah; tidak ada periode QC/proses baru |
| 2.3 Rentang, batas hari, zona waktu | Lulus | Seluruh periode API dibandingkan dan unit `_rentang`; PDF/riwayat memakai `jam` lama |
| 2.4 Kombinasi, cari, urut, pagination, reset | Lulus | Audit cari OUT→kosong→Back; muat ulang; empat uji kursor proses. Urutan tetap terbaru dahulu; tidak ada sortir bebas sebelumnya |
| 2.5 Jumlah/total lintas halaman | Lulus | Reader dan jumlah sama; uji pagination; statistik proses menyebut halaman ini. Audit `semua` mengikuti hitungan lama, bukan dihitung ulang dari tabel tampilan |
| 2.6 Kosong | Lulus | QC tanpa data dan audit tanpa kecocokan, navigasi tetap tersedia |
| 2.7 Memuat/gagal | Lulus | Tujuh laporan dibuka; pemutusan server lokal; pesan Indonesia, Tutup aktif, aksi lain tetap dinonaktifkan |
| 3.1 Semua jenis/rincian laporan | Lulus | Tujuh tombol browser dan semua endpoint di empat peran |
| 3.2 Sumber/rumus/satuan/pembulatan/null | Lulus | API, reader, teks PDF sebelum–sesudah identik; layanan hitungan tidak diedit |
| 3.3 Belum dicatat berbeda dengan nol | Lulus | Uji PDF sisa belum dicatat dan uji riwayat hasil belum tercatat tetap lulus |
| 3.4 Ringkasan cocok dengan rincian | Lulus | Reader sumber dan API/PDF pembanding; kasus campuran dan asal ulang di `test_pdf_konsisten` |
| 3.5 Tidak menghitung ganda lintas tahap | Lulus | PK dan hasil sosoh tetap pembacaan terpisah; tidak ada reader/agregasi baru |
| 3.6 Koreksi/pembatalan/retur | Lulus | Uji koreksi sesi aman, undo tepat/cakupan/sosoh, dan regresi stok/Jasa; layanan laporan lama tetap |
| 3.7 Saldo/transaksi tidak berubah | Lulus | Hash seluruh tabel; hanya metadata login akun uji berubah setelah browser |
| 4.1 Empat riwayat proses lengkap | Lulus | GET lama, reader identik, suite pengeringan/giling/sosoh/transfer |
| 4.2 Detail fakta/hasil/waktu/status | Lulus | Suite masing-masing proses dan browser detail; lebar detail sama dengan area utama |
| 4.3 Tiket/lot/Jasa/sumber campuran/hasil | Lulus | Data Catur, dua sumber giling dan PK luar, `test_pdf_konsisten`, regresi Jasa |
| 4.4 Susut/rendemen/ketidaktersediaan | Lulus | Reader/PDF sama; uji sisa belum dicatat dan hasil melebihi bahan |
| 4.5 Tindakan/form lama | Lulus | Koreksi dan konflik, dependensi hilir, jeda serta pembatalan diuji melalui layanan/rute asli |
| 5.1 Jenis dan parameter QC | Lulus | Lima tujuan, empat reader tersedia; QC beras hasil sosoh memang belum memiliki log pada versi lama, pesan ketidaktersediaannya dipertahankan |
| 5.2 Putaran/pemeriksa/waktu/histori | Lulus | Dua putaran browser, lima/tiga putaran integrasi, termasuk di luar batas 200; pencatat dari FK aktual |
| 5.3 Rumus/kelas/validasi/pengaturan | Lulus | Skor dan aturan lama tidak diedit, tes penilaian/QC dan konfigurasi non-PG; riwayat tidak diubah menjadi tindakan QC baru |
| 5.4 Tautan QC ke asal | Lulus | Referensi/asalan/plat dan tautan detail yang tersedia tetap benar; tidak mengarang hubungan baru ketika versi lama hanya menyimpan teks asal |
| 5.5 Form/field/default/error/tindakan QC | Lulus | Tidak ada form edit baru di riwayat; form operasional Pekerjaan tetap; regresi Pekerjaan lulus |
| 6.1 Cetak/unduh/ekspor tersedia | Lulus | Halaman PDF, inline dan attachment tiga proses tetap 200 sesuai izin; tidak ada ekspor daftar/CSV atau PDF transfer pada v397 |
| 6.2 Dokumen mengikuti filter/izin | Lulus | PDF tetap per ID proses, bukan filter tabel; semua enam periode laporan dibanding; operator gudang lain ditolak |
| 6.3 Isi/nomor/tanggal/angka/format | Lulus | Teks setiap halaman PDF cocok, unit renderer dan uji asal/jeda; waktu cetak saja dinormalisasi |
| 6.4 Data halaman berikutnya | Lulus | PDF per catatan tidak memakai batas daftar; QC detail di luar batas 200 diuji; tidak ada ekspor daftar multi-halaman pada versi lama |
| 6.5 Kegagalan dokumen | Lulus | Simulator GET-only memberi 503 pada PDF; empat halaman tetap terbuka, pesan gagal/pemulihan dan tautan lama tersedia |
| 7.1 Audit lengkap | Lulus | ID/aktivitas/isi/pelaksana/waktu/status lama sama; reader audit sebelum–sesudah identik |
| 7.2 Filter/rujukan audit | Lulus | Rentang/kelompok/cari serta nomor/ref lama dipertahankan; versi lama tidak memiliki halaman detail audit mandiri |
| 7.3 Hak baca/detail/dokumen/koreksi/undo | Lulus | Matriks HTTP empat akun, API finansial, PDF dan suite koreksi/undo |
| 7.4 Empat akun/gudang | Lulus | Empat akun database benar-benar login lewat browser; pembandingan 57 URL per akun |
| 7.5 URL/API langsung | Lulus | Audit 403 untuk operator, giling G1 403 bagi G2; API uang 403; gateway tidak melompati gerbang |
| 7.6 Audit hanya pemegang izin lama | Lulus | Tab Audit hanya `akun.is_admin`, rute tetap `butuh_admin`, termasuk lihat sebagai operator |
| 8.1 Desktop rapi | Lulus | 1440×1000 dua tema, empat tab, detail penuh; overflow halaman 0; tabel lebar bergulir di wadah |
| 8.2 Keyboard/fokus/tema | Lulus | Tautan asli, fokus terlihat, select laporan dan Tutup dapat dipakai keyboard; dua tema browser dan paket tampilan |
| 8.3 Ponsel | Lulus | 390×844 dua tema, empat tab, pilihan jenis bergulir mendatar, dua putaran QC dan detail proses |
| 8.4 Modul/konsolidasi sebelumnya | Lulus | 81 regresi PG Stok/Pekerjaan/Jasa, 753 non-PG, 398 paket; tautan Stok→Laporan kembali tetap berfungsi |

## Keterbatasan yang tetap dinyatakan

- **Belum diuji:** pencetakan ke printer fisik dan pengiriman lewat aplikasi
  berbagi eksternal pada ponsel sungguhan. Verifikasi dokumen di atas mencakup
  pembentukan, isi, inline/attachment, izin dan jalur gagal; tidak mengklaim
  kertas tercetak atau file telah dikirim ke orang lain.
- Pemeriksaan ponsel memakai viewport browser 390 px, bukan pengujian
  perangkat fisik di bawah matahari.
- QC beras hasil sosoh, PDF transfer, ekspor CSV/daftar, sortir bebas dan
  detail audit mandiri tidak tersedia pada v397; tidak dibuat dalam tahap ini.
- Pembatas lama 30/kursor proses, 200 QC/audit, serta cakupan hitungan audit
  dipertahankan. Konsolidasi ini bukan perubahan cakupan laporan.
- Tidak ada perubahan skema, layanan stok atau transaksi. Perubahan lokal
  yang sudah ada, termasuk tiga skrip audit uji, dipertahankan.
- Deploy telah diizinkan pengguna. Pemeriksaan produksi hanya membaca halaman,
  laporan dan dokumen; tidak menyimpan tindakan operasional.
