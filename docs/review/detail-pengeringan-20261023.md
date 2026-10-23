# Detail pengeringan dan pendinginan — inventaris sebelum perubahan

Acuan fungsi: `proses_aktif.rincian`, `berjalan.untuk_operator_gudang1`, template `proses_aktif_detail.html`, layanan `drying`, jeda, aksi.js dan endpoint lama. Acuan visual: USULAN detail-pengeringan-desktop/ponsel tanggal20 Oktober2026.

|Informasi/tindakan lama|Lokasi baru|Sumber/kondisi dipertahankan|
|---|---|---|
|Kode/pemilik/pabrik-jasa/pesanan/gudang/dryer/mode/status/nota|Hero, Bahan, Riwayat|Identitas kartu dan model; tidak memakai contoh|
|Bahan, alat tes terakhir, target|Ringkasan dan Pengukuran|Bobot `dari_batches`, log alat tes non-NULL terakhir, target lot/fallback helper setelan|
|Awal proses/fase/pencatat/berlalu/efektif/jeda/berat/waktu ukur/selesai|Riwayat lengkap dan Ringkasan waktu|Seluruh d.fakta lama, helper waktu/jeda|
|Seluruh batch/kondisi/berat/pemasok/pemilik/tiket/waktu/kendaraan|Bahan|_lot_batches dan _bahan_gabah lama; asal bukan tambahan bahan|
|Pengukuran rata-rata, empat sampel, indikator, waktu/pencatat/pagination|Pengukuran|_log lama, halaman_ukur; ringkasan tidak dipaginasi|
|Kemajuan/peringatan|Ringkasan dan Pengukuran|kartu.maju dan peringatan_kadar_air, tidak menyalin rumus/ambang|
|Seluruh jeda/kejadian/pencatatan/sebab/kondisi/keterlambatan/pembatalan/pagination|Riwayat|macro riwayat_jeda_blok lama|
|Seluruh catatan putaran pendinginan/waktu/pencatat/pagination|Riwayat|DryingCoolingLog, halaman_dingin lama|
|Perbarui kadar air, dinamis1–4 titik, indikator terpisah|Utama Ringkasan berjalan; Pengukuran; tetap tersedia dijeda|kadar_air, nilai kode lot lama; dialog/endpoint unchanged|
|Ubah target dan kembali mempertahankan draft, konfirmasi/audit|Dari dialog kadar air lama|ubah_target, terpisah dari pengukuran; bukan kontrol baru di tab|
|Hentikan sementara|Ringkasan berjalan|hentikan_proses, nilai pengeringan:kode|
|Lanjutkan pengeringan|Utama Ringkasan dijeda|lanjutkan_proses, pengeringan:kode|
|Perbarui kondisi|Pengelolaan proses dijeda|ubah_kondisi_proses; tidak melanjutkan|
|Selesai pengeringan|Pengelolaan proses|selesai_pengeringan; indikator akhir wajib; transisi otomatis layanan|
|Nyatakan sudah dingin|Utama Ringkasan pendinginan|selesai_pendinginan lama; tidak memindah bahan|
|Dinginkan lagi/Pindah ke silo|Riwayat dan tindak lanjut lama setelah sudah dingin|halaman riwayat tidak diganti; kapasitas/izin/pemilik/putaran tetap layanan lama|
|Kembali/buka/nilai/hash/pagination/refresh/navigasi instan|Semua tab|konteks_aman, handler PINDAH lama, fragment dipetakan tab|

Hanya pilihan dari proses.pilihan yang disajikan. Backend gudang/peran/tampilan efektif dan status tidak berubah. Proses sudah dingin tetap dialihkan ke riwayat; pengeringan selesai mengikuti detail pendinginan. Penanda tahap informatif, tidak dapat ditekan.

## Hasil pemeriksaan
Implementasi memakai template/CSS/JS khusus pengeringan dan pendinginan aktif. Desktop menampilkan pantauan dan ringkasan berdampingan, ponsel satu kolom. Empat tab berkotak; penanda tahap hanya informasi. Metadata tampilan membaca bacaan dan waktu alat tes/mesin secara terpisah; riwayat menampilkan empat kolom titik tanpa mengubah pengukuran tersimpan. Semua d.fakta dan bagian lama dipetakan di atas.

Berkas aplikasi: `app/services/proses_aktif.py`, `app/web/layar_berjalan.py`, `app/web/templates/detail_pengeringan.html`, `_detail_pengeringan_bagian.html`, `app/web/static/detail_pengeringan.css`, `detail_pengeringan.js`, dan `app/web/templates/proses_aktif_beralih.html`. Ditambah `tests/pg/test_detail_pengeringan_tab.py` serta laporan ini.

