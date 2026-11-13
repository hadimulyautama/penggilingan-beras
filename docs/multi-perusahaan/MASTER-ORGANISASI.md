# Tahap 2: master organisasi bersama

13 November 2026. Tahap ini menambah struktur kosong dan kontrak pembacaan;
pemilihan perusahaan serta pembatasan transaksi belum diaktifkan pada aplikasi.

## Model dan aturan relasi

| Class bersama | Tabel | Identitas dan batas |
|---|---|---|
| `Perusahaan` | `hmu_companies` | `id` menjadi `company_id` kedua aplikasi; kode unik, nama boleh sama. |
| `LokasiPabrik` | `hmu_factory_sites` | Milik tepat satu perusahaan; kode unik dalam perusahaan. Nama/kode boleh sama di perusahaan lain. |
| `PenempatanGudang` | `hmu_warehouse_sites` | Satu gudang berada pada satu lokasi; FK gabungan menjaga lokasi dan perusahaan cocok. |
| `KeanggotaanPerusahaan` | `hmu_company_memberships` | Satu keanggotaan per pengguna/perusahaan, peran dan status tersendiri. |
| `AksesLokasiAnggota` | `hmu_membership_sites` | Lokasi eksplisit per anggota; pilihan semua gudang harus disengaja. |
| `AksesGudangAnggota` | `hmu_membership_warehouses` | Gudang terpilih pada lokasi dan perusahaan yang cocok, dijaga FK gabungan. |
| `KonteksKerja` | Tidak disimpan | Nilai immutable hasil pemeriksaan pengguna, perusahaan, lokasi, gudang dan keanggotaan aktif. |

Model berasal dari `core/hmu_core/organisasi.py`; kedua aplikasi menggunakan
paket yang sama, bukan membuat ID perusahaan sendiri. Pembentuk konteks ada
di `core/hmu_identitas/organisasi.py`. Paket identitas utama tetap dapat diimpor
tanpa SQLAlchemy; modul DB ini hanya diimpor bila dibutuhkan.

Penempatan gudang sengaja memakai tabel penghubung. Tidak ada kolom atau baris
`warehouses`, `users`, master barang maupun transaksi lama yang ditulis ulang.
Gudang lama yang belum dipetakan tetap tidak diketahui lokasinya. Tidak ada
tebakan berdasarkan Gudang 1/2, nama, kode, ID terkecil, atau perusahaan pertama.
Line mengikuti gudang melalui relasi `warehouse_id` yang sudah ada. Kode fungsi
g1/g2 yang masih unik global belum digeneralisasi pada tahap ini.

## Kontrak pemeriksaan konteks

`konteks_kerja()` menerima `user_id` dari sesi yang **sudah diverifikasi** oleh
pemanggil server. Nilai perusahaan/lokasi/gudang dari formulir tetap diperiksa
ke database dalam satu pembacaan. Super Admin tanpa keanggotaan tidak otomatis
mendapat akses perusahaan lain. Peran global tidak dipakai sebagai fallback.
Keanggotaan saja tidak memberi hak seluruh fasilitas. Kontrak lanjutan
mewajibkan akses lokasi eksplisit, kemudian semua gudang pada lokasi itu
atau daftar gudang tertentu. Tidak ada pilihan berarti tidak ada hak kerja
baru. Super Admin adalah wewenang platform; peran keanggotaan hanya Admin
atau Operator. Gudang bawaan pengguna tidak membatasi pilihan yang sah.

Pembacaan tidak melakukan autoflush terhadap draf ORM milik pemanggil, tidak
menulis audit, dan tidak menyimpan konteks pada sesi. Peran tak dikenal ditolak.
Pesan penolakan tidak membocorkan apakah perusahaan, lokasi, gudang, atau anggota
yang tidak tersedia. Dataclass bukan token autentikasi atau bukti akses mandiri.
Perubahan keanggotaan harus diperiksa lagi ketika gerbang transaksi nanti memakai
konteks; jangan mempercayai objek lama dalam cache atau payload.

