# Deploy ke Railway

> **24 September 2026 — app Meja & app Gudang 2 DIHAPUS.** Keputusan pemilik:
> keduanya tidak dipakai lagi; operator Gudang 2 maupun staf administrasi
> memakai Pos Produksi. Layanan Railway, repo GitHub, dan folder lokalnya
> dihapus (riwayatnya tersimpan sebagai bundel git di `../arsip/`), dan pintu
> `/internal/meja/*` serta `/internal/gudang2/*` berikut `MEJA_API_TOKEN`
> dicabut dari produksi. **Setiap kalimat di bawah yang menyebut kedua app itu
> harus dibaca sebagai riwayat, bukan keadaan sekarang.**


Backend = FastAPI + bot Telegram (long-polling) dalam **satu proses**, plus
PostgreSQL. Deploy pakai **Dockerfile** yang sudah ada (migrasi jalan otomatis
saat start via `docker/entrypoint.sh`). Port dari `$PORT` (disuntik Railway).

> ⚠️ **WAJIB 1 replica.** Long-polling menuntut hanya SATU proses yang polling
> tiap token. `railway.json` sudah set `numReplicas: 1` — jangan menaikkannya,
> dan jangan menjalankan laptop + Railway dengan token bot yang SAMA bersamaan
> (nanti bentrok `409 Conflict`).

---

## Bagian 0 — Hapus sistem TES di Railway (bersihkan dulu)

> Menghapus project/service **tidak bisa dibatalkan** — data test hilang. Karena
> ini memang sistem uji, aman.

1. Buka <https://railway.app> → login.
2. Pilih **project tes** yang lama.
3. Hapus salah satu cara:
   - **Hapus seluruh project**: **Settings** project → scroll ke **Danger** →
     **Delete Project** → ketik nama project untuk konfirmasi.
   - **Atau per service**: klik service (app / Postgres) → **Settings** →
     **Delete Service**.
4. Pastikan tak ada service tersisa yang masih memakai token bot lama.

---

## Bagian A — Repo siap

Kode sudah di GitHub: **`wahidnurhani20/penggilingan-beras`**. Pastikan commit
terbaru ter-*push* (berisi `railway.json`, `Dockerfile` `$PORT`, router, dll):

```bash
git push origin main
```

---

## Bagian B — Buat project + database

1. Railway → **New Project** → **Deploy from GitHub repo** → pilih
   `penggilingan-beras`. Railway mendeteksi `Dockerfile` → build otomatis.
2. Di project itu: **+ New** → **Database** → **Add PostgreSQL**.

---

## Bagian C — Variables (di service **app**, tab *Variables*)

Wajib:

| Key | Nilai |
|---|---|
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` *(referensi — internal, tanpa ribet SSL)* |
| `ANTHROPIC_API_KEY` | `sk-ant-...` (kunci produksi Anda) |
| `CLAUDE_MODEL` | `claude-sonnet-5` |
| `ADMIN_TELEGRAM_ID` | ID Telegram admin (mis. `1352846912`) |
| `ADMIN_NAME` | nama admin |
| `APP_TIMEZONE` | `Asia/Jakarta` |

Isi **NANTI** (setelah buat bot produksi di Bagian E):

| Key | Nilai |
|---|---|
| `BOT_ADMIN_TOKEN` | token bot admin produksi |
| `BOT_GUDANG1_TOKEN` | token bot Gudang 1 |
| `BOT_GUDANG2_TOKEN` | token bot Gudang 2 |

Opsional: `MINIAPP_MODEL=claude-haiku-4-5`, `DASHBOARD_TOKEN=<rahasia>`.

> `PORT` diatur Railway **otomatis** — jangan diset manual.
> Tanpa token bot, app tetap jalan (web/Mini App saja) — bisa deploy dulu,
> tambah bot belakangan.

---

## Bagian D — Deploy & verifikasi

1. Simpan Variables → Railway **redeploy** otomatis.
2. **Deploy Logs** harus memuat: `migrasi selesai` lalu `Backend siap`.
3. **Settings** service app → **Networking** → **Generate Domain** → dapat URL
   publik `https://<nama>.up.railway.app`.
4. Buka `https://<domain>/health` → `{"status":"ok","model":"claude-sonnet-5",...}`.

---

## Bagian E — Bot produksi + Mini App

1. **@BotFather** → `/newbot` (buat bot produksi; bisa 3 bot atau sesuai
   kebutuhan). Salin tiap token.
2. Isi token ke **Variables** Railway (Bagian C) → redeploy → bot online 24/7.
3. Aktifkan tombol Mini App tiap bot (pakai domain publik dari Bagian D):

   ```bash
   curl -X POST "https://api.telegram.org/bot<TOKEN>/setChatMenuButton" \
     -H "Content-Type: application/json" \
     -d '{"menu_button":{"type":"web_app","text":"Buka Dashboard",
          "web_app":{"url":"https://<domain>/api"}}}'
   ```
   Ulangi untuk tiap token bot.
4. Buka bot → tombol **Buka Dashboard** → login otomatis via Telegram (initData)
   → halaman menyapa nama + role Anda.

---

## Catatan penting

- **Satu replica saja** (sudah di `railway.json`). Scale >1 = bot bentrok.
- **Jangan** polling token bot yang sama dari laptop dan Railway bersamaan.
- `DATABASE_URL` pakai **referensi** `${{Postgres.DATABASE_URL}}` (jaringan
  internal Railway) — lebih aman & cepat daripada public URL.
- **Data uji di laptop tidak ikut** — DB Railway mulai kosong; data master
  (standar/merk/kemasan) di-*seed* otomatis saat start.
- Ganti kunci/token bila pernah bocor. Bot yang dihapus di @BotFather otomatis
  membatalkan tokennya.


## Meja Administrasi (service `meja`, repo `meja/`)

Sejak 12 September 2026 pekerjaan staf administrasi dikerjakan dari service
`meja`, yang memanggil API internal service ini. Variabel yang perlu ada:

| Di service | Variabel | Isi |
|---|---|---|
| `penggilingan-beras` | `MEJA_API_TOKEN` | token acak panjang; kosong = pintu Meja mati |
| `meja` | `MEJA_PRODUKSI_TOKEN` | nilai yang SAMA |
| `meja` | `MEJA_URL_PRODUKSI` | alamat privat service produksi (`http://penggilingan-beras.railway.internal:PORT`) |
| `meja` | `MEJA_SECRET_KEY` | kunci cookie sesi Meja |

Taruh rahasia lewat `--stdin` atau berkas; jangan pernah dicetak.
