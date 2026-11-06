# Detail riwayat transfer PK

Detail `/riwayat-transfer/{id}` dan `/permintaan-pk/{id}` memakai kerangka
riwayat proses yang sama pada desktop dan ponsel: judul, kode, status,
kepemilikan, sumber, kontrol tindakan, panduan dan empat tab bergaris bawah.
Halaman daftar riwayat transfer tidak diubah.

Ringkasan membedakan bobot catatan yang sedang dibuka, total transfer aktif
seluruh lot dan saldo PK di Gudang 1. Angka dibaca dari penyusun rincian
lama; JavaScript tidak menghitung stok. Identitas, packing, pemilik, jenis PK,
tujuan, komponen saldo, empat bobot permintaan, selisih, sebab, waktu,
pencatat, pembatalan, tahapan, audit, catatan terkait, tautan dan paginasi tetap
tersedia. Catatan lama yang tidak lengkap tetap memakai keterangan aslinya.

Panduan memakai `_panduan.html` dan `panduan.css` bersama. Navigasi induk
Laporan & Riwayat ditempatkan dalam dialog dengan node tautan asli; tanpa
JavaScript tetap tampil seperti sebelumnya. Tidak ditambahkan fungsi PDF
yang sebelumnya tidak dimiliki detail transfer.

Formulir koreksi tetap berasal dari `_transfer_koreksi.html`, termasuk POST,
token CSRF, `hasil_transfer`, `dasar_transfer`, alasan, `kembali_kerja`,
`wajib_periksa` dan `periksa_ulang`. Dengan JavaScript, node formulir itu
ditampilkan dalam dialog, lalu diperiksa dampaknya sebelum konfirmasi.
Menutup dialog dan berganti tab tidak membuang isian atau mengganti baseline.
Tanpa JavaScript formulir asli tetap dapat digunakan langsung di tab Riwayat.

Koreksi tetap membatalkan catatan asal dan membuat pengganti bila bobot lebih
dari nol; nol membatalkan tanpa pengganti. Bobot dan packing asal tetap
historis. Pemeriksaan nilai terbaru, stok, izin dan pemakaian hilir tetap
dilakukan layanan lama. Respons 422 memasang ulang kontrol pada main baru,
memakai isian dan baseline dari server, serta membuka pemeriksaan ulang.
Tidak ada perubahan skema, transaksi, penulisan peristiwa atau aturan akses.

Tautan paginasi membersihkan parameter pembuka tindakan yang lama agar
formulir yang telah ditutup tidak terbuka lagi saat membaca halaman berikutnya.
Pemberitahuan sukses koreksi membungkus teks serta tautan pengganti sehingga
tautan tidak menyusut menjadi lebar nol pada ponsel.

Verifikasi lokal:

- `tests/pg/test_riwayat_transfer_desain_browser.py`: desktop 1440 px, ponsel
  390 dan 320 px; tab, navigasi keyboard, panduan, rincian, packing, draf,
  pemeriksaan dampak, penolakan baseline lama, pemeriksaan ulang, koreksi nol,
  koreksi positif, tautan pengganti, konteks kembali, formulir tindakan dan
  paginasi yang tidak membuka ulang tindakan.
- `tests/pg/test_detail_transfer_pk.py` dan
  `tests/pg/test_permintaan_empat_langkah.py`: peran, empat bobot, saldo,
  pembatalan, penghalang hilir dan rantai permintaan asli.
- `tests/test_tampilan_paket.py`: paket bersama tetap utuh.

Uji lama `test_riwayat_transfer.py::test_tiga_yang_boleh[superadmin-None-None]`
gagal pada fixture penggilingan karena jenis proses tidak tersedia. Kegagalan
yang sama direproduksi pada commit dasar sebelum perubahan UI, dalam database
lokal terpisah; bukan perubahan layanan atau fixture pada pekerjaan ini.
