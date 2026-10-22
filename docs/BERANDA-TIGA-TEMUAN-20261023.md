# Perbaikan tiga temuan Beranda — 23 Oktober 2026

Perubahan telah ditinjau dan disetujui pemilik untuk push serta deploy pada 23 Oktober 2026. Beranda tidak memerlukan migrasi tambahan. Perubahan Kabar yang sudah ada saat pekerjaan dimulai dipertahankan, termasuk model, rute, status baca dan detail permintaan Pekerjaan. Sumber tampilan diperbarui di repo Tampilan, versi **402**, lalu disinkronkan dengan skrip resminya.

## Penyebab dan perbaikan

1. Seluruh pembacaan Beranda berada dalam satu `try`; objek kosong bawaan tetap dikirim setelah exception. Akibatnya kegagalan dapat terlihat seperti pekerjaan habis atau tidak ada mesin aktif. Sekarang pekerjaan/proses, ringkasan, peringatan dan Pengiriman dibaca dalam sesi terpisah dengan bendera keberhasilan. Bagian yang berhasil tetap dirender. Bagian gagal menampilkan pesan umum dan tautan GET `/` “Coba lagi”. Rincian exception hanya masuk log. Hitungan pekerjaan yang tidak diketahui dikirim sebagai `None`, dan ringkasan gagal tidak digambar sebagai nol atau akun tanpa gudang. Kesimpulan “Semua sudah ditangani” mensyaratkan seluruh pembaca yang diperlukan berhasil; kesimpulan mesin kosong mensyaratkan pembaca proses berhasil.
2. Partisi konsolidasi yang tersedia, `kelompok_kerja.bagi`, sebenarnya sudah mempertahankan kartu informasi tanpa tindakan. Celahnya berada pada akses Beranda. Sekarang terdapat pintu **Status & informasi** ke `/pekerjaan?tab=berjalan&informasi=1`. Filter ini membatasi bagian informasi yang sudah ada di tab Berjalan; bukan tab ketiga dan bukan tugas wajib. Pintu `/aksi` Antrian tunggu di badan Beranda dihapus setelah partisi diuji. Rute alias lama dan parameter tindakan tidak diubah.
3. Pengiriman sebelumnya menghitung kartu tindakan `grup=muat` dan menuju Pekerjaan. Kini menuju **`/barang-keluar?status=perintah`**. Helper baca `barang_keluar.menunggu_muat` memakai `daftar` yang sama dengan halaman Barang Keluar, tanpa membuat transaksi baru atau mengubah aturan muat. Filter aktif disebutkan di halaman tujuan.

## Inventaris dan pemetaan antrean lama

Sumber inventaris: `berjalan._GRUP_AKSI`, `_GRUP_KELOMPOK`, `keputusan.SEMUA`, `kelompok_kerja.PENERIMAAN`, seluruh daftar `menunggu`, `meja`, `transit`, `berjalan`. Partisi mengikuti kemampuan kartu asli, termasuk tombol yang dinonaktifkan, bukan hanya nama kelompok. Tidak ada perubahan pada penyusun kartu atau izin/tindakan masing-masing.

| Catatan lama | Akses pengganti |
|---|---|
| `gabah_masuk`, `catat_pk_luar`, `catat_beras_timbang_masuk`, `catat_broken_timbang_masuk` | Barang Masuk, Belum ditangani; formulir lama tetap dipakai |
| Tiket informasi tanpa aksi, termasuk tiket yang dicatat Admin | Barang Masuk; tetap informasi bagi peran yang tidak berwenang menerima |
| `pindah_tumpukan`, `masukkan_pk`, `pindah_tumpukan_silo`, `pindah_silo` | Pekerjaan → Perlu tindakan, kategori penempatan/transfer |
| `mulai_pengeringan`, `mulai_giling`, `mulai_penyosohan`, serta tindakan operasional lain yang tersedia | Pekerjaan → Perlu tindakan; aksi dan formulir asli dipertahankan |
| `catat_packing` dan varian packing pabrik/jasa | Pekerjaan → Perlu tindakan, Packing |
| `muat_semua`/kartu keluar yang dapat ditindak | Pekerjaan → Perlu tindakan tetap tersedia; pintu Pengiriman di Beranda menuju Barang Keluar |
| `acc_permintaan_pk`, `tutup_permintaan_pk`, `betulkan_bobot_giling` | Pekerjaan → Perlu tindakan, Keputusan |
| `kirim_permintaan_pk`, permintaan transfer yang dapat ditindak | Pekerjaan → Perlu tindakan, Transfer PK |
| `qc_giling`, `qc_pk_luar`, `qc_gabah_basah`, `qc_gabah_kering` | Pekerjaan → Perlu tindakan, QC; sakelar mutu dan hak akses lama tetap berlaku |
| Mesin aktif, pendinginan, giling, sosoh dan proses dijeda | Tetap di Beranda dengan tindakan langsung; juga Pekerjaan → Berjalan |
| Transit yang dapat ditindak | Tetap di Beranda; Pekerjaan → Perlu tindakan |
| Transit tanpa tindakan, kartu diam kelompok produk/permintaan/penyosohan/keluar/tumpukan, serta jenis informasi yang tidak dikenal | Pekerjaan → Berjalan → Status & informasi, pintu khusus dari Beranda |
| Jenis operasional baru yang belum dikategorikan | Perlu tindakan jika memang dapat ditindak; selain itu Status & informasi. Tidak dibuang karena namanya tidak dikenal |

