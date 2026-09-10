---
name: gmail-pribadi-token-mati
description: "Dua mailbox Gmail PRIBADI Kantor gagal invalid_grant sejak 2026-09-02 — refresh token OAuth-nya mati, BUKAN akibat pemisahan repo (terbukti lewat perbandingan hash)"
metadata:
  type: project
---

Poller email & tagihan Kantor melempar `google.auth.exceptions.RefreshError:
invalid_grant: Bad Request` untuk **wahidnurhani20@gmail.com** dan
**wahidnurhani@gmail.com** — dua mailbox PRIBADI yang memakai user-OAuth
(`GMAIL_PRIBADI*_REFRESH_TOKEN`), bukan mailbox Workspace (service account +
domain-wide delegation, jalur itu sehat).

**Bukan akibat pemindahan ke service `kantor`.** Dibuktikan tanpa memaparkan
rahasia: SHA-256 tiap variabel di service produksi vs kantor dibandingkan — 23
dari 24 identik byte-per-byte termasuk kedua refresh token itu; satu-satunya
selisih `GMAIL_SA_JSON` cuma kehilangan `\n` di ujung (dan kodenya `.strip()`
duluan, jadi tak berpengaruh). Artinya token yang sama juga sudah ditolak Google
saat masih di produksi.

**Dugaan penyebab:** OAuth consent screen masih berstatus *Testing* → refresh
token kedaluwarsa 7 hari; atau aksesnya dicabut dari akun Google.

**Cara perbaiki:** jalankan ulang alur OAuth dan tempel token barunya ke
Variables service `kantor` — skripnya `kantor/scripts/gdrive_oauth.py` (pola
sama, tinggal ganti scope Gmail). Belum dikerjakan; menunggu pemilik.

Terkait: [[kantor-email-gmail]], [[pisah-kantor-produksi]].
