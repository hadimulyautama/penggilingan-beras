# Kontrol Laporan dan Riwayat

Perubahan dibatasi pada area kontrol: kepala halaman, Panduan/Print, empat tab, pilihan jenis, serta filter dan pencarian Audit. `_laporan_kontrol.html`, `_laporan_audit_kontrol.html`, `laporan-kontrol.css`, dan `laporan-kontrol.js` berada di paket tampilan bersama. Panduan memakai `_panduan.html` yang sama dengan halaman lain.

Desktop menempatkan Filter sejajar pencarian dan Cari. Pada ponsel Filter Audit berada di kanan judul; Panduan dan Print ada pada menu tindakan. Tab/jenis tetap memakai alamat dan izin yang disiapkan `laporan_navigasi`. Jenis yang tidak dapat diakses tetap mengikuti status terkunci semula.

Form Audit tetap mengirim `rentang`, `kelompok`, dan `cari` melalui GET ke `/audit`. Daftar pilihan berasal dari `RENTANG` dan `KELOMPOK`, bukan salinan. Teks pencarian yang sedang diketik ikut saat menerapkan/reset filter. Gerbang dan form pembatalan, termasuk CSRF dan ID catatan, tidak diubah.

Katalog, daftar/kartu, isi laporan, penggambar laporan, API, pilihan periode, PDF, detail, paginasi/kursor, dan seluruh pembaca transaksi tetap seperti sebelumnya. Hanya tombol Print ditambahkan pada kepala dialog laporan; pencetakan menggunakan isi yang sedang terbuka tanpa meminta atau mengubah transaksi.

Pemeriksaan: 37 pengujian lokal (navigasi dan akses peran, kontrol, keamanan/isi laporan, serta paket tampilan); 15 tampilan pada lebar 1440/390/320 piksel untuk tab, filter, periode, Panduan dan isi cetak. Perbandingan sumber membuktikan badan Audit dan katalog/penggambar laporan tidak berubah, serta 16 templat riwayat/detail identik.