Pengujian partisi membandingkan identitas objek kartu, termasuk seluruh id aksi yang terdaftar dan catatan tanpa aksi. Fixture konsolidasi juga menguji tiket lima jenis, operator G1/G2, admin/superadmin dan cakupan lihat-sebagai. Informasi tidak masuk jumlah pekerjaan wajib.

Jumlah Barang Masuk di **Beranda saja** mengikuti jumlah semua kartu daftar Belum ditangani, termasuk kartu informasi tiket; hitungan global `Berjalan.lencana()` tidak diubah. Jumlah Pekerjaan tetap jumlah Perlu tindakan. Jumlah Status & informasi tepat `len(kerja.informasi)`, sesuai daftar tersaring tujuannya. Tidak dibuat total gabungan: Pengiriman dapat beririsan dengan tindakan muat pada Pekerjaan, sehingga kedua angka tidak dijumlahkan.

## Aturan Pengiriman

- Satuan: satu `OutgoingRecord`/transaksi, bukan item muatan, kilogram, atau tombol tindakan.
- Status: `perintah`, termasuk perintah yang muatannya masih sebagian. Status `dimuat`, `selesai`, `dibatalkan` tidak masuk filter menunggu muat.
- Halaman dan kartu memakai helper pembaca yang sama. Daftar filter ini tidak dibatasi 500 baris sehingga jumlah tidak berbeda karena pemotongan daftar.
- Cakupan: Admin ke atas dan operator G2 sesuai pembaca serta gerbang lama Barang Keluar. Operator G1 tidak ditawari kartu; URL Barang Keluar tetap menolaknya. Tindakan yang sebelumnya tersedia bagi G1 melalui Pekerjaan/API tidak diubah.
- Pembaca tetap menerima pencarian, tanggal dan pelanggan jasa dari halaman yang ada. Halaman tanpa filter, histori, detail transaksi, tombol muat/verifikasi dan hubungan timbang tidak dihapus.

## Hasil dan bukti

Bukti berada di `output/beranda402/`:

- `unit.txt`: seluruh unit Produksi, tanpa suite PG/Timbangan, **753 lulus**.
- `postgres.txt`: regresi Beranda, konsolidasi Pekerjaan, Barang Keluar, proses aktif dan Kabar. **201 lulus**.
- `visual-tests.txt`: **54 lulus** pada pengujian tampilan Beranda yang tersedia, termasuk ponsel 320–430 px, tablet, desktop, kedua tema, progres dan proses dijeda.
- `visual.json`: 16 screenshot dan pemeriksaan fokus keyboard berbasis HTML HTTP aktual, sebelum/sesudah serta kosong/gagal/sebagian, pada 390/1440 px. Tidak ada overflow horizontal atau exception JavaScript.
- `paritas.json`: objek kartu proses/transit sebelum dan sesudah identik. Pembanding menggunakan akun dan database yang sama; sumber lama diambil dari snapshot lokal sebelum pekerjaan ini, termasuk perubahan Kabar yang saat itu sudah ada.
- `tidak.html`: pembaca pekerjaan berhasil dan kosong; pesan kosong sah.
- `pekerjaan.html`: pembaca pekerjaan gagal; tidak menyimpulkan pekerjaan habis atau mesin mati, ringkasan yang berhasil tetap tersedia.
- `ringkasan.html`: ringkasan gagal; tidak menggambar nol palsu, bagian lain tetap tersedia.
- `pengiriman.html`: Pengiriman gagal; tidak menyimpulkan seluruh pekerjaan sudah selesai.
- `semua.html`: seluruh pembaca utama gagal; pesan mencoba kembali, tanpa kesimpulan kosong.
- `aktif-sesudah-1.html`: proses aktif asli tetap dirender. Uji terpisah membuktikan lot dari dua hari lalu tetap tampil saat ringkasan gagal dan tautan formulir kadar air tetap tersedia.

HTML screenshot memakai hasil server nyata dengan respons sesi/polling uji saat dibuka di Chromium; pengujian transaksi/izin memakai HTTP ASGI dan PostgreSQL sungguhan. Tidak ada akses data produksi. Pengujian mengulangi GET dan memeriksa tidak lahir transaksi keluar; kode retry tidak mengirim POST atau membawa `buka`/`nilai`.

