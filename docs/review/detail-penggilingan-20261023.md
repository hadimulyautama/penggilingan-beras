# Detail penggilingan — inventaris dan pemeriksaan

## Inventaris sebelum penyuntingan

Acuan fungsi: `proses_aktif_detail.html`, `proses_aktif.rincian`, kartu giling `berjalan.untuk_gudang1`, helper milling, sumber bahan, mutu PK dan jeda. Acuan penyajian: bagian USULAN `detail-penggilingan-{desktop,ponsel}.html` tanggal 20 Oktober 2026.

| Informasi/tindakan yang ada | Lokasi baru | Sumber/kondisi tetap |
|---|---|---|
| Kode, jenis, kepemilikan, nama/pesanan jasa, Gudang 1, status, nota, data belum final | Hero semua tab | Identitas pekerjaan, status model/jeda, macro kepemilikan |
| Gabah masuk + belum final/belum diketahui, PK kumulatif terbaru/belum dicatat, rendemen sementara | Ringkasan dan Hasil & QC | `d.statistik`, `_latest_progress`, bobot model; tanpa penjumlahan log |
| Pemilik, gudang, mulai proses/fase, pencatat awal, waktu berlalu, efektif, total jeda, catatan | Riwayat; ringkasan waktu di Ringkasan | Seluruh `d.fakta`, `proses.catatan`, helper jeda |
| Seluruh sumber/pemakaian silo: awal, tambahan, sisa, terpakai, status, sumber ulang | Bahan & silo | `sumber_giling_banyak` dan macro bersama; sumber warisan tetap ditampilkan |
| Batch/lot, pemasok/pemilik, kondisi/bobot batch, tiket, waktu masuk dan kendaraan | Bahan & silo → Asal bahan gabah | `_bahan_gabah`; bobot asal bukan tambahan/sisa proses |
| Riwayat PK kumulatif, waktu, pencatat, pagination | Hasil & QC | `_log` 20 per halaman, tidak dijumlahkan |
| Nilai QC, kelas, kelengkapan, jumlah putaran, enam komponen, rumus/aturan skor dan kelas | Hasil & QC; ringkasan singkat di Ringkasan | `penilaian_dari_log` atas semua log + macro `penilaian_pk` lama |
| Riwayat semua QC: nomor/waktu, pemeriksaan angka/kualitatif, nilai, kondisi, catatan lab, pencatat, pagination | Hasil & QC | `_log` lama; ringkasan QC tetap semua putaran |
| Riwayat jeda/perubahan kondisi: kejadian, pencatatan, sebab, catatan, keterlambatan, pembatalan, halaman | Riwayat | `riwayat_jeda_blok` lama |
| Perbarui hasil giling | Utama Ringkasan berjalan; tersedia dijeda; Hasil & QC | `hasil_giling`, nilai kode asli, aturan koreksi lama |
| Catat mutu sekarang | Pengelolaan proses dan Hasil & QC | Hanya bila `qc_giling` ada pada pilihan lama: izin QC + fitur aktif + tidak dijeda |
| Tambah silo/mix | Pengelolaan proses dan Bahan & silo | Hanya bila `tambah_silo_giling` ada; tidak ditambahkan saat dijeda |
| Hentikan sementara | Langsung di Ringkasan berjalan | `hentikan_proses`, nilai `giling:{kode}` |
| Lanjutkan giling | Utama Ringkasan dijeda | `lanjutkan_proses`, nilai `giling:{kode}` |
| Perbarui kondisi jeda | Pengelolaan proses dijeda | `ubah_kondisi_proses`, tidak melanjutkan mesin |
| Bebaskan silo | Pengelolaan proses dan Bahan & silo | `tutup_silo_giling`; sisa fisik + pratinjau/token lama; tidak menutup proses |
| Selesai giling | Pengelolaan proses | `selesai_giling`; semua pemeriksaan sisa, hasil akhir, cuplikan terbaru dan token lama |
| Kembali, buka/nilai, konteks Pekerjaan, fragmen dan pagination | Semua tab | URL lama tetap; tab hanya mengubah penempatan |
| Proses selesai, verifikasi/koreksi/QC lanjutan dan audit | Jalur riwayat lama | Redirect detail aktif, gerbang dan endpoint lama tidak diganti |

Operator diperiksa terhadap gudang kerja efektif di backend; Admin/Super Admin dan tampilan sebagai peran lain tetap memakai mekanisme identitas lama. Dialog, penanganan gagal/berhasil, pengiriman ganda dan sesi tetap melalui `aksi.js`/CSRF lama. Tidak menambah tindakan berdasarkan isi tab.

## Hasil implementasi dan pengujian

Tampilan khusus giling memakai empat tab, hero ringkas, kartu angka, tindakan rutin dan Pengelolaan proses. Desktop memakai ringkasan berdampingan; ponsel satu kolom dengan empat tab berukuran tetap. Formulir, endpoint, layanan produksi, helper QC, sumber, stok, jeda, konfirmasi/token dan CSRF tidak diganti. Tambahan service hanya metadata tampilan jeda, daftar silo dan jenis PK dari helper lama.

