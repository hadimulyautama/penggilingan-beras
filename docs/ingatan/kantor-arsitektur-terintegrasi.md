---
name: kantor-arsitektur-terintegrasi
description: "Desain KANONIK sistem terintegrasi — satu loop agen (config per domain), modul Production terpisah, fondasi bersama; optimal: murah/cerdas/andal/sederhana"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-08-13T09:23:11.887Z
---

Prinsip pemilik (dikonfirmasi): **seefisien & semurah mungkin, tetap handal/cerdas/reliable, arsitektur sangat optimal & TIDAK terlalu kompleks.** Diagram + status: artifact **"Pengembangan Kantor AI"** (https://claude.ai/code/artifact/2a30bb43-0bc3-4173-9118-4eb82ede72c2) — dulu bernama "Kantor AI — Arsitektur Terintegrasi", sejak 2026-09-06 dijadikan halaman pengembangan (arsitektur + sakelar + papan kerja + utang teknis).

**PRINSIP INTI — "AI Agent = config, BUKAN proses":**
- AI Agent Finance/HR/Legal/Arsip/Sekretaris = **SATU loop agen yang sama**, di-instantiate dgn **bundel-tool + prompt domain** yang di-swap per permintaan. Bukan proses/bot terpisah. → sederhana, tak ada orkestrator berlapis.
- Hanya **AI Agent Production** (rice mill) yang benar-benar **modul terpisah** (punya agen `app.ai.agent` + data operasional sendiri) → **didelegasikan** via `app/kantor/produksi.py` (tool `tanya_produksi`, read-only, financial dari RBAC).

**ALUR SATU PERMINTAAN (termurah dulu):**
1. **Deterministik?** perintah umum → jawab **tanpa LLM** (0 token, paling andal).
2. Perlu LLM → **Router Haiku** (murah) pilih domain + pangkas bundel tool.
3. **SATU loop agen Sonnet** dgn bundel domain (prompt pendek + prompt-caching).
4. Butuh produksi? → **delegasi ke Modul Production** (jarang). Hindari nested-LLM sebagai default.

**FONDASI BERSAMA (dipakai semua modul, nol duplikasi):**
- **Memori percakapan**: SATU per user, di front-end (Kantor), lintas domain; ~8 giliran (kecil=murah). Modul dipanggil dgn tugasnya; kontinuitas dari memori front-end.
- **Knowledge/otak perusahaan**: SATU base semantik (Voyage), **bertag domain + disaring RBAC** (`rbac.knowledge_larang`); top-k saja (murah). BEDA dari **data operasional** (batch/produksi = tabel DB per modul).
- **RBAC/identitas · audit · pengaman biaya (cap $50/kill-switch) · prompt-caching**.

**EMPAT LAPIS HEMAT:** deterministik (Rp0) → router Haiku → bundel ramping+cache → cap biaya.

**STATUS (2026-09-06):** Router **dikirim sebagai kata-kunci deterministik, BUKAN Haiku** (`app/kantor/router.py`) — alasannya: dgn prompt-caching, membundel tak selalu lebih murah, nilainya KETAJAMAN; karena itu di balik flag. 65 tool → 7 bundel domain (peta menutup semua tool, pas). Tiga sakelar masih ditahan: `router_aktif=false`, `rbac_enforce=shadow`, `invoice_auto=false`; `poller_aktif=true` (8 task latar). SUDAH = pemisahan repo, adopsi skema otomatis, fondasi bersama, jembatan produksi read-only, 97 tes. BERIKUTNYA = onboarding peran → `rbac_enforce=on` · A/B router · uji invoice_auto (renewal GajiHub) · Kledo Fase 1 (klien tulis + gerbang).

**PRINSIP PERMANEN (anti sprawl):** fungsi baru → bundel-tool di satu loop, BUKAN bot/agen baru. Modul terpisah hanya bila punya data+agen sendiri.

Related: [[kantor-bot-consolidation]], [[kantor-org-rbac]], [[agentic-layer]], [[kantor-otak-perusahaan]]
