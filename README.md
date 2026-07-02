# Sistem Manajemen Produksi Penggilingan Beras — Backend + 3 Telegram Bot

Sistem pencatatan & analitik penggilingan beras berbasis AI Agent (Claude) via
Telegram. **Fase 1** mencakup Gudang 1 dasar: pembelian gabah, pengeringan,
silo, dengan fitur input pembelian gabah memakai bahasa natural.

## Arsitektur

```
 Bot Gudang 1 ─┐
 Bot Gudang 2 ─┼─►  FastAPI backend  ─►  PostgreSQL (12 tabel Fase 1)
 Bot Admin    ─┘         │
                         └─►  Claude API (ekstraksi bahasa natural)
```

Ketiga bot berjalan dalam satu proses (long-polling), terhubung ke satu
database. Identifikasi pengguna otomatis via `telegram_user_id`.

## Stack
FastAPI · SQLAlchemy 2 (async) · Alembic · aiogram 3 · Anthropic SDK · PostgreSQL

## Setup

### 1. Prasyarat
- Python 3.11+
- Docker Desktop (untuk PostgreSQL)

### 2. Konfigurasi
```bash
cp .env.example .env
# Isi: BOT_*_TOKEN (dari @BotFather), ANTHROPIC_API_KEY
```

### 3. Dependencies
```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

### 4. Database (Docker)
```bash
docker compose up -d          # jalankan PostgreSQL
alembic upgrade head          # buat 12 tabel Fase 1
python -m app.seed            # seed 2 gudang, 4 silo, 1 admin
```
Opsi seed admin dengan ID Telegram Anda:
```bash
SEED_ADMIN_TELEGRAM_ID=123456789 SEED_ADMIN_NAMA="Wahid" python -m app.seed
```

### 5. Jalankan
```bash
uvicorn app.main:app --reload
```
Cek: http://localhost:8000/health

## Cara pakai (Bot Gudang 1)
```
Operator : gabah masuk dari pak budi 8 ton plat B 1234 XY
Bot      : Oke, saya catat: … Konfirmasi simpan?
Operator : ya
Bot      : ✓ Tersimpan. Kode batch: GB-20260702-01
```
Dukungan: gabah basah/kering, tanya data yang kurang, koreksi sebelum simpan
("eh salah 9 ton"), batal dalam 15 menit ("batalkan input").

## Mendaftarkan pengguna
Lewat Bot Admin (oleh admin):
```
/daftar <telegram_id> <nama> <role>      # role: operator|staff|admin
```
Cari `telegram_id` seseorang: minta mereka kirim `/start` ke bot — ID muncul di
balasan bila belum terdaftar.

## Struktur
```
app/
  config.py        database.py       seed.py       main.py
  models/          → 12 tabel SQLAlchemy
  services/        → codegen, purchase, activity_log, notification
  ai/              → claude_client, tools (tool-use), nlp_parser
  bots/            → registry (3 bot), common (auth+session), gudang1/gudang2/admin
migrations/        → Alembic (0001_phase1: 12 tabel)
```

## Status fitur Fase 1
| Fitur | Status |
|---|---|
| 12 tabel + migrasi + seed | ✅ |
| 3 bot terhubung + auth per role | ✅ |
| Input pembelian gabah (natural language) | ✅ |
| Verifikasi harga, pengeringan, silo, milling | ⏳ fase berikutnya |
