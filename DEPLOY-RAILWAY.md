# Deploy ke Railway

Alternatif paling sederhana: deploy langsung dari GitHub, tanpa VM/SSH/jaringan.
Railway otomatis mem-build `Dockerfile` di repo ini dan menjalankan migrasi
lewat `docker/entrypoint.sh`.

> **Biaya:** Railway tidak gratis-selamanya. Ada kredit trial, lalu paket
> **Hobby ~$5/bulan** (sudah termasuk pemakaian $5) untuk jalan 24 jam. Bot +
> Postgres kecil ini muat di dalamnya.

Bot memakai **long-polling**, jadi service ini jalan sebagai **worker** —
tidak perlu domain publik.

---

## Langkah 1 — Daftar & buat proyek

1. Buka <https://railway.app> → **Login with GitHub** → authorize.
2. **New Project** → **Deploy from GitHub repo**.
3. Kalau diminta, beri Railway akses ke repo **`penggilingan-beras`**.
4. Pilih repo tersebut. Railway mendeteksi `Dockerfile` dan mulai build.
   - Build pertama boleh gagal/crash — wajar, belum ada database & token.

## Langkah 2 — Tambah database Postgres

1. Di kanvas proyek, klik **New** (atau **+ Create**) → **Database** →
   **Add PostgreSQL**.
2. Muncul service **Postgres**. Railway otomatis menyiapkan variabel
   koneksinya.

## Langkah 3 — Isi variabel di service aplikasi

1. Klik service aplikasi (yang dari repo) → tab **Variables** → **New Variable**
   / **Raw Editor**.
2. Tambahkan:

   | Variable | Nilai |
   |---|---|
   | `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` |
   | `BOT_GUDANG1_TOKEN` | token dari @BotFather |
   | `BOT_GUDANG2_TOKEN` | token dari @BotFather |
   | `BOT_ADMIN_TOKEN` | token dari @BotFather |
   | `ANTHROPIC_API_KEY` | kunci Claude Anda |
   | `CLAUDE_MODEL` | `claude-haiku-4-5-20251001` |
   | `APP_TIMEZONE` | `Asia/Jakarta` |

   - `${{Postgres.DATABASE_URL}}` adalah **referensi** ke service Postgres
     (jaringan internal, gratis). Kode app otomatis mengubahnya ke driver
     async (`postgresql+asyncpg://`).

## Langkah 4 — Deploy & verifikasi

1. Railway otomatis redeploy setelah variabel diubah (atau klik **Deploy**).
2. Buka service app → tab **Deployments** → **View Logs**.
   - Cari baris migrasi Alembic `Running upgrade ... 0006_moving` (skema dibuat).
   - Lalu polling aiogram jalan tanpa error.
3. Kirim pesan ke bot dari Telegram — harus dibalas.

> ⚠️ **Matikan bot yang jalan di laptop** sebelum ini. Dua poller pada token
> yang sama = konflik Telegram 409 → pesan hilang.

## Update / redeploy

Cukup `git push` ke `main`. Railway otomatis build & deploy versi baru;
migrasi baru jalan otomatis via entrypoint.

## Hapus data dummy (setelah fase pengembangan)

Selama sebulan dev, data dummy menumpuk. Saat siap produksi, kosongkan **data
transaksi** tapi pertahankan **data master** (users, gudang, silo, mesin
pengering, supplier):

1. Di proyek Railway → service **Postgres** → tab **Data** (query runner), atau
   dari laptop: `railway connect Postgres` (buka psql).
2. Tempel & jalankan isi file **`scripts/reset_data.sql`**.
   - Ingin supplier ikut dikosongkan? Hapus `'suppliers'` dari daftar `keep` di
     SQL itu.
3. Selesai — skema tetap, tabel transaksi kosong, siap data asli.

> Skema tidak dihapus, jadi **tidak perlu** migrasi ulang. `RESTART IDENTITY`
> otomatis mereset penomoran id & kode harian (GB/LOT/MIL) dari 1 lagi.

Alternatif paling bersih: saat go-live, tambah **Postgres baru** di Railway,
arahkan `DATABASE_URL` ke situ — data dummy ditinggal di DB lama.

## Catatan

- **Tidak perlu** klik "Generate Domain" — ini worker, bukan web publik.
- Kalau koneksi DB gagal (jaringan internal Railway pakai IPv6), coba ganti
  `DATABASE_URL` ke `${{Postgres.DATABASE_PUBLIC_URL}}` sementara untuk tes.
- Backup: `railway connect Postgres` lalu `pg_dump`, atau pakai fitur backup
  bawaan plugin Postgres Railway.
