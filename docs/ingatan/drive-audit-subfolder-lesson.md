---
name: drive-audit-subfolder-lesson
description: "CRITICAL — Drive audit must be subfolder-aware; never bulk-move by top-level category; user's Drive has deliberate deep structure incl. a legal dispute file"
metadata: 
  node_type: memory
  type: feedback
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-08-11T18:10:57.876Z
---

On 2026-08-03 a category-level (top-folder 00–11 only) AI audit flagged 58 files as "nyasar" and I moved them to category roots. This was WRONG and had to be fully reverted — the files were NOT misplaced; they were deliberately organized in DEEP, meaningful subfolders the audit couldn't see.

**Why:** The classifier/taksonomi models only the 12 top-level categories. It cannot see subfolder structure, so it judged deliberately-nested files as misplaced.

**The user's Drive is deeply, intentionally structured — examples discovered:**
- `03 SDM / 01 Data & Identitas Karyawan / [01 Komisaris…08 Buruh Harian by role] / [per-EMPLOYEE folder] / docs` (e.g. NPWP lives in the employee's own folder). `03` also has 11 subfolders (Kontrak Kerja, SK & Pengangkatan, Payroll/BPJS, Jobdesk, …).
- `00 / SOP / [Finance and Accounting_ | Pemasaran dan Penjualan]` — central SOP repository by department.
- `00 / KONTRAK / [party]` and `00 / Surat Perjanjian / [party]` — YES there IS a central contracts archive (I wrongly told the user "no contracts folder" — corrected).
- **`00 / Sengketa / PT. RAJAWALI / …` — a LEGAL DISPUTE evidence collection** (invoices, nota, surat jalan, rekap pembayaran organized per invoice number). The audit scattered this case file to 05/02 — potentially harmful. There is an active/known dispute with **PT Rajawali**; its evidence MUST stay together.

**RULES going forward (hard):**
1. NEVER run top-level-category bulk auto-moves again. The audit/classifier MUST be subfolder-aware: learn the FULL folder tree first.
2. A file already sitting in a DEEP, meaningful subfolder = deliberately filed → LEAVE IT ALONE (do not flag as nyasar).
3. NPWP is not automatically Keuangan: company NPWP (name "HADI MULYA UTAMA" / no. 62.724.859.4-528.000 = 627248594528000) → 02; personal employee NPWP → 03 SDM per-employee folder (sensitive personal data).
4. Consequential moves need per-item review with CONTENT read for sensitive types — batching let 2 personal-NPWP mis-moves slip through.
5. Drive search/list index is eventually-consistent and lags badly after many rapid moves — do NOT act fast on stale results; use exact-match queries and re-verify; never chase with broad substring matches (caused a wrong-file move).

**2026-08-12 — subfolder STANDARDIZATION + placement taxonomy (done RIGHT this time):** owner said Drive filing was "sering salah & berantakan." Root cause: agent files to TOP category but not the right SUBFOLDER → loose files pile at folder-tops + some cross-category misfiles (HR PKWT/SK docs sat in 02-Keuangan & 99-Arsip Lama; _TRANSIT backlog). FIX: (1) designed & created a consistent numbered subfolder scheme across all categories (01-Korespondensi, 06-Pengadaan, 08-IT were empty → created; 05/07/09/11 standardized; Events consolidated into 10-CSR/04-Events, top-level "12 - Events" trashed; 02 typo "Payment Reminer"→"Reminder", NPWP→"09 - NPWP"; +new 02 subfolders 00-Kebijakan & SOP Keuangan, 10-Status Pajak (PKP/Non-PKP), 11-Dokumen Perbankan). (2) Moved ~47 LOOSE (un-subfoldered) files into correct subfolders — ONLY loose files, never touched deliberately-nested ones; PKWT→03-SDM/02, SK→03-SDM/03. Company NPWP (627248594528000) → 02/09 (correct per rule 3). (3) Saved knowledge doc "Panduan Penempatan File — Struktur Drive Arsip PT HMU" (ranah umum) so the bot can now ANSWER "file ini taruh di mana?" — owner's explicit want. This is the subfolder-AWARE approach the lesson demanded. STILL LOOSE (owner to clarify): SURAT PERNYATAAN.docx (generik), toolbox.xlsx, tester.xlsx, broken.xlsx. Pending: improve agent's routing logic to be subfolder-aware at file-creation time; empty _TRANSIT discipline.

**Outcome (2026-08-03 incident):** all 58 reverted to original locations (verified). One identical-duplicate copy of `SALES CONTRACT_DIOPUTRI.pdf` (same md5, safe copy restored to 00/KONTRAK) was quarantined during a dedup and its exact spot is unconfirmed due to index lag — never deleted; re-verify when index settles. Related: [[kantor-ai-project]], [[hermes-vs-own-bot]], [[sop-mastery-principle]].
