# Riwayat QC desktop dan ponsel

Daftar dan detail QC mengikuti pola riwayat proses: header tanpa kartu besar,
tab garis bawah, kontrol Panduan dengan ikon ⓘ, serta navigasi induk dalam menu.
Pada daftar, lima kategori QC tetap terlihat dan mengikuti cakupan baca asli.
Tidak ada pencarian, filter, PDF atau tindakan domain baru.

Detail gabah dan PK mempertahankan empat panel server: Ringkasan, Putaran,
Perhitungan, Asal & catatan. Ringkasan menjadi satu kolom; komponen PK tiga
kolom di desktop dan dua di ponsel. Seluruh isi panel dan tabel daftar lama
utuh. Pergantian tab dan putaran berjalan lokal, mempertahankan query konteks,
putaran terpilih dan tautan GET sebagai fallback. Navigasi keyboard tab tersedia.
Seluruh putaran tetap dirender, termasuk ketika melebihi batas daftar 200 lot.

QC beras memakai Ringkasan, Sampel & hasil, Sesi & pemetaan, Asal & catatan.
Skrip khusus halaman memindahkan node komponen `_qc_sosoh.html` yang sama ke
panel, termasuk editor asli; tidak menggandakan form, id, field, atau handler.
Sebelum membuka editor, panel Sampel & hasil ditampilkan agar editor terlihat.
Catat QC dan tautan proses tetap menjadi satu area tindakan di dalam root QC.
Pergantian tab mempertahankan node/isian. Penyimpanan dan Lanjutkan nanti tetap
menyegarkan melalui alur asli, dengan tab dipulihkan dari query URL.
Tanpa skrip penataan, seluruh komponen QC beras asli tetap terlihat.

Total hasil timbang tetap aktual. Sesi, durasi dan alokasi sampel tetap berlabel
estimasi. Jenis/waktu sampel, pengambil, lima komponen, catatan, pemeriksa,
waktu lab, pembatalan, batas pergantian dan rentang pemetaan tidak dibuang.
Sampel dibatalkan tetap terlihat dan tidak ikut pemetaan. Pengisian lab setelah
proses selesai tetap tersedia; pengambilan sampel baru tetap mengikuti status.

Layanan, perhitungan mutu, endpoint, validasi, idempotensi, CSRF, izin gudang,
portal pelanggan, macro penilaian dan komponen/editor QC bersama tidak diubah.
Tidak ada migrasi atau perubahan data produksi. Aset baru hanya berlaku pada
halaman Riwayat QC, menggunakan cap aset bersama yang sudah ada.

Validasi: `tests/pg/test_riwayat_qc_desain_browser.py` (saklar
`UJI_BROWSER_RIWAYAT_QC_DESAIN=1`) menguji lebar 1440, 390 dan 320 piksel,
semua kategori bahan, putaran, perhitungan, sumber/catatan, menu/panduan,
draf editor, pengambilan, hasil desimal dan pembatalan sampel lewat API asli,
operator tanpa editor, proses selesai serta aktual vs estimasi. Suite QC lama,
portal, penilaian, paket tampilan dan cap aset ikut dijalankan pada PostgreSQL
lokal terisolasi. Penerapan ini belum dirilis ke produksi.
