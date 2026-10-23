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
