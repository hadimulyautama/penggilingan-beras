---
name: kantor-bot-consolidation
description: TUNTAS 2026-09-08 — bot produksi dibubarkan, perintah lewat percakapan dihapus; agen = baca-saja untuk Direksi/pengawas, Kantor satu-satunya bot
metadata:
  node_type: memory
  type: project
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-09-08T15:24:13.751Z
---

**Keputusan pemilik 8 September 2026 — menggantikan roadmap fold bertahap:**
"perintah melalui agen dihapus saja. agen hanya untuk direksi ataupun pengawas
saja. operasional dan timbangan murni menggunakan app." + "sisakan bot AI kantor".

Jadi Fase D terjadi, tapi BUKAN dengan memindahkan tulis ke Kantor lewat gerbang
approval (rencana lama Fase C). Kemampuan menulis lewat percakapan **dibuang**,
bukan dipindah. Alasannya: yang mencatat bukan yang menjawab.

**Keadaan sekarang:**
- Bot Telegram di repo produksi **tidak ada lagi** — `app/bots/` dihapus, beserta
  parser forced-tool (`ai/nlp_parser`, `ai/tools`, `ai/base`), penyalur niat
  (`ai/router`, `ai/fast_route`), jalur initData Telegram (`web/telegram_auth`,
  `require_miniapp_user`), halaman Mini App lama, aiogram, dan `BOT_*_TOKEN`.
- `run_agent` **tak punya parameter `allow_write`** — sengaja dibuang, bukan
  di-`False`-kan. Bendera yang mati cuma menunggu dinyalakan lagi.
- Satu-satunya pintu ke agen produksi: `POST /internal/produksi/tanya`, dipanggil
  **Kantor AI** (repo & service sendiri) dengan token `INTERNAL_API_TOKEN`.
  Dijaga tes `tests/test_tanpa_bot.py`.
- Aturan peran pindah `app/bots/common.py` → **`app/peran.py`**.

**PRINSIP PERMANEN (masih berlaku, diperkuat):** fungsi/divisi baru → tool+role di
bot **Kantor**, jangan bikin bot baru. Dan sekarang tambahannya: **jangan
menambahkan jalur tulis lewat percakapan ke produksi**. Operasional dicatat di Pos
Produksi, penimbangan di app Timbangan.

**Temuan saat membongkar:** peringatan pengeringan telat mengirim lewat
`bots["gudang1"]` — bot yang sudah dihapus 3 September — jadi sejak itu ia
berputar tiap 5 menit tanpa pernah mengirim apa pun. Sisi Telegram-nya dibuang;
catatan notifikasi di basis data tetap, karena itu yang dibaca Pos Produksi.

Related: [[kantor-org-rbac]], [[hermes-vs-own-bot]], [[kantor-ai-project]],
[[pisah-kantor-produksi]], [[fase-b-webapp-produksi]]
