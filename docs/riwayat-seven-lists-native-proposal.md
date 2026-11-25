# Proposal tujuh daftar Riwayat: native structure + GET yang sama

Basis exact `d147691f1650d623df2a2f5ebda5b0665e43404f`; child terpisah.
Tidak membawa proposal report/schema/data/PDF, Transfer, detail atau QC beras.
Tidak mengubah handler, shared compiler/registry/PINDAH/core/vendor/perizinan.
QC prototype `a7ddb4bd` tetap frozen; proposal ini menerapkan pola yang sama
pada tujuh route tanpa membawa partial laporan yang ditahan.

## Route, query dan guard exact

| Route | Query shell didukung | Predicate native sebelum render |
|---|---|---|
| /riwayat-giling | kosong atau satu `sebelum` raw | _is_jenis_operator(user, penggilingan) |
| /riwayat-sosoh | kosong atau satu `sebelum` raw | _is_jenis_operator(user, penyosohan) |
| /riwayat-pengeringan | kosong atau satu `sebelum` raw | _is_jenis_operator(user, pengeringan) |
| /riwayat-qc/gabah-basah | kosong | _is_gabah_operator(user) |
| /riwayat-qc/gabah-kering | kosong | _is_gabah_operator(user) |
| /riwayat-qc/pk-hasil-giling | kosong | _is_jenis_operator(user, penggilingan) |
| /riwayat-qc/pk-luar | kosong | _is_g2_operator(user) |

GET saja; portal/portal_scope, alias, detail, aksi, QC beras, Transfer dan query
lain decline ke handler native. Tidak membuang query atau mengganti cursor.
Cursor invalid tetap disimpan raw dalam URL; arti valid/invalid tetap kontrak
handler asli. Query maks 2048 karakter dibatasi sebagai descriptor,
bukan validasi data baru. Tidak ada filter pencarian QC yang dibuat-buat.

`kerangka(request, akun, konteks)` pada riwayat_daftar_bertahap.py menjalankan
predicate native dahulu, lalu membaca metadata. `konteks.LAPORAN_NAV` wajib
berasal pemilik native pilihan(akun)/siapkan, aktif/family, jenis dan detail=False
cocok serta route ada boleh_alamat. Missing/mismatch decline. Tidak mengimpor
siapkan untuk memilih role sendiri, tidak membuat akun, dan snapshot bukan izin
reader. Handler GET berikutnya tetap menjalankan guard/scope/query aslinya.

Alias /riwayat dan /laporan-riwayat tidak mempunyai default G1/G2 pada proposal.
Root perlu memilih exact destination dari opsi native sebelum klik untuk
blueprint. Jangan membuat asumsi gudang/peran atau menebak link objek.

## Struktur dan titik integrasi root

Metadata pure riwayat_daftar_metadata.py mengekstrak header tabel/grid statis
persis dari template sumber. Ringkasan proses memakai macro `_riwayat.header`
asli dengan caption sumber Jinja dan **Belum dibaca**, tanpa mengevaluasi nilai,
merender kartu kosong palsu, memanggil formatter atau membuat ORM/identitas.
Pengeringan tidak mengasumsikan angka/status lot; placeholder ringkasan belum
membaca data. Metadata cache hanya source label/markup, bukan akses atau saldo.

Proses memakai parent `_daftar_riwayat_proses.html`: CSS, posisi tools, slot
kategori dan panduan native tetap. QC memakai `_riwayat_qc_alat` serta CSS/guide
native. Tidak ada H1 transisi tambahan. Tidak ada pintu record/aksi palsu;
penelusuran/cetak dijelaskan belum tersedia. Builder menonaktifkan cetak asli.
Root compiler yang merender block langsung juga wajib menonaktifkan marker itu.

