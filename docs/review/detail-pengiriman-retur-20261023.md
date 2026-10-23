# Inventaris dan pemeriksaan detail Pengiriman & Retur

Inventaris dilakukan sebelum perubahan. Acuan tampilan: bagian USULAN detail-pengiriman-retur desktop dan ponsel 20 Oktober 2026. Acuan transaksi: aplikasi pada main adad43b.

## Pemetaan informasi dan tindakan lama

| Halaman/sumber lama | Lokasi baru | Syarat tetap |
|---|---|---|
| _pengiriman_detail: kode, status, pelanggan/pemilik, polisi, ekspedisi, jasa | Kepala tetap dan Ringkasan | can_see_financials / operator G2; G1 tetap jalur tugas lama |
| Pemeriksaan sebelum verifikasi, alur cepat <200 kg, k.tombol | Ringkasan: Tindakan saat ini | _tombol, boleh_perintah/boleh_muat dan endpoint lama; Admin tidak ditawari muat |
| Total perintah/aktual/sisa | Ringkasan | k.total_* lama, tanpa rumus baru |
| Semua item/nama lengkap/merek/mutu/kemasan/sumber, karung, catatan/sebab | Barang | _nama_barang, sumber asli; ubah/hapus/tambah native dan baseline lama |
| Tiket, sopir, timbang1/2+waktu, netto, tara, selisih/kondisi kosong | Tiket & bobot | data tiket dan ambang_selisih barang keluar lama |
| Jejak diperintah/dimuat/diverifikasi dan retur_terkait | Retur & riwayat | daftar retur hanya bagi BOLEH_PERINTAH |
| retur_asal: status/alasan/hasil pemeriksaan, customer_return_id, wajib_manual | Ringkasan | pengajuan berbeda dari penerimaan, manual_siap dari _koreksi_terbukti |
| Semua baris asal, satuan/kg/karung, sisa, tertunda, kemasan, catatan, formulir | Barang | satu formulir lama; field/name/min/max/step/CSRF/POST tetap; tidak memakai katalog bebas |
| Pilihan tiket RTP, tautan dan data tiket sebenarnya | Barang (pilihan formulir) dan Tiket & bobot (rincian) | pelanggan, aktif dan pembatasan penggunaan lama; tidak menerima stok saat GET |
| Verifikasi manual dan pembatalan beralasan | Ringkasan | hanya Admin, disabled sampai manual_siap, terkunci setelah diterima/batal |
| Seluruh logs sebelum/sesudah, alasan, bukti koreksi Pos Timbang | Riwayat | semua catatan lama, aktor dan waktu dipertahankan |
| retur_detail: identitas penerimaan, pemilik per item, stock reference | Kepala/Ringkasan, Barang, Riwayat | CustomerReturn snapshot asli, data lama tanpa asal tetap jujur |
| Snapshot bobot saat diterima dan tiket sekarang | Tiket & bobot terpisah | tidak menimpa snapshot dengan tiket kini |
| Penerima, waktu, gudang, catatan dan tautan asal/tiket | Riwayat dan Ringkasan | izin lama, tidak hardcode semua Gudang 2/pabrik |

## Layanan dan penjaga yang dipertahankan

barang_keluar: perintah/item/armada, muat per item/semua/selesai, baseline terbaru, verifikasi, batal/balik, cepat dan jasa. Stok berkurang saat dimuat. Admin tombol muat sengaja tidak ditawarkan; jalur darurat backend tetap.

retur_pengajuan.sisa_asal/simpan/batalkan: item asal, pelanggan/tiket, pengajuan aktif lain, jumlah, karung/kemasan, row locks dan audit. retur_pemeriksaan.periksa_bobot: toleransi inklusif total tara sebenarnya; tara kosong tidak nol; selisih besar melekat manual. retur_penerimaan.periksa_dan_terima/_koreksi_terbukti: bukti rincian/timbang, stok tepat sekali, kepemilikan/gudang per item, snapshots dan transaksi utuh. GET tidak memanggil layanan penerimaan.

## Rencana verifikasi

Jalankan suite asli barang keluar/retur, guard repository dan pengujian integrasi tab/form yang bermakna pada PostgreSQL disposable. Potret seluruh tab desktop/ponsel dan keadaan pengajuan, menunggu timbang, perlu koreksi, siap manual, diterima, dibatalkan, data lama. Uji keyboard/tautan/query/instant, satu formulir/draft/tab dan overflow. Hasil nyata serta batas verifikasi ditambahkan setelah pengujian; daftar ini belum merupakan kelulusan.

## Hasil pemeriksaan nyata

