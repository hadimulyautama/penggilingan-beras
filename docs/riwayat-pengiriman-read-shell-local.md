# Final Shipping journey: local read framework handoff

Implementation owner: Flow family child. Integration, global head/provider and
serial native runtime: Root. This batch is **not runtime-verified, globally
wired, CI-approved, or released**.

## Exact scope and original guard

Only GET `/barang-keluar/{id}` for an actual selected native record whose
status is `selesai` or `batal`, with the default journey interpretation.
The original handler remains `layar_keluar.halaman_barang_keluar`, with its
`butuh_akun`, positive `pengiriman_bertahap.boleh_baca` predicate (financial
reader or native G2 Operator), namespace and native resource lookup. Missing
records still reach the original 404 before shell rendering; G1 remains denied.
No new route, server permission, SQL, schema, business rule or writer is added.

Portal is deliberately declined by both early builder and catalogue. Its
native `allowed_ids`, item `jasa_ids`, grouped-ticket/customer restrictions and
reader-specific DTO remain unchanged. A presentation flag is never authority.

The existing eligible-document `svc.daftar(...transaksi_id=id,batas=1)` tuple is
reused after the active shell declines. The DB connection has already closed;
the new helper reads only loaded scalar/relationship dictionary entries, and
declines if required state is missing. It never triggers an ORM property/lazy
query. The fallback path reuses the same `dokumen_baris`; the native full
`riwayat_kiriman.baca` is not called by the shell or catalogue and still runs
once when the fresh native GET is requested.

There are **zero new explicit row or per-card SQL calls** in this family.
Existing native predicate and `konteks_kerangka` navigation/context preparation
are reused. Their actual total query cost and connection lifetime still need
Root's serial runtime measurement; pure tests do not establish endpoint cost.

## Native shape and genuinely unknown data

The app-only template follows `riwayat_kiriman.html` and native
`_riwayat_kiriman.html`: optional permitted review control, native shipping
navigation, history Back, journey hero, native status headings, customer/item
region, weighing, journey summary, examination history and permitted correction
history. All controls that require data are disabled; only Back/retry can act.

The title uses actual loaded `kiriman.no_polisi` or `rec.no_polisi`, then code,
exactly as the native journey; the desktop crumb uses native
`breadcrumb.susun` + `_breadcrumb.html` (Beranda / Barang Keluar / actual code).
The mobile title is `Riwayat pengiriman · code`, and Menu/Back follows the
native base/header context. The history Back retains native q/status/date/
cursor filters and `#judul-riwayat-keluar`.

One important original contract is preserved: the final handler supplies
`boleh_perbaiki`, not `BOLEH_PERINTAH`. Native top navigation consequently has
disabled Barang Retur even for the internal Admin journey. This batch does not
silently make that link active. Review metadata comes from the actual original
list `BOLEH_PERINTAH` flag, not a role-name mapping.

Customer/member/item counts, weight totals, return balances, audit, verification
method, ticket version and grouped members are **unread**, not zero or empty.
The placeholder customer region has no `.rk-customer`, `data-item`, customer ID,
item ID, invented name, ORM, row, quantity or return/ledger allocation. A shared
journey may contain other members in different statuses; its journey status
remains explicitly unread instead of assuming all members have the selected
record's status. A native fresh read alone supplies real groups and emptiness.
The weighing comparison label also waits for native legacy/current provenance.

## Private catalogue and public package

`riwayat_pengiriman_catalog.pasang` decorates only the actual native parent
`/barang-keluar` list response. It uses its original `riwayat` DTO and exact
visible history row/code/href, with a maximum of 50 entries, no extra lookup.
No catalogue is fabricated for the journey itself: it has no native default
journey-to-journey tab links. Metadata carries only bound code/title/status and
layout flags; no balance, actor, quantity, audit, customer or item payload.

The private host is `#padi-riwayat-pengiriman-catalog`, no-store, session/context/
CAP/current-source/hash-bound. Client proof independently requires computed
visibility of that exact original history row and code/link in the current
main. Source changes, hidden/inert links, wrong identity/package or unknown
targets decline to native; no role/regex grant is derived client-side.

Public compiler: `scripts/buat_kerangka_riwayat_pengiriman.py`; output
`kerangka-riwayat-pengiriman-ui.js` + `.meta.json`; runtime factory
`PadiKerangkaRiwayatPengirimanUI.buat`. Public data contains only `read`/`review`
layout variants, native CSS/read-only adapter and native compiled chrome.
Native source/template/compiler inputs are hash-pinned. `riwayat-pengiriman-
native.js` mounts existing `PADI_BACA_NATIVE` for same-URL fresh GET with
`X-Pindah:1`/`X-Kerangka-Halaman:0`, stale generation/context/session checks,
GET-only retry and quick navigation cancellation. After hydration, deeper
editor/document/return/audit links stay full native (`data-utuh`), without
adopting their controllers or changing their guards.

Root still needs the scoped head asset + provider/prefix wiring. The bounded
`layar_keluar.py` edits are only early-final helper dispatch and post-native-
list catalogue decoration. No global registry/compiler/runtime file is edited.
Because the existing active Shipping compiler hashes `layar_keluar.py`, Root
must regenerate/check its affected active artifact during integration; this
child intentionally does not overwrite frozen active-family/generated files.

## Held inventory (not this batch)

- `?rincian_perintah=1` remains native `pengiriman.html` /
  `_pengiriman_detail_tab.html` with four native tabs. Final Admin also reads
  `verifikasi_pengiriman.baca` under the original saldo lock and activates an
  actual controller, so do not treat this as a static journey variant.
- `tab_detail`, unknown/duplicate/action queries (`buka`, `nilai`, `tiket`, even
  empty) are conservatively declined. Normal native behavior is preserved.
- `/barang-keluar/{id}/serah-terima` and `.pdf?unduh=1` remain native
  `serah_terima.detail` / `svc.pengeluaran`. Outbound needs native G2 predicate;
  portal adds resource/item/ticket-customer checks. HTML ready/unready and PDF
  409 readiness are real variants. Existing `rekap-jasa.css?v=CAP-serah1` would
  require a separate asset-version review before native-reader adoption.
- `/muatan`, `/selesai-muat`, `/verifikasi-pengiriman` and aliases are native
  read pages that embed writer controllers; `/perbaikan` embeds undo,
  `/koreksi-selesai` and returns embed held correction/receipt workflows.
  None are adopted here. PDF, Transfer, PACK, RETUR and NET writers stay out.

## Verification and next acceptance

Only pure Python/Node tests and reproducible package generation are allowed in
this child turn. They prove validation, no-value/inert structure, loaded-state
decline, native chrome extraction, private visible-link binding and strict
package/session/source contracts. They do not prove real role scope or browser
hydration. Root must pin the integrated source, then serially test Admin/G2/G1,
390/1280 in both approved engines, actual final list links, separate document
and delayed native reads, grouped/mixed statuses, true missing/empty records,
error/retry, Back/filter preservation, stale completion/no POST and all-table
fingerprints. Preserve old held-action behavior and check query counts before
making any release claim. No production action, CI, remote or deployment here.

Local result at freeze: **48 Python pure tests + 6 Node tests passed**, no skip;
the generated package `--check` passed (50,945-byte JS, 2,425-byte manifest).
These results cover the new family only; no old runtime suite was rerun.