Berkas: `app/services/proses_aktif.py`, `app/web/layar_berjalan.py`, `app/web/templates/detail_giling.html`, `_detail_giling_bagian.html`, `_bahan_silo_giling.html`, `app/web/static/detail_giling.css`, `detail_giling.js`, `tests/pg/test_detail_giling_tab.py`, dan laporan ini. Template bersama proses lain dan halaman riwayat tidak diubah.

### Bukti pengujian 23 Oktober 2026

- PostgreSQL lokal terisolasi: **1.277 lulus dalam 475,55 detik**, seluruh `tests/pg`, termasuk enam kasus baru detail giling.
- Non-PostgreSQL: **774 lulus dalam 8,85 detik**, `pytest -o addopts='' -q tests --ignore=tests/pg`.
- Pemeriksaan terarah awal: 62 lulus; enam kasus baru juga lulus terpisah. `git diff --check` bersih.
- DB uji bernama `uji_giling_detail` dan `uji_giling_browser`, loopback port 55449; aplikasi browser pada port 8059. Tidak memakai data operasional.
- Browser Chromium: 60 kombinasi (3 peran × 5 lebar 320/390/768/1440/1920 × 4 tab), tanpa overflow horizontal. Keyboard Home/ArrowRight, navigasi instan berulang, sembilan fragmen lama dan kembali/konteks diperiksa. Lebar tab desktop 1.067,84 px dan ponsel 358 px, tinggi selalu 49 px pada semua tab/pagination.
- Kumulatif awal 3.000 lalu 6.400 kg menghasilkan 6.400 kg dan 64,0%, bukan jumlah log. Browser memperbarui 6.600 lalu mengoreksi 6.500: setiap klik ganda hanya satu POST dan total mengikuti catatan terbaru. Saat dijeda, 6.600 kg tersimpan tanpa melanjutkan mesin.
- QC: 21 putaran menghasilkan 88,33/B1; pagination kedua tetap 21 putaran/88,33. Browser menambah putaran ke-22, nilai tetap 88,33. Pilihan kualitatif kosong mencegah pengiriman; penyimpanan klik ganda hanya satu POST. Operator tidak mendapat tindakan QC, Admin/Super Admin mendapatkannya saat berjalan dan fitur aktif.
- Browser: hentikan → ubah kondisi → catat hasil tetap dijeda → lanjutkan. Riwayat memisahkan kejadian dan pencatatan. Suite jeda memeriksa waktu aktual/terlambat, pembatalan, durasi dan penutupan interval.
- Browser: Bebaskan Silo A dengan 100 kg, B dengan 0 kg melalui pratinjau/token. Proses tetap aktif setelah masing-masing. Sesudah Selesai giling dengan hasil 6.600 kg dan konfirmasi, redirect `/riwayat-giling/1`. Query DB: A terisi, sisa100/terpakai5900; B kosong, sisa0/terpakai4000; kedua ikatan kosong; proses selesai; verifikasi otomatis **0**.
- `test_pembebasan_silo_giling`, `test_silo_selesai_aman`: sumber isi ulang tidak masuk lot lama, mix, sisa tidak sah, pemakaian ulang, konfirmasi basi, konkurensi dan perlindungan stok.
- `test_stok_penerimaan::test_koreksi_hasil_giling_saldo_rendemen_audit_dan_batal`: hasil 6.500 → terverifikasi 6.750,25, stok/rendemen 67,5025%, pembatalan kembali 6.500/65%; QC setelah selesai, audit dan izin jalur lama diuji oleh suite yang sama.
- `test_qc_pk_putaran`, `test_stok_pk_qc`, `test_qc_berjalan`: enam komponen, rata-rata seluruh putaran, kekosongan, rentang/wajib, kelas/pembulatan, pembatalan, konfigurasi fitur dan izin.
- `test_detail_giling_tab`: data lama/bobot belum diketahui bukan nol; seluruh identitas/sumber/tiket/kendaraan; pagination tidak mengubah total/QC; gudang kerja efektif untuk tiga peran; penyamaran peran; akses API ditolak 403; fitur QC nonaktif ditolak backend.
- Suite penuh mencakup pengeringan, pendinginan, penyosohan, detail/riwayat, sesi dicabut, koreksi/sesi aman dan validasi CSRF. Tidak ada perubahan pada template/CSS bersama; tidak ditemukan regresi otomatis.

### Checklist penerimaan

Semua tanda di bawah didasarkan pada pemeriksaan kode, suite dan alur browser di atas; bukan klaim pengujian seluruh kombinasi data produksi.