- Suite penuh PostgreSQL: **1347 lulus**, 605,19 detik, termasuk seluruh proses lain. Dua skenario tambahan kemudian ditambahkan dan kelima tes detail dijalankan ulang: **5 lulus**. Total unik PostgreSQL1349; non-PostgreSQL **791 lulus**. Total unik2140. CI akan memeriksa seluruh2140 sekaligus pada commit push.
- Suite terarah asli barang keluar/pengajuan/penerimaan retur:180 kasus lulus. Layanan/model/API tidak diubah (perbandingan Git dengan baseline adad43b).
- Stok asli10000kg; perintah100karung×25kg tidak memotongnya; muat menjadi7500kg; verifikasi dan seluruh pembukaan tab tetap7500kg.
- Pengajuan9karung=225kg menunggu timbang, stok0. Tiket250kg menyebabkan perlu_koreksi/manual melekat. Koreksi10karung=250kg dengan alasan nyata menjadi calon_manual; verifikasi asli mencatat1penerimaan/1stok250kg. Pengulangan verifikasi tidak menggandakan stok. Pengiriman asal tetap selesai dan utuh.
- Batas inklusif:10karung×tara0,10=±1kg, tiket251 terhadap rincian250 diterima otomatis; stok250kg tanpa potongan tara. Setelah tiket kini berubah261, snapshot penerimaan tetap251. Master tara hilang menahan penerimaan dan ditampilkan belum tersedia, bukan nol.
- Pengajuan dibatalkan tetap terkunci dan stok0. Suite lama membuktikan lock/race, rollback, pelanggan/tiket, sisa/pengajuan bersamaan, kemasan/kg/karung, kepemilikan jasa, bahan G1/G2, bukti Pos Timbang dan alasan saja tidak meloloskan.
- Browser Chromium:20kombinasi lima lebar320/390/768/1440/1920×empat tab; tanpa overflow/ID ganda/perubahan ukuran tab. Draft dan catatan utuh, keyboard Home, satu POST saat klik ganda,8navigasi instan, tampilan efektif operatorG1/G2 tetap403. Cookie/sesi/CSRF asli pada database lokal.
-120tangkapan desktop/ponsel penuh dari respons HTTP asli selama transisi fixture, seluruh rincian pada tab dibuka. Potret memakai arsip respons agar tiap status dapat dibandingkan; uji interaksi browser terpisah memakai aplikasi langsung. CSS pelebaran frame hanya untuk potret sampai bawah, bukan kode produksi.
- Image Docker dibangun dan menjalankan health200; tujuh template dan dua aset tersedia, checksum sumber/image cocok. Alembic check:No new upgrade operations detected. Tidak ada migrasi, rumus, data operasional, atau transaksi produksi yang diubah untuk pengujian.

## Status checklist penerimaan

| Kelompok | Status dan bukti |
|---|---|
| Tampilan/informasi | Lulus pada Chromium desktop/ponsel: empat tab tiap detail, semua informasi lama dipetakan di atas, status pengajuan/stok terpisah, keadaan kosong/legacy dipertahankan, galeri120gambar tanpa potongan horizontal. |
| Barang keluar | Lulus suite asli180kasus terarah dan suite penuh: perintah/armada/item/muat/verifikasi/batal/balik/cepat/jasa/jejak. Tidak mengubah aturan bobot keluar menjadi aturan retur. |
| Pengajuan retur | Lulus asal wajib/item asli/tiketRTP/pelanggan/sisa/satuan/karung/kemasan/catatan dan menunggu tanpa stok. Form lama danPOST tetap, isian tidak hilang saat berpindah tab. |
| Pemeriksaan bobot | Lulus batas inklusif ±tara, tara tidak sah, otomatis, manual melekat, bukti koreksi rincian/timbang, izin Pos Timbang dan guard manual. Helper lama utuh. |
| Stok/pembatalan | Lulus tepat sekali, stock250utuh, pemilik/gudang sesuai jenis, pengiriman asal utuh, batal tanpa stok, terkunci, snapshot versus tiket kini, transaksi bersamaan dan rollback asli. |
| Riwayat/akses/navigasi | Lulus semua log sebelum/sesudah dan bukti Pos Timbang dipertahankan, tautan asal/pengajuan/penerimaan/tiket, hak Admin/Super Admin/operator/tampilan efektif, jalur G1 asli, URL/API, filter/pagination asli, konteks kembali aman, tab/query/hash/instant dan satuPOST. |

## Berkas perubahan

Tiga controller baca:layar_keluar.py (nama pemilik per item),layar_retur_asal.py (pengaju dan rincian tiket baca),layar_retur.py (identitas pengajuan). Tiga template utama:pengiriman.html,retur_asal.html,retur_detail.html. Empat partial:_detail_kirim_tabs.html,_pengiriman_detail_tab.html,_retur_perbandingan.html,_retur_tiket_fakta.html. Aset khusus:detail_kirim_retur.css/js. Tes:tests/pg/test_detail_pengiriman_retur.py. Dokumen ini. Perubahan sidebar v411 berasal dari main lain dan diintegrasikan tanpa suntingan di pekerjaan ini.

## Belum diverifikasi

Perangkat fisik Android/iOS, Safari/Firefox, pembaca layar dan semua variasi data operasional belum diuji. Tidak menguji transaksi dengan stok produksi. Data historis tanpa hubungan tidak dibuatkan hubungan palsu. Status CI/deploy final dicatat terpisah setelah push. Tidak ada perluasan hak, rumus baru, simulasi timbang/koreksi, atau tombol laporan baru.
