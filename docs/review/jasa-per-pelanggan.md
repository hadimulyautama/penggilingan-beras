# Konsolidasi Jasa per pelanggan — v392 (belum diterapkan)

## Inventaris sebelum perubahan

| Fungsi lama | Lokasi baru / dipertahankan | Sumber dan izin |
|---|---|---|
| Daftar pesanan berjalan/selesai/batal/digabung | `/jasa`: satu pelanggan, filter status pesanan; semua nomor tetap di detail | `Jasa`, `Pelanggan`; Admin ke atas, termasuk peran efektif |
| Sisa dan fase pesanan | Ringkasan pelanggan: beberapa kondisi bersamaan, saldo per jenis/lokasi | Pembaca Stok yang sama; tidak menjumlah bobot antar tahap |
| Umur, catatan, status, penggabungan administratif lama | Daftar pesanan dalam Ringkasan | Baris pesanan asli; tidak menggabungkan atau menulis saat dibaca |
| Nota | Tetap `/jasa/{id}/nota`, per pesanan | `nota_jasa`; izin lama |
| Tutup pesanan, sebab terkunci | Daftar pesanan dalam detail pelanggan | `boleh_ditutup`, aksi `tutup-jasa`; tidak menutup seluruh pelanggan |
| Batalkan pesanan, alasan wajib, audit | Formulir operasional lama dari pesanan yang tepat | `batalkan_jasa`, `pernah_ada_barang`; izin/validasi lama |
| Buat pesanan | Tetap di Pos Timbang/penerimaan sesuai fungsi lama | Tidak membuat pintu pencatatan kedua |
| Penerimaan, tiket, jenis, bobot, waktu, lokasi | Tab Penerimaan, tautan Barang Masuk | Sumber penerimaan asli, satu entri per tiket |
| Dryer, giling, transfer, sosoh, sumber | Tab Proses → detail/riwayat asli | FK sumber; tidak mencocokkan nama/tanggal/berat untuk membuat relasi |
| PK, produk, curah/kemasan, karung | Tab Stok → cakupan pelanggan di Stok | `pk_gudang1`, `pk_gudang2`, `stok_produk`, pembaca karung lama |
| Ambil jasa, pengiriman, retur | Ringkasan → Pengambilan barang / catatan pengiriman dan retur asli | Item ber-`jasa_id`; retur lewat ID pelanggan atau item, bukan kecocokan nama |
| QC, packing/rebag, pindah kepemilikan/silo | Tetap tindakan operasional pada Pekerjaan/Stok | Tidak menambah wewenang; endpoint lama tetap memeriksa izin |
| Audit, notifikasi dan pembatalan transaksi | Tetap melalui tindakan dan laporan lama | Tidak ada saldo, peristiwa, tugas atau skema baru untuk konsolidasi |

## Batas penelusuran yang harus jujur

`polishing_silo_usage` menyimpan konsumsi per pemakaian silo, bukan alokasi
setiap intake di dalam campuran. Jumlah per lot hanya dapat dinyatakan pasti
bila seluruh riwayat silo menunjuk satu sumber yang tidak ambigu. Untuk silo
dengan lebih dari satu riwayat asal, hanya pemakaian silo dan bobot aktualnya
yang disebut; pembagian terpakai per lot dinyatakan belum tersedia. Transfer
baru pada pemakaian ulang tidak ditempelkan sebagai asal proses sebelumnya.
Tidak ada pembagian hasil sosoh ke pesanan/tiket asal.

Penggabungan administratif yang sudah terjadi pada data lama tetap terlihat
sebagai status Digabung. Pembaca baru tidak memanggil `gabung_jasa` dan tidak
mengubah identitas pesanan. Hubungan pesanan asal tiket dibaca dari referensi
tiket bila tersedia, terpisah dari pesanan pemilik catatan saat ini.

## Hasil verifikasi lokal, 21 Oktober 2026

