# Detail riwayat penggilingan

Riwayat giling selesai memakai lima tab: Ringkasan, Bahan & silo, Hasil & stok,
QC asal, dan Riwayat. Gaya visual memakai kelas `.rhs` dan stylesheet riwayat
sosoh yang sudah dirilis. Riwayat sosoh, proses aktif, dan riwayat lain tetap
menggunakan template masing-masing tanpa perubahan.

Template lama tetap tersedia. Route detail giling hanya beralih ke template
khusus; query, konteks, pemeriksaan izin, koreksi hasil dan PDF tidak berubah.
Seluruh blok fakta, pemakaian silo/batch dan formulir koreksi disalin identik.
QC gabah asal, penghalang koreksi, panduan dan riwayat jeda menggunakan komponen
asli. Seluruh hasil, kondisi, mutu, bahan, transfer, tersedia, waktu, durasi,
identitas jasa, sumber dan bacaan QC tetap tersedia. Hasil belum dicatat
berbeda dari nol; rendemen tidak dihitung ulang oleh browser.

Pergantian tab mempertahankan node formulir dan draf. Pratinjau koreksi lokal
menampilkan dasar, target dan alasan; konfirmasi tetap mengirim formulir asli
ke server melalui handler koreksi bersama. Penolakan server mempertahankan
isian dan membuka tab Hasil & stok, termasuk pemeriksaan ulang data bersamaan.
Browser tidak memperbarui dasar tersembunyi sendiri. Tidak ada perubahan API,
layanan, skema atau rumus bisnis.

Navigasi induk Laporan & Riwayat tetap tersedia di menu, memakai node dan
handler asli di dialog. Print detail mencetak seluruh tab. Tautan tab memakai
query `tab_detail` sebagai fallback tanpa JavaScript, serta hash rincian lama.
PDF tetap membuka viewer, unduhan dan laporan yang sama. Panduan menggunakan
kelas bersama; isinya khusus riwayat giling.

Uji browser PostgreSQL mencakup desktop 1440px dan ponsel 390/320px, keyboard,
identitas node/isian selama berganti tab, QC per batch, sumber silo, pratinjau
baca saja, simpan koreksi, konflik data lama, izin operator, stok yang sudah
sebagian ditransfer, penghalang koreksi, PDF, panduan dan navigasi induk.
