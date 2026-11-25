# Native process PDF HTML viewers: local handoff

Owner: Flow family child. Root owns head/provider wiring, package regeneration,
serial PostgreSQL/browser acceptance and any later release decision. This batch
has **no runtime/browser proof, official CI, hosted verification or release**.

## Scope and unchanged native authorization

Only HTML GET `/riwayat-{giling,sosoh,pengeringan}/{positive_id}/laporan`, with
no query. No Transfer, binary `.pdf`, PDF composer, writer, portal, new role,
grant, model, database query, route or business rule is adopted.

The original viewer functions remain authoritative:

- `layar_riwayat.halaman_laporan_giling`: `butuh_akun`, original
  `_izin_lokasi(MillingProcess,id)`, `_is_jenis_operator('penggilingan')`, then
  the original scalar process lookup and completed-status 404.
- `layar_sosoh.halaman_pdf_riwayat_sosoh`: original location check,
  `_pastikan_akses_sosoh`, scalar lookup and `status == 'selesai'` 404.
- `layar_riwayat.halaman_laporan_pengeringan`: original location check,
  `_is_jenis_operator('pengeringan')`, scalar lot lookup and completed-cooling
  404. Binary endpoints retain their original, separate authorization/read.

There is no new early document response. Direct native documents already have
their complete controls before binary loading; this batch adds the first-click
structure before that HTML response arrives, then reads the ORIGINAL viewer
through same-URL `X-Pindah:1` / `X-Kerangka-Halaman:0`.

## Actual parent detail metadata

The three successful native detail handlers decorate their response only after
render. `k.id/k.kode` (Giling/Sosoh), or `d.lot_id/d.kode` plus
`d.laporan_tersedia is True` (Dry), are already read by their original reader.
The private catalogue verifies the actual matching header `.rhs-code` and
visible `.rhs-actions > a` report link, existing frame/main/session, CAP,
context, current source address and its digest. There are no per-row SQL calls,
model construction, fabricated actor/DTO, outputs, weights or new grant.

One bound entry is emitted at `#padi-proses-pdf-catalog`, with kind/id/code/exact
HTML report target; source program assets are hash-checked. Unknown/duplicate/
action source queries, another resource/code, hidden links, absent native
wrapper or portal context decline to native. Client selection independently
requires the same current computed-visible native link and code, session,
context, CAP and source; a public route pattern alone never grants access.

## Native structure, navigation and browser contract

`scripts/buat_kerangka_proses_pdf.py` renders the actual block `isi` of
`laporan_giling.html`, `laporan_sosoh.html`, `laporan_pengeringan.html` with
code/URL placeholders only. There is no fake ORM, record, account, count or
weight. H2, Back label/href, share/download placement and iframe title/style/
height come directly from those native templates. Public variants never run
the native share-fetch program or set an iframe src. Share remains disabled;
Download has no href and explains its pending state until fresh HTML arrives.

The full breadcrumb is compiled with native `breadcrumb.susun` and
`_breadcrumb.html`; the intermediate native PDF parent is **Detail proses**,
because the viewer's original context supplies `kode`, not `breadcrumb_detail`.
It must not be silently renamed to the code. Mobile title remains `Laporan
{code}` with the native Menu control.

The native `LAPORAN_NAV` control structure is reused from the current same-family
detail DOM, rather than guessed from a role. Its `.laporan-isi` is emptied in a
clone, then replaced with the viewer structure. Existing native controls,
allowed paths and selected process remain; only the clone's initialization
marker is reset and its pinned native CSS/controller are rebound. Record-
dependent guide/print controls are disabled while pending. Source wrappers or
selection that do not match decline. An iframe-bearing base is conservatively
declined before parsing, avoiding resource activation from another cached page.
This restriction is a native fallback, not evidence that all entry variants
have passed runtime acceptance.

Root wiring: `PadiKerangkaProsesPDFUI.buat`, asset
`kerangka-proses-pdf-ui.js`; wrapper `[data-proses-pdf-kerangka]`, retry
`[data-ppv-retry]`, native status `#status-bagikan`. Root head/provider/global
registry/runtime are not changed by this child.

## Explicit X1 iframe deferral

Native source has two binary requests: iframe navigation plus the original
share program's fetch. That is a **source baseline, not a measured browser or
production count, and not a new optimization claim**. A pending iframe followed
by another native iframe, or HTML parser resource loading, must not add reads.

After all original viewer guards/read/render, only explicit X1/0 HTML responses
receive this presentation delta: the one exact original `src="...laporan.pdf"`
attribute becomes `data-ppv-src`, with its same HTML viewer address. The original
inline share script and download URL remain byte-identical. A scoped adapter is
appended. Direct documents, other negotiations and binary endpoints are
untouched. This is a surgical byte replacement after parsed structural checks,
not wholesale HTML normalization or a substitute for permissions.

`proses-pdf-native.js` activates that exact original URL once after fresh content
is installed. The native share script still performs its original fetch once.
Activation requires current address/CAP/context/session, connected content and
frame, matching source URL, and no existing src/activation marker. A stale
navigation or detached subtree cannot activate it. Self-boot covers a generic
native X1 install; its later afterInstall callback is idempotent. Neither this
adapter nor public structure fetches/caches a PDF, changes its data or submits.
Unexpected response structure declines the surgical decoration; Root must
test parser/request behavior on the exact package before adoption.

## Separate bounded connection-lifetime fix requested by Root

In `detail_riwayat_pengeringan`, the optional completed-history helper is moved
after unchanged native location/role checks and before the outer `SessionLocal`.
The helper already independently checks completed/scoped source. Active/missing
cases decline to the original redirect/404; X1 declines early without extra
helper queries. No optional second-session metadata preparation remains inside
the outer lot-reader session. A pure AST test verifies this ordering; runtime
query/connection proof remains Root's task.

## Verification and remaining gates

Local only: **31 new pure Python tests + 15 existing native PDF unit regressions
= 46 PASS; 8 Node tests PASS**. Generated package `--check` passes: JS 49,962
bytes, manifest 2,480 bytes. No PG, browser, listener, CI, remote or deployment
was run by this child. Tests establish native presentation equality, direct
document byte preservation, narrow X1 deferral, original share script, guards/
proof formats, source binding, activation-once/stale/detach rejection and the
connection source ordering. They do not prove real role scope or HTTP counts.

Root must regenerate affected History/Giling/Sosoh packages because their
tracked compiler inputs include the two changed family handler modules. Then
run serial native fixture acceptance in both approved engines at 390/1280:
actual native detail report link; delay HTML separately from PDF; native
header/nav/body control parity; request counts baseline versus candidate,
**zero binary requests before fresh HTML and only the native two after**;
error/retry and pending navigation; wrong role/resource/not-completed native
denial; no POST and unchanged table fingerprints. Include warmed assets/PWA
upgrade/rollback and an old/base document with an iframe. Do not relax native
checks or claim PDF correctness/performance merely because the shell appears.