Dua integrasi antarmuka dibuktikan di browser: tombol Hapus untuk titik tambahan (maksimal tetap4), dan draft alat tes/indikator ketika membuka target lalu kembali, termasuk sesudah target disimpan. Draft hanya dalam memori halaman dan dipagari kode lot/CSRF sesi; formulir, validasi dan penyimpanan target tetap lama. Halaman peralihan diberi wadah `kabar` karena callback sukses lama mencoba menulis ke wadah yang belum ada; stack galat direproduksi, lalu diuji ulang tanpa galat. Paket tampilan vendored tidak diedit.

### Pemeriksaan nyata

- Seluruh `tests/pg`: **1.325 lulus, 497,92 detik** pada PostgreSQL loopback55449, DB `uji_giling_detail`. Setelah tambahan tes waktu aktual, empat kolom sampel dan wadah notifikasi: **49 tes terkait lulus, 28,65 detik**, mencakup enam kasus baru (tiga peran + penutupan/ulang + legacy/target/audit + jeda aktual), giling, sosoh, jeda dan alur proses bersama.
- Non-PG: **787 lulus, 6,33 detik**; `git diff --check`, pemeriksaan sintaks JS dan compile Python bersih.
- Browser Chromium: tiga peran × lima ukuran320/390/768/1440/1920 × empat tab =60 kombinasi, tanpa overflow horizontal; Home/ArrowRight berfungsi. Tujuh hash lama membuka tab sesuai lokasi. Konteks kembali dipertahankan. Tab desktop1.067,84px/ponsel358px dan tinggi44px tetap pada semua tab/halaman.
- Fixture: bahan8.000 + tambahan2.000 =10.000kg; seluruh batch, tiketTK-DR-TAB, kendaraanB4321UJI. Pengukuran15/NULL/17/16 menghasilkan16,0%, bukan12%; indikator19 terpisah.21 catatan dipaginasi20 tanpa mengubah ringkasan; data kosong memakai teks helper bobot asli.
- Format request lama `tes_1/tes_3` tetap menghasilkan16; `kadar_air:18` tetap catatan indikator saja. Target13→14 tercatat old/new/pencatat; jumlah log tidak bertambah dan target global tidak berubah. Range/wajib memakai model dan layanan lama.
- Browser dinamis: menambah sampai4 titik, menghapus titik tambahan mempertahankan15/17/18 dan indikator20; membuka target lalu kembali mempertahankan draft. Target14 dikonfirmasi terpisah. Pemeriksaan tambahan: draft18 tetap ada sesudah target disimpan/refresh. Klik ganda pengukuran mengirim satu POST.
- Browser jeda: hentikan Listrik padam → kondisi Mesin dryer rusak → catat alat tes14/mesin17 tetap dijeda → lanjut. Kemajuan100% tetap aktif. Kasus aktual backend: mulai4jam lalu, berhenti padajam1, kondisi padajam2, lanjut padajam3; jeda tepat7.200detik, efektif2jam; kejadian/pencatatan/alasan terlambat terpisah.
- Browser selesai: isian indikator kosong dicegah; mesin18 (di atas target14) diterima sesuai aturan lama, satu POST, otomatis masuk pendinginan; alat tes14 dan waktu aslinya tetap, mesin18/waktunya terpisah, tindakan pengeringan hilang. Konteks Pekerjaan tetap dibawa.
- Browser/suite: Nyatakan sudah dingin → detail riwayat lama; bahan belum ke silo. Dinginkan lagi melalui rincian Pekerjaan memakai konfirmasi lama; riwayat dan status belum siap pindah dipertahankan. Putaran kedua dinyatakan dingin lalu Pindah ke silo melalui formulir lama, satu POST dan tanpa galat JS.
- Query DB uji sesudah alur: status lot selesai, target14;4 catatan pendinginan; tepat1 baris SiloStorage untuk lot, status terisi. Audit target13.0→14.0 satu baris. `test_alur_proses_ux::test_pendinginan_ulang_menahan_pindah_dan_menyimpan_waktu` membuktikan larangan pindah saat pendinginan, arsip putaran lama dan penolakan ulang setelah ke silo.
- Hak akses: masing-masing operator/admin/superadmin dapat membaca empat tab pada gudang1; tampilan efektif operator:g2 ditolak403 pada detail dan POST langsung. Semua tombol berasal pilihan lama, bukan dari tab. Full suite mencakup sesi dicabut, CSRF, koreksi, kepemilikan, kapasitas, stok dan konkurensi.
- Durasi memakai d.fakta/tertahan_detik/lama_kata lama; pendinginan memakai selisih dari awal fase tanpa mengurangi jeda. `drying.finish_cooling` tetap menyimpan waktu pernyataan yang menjadi dasar idle, `mulai_pendinginan_ulang` mencabut status siap dan mengarsip putaran. Keduanya tidak diubah. Pemeriksaan kode dan regresi fase/riwayat mengonfirmasi dasar waktunya tetap; tidak mensimulasikan mesin fisik.