**Belum ada endpoint/formulir yang memakai konteks baru.** Hak akses, sesi,
view operator, stok, portal, integrasi timbang, dokumen dan antrean luring tetap
menggunakan kontrak yang sudah berlaku. Tabel baru tidak menyediakan isolasi
perusahaan untuk transaksi lama. Jangan membuka perusahaan kedua untuk operasi
sebelum seluruh pembaca/penulis dan cache mendapat cakupan perusahaan.

## Keputusan pelari migrasi

Model master dimiliki paket core, tetapi server saat ini menjalankan rantai
PadiFlow untuk master bersama. Karena pemindahan runner core adalah tahap
terpisah, DDL penambahan ini dimiliki **hanya** PadiFlow:
`0128_master_organisasi`, sesudah `0127_transfer_tanpa_kendaraan`.
TeraFlow tidak menjalankan migrasi duplikat dan tidak men-stamp rantai core.
Tidak ada pelari baru yang diaktifkan pada startup.

Migrasi hanya membuat empat tabel kosong, indeks, dan constraint. Tidak ada
INSERT/UPDATE/DELETE, seed perusahaan, pengisian keanggotaan, perubahan pemilik,
backfill lokasi, atau perubahan kolom tabel lama. Downgrade hanya boleh ketika
seluruh tabel baru kosong; bila ada data, ditolak sebelum DROP pertama.
Rollback kode aplikasi lama tetap dapat mempertahankan tabel baru tersebut.

Saat runner core dipindah, kepemilikan migrasi ini harus diinventarisasi dan
batas riwayatnya dipindahkan secara eksplisit. Jangan membuat ulang tabel yang
sudah ada atau menjalankan migrasi historis core sebagai jalan pintas.

## Bukti pengujian

- Dua perusahaan, masing-masing dua lokasi dan dua gudang per lokasi; nama sama
  dan kode lokasi sama antarperusahaan tetap sah.
- Satu pengguna mempunyai peran berbeda antarperusahaan, berpindah ke gudang
  selain gudang bawaannya; hasil konteks mengikuti keanggotaan yang dipilih.
- Payload yang mencampur perusahaan/lokasi/gudang, anggota hilang, ID tidak sah,
  objek nonaktif dan peran tak dikenal ditolak tanpa menulis data.
- FK/unique database menolak pemetaan gudang lintas perusahaan, dua lokasi untuk
  satu gudang, keanggotaan ganda, kode duplikat dalam perusahaan, dan penghapusan
  perusahaan yang masih dirujuk.
- Upgrade/downgrade tabel kosong diuji bersama proses sosoh nyata pada database
  sementara. Sidik seluruh tabel bisnis/audit/master lama tetap identik.
- Downgrade tabel terisi ditolak tanpa kehilangan data.
- PadiFlow dan interpreter TeraFlow membaca ID dan keputusan akses yang sama
  dari database bersama yang dibangun memakai kedua rantai migrasi sebenarnya.
- Integrasi HTTP transfer PK lama tetap diuji; tidak ada stok ganda.

```sh
UJI_PG_URL=postgresql+asyncpg://USER@127.0.0.1:PORT/uji_organisasi \
python -m pytest tests/pg/test_master_organisasi.py

UJI_TF_ROOT=/path/timbangan UJI_TF_PYTHON=/path/python-teraflow \
UJI_PG_URL=postgresql+asyncpg://USER@127.0.0.1:PORT/uji_tf_kiriman_organisasi \
python -m pytest tests/pg/test_organisasi_dua_aplikasi.py -m dua_aplikasi
```

## Tahap berikutnya

Siapkan administrasi master dengan audit dan penetapan perusahaan/lokasi lama
yang ditinjau pengguna. Sesudah itu: keanggotaan terverifikasi pada sesi,
pembatasan master pelanggan/pemasok/produk/kemasan, gudang dan line, seluruh
transaksi/portal/cache/integrasi, serta pengujian kebocoran lintas perusahaan.
Mengisi master baru saja belum cukup untuk mengaktifkan operasi multi-perusahaan.


Tahap Console website dan layanan administrasi terikat perusahaan dijelaskan
di [CONSOLE-CENTER.md](CONSOLE-CENTER.md). Migrasi 0130 menambah dua tabel izin,
kunci relasi metadata, dan sesi Console terpisah; tidak mengisi data atau
mengaktifkan konteks baru pada gerbang transaksi harian.
