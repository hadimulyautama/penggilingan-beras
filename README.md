# Pos Produksi — PT Hadi Mulya Utama

Pos Produksi adalah webapp operasional penggilingan beras. Operator dan staf
mencatat alur dari gabah masuk, pengeringan, silo, milling, penyosohan,
barang jadi, hingga barang keluar. Bot Telegram produksi sudah dipensiunkan;
bot Kantor adalah layanan terpisah.

## Arsitektur

- FastAPI, SQLAlchemy async, PostgreSQL, dan Alembic.
- Repo dan Railway service sendiri (`penggilingan-beras`).
- Berbagi satu PostgreSQL dengan Kantor dan Timbangan, dengan chain migrasi
  terpisah.
- Tiket timbang menjadi sumber bobot masuk. Kantor membaca data pabrik melalui
  API internal ber-token dan read-only.
- Paket `hmu_core`, `hmu_identitas`, dan `hmu_tampilan` disinkronkan dari repo
  sumber masing-masing. Jangan mengedit salinan vendored secara langsung.

App Meja dan Gudang 2 dipensiunkan pada 24 September 2026. Riwayat Git-nya
tersimpan di bundel `../arsip/` pada workspace induk.

## Panduan

- `CLAUDE.md` — aturan kerja, batas modul, dan informasi operasional terkini.
- `docs/ARSITEKTUR.md` — batas sistem, database bersama, dan kontrak lintas repo.
- `docs/DEPLOY-RAILWAY.md` — langkah deploy Produksi.
- `docs/` — rancangan modul dan prosedur khusus.

README lama yang menyebut “Fase 1” dan tiga bot sudah digantikan; gunakan
`CLAUDE.md` dan dokumen arsitektur untuk detail implementasi terbaru.
