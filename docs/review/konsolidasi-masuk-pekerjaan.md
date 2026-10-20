# Review lokal — Barang Masuk dan Pekerjaan

Status: implementasi lokal untuk ditinjau. **Belum dipush atau dideploy.** Data operasional tidak disentuh, tidak ada perubahan skema, dan pekerjaan lokal Stok v390 tetap dipertahankan. Paket bersama dinaikkan ke v391 dan disinkronkan melalui prosedur repo.

## Susunan baru

- **Barang Masuk**: Belum diterima / Diterima, filter lima jenis barang (ditambah jenis belum dikenal untuk informasi lama), pemilik dan gudang. Tindakan penerimaan tetap tombol/formulir lama.
- **Pekerjaan**: Perlu tindakan / Berjalan, filter jenis pekerjaan, pemilik, gudang, nama dan pencarian. QC serta keputusan masuk Perlu tindakan dengan gerbang izin lama.
- Proses aktif tetap menyediakan status, penanda jasa/pemilik, progres, detail serta semua tindakan lanjutannya. Mesin yang sekadar menunggu waktu tidak ditagih sebagai pekerjaan tertunda.
- Penerimaan tidak diduplikasi dalam Pekerjaan. **Gabah yang sudah diterima tetapi menunggu penempatan dan PK yang akan dimasukkan silo tetap Pekerjaan**, meskipun dahulu berada dalam grup “bahan”.
- Lencana menghitung pekerjaan yang dapat ditindak pengguna. Operator G2 tetap dapat melihat tiket PK sebagai informasi tanpa lencana yang menyuruhnya melakukan penerimaan khusus Admin. Angka tab Belum diterima mencakup kartu informasi yang dapat dilihatnya.
- Stok tetap satu menu tanpa lencana. Layanan dan perhitungan saldo Stok tidak diubah oleh konsolidasi ini.

## Batas perubahan dan inventaris

Inventaris dibuat sebelum perubahan di `output/konsolidasi-kerja391/inventaris-kartu.json`: **28 konstruktor kartu**, beserta seluruh ekspresi atributnya (bobot, fakta, pilihan, tombol, payload, sumber tiket, status, pemilik, mutu, catatan dan progres). Salinan sumber awal ada di subfolder `sebelum/`.

Katalog formulir lama dan seluruh isi kartu dibandingkan terhadap snapshot lokal sebelum perubahan (termasuk pekerjaan Stok v390, dengan HEAD `e6f5a62080261425b3287dade51b547678bc005e`) pada **DB yang sama**, untuk Super Admin, Admin, Operator G1 dan Operator G2. Hasil identik: `paritas-*.json`. Pembanding ini meliputi kolom, nilai bawaan, pilihan dinamis, sumber pilihan, payload, serta pembatasan formulir. Pembangun kartu dan formulir tidak diganti. Endpoint penerimaan tetap sama; satu urutan pemeriksaan silo diperbaiki setelah kegagalan parsial berhasil direproduksi (lihat temuan di bawah).

## Pemetaan kartu satu per satu

