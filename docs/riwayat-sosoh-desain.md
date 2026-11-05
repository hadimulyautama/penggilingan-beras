# Desain detail riwayat sosoh

Detail `/riwayat-sosoh/{id}` memakai header dan tab yang mengikuti pola proses aktif: Ringkasan, Bahan & silo, Hasil, QC, Riwayat. PDF tetap di area tindakan utama; panduan memakai macro bersama. Navigasi induk Laporan & Riwayat dipindah utuh ke dialog melalui menu; seluruh tautan, izin dan handler lama tetap tersedia, tanpa header kedua pada detail. Hanya pemilihan template pada rute detail sosoh yang berubah. Reader, izin, POST koreksi, layanan, skema database dan perhitungan tidak berubah. Detail giling, transfer dan template riwayat lama tetap identik.

## Informasi dan fungsi

Blok Informasi proses, Neraca hasil, Bahan & pemakaian silo, serta seluruh koreksi/hilir disalin utuh dari template asli. Semua field, peringatan bobot belum final, neraca saat penutupan, hasil melebihi bahan, tautan sumber dan alasan penghalang tetap ada. Ringkasan menampilkan nilai dari `k.neraca`/`k.rendemen` asli tanpa rumus pengganti. Tab Hasil menambahkan tampilan seluruh sembilan jenis berdasarkan `k.beras` dan `k.neraca.samping`; operator tidak memakai `hasil_awal` khusus formulir Admin sebagai sumber bacaan.

Catatan asal pengemasan otomatis tetap menuju empat halaman asli (broken, bekatul, menir, reject). Perhitungan karung, curah, pemakaian terkait, koreksi dan pembatalan asal tetap milik layanan yang sama. PDF dan lembar laporan memakai tautan lama.

QC memakai `_qc_sosoh.html` dan `qc-sosoh.js` identik, termasuk kelima komponen, format desimal, waktu/jenis sampel, hasil lab, pembatalan dan pemetaan sesi. Sampel baru pada proses selesai mengikuti aturan asli. Jeda memakai macro asli, termasuk waktu aktual, waktu pencatatan, alasan dan pembatalan.

## Draf dan penyimpanan

Tab berpindah lokal dengan node formulir yang sama. Tautan GET tetap tersedia bila JavaScript mati, dan hash lama `#qc-sosoh`/jeda membuka panel yang memuatnya. Sesudah POST berhasil atau ditolak, tab Hasil dibuka agar status dan isian terlihat.

Penyimpanan QC menyegarkan bingkai melalui PINDAH. Node draf koreksi dipertahankan di memori halaman dengan kunci akun, view, proses dan token CSRF. Seluruh `dasar_*` lama ikut dipertahankan; pembanding tidak diganti diam-diam dengan data terbaru. Node yang sama ditempatkan kembali setelah refresh dan detail koreksi dibuka. Draf tidak dibagikan lintas akun/peran/sesi.

Pratinjau koreksi hanya menghentikan propagasi submit awal dan menampilkan seluruh nilai. Konfirmasi meneruskan submit ke `koreksi.js` asli. Tidak ada POST sebelum konfirmasi. Saat server menolak dengan 422 dan mengganti main, kontrol/QC diaktifkan kembali, nilai dan alasan dari jawaban server tetap dipakai, serta pemeriksaan ulang wajib mengikuti formulir asli. Kesalahan/stale tidak ditutupi dengan data contoh.

## Validasi

Pengujian browser memakai server HTTP ASGI asli dan PostgreSQL uji lokal agar redirect POST, cookie dan formulir diuji seperti browser nyata. Desktop 1440 px dan ponsel 390/320 px mencakup tab, node/draf, QC, koreksi, tautan asal, laporan/PDF dan panduan. Uji lain mencakup pembaca operator serta penolakan/perbaikan data yang berubah bersamaan. Uji QC lama tetap mencakup pemulihan balasan putus. Bukti dan hasil disimpan di direktori paket perubahan, tanpa data uji di produksi.