**Belum dipush atau dideploy.** Hasil ini untuk ditinjau pengguna. Tidak ada
migrasi, perubahan skema, penghapusan, atau penulisan data operasional.
Versi paket tampilan **392**, disunting di `tampilan/` lalu disinkronkan.
Perubahan lokal lain yang sudah ada tetap dipertahankan.

- Seluruh **1.896 uji Produksi** lulus, 0 gagal/error/dilewati.
- Seluruh **391 uji paket tampilan** lulus, 0 gagal/error/dilewati.
- Pemeriksaan akhir terarah **63 uji** lulus setelah melengkapi verifikasi
  pengambilan dan memastikan tautan penutupan mempertahankan filter daftar.
  Angka ini merupakan pengujian ulang bagian dari suite, bukan 63 uji tambahan.
- Checklist 55 butir dijabarkan dalam [checklist-jasa-pelanggan.md](checklist-jasa-pelanggan.md).
- PostgreSQL khusus uji di `127.0.0.1:55443`: `uji_jasa392` untuk integrasi,
  `uji_jasa392_browser` untuk browser. Terpisah dari database aplikasi lain.
- Browser lokal `http://127.0.0.1:8090/jasa`, data sepenuhnya buatan.
  20 tampilan dasar (daftar + empat tab × ponsel/desktop × terang/gelap),
  ditambah sumber sosoh terbuka, formulir pengambilan dibuka lalu dibatalkan,
  dan pemeriksaan peran. Tidak ada luapan horizontal pada 20 tampilan dasar.
- Snapshot browser sebelum–sesudah: **17 tabel transaksi, 53 baris**, jumlah
  dan checksum sama. Membuka halaman, detail, formulir, Batal, serta berganti
  mode lihat sebagai tidak menulis stok, transaksi, audit, atau peristiwa baru.

### Pembanding sebelum–sesudah pada data yang sama

Pembanding saldo adalah layanan Stok lama yang tetap dipakai aplikasi,
bukan penjumlahan perkiraan fase pada kartu Jasa lama. Untuk data yang sama,
saldo pembaca Stok dan ringkasan pelanggan identik; pembacaan halaman tidak
mengubah catatan. Tindakan perubahan data di bawah memakai layanan lama.

Pelanggan **Catur Uji 392**, pesanan **JAS-392-001/002/003**;
tiket **TRX-392-GABAH_BASAH**, **TRX-392-GABAH_KERING**, **TRX-392-PK**.
Riwayat awal pengeringan/giling disiapkan sebagai catatan historis bertaut FK;
transfer, pemasukan PK, sosoh, hasil, pembebasan silo, penyelesaian, packing,
muat dan verifikasi dijalankan melalui layanan operasional yang sebenarnya.
Rantai penerimaan/pengeringan/giling melalui layanan lama juga tercakup dalam
uji regresi `test_jasa_ketaatan` dan `test_gabung_jasa`.

| Komponen | Sebelum dipakai | Aktual dipakai sosoh | Sisa Stok lama | Ringkasan baru |
|---|---:|---:|---:|---:|
| LOT-392-1, dari gabah basah / PGR-392-01 | 3.000 kg PK | 2.500 kg via TRF-20261021-01 | 500 kg | 500 kg |
| LOT-392-2, dari gabah kering | 4.000 kg PK | 3.500 kg via TRF-20261021-02 | 500 kg | 500 kg |
| PKB-392-01, dari luar | 5.000 kg PK | 4.000 kg | 1.000 kg | 1.000 kg |
| **PK** | **12.000 kg** | **10.000 kg** | **2.000 kg** | **2.000 kg** |
| Beras Medium | 6.500 kg hasil sosoh | 2.000 kg diambil dan diverifikasi | 4.500 kg | 4.500 kg |
| Broken + menir + bekatul | 1.000 + 200 + 2.000 kg hasil | 0 kg diambil | 3.200 kg | 3.200 kg |

