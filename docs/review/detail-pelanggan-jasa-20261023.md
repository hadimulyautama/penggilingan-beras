# Inventaris sebelum penataan

Baseline e582626. Sumber halaman: app/web/layar_jasa.py, app/services/jasa_pelanggan.py, hmu_tampilan/templates/jasa_pelanggan_detail.html, hmu_tampilan/static/jasa-pelanggan.css. Inventaris dibuat sebelum perubahan implementasi.

| Informasi/tindakan lama | Letak lama | Letak baru |
|---|---|---|
| Nama dan ID kontak, jumlah penerimaan/pesanan/proses, penanda titipan | Kepala | Kepala tetap; jumlah pesanan berjalan dari status pesanan yang sama |
| Kondisi bersamaan, PK/beras/hasil samping terpisah, catatan bobot belum final | Ringkasan | Kartu saldo dan tindak lanjut Ringkasan |
| Barang Masuk, Pekerjaan, proses berjalan, Stok pelanggan | Ringkasan | Tindak lanjut/dekat ringkasan, konteks ke() tetap |
| Pesanan: kode, status, umur, tanggal, catatan, penggabungan administratif | Ringkasan details | Pesanan & nota di Ringkasan; seluruh detail tetap |
| Nota masing-masing pesanan | Ringkasan details | Sama; endpoint lama /jasa/{id}/nota |
| Tutup dan batalkan | Ringkasan details | Sama; boleh_tutup/boleh_batal/sebab dari layanan; formulir tutup_jasa/batalkan_jasa dan API lama |
| Formulir ambil_jasa pelanggan terpilih dan daftar pengiriman | Ringkasan | Tindak lanjut Ringkasan dan tab Pengambilan & retur; endpoint Pengiriman lama |
| Pengiriman: kode/status/item/kg aktual | Ringkasan details | Tab Pengambilan & retur; Ringkasan hanya jumlah dan tautan |
| Retur: kode/status/kepemilikan/tanda asal belum tertaut | Ringkasan | Tab Pengambilan & retur dan tautan sumber; jumlah di Ringkasan |
| Penerimaan: tiket/jenis/pesanan/status, setiap catatan, waktu/bobot/sumber/status final | Penerimaan | Penerimaan tetap; tidak menggabungkan catatan tiket |
| Lokasi/proses terkait penerimaan; tiket belum diterima dari berjalan; batch warisan tanpa tiket | Penerimaan | Sama, tidak membuat tautan tebakan |
| Proses: pengeringan/giling/transfer/sosoh aktif atau selesai, pesanan/sumber/kg/ket/detail | Proses details | Proses, seluruh detail tetap |
| Hasil sosoh campuran, tiap jenis, bahan/susut/final, pemakaian silo, alokasi lot belum tersedia | Proses details | Sama; selisih aktif tidak diberi label final |
| Stok: barang/kode/lokasi/pesanan/kelompok pelanggan, bobot/final/kemasan/curah | Stok | Stok, saldo utuh tanpa filter perhitungan baru |
| Rincian asal tersedia pada s.rincian pembaca | Data stok, tautan sumber | Dapat dibuka di Stok tanpa menambahkannya sebagai saldo |
| Bahan & PK/Produk/Karung kontak | Stok | Sama; tautan master lama |

## Penjagaan yang dipertahankan

- Pembaca pelanggan berdasarkan Pelanggan.id dan Jasa.pelanggan_id, seluruh pesanan tanpa pengaruh filter daftar. Nama bukan relasi.
- Saldo berasal stok.pk_gudang1/pk_gudang2/stok_produk; hasil dari stok.output_sosoh. Layanan tidak diganti; tiga angka tidak dijumlah.
- Boleh tutup/batal dari jasa.boleh_ditutup/pernah_ada_barang; per pesanan. Stok nol bukan izin baru.
- Internal: can_see_financials(akun.user), efektif lihat sebagai tetap gerbang backend; operator403.
- Portal tersedia: scope berbasis sesi/ID, own_order/own_ticket/own_model, proyeksi read_only dan penyaringan koleksi. Template bersama tidak boleh menambah transaksi atau kebocoran koleksi.
- tab/status/cari/halaman, kembali_jasa, buka/nilai, /jasa/{id} redirect #pesanan-{id}, nota dan jalur administratif tetap.
- Formulir aksi.js generik tetap; tidak menambah formulir atau penangan transaksi sendiri.