### Checklist penerimaan

**Tampilan dan kelengkapan6/6**
- [x] Desktop/ponsel mengikuti susunan USULAN.
- [x] Empat tab berfungsi.
- [x] Informasi/tindakan lama terpetakan.
- [x] Identitas/pemilik/gudang/dryer/mode/pesanan dari data asli.
- [x] Kosong/legacy/bobot belum final atau tidak diketahui tetap dari helper.
- [x] Tidak ada overflow/potongan container pada lima ukuran yang diuji.

**Bahan dan stok6/6**
- [x] Batch/berat/tiket/waktu/kendaraan tersedia.
- [x] Total memakai dari_batches, tidak menambah bobot asal lagi.
- [x] Gabung tambahan2.000kg diuji lewat layanan lama.
- [x] Pabrik/jasa mengikuti identitas dan pagar kepemilikan lama; suite penuh.
- [x] Pergantian fase tidak menghasilkan SiloStorage sebelum pindah.
- [x] Pindah memakai layanan lama; status/kapasitas/kepemilikan tidak diganti.

**Pengukuran9/9**
- [x]1–4 titik, batas4 tetap.
- [x] Tambah/hapus tidak membuang nilai lain.
- [x] Rata-rata hanya titik terisi.
- [x] Indikator terpisah.
- [x] Sampel/waktu/pencatat tersedia, empat kolom titik.
- [x] Riwayat/pagination20 tetap.
- [x] Indikator penutupan tidak menghapus tes/waktunya.
- [x] Request legacy empatkolom dan indikator tunggal diuji.
- [x] Model/range/aturan wajib tidak diubah.

**Target dan kemajuan8/8**
- [x] Target terpisah dengan konfirmasi nilai/akibat lama.
- [x] Draft kembali utuh dan bertahan sesudah target disimpan.
- [x] Audit old/new/pencatat diverifikasi.
- [x] Tidak ada log palsu/target global berubah.
- [x] Kemajuan memakai kartu.maju/helper lama.
- [x] Belum dapat dihitung tetap jelas.
- [x]100% tetap aktif hingga tindakan selesai.
- [x] Ambang1,5/2,0 memakai peringatan_kadar_air lama; batas diuji unit, kasus2/3 diuji integrasi.

**Jeda dan waktu6/6**
- [x] Hentikan/lanjut/kondisi browser dan backend.
- [x] Pengukuran/kondisi tidak melanjutkan.
- [x] Sebab mengikuti konfigurasi pengeringan.
- [x] Kejadian/pencatatan/alasan terlambat terpisah.
- [x] Efektif/jeda/pergantian fase memakai sumber lama, kasus7.200detik.
- [x] Riwayat dan pembatalan memakai macro/layanan lama; suite penuh.

**Penyelesaian dan pendinginan8/8**
- [x] Indikator akhir wajib, range dan waktu layanan lama.
- [x] Selesai otomatis ke pendinginan.
- [x] Tindakan pengeringan tidak tertinggal.
- [x] Gabah tetap dryer sebelum pindah.
- [x] Nyatakan dingin dan redirect riwayat lama.
- [x] Ulang mempertahankan riwayat serta menahan pindah.
- [x] Dasar pendinginan/idle tetap waktu tersimpan dari layanan lama (pemeriksaan kode + regresi waktu/fase).
- [x] Klik ganda/transisi dan notifikasi sukses diperiksa tanpa transaksi ganda.

**Hak akses dan navigasi6/6**
- [x] Operator memakai gudang efektif.
- [x] Admin/superadmin/tampilan sebagai operator diperiksa.
- [x] URL/API langsung tanpa izin ditolak403.
- [x] Tab tidak menambah pilihan/status baru.
- [x] Kembali/refresh/hash/buka/nilai/pagination/fase dipertahankan.
- [x] Listener pada elemen halaman/dialog sendiri; hash global memakai PINDAH.pasang; klik ganda dan navigasi instan diuji.

### Tangkapan dan batas verifikasi

`output/detail-pengeringan/`: empat tab desktop/ponsel lengkap, Pengukuran halaman2, bukti ukuran dan alur JSON. Subfolder `pendinginan/` menyediakan empat tab serta halaman2 pada fase pendinginan. Semua details dibuka; CSS capture hanya mengembangkan container gulir, tidak mengubah aplikasi. Berkas hasil-database dan logpytest menjadi bukti tambahan.

Belum diuji: perangkat iOS/Android fisik, Safari/Firefox, pembaca layar, seluruh kombinasi data operasional atau pengoperasian mesin fisik. Semua transaksi uji memakai DB loopback dengan awalan uji_; tidak ada mutasi data operasional. Status deploy diverifikasi terpisah melalui hash/status Railway.

