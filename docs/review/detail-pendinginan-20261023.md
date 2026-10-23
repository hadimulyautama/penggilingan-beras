# Detail pendinginan — inventaris sebelum perubahan

Acuan: bagian USULAN mockup detail-pendinginan desktop/ponsel20Oktober2026. Acuan fungsi: proses_aktif.rincian/route aktif, riwayat_pengeringan/riwayat_detail, kartu Pekerjaan, layanan drying/silo, PDF asli.

|Informasi/tindakan lama|Lokasi baru|Sumber/izin|
|---|---|---|
|Kode/pemilik/pabrik-jasa/pesanan/gudang/dryer/mode/status|Hero seluruh tab dan Riwayat|Identitas lot/helper kepemilikan asli|
|Bahan dalam lot dan semua batch/kondisi/berat/pemasok/tiket/waktu/kendaraan|Ringkasan dan Bahan|dari_batches, _lot_batches, _bahan_gabah; tidak menghitung sumber dua kali|
|Alat tes terakhir/waktu, mesin akhir/waktu, target|Ringkasan hasil pengeringan dan Pengukuran|Bacaan non-NULL terpisah, bukan suhu/kemajuan pendinginan|
|Seluruh log rata-rata/empat sampel/indikator/waktu/pencatat/pagination|Pengukuran|_log lama, halaman_ukur|
|Mulai proses/fase/pencatat/berlalu/lama pendinginan/jeda/durasi kering/total/waktu selesai|Riwayat lengkap, ringkasan waktu|Tanggal tersimpan, lama_kata, tertahan_detik, KartuPengeringan lama|
|Putaran pendinginan lama dan terbaru|Riwayat|ProsesTerpadu.metadata_domain.putaran_sebelumnya dan waktu lot; data tidak lengkap tetap belum diketahui|
|Semua catatan pendinginan/waktu/pencatat/pagination|Riwayat|DryingCoolingLog, halaman_dingin|
|Jeda pengeringan/kejadian/pencatatan/sebab/kondisi/keterlambatan/pembatalan/pagination|Riwayat|riwayat_jeda_blok lama|
|Lokasi dan waktu pindah/status silo|Hero, Ringkasan, Bahan, Riwayat|SiloStorage/riwayat_pengeringan, bukan status dingin saja|
|Nyatakan sudah dingin|Tindakan saat ini di Ringkasan aktif|Pilihan kartu lama; selesai_pendinginan; tanpa isian baru|
|Pindah ke silo dan Dinginkan lagi|Tindakan saat ini di Ringkasan sudah dingin|Pilihan transit Pekerjaan lama, endpoint/dialog/status/izin tetap|
|Pernyataan dingin berulang|Jalur API/formulir lama|finish_cooling tidak diganti; tidak menambah tombol di luar mockup/pilihan lama|
|Lihat/bagikan/unduh PDF|Tautan laporan setelah isi tab, saat tersedia|Route halaman laporan/PDF/unduh lama, belum selesai tetap404|
|Kembali/URL aktif/riwayat/buka/nilai/hash/refresh/pagination|Seluruh tab|Konteks aman; aktif sudah dingin tetap ke riwayat; riwayat yang didinginkan ulang mengikuti fase terbaru|

Perubahan hanya penyajian dan integrasi rute/detail. Semua tindakan harus berasal kartu yang diizinkan; detail lot yang sudah dipindah tidak mendapat tindakan dryer. Laporan asli, layanan transaksi, stok, perhitungan QC/laju/waktu tidak diganti.

## Hasil pemeriksaan
Implementasi mengikuti posisi USULAN: hero, empat tab, tahap informatif, tiga kartu angka, Tindakan saat ini, lalu Waktu pendinginan berdampingan dengan Mesin & bahan/Hasil pengeringan. Ponsel satu kolom. Setelah dingin tetap memakai URL riwayat pengeringan, dengan susunan empat tab yang sama dan tindakan dari kartu Pekerjaan lama. Setelah pindah, lokasi/waktu berasal SiloStorage dan tidak ada tindakan dryer. Laporan ditautkan pada akhir isi tab, hanya ketika aturan lama mengizinkan.