## Batas data lama

Detail pelanggan hanya menyajikan relasi dan rincian yang diberikan pembaca lama. Pengiriman/retur tetap menuju detail asli; tidak membuat hubungan atau snapshot yang belum ada. Alokasi sumber lot yang belum tersedia tetap dinyatakan belum tersedia. Bekatul milik pabrik tetap bukan stok titipan.

## Implementasi

Lima tab memakai navigasi tautan native/SPA dengan aria-current. Parameter tambahan pengambilan hanya menata bagian halaman; gerbang backend, pembaca pelanggan dan seluruh layanan transaksi tidak diubah. Ringkasan menempatkan saldo terpisah, kondisi bersamaan, tindakan, perkembangan pelanggan dan Pesanan & nota. Rincian pengambilan/retur pindah ke tab khusus. Stok internal dapat membuka rincian asal yang sudah disediakan pembaca; rincian tambahan ini tidak memperluas proyeksi portal lama. Portal tetap menyaring tautan tindakan melalui read_only dan boleh_tutup/boleh_batal tetap false.

Perubahan komponen dibuat pada sumber tampilan, paket dinaikkan ke 431, dan disinkronkan dengan scripts/sinkron.py. Snapshot rilis sumber terisolasi /tmp/tampilan-rilis-jasa-detail berbasis paket 430 main terbaru (termasuk Beranda yang masuk bersamaan) dipakai agar working tree sumber yang berisi pekerjaan lain tidak ikut tersalin. Hanya template detail, CSS khusus detail dan versi/manifest yang berubah; perubahan sumber target tersedia di repo tampilan. Folder vendor tidak diedit langsung.

## Bukti pemeriksaan

- Baseline sebelum perubahan:73 tes pelanggan/ketaatan/portal lulus; hasil skenario campuran disimpan untuk perbandingan.
- Regresi setelah penataan:285 tes PG pelanggan, ketaatan jasa, portal, penggabungan, stok produk/karung, pengambilan dan retur lulus pada database uji lokal.
- 11 tes baru mencakup lima tab, saldo/snapshot 18 tabel tetap, proses campuran, kontak bernama sama, data lama/unknown, tiket belum diterima, pesanan historis, peran dan portal.
- Skenario sama sebelum/sesudah: PK2000 kg, beras4500 kg, hasil samping3200 kg; sumber2500+3500+4000=10000 kg; hasil9700 kg dan selisih300 kg. Status pesanan dan snapshot transaksi identik setelah semua tab/nota dibuka. Tidak menjumlah lintas tahap.
- Browser 320/390/768/1440/1920:5 tab, keyboard, refresh, konteks daftar, tidak overflow.8 navigasi SPA tanpa POST; Pengambilan barang membuka formulir Pengiriman lama dengan pelanggan yang benar. Tidak menambah formulir baru.
- 60 tangkapan penuh:5 tab×desktop/ponsel×6kondisi(campuran, kosong, belum diterima, lama aktif, historis, portal). Seluruh details dibuka; teknik membuka area gulir untuk tangkapan tidak masuk CSS aplikasi.

Log lengkap, perbandingan JSON, galeri dan hasil CI/deploy disimpan pada output/detail-pelanggan-jasa di checkout utama; hasil CI/deploy ditambahkan setelah selesai.

## Batas verifikasi

Chromium desktop dan emulasi ukuran ponsel sudah diuji. Safari, Firefox, perangkat fisik dan pembaca layar belum diuji. Tidak ada pengujian transaksi pada produksi. Tidak ada migrasi, formula, saldo, konfigurasi operasional, izin atau endpoint transaksi baru. Pembaruan dapat di-revert ke baseline e582626 tanpa pemulihan data; tidak ada perubahan skema/transaksi.

Penanda Ringkasan untuk bobot belum diukur/belum final memakai flag dan nilai pembaca yang sama. Tidak mengubah saldo; kondisi ini diuji pada data lama aktif. Pemeriksaan integrasi final:805tes non-PG dan11tes baru lulus kembali pada paket431.
