# Fondasi multi-perusahaan — tahap awal

Status 12 November 2026: persiapan, bukan pengaktifan multi-perusahaan.
PadiFlow dan TeraFlow masih memakai satu kumpulan data bisnis. Tahap ini
menyediakan inventaris, pembanding perilaku lama, dan identitas fasilitas
baca-saja. Tidak ada migrasi atau perubahan hitungan stok, izin, maupun
transaksi produksi.

## Aturan yang sudah disepakati

- Setiap perusahaan mempunyai identitas stabil yang sama di PadiFlow dan TeraFlow.
- Perusahaan mempunyai banyak lokasi pabrik. Setiap lokasi mempunyai banyak
  gudang/tempat produksi; setiap gudang mempunyai banyak line/alat sejenis
  maupun berbeda. Hubungannya relasi data, bukan pewarisan kelas.
- Produk, spesifikasi, hasil samping, kemasan, pelanggan, dan pemasok dapat
  berbeda per perusahaan. Kontak/nama/kode yang sama tidak menyatukan kepemilikan.
- Operator mengikuti gudang kerja yang dipilih dalam perusahaan yang diizinkan.
- Perusahaan pengelola berbeda dengan pemilik barang: barang jasa tetap milik
  pelanggan sesuai transaksi dan pengalihan yang sah.
- Bobot, jumlah, tanggal, status, pemilik, snapshot dan audit lama dipertahankan.
  Migrasi penanda perusahaan di tahap berikutnya harus dirancang dan diaudit.

## Peta pekerjaan dan pemanggil

Kolom status membedakan master yang sudah dinamis dari pembatas bisnis yang
masih berada di kode. Literal untuk membaca riwayat bukan otomatis boleh dihapus.

| Area | Sumber/pemanggil | Kondisi dan pekerjaan berikutnya |
|---|---|---|
| Identitas perusahaan | `hmu_dokumen/perusahaan.py`, `app/services/perusahaan.py`, `app/web/perusahaan.py` | Satu kunci global; butuh master perusahaan dan pengaturan per perusahaan. |
| Pelanggan/pemasok | `hmu_core/models.py`, `hmu_core/kledo_kontak.py`, `app/services/kledo_sinkron.py` | Master dan pencocokan kontak global; perlu pembatas perusahaan sebelum sinkron. |
| Pengguna dan akses | `hmu_identitas/model.py`, `hmu_identitas/peran.py`, `app/web/security.py`, `app/services/cakupan_fasilitas.py` | Peran dan konteks gudang belum mempunyai keanggotaan perusahaan. |
| Lokasi pabrik | Belum ada master lokasi pabrik; rancangan membutuhkan `lokasi_pabrik_id` | Satu perusahaan dapat mempunyai beberapa lokasi. Alamat operasional, zona waktu, pos timbang, printer dan akses lokasi perlu dipetakan. |
| Gudang dan fasilitas | `hmu_core/models.py`, `app/models/fasilitas.py`, `app/services/fasilitas.py` | Line sudah eksplisit; kode fungsi gudang masih unik global. |
| Tampilan fasilitas | `app/services/identitas_fasilitas.py`, `app/services/proses_aktif.py`, `app/web/giling_ringkas.py`, `app/web/sosoh_ringkas.py` | Objek identitas baca-saja menjadi sumber label; pembaca string lama tetap tersedia. |
| Produk/spesifikasi | `app/services/spesifikasi_beras.py`, `hmu_core/models.py` | Master sudah dinamis tetapi masih global. |
| Hasil samping | `app/services/jenis_hasil_samping.py`, `app/models/system.py` | Master dinamis di `setelan_pabrik`; kunci dan pencarian pemakaian belum dibatasi perusahaan. |
| Kemasan/SKU | `app/penggilingan/inventory/packaging.py`, `app/penggilingan/inventory/models.py` | Kombinasi dan ukuran beras masih dibatasi daftar kode; master belum per perusahaan. |
| Silo dan penerimaan | `app/penggilingan/silo_policy.py`, `app/penggilingan/peta_jenis.py`, `app/services/barang_masuk_daftar.py` | Routing dan fallback lama masih mengenal g1/g2 serta keluarga komoditas tetap. |
| Transfer | `app/services/pengiriman_pk.py`, `app/web/pengiriman_pk.py`, TeraFlow `lintasan_transfer.py` | Jalur lama khusus G1 ke G2; digeneralisasi setelah cakupan gudang dan perusahaan tersedia. |
| Pelaksana proses | `app/services/fasilitas.py:PENJALAN` | Tiga engine proses; menambah label jenis belum menyediakan engine baru. |
| Stok/kepemilikan | `app/services/stok.py`, `app/services/pk_persediaan.py`, `app/services/kepemilikan.py` | `jasa_id=None` berarti pabrik; harus tetap dipisahkan dari perusahaan pengelola. |
| Portal/dokumen | `app/models/portal.py`, `app/web/portal/security.py`, `app/web/pdf_periode.py`, `app/web/identitas_dokumen.py` | Pembaca dan identitas dokumen perlu cakupan perusahaan; snapshot lama dipertahankan. |
| Nomor/audit/pembaruan | `app/models/system.py`, `app/services/activity_log.py`, `app/performa.py` | Penomoran, audit, notifikasi, dan kunci cache perlu konteks perusahaan. |
| Integrasi/luring/printer | TeraFlow `app/config.py`, `klien_produksi.py`, `static/luring.js`, `static/sw.js`, `static/app.js` | Sambungan, konteks kiriman, cache dan printer perlu terikat perusahaan/lokasi. |
| Instalasi awal | `app/services/seed.py`, `app/seed.py`, `app/services/fasilitas.py:seed_fasilitas` | Template G1/G2 adalah konfigurasi instalasi lama; jangan diterapkan sebagai aturan seluruh perusahaan. |