| Sumber lama | Kode / aksi lama | Tujuan baru |
|---|---|---|
| _tiket_belum_ditaut:1476 | 'gabah_masuk' | Barang Masuk · Belum diterima |
| _tiket_pk_luar:1597 | 'catat_pk_luar' if boleh_catat else None | Barang Masuk · Belum diterima |
| _tiket_jenis_tak_dikenal:1692 | nama | Barang Masuk · Belum diterima |
| untuk_gudang1:1782 | 'mulai_pengeringan' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| untuk_gudang1:1834 | 'pindah_tumpukan' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| untuk_gudang1:1890 | 'pindah_tumpukan' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| untuk_gudang1:1922 | 'pindah_silo' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| untuk_gudang1:1943 | 'selesai_pendinginan' | Pekerjaan · Berjalan |
| untuk_gudang1:2023 | 'lanjutkan_proses' if macet else 'kadar_air' | Pekerjaan · Berjalan |
| untuk_gudang1:2128 | 'mulai_giling' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| untuk_gudang1:2221 | 'lanjutkan_proses' if macet else 'hasil_giling' | Pekerjaan · Berjalan |
| untuk_gudang1:2322 | 'kirim_permintaan_pk' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| untuk_gudang2:2432 | 'masukkan_pk' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| untuk_gudang2:2498 | 'qc_pk_luar' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| _kartu_penyosohan_g2:2711 | 'lanjutkan_penyosohan' if macet else 'hasil_penyosohan' | Pekerjaan · Berjalan |
| _kartu_silo_g2:2856 | None if sedang else 'mulai_penyosohan' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| _kartu_tumpukan_g2:2946 | 'pindah_tumpukan_silo' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| _kartu_beras_curah:2998 | 'catat_packing' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| _kartu_barang_keluar:3062 | 'muat_semua' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| untuk_operator_gudang2:3181 | 'Permintaan PK Anda' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| untuk_operator_gudang2:3223 | 'Permintaan Anda ditolak' if ditolak else 'Permintaan Anda gugur' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| untuk_staff:3403 | 'betulkan_bobot_giling' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| untuk_staff:3487 | 'acc_permintaan_pk' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| untuk_staff:3369 | 'qc_giling' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| untuk_staff:3456 | 'tutup_permintaan_pk' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| untuk_staff:3306 | 'qc_gabah_basah' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| untuk_staff:3320 | 'qc_gabah_kering' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |
| _kartu_tiket_keluar_menganggur:3558 | 'Tiket timbang keluar terlewat' | Pekerjaan · Perlu tindakan (atau informasi di Berjalan bila tidak dapat ditindak) |

## Fungsi lintas kartu yang tetap terjangkau

| Fungsi lama | Lokasi / perlakuan sekarang |
|---|---|
| Gabah basah/kering dari tiket | Barang Masuk; tujuan dryer/silo/tumpukan persis yang ditawarkan aturan lama. Gabah basah jasa tetap harus ke dryer. |
| Catat / tolak PK luar | Barang Masuk untuk Admin ke atas; operator G2 tetap informasi. Jenis PK, QC terpisah dan validasi lama dipertahankan. |
| Beras dan broken dari Timbangan | Barang Masuk; penerimaan khusus stok melalui endpoint lama, tetap khusus Admin. |
| Timbang pertama/kedua, susulan, perkiraan/final dan perubahan bobot | Sumber tiket serta layanan bobot lama; tidak ditambah syarat timbang akhir. |
| Penempatan gabah/PK, memulai proses, pendinginan, pindah silo, transfer, packing, muat | Pekerjaan sesuai kondisi kartu asli; tombol dan parameter tindakan sama. |
| Pencatatan hasil, mutu, jeda/lanjut, tambah/bebaskan silo, penyelesaian proses | Detail proses dari Berjalan, memakai tindakan lama. Status dan pengaman silo tidak diubah. |
| QC dan putaran berikutnya | Perlu tindakan · QC; QC pada proses aktif tetap dapat dibuka dari detail. Pengaturan mutu aktif/nonaktif tetap diperiksa. |
| Permintaan lot, persetujuan, penolakan, penutupan transfer, koreksi bobot | Perlu tindakan · Transfer PK / Keputusan sesuai kartu dan izin lama. |
| Packing, bekatul dan pembatalan tanpa kartu | Pintasan operator di bagian bawah Pekerjaan tetap memakai `_pintasan_aksi`; katalog Catat pekerjaan lain tetap untuk Admin. |
| Finansial, audit, notifikasi, idempotensi dan pembatalan | Penjagaan serta pencatatan di layanan/endpoint lama; filter halaman bukan pengganti izin. Tidak ada harga/kolom finansial baru di daftar penerimaan. |
| Riwayat Diterima | Dibaca dari catatan sumber penerimaan yang sudah ada, bukan membuat status atau stok baru. Satu tiket satu entri daftar; seluruh baris sumber tetap di detail. |
| Detail penerimaan | Kode tiket, pihak pada tiket, bobot/sumber bobot, waktu, plat/sopir, pemilik catatan, pencatat, lokasi dan tautan stok/proses yang mempunyai relasi nyata. |

