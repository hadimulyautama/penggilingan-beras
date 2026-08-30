# Deploy modul Timbangan ke Railway

**Service kedua, database yang sama.**
Versi 1.0 · 30 Agustus 2026

Modul Timbangan berjalan sebagai service Railway tersendiri di atas repo dan
PostgreSQL yang sama dengan service `app`. Pemisahan ini bukan soal skala —
melainkan agar **deploy pos timbang tidak pernah sanggup menjatuhkan bot yang
sedang melayani manajemen**, dan sebaliknya.

---

## 1. Aturan yang tidak boleh dilanggar

| Hal | Aturan | Alasan |
|---|---|---|
| Migrasi | **Hanya service `app`** yang menjalankan `alembic upgrade head` | Dua service yang bermigrasi bersamaan akan berebut skema |
| Urutan deploy | Saat skema berubah: **`app` dulu**, baru `timbangan` | Tabel harus ada sebelum dipakai |
| Replica | Service `timbangan` **boleh lebih dari satu** | Tidak memegang token bot Telegram, jadi tidak ada bentrok long-polling |
| Database | `DATABASE_URL` **sama persis** dengan service `app` | Satu sumber kebenaran; tidak ada master tandingan |

Service ini sengaja memakai `docker/entrypoint-timbangan.sh` yang **melewati
migrasi**. Bila tabel `timbangan_*` belum ada, aplikasi akan gagal terang-terangan
pada query pertama — itu yang diinginkan, jauh lebih baik daripada diam-diam
membuat skema versi sendiri.

---

## 2. Membuat service

> **Config-as-code tidak bisa dipakai.** Sejak 2026-08-28 Railway menutupnya
> untuk service yang belum pernah memakainya, dan seluruh fiturnya berakhir
> 2026-12-01. Semua setelan di bawah diisi lewat dashboard.

1. Buka project Railway yang sudah ada (berisi `app`, `mcp`, dan PostgreSQL).
2. **New** → **GitHub Repo** → pilih repo yang sama (`penggilingan-beras`).
   Railway membuat service dengan nama acak dan **belum men-deploy** — semua
   setelan berikut diisi lebih dulu, baru tekan Deploy sekali di akhir.
3. Klik nama servicenya, ganti jadi **`timbangan`**.
4. **Settings** → **Deploy** → **Custom Start Command**:

   ```bash
   docker/entrypoint-timbangan.sh uvicorn app.timbangan.main:app --host 0.0.0.0 --port $PORT
   ```

5. **Settings** → **Deploy** → **Healthcheck Path**: `/health`
6. **Settings** → **Networking** → **Generate Domain**

---

## 3. Variabel lingkungan

Wajib:

| Variabel | Nilai | Catatan |
|---|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` | Referensi, bukan salinan — ikut berubah sendiri bila database dipindah |
| `TIMBANGAN_SECRET_KEY` | string acak panjang | **Wajib.** Tanpa ini, semua sesi login hangus setiap kali server restart |
| `TIMBANGAN_ADMIN_PASSWORD` | sandi admin awal | Hanya dipakai sekali, saat tabel akun masih kosong |

> **Jangan pakai "Suggested Variables".** Railway menawarkan variabel yang
> ditemukannya di kode, termasuk `BOT_*_TOKEN`. Mengisinya akan membuat
> instance bot keempat yang bentrok `409 Conflict` dengan service `app`.
> Isi lewat **Raw Editor** agar isinya persis tiga baris di atas.

Membuat kunci sesi:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"
```

Opsional — semuanya punya nilai bawaan yang benar, isi hanya bila memang berubah.
**Lima yang bertanda ✎ dapat diubah Admin langsung dari halaman Pengaturan**
tanpa menyalakan ulang service; nilai dari layar menang atas environment sampai
dikembalikan ke bawaan.

| Variabel | Bawaan | Arti |
|---|---|---|
| ✎ `TIMBANGAN_KAPASITAS_KG` | `20000` | Kapasitas jembatan timbang. Angka di atas ini ditolak sebagai mustahil |
| ✎ `TIMBANGAN_KELIPATAN_TERA_KG` | `10` | Kelipatan pembacaan alat; dipakai memperingatkan angka janggal |
| `TIMBANGAN_SESI_HARI` | `180` | Batas atas umur sesi. Bukan pengusir harian — sesi berakhir saat petugas menekan Keluar |
| ✎ `TIMBANGAN_JAM_KUNCI` | `24` | Jam sampai transaksi terkunci bagi petugas; pengawas tetap bisa mengoreksi |
| ✎ `TIMBANGAN_JAM_TIKET_MENGANGGUR` | `12` | Tiket terbuka yang lebih lama dari ini ditandai "Lama" |
| ✎ `TIMBANGAN_MAKS_FOTO_MB` | `4` | Batas ukuran satu foto bukti |
| `TIMBANGAN_ADMIN_USERNAME` | `admin` | Nama pengguna admin awal |
| `TIMBANGAN_PERUSAHAAN` | `PT Hadi Mulya Utama` | Tercetak di bukti timbang |
| `TIMBANGAN_ALAMAT` | `Masaran, Kab. Sragen` | Tercetak di bukti timbang |
| `TIMBANGAN_TELEPON` | `+62 851-7416-7950` | Tercetak di bukti timbang |

