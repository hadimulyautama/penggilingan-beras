# Konsolidasi Stok — calon perubahan lokal, belum diterbitkan

## Inventaris sebelum perubahan (20 Oktober 2026)

Inventaris berdasarkan rute, templat, komponen detail, katalog tindakan dan pengujian yang berlaku. Nama lama pada komentar tidak dijadikan aturan jika berbeda dari kode berjalan.

| Halaman lama | Informasi dan akses yang dipertahankan | Letak baru |
|---|---|---|
| `/stok` | Lot PK G1 dan tumpukan PK G2, kode, tanggal/umur, pemilik, berat tersedia/belum dicatat, kadar air, broken, susut, kelas/kondisi, skor dan jumlah komponen QC; filter gudang untuk admin; tautan detail setiap kode | Bahan & PK → Pabrik |
| `/stok-pk-jasa` | Informasi PK yang sama; pesanan/pemilik, pemisahan G1/G2, detail; bukan salinan stok pabrik | Bahan & PK → Titipan jasa → filter pelanggan |
| `/stok-produk` | Beras dan hasil samping dalam blok terpisah; hasil, keluar, dikemas/tercatat, curah, sisa; tautan kategori; detail asal FIFO, kemasan/merek/ukuran/jumlah, sisa kemas ulang, catatan stok dan alarm selisih | Produk → Pabrik |
| `/stok-produk-jasa` | Informasi produk yang sama, dikelompokkan per pelanggan dengan semua pesanan; rincian kemasan per pesanan; informasi bekatul lama yang sudah berpindah ke pabrik tidak masuk saldo titipan | Produk → Titipan jasa → filter pelanggan |
| `/stok-karung` | Jumlah lembar bersih, jenis, merek, ukuran, Menipis; kelompok laminasi/biasa/polos, per gudang; karung bekas tetap tidak ditampilkan tetapi tersedia untuk packing | Karung → Pabrik |
| `/stok-karung-jasa` | Stok karung per kontak pelanggan, per jenis/merek/ukuran/gudang; Menipis; tidak menawarkan pindah balik yang tidak didukung | Karung → Titipan jasa → filter pelanggan |

## Semua tindakan lama dan jalur barunya

| Tindakan | Jalur baru | Gerbang lama yang tetap berlaku |
|---|---|---|
| Catat/perbaiki hasil giling (`verify_output`) | Bahan & PK → detail lot | Admin, bukan view G2; proses sudah tidak berjalan |
| QC giling dan QC PK luar | Bahan & PK → detail → Catat QC | Hak koreksi, saklar QC dan status pemeriksaan lama |
| Minta lot PK G1 | Bahan & PK → detail lot (kedua kepemilikan) | Operator G2; lot tidak sedang digiling |
| Masukkan tumpukan PK ke silo | Bahan & PK → detail tumpukan (kedua kepemilikan) | Operator G2 / Super Admin; server memeriksa stok, silo, pemilik |
| Masukkan produk/curah ke silo | Produk → detail kategori → Aksi | Gerbang masing-masing sumber dan peran lama |
| Kemas curah / kemas ulang kemasan | Produk → detail kategori → Aksi | Sumber, stok, merek, kemasan dan kepemilikan lama |
| Catat bekatul curah | Produk → detail bekatul → Aksi curah | Hak pencatatan dan saldo belum tercatat |
| Pindah kepemilikan produk | Produk → Titipan jasa → detail → Aksi | Admin ke atas, stok tercatat, pesanan/sumber tetap dibawa |
| Pindah kepemilikan karung | Karung → Pabrik → menu baris | Admin ke atas; tujuan kontak pelanggan, FIFO dan batas stok lama |
| Pembelian/kehilangan karung dari katalog aksi | Tautan `?buka=...&nilai=...` lama tetap hidup | Katalog dan endpoint lama, tidak ditambah hak baru |
| Batal/Lanjut isi, validasi, pemulihan gagal simpan, konflik, audit | Dialog/halaman aksi lama dipakai kembali | Tidak menyalin atau mengganti implementasi transaksi |

Detail dan URL aksi lama dipertahankan. Daftar baru menambahkan navigasi jenis, pemilik dan pelanggan, bukan menggantikan endpoint transaksi.

## Cakupan dan pencegahan penghitungan ganda