Sumber bersama `hmu_core`, `hmu_identitas`, `hmu_dokumen`, dan `hmu_tampilan`
harus diubah melalui repositori sumber serta prosedur sinkronisasinya, bukan
mengubah satu salinan vendor saja. Kontrak database bersama perlu diuji kedua aplikasi.

## Pembagian kelas

| Kelas/objek | Tanggung jawab | Status |
|---|---|---|
| `Warehouse`, `LiniProduksi`, `JenisProsesProduksi` | Identitas dan relasi fasilitas yang tersimpan | Sudah ada; dipertahankan. |
| `IdentitasFasilitas` | ID/nama gudang dan line untuk tampilan, immutable, tanpa izin/perhitungan | Diterapkan di tahap ini. |
| `KonteksGudang` | Konteks gudang efektif yang sudah dipakai pembaca | Sudah ada; perubahan izin di luar tahap ini. |
| Model perusahaan, lokasi pabrik dan keanggotaan | Perusahaan, banyak lokasi pabrik, serta peran dan akses pengguna pada perusahaan/lokasi | Rancangan tahap berikutnya, belum diaktifkan. |
| `KonteksKerja` | Konteks immutable perusahaan, lokasi pabrik, pengguna dan gudang aktif yang sudah diverifikasi server | Tahap akses; bukan percaya pada company_id dari formulir. |
| Kebijakan komoditas/pengemasan | Aturan bisnis berversi per perusahaan; hasil validasi terstruktur | Setelah master per perusahaan; tidak mengubah saldo langsung. |
| Snapshot lintasan/dokumen | Identitas dan aturan saat transaksi; kontrak berversi lintas aplikasi | Pertahankan JSON lama; penguatan tipe harus menjaga serialisasi. |
| Konteks integrasi | Perusahaan dan otorisasi koneksi, tanpa membocorkan rahasia ke browser | Setelah cakupan perusahaan tersedia. |

Fungsi perhitungan stok yang sudah teruji tetap mempunyai kontrak dan jalur
penulisan sekarang. Pemindahan ke kelas dilakukan ketika tanggung jawab serta
pemanggilnya jelas; satu objek besar untuk seluruh aplikasi akan menyulitkan audit.
`IdentitasFasilitas` tidak boleh dipakai sebagai bukti hak akses.

## Pembanding yang dapat dijalankan ulang

Semua uji PostgreSQL mewajibkan alamat loopback dan nama database `uji_*`.
Gunakan database kosong khusus uji. Fixture memang membuat dan menghapus data
uji; jangan memakai cadangan produksi sebagai database yang sedang digunakan aplikasi.

```sh
UJI_PG_URL=postgresql+asyncpg://USER@127.0.0.1:PORT/uji_fondasi \
python -m pytest -m fondasi_multi \
  tests/pg/test_identitas_fasilitas.py \
  tests/pg/test_fasilitas.py \
  tests/pg/test_cakupan_fasilitas.py \
  tests/pg/test_master_rantai_dinamis.py \
  tests/pg/test_master_samping_rantai.py \
  tests/pg/test_portal_stok_karung.py --junitxml=bukti/fondasi-padiflow.xml
```

