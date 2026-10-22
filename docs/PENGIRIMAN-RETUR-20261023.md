# Konsolidasi Pengiriman dan retur — 23 Oktober 2026

Status: implementasi dan pengujian lokal selesai; push/deploy disetujui pengguna pada 23 Oktober 2026. Rilis ini meneruskan Kabar/Beranda `564569f` yang sudah SUCCESS di produksi.

## Inventaris dan pemetaan

| Fungsi lama | Lokasi setelah konsolidasi |
|---|---|
| `/barang-keluar`, pencarian, status, tanggal, pagination | Pengiriman → Barang Keluar; rute dan parameter tetap |
| Detail, perintah, draf, pengambilan jasa, reservasi, muat, aktual, konfirmasi, timbang, verifikasi, penyerahan kecil | Layanan `barang_keluar`, `outgoing`, draf dan endpoint aksi lama tetap dipakai |
| Dokumen, pembatalan, undo | Jalur lama; membuka kembali pengiriman ditahan bila masih memiliki retur terkait, agar barang keluar historis dan stok retur tidak dihitung dua kali |
| `/retur`, `/retur/{id}` dan penerimaan lama | Pengiriman → Barang Retur; histori dan snapshot lama tetap dibaca |
| Rincian sementara lama | Tetap terlihat sebagai rincian belum terhubung; dapat dipilih tiketnya saat pengajuan dari asal yang dibuktikan pengguna |
| Penerimaan bebas SKU tanpa asal | Diganti pengajuan dari detail pengiriman selesai. Endpoint lama tidak dapat menerima stok atau menimpa pengajuan baru |
| Penerimaan selisih besar hanya dengan alasan | Dihapus. Selisih wajib dikoreksi; kasus tersebut tetap wajib manual setelah sesuai |

Sidebar memakai satu pintu Pengiriman dengan SVG truck. Kunci/rute lama Retur dipertahankan, pintu sidebarnya disembunyikan. Operator yang sebelumnya tidak boleh menangani retur tetap ditolak pada tampilan dan endpoint; tab retur ditawarkan hanya bagi pemeriksa lama.

## Transaksi dan bobot

`ReturRincian` menjadi pengajuan dengan identitas pengiriman, item asal di setiap baris, status pemeriksaan, flag manual yang melekat, hasil pemeriksaan, dan tautan penerimaan. Pengajuan berbeda dapat memakai item pengiriman yang sama secara bertahap.

Penulis mengunci header pengiriman sebelum menghitung sisa, lalu mengunci tiket. Sisa mencakup seluruh pengajuan terkait yang sudah diterima maupun masih tertunda. Indeks tiket dan penerimaan unik menjadi pagar tambahan. Jumlah nol dilewati; pengajuan kosong, negatif, pecahan karung, item asing, dan jumlah melebihi aktual ditolak.

Pengajuan yang belum menjadi penerimaan dapat dibatalkan dengan alasan oleh pemeriksa berwenang. Audit dan tiketnya tetap tersimpan; klaim jumlah dilepas tanpa perubahan stok. Pembatalan dan pekerja penerimaan memakai kunci yang sama sehingga tidak dapat menghasilkan status batal dengan stok yang terlanjur masuk. Penerimaan yang sudah menambah stok tidak diperlakukan sebagai draf yang boleh dibuang.

Tiket harus RTP/RETUR_MASUK, AKTIF, pelanggan sama, belum dipakai penerimaan lain, dan memiliki bacaan sah sesuai tahap. Menyimpan pada tiket terbuka tidak menambah stok. Pekerja server setiap 10 detik memeriksa tiket selesai; aturan sama dijalankan saat pengajuan disimpan.

Selisih = berat barang dari Pos Timbang − berat rincian. Toleransi = jumlah karung fisik setiap item × tara master jenis/ukuran kemasannya, dijumlahkan. Batas positif/negatif inklusif; tara kosong, nol, negatif atau tidak sah menahan penerimaan. Tidak ada batas tambahan 2 kg/0,2%. Tara tidak memotong rincian atau stok. Untuk PK/gabah, kg dan jumlah karung fisik dicatat terpisah. Jenis karung gabah lama yang tidak tercatat harus dipilih eksplisit, tidak ditebak.

Selisih besar melekatkan `wajib_manual`. Koreksi disimpan dengan sebelum/sesudah, alasan, pelaku, dan waktu. Koreksi timbang tetap di Pos Timbang; referensi audit KOREKSI berikut pelaku/waktu/alasan disalin ke hasil pemeriksaan. Alasan tanpa perubahan yang sah tidak membuka penerimaan. Perubahan tiket juga divalidasi ulang.

Penerimaan, item, stok dan audit berada dalam satu transaksi. Pengulangan permintaan mengembalikan penerimaan yang sama. Pemilik memakai `OutgoingItem.jasa_id`, termasuk beberapa pesanan pada satu pengiriman; tidak memakai header sebagai pengganti.

| Jenis asal | Penerimaan stok |
|---|---|
| Barang jadi kemasan | `FinishedGoodsStock`, tanpa pemakaian stok karung kosong |
| Hasil samping curah | `ByproductStock`, tanpa SKU kemasan buatan |
| PK Gudang 2 | `_add_intake` lama, peristiwa idempoten, kembali ke tumpukan |
| PK Gudang 1 | Suku masuk terpisah pada pembaca saldo dan breakdown satuan/borongan |
| Gabah kering | Suku masuk terpisah pada saldo lot asal |

Jumlah keluar dan hasil produksi historis tidak diubah. Histori tanpa bukti asal tidak dibackfill atau dipindahkan kepemilikannya.

## Skema dan konfigurasi