## Checklist

### A. Pemuatan data

- [x] Data berhasil dan benar-benar kosong menampilkan pesan kosong — simulasi `tidak`.
- [x] Gagal membaca database tidak menampilkan “Semua sudah ditangani” — exception pembaca pekerjaan/semua.
- [x] Kegagalan tidak disimpulkan sebagai tidak adanya proses aktif — cabang error terpisah.
- [x] Pesan jelas dan cara mencoba kembali — GET `/`, tanpa rincian teknis.
- [x] Bagian berhasil tetap tersedia saat gagal sebagian — sesi terpisah dan uji proses asli/ringkasan gagal.
- [x] Mencoba kembali tidak membuat transaksi/tindakan ganda — GET berulang dan pemeriksaan jumlah transaksi; pembaca transaksi tidak mengeksekusi aksi.

### B. Pengganti antrean lama

- [x] Semua jenis dipetakan — tabel inventaris dan partisi lengkap dengan fallback jenis tak dikenal.
- [x] Tiket, tindakan, QC, keputusan, transit dan informasi terjangkau — regresi konsolidasi dan filter informasi.
- [x] Catatan tanpa tindakan tidak hilang/dihitung sebagai kewajiban — partisi identitas kartu dan tes HTTP informasi.
- [x] Jumlah kartu sesuai daftar tujuan — sumber partisi yang sama; tiket memakai jumlah daftar, bukan hanya tiket actionable.
- [x] Antrian tunggu hilang dari badan Beranda — DOM/tes HTTP; pengganti informasi terverifikasi.
- [x] URL lama, parameter, dan tautan tindakan tetap berjalan — alias tidak diubah dan regresi konsolidasi.
- [x] Pekerjaan tetap dua tab — Perlu tindakan/Berjalan; filter informasi berada di Berjalan.

### C. Pengiriman

- [x] Kartu menuju Barang Keluar — `/barang-keluar?status=perintah`.
- [x] Filter menunggu muat diterapkan — status `perintah`, disertai label filter pada tujuan; tidak menambah tab transaksi baru.
- [x] Jumlah sama dengan daftar — helper baca yang sama; uji dua transaksi pada admin/operator G2.
- [x] Detail, muat, verifikasi, timbang dan pencatatan keluar tetap berjalan — suite Barang Keluar dan konsolidasi, log regresi.
- [x] Aksi melalui Pekerjaan tetap berjalan — tautan grup muat diuji; logika/formulir API tidak diedit.
- [x] Visibilitas, URL langsung dan API mengikuti hak lama — helper tidak memperluas kewenangan, G1 ditolak rute, regresi izin transaksi.

### D. Regresi Beranda

- [x] Pengeringan, giling, sosoh, dijeda dan transit dipertahankan — pembaca kartu tidak diubah; paritas dan suite detail/tampilan.
- [x] Proses hari sebelumnya tetap tercakup — lot asli bertanggal dua hari lalu.
- [x] Tindakan langsung dan formulir tetap tersedia — makro kartu/dialog/`aksi.js` tidak diubah; tautan kadar air dan suite detail proses.
- [x] Perhitungan stok/transaksi/status tidak diubah — perubahan hanya pembaca/filter dan orkestrasi render; regresi Barang Keluar termasuk saldo saat muat.
- [x] Desktop, ponsel, kedua tema dan keyboard — pengujian responsif serta tautan/tombol native dengan gaya fokus lama. Peninjauan visual screenshot tercatat.
- [x] Sinkron paket/manifest lulus — versi 402 dan tes penjaga dalam suite unit.
- [x] Kabar dan modul lain tidak tertimpa — suite Kabar di regresi; perubahan pada layar Pekerjaan hanya filter informasi, detail permintaan Kabar tetap tersedia.

## Keterbatasan

- Belum diuji pada akun/data produksi, perangkat fisik, iOS Safari/PWA atau jaringan gudang nyata.
- Simulasi kegagalan memakai exception pada fungsi pembaca di HTTP aplikasi; tidak mematikan server database fisik. Exception dan pemulihan antar sesi benar-benar melewati route/render.
- Pengujian browser memakai data sesi/polling yang disediakan harness; bukan transaksi browser langsung ke produksi. Regresi transaksi dijalankan melalui HTTP/layanan dan PostgreSQL lokal.
- Kartu Pengiriman dan daftar filter membaca seluruh transaksi menunggu muat agar jumlah tepat. Beban pada jumlah transaksi produksi yang sangat besar belum diukur.
- `berjalan.untuk` tetap pembaca lama, termasuk pemeliharaan otomatis historis yang sudah ada; tidak ada pengulangan formulir/transaksi operasional pada retry.
- Deploy hanya setelah tinjauan dan persetujuan pemilik.
