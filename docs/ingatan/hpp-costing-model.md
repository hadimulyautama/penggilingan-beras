---
name: hpp-costing-model
description: How white-rice HPP is actually computed in the mill system — it was material-only; penyosohan cost now added; milling-conversion (hpp_penuh) still not wired in
metadata: 
  node_type: memory
  type: project
  originSessionId: 7fd8aaef-abc2-49c5-b3ef-2dc65faf1113
  modified: 2026-09-01T02:35:13.444Z
---

Audit 2026-09-01 (owner asked "apa tidak ada biaya penyosohan?"). White-rice HPP =
[`hitung_hpp_beras`](app/penggilingan/inventory/finished_goods.py:274), computed per
penyosohan (polishing) process, flat across all grades:
`(biaya_PK + biaya_penyosohan + biaya_kemasan − nilai_byproduct) / total_beras_kg`.

**Key finding:** HPP was **material-only** — it absorbed gabah cost + packaging − byproduct
credit, but NO conversion cost. The PK entering Gudang-2 silo carries **material-only** HPP:
[`hpp_per_kg_pk`](app/services/transfer.py:85) = `_gabah_cost / output PK` (berat×harga, no
operasional). A full-cost path EXISTS —
[`production_cost`/`hpp_penuh`](app/services/costing.py:55) adds bongkar/pengeringan/operator/
tenaga_milling/listrik/rubber — but it's used ONLY in analytics.py (biaya_produksi_detail,
simulations), NOT wired into the real HPP. So milling conversion cost is reported but not
absorbed.

**DONE (commit c229aca):** penyosohan cost now added to HPP. Config (config.py, all env-
overridable): `biaya_penyosohan_per_kg_pk=100`, `biaya_tenaga_penyosohan_per_kg_pk=50`,
`biaya_transport_penyosohan_per_kg_pk=50` (basis = kg PK disosoh, crew SEPARATE from milling),
`biaya_operator_penyosohan=300_000` (FLAT per polishing process). Helper
`biaya_penyosohan_proses(total_pk)`. Marketing (`biaya_marketing_per_kg_beras=50`) is a
SELLING expense — deliberately NOT in HPP (belongs in Kledo P&L / a margin report).

**DONE (commit fdfc916):** milling-conversion cost now wired in. `hpp_per_kg_pk` (transfer.py)
uses `production_cost().total_penuh / output` (bahan + biaya giling) instead of `_gabah_cost`;
this hpp attaches to milling-origin PK entering the Gudang-2 silo → flows via wavg silo into
HPP beras. PK BELI LUAR is untouched (HPP = verified purchase price; not milled), but still
gets penyosohan cost via hitung_hpp_beras. `_gabah_cost` + 3 orphan imports removed.
**So all three conversion costs (drying + milling via hpp_penuh, penyosohan) are now absorbed
into white-rice HPP.** Owner still to settle: absorption (per-lot, now the default) vs direct
costing (overhead in Kledo P&L). Flow diagram artifact from this session shows the pre-wiring
state — offer to update it. Related:
[[penggilingan-beras-project]], [[no-redundancy-kledo]], [[kledo-integration]].