## Kompatibilitas alamat dan konteks

| Alamat lama | Tujuan kompatibel |
|---|---|
| `/aksi` | Pekerjaan · Perlu tindakan. |
| `/aksi?buka=gabah_masuk|catat_pk_luar|catat_beras_timbang_masuk|catat_broken_timbang_masuk&nilai=…` | Barang Masuk dengan formulir dan tiket yang sama. |
| `/aksi?grup=bahan` tanpa `buka` | Barang Masuk; tautan Penempatan bahan tersedia ke Pekerjaan. Grup campuran ini tidak dipindahkan utuh. |
| `/aksi?grup=…` lainnya | Pekerjaan, grup lama tetap disaring; informasi silo yang menunggu mesin masuk Berjalan. `packing_jasa` tetap alias packing. |
| `/berjalan` | Pekerjaan · Berjalan. |
| `/mutu`, `/keputusan`, termasuk kategori dan pembuka formulir | Perlu tindakan dengan saringan lama; alamat tetap khusus Admin seperti sebelumnya. |
| Detail proses, stok, riwayat dan notifikasi | Alamat tetap ada. Tautan dari daftar membawa konteks aman dalam `kembali_kerja`. |

Jenis, tab, pemilik, gudang, pencarian dan nama tersimpan di URL. Pembukaan formulir membuang hanya parameter pembuka formulir ketika selesai; filter tetap dibawa. Tautan Kembali di kepala maupun isi detail proses sekarang sejalan. Pengalihan fase menuju riwayat juga membawa konteks. URL kembali dibatasi ke halaman lokal Barang Masuk/Pekerjaan.

## Hasil verifikasi

Lingkungan transaksi: PostgreSQL lokal loopback, `uji_rilis388` untuk suite dan `uji_kerja391_preview` untuk browser. Preview mematikan tugas latar; tidak mengakses aplikasi atau DB produksi. Akun uji: Uji superadmin, Uji admin, Uji operator G1/G2, serta mode lihat sebagai operator pada akun Super Admin.

**Produksi: 1.867 lulus (1.131 PostgreSQL + 736 pendukung), 0 gagal/galat/dilewati. Audit khusus penerimaan dan pembanding lokal: 45 lulus, 0 dilewati. Paket tampilan: 391 lulus, 0 gagal/galat/dilewati. Empat uji pencarian pada dua ukuran dan dua tema ikut lulus pada perubahan terakhir.**

