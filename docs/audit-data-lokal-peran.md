# Audit data lokal: PK, draf tersimpan, retur supplier

Basis: 3c65164 (produksi v479). Perbaikan dalam branch ini belum dideploy.
Tidak ada database produksi yang digunakan untuk membuat data contoh.

Data dibuat melalui fixture dan layanan transaksi sebenarnya di Postgres
loopback uji_audit_peran_20261028. Browser masuk dengan empat akun uji asli.
Server uji memakai lifespan=off agar bot tidak berjalan dan memblokir HTTP
keluar dari loopback. Database regresi terpisah: uji_audit_peran_regresi_20261028.

Cakupan dan hasil:

- PK: diminta, disetujui, dikirim, selesai, ditolak; catatan permintaan dan
  detail tindakan/riwayat sesuai gudang.
- Draf: tersimpan lengkap dan parsial, saldo pratinjau selesai dimuat,
  draf sendiri dan draf akun lain.
- Retur: pembuatan, pengajuan tersimpan, tiket terbuka, siap diperiksa,
  barang keluar, tiga jenis formulir koreksi, hasil koreksi, pembatalan,
  tab riwayat serta tahap konfirmasi pengajuan/keluar melalui browser.
- 216 tampilan pada lebar 320/390 px; 10 POST/PUT tanpa izin ditolak 403/404.
- 142 uji regresi transaksi/HTTP lulus. Enam skenario otomasi browser lulus.
- Browser tidak menyimpan pengajuan, menerbitkan draf, atau mencatat barang
  keluar. Pratinjau boleh berjalan lokal. Fixture membentuk transaksi lokal
  agar tahap berikutnya dapat dibaca. Produksi tidak diubah.

Temuan yang diperbaiki:

1. Detail PK masih menautkan Tutup permintaan untuk operator G1 pada status
   dikirim. Tautan kini mengikuti izin katalog dan menjadi span terkunci
   untuk peran tanpa hak; server tetap menolak POST operator dengan 403.
2. Koreksi berat transfer ditampilkan sebagai kontrol terkunci saat tidak
   berizin atau terhalang status, dengan label yang sama.
3. Pembuatan retur, pengaitan tiket, pembatalan pengajuan, serta aksi koreksi
   dan pembatalan setelah keluar tetap terlihat bagi pembaca yang berhak
   melihat data, dengan kontrol disabled/fieldset disabled sesuai izin.
   Tidak ada perubahan izin, scoping gudang, atau kepemilikan draf.

Uji browser opt-in membutuhkan Playwright + Chromium, selain dependensi uji
proyek. Jalankan dari root checkout ini. Pilih database uji loopback kosong
berawalan uji_; fixture mengosongkan tabel pada setiap kasus. Contoh URL
lokal yang dipakai dalam audit ini tidak memuat password produksi.

```sh
export DATABASE_URL=postgresql+asyncpg://postgres@127.0.0.1:55493/uji_audit_peran_20261028
export UJI_PG_URL="$DATABASE_URL"
export MODE_UJI=true
python -m alembic upgrade head
python tests/pg/_audit_local_server.py
```

Pada terminal lain, dengan tiga variabel yang sama:

```sh
HMU_AUDIT_UI_OUT=/tmp/hasil-audit-peran python -m pytest tests/pg/test_audit_lokal_peran.py -q -s
```

Server hanya mengikat 127.0.0.1:8882. HMU_AUDIT_UI_BASE boleh diarahkan ke
port loopback lain; set HMU_AUDIT_UI_PORT pada proses server ke port yang sama. Uji browser
normalnya dilewati bila HMU_AUDIT_UI_OUT tidak disetel. Uji regresi HTTP yang
menjaga kontrol terkunci tetap menjadi bagian suite Postgres biasa.

Status 404 pada draf akun lain melindungi kepemilikan; ini berlaku juga bagi
Super Admin. Fitur draf tetap tersedia untuk draf pribadi masing-masing
Admin/Super Admin. Operator tidak memperoleh akses finansial atau draf.