Berkas aplikasi: `app/services/detail_pendinginan.py`, `app/services/proses_aktif.py`, `app/web/layar_berjalan.py`, `app/web/layar_riwayat.py`, `app/web/templates/detail_pendinginan.html`, `proses_aktif_beralih.html`, `app/web/static/detail_pendinginan.css`, `detail_pendinginan.js`, serta adapter `app/web/tampilan.py`. Ditambah `tests/pg/test_detail_pendinginan_tab.py`, `tests/test_urlencode_query.py` dan laporan ini. CSS pengeringan dipakai ulang tanpa diedit. Layanan drying/silo, endpoint transaksi, laporan/PDF, stok dan paket vendored tidak diubah.

Metadata menyajikan selisih waktu dari awal putaran sampai sekarang atau pernyataan dingin tersimpan, memakai format lama `lama_kata`; tidak menjumlah putaran atau mengurangi jeda. Ringkasan kering/total lama tetap dibawa. Putaran terdahulu berasal metadata `ProsesTerpadu`, seluruh pernyataan/catatan tetap dari `DryingCoolingLog`. Kekurangan arsip/data waktu tetap diberi keterangan belum diketahui, bukan angka nol. Presisi berat batch/tanggal pembelian riwayat lama dilengkapi dari sumber asli tanpa mengubah bobot total proses.

Pengalihan fase/riwayat kini mempertahankan tab_detail, pagination dan fragmen, termasuk saat membuka URL aktif lama sesudah selesai. `buka/nilai` tindakan lama tidak dibawa ke fase baru. Rute riwayat yang didinginkan ulang mengikuti fase terkini. Gerbang akses tetap dijalankan sebelum membaca data atau mengalihkan halaman.

### Bukti pemeriksaan nyata