**Informasi dan tampilan — 6/6**
- [x] Desktop/ponsel mengikuti susunan USULAN, tanpa kontrol contoh.
- [x] Empat tab dapat dipilih dengan tautan dan keyboard.
- [x] Seluruh informasi lama dipetakan dalam tabel inventaris.
- [x] Kode/pemilik/gudang/pesanan/status/catatan berasal data lama.
- [x] Legacy/kosong/bobot tidak diketahui tidak diganti nol.
- [x] Lima lebar layar diperiksa tanpa potongan horizontal; tangkapan penuh semua rincian dibuka.

**Bahan dan silo — 7/7**
- [x] Semua silo/sumber, pemakaian ulang, tambahan, sisa dan status dipertahankan.
- [x] Asal batch/lot, pemasok/pemilik, tiket, waktu/kendaraan memakai bagian lama.
- [x] Bobot sumber tidak ditambahkan ke statistik proses.
- [x] Mix memakai layanan/penjaga pemilik dan saldo lama.
- [x] Pembebasan tidak menutup proses (browser dan suite).
- [x] Sisa0 dan sisa positif mempertahankan status/stok berbeda.
- [x] Isi ulang tidak mengubah sumber lot lama (suite pembebasan).

**Hasil, perhitungan dan penyelesaian — 10/10**
- [x] Ringkasan memakai `_latest_progress`, bukan sum.
- [x] Seluruh log/waktu/pencatat/pagination tersedia.
- [x] Statistik dan rumus rendemen lama digunakan utuh; nilai uji cocok.
- [x] Penanda bahan belum final dan belum diketahui dipertahankan.
- [x] Penambahan/sisa memakai layanan lama dengan regresi stok.
- [x] Koreksi turun tetap diperbolehkan sesuai validasi lama.
- [x] Selesai tetap memeriksa semua sisa/hasil akhir.
- [x] Pratinjau/token/data terbaru dan konfirmasi basi diuji.
- [x] Selesai tidak mengosongkan sisa atau membuat verifikasi admin.
- [x] Verifikasi/koreksi/audit/prioritas hasil terverifikasi diuji suite stok.

**Jeda — 5/5**
- [x] Hentikan/lanjutkan/perubahan kondisi diuji browser.
- [x] Catat hasil saat jeda tidak melanjutkan mesin.
- [x] Perubahan kondisi tidak mengakhiri jeda.
- [x] Kejadian/pencatatan/alasan terlambat tetap melalui mekanisme lama dan suite jeda.
- [x] Durasi efektif/total jeda/penutupan interval diuji suite jeda.

**QC — 6/6**
- [x] Enam komponen dan semua putaran tersedia.
- [x] Rata-rata/skor/kelas/pembulatan/kosong memakai helper dan macro lama.
- [x] Isian wajib/rentang/catatan lab tetap divalidasi.
- [x] Jenis PK memakai `pk_jenis` dari asal bahan.
- [x] Pagination tidak mengubah ringkasan semua putaran.
- [x] Fitur QC/peran/status diperiksa frontend dan backend.

**Hak akses dan navigasi — 7/7**
- [x] Gudang efektif operator dan tindakan diizinkan diuji backend/browser.
- [x] Admin/Super Admin/tampilan peran lain menggunakan mekanisme lama.
- [x] URL/API tanpa izin ditolak backend, termasuk POST QC.
- [x] Dijeda tidak membuka QC/mix; selesai redirect ke riwayat lama.
- [x] Verifikasi/koreksi/QC setelah selesai tetap melalui jalur lama dan regresinya.
- [x] Konteks Pekerjaan/buka/nilai/tautan/refresh/pagination/fragmen dipertahankan.
- [x] Navigasi instan dan klik ganda diuji tanpa transaksi ganda; listener global memakai PINDAH.pasang.

### Tangkapan dan batas verifikasi

Artefak lokal: `output/detail-giling/{desktop,ponsel}-{ringkasan,bahan,hasil,riwayat}-lengkap.png`, tambahan Hasil halaman2; `bukti-tangkapan.json`, `akses-responsif.json`, `alur-awal.json`, `alur-jeda.json`, `alur-qc.json`, `alur-selesai.json`, dan `hasil-database.txt`.

Tangkapan menampilkan data uji aktif sebelum penyelesaian, seluruh details dibuka. CSS khusus pengambilan gambar hanya mengembangkan container gulir agar screenshot mencapai bawah, tidak disimpan ke aplikasi. Riwayat hasil dan QC yang panjang tetap dipaginasi 20 catatan sesuai aplikasi lama; halaman kedua juga disertakan.

Belum diverifikasi: perangkat Android/iOS fisik, Safari/Firefox, pembaca layar, kombinasi seluruh data produksi dan transaksi langsung produksi. Deployment diverifikasi melalui status Railway serta hash commit; tidak menguji transaksi pada lingkungan operasional. Data warisan yang sejak awal tidak memisahkan tambahan per pemakaian tetap bertuliskan “Tidak dipisahkan”; tidak direkonstruksi menjadi angka baru.