Adapter `riwayat-daftar-native.js` hanya memasang PADI_BACA_NATIVE pada explicit
7-route URL yang sudah diberikan root. `data-url` sama persis path+query dokumen,
mis. `/riwayat-giling?sebelum=123`; bukan endpoint data baru. Core existing
mengirim **GET URL itu dengan X-Pindah:1**, memeriksa cap/context/session/address,
menyiapkan aset sebelum swap, dan abort/abaikan hasil usang; tidak ada fetch atau
POST tambahan dalam adapter. Status error/timeout dan tombol Coba lagi memakai
core existing. Retry hanya GET. Stamp disediakan builder konteks+target; bukan
pengganti server authorization. Tidak ada route/reader wiring dalam child ini.

Pure `keadaan()` menyediakan loading, empty, filtered-empty, error eksplisit;
missing ditolak. Shell awal hanya loading. Body placeholder netral Data belum
tersedia tidak berpura-pura berisi stok/status terkini; status hidup terpisah
memuat pesan core. Reader sukses memasang hasil native. Tidak ada normalizer
HTML client yang menyamarkan hasil kosong/gagal sebagai data benar.

Untuk compiler: sediakan public metadata(path), RIWAYAT_STATE, RIWAYAT_URL,
RIWAYAT_STAMP, VERSI, request dengan path tujuan, PORTAL_READ_ONLY=False serta
LAPORAN_NAV asli. Tidak perlu kartu/rows/count/account contoh. Template proses
mewarisi parent dan mendefinisikan block daftar_isi; jangan mengekstrak child
block isi yang tidak ada dan kehilangan parent/panduan. Gunakan renderer
inheritance dengan base content-only/wrapper native seperti compiler root.
Root memiliki wrapper .laporan-riwayat/navigation, descriptor izin dan manifest
semua partial/aset termasuk native guide scripts dan padi-baca-native.

## Sukses kosong dan perbedaan mobile

App-owned `riwayat_qc.html` juga diubah presentasinya (izin khusus root) agar
header **asli enam span** selalu ada dan empty berada dalam satu body cell
aria-colspan=6. Teks empty/catatan_kosong lama tetap; **loop baris aktual persis
identik byte** terhadap baseline. Tidak ada master, metric, formula atau row
calculation yang diubah. Grid native bukan HTML table: role row/cell digunakan
untuk status, tidak membuat header kolom baru. Karena daftar QC belum memiliki
filter search, tidak menambah filter-empty query bisnis baru. Keadaan filtered
empty murni kontrak presentasi; keputusan emptiness tetap pembaca asli.

Tiga daftar proses sudah menjaga header desktop pada empty native. CSS native
menyembunyikan `.riwayat-desktop-list` di bawah 900 px; phone memakai daftar
kartu. Proposal menjaga nav/ringkasan/status serta container mobile kosong dan
**tidak membuat lot/card palsu**. Ini belum membuktikan seluruh field kartu
mobile tampak sebelum data. Jika keputusan root mengharuskan label field kartu
sebelum data juga, perlu prototype structural mobile yang ditinjau terpisah;
jangan membuka desktop grid lewat CSS global atau mengklaim pixel parity.

## Bukti lokal dan gerbang

54 pure tests PASS: 7 route × 4 explicit states, kolom/header asli, caption/stat
unknown, query preserved/decline, predicate delegation, guard sebelum metadata,
nav wajib/context tidak dimutasi, cetak nonaktif, loop rows QC byte-identik,
empty native QC six-header/one-cell, dan JS adapter allowlist melalui Node.
Tiny base, helper predicate stubs dan source Git blob adalah test harness;
bukan bukti akun/tenant/PG/browser/native permission. Tidak ada server/listener.

Root review diff dan runtime sequential: native nonempty parity QC/proses,
403/session invalid, facility/tenant switch, sameURL+cursor/deep-link/Back,
HTML/data delay, stale response/abort, empty/error/retry, desktop/390, keyboard,
PWA cold/warm/rollback. Tidak ada global GO/halaman selesai sebelum wiring dan
bukti tersebut. Tidak ada remote, CI/deploy, transaksi/data/config nyata.
