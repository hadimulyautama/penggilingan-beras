# Pemisahan Kantor ↔ Produksi — status & langkah cutover

Status: **siap cutover, BELUM dieksekusi.** Produksi live masih menjalankan
Kantor di proses yang sama. Repo `kantor/` sudah lengkap & teruji lokal.

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
2. **Stamp Alembic** — pada DB LIVE, dari `kantor/`:
   `DATABASE_URL=<live> alembic stamp 0001_baseline_kantor`
   (membuat `alembic_version_kantor`; TIDAK menyentuh tabel/chain lain).
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
