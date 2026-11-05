# Desain proses sosoh aktif

Cakupan hanya proses sosoh aktif, desktop dan ponsel. Halaman riwayat selesai tidak diubah. Saat proses selesai melalui alur lama, rincian selesai tetap dirender pembaca lama.

`sosoh-desain.js` menyusun DOM asli menjadi Ringkasan, Bahan & silo, Hasil, QC, dan Riwayat. Editor hasil tetap editor kumulatif asli, termasuk seluruh sembilan jenis, pertambahan, koreksi, pemulihan draf, pembandingan data terbaru, ketidakpastian penyimpanan dan konfirmasi. Catat hasil di kepala membuka tab Hasil dan memfokuskan isian asli. Jeda, waktu aktual, kondisi jeda, mix bahan, pelepasan per siklus dan penyelesaian tetap memanggil handler serta API yang sama. Tab dikunci selama pemeriksaan/tindakan, dan mendukung navigasi keyboard.

QC dan pengemasan otomatis menggunakan node/template asli. Slot QC tidak dibangun ulang ketika editor proses dirender ulang, sehingga isian sampel/lab tetap ada. Identitas, durasi, waktu efektif, jeda, seluruh spesifikasi, catatan hasil, catatan asal pengemasan, koreksi dan pembatalan tetap tersedia. Kalimat lama yang menyebut QC belum tersedia diperbaiki agar menunjuk tab QC yang memang sudah ada.

Kelompok sumber memakai `kelompok_bahan_silo` yang sudah dipakai detail lama: ID dan urutan siklus diperiksa, nama silo berulang tidak digabung. Komposisi dan seluruh catatan asal ditampilkan tanpa menjumlahkan ulang bobot asal ke bahan masuk. Catatan masuk yang dapat dikoreksi tetap berasal dari kontrak koreksi asli: ID catatan/siklus, sumber, kg, jumlah karung, jenis, pemilik proses serta waktu/pencatat jika tersedia. Metadata waktu/pencatat ditambahkan setelah sidik koreksi dibentuk; tidak mengubah perhitungan maupun versi transaksi. Data yang tidak tersedia tetap ditandai. Tautan asal hanya dibuat bila hubungan transfer, tiket penerimaan atau proses asal tercatat.

`KONTRAK.json` pada bukti pekerjaan membuktikan fungsi mutasi/validasi Python tetap identik, mesin kerja JS sama selain publikasi konteks baca dan koreksi kalimat QC, serta template/JS QC, mesin koreksi dan detail riwayat identik dengan basis. Tidak ada migrasi atau mutasi baru.

Validasi: 81 pengujian gabungan mencakup browser QC, sosoh, koreksi bahan, sumber PK, konflik dan draf; 8 pemeriksaan akhir mencakup browser 1440/390/320 px dan penjaga paket. Browser memakai API ASGI dan PostgreSQL uji asli, termasuk penyimpanan hasil; tidak memakai handler simulasi mockup. Pencatatan setelah respons putus, draf hasil ketika QC disimpan, dan rincian sumber kg/karung tetap diuji.
