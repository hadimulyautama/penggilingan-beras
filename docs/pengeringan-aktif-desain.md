# Desain pengeringan aktif

Header, panduan bersama, tindakan utama dan tab bergaris mengikuti pola sosoh/giling aktif pada desktop dan ponsel. Pantauan menjadi isi utama Ringkasan. Tidak ada perubahan layanan, API, rumus, izin atau skema database.

Seluruh sumber, pemilik, berat batch, tiket, kendaraan dan QC gabah asal tetap berasal dari macro/reader yang sama. Rata-rata alat tes, masing-masing titik, indikator mesin, waktu masing-masing bacaan, target, kemajuan dan peringatan tetap menggunakan data asli. Tab pengukuran mempertahankan seluruh catatan dan paginasi. Identitas/waktu, jeda dan catatan pendinginan tetap tersedia. Teks penjelasan tindakan asli dipertahankan dalam 'Penjelasan tindakan & keadaan'; perbarui kondisi jeda tetap berada di menu tindakan.

Tombol tetap menaut ke katalog/formulir `aksi.js` asli. Fungsi notifikasi menyediakan slot bila belum hadir ketika bingkai berpindah fase, sehingga hasil simpan tidak memicu galat JavaScript; seluruh handler formulir dan mutasi identik. Target tetap meminta konfirmasi terpisah dan tidak mencatat hasil ukur. Pengukuran tidak melanjutkan mesin atau menyelesaikan pengeringan. Selesai pengeringan tetap mewajibkan bacaan mesin saat dimatikan dan memulai pendinginan. Dinyatakan dingin dan pindah ke silo tetap tindakan terpisah. Template pendinginan serta riwayat selesai tidak diubah.

Judul halaman kini 'Pengeringan aktif', sedangkan kode lot tampil tersendiri pada `data-kode`. Kunci draf memakai kode ini agar tetap terisolasi per lot dan kompatibel dengan kunci lama. Pemulihan draf ketika membuka perubahan target lalu kembali memakai script asli. Navigasi tab tetap GET dengan query, pagination, hash dan konteks Pekerjaan; keyboard tab tetap ditangani script asli.

Panduan memakai macro `_panduan.html` bersama dengan isi khusus pengeringan. `pengeringan-desain.js` hanya membuka panduan, membaca ulang halaman dan mencetak. CSS baru berskop `.dr-redesign` sehingga tidak mengubah halaman pendinginan atau riwayat. Cetak menampilkan seluruh tab.

Validasi memakai PostgreSQL lokal, HTTP aplikasi asli dan browser desktop 1440 px serta ponsel 390/320 px. Bukti screenshot dan hasil pemeriksaan disimpan pada direktori paket perubahan. Tidak ada penulisan data uji ke produksi.