Pembanding memakai jalur asli: campuran 1.000 kg PK, 100 kg beras, 50 kg menir,
25 kg reject dan 75 kg broken menghasilkan 1.250 kg bahan silo. Pemakaian
1.150 kg, sisa 100 kg dan hasil beras 1.000 kg diperiksa untuk kepemilikan
pabrik maupun jasa. Skenario lain menjaga replay penerimaan, saldo kemasan,
alokasi, dua line, batas operator, dan pembacaan portal tanpa penulisan tabel.

Integrasi pengiriman PK nyata memakai proses HTTP kedua aplikasi:

```sh
UJI_TF_ROOT=/path/ke/timbangan \
UJI_TF_PYTHON=/path/ke/interpreter-teraflow \
UJI_PG_URL=postgresql+asyncpg://USER@127.0.0.1:PORT/uji_tf_kiriman_fondasi \
python -m pytest -m fondasi_multi tests/pg/test_pengiriman_pk_dua_aplikasi.py \
  --junitxml=bukti/fondasi-integrasi.xml
```

Uji integrasi ini dilewati bila source/interpreter TeraFlow tidak tersedia;
hasil yang dilewati bukan bukti integrasi lolos. CI lengkap yang sudah ada
tetap menjadi pemeriksaan rilis, termasuk profil WebKit/iPhone.

## Batas tahap dan urutan berikutnya

1. Lengkapi inventaris dan pembanding, rapikan label dari relasi nyata (tahap ini).
2. Rancang master perusahaan, lokasi pabrik dan keanggotaan bersama; uji migrasi metadata pada salinan terisolasi.
3. Terapkan cakupan master, akses, lokasi pabrik, gudang, transaksi, portal serta integrasi bertahap.
4. Uji dua perusahaan, masing-masing dua lokasi dan beberapa gudang/line,
   kode/nama sama, transfer dalam lokasi dan antarlokasi, line bersamaan, konflik stok,
   gangguan jaringan, pergantian konteks, koreksi dan pembatalan.
5. Verifikasi saldo, bobot, jumlah, tanggal, pemilik, snapshot serta audit lama
   sebelum mengaktifkan perusahaan kedua.

Belum ada klaim isolasi perusahaan pada tahap ini. Mengisi satu kolom company_id
saja belum menyediakan pemisahan akses, relasi, cache, maupun proses latar.

## Hierarki lokasi yang harus diterapkan sebelum aktivasi

```text
Perusahaan (company_id)
└── Lokasi pabrik (lokasi_pabrik_id)
    ├── Pos timbang / profil perangkat
    └── Gudang atau tempat produksi (warehouse_id)
        └── Line atau alat (lini_id)
```

Master barang, pelanggan dan pemasok milik perusahaan; saldo serta alokasinya
berada pada lokasi/gudang nyata. Gudang penyimpanan boleh tidak memiliki line.
Line sejenis dapat berada di beberapa gudang pada lokasi yang sama atau berbeda.
Sistem tidak boleh menyimpulkan perusahaan/lokasi dari nama, awalan kode, atau
urutan ID. Hubungan perusahaan–lokasi–gudang–line harus divalidasi server dan
dijaga integritas relasinya. Nama gudang/line yang sama pada lokasi berbeda sah.

Transfer perlu membedakan asal dan tujuan yang sebenarnya, termasuk antarlokasi
dalam perusahaan yang sama. Perpindahan antarperusahaan memerlukan transaksi
bisnis yang jelas dan hak akses tersendiri. Kiriman tertunda tetap terikat
perusahaan/lokasi/gudang asal saat dibuat. Dokumen memisahkan penerbit perusahaan
dari alamat lokasi operasional. Alamat lama pada snapshot tidak ditulis ulang.

Pilihan konteks kerja mengikuti perusahaan dan lokasi yang diizinkan. Bila
pilihan hanya satu boleh otomatis; bila lebih dari satu, pengguna memilih atau
melanjutkan konteks terakhir yang masih sah. Pergantian konteks tidak boleh
memindahkan formulir lama atau antrean kiriman ke perusahaan/lokasi baru.

`IdentitasFasilitas` tahap awal baru membaca relasi gudang dan line yang memang
sudah tersimpan. Tidak ada ID lokasi pabrik/perusahaan karangan atau migrasi
untuk menebak lokasi transaksi lama.