Migrasi `0107_retur_asal`, setelah `0106_kabar_pribadi`: kolom pengajuan pada `retur_rincian`, FK item asal pada `customer_return_items`, tabel audit pemeriksaan. SKU penerimaan menjadi nullable untuk bahan/curah yang memang tidak memiliki SKU. Tidak ada penghapusan atau penebakan data historis. Paket tampilan sumber `tampilan/` versi 403 (commit `31ee495`) disinkronkan menggunakan skrip resmi; tidak ada penyuntingan langsung salinan vendored.

Tidak memerlukan konfigurasi produksi baru. Rollback harus mempertahankan berkas migrasi yang sudah diterapkan; jangan menurunkan skema atau menghapus penerimaan untuk mengembalikan aplikasi.

## Bukti pengujian

- Unit sumber akhir: **772 lulus**.
- Model/migrasi: `alembic check` bersih pada database baru lokal; manifest paket/identitas **7 lulus**.
- Regresi Postgres penuh bersih: **1.216 lulus** (553,57 detik). Putaran sebelumnya 1.213 lulus dan dua fixture gagal; kedua fixture yang masih memakai penerimaan tanpa asal diperbaiki dan seluruh suite dijalankan kembali.
- Pengujian akhir terarah: **82 lulus**, meliputi retur, histori, skenario data uji dan pelanggan jasa. Tambahan kasus akhir menguji pembatalan/penerimaan bersamaan dan halaman retur curah.
- Seluruh paket tampilan: **398 lulus**; pengiriman lama juga diverifikasi terarah pada 14 kasus desktop/ponsel dan tema.
- Halaman baru: **28 kombinasi** (7 tahap × desktop/ponsel × terang/gelap), masing-masing potret atas/bawah; overflow, fokus input, target sentuh tombol dan pembuka riwayat diperiksa.
- Bukti HTML diekspor langsung dari rute aplikasi dengan akun/data uji yang sama, bukan mockup simulasi. `tests/qa/potret_retur.py` memuat aset dan API sesi tiruan lokal; tidak menghubungi atau mengubah data operasional.

Uji lama yang mengharapkan penerimaan tanpa asal/kelolosan hanya dengan alasan diubah menjadi penolakan sesuai aturan baru. Fixture histori tetap dibuat sebagai fakta lama tanpa asal, sehingga pembacaan histori dan kepemilikan pabrik tidak menjadi pengujian alur baru secara terselubung. Skenario pengisian data uji kini melewati perintah, muat, pengiriman asal, pemeriksaan, koreksi nyata, dan verifikasi manual yang sah.

## Checklist penerimaan

Centang berarti ada pemeriksaan kode dan uji otomatis yang relevan, bukan klaim seluruh kombinasi akun/data produksi sudah dicoba.

- [x] A: Satu menu dan dua tab, SVG truck, URL lama serta parameter tetap.
- [x] A: Potret halaman retur baru pada desktop/ponsel, terang/gelap, fokus dan target sentuh; tidak ada overflow horizontal pada seluruh kombinasi.
- [x] B: Jalur perintah, reservasi, aktual/muat, verifikasi, penyerahan kecil, timbang, koreksi, pembatalan, undo dan multiitem tetap memakai layanan lama; regresi terarah lulus.
- [x] B: Filter, pencarian, pagination dan histori tetap tersedia; dokumen lama tidak dialihkan ke logika transaksi baru.
- [x] C: Form dari detail pengiriman selesai, item asal eksplisit, nol dilewati, batas kumulatif dan tiket wajib.
- [x] C: Tiket terbuka hanya menyimpan rincian; belum ada stok.
- [x] D: Batas ±tara termasuk tepat batas, tidak ada aturan lama, data tara tidak lengkap ditahan.
- [x] D: Pemeriksaan server saat simpan dan pekerja latar, termasuk tiket selesai sebelum pengajuan.
- [x] E: Selisih besar menahan stok, alasan saja tidak meloloskan, koreksi masih di luar batas tetap tertahan, setelah sesuai tetap manual.
- [x] E: Audit koreksi dan referensi koreksi timbang tersedia; tombol/endpoint mengikuti hasil pemeriksaan.
- [x] F: Penerimaan idempoten dan transaksi bersamaan diuji; pemilik per item, karung kosong, berat rincian, dan angka keluar historis dipertahankan.
- [x] F: Tautan pengiriman, pengajuan, penerimaan dan tiket tersedia; histori lama tidak ditebak asal/pemiliknya.
- [x] G: Akun dan sesi database lokal nyata menguji Admin, Super Admin, operator Gudang 1/Gudang 2; endpoint langsung, CSRF, tiket ganda dan batas kumulatif memakai Postgres loopback berawalan `uji_`.
- [ ] G: Semua akun/peran nyata di produksi — belum diuji; tidak membuat transaksi atau mengganti peran akun operasional untuk QA.
- [x] G: Regresi Postgres penuh, unit, paket tampilan, manifest, selisih model/migrasi dan pemeriksaan diff dijalankan; pengujian tambahan akhir menutup perubahan setelah putaran penuh.

## Batas pemeriksaan

Uji transaksi memakai data terisolasi. Histori lama tanpa tautan tidak diasumsikan berasal dari pengiriman tertentu dan tidak dimasukkan secara spekulatif ke jumlah retur asal. Sebelum memakai pengiriman historis untuk retur baru, pengguna perlu memastikan bukti asal; rekonsiliasi hubungan historis massal bukan bagian dari migrasi ini.

Tidak dilakukan koreksi timbang, verifikasi, pembatalan, atau perubahan stok percobaan pada data operasional. Pembacaan halaman produksi tidak membuktikan seluruh alur transaksi produksi.
