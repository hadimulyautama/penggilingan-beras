# Portal native detail batch: active Giling and receipt only

## Owner / status

Owner: Flow portal subagent; Root is the sole integration/runtime/release owner. Local proposal only. No PG/browser/network/production execution was performed by this child. Existing seven-menu browser evidence is separate; this batch does not claim hosted or full portal acceptance.

## Exact bounded change

- `routes.read` stores the original public address **after** real `load_scope` and before the unchanged `native_request` clone. It is presentation correlation, never an authorization predicate. `require_customer`, `own_ticket`, `own_model`, native dispatch, redirects/404, transaction readers and action stripping remain unchanged.
- `render_customer` decorates only five already-rendered source template names **after** `read_only` and `tampilkan_detail`. All other templates immediately decline. There is no SQL or additional reader call.
- Catalog collection requires actual scoped `progres` DTOs plus matching projected card code, heading and href; or actual receipt rows plus ticket scope membership, projected ticket code, goods label and href. Legacy receipt rows with no ticket ID are not guessed. Current detail sources contribute only their actual same-resource native tab links, native H1 and native document title.
- The private inert JSON contains only identities/headings/links already visible in that response, with CAP/account/session/original-address binding. It never serializes ReadScope sets, quantities, owner/location/status, editable values or business forms. No new HTML/data/draft cache.
- Public compiled variants contain structure only: exact native customer tab labels, fields, blank values, read status and retry. Receipt tables and Giling result/QC log headers are visible before data. The latter arrays are extracted from literal columns in the real `proses_aktif` reader. Variant-dependent source groups, weighing mode and QC rounds remain unread, never fabricated.
- First entry from a source menu has only its actual visible detail href. Other resource tabs are visibly disabled with an unread-data reason until the fresh native response supplies their real hrefs. From a rendered native detail, existing exact tab hrefs are available. No speculative tab/pagination/resource URL is minted.

## API / Root wiring still required

Load `/static/kerangka-portal-detail-ui.js?v=<release CAP>` in the native portal shell. This child deliberately did **not** modify shell/controller wiring.

`window.PadiKerangkaPortalDetailUI.buat(exactNativeHref)` returns `{html,title,address,hash}` or null. `address` is the exact request address without the validated fragment; `hash` is only an exact Giling `#panel-<matching tab>`. `siap(exactNativeHref)` returns the same current private-catalog/visible-link validation result.

Returned root has both `[data-portal-native-frame]` and `[data-portal-detail-frame]`, `data-portal-address` for the request, and existing `[data-portal-read-status]` / `[data-portal-read-retry]` markers. All public structure carries its scoped hidden rule inside the root. The private catalog is copied only for that selected resource while pending; source provenance and current frame address must still match. Unknown addresses, stale CAP/account/session/program, mixed resource targets and unmatched links decline.

Root must extend factory fallback, adopted fresh-only behavior, bounded fragment handling and temporary-error/retry for this provider. Never globally allow fragments. Native data GET retains `X-Portal-Navigasi:1`, no-store and fresh guard; the seven-menu `freshDocument` binding continues to protect installation. Do not turn a rejected parser/catalog into an early 200.

## Pure evidence

- 24 new Python contracts pass, including actual native tab literal labels through the real pure customer projection; source/DTO/scope/link mismatch, foreign ticket, unsupported shape, malformed/action query, data-free compiler, unchanged caller ordering and no SQL.
- Focused combined run: **55 Python tests PASS** (`test_portal_detail_kerangka`, existing seven-menu structure and customer detail contracts).
- **3 new Node contracts PASS**; combined with existing seven-menu/router tests, **10 PASS**. No browser claim.
- Both compilers deterministic `--check`, Python compile, Node syntax and diff whitespace check pass.
- Existing Portal7 seven `variants` and `schemas` compare byte-for-byte equal to their pre-change generated content. Its pinned `routes.py` digest changed, so only program source/digest metadata was regenerated.
- New detail public program: 15,870 raw bytes / 3,957 gzip bytes (mtime zero). Existing Portal7: 41,754 raw / 7,241 gzip. These are package sizes, not latency measurements.

## Root owner acceptance recipe (not executed here)

Existing fixtures are sufficient; no new account/role/tenant type or reader stub is proposed:

- `tests/pg/test_portal_alur_hp.py::alur(pg, portal, catatan)` provides `paths['giling']` from a real active MillingProcess and `masuk_detail` from the real receipt ticket. Its actual linked source recipes retain native signed-in customer guards.
- `tests/pg/test_portal_transaksi_detail.py::transaksi(pg,portal)` supplies native GABAH_KERING/BERAS_PK receipt variants and customer B foreign rows. `test_portal_pelanggan::portal` supplies the existing A/B identities. They are customer ownership scopes, **not two company tenants**.
- Reuse the native customer HTTP/browser helper from `test_portal_kerangka_browser.py`, preserving actual X-Portal headers and actual signed customer cookies. Do not substitute the staff peramban or fake auth/data responses.

After Root wiring/all-source freeze, use one disposable approved PG run serially: A desktop1280/390 and approved Chromium/WebKit, click actual Giling and receipt links from native menus while HTML/native GET delivery is held separately. Assert exact persistent H1/title, four native tabs, disabled unread-only controls, native column/field structure before data; then fresh GET has original amounts/links. Click all four tab links after native data returns. Exercise 503/retry, quick destination change with late response, Back/deep link/refresh, and foreign B queries returning native404. Verify no POST, no writers/audit mutations, full fingerprint unchanged and cleanup receipt. Direct/cold deep URLs still perform the original native full read; this batch does not accelerate or bypass them.

## Explicit remaining inventory

This is **not all portal deep pages**. Deferred: active Sosoh (real material composition controls heading), dryer/pendinginan (real stage/location), Shipping (live vs completed layout and actual `cepat` columns), stock/PK bag variants (real DTO composition), history/QC, nota/documents/PDF and password/account documents. Receipt-related process links are not treated as a newly read Giling DTO. Rows beyond the bounded 50 active DTOs / native 25-ticket page and legacy receipts retain original navigation. No Transfer or held PACK/RETUR/NET business changes are included.

Next: Root wiring + exact native acceptance, then review this batch before any public CI/release. Existing all-pages release and website gates remain Root's responsibility.
