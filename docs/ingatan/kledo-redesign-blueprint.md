---
name: kledo-redesign-blueprint
description: "Approved redesign: mill=physical/process authority, Kledo=money authority; one event one record, bridged via Kledo write API; phased plan"
metadata: 
  node_type: memory
  type: project
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-09-01T03:41:46.310Z
---

Owner (2026-09-01) decided to overhaul the mill system so it CONNECTS to Kledo and stops
DUPLICATING it. Approved direction (blueprint artifact:
https://claude.ai/code/artifact/1316c872-2c66-4e37-833c-fca8b4404ccd).

**Guiding principle:** Mill = authority for PHYSICAL & PROCESS (berat, rendemen, mutu, stok kg,
HPP operasional). Kledo = authority for MONEY (transaksi, utang/piutang, beban riil, jurnal,
neraca). One event recorded ONCE, then pushed/pulled via API — never re-typed.

**Source-of-truth map (owner confirmed):** Pembelian gabah/PK → born in MILL, pushed to Kledo.
Beban operasional → born in KLEDO, mill reads. Penjualan beras → mill→Kledo (later phase).
Supplier/pelanggan master → KLEDO (single master, synced down; tabel `suppliers` ganda to be
removed). HPP → HYBRID (mill computes operational per-lot; reconciled vs Kledo actual beban —
this settles the absorption-vs-direct-costing question). Nilai persediaan (Rp) → Kledo.

**Kledo WRITE confirmed available** (probe of OpenAPI, 1996 paths, via `railway run --service
penggilingan-beras` so KLEDO_API_KEY stays in env): `POST /finance/joinedPurchaseInvoices`
(buat tagihan beli), `POST /finance/invoices` (faktur jual; + `executeMassVoid` rollback),
`GET,POST /finance/expenses` (+approve/reject/revert), `GET,POST /finance/manualJournals`,
`GET /finance/contacts`. Current client (app/kantor/kledo.py) is READ-ONLY; base
`https://pthadimulyautama.api.kledo.com/api/v1`, Bearer KLEDO_API_KEY, spec at `/docs?format=json`.

**Phased plan:** (0) clean operational foundation — DONE-ish (timbang→HPP done this session;
customer master from Kledo type-3 started by commit 07be7b6, NOT my work). (1) NEXT: Kledo
write client + approval gate (usul→konfirmasi→tulis, like the agentic controlled-write). (2)
Push pembelian → joinedPurchaseInvoices, idempotent link `kledo_invoice_id` UNIQUE (mirror of
`timbangan_transaksi_id`). (3) Pull beban → HPP reconciliation. (4) Consolidate supplier master
(make `suppliers` a cache of Kledo, like customers). (5) Push penjualan → invoices.

**Controls (writing to LIVE finance):** idempotent unique link (no double-post), approval gate
(no POST without human confirm), void/revert not hard-delete, periodic reconciliation report.
Nothing implemented yet beyond the blueprint — Fase 1 is the next build when owner says go.
Related: [[no-redundancy-kledo]], [[kledo-integration]], [[hpp-costing-model]],
[[kledo-kontak-supplier-sync]], [[agentic-layer]] (controlled-write pattern),
[[timbangan-intake-integrasi]] (idempotent-link precedent).