- Full PostgreSQL: **1.331 lulus dalam504,86detik**, `pytest -o addopts='' -q tests/pg`. Setelah tambahan kasus presisi/tanggal dan perbaikan navigasi: **56 regresi terkait lulus dalam80,53detik**, meliputi enam kasus baru pendinginan, detail pengeringan, riwayat/PDF, alur pendinginan ulang, giling dan sosoh. Pemeriksaan awal39 dan lima kasus baru juga lulus terpisah.
- Non-PG akhir: **789 lulus dalam17,18detik**. Sintaks JS, compile Python dan git diff --check bersih. Semua DB uji loopback55449 bernama `uji_giling_detail`/`uji_giling_browser`; server browser localhost8059 tanpa bot/operasional.
- Operator/admin/superadmin ×3status (aktif, sudah dingin, di silo) ×4tab diuji backend. Setiap status memuat sumber10.000kg/dua batch/tiketTK-DR-TAB/kendaraanB4321UJI. Bacaan16,0% dari15/NULL/17/16 tetap tersedia setelah catatan penutupan mesin18,0%; target13,0%. Tidak ada progress pendinginan, suhu, atau kewajiban tambahan.
- Seluruh peran: viewer/PDF inline/download200 setelah dingin;404 sebelum dingin dan ketika pendinginan ulang. PDF diurai `PdfReader` untuk memeriksa lot, bahan, pengukuran dan pendinginan. Test export laporan lama juga lulus (QC bahan, pengukuran, laju, jeda dan isi laporan asli tidak disentuh).
- Gudang efektif operator:g2 untuk ketiga peran: detail aktif, riwayat, viewer, PDF dan POST langsung ditolak403. Admin/superadmin dan tampilan efektif memakai helper lama. Status di silo menolak POST dingin/ulang; pemeriksaan tambahan POST pindah ulang memastikan tidak menambah stok.
- Browser Chromium:60 kombinasi peran/lebar320/390/768/1440/1920/tab pada aktif, lalu60 lagi sesudah pindah melalui URL aktif lama; tanpa overflow horizontal. Home/ArrowRight berfungsi. Tab desktop1.067,84px/ponsel358px, tinggi44px tetap pada semua tab/pagination.
- Browser delapan hash lama melalui URL aktif setelah selesai membuka tab riwayat terbaru: ringkasan-proses, tindakan-proses, catatan-proses, bagian-1, halaman_ukur, halaman_dingin, riwayat-jeda, putaran-pendinginan. Konteks Pekerjaan dan pagination dipertahankan; tombol formulir tetap membawa kode lot.
- Browser: Nyatakan sudah dingin klik ganda → satu POST → riwayat empat tab, tetap dryer. PDF asli tersedia. Dinginkan lagi dari detail riwayat → konfirmasi lama → satu POST → detail aktif; putaran1/2 dan catatan terdahulu tetap terlihat, pindah ditahan dan PDF kembali404 sesuai aturan lama.
- Browser: putaran kedua dinyatakan dingin → Pindah ke siloA klik ganda → satu POST. Halaman menunjukkan Sudah di silo, sumber/lokasi transaksi dan waktu pindah; tindakan dingin/ulang/pindah tidak tersedia. Tidak ada galat JS sepanjang alur.
- Query DB: satu lot, dua putaran dengan4catatan pendinginan, tepat1barisSiloStorage untuk lot tersebut. Tidak ada baris silo sebelum tindakan pemindahan (assert integrasi). Layanan terkunci lama tetap memeriksa status/kapasitas/pemilik/ketersediaan dan mencegah duplikasi; suite penuh mencakup mekanisme tersebut.
- Durasi: contoh tersimpan mulai4jam lalu, dingin2jam kemudian menghasilkan2jam0menit; menggeser waktu baca menjadi sehari kemudian tidak mengubah hasil terakhir; waktu sejak pernyataan dingin menjadi22jam0menit, dibedakan dari pendinginan2jam. Jeda pengeringan tetap terpisah; kasus aktual pengeringan pada suite menyimpan7.200detik jeda. Waktu pendinginan tidak dipotong jeda. Mulai/selesai setiap putaran dibaca terpisah, tanpa penjumlahan baru.
- Pernyataan dingin berulang diuji layanan asli pada semua peran: timestamp terakhir diperbarui, catatan sebelumnya dipertahankan, belum ada pemindahan. `pemantau` masih menghitung idle dari waktu_selesai_pendinginan yang berlaku; `mulai_pendinginan_ulang` mencabut timestamp siap pindah dan mengarsip putaran, tidak diubah.
- Kasus data warisan: pengukuran kosong tetap Belum diukur, awal pendinginan tidak diketahui tetap Belum dapat dihitung, tanggal pembelian yang berbeda dari timestamp tetap tampil, presisi8.000,12kg tidak dibulatkan hilang pada rincian batch. Ringkasan tetap memakai helper bobot lama.
- Dokumen di browser: membuka viewer, Bagikan PDF melalui fallback salin tautan berhasil, tombol Unduh menghasilkan file.pdf; tanpa galat JS. Tidak mengirim dokumen kepada orang lain.
- Regresi halaman pengeringan, penggilingan, penyosohan, transisi bersama, sesi/CSRF dan stok tercakup full suite serta pemeriksaan terarah. Tidak ada migrasi atau aturan produksi baru.

### Checklist penerimaan

**Tampilan dan kelengkapan8/8**
- [x] Desktop/ponsel mengikuti USULAN.
- [x] Posisi tombol tetap pada Tindakan saat ini sebelum ringkasan berdampingan.
- [x] Empat tab aktif/riwayat berfungsi.
- [x] Seluruh informasi/tindakan lama terpetakan di atas.
- [x] Identitas/pemilik/gudang/dryer/mode/pesanan dari data asli.
- [x] Lokasi dryer dan transaksi silo dibedakan.
- [x] Legacy/kosong/belum diketahui tetap jelas.
- [x] Lima ukuran diperiksa tanpa potongan horizontal; capture lengkap.

**Pendinginan dan tindak lanjut11/11**
- [x] Nyatakan dingin memakai dialog/validasi lama.
- [x] Durasi tidak menulis status otomatis.
- [x] Tidak ada suhu/waktu/isian operasional baru.
- [x] Timestamp tersimpan dan redirect riwayat lama.
- [x] Dingin tidak membuat SiloStorage.
- [x] Jalur Pekerjaan tetap utuh; tidak diganti.
- [x] Pernyataan dingin berulang diuji.
- [x] Ulang memakai konfirmasi dan validasi waktu lama.
- [x] Putaran/catatan sebelumnya tetap utuh.
- [x] Ulang menahan pindah sampai dingin kembali.
- [x] Setelah pindah, tombol hilang dan API dryer menolak.