Seluruh daftar ini juga tampil di dalam aplikasi pada **Pengaturan**
(`/timbangan/pengaturan`) lengkap dengan **nilai yang sedang berlaku** — jadi
tidak perlu menebak apakah variabel di Railway sudah benar-benar terpakai.
Setiap perubahan dari layar tersimpan di tabel `timbangan_config` dan tercatat
di jejak audit sebagai `UBAH_SETELAN`.

**Yang tidak ada di sini dan memang tidak akan pernah ada:** ambang kontrol,
tara, dan aturan komoditas. Semua itu hidup di tabel `timbangan_jenis`, karena
merevisinya berarti merevisi cara perusahaan menilai kejujuran timbangan —
keputusan yang harus lewat revisi SOP, bukan lewat kotak isian environment.

---

## 4. Urutan menyalakan pertama kali

1. **Deploy service `app`** lebih dulu (menjalankan migrasi `0022_timbangan`
   dan `0023_timbangan_config` yang membuat 13 tabel `timbangan_*`).
2. Setel variabel lingkungan service `timbangan`, termasuk
   `TIMBANGAN_ADMIN_PASSWORD`.
3. **Deploy service `timbangan`.** Saat menyala, ia menyemai master komoditas
   (11 baris) dan membuat akun admin awal.
4. Buka `https://<domain-timbangan>/timbangan/` → masuk sebagai `admin`.
5. Buka **Pengguna** → buat akun tiap petugas, beri **kode perangkat** berbeda
   (`P1`, `P2`, …). Kode itu masuk ke nomor transaksi, sehingga dua perangkat
   yang sedang tanpa jaringan tidak akan membuat nomor yang sama.
6. **Hapus `TIMBANGAN_ADMIN_PASSWORD`** dari environment setelah admin dipakai.

Penyemaian aman dijalankan berulang: hanya menambah baris yang belum ada, tidak
pernah menimpa aturan yang sudah disetel manajemen.

---

## 5. Memasang di ponsel petugas

Aplikasi ini PWA — tidak lewat toko aplikasi, tidak perlu instalasi.

**Android (Chrome).** Buka alamatnya → menu ⋮ → **Tambahkan ke layar utama**.

**iPhone (Safari).** Buka alamatnya → tombol Bagikan → **Tambahkan ke Layar Utama**.
Harus lewat Safari; Chrome di iOS tidak menyediakan pilihan ini.

Setelah dipasang, aplikasi terbuka layar penuh tanpa bilah alamat, dan **tidak
meminta sandi lagi** sampai petugas menekan Keluar.

---

## 6. Memeriksa setelah deploy

```bash
curl https://<domain-timbangan>/health
```

Harus menjawab `{"status":"ok","modul":"timbangan"}`.

Lalu periksa dengan mata:

- `/timbangan/` menampilkan tiga pilihan: Barang masuk, Pengiriman, Jasa timbang
- `/timbangan/aturan` menampilkan 11 komoditas beserta tara dan batasnya
- Buat satu transaksi uji, lalu **batalkan** — jangan hapus. Modul ini memang
  tidak punya cara menghapus.

---

## 7. Printer 80 mm

Bukti timbang dicetak sebagai halaman HTML biasa lewat **AirPrint (iOS)** atau
**Mopria (Android)** — bukan ESC/POS lewat Bluetooth, karena iOS tidak
mengizinkan Web Bluetooth. Konsekuensinya: printer harus **printer jaringan
(Wi-Fi/LAN)**, dan satu printer bisa dipakai semua perangkat sekaligus.

Halaman cetak sudah diatur `@page { size: 72mm auto }` — lebar kertas 80 mm
dengan margin cetak 4 mm di kiri-kanan.

---

## 8. Bila ada yang salah

| Gejala | Sebab yang paling mungkin |
|---|---|
| `relation "timbangan_transaksi" does not exist` | Service `app` belum di-deploy dengan migrasi `0022`/`0023` |
| Semua orang ter-logout tiap deploy | `TIMBANGAN_SECRET_KEY` belum diset |
| Tidak bisa masuk sama sekali | `TIMBANGAN_ADMIN_PASSWORD` kosong saat penyalaan pertama, sehingga tidak ada akun yang dibuat |
| Nomor transaksi bentrok antar-perangkat | Dua akun memakai kode perangkat yang sama |
| Halaman "Tanpa jaringan" muncul terus | Service worker memegang versi lama — naikkan `VERSI` di `app/timbangan/web.py` dan `sw.js` |