Proses **POL-20261021-01**: bahan aktual 10.000 kg, hasil tercatat 9.700 kg,
selisih neraca/susut 300 kg. Hasil campuran dibaca sekali untuk pelanggan,
tidak dibagikan ke tiga pesanan asal. Penutupan pengiriman tidak mengurangi
stok kedua kali. Pembatalan verifikasi lalu muat mengembalikan beras 6.500 kg,
PK dan hasil samping tetap. Kasus kedua memakai ulang silo A, menjalankan
sosoh kedua dan pengambilan kedua; transfer baru tidak diklaim sebagai asal
sosoh pertama. Koreksi hasil 5.000 → 4.800 kg dan kemas ulang 100 → 80 kg
+ 20 kg curah juga diperiksa terhadap saldo pelanggan yang sama.

### Hak akses

| Akun uji | Pesanan Jasa lama → baru | Halaman operasional |
|---|---|---|
| Uji superadmin / Uji Super 392 di browser | Diizinkan → diizinkan | Sesuai izin lama |
| Uji admin | Diizinkan → diizinkan | Sesuai izin lama |
| Uji operator Gudang 1 | Ditolak → ditolak (403) | Penerimaan, Pekerjaan dan Stok tetap mengikuti izin G1 |
| Uji operator Gudang 2 | Ditolak → ditolak (403) | Termasuk akses PK G1 sebagai bahan sesuai izin lama |
| Super Admin, lihat sebagai Operator G1/G2 | Ditolak (403) | Memakai peran efektif, bukan wewenang akun asli |

Konsolidasi tidak membuka akses halaman administrasi Jasa bagi operator.
Operator tetap menjalankan tindakan jasa dari halaman operasional lamanya.
Nota tetap per pesanan. Tombol Tutup/Batalkan membawa ID pesanan yang tepat;
menolak penutupan pesanan dengan saldo dan alasan pembatalan kosong tetap diuji.

### Batas data dan pemeriksaan yang tersisa

- **Alokasi lot pada silo campuran/pemakaian ulang lama:** belum tersedia jika
  tidak pernah dicatat. Bobot aktual per pemakaian silo tetap terlihat. Tidak
  ada alokasi proporsional, tebakan asal, atau perubahan sejarah untuk
  melengkapi tampilan. Ini kondisi data yang ditangani dan diuji, bukan hasil
  pengujian yang diasumsikan lulus.
- **Retur lama:** layanan penerimaan retur saat ini menulis kepemilikan pabrik.
  Retur milik pelanggan yang sama ditautkan sebagai riwayat dengan label
  kepemilikan tersebut; tidak otomatis menambah saldo titipan. Tautan ke
  pengeluaran asal belum tersedia jika tidak ada FK-nya. Aturan ini tidak
  diubah oleh konsolidasi.
- **Belum diuji:** perangkat ponsel fisik, volume produksi sebenarnya, integrasi
  eksternal langsung, dan pemeriksaan pascadeploy. Browser memakai viewport
  390×844 dan 1440×900; integrasi memakai database buatan. Tidak ada klaim
  pengujian pada data operasional atau penerapan ke produksi.

### Bukti yang dapat dibuka

Semua berikut berada di `produksi/output/jasa392/`, tidak dipush:

- `produksi-final.xml`, `tampilan-final.xml`, `fokus-final.xml`: hasil uji.
- `campuran.json`: sumber, penerimaan, stok per komponen dan pengiriman final.
- `browser-matrix-final.json`: 20 tampilan dasar dan 8 tampilan proses/sumber.
- `browser-formulir.json`: empat kombinasi pembukaan pengambilan lalu Batal.
- `browser-peran.json`, `browser-konteks.txt`: gerbang peran dan konteks URL.
- `browser-sebelum.json`, `browser-sesudah.json`: checksum transaksi sama.
- `ringkasan-{ponsel|desktop}-{terang|gelap}.png`,
  `sumber-{ponsel|desktop}-{terang|gelap}.png` dan gambar empat tab lainnya.
