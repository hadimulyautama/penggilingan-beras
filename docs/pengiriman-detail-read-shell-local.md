# Active shipping detail: local READ adoption

Scope starts from Root `277e337a30dd85afdf1c2e30a1a2b5123200a335` and stays on
the same Root branch/worktree. Root owns global head/registry/provider wiring,
native PG/browser proof, official CI and release. This proposal is not runtime
or release GO.

## Exact native family and held paths

`layar_keluar.halaman_barang_keluar` serves `/barang-keluar` and
`/barang-keluar/{transaksi_id}`. Its existing `butuh_akun` and positive
`pengiriman_bertahap.boleh_baca` precede the actual `svc.daftar` row/items read.
The latter predicate is financial-read OR G2 Operator, not every Operator.
G1 can use the distinct loading workflow; this proposal gives G1 no detail grant.

- `perintah` / `dimuat`: `pengiriman.html` / `_pengiriman_detail_tab.html` has
  Ringkasan, Barang, Tiket & bobot, Retur & riwayat. This is the adopted slice.
- `selesai` / `batal`: default `riwayat_kiriman.html` uses the separate
  `riwayat_kiriman.baca` journey DTO, shared-armada/return balances and historical
  corrections. It is held. `rincian_perintah=1` is also deliberately declined.
- Portal, action/deep URLs (`buka`, `nilai`, `tiket` even empty), return,
  correction and perbaikan routes stay native.
- `/muatan` and `/barang-keluar/{perintah:int}/muatan`: native `muatan.halaman`
  allows `boleh_catat` OR financial-read, reads `papan_selesai`, and renders
  `_lembar_muatan.html` with an actual transaction editor. `boleh_catat` means
  Super or non-financial active G1/G2 Operator; ordinary Admin reads only.
- `/selesai-muat` and its nested alias use the same actor predicate,
  `papan_selesai` DTO and editor. `/verifikasi-pengiriman` and its nested alias
  require financial-read and `verifikasi_pengiriman.baca`, which holds the
  existing balance lock and returns the native pemeriksaan/armada DTO.
  All three action workflows remain held; no editor/writer is adopted here.

## Resource, connection and fresh-data boundary

For eligible document READ only, the exact existing `svc.daftar(...,
transaksi_id=..., batas=1, **customer_scope)` executes once in a small session.
Missing rows keep native 404. That session is closed before optional navigation
metadata or the repeated positive read predicate can obtain another connection.
Only already-loaded scalar record/item fields are used for the shell; no ORM
relationship is dereferenced. If shell construction declines, the original
row/items tuple is reused by native fallback. The original select-in `kiriman`
loader remains part of `svc.daftar`; no lookup, SQL, ordering or status rule was
replaced. Exact query count and PG lifetime still need Root runtime proof.

X-Pindah:1, action queries and portal skip that document pre-read branch and
retain the original reader. A successful early document intentionally requires
a second fresh HTTP GET, whose native guard/row/status/readers are unchanged.
This is not a cache of the first row. No new database read occurs per catalog
entry. `konteks_kerangka` and the positive read-predicate recheck have their
existing metadata/permission cost on the early document; it is not claimed zero.

`pengiriman_detail_catalog` consumes actual native `kartu` DTOs after rendering.
It binds only active records to exact native visible list hrefs or four native
detail-tab hrefs. Private metadata contains code/status/known boolean layout
flags and authorized disabled action labels, not customer names, weights,
item IDs, fingerprints, balances or actor IDs. It is bound to current source
address/hash, CAP, context and session, inside the current page and no-store.
Native list >50 active entries declines the optional catalog; it is not sliced.

The public compiler emits two native layout flags (`read` / `command`), not
roles or grants. The runtime also requires the current native visible source,
computed visibility, exact href and private metadata. Pending-tab continuation
is restricted to the original authorized record and identical read filter
scope. Routes/IDs alone cannot construct a frame.

## Local integration and release limits

Owned compiler: `scripts/buat_kerangka_pengiriman_detail.py --check`.
Root integration point: public `kerangka-pengiriman-detail-ui.js?v=CAP` in the
head and `PadiKerangkaPengirimanDetailUI.buat` in the existing private provider.
The family caller itself installs only the document helper and private native
DTO catalog. No shared registry/navigation/compiler file is edited here.

The app-owned `_pengiriman_detail_tab.html` changes only fixed CSS/JS cache
keys (`v=2` / `v=1`) to the release CAP; otherwise the fresh native reader would
reject those assets as a version mismatch. Source renderer/row markup stays
otherwise unchanged. Read hydration does not copy footer `aksi.js` into a new
controller: explicit action/editor links are kept as `data-utuh`, so those
held paths load their existing native document/controllers after user action.

Pure tests cover structure, conservative queries, guard order, missing/final
fallback source boundaries, schema/provenance rejection, pending continuation,
computed-visibility predicate, native action links and generated allowlist
parity. They do not prove native role/tenant SQL, browser layout, current native
DTO parity, two-tab races, status changes, cold/warm cache or any transaction.
Root must test those on the exact integrated fixture before a release decision.

## Native chrome parity delta after Root review

The compiler now imports the pure authoritative `breadcrumb.susun`, renders
the existing `_breadcrumb.html`, and captures the native menu/back fragment
from `base.html`. Both are source-pinned compiler inputs. Runtime binds only
the verified code through textContent and the private native navigation hrefs;
it does not compose a shorter breadcrumb or invent a header Back control.

Native three-way return behavior remains distinct: the content link can return
to Pekerjaan or another allowed source; desktop breadcrumb goes to its actual
Barang Keluar parent with the native filter query; the mobile header is Menu by
default and only becomes Back when native render_laci's konteks_aman supplied
kembali_kerja. Private per-entry navigation is derived from the actual native
response context and target using the native breadcrumb policy, so query and
code binding do not rely on client role/route guesses. Pending tab reuse cannot
change that entry's read filter scope. Historical/editor/return coverage and all
runtime gates remain held as described above.
