# Penyajian penggilingan aktif

Header, tindakan proses, panduan dan tab mengikuti pola proses sosoh aktif. Hanya proses aktif memakai penyajian ini. Riwayat selesai tetap memakai penyajian asal.

- Ringkasan: metrik sumber asli, formulir PK kumulatif dan dasar/saldo stok.
- Bahan & silo: seluruh sumber dan siklus, sisa fisik, tambah silo/mix, asal gabah dan QC bahan, serta koreksi/pembatalan asli.
- Hasil PK: formulir PK yang sama dan rincian perhitungan stok asli.
- QC: keenam komponen, aturan penilaian, seluruh putaran, catatan lab dan formulir asli.
- Riwayat: identitas/waktu, log PK kumulatif, jeda dan jejak koreksi termasuk catatan dibatalkan.

`giling-desain.js` memindahkan node DOM asli pada `pf:detail-render`. Ringkasan dan Hasil PK memakai satu formulir yang dipindahkan ketika tab dipilih, sehingga input, handler dan draf tidak bercabang. Saldo ringkasan menampilkan hasil pembaca stok yang sama; verifikasi Admin tidak diganti dengan catatan operator. Tidak ada rumus produksi, persediaan atau QC baru.

`giling-ringkas.js` hanya mengekspos data dan keadaan UI untuk adaptor. Pemeriksaan, penyimpanan, cap data, pemulihan respons terputus, CSRF, peran dan semua layanan tetap sama. Formulir/pemeriksaan yang sedang terbuka selalu terlihat; tab terkunci selama tindakan aktif. Penyelesaian tetap menampilkan langkah asli secara utuh. Tautan lama ke sumber/hasil mengaktifkan tab tujuan. Draf hasil tetap dijaga saat berpindah tab dan ketika kembali dari penyelesaian.

Gaya header/tab memakai `sosoh-desain.css` yang sama, tanpa mengubah berkas tersebut; penyesuaian giling ada pada `giling-desain.css`. Panduan menggunakan makro `_panduan.html` bersama dengan isi khusus penggilingan.

Validasi: pengujian browser dengan API asli pada PostgreSQL lokal untuk desktop 1440 px, ponsel 390/320 px, perpindahan node dan draf, QC, pencatatan PK tanpa menimpa verifikasi/stok, koreksi sumber, penyelesaian, tautan lama dan jeda; suite API penggilingan yang sudah ada. Tidak ada pengiriman data uji ke produksi.
