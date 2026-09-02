# Pemisahan Kantor ↔ Produksi — SELESAI (2026-09-02)

Kantor AI berjalan di **repo & service Railway sendiri**. Dokumen ini jadi catatan
apa yang dilakukan dan apa yang masih tersisa.

- Repo: **github.com/hadimulyautama/kantor** (privat) · service Railway **`kantor`**
- Produksi: repo `penggilingan-beras` · service `penggilingan-beras`
- SATU Postgres bersama, TIGA chain migrasi: `alembic_version` (produksi) ·
  `alembic_version_core` (master) · `alembic_version_kantor` (Kantor)

## Hasil akhir yang diverifikasi

| Bukti | Hasil |
|---|---|
| `/health` produksi | `bots: ["gudang1","gudang2","admin"]` — Kantor tak ada lagi |
| `/internal/produksi/*` | tanpa token → 403 · token salah → 403 · token benar → data |
| `/internal/produksi/tanya` | dijawab agen pabrik (uji: "stok beras jadi") |
| Log service kantor | `Bot aktif: ['kantor'] · poller: ya` + 7 poller + heartbeat |
| Telegram | `Connection established` — polling eksklusif di service kantor |
| Alembic kantor di DB live | `mengadopsi skema: stamp 0001_baseline_kantor` (0 tabel disentuh) |
| Tes | produksi 16 · kantor 97 |

## Yang MASIH tersisa

1. **`app/kantor/` di repo produksi = SALINAN BEKU.** Ditahan hanya karena
   `mcp_server.py` (service `mcp`) membungkus tool arsip/Drive/dokumen dari sana.
   Untuk menghapusnya, server MCP harus dipecah dulu: tool pabrik tetap di
   produksi, tool Kantor pindah ke repo kantor. **Butuh keputusan pemilik** —
   akibatnya agen Hermes/Cowork menunjuk dua endpoint MCP, bukan satu.
   Sampai itu terjadi: **kembangkan Kantor HANYA di repo kantor.**
2. **Service `mcp` menandai deploy gagal** tiap push (instance yang berjalan
   sehat, HTTP 200). Sudah begitu sebelum pemisahan ini; belum ditelusuri.
3. **Produksi tak punya deteksi downtime sendiri** — heartbeat ikut Kantor
   (memakai bot Kantor + tabel `kantor_heartbeat`). Bila perlu, tambahkan poller
   di Kantor yang mem-ping `/health` produksi.
4. **Fase B** (produksi jadi webapp tanpa bot, seperti timbangan) belum mulai.
   Tak terhalang: `/internal/*` menempel di FastAPI yang nanti jadi webapp itu.

## Catatan operasional

- **Satu token bot = satu proses.** `BOT_KANTOR_TOKEN` kini HANYA di service
  `kantor` (sudah dihapus dari produksi). Jangan pernah diisi di dua tempat.
- **`POLLER_AKTIF`** di service kantor: isi `false` bila suatu saat perlu
  menjalankan instance kedua untuk uji tanpa memproses email/invoice dua kali.
- **Migrasi tabel `kantor_*`** dibuat di repo kantor. Chain produksi kini
  menyaringnya lewat `include_object` — autogenerate produksi tak akan lagi
  mengusulkan DROP/ALTER tabel Kantor.
- **Drift `timbangan_*`**: `alembic check` di produksi melaporkan selisih untuk
  tabel `timbangan_*` (chain produksi membuatnya, aplikasi timbangan pakai SQL
  mentah tanpa model ORM). Pra-ada; jangan autogenerate-apply tanpa disaring.
- **Rollback** (bila perlu): kembalikan `BOT_KANTOR_TOKEN` ke service produksi,
  deploy commit sebelum `7c60932`, lalu matikan service kantor. Data aman —
  Kantor tak pernah mengubah skema, hanya dicap.

---

# Lampiran — rincian pekerjaan

## Yang sudah selesai


**Sisi produksi (branch `feat/pisah-kantor`, belum di-merge/deploy)**

| Jerat lama | Sekarang |
|---|---|
| `bots/common.py` → `ai/nlp_parser` → NLP pabrik | impor tipe di-lazy (`TYPE_CHECKING`); master dari `hmu_core` |
| `ai/guard.py` → `app.kantor.models` | tabel guard pindah ke `app/ai/models.py` (nama tabel TETAP) |
| `ai/base._date_context` (menyeret `ai/tools`, ~1.6k baris tool pabrik) | dipisah ke `app/ai/tanggal.py`, `base` re-export |
| Kantor → `app.ai.agent`, `services.analytics`, `services.dashboard` | API internal `app/web/internal.py` + `app/kantor/klien_produksi.py` |
| Kantor → `app.models` (fasad domain) | `hmu_core` langsung |