- PK G1 memakai saldo lot setelah transfer/keluar; PK G2 memakai saldo intake **tumpukan**, setelah pindah silo. Transfer tidak ditambahkan lagi sebagai stok tersendiri.
- PK yang sudah di silo adalah bahan proses, bukan saldo tersedia untuk pengeluaran langsung. Konsolidasi tidak memasukkannya kembali ke daftar stok tumpukan.
- `barang_jadi_g2` adalah rincian kemasan, bukan saldo tambahan di atas `stok_produk`; tidak dibuat total gabungan dari keduanya.
- Produk beras dan hasil samping tetap memiliki subtotal masing-masing. Curah dan dikemas adalah bagian dari sisa, bukan tambahan atas sisa.
- Produk titipan dikelompokkan per pelanggan untuk tampilan; saldo, reservasi, sumber aksi tetap per pesanan. Pelanggan bernama sama tidak disatukan berdasarkan nama.
- Karung titipan menggunakan `pelanggan_id` langsung. Stok pabrik tidak memasukkan karung pelanggan. Karung bekas tidak menambah total lembar yang dipantau.
- Info bekatul historis “sudah menjadi milik pabrik” tidak ditambahkan ke total titipan.

## Hak akses

Admin/Super Admin dapat membaca kedua gudang. Operator G1 tetap tidak dapat membuka Produk/Karung. Operator G2 tetap dapat membaca PK G1 sebagai bahan yang dapat diminta, tanpa memperoleh hak mengubah Gudang 1. Filter gudang bukan pemeriksaan izin; endpoint halaman/detail/tindakan mempertahankan pemeriksaan server. Pengecualian lama dipertahankan: halaman Karung Jasa dapat dibaca operator G2 termasuk karung PK G1, sementara Karung Pabrik membatasi operator G2 ke baris G2. Tidak ditambahkan kemampuan memindahkan karung dari halaman jasa.

## Rencana verifikasi

1. Bandingkan konteks saldo/isi pada enam rute lama dan tujuan baru dengan fixture PostgreSQL yang sama.
2. Periksa semua tautan detail/aksi, parameter pembuka, keadaan kosong, filter pelanggan/gudang, reload/back dan izin admin/G1/G2.
3. Jalankan uji transaksi stok: packing/rebag/silo, pindah kepemilikan produk/karung, QC/koreksi, permintaan/transfer, saldo/audit/pembatalan, batas stok dan pemisahan pesanan.
4. Periksa browser lokal pada ponsel/desktop, terang/gelap; simpan gambar hasil. Tidak ada permintaan mutasi ke aplikasi produksi.

## Hasil verifikasi lokal

20 Oktober 2026. Paket tampilan **389**, disinkronkan lewat prosedur paket; salinan vendored tidak diedit langsung. Tidak ada perubahan skema, layanan transaksi, atau data operasional. Belum dipush atau dideploy.

- **1.805 uji Produksi lulus** pada PostgreSQL lokal terisolasi (`uji_rilis388`, port 55442). Tidak ada pengecualian/skip dalam hasil akhir. Durasi 435 detik.
- **387 uji paket tampilan lulus**. Setelah perapian jarak dan tautan terakhir, **32 pemeriksaan paket** serta **21 uji integrasi tautan/detail/karung/konsolidasi** lulus kembali.
- **24 kombinasi browser**: tiga jenis × dua kepemilikan × ponsel 390×844 / desktop 1440×900 × terang/gelap. Navigasi, pilihan aktif, filter pelanggan, penanda kepemilikan dan total terbaca; halaman tidak melebar ke samping. Tombol pilihan pemilik dan filter minimal 56 px.
- Browser tambahan: operator G1/G2, alamat lama Produk Jasa dan Karung, filter pelanggan bernama panjang, keadaan kosong Gudang 1 untuk Produk, muat ulang, Kembali, tautan detail dan pembukaan/Batal formulir Kemas serta Pindah kepemilikan karung. Filter kembali tetap dibawa, termasuk setelah membuka aksi dari detail.
- Uji pembacaan keenam alamat lama dan baru merekam perintah database: **tidak ada INSERT, UPDATE, atau DELETE**.
- Pemeriksaan format perubahan bersih; perubahan paket sumber dan hasil sinkron selaras.

### Perbandingan saldo pada data uji yang sama

| Stok | Pabrik | Titipan pelanggan 1 | Titipan pelanggan 2 |
|---|---:|---:|---:|
| PK tersedia | 6.500 kg | 3.500 kg | 1.250 kg |
| Produk beras | 9.000 kg | 5.000 kg | 2.300 kg |
| Karung setelah transfer kepemilikan | 650 lembar | 100 lembar | 50 lembar |