**Perhitungan6/6**
- [x] Durasi memakai awal putaran dan end/now sesuai sumber lama.
- [x] Jeda tidak dikurangkan dari pendinginan.
- [x] Kering/pendinginan/total/jeda tampil terpisah.
- [x] Dasar idle timestamp dingin terakhir tetap (pemeriksaan kode + tes berulang/ulang).
- [x] Tes non-NULL terakhir dan waktunya tidak hilang akibat log indikator akhir.
- [x] Ringkasan/putaran memakai seluruh sumber; pagination hanya daftar.

**Bahan dan stok6/6**
- [x] Batch/berat/tiket/waktu/kendaraan dan presisi/tanggal lama dipertahankan.
- [x] Pabrik/jasa dari helper identitas dan sumber lama; suite kepemilikan lulus.
- [x] Pindah memakai layanan status/kapasitas/pemilik/ketersediaan lama.
- [x] Lokasi/sumber/status konsisten sesudah transaksi.
- [x] Browser satu POST dan DB satu baris; pengiriman ulang ditolak backend.
- [x] Penyimpanan tetap memeriksa data terkunci terbaru.

**Riwayat dan dokumen6/6**
- [x] Semua pengukuran/empat sampel tersedia.
- [x] Seluruh putaran dan catatan tersedia.
- [x] Macro jeda mempertahankan kejadian/pencatatan/kondisi/keterlambatan/pembatalan.
- [x] Pagination pengukuran/catatan/jeda tetap.
- [x] Viewer, fallback Bagikan, Unduh dan akses dokumen diuji.
- [x] Pembuat/payload/rumus PDF lama tidak berubah; tes export asli dan ekstraksi lulus.

**Hak akses dan navigasi7/7**
- [x] Operator mengikuti gudang efektif/tindakan lama.
- [x] Admin/superadmin/tampilan peran lain memakai helper lama.
- [x] URL/API tanpa izin ditolak403.
- [x] Laporan tetap dipagari backend dan status.
- [x] Tab tidak menambah pilihan di luar kartu/status.
- [x] Kembali/refresh/alias/hash/formulir/pergantian fase/pagination diperiksa.
- [x] Listener hash memakai PINDAH.pasang; navigasi dan klik ganda tidak menggandakan penyimpanan.

### Tangkapan dan batas verifikasi

`output/detail-pendinginan/` berisi subfolder `aktif/`, `siap/`, `ulang/`, `silo/`: masing-masing empat tab desktop/ponsel sampai bawah dan Pengukuran halaman2. Semua rincian terbuka; CSS capture hanya mengembangkan container gulir. Bukti ukuran, role, alur, dokumen, database dan logpytest disertakan terpisah.

Belum diuji: perangkat Android/iOS fisik, Safari/Firefox, pembaca layar, dialog berbagi native perangkat, seluruh kombinasi data operasional serta mesin fisik. Bagikan diuji melalui fallback clipboard Chromium, bukan mengirim kepada penerima. Tidak ada mutasi data operasional. Deploy dibuktikan melalui status Railway/hash commit secara terpisah.


Pemeriksaan API akhir pada tiga peran: pernyataan dingin, pernyataan berulang dan pemindahan berhasil200; kiriman pindah ulang/dingin/ulang setelah ke silo ditolak400 dan SiloStorage tetap satu baris. Enam tes pendinginan akhir lulus terpisah.

Pemeriksaan wajib workflow repository: migrasi kosong dijalankan oleh fixture PostgreSQL; alembic check pada database uji menyatakan No new upgrade operations detected.

Integrasi main252f932 (pembaruan Pekerjaan terpisah): awalnya dua kasus katalog menemukan QueryParams tidak didukung urlencode bawaan Jinja. Adapter aplikasi kini menormalisasi hanya QueryParams menjadi pasangan multi_items; string/dict tetap sama dengan filter asli, Unicode/spasi/kunci ulang diuji. Paket/menu tidak diedit oleh perbaikan ini. Hasil akhir63 tes PostgreSQL integrasi lulus76,45detik dan789 non-PG lulus17,18detik; browser katalog/konteks serta empat tab pendinginan tanpa galat.

Tangkapan mewakili beberapa skenario/putaran data uji yang dibuat ulang; waktu antarskenario dapat berbeda. Seluruhnya berasal aplikasi yang berjalan, bukan data atau rumus simulasi mockup.