Hasil: `import app.kantor.*` hanya memuat `app.config`, `app.database`,
`app.ai.{claude_client,guard,models,tanggal}`, `app.bots.common`. **Nol modul
produksi.** 109 tes lulus.

**Sisi kantor (`kantor/`, commit `fdc95e5`, remote belum ada)**
repo mandiri: `app/` (domain + fondasi salinan), `main.py` sendiri (bot + 7
poller + heartbeat), Alembic sendiri (`alembic_version_kantor`, baseline
terverifikasi `alembic check` bersih), Dockerfile/entrypoint/requirements/
.env.example/README.

## PENTING sebelum deploy branch ini ke produksi

Modul Kantor masih ikut proses produksi, tapi kini bicara lewat HTTP. Karena itu
**sebelum/berbarengan dengan deploy**, set di service `penggilingan-beras`:

```
INTERNAL_API_TOKEN=<rahasia baru>
PRODUKSI_API_URL=https://<url-publik-service-produksi>
PRODUKSI_API_TOKEN=<rahasia yang sama>
```

Kalau tidak diisi: `tanya_produksi`, simulasi HPP di agen Kantor, dan bagian
"operasional" di briefing pagi akan membalas "sistem produksi tak bisa
dihubungi". Sisanya (email, Drive, Kledo, approval) tak terpengaruh.

Verifikasi setelah deploy: `curl -H "X-Internal-Token: <token>"
https://<url>/internal/produksi/operasional` → JSON, dan di Telegram tanya
Kantor "stok beras berapa" → harus dijawab data pabrik.

## Langkah cutover (butuh jendela pemeliharaan, ±15 menit)

1. **Repo GitHub** — buat `hadimulyautama/kantor` (privat), `git push -u`.
   Submodule `core` sudah ter-pin; pastikan Railway boleh akses repo core.
2. ~~Stamp Alembic manual~~ — **tidak perlu lagi.** `kantor/migrations/env.py`
   mengadopsi skema lama sendiri: melihat tabel `kantor_*` sudah ada tapi
   `alembic_version_kantor` belum → baseline dicap, bukan dijalankan. Sudah
   diuji di Postgres bersih untuk ketiga jalur (kosong / sudah ter-chain /
   tabel-ada-tanpa-chain).
3. **Service Railway baru** `kantor` — env dari `.env.example`; `DATABASE_URL`
   sama dengan produksi; `PRODUKSI_API_URL/TOKEN` = URL publik + token produksi.
   `numReplicas: 1`. **Jangan isi BOT_KANTOR_TOKEN dulu.**
4. **Lepas Kantor dari produksi** (satu token = satu polling — urutan wajib):
   a. hapus `BOT_KANTOR_TOKEN` dari service produksi;
   b. deploy produksi tanpa Kantor: buang 7 impor poller + task-nya di
      `app/main.py`, entri `"kantor"` di `bots/registry.py`, blok impor kantor
      di `app/models/__init__.py`, `app/services/heartbeat.py` (pindah ke Kantor),
      lalu hapus folder `app/kantor/`;
   c. begitu produksi hijau, isi `BOT_KANTOR_TOKEN` di service kantor & deploy.
5. **Uji** — /health kedua service; di Telegram: surat/nomor, arsip Drive, email,
   approval, `tanya_produksi`; tunggu briefing pagi berikutnya.
6. **Rollback** — kembalikan `BOT_KANTOR_TOKEN` ke produksi + deploy commit
   sebelum 4b, matikan service kantor. DB tak perlu disentuh (stamp di langkah 2
   tak merusak apa pun).

## Catatan

- **Migrasi tabel `kantor_*` setelah cutover** dibuat di repo `kantor/`, bukan di
  produksi. Chain produksi jangan lagi menyentuh tabel `kantor_*`.
- **Heartbeat** ikut Kantor (memakai bot Kantor + tabel `kantor_heartbeat`).
  Setelah cutover produksi tak punya deteksi downtime sendiri — bila perlu,
  tambahkan ping `/health` produksi dari poller Kantor.
- **Drift `timbangan_*`** — `alembic check` di produksi memang melaporkan selisih
  untuk tabel `timbangan_*`: chain produksi yang membuatnya, tapi aplikasi
  timbangan memakai SQL mentah (tanpa model ORM). Sudah begitu sejak sebelum
  pemisahan ini; jangan pernah jalankan autogenerate lalu apply tanpa disaring.
- **Fase B (produksi jadi webapp tanpa bot)** tidak terganggu: `/internal/*`
  menempel di FastAPI yang sama yang nanti menjadi webapp, jadi Kantor tak peduli
  produksi punya bot atau tidak. Saat bot pabrik dihapus nanti, `app/bots/` di
  repo produksi ikut hilang tanpa menyentuh Kantor (Kantor punya salinannya).