Saldo tersebut cocok pada alamat lama dan tab baru. Dua pelanggan sengaja memakai nama sama dalam uji otomatis: filter tetap memisahkan ID mereka. Dalam pratinjau browser, tambahan transaksi contoh packing 8 × 25 kg untuk pabrik dan pelanggan 1 mengubah karung menjadi 642 / 92 / 50 lembar; berat produk tetap 9.000 / 5.000 / 2.300 kg, hanya komposisi curah dan kemasan berubah. Ini data buatan pada database pratinjau terpisah, bukan salinan atau perubahan data operasional.

### Verifikasi setiap kelompok fungsi

| Fungsi inventaris | Bukti verifikasi |
|---|---|
| PK, QC, mutu kosong, per gudang dan pemilik | `test_konsolidasi_stok`, `test_stok_pk_qc`, `test_stok_g2_per_kode`, `test_stok_pk_g1_polesan`; browser daftar kedua pemilik |
| Koreksi hasil giling / QC dan audit | Pengujian koreksi, QC, peristiwa dan pembatalan dalam suite lengkap; parameter pembuka/izin pada detail diperiksa integrasi. Tidak disimpan manual lewat browser |
| Minta lot, transfer, tumpukan ke silo | `test_permintaan_pk`, `test_permintaan_empat_langkah`, `test_peristiwa_transfer`, `test_peristiwa_pindah_tumpukan`; saldo dan hak lama dipertahankan |
| Produk, hasil samping, FIFO, curah/kemasan, detail | `test_stok_produk`, `test_stok_produk_jasa`, `test_stok_produk_detail`; browser detail Produk Jasa dan kembali ke filter pelanggan |
| Produk ke silo | `test_produk_kemasan_silo`, `test_masukkan_beras_silo`, `test_masukkan_broken_silo`; tidak ada perubahan layanan sumber |
| Packing dan rebag | `test_grup_packing_jasa`, `test_packing_karung_bekas`, `test_kemas_ulang`; stok, pemilik, sisa, kiriman ulang dan perebutan saldo. Browser membuka Kemas lalu Batal |
| Bekatul dan pindah kepemilikan produk | `test_pindah_kepemilikan_produk` beserta uji produk/bekatul suite lengkap; curah dan kemasan benar-benar berpindah pada data uji |
| Pembelian, pemakaian, kehilangan karung, Menipis | `test_stok_karung`, `test_stok_karung_jasa`; saldo per komponen dan pemilik, browser tabel/kartu Menipis |
| Pindah kepemilikan karung | `test_stok_karung_http`, `test_stok_karung_jasa`; FIFO, penolakan melebihi saldo, izin server. Browser menu baris, formulir terisi sumber dan Batal; URL menjaga gudang |
| Validasi, konfirmasi, gagal simpan, identitas dan audit | Suite paket dan Produksi yang memakai implementasi aksi lama; konsolidasi tidak menggantikan skrip/endpoint transaksi |
| Enam alias, navigasi kosong, filter, akses | 17 kasus konsolidasi ditambah suite lama; browser admin/G1/G2, tautan detail, reload/Back |

### Batas verifikasi dan hal yang perlu ditinjau

- Browser memakai ukuran ponsel simulasi, belum perangkat fisik Android/iPhone.
- Semua penyimpanan/transaksi diuji otomatis pada database lokal. Tidak setiap formulir dalam inventaris disimpan ulang secara manual melalui browser; yang dibuka manual pada pemeriksaan tambahan ini adalah Kemas dan Pindah kepemilikan karung, lalu dibatalkan.
- Tidak ada perbandingan saldo dengan database produksi. Perbandingan menggunakan data uji identik dan layanan perhitungan yang sama.
- Operator G1 belum diberi akses Produk/Karung karena konsolidasi mempertahankan izin lama. Jika akses baca lintas gudang diinginkan, itu keputusan izin terpisah dari konsolidasi ini.
- Pengecualian cakupan baca Karung Jasa G1 oleh operator G2 adalah perilaku lama yang sengaja dipertahankan dan diuji, bukan izin baru.
- Bahan & PK memuat cakupan enam halaman yang diminta; konsolidasi ini tidak menambahkan stok gabah dari halaman lain.
- Pratinjau lokal menolak permintaan penyimpanan browser. Gambar berada di `output/stok389/`; daftar hasil 24 kombinasi di `output/stok389/browser.json`.

## Contoh tampilan

### Ponsel

![Produk titipan jasa — terang](../../output/stok389/produk-jasa-ponsel-terang.png)
![Produk titipan jasa — gelap](../../output/stok389/produk-jasa-ponsel-gelap.png)

### Desktop

![Karung pabrik — terang](../../output/stok389/karung-pabrik-desktop-terang.png)
![Bahan & PK titipan jasa — gelap](../../output/stok389/bahan-jasa-desktop-gelap.png)
