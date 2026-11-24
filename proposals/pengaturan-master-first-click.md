# Master Pengaturan: two-route native structure handoff

Scope: only `/pengaturan/spesifikasi-beras` and `/pengaturan/hasil-samping`. Initial read-only audit source `88560d962f61f027c9b2c77cbda3d19f53104384`; implementation began at Root `277e337a30dd85afdf1c2e30a1a2b5123200a335`, with Root integrating unrelated shared navigation work concurrently. This family owns its new helper/template/adapter/compiler/runtime/tests and the two native GET `lihat` presentation deltas. It does not edit shared `pengaturan.py`, Pengguna, Console, identity/core/vendor, transaction/packing writers or native form templates.

## Actual source and guard

Both native `lihat` routes depend on `butuh_admin`. Its actual predicate is `akun.is_admin` after native `butuh_akun`, not a new role list. The family reasserts the exact same request-state account, actual Boolean `is_admin`, forced-password false and no portal before rendering an inert shape or optional private presentation metadata. Denied/unknown checks decline; the native dependency remains the authority.

The GET gate admits only bare declared paths with no query, after the native dependency. Explicit shell or document navigation may render structure before native `halaman` reads master records/usage. `X-Pindah: 1` always takes the original native data path, even when `X-Kerangka-Halaman: 1` is inherited. Normal unnegotiated GET, feedback/query/deep action and all POST remain native. `halaman` and `ubah` bodies are unchanged (pure AST comparison). No DB query or fake master/account object is added to the shape.

Spesifikasi native data reads `master.rincian(pemakaian=True)` including usage/FK/log probes, default reference and stored QC-reference metadata. Hasil Samping native data reads current configured types and usage across actual schema columns. These reads decide record status and which edit/delete/activate/default operations are valid. The structure does not guess any result or make a record action available before fresh HTML.

## Native pending shape and hydration

The native heading, Operational breadcrumb, add-details summary, field labels and add button exist before data. Inputs/selects are disabled, unnamed, valueless and explicitly pending, and there is no form/POST/control ID for an actual master record. The list remains native card layout with a pending region and unread count, never a fabricated table, empty result or zero. There is no invented active/default/used state or master record. Hasil Samping's stock-form options remain pending until the native GET, avoiding an implied selected configuration. Existing add summary stays expandable; no edits can be made before fresh data.

`pengaturan-master-native.js` declares only the two exact bare same-origin addresses to `PADI_BACA_NATIVE`. Retry reads GET only; after success native HTML/assets restore the original fields, forms, record versions and native controls. Retry focus returns to the read content rather than a mutation field. The family does not add/remove/change `beforeunload`, dirty-draft, native validation or save semantics. Native `pengaturan-isian.js` is activated only with fresh native HTML, as before; no transaction controller is adopted by the shell.

## Root-owned public wiring

Root should register the versioned public asset `/static/kerangka-pengaturan-master-ui.js?v=CAP` and a single escaped inert private host:

`<script type="application/json" id="padi-pengaturan-master-kerangka" data-cap="CAP" data-konteks="context">…</script>`

Payload comes from `await pengaturan_master_kerangka.susun(request, akun, registry=registry)` and contains exactly `{versi:1,cap,konteks,sesi,sumber,allowed:true}`. It has no master values, user/tenant IDs, roles, config, credentials, counts or record identities. It is only returned for a GET with the actual current eligible account; no metadata means decline. Root must serialize with the existing safe private JSON mechanism/no-store handling, not copy it to public assets/storage or derive eligibility from a URL. Do not auto-adopt any other Settings/User routes.

Factory signature:

`window.PadiKerangkaPengaturanMasterUI.buat(target, baseHTML, context, CAP, sessionToken)`

It returns `null` for native fallback or `{versi:1,alamat,konteks,cap,html}`. The target is one of the two declared bare paths; an address is correlation, never authorization. Current and detached-base frame/main/session must be unique, contained and match exact context/CAP/session; current address must match the live document. The private host must be unique, connected, exact-schema, same context/CAP/session/program source and explicitly allowed. The program has two source-only native variants and interned CSS/JS pools. Missing/old metadata, query/actions, portal/editor source, malformed base, duplicate/missing frame, outside-frame session/main or invalid shape/control declines. No POST, storage or master lookup is performed.

Root owns global provider/metadata/head wiring and final shared-chrome behavior. This commit does not edit any of those files. Shared SDK/chrome remain a concurrent Root concern; the generated package is a review artifact and must be regenerated against Root's final frozen SDK before final runtime/CI gates.

## Evidence and remaining gates

26 Python pure/source/template tests and four Node pure/DOM-protocol tests pass. Compiler runs with all `app.*` imports forbidden, checks the two native layouts/unknown fields/no forms, interns program pools and checks generated freshness. Native caller dependency and unchanged writer/heavy-reader ASTs are checked. Node checks explicit addresses, exact allow metadata, stale context/CAP/session/source, containment/address and retry focus. JS syntax and diff checks pass. No PostgreSQL, browser, HTTP, account creation, writer, remote/CI, production or deploy test was run by this child.

Root sequential gates still required: actual allowed/denied role/product/session namespaces, first-click provider before HTML, early document vs native data negotiation, native data success/empty/error/retry, native forms restored, delayed/stale navigation and drafters, 390px/desktop geometry and keyboard, zero POST during navigation/loading, cold/warm upgrade/rollback and final generated input freshness. Native record usage and packing configuration must be unchanged. This is not proof that all Pengaturan/Pengguna pages are complete.

## Remaining inventory (not adopted)

- Pengguna staff `/pengguna`: native `butuh_super`, including its narrowly defined legacy recovery exception (`is_admin`, no master company and no active Super). `_muat` loads all accounts/users and at most 50 active people without a login. Native sections: Daftarkan orang baru, Buatkan akun, Akun yang ada. Role/new-person defaults, generated initial password and row-level actions need native fresh data; do not infer Super from menu visibility.
- `/pengguna/{akun_id}`: native account/user lookup plus `_jumlah_admin`, returning the list with error if missing. Name/username/role/device fields, reset and last-highest warning depend on actual record/count. A detail first-click proposal needs positive native resource provenance or a matching fresh light guard; a numeric URL is insufficient. Writers remain out of scope.
- `/pengguna/pelanggan`, `/kontak`, `/{account_id}`: separate portal-admin family with strict `super_only` and no recovery fallback, 20-row table, account ownership and contact eligibility/autocomplete. Do not merge this guard or credential forms with staff.
- `/pengaturan/peran`, `/akses`, `/sebab-berhenti`, `/mutu`, `/kledo`, `/sistem`: actual caller scope flags/selected warehouse/action policy and configured values required; no policy guesses here. Existing Akun/index/Sesi are separate adopted families.
- `/pengaturan/gudang`, `/silo`, `/alat`, `/mesin`, `/jenis-proses`, `/mesin/{id}`, `/dryer/{id}`: native `butuh_super`, current warehouse/line/dryer/silo content/usage and resource redirects required. Existing form/draft/operation-key guards must survive. Company/platform/Console/recovery authority families stay excluded from this child.
