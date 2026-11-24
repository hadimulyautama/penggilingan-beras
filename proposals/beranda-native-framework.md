# Beranda: invariant native framework (local proposal)

Scope: canonical GET `/`, with no query. This is Home, not the warehouse views
`/gudang/g1` and `/gudang/g2`, not `/dashboard`, and not an invented `/beranda`
alias. Fresh data still comes from the native same-URL GET with `X-Pindah: 1`.

## Presentation and actual authority

`main.beranda` still executes `akun_opsional` and its unauthenticated redirect
first. The new shape decision precedes Home's collection/aggregate reads. It
requires that exact account in request state, a known actual view, no portal
context and no mandatory password change. It adds no permission rule. Unknown
state declines to the old native route. Action/feedback/filter query strings
also decline rather than dropping their effects.

Private metadata uses the existing server `sapaan_dan_tanggal` and the actual
view plus the navigation context Root already read. The displayed scope literals
match native `beranda.html`; they are presentation, never warehouse identities
or grants. `.susun` adds zero SQL. Direct documents use the existing
`konteks_kerangka` reference helper (existing feature/navigation/scope reads,
not zero SQL). It does not read Home jobs, stock, machines, silos or counts.
Native reference errors retain the old route's partial-failure behavior; an
explicit HTTP 401/403 is propagated.

The invariant greeting/header and Perlu perhatian, Sedang berjalan/Transit,
and Ringkasan operasional regions appear immediately. Unknown dynamic machine,
silo, warehouse cards, their cardinality, balances and action choices stay
explicitly unread. No fake DTOs, placeholder IDs, row counts, zeros or implied
empty state are supplied. This is not proof of complete dynamic-card first
paint. No actionable business control is advertised before native data.

## Root wiring interface (not owned here)

1. Load `/static/kerangka-beranda-ui.js?v={{ VERSI }}` as versioned public program.
2. After actual global navigation and private registry are ready, call
   `await beranda_kerangka.susun(request, akun, registry=registry, navigasi=navigasi)`.
   Only a non-None result becomes private JSON host `#padi-beranda-kerangka`
   outside `.bingkai`, with `data-cap` and `data-konteks` matching registry.
   Use existing safe JSON serialization/private-document policy.
3. Only exact target `/` invokes
   `PadiKerangkaBerandaUI.buat('/', decodeFrame(registry,'/barang-masuk'), context, cap, token)`.
   Null retains native navigation. Root must retain its final cap/session/CSP,
   frame-size, context and target validation. No registry-address alias.
4. The direct-document path is the bounded early call in `main.beranda`.
   The remaining native route is unchanged. `X-Pindah: 1` bypasses this shape.

The factory uses only a Root-bound BM prototype's invariant chrome, current
private greeting/scope and reviewed public layout. Content scripts are pooled,
not external unversioned downloads. Script/meta source pins include native Home
and base, its pure greeting code, view presentation, main route, compiler and
reader assets. Root must regenerate/check after integrating concurrent changes.
No server JSON-read stamp SHA is invented: native reader correlation is the
existing context plus exact target. It is not authorization.

## Failure, cancellation and verification boundaries

Shared `PADI_BACA_NATIVE` handles the sole optional same-origin GET, version/
session/address match, safe script/style activation, discard on route change,
retry and focused-input interaction. The local adapter does not POST, cache
private state, or write storage. Failure says unread, not zero/empty. Retry is
an explicit button and has accessible focus restoration to the native heading
only when the shared reader establishes current retry intent.

Owner pure checks: 22 Python and 8 Node contracts. These prove projection,
negotiation, reference passthrough, strict private/public binding, unknown-view
rejection, native route ordering, deterministic compiler and inert markup.
They do not prove browser layout, runtime SQL duration, real roles or live CI.

Required Root browser delta: Admin and legitimate Operator G1/G2 (and unassigned
view if fixture exists), desktop/390, click sidebar Home while HTML is held,
then separate GET-data hold; delayed/error/retry/stale navigation; correct actual
header and action activation after native data; no POST/mutation. Include cold/
warm PWA upgrade/rollback and invalid session. Do not claim all cards complete
from this invariant-region implementation. Dynamic layout height remains a
runtime measurement gap. Final official CI/release/Website gate belongs Root.