| Pemeriksaan wajib | Hasil | Contoh dan bukti |
|---|---|---|
| Lima jenis penerimaan pabrik dan titipan | Lulus | 10 kombinasi; `TRX-391-*`, 9.800 kg per tiket, tepat satu catatan sumber dan pemilik benar. `terima-*.json`. |
| Langkah, formulir, nilai bawaan dan pilihan sebelum–sesudah | Lulus | Seluruh kartu/katalog identik pada DB sama untuk empat peran. `paritas-*.json`. |
| Tiket belum final | Lulus | Lima jenis diuji. Gabah/PK mengikuti penerimaan bobot belum diketahui yang dahulu didukung; beras/broken tetap menolak jika belum memiliki bobot yang dapat dipakai. Tidak menambah syarat final. |
| Sudah diterima, ditolak, dan pencegahan duplikat | Lulus | Tiket terpakai hilang dari pilihan. PK ditolak/DITUTUP_PAKSA tetap terbaca dalam detail tanpa dapat diterima ulang. Kirim ulang HTTP dan klik Simpan ganda browser menghasilkan satu catatan. |
| Saldo, kepemilikan, lokasi dan tiket | Lulus | 10 kombinasi DB; 5 penerimaan melalui browser masing-masing tepat 9.800 kg, relasi tiket utuh. `browser-saldo-audit.json`. |
| Kartu, tindakan dan status pekerjaan | Lulus | Partisi satu-ke-satu, tidak ada kartu dibuang atau penerimaan diduplikasi. Regresi proses/transfer/packing/muat dan pengaman silo dijalankan dalam suite Produksi. |
| QC, keputusan, mutu nonaktif, audit, notifikasi dan undo yang didukung | Lulus | Regresi layanan lama tetap lulus; QC nonaktif ditolak juga melalui endpoint langsung. Riwayat dan audit tidak diganti. Pembatalan penempatan gabah diuji lewat browser. |
| Empat peran dan lihat sebagai | Lulus | Enam konteks akses HTTP, pemeriksaan endpoint langsung dan detail lintas gudang; empat akun dibuka melalui browser. `browser-peran.json`. |
| Tautan lama, filter, detail, simpan, batal, muat ulang dan kembali | Lulus | Alias diuji HTTP; pencarian/filter diuji browser, hasil giling 6.000 kg tersimpan dan kembali ke daftar G1/Pabrik/Giling dengan rendemen 61,2%. |
| Batal / Lanjut isi tidak menyimpan | Lulus | 12 kasus formulir PK/beras/broken pada empat kombinasi layar/tema; seluruh 99 tabel (141 baris) identik sebelum–sesudah. `form-browser.json`, `browser-batal-*.json`. |
| Ponsel / desktop, terang / gelap | Lulus | Matriks 16 tampilan daftar, 12 formulir, 8 pembukaan pilihan gabah. Tidak ada luapan horizontal. `browser.json`, `gabah-browser.json`. |
| Progres, penanda jasa, stok dan tampilan kosong | Lulus | Progres memakai komponen lama; semua tab/filter tetap tersedia saat kosong. Regresi Stok ikut dijalankan, menu tetap tanpa lencana. |

## Perbaikan yang muncul selama verifikasi

0. **Kegagalan parsial lama:** silo tidak sah menghasilkan HTTP 400 tetapi penerimaan gabah telanjur tercatat. Pemeriksaan silo yang sama dipindahkan sebelum pencatatan, dengan pesan penolakan yang sama. Bukti: `TRX-391-UJI-TUJUAN2` dahulu 4 → 5 batch walau gagal; `TRX-391-UJI-TUJUAN3` sesudah perbaikan 5 → 5 batch, tanpa sumber penerimaan baru. Kasus tidak memilih silo dan ID silo tidak sah juga diuji otomatis. Tidak menambah isian atau kewajiban pada alur sah.

1. Riwayat PK yang tiketnya ditutup paksa perlu pembaca metadata khusus agar detail tetap terbuka, tanpa menawarkan penerimaan ulang.
2. Pencarian perlu meneruskan nilai yang baru diketik ke tab, tautan detail, pembuka formulir dan filter. Pencarian juga harus menghormati `hidden` meskipun kartu memakai gaya responsif; hitungan hanya menghitung representasi layar yang tampil. Mengosongkan pencarian mengembalikan seluruh hasil.
3. Baris proses aktif kini menyertakan kunci nama yang dipakai penyaring serta nama pemilik untuk pencarian.
4. Tautan tindakan dan Kembali pada detail proses semula membuang konteks daftar; sekarang menggunakan pola tautan formulir bersama yang mempertahankan parameter.
5. Identitas pemilik detail mengikuti catatan penerimaan, bukan bendera tiket yang dapat dikoreksi kemudian. Pihak pada tiket tetap ditampilkan terpisah.

## Catatan batas verifikasi

