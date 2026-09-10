---
name: kantor-it-management-domain
description: "IT Management as a DOMAIN of the Kantor agent (not a new bot) — subscription/asset register (Sheet source + DB mirror), gated writes, renewal radar; DESIGNED not built"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-08-15T05:47:57.136Z
---

Owner wants the Kantor agent to also act as an **IT Manager Assistant**: when he says
things like "Kledo sudah diperpanjang", it should record the renewal, update the
register + related Google Drive files, and remind before the next expiry. Trigger: he
confirmed Kledo Elite renewal in Telegram and the agent did nothing — because the
**capability didn't exist**, not a memory/context bug.

**Decision (2026-08-15): NO separate agent.** IT Management = a new **domain** inside the
one Kantor agent, consistent with [[kantor-arsitektur-terintegrasi]] ("AI Agent = config
not process"). RBAC domain `folder_it` already exists (Direksi + Elfira only).

**User choices:** register stored as **BOTH** — human-visible Sheet source **+ DB table
`kantor_it_aset`** (structured mirror for fast query + renewal radar). Next step chosen:
**design first** (diagram + memory), build only after approval. Diagram at scratchpad
`it_management_domain.html`.

**CRITICAL (2026-08-15, after inspecting Drive): a mature IT DB ALREADY EXISTS — do NOT
create a new "Register IT" sheet.** Folder "IT Accounts (kredensial)"
(`12n4jOMrbS-krWekH6yJODu8RV4Pg7slO`) holds Sheet **"IT Accounts (Database) - PT Hadi
Mulya Utama"** with 7 tabs: **Services** (28 services — cols incl. Biaya, Tgl Renewal),
Users (8), Accounts (12), Akses (26), Perbankan (9), Keamanan (17), Offboarding info (13).
Sibling folder "08 IT & Sistem" (`1OtrKmw0txv3GQYv_ily6nDuj8ED4eXM5`) has subfolders
(Kebijakan & SOP, Panduan, Lisensi & Langganan, Rencana Kerja) + a SOP IT PDF
(Onboarding/Offboarding/Insiden) in `1DZ6WiAx7n6PwSs8jiAyEmXVeI3fP1cao`. Kept MANUALLY &
current (Kledo row already shows renewal 14 Agu 2027). Design REVISED: register = existing
**Services tab** (Tgl Renewal/Biaya = radar source); DB mirror = sync Services (+Perbankan)
→ `kantor_it_aset`; "Kledo diperpanjang" → update the Kledo row (propose→confirm), not a
new sheet. NOTE when reading this folder: it holds credentials — read structure/non-secret
cols only, never dump login/2FA values.

**Design:**
- Data: write to **Sheet first** (single writer) → sync Sheet→DB (daily + after each write).
  Sheet cols: Item, Kategori, Vendor, Biaya, Siklus, Mulai, Habis, Status, PIC, Link file.
- Tools (domain "it"): `register_it` (read/filter), `cek_jatuh_tempo_it` (read), and
  `catat/perbarui_it` (WRITE via propose→confirm→apply, then resync DB). Reuse existing
  Arsip tools for related Drive files.
- Router: add domain "it" keywords (kledo, gajihub, langganan, domain, hosting, railway,
  lisensi, akun, perpanjang, subscription, server, jatuh tempo langganan).
- Proactive: daily poller → items expiring in 30/14/7 days → notify Direksi + PIC (fits
  [[kantor-proaktif]] deadline-radar roadmap). Renewal reschedules radar automatically.
- RBAC: gate IT tools on `folder_it` (read/write). ALL writes gated by persetujuan — never
  silent auto-write (deliberate, per controlled-write principle).
- Seed: Kledo Elite, GajiHub, domain hadimulya.com, Google Workspace (3 mailboxes),
  Railway (penggilingan-beras + mcp), hosting hadimulya-website.

**MORE (2026-08-15, after inspecting code): renewal RADAR ALREADY EXISTS & runs** —
`app/services/deadline_poller.py` reads Services tab "Tgl Renewal" (Indonesian dates) +
Calendar, alerts H-7/3/1/0 + overdue≤3d daily 07:00 WIB. Sheet id default
`1BxcGg1GitQmjTwbKRHmXUdiU2c2Z1yXt9TGK7kIOLY0` = the real sheet (correct). So DB-mirror
and a new radar were BOTH dropped as redundant — read the sheet live, no `kantor_it_aset`.

**BUILT & DEPLOYED (commit 1b4b942):** `app/kantor/it_aset.py` — 3 read-only tools over the
IT Accounts sheet (live read, no DB mirror): `register_it` (list services + filter),
`cek_jatuh_tempo_it` (upcoming/overdue renewals), `info_layanan_it` (one service detail +
who has access; UserID→Nama via Users tab). PRIVACY: only non-secret operational cols —
never password/login. Wired into agent (_TOOLS + dispatch), router (domain "it"), rbac
(`_IT_READ`→folder_it read; Direksi+Elfira). 8 pure tests in tests/test_it_aset.py.
Env `IT_ACCOUNTS_SHEET_ID` overrides sheet id (shared with deadline_poller).

**SHEET DESIGN TIDIED (2026-08-15, commit 9feed31 + direct sheet writes, all confirmed):**
Services tab now has **M="Status"** (aktif/dipensiunkan) + **N="Siklus"** (gratis/bulanan/
tahunan/per-pemakaian) — appended so cols A–L unchanged (radar/tool unaffected). Zoho
"Dipensiunkan" moved Paket→Status. it_aset.py now reads A2:N & shows Status/Siklus.
Deterministic content fills done: 11 free services Tgl Renewal→"N/A"; 4 banks Siklus→
"bulanan"; Squarespace renewal→"11 Agu 2027 (auto-renew ON)". So a BLANK now genuinely
means "needs filling". Audit verdict: relational integrity clean (no orphan ServiceID/
UserID, no dup). IT_ACCOUNTS_SHEET_ID default = 1BxcGg1GitQmjTwbKRHmXUdiU2c2Z1yXt9TGK7kIOLY0.

**STILL TODO:** (B, needs owner data) biaya + real renewal dates for paid svcs (GajiHub,
McEasy, Voyage, Kledo, Workspace, Glints, SEEK; confirm Railway date); 2FA posture (banks/
Workspace/domain/Railway/Kledo — Keamanan 8/17 & Accounts 10/12 blank); add Akses/Keamanan
rows for social media + recruitment + McEasy; remaining Siklus (GajiHub/McEasy/Glints/SEEK).
**GATED WRITE DONE (2026-08-15, commit bfa9a29): `perbarui_it`** — agent proposes a
1-field update to Services (renewal/biaya/status/siklus/paket/catatan; login/credential
cols REJECTED) when owner says a service changed. Reuses existing executor
`persetujuan._lakukan` jenis `"sheet_update"` (writes one cell) → owner ✅ button → written.
RBAC `_IT_WRITE`→folder_it write. So the AGENT now does what I did manually — answers the
original complaint fully. Wired: agent dispatch (NAMA_USUL), router "it", 14 tests total.

**IT MANAGEMENT DOMAIN COMPLETE** (read + gated write + radar already-existing). Remaining
is only DATA ENTRY (the B list above — owner supplies biaya/dates/2FA). Possible future:
give the agent the same for other tabs (Akses/Keamanan) if needed.

Related: [[kledo-integration]] (Kledo is the trigger item), [[kantor-org-rbac]]
(folder_it = Direksi + Elfira), [[drive-audit-subfolder-lesson]] (Folder IT structure).
