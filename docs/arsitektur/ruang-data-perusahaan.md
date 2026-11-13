# Ruang data perusahaan PadiFlow–TeraFlow

Keputusan 14 November 2026: satu pasangan layanan PadiFlow–TeraFlow berbagi
satu database operasional untuk satu perusahaan. Perusahaan berbeda memakai
database, pasangan layanan, domain, volume berkas, dan kredensial terpisah.
HMU tetap pada database lama. Ini bukan penyaringan baris oleh parameter
`company_id` dan bukan pergantian perusahaan melalui cookie/header pengguna.

Registry Console boleh memuat banyak master perusahaan/lokasi. Baris registry
belum berarti layanan transaksi perusahaan tersebut sudah disediakan.
Console saat ini terhubung ke satu penerbit/API; penyediaan layanan/database
baru dan penghubung Console ke API perusahaan lain **belum otomatis**.
Perusahaan lain tidak boleh mulai bertransaksi di database HMU.

## Pagar runtime

- `HMU_COMPANY_ID`: identitas perusahaan pada registry.
- `HMU_RUANG_DATA`: UUID ruang operasional; sama di pasangan PadiFlow–TeraFlow.
- `HMU_SESI_LAMA_SAMPAI`: epoch batas penerimaan cookie lama. Nol pada ruang
  baru. Pengecualian hanya sah untuk database warisan yang telah ditetapkan.
- Ketiganya harus cocok dengan JSON `setelan_pabrik.ruang_data_perusahaan`.
  Setiap awal transaksi SQL memeriksa identitas sebelum SQL aplikasi berjalan,
  termasuk ORM, SQL mentah, laporan, sinkronisasi, dan pekerja latar.
- Tidak ada `DATABASE_URL`, token layanan, atau kunci sesi yang diterima dari
  payload pengguna. `DATABASE_URL` tetap rahasia deployment.
- Trigger menolak perubahan/penghapusan identitas ruang dan penempatan gudang
  perusahaan lain. Migrasi tidak menambah kolom atau menghitung ulang transaksi.
- Cookie staf/portal baru membawa ID perusahaan dan UUID ruang. Klaim salah
  selalu ditolak, termasuk bila nomor akun sama atau kunci salah tersalin.
- TeraFlow menyertakan `X-HMU-Company` dan `X-HMU-Ruang`; PadiFlow menolak
  ketidakcocokan sebelum membaca/mengubah tiket. Token layanan tetap wajib.
  Pemanggil layanan lama HMU tanpa header tetap didukung dengan token lama;
  ruang baru wajib header. Ini berbeda dari batas waktu cookie lama.
- Pengaturan perusahaan sendiri hanya bekerja pada perusahaan runtime.
  Console tetap dapat mengatur registry; gudang HMU tidak bisa dialihkan ke
  registry perusahaan lain. Pembatasan peran/fungsi harian tetap berlaku.
- Dokumen non-warisan tidak mengambil nama/alamat/kontak HMU sebagai bawaan.

## Penetapan dan deployment

1. Jalankan migrasi 0131 (DDL pagar saja; tanpa penulisan transaksi).
2. Tinjau `scripts/tetapkan_ruang_perusahaan.py --company-id ID --ruang-id UUID
   [--sesi-lama-sampai EPOCH]`. Seluruh gudang harus sudah terkait perusahaan
   yang benar. Database warisan tidak dapat diganti pemiliknya.
3. Terapkan dengan bukti pratinjau, nama persis, dan alasan. Skrip hanya
   mengizinkan SELECT serta INSERT metadata/audit; tidak mengubah akun,
   password, versi sesi, stok, timbang, proses, atau pengiriman.
4. Setel variabel identitas yang sama di PadiFlow dan TeraFlow, lalu restart
   keduanya. Jangan mengganti kunci sesi HMU agar operator tetap masuk.
5. Verifikasi hash commit, health, skema, dan identitas database secara
   baca-saja. Jangan menguji transaksi pada produksi.

Pada rollout HMU, metadata dapat ditetapkan dengan skrip administratif yang
sama sebelum mengaktifkan konfigurasi layanan; setelah migrasi 0131, trigger
membuat identitas itu tetap. Bila konfigurasi salah, kembalikan konfigurasi
ke identitas yang sudah ditinjau, bukan mengganti pemilik database. Jangan
menurunkan migrasi setelah penetapan atau menghapus audit.

## Perusahaan baru

Gunakan database baru tanpa transaksi/akun/master warisan, identitas dokumen
sendiri, domain dan volume tersendiri. Skrip menolak ruang baru yang sudah
berisi tabel bisnis/akun agar salinan HMU tidak dapat dilabel ulang. Penyediaan
migrasi/master generik perlu ditinjau sebelum onboarding perusahaan berikutnya;
seed lama belum menjadi provisioning SaaS otomatis. Kunci layanan/sesi,
printer, Kledo, backup dan akses database harus berbeda per perusahaan.

Tidak ada perusahaan contoh atau salinan transaksi HMU pada produksi.
Pengujian dua database, ID transaksi bertabrakan, pool, cookie, payload lama,
header integrasi, trigger, dokumen dan fingerprint transaksi memakai database
loopback berawalan `uji_`.