- Browser memakai viewport 390×844 dan 1440×900; **belum diuji pada perangkat fisik** atau jaringan gudang sesungguhnya.
- **Belum diuji beban/volume riwayat produksi**. Daftar Diterima menampilkan 25 tiket per halaman; pembaca saat ini mengumpulkan sumber penerimaan sebelum pembagian halaman. Pencarian cepat menyebut “pada halaman ini” dan tidak menjanjikan pencarian lintas halaman.
- Tidak melakukan pencocokan atau perubahan data operasional. Seluruh bukti saldo sebelum–sesudah berasal dari data uji yang disebutkan.
- Relasi asal ke proses hanya ditampilkan bila tersimpan secara nyata. Untuk PK/produk G2 yang tidak memiliki alokasi per tiket ke proses hilir, detail menghubungkan catatan penerimaan, perpindahan yang tercatat dan stok pemilik terkait; tidak menebak proses dari nama silo yang dapat dipakai ulang.
- **Perilaku lama yang sengaja dipertahankan:** BATALKAN pada penerimaan gabah membatalkan langkah penempatan terakhir, bukan menghapus batch masuk. Uji browser membuktikan batch kembali `baru` dan muncul sebagai pekerjaan penempatan, tanpa penerimaan kedua. Mengubah makna pembatalan ini berada di luar konsolidasi.
- Riwayat panjang diuji dengan 28 penerimaan tambahan; dalam DB browser yang juga memuat skenario lain terdapat 31 penerimaan gabah kering, terbagi 25 + 6. Tidak ada luapan pada empat kombinasi layar/tema.
- Tidak ada fungsi lama yang diketahui gagal pada pengujian tercatat. Tidak menganggap pemeriksaan perangkat fisik/volume riil yang belum dilakukan sebagai Lulus.

Checklist rinci **55 butir**, setiap butir dengan status, akun, identitas dan bukti sebelum–sesudah: [Checklist penerimaan](checklist-barang-masuk-pekerjaan.md).

## Galeri data uji

Tampilan awal mempunyai lima tiket belum diterima. Setelah uji simpan, tiket yang sama berpindah ke Diterima; perbedaan angka pada potret akhir adalah transaksi **DB uji** yang tercatat dalam bukti, bukan perubahan operasional.

| Halaman | Ponsel terang | Ponsel gelap | Desktop terang | Desktop gelap |
|---|---|---|---|---|
| Barang Masuk | [Lihat](../../output/konsolidasi-kerja391/masuk-ponsel-terang.png) | [Lihat](../../output/konsolidasi-kerja391/masuk-ponsel-gelap.png) | [Lihat](../../output/konsolidasi-kerja391/masuk-desktop-terang.png) | [Lihat](../../output/konsolidasi-kerja391/masuk-desktop-gelap.png) |
| Diterima | [Lihat](../../output/konsolidasi-kerja391/diterima-ponsel-terang.png) | [Lihat](../../output/konsolidasi-kerja391/diterima-ponsel-gelap.png) | [Lihat](../../output/konsolidasi-kerja391/diterima-desktop-terang.png) | [Lihat](../../output/konsolidasi-kerja391/diterima-desktop-gelap.png) |
| Perlu tindakan | [Lihat](../../output/konsolidasi-kerja391/tindakan-ponsel-terang.png) | [Lihat](../../output/konsolidasi-kerja391/tindakan-ponsel-gelap.png) | [Lihat](../../output/konsolidasi-kerja391/tindakan-desktop-terang.png) | [Lihat](../../output/konsolidasi-kerja391/tindakan-desktop-gelap.png) |
| Berjalan akhir | [Lihat](../../output/konsolidasi-kerja391/hasil-berjalan-ponsel-terang.png) | [Lihat](../../output/konsolidasi-kerja391/hasil-berjalan-ponsel-gelap.png) | [Lihat](../../output/konsolidasi-kerja391/hasil-berjalan-desktop-terang.png) | [Lihat](../../output/konsolidasi-kerja391/hasil-berjalan-desktop-gelap.png) |
