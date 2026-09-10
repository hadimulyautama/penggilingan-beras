---
name: kledo-kontak-supplier-sync
description: "Kledo contact cleanup (no merge feature — reassign txns then delete) + planned Kledo→production supplier sync (designed, not built)"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-08-25T09:49:35.349Z
---

**Kledo contact hygiene (2026-08-22):** Kledo has **NO merge-contact feature**. To dedup:
move every transaction off the duplicate contact (edit each invoice/bill/payment → change
its contact to the keeper), and only once the contact has zero transactions can it be
deleted. Balance=0 does NOT mean zero transactions (paid ones still linked & block delete).

611 contacts audited → duplicates: 13 exact-name groups + 1 same-phone group (strong) +
28 honorific-stripped clusters (review — Pak vs Ibu can be different people). CSV worklist
+ a ready Claude-in-Chrome prompt (reassign-then-delete + type-tagging) were produced. Rule
the owner set: **for any non-Pegawai contact, tag it Vendor + Pelanggan + Lainnya** (Kledo
type_ids is multi-value) so one contact serves all roles (fixes e.g. Umar Arifuddin who was
split #515 supplier vs #539 "Umar Arifuddin 2" customer w/ Rp 1.625.000 receivable).

**Planned Kledo→Production supplier sync (DESIGNED, not built; owner chose "rancang dulu"):**
Production module (`suppliers` table: nama_supplier/no_telfon/alamat/status, in
app/models/master.py) needs supplier master data — and the prod DB is still EMPTY (operators
not entering gabah intake, partly for lack of supplier list). Plan: **one-way Kledo →
production**, basis = **riwayat pembelian** (contacts appearing on purchase invoices / with
payable = real gabah vendors), NOT customers. Dedup: add a `kledo_contact_id` column to
`suppliers` (idempotent link, no duplicates) + normalize-name dedup. Preview counts before
writing. Kledo contact fields: id/name/phone/address/type_ids/payable/receivable at
/finance/contacts. NEXT: build diagram+design, then migration + sync fn + preview.

**DEDUP EXECUTED (2026-08-22/23) — DONE for category 1 & 2 via ARCHIVE.** Hard-won method:
the reliable dedup action is **`PATCH /finance/contacts/{id}/archive` with body `{}`**
(reversible via `/unarchive`) — works whenever the contact's outstanding hutang/piutang = 0,
regardless of reconciled transactions (archive doesn't touch transactions). DELETE only works
if the contact has ZERO transactions of any type (invoices AND expenses — Kledo blocks
otherwise: "Contact sudah digunakan pada transaksi"). MOVING a transaction's contact:
expenses need a **full PUT `/finance/expenses/{id}`** with booleans as INT (include_tax/
pay_later = 0/1, else 400 "harus berupa integer") — BUT **reconciled expenses are blocked**
("Biaya tidak dapat diubah karena pembayaran telah direkonsiliasi"), and reconciliation is
NOT visible on the expense (bank_statement_id stays None) — only revealed at PUT time.
Un-reconcile via API only reverts a WHOLE bank statement (blast radius) — UNSAFE; do it in
UI if ever needed. So: **don't move/delete reconciled contacts — ARCHIVE them.** Financial
snapshot (Σ all contacts' receivable+payable + Σ bank) stayed invariant across every op.
RESOLVED groups (keeper): Dwi Purwanto→#851 (del #1067), Hardi→#1113 GajiHub master (archived
#942 w/147 reconciled exp), Sieny→#882 (archived #1008/#1009), Wignyo→#1106 GajiHub (archived
#1043), Pur Bagong→#550 (arch #814), Agus Jatmiko→#1018 (arch #1017), Satria→#596 (arch #650),
Jafar→#600 (arch #573), Puji→#586 (arch #587), Purwanto→#668 (arch #931), Toko Larice→#1086.
NOT a dup (left active): Agus #503 "Agus Ompong" vs #534. PENDING: Umar #539 "Umar Arifuddin 2"
has Rp 1.625.000 receivable → settle first, then archive; #515 "UD Azzam Putra" is the real
supplier (keep). Reusable script: scratchpad `arsip.py <ids...>` (archive + snapshot verify).
Rule from owner: **which contact to KEEP must be asked each time** (prefer GajiHub-synced /
company-name master); archive only when hutang/piutang=0.

**API DEDUP capability (DESIGNED 2026-08-22, superseded by the archive method above) — owner
asked to do dedup via Kledo API since volume is high.** Verified via OpenAPI spec at `https://pthadimulyautama.api.kledo.com/docs?format=json`
(1991 paths): `PATCH/PUT /finance/invoices/{id}` & `/finance/purchaseInvoices/{id}` change
`contact_id`; `PATCH /finance/invoices/executeMassPatch` (+purchaseInvoices) = bulk; `PUT
/finance/contacts/{id}` sets type_ids; `DELETE /finance/contacts/{id}` (contact has
`deleted_at` ⇒ SOFT-delete, recoverable); `?contact_id=` filter works. **Real volume: ~161
transactions to reassign across the 14 groups, dominated by #539 "Umar Arifuddin 2" = 120
sales invoices → #515; #1018=14 beli→#1017; #814=8→#550; rest 1–4; #1067/#1113/#1106 truly
empty (delete directly).** DESIGN = a SEPARATE, manually-run, supervised tool (agent stays
READ-ONLY — do NOT wire write into the agent toolset). Per group, 3 phases: ① dry-run
(enumerate all txns, preview, no writes) → ② human confirm (PILOT 1 group first) → ③ apply
(set keep types FIRST, reassign txns [massPatch for #539], verify delete-target 0 txns,
DELETE contact, audit-log every change). Safeguards: dry-run default (--apply to write),
pilot-1-group, reversible (re-patch / soft-delete), full audit, **Tahap-0 = verify token
has WRITE scope on 1 safe reversible action (403→stop, ask for write token)**, stop on
locked/posted txns. Design doc: scratchpad `dedup_kontak_api.html`. Build plan: T0 scope
check → T1 dry-run reporter → T2 --apply executor (pilot) → T3 rest. STATUS: awaiting
build approval.

Related: [[kledo-integration]], [[penggilingan-beras-project]], [[kantor-arsitektur-terintegrasi]].
