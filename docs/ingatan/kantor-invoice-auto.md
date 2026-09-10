---
name: kantor-invoice-auto
description: "Auto-process incoming invoices/subscription docs → propose Arsip filing + IT Management update in one gated confirm; phased build, brain done"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-08-15T16:03:12.267Z
---

Owner loved the flow demoed 2026-08-15 (a Kledo invoice PDF → enriched IT Management biaya
+ filed to correct Drive folder). Wants it AUTOMATIC. Chosen: **trigger = auto-watch
_TRANSIT + email attachments**; **build Phase 1 now**; **real test will be at GajiHub
renewal** (a real invoice, no rush to fire today).

**Flow:** doc arrives (email attachment / _TRANSIT) → OCR/extract → classify (invoice?
vendor/service? amount? paid?) → propose TWO actions in ONE ✅ gate: (a) Arsip file to
right folder, (b) IT Management update (biaya/renewal/catatan of matched service) → owner
✅ → both execute + verify.

**COST RISK (critical):** bulk OCR/LLM once tripped the API spend cap & took the bot
offline (see [[bulk-llm-audit-cost]]). Guards: pypdf text FIRST (free), Haiku vision OCR
only if no text; Haiku for extraction; cap docs/run; only process detected invoices;
processed-marker (label/DB) to avoid re-processing; put poller behind a config FLAG.

**Reuses existing pieces:** ocr.py (`ocr_bytes`), billing.py (Haiku forced-tool extract
pattern), persetujuan gate (`sheet_update` jenis + `_lakukan`), it_aset `perbarui_it`,
drive taksonomi/mapper, deadline/billing pollers as poller templates.

**BUILT (commit 23c445f) — Increment 1: the BRAIN `app/kantor/invoice.py` (INERT, not yet
wired):** `ekstrak()` (Haiku forced-tool → jenis/langganan/vendor/layanan/no_invoice/
tanggal/total/lunas/siklus/keyakinan), `cocok_layanan()` (→ Services row by token overlap),
`susun_usulan()` (deterministic → folder [langganan→08/03 Lisensi&Langganan
id=1_IVqi1Nk56Jb8HywsSfTF3EHkiWUbyVJ], clean filename, IT updates incl renewal=tanggal+1yr),
`ringkas_usulan()` (preview). PROVEN dry-run on real Kledo invoice: correct extract, matched
"Kledo", proposed renewal 14 Agu 2027 + biaya + arsip. 5 unit tests (tests/test_invoice.py).

**BUILT — Increment 2 & 3 (commit adef40e, deployed, FLAG OFF so dormant):**
- Executor: `persetujuan._lakukan` jenis **`invoice_proses`** — one ✅ does file move+rename
  (arsip) AND multiple Services cell writes (IT update). Reuses DriveClient.pindah/
  ganti_nama/sheet_tulis.
- `invoice.usul_dari_file(file_id, mime, nama, asal_id)`: read doc (pypdf free) → ekstrak
  Haiku → if LANGGANAN → `resolve_updates()` (→ concrete `Services!<col><row>` cells,
  catatan appended) → buat_pending(invoice_proses). Skips non-langganan/low-confidence/no-text.
- Poller `app/services/invoice_poller.py`: watches _TRANSIT every 30min, max 5 PDF/run,
  dedup via active pending (no double-propose), behind `settings.invoice_auto` (default
  False). Wired in main.py. 8 tests in tests/test_invoice.py.

**STAGED ARCHIVE redesign (commit 92ff3d7, deployed) — per SOP Kearsipan + owner:** files do
NOT go straight to final category; they pass through `_TRANSIT` stage subfolders so digital⇄
physical stay consistent (print/scan) and order is tracked. Subfolders created in Drive:
`00 - Belum Dipilah` (1IjpGW-bnfCLTglYgRBsQasdGbgW0C6Z-), `01 - Perlu Dicetak`
(1XlMGc72CW8tKgM36M-g2VYHHayx96vK_), `02 - Perlu Discan` (1mkfuhzhAlL68Jic6PN3FgWNbnhgOrle9),
`03 - Siap Arsip Final` (1Apex3m9QnH3bCnkq_9xLK9c4MFTStYJe), `04 - Draft`
(1R29uTZWd3VMsrNlHvO64TOw4SabxjFl0). SOP rule: physical is MASTER only for legal originals
(wet-sign/materai/sertifikat); regular work docs (invoices/notes) = digital enough, physical
optional. `invoice.ekstrak` now has `perlu_fisik` flag; **AUTO-ARCHIVE SCOPE (commit bca250f): the poller/auto-archive acts ONLY on files in
`03 - Siap Arsip Final`** (owner: "auto arsip hanya berlaku di subfolder siap arsip final").
Human owns stages 00/01/02/04 (sort, print, scan, draft); when a doc is ready they move it
into `03`. The bot then watches `03`, and for each invoice proposes: move file `03`→final
category (langganan→08/03 `LANGGANAN_FOLDER_ID`=1_IVqi1Nk56Jb8HywsSfTF3EHkiWUbyVJ) + IT-Mgmt
update, one ✅ gate. `perlu_fisik` no longer routes (file in 03 already vetted) — it's just a
"ensure physical copy archived" reminder in the proposal. IT-Mgmt update happens at that ✅. Draft docs ([DRAFT] docx from persetujuan drive_dokumen) now land in
`_TRANSIT/04 - Draft` (7 old drafts moved there).

**TO ACTIVATE:** env `INVOICE_AUTO=true` → poller runs (currently OFF). Validate at GajiHub
renewal. **Email-attachment ingestion: EXPLICITLY OUT OF SCOPE** (owner decided 2026-08-15 —
docs enter via _TRANSIT only: manual download / scan). **REMAINING (optional):** image/scan
OCR (text-PDF only via pypdf now); optional auto LOG - Disposisi File entry when the bot
archives from `03` (kept manual for now — don't change official process unilaterally); proper
seen-table (relies on _CAP + pending-dedup; KantorConfig.nilai 255-char cap blocks a
config-based seen-set). Physical→scan path (02) is a human/basket step, not Drive-automatable.

Related: [[kantor-it-management-domain]] (the IT side + perbarui_it), [[kledo-integration]],
[[drive-audit-subfolder-lesson]] (correct folder placement matters).
