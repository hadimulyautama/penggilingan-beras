# Deploy ke Oracle Cloud (Always Free)

Panduan menghosting Sistem Penggilingan Beras di **Oracle Cloud Infrastructure
(OCI) Always Free** — gratis selamanya, tidak ditagih selama pakai resource
"Always Free".

## Kenapa setup ini sederhana

Ketiga bot memakai **Telegram long-polling** (koneksi keluar ke Telegram),
bukan webhook. Artinya server **tidak perlu**:
- Port HTTP/HTTPS terbuka ke internet
- Domain / DNS
- Sertifikat TLS

Yang perlu terbuka hanya **SSH (port 22)** — dan itu default. Server cukup bisa
akses internet keluar (untuk Telegram + Claude API).

Arsitektur di server: satu VM menjalankan 2 kontainer via Docker Compose —
`db` (Postgres) dan `app` (FastAPI + 3 bot). Keduanya bicara lewat jaringan
internal Docker; tidak ada yang diekspos ke publik.

---

## Bagian A — Daftar Oracle Cloud

1. Buka <https://www.oracle.com/cloud/free/> → **Start for free**.
2. Isi email, negara **Indonesia**, verifikasi.
3. Perlu **kartu kredit/debit** untuk verifikasi identitas. Selama Anda hanya
   memakai resource "Always Free", **tidak ada tagihan**. (Akun baru juga dapat
   $300 trial 30 hari untuk resource berbayar — abaikan saja.)
4. Pilih **Home Region** yang dekat, mis. **Singapore** atau **Jakarta** (kalau
   tersedia). ⚠️ Region tidak bisa diganti nanti — pilih yang benar sekali ini.

---

## Bagian B — Buat VM Ampere A1 (ARM, gratis)

Free tier memberi total **4 OCPU + 24 GB RAM** ARM Ampere A1. Untuk app ini
2 OCPU / 12 GB sudah sangat cukup.

1. Console OCI → menu ☰ → **Compute** → **Instances** → **Create instance**.
2. **Name**: `penggilingan`.
3. **Image and shape** → **Edit**:
   - **Image**: **Canonical Ubuntu 22.04**.
   - **Shape** → **Ampere** → **VM.Standard.A1.Flex** → set **2 OCPU**,
     **12 GB memory**.
4. **Networking**: biarkan default (buat VCN baru otomatis). Pastikan
   **"Assign a public IPv4 address"** = **Yes**.
5. **Add SSH keys**:
   - Kalau belum punya kunci, pilih **Generate a key pair for me** → **Download
     private key** (simpan file `.key` baik-baik — ini satu-satunya cara masuk).
   - Atau **Paste public key** kalau sudah punya (`~/.ssh/id_ed25519.pub`).
6. **Create**. Tunggu status **RUNNING**, lalu catat **Public IP address**.

### Kalau muncul "Out of host capacity"

A1 sering penuh di region populer. Solusi:
- Ganti **Availability Domain** (AD-1/2/3) saat create, coba satu-satu.
- Turunkan ke **1 OCPU / 6 GB** (tetap cukup untuk app ini).
- Coba lagi beberapa jam kemudian (kapasitas dilepas berkala).
- Alternatif terakhir: shape AMD **VM.Standard.E2.1.Micro** (1 GB RAM) — jalan,
  tapi tambahkan swap (lihat Bagian C) karena RAM mepet.

---

## Bagian C — Masuk ke server (SSH)

Dari komputer Anda (macOS Terminal):

```bash
# Kalau pakai private key hasil download dari OCI:
chmod 600 ~/Downloads/ssh-key-*.key
ssh -i ~/Downloads/ssh-key-*.key ubuntu@<PUBLIC_IP>
```

User default Ubuntu di OCI adalah `ubuntu`.

**(Opsional) Tambah swap** — wajib kalau pakai shape 1 GB, opsional selain itu:

```bash
sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
sudo mkswap /swapfile && sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

---

## Bagian D — Install Docker

```bash
sudo apt update && sudo apt upgrade -y
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker ubuntu
newgrp docker   # aktifkan grup tanpa logout
docker --version && docker compose version
```

---

## Bagian E — Ambil kode & isi konfigurasi

```bash
sudo apt install -y git
git clone https://github.com/wahidnurhani20/penggilingan-beras.git
cd penggilingan-beras

cp .env.example .env
nano .env
```

Isi di `.env` (yang WAJIB):
- `BOT_GUDANG1_TOKEN`, `BOT_GUDANG2_TOKEN`, `BOT_ADMIN_TOKEN` — dari @BotFather
- `ANTHROPIC_API_KEY` — kunci Claude Anda
- `CLAUDE_MODEL` — biarkan `claude-haiku-4-5-20251001`

`DATABASE_URL` di `.env` **diabaikan** saat prod — compose otomatis
mengarahkannya ke kontainer `db`. Simpan (Ctrl+O, Enter) dan keluar (Ctrl+X).

> ⚠️ Jalankan **hanya satu** instance bot per token. Kalau bot lokal di laptop
> masih menyala dengan token yang sama, matikan dulu — dua poller pada satu
> token bikin konflik (Telegram 409) dan pesan bisa hilang.

---

## Bagian F — Jalankan

```bash
docker compose -f docker-compose.prod.yml up -d --build
```

Perintah ini: build image app, start Postgres, tunggu sehat, jalankan migrasi
Alembic otomatis, lalu start server + 3 bot.

Cek:

```bash
docker compose -f docker-compose.prod.yml ps          # kedua service Up
docker compose -f docker-compose.prod.yml logs -f app  # lihat log bot
```

Cari baris polling aiogram yang berjalan tanpa error, lalu tes kirim pesan ke
bot dari Telegram. Keluar dari log dengan Ctrl+C (server tetap jalan).

Kontainer akan **auto-start saat server reboot** (`restart: unless-stopped`).

---

## Bagian G — Update / redeploy

Setelah ada perubahan kode di GitHub:

```bash
cd ~/penggilingan-beras
git pull
docker compose -f docker-compose.prod.yml up -d --build
```

Migrasi baru dijalankan otomatis oleh entrypoint saat kontainer app start.

---

## Bagian H — Operasional

**Restart / stop:**
```bash
docker compose -f docker-compose.prod.yml restart app
docker compose -f docker-compose.prod.yml down        # stop semua (data aman di volume)
```

**Backup database** (jadwalkan via cron kalau perlu):
```bash
docker exec penggilingan_db pg_dump -U milluser penggilingan \
  | gzip > ~/backup-penggilingan-$(date +%F).sql.gz
```

**Restore:**
```bash
gunzip -c ~/backup-penggilingan-YYYY-MM-DD.sql.gz \
  | docker exec -i penggilingan_db psql -U milluser -d penggilingan
```

**(Opsional) Pindahkan data dari laptop ke server** — sekali di awal:
```bash
# di laptop:
docker exec penggilingan_db pg_dump -U milluser penggilingan | gzip > dump.sql.gz
scp -i <key> dump.sql.gz ubuntu@<PUBLIC_IP>:~/
# di server (setelah stack jalan sekali agar skema ada; atau restore penuh):
gunzip -c ~/dump.sql.gz | docker exec -i penggilingan_db psql -U milluser -d penggilingan
```

---

## Catatan keamanan

- Hanya port **22 (SSH)** yang terbuka; tidak ada layanan web publik.
- Ganti password Postgres default (`millpass`) untuk produksi: ubah di
  `docker-compose.prod.yml` (env `POSTGRES_PASSWORD` **dan** `DATABASE_URL`)
  sebelum `up` pertama, atau `docker compose down -v` dulu bila mengganti setelah
  ada data (⚠️ `-v` menghapus volume/data).
- `.env` berisi rahasia dan sudah di-`.gitignore` — jangan commit.
