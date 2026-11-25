# Parent facility first-click — source-only handoff

Owner: Flow remaining-pages child; Root is the sole integrator/runtime owner.
Baseline: `cafdb911c33a422b984c078c03b72ed568d82912`.
Native empty-state delta: `c081c2b` (separate, 9 pure tests).

## Scope and native evidence

Only bare `/pengaturan/gudang`, `/pengaturan/silo`, `/pengaturan/mesin`,
`/pengaturan/jenis-proses`. Query/error/success aliases, detail/dryer routes,
POST and direct documents are NOT adopted here. Direct cold-document reader
cost is unchanged. No handler, native dependency, writer, configuration,
controller, CSRF/operation key, role or database schema is changed.

Actual same dependency `Depends(butuh_super)`:

| Target | Existing caller | Existing native shape |
| --- | --- | --- |
| Gudang | `pengaturan.halaman_gudang_pengaturan` → `_halaman_gudang` | `gudang_pengaturan.html`: title Pengaturan gudang/H1 Gudang, Daftar gudang, Tambah gudang, Nama/Alamat/Latitude/Longitude |
| Silo | `pengaturan.halaman_alat` → `_halaman_alat` | `silo_pengaturan.html`: Silo gabah/Silo bahan penyosohan, Gudang (gabah only), Nama silo baru; NO capacity field |
| Mesin | `fasilitas.daftar` → `halaman` | `fasilitas.html`: Mesin & line produksi, groups read later, Tambah mesin / line and Tambah dryer, actual native field labels |
| Jenis proses | `fasilitas.daftar` → `halaman` | `fasilitas.html`: Jenis proses, native execution-support warning, Tambah jenis proses, Nama/Kode/Aktif |

The precise native `butuh_super` predicate, including its narrow recovery
semantics, remains owned by `security.py`. No Admin flag is substituted.
The immutable receipt pins native functions and original controllers; its
assertions use AST hashes, not current HEAD or Git commands at test runtime.
A negative control verifies that changing the native guard is detected.

## Root wiring contract (not performed by child)

1. Reuse the actual **same request** local result already obtained from
   `pengaturan_alat_kerangka.susun`, not reconstructed request/DOM data.
2. Call synchronous
   `fasilitas_parent_kerangka.susun(request, akun, registry=registry, guarded_alat=alat)`.
   It accepts only the exact Alat descriptor shape, current program source,
   matching CAP/context/session, actual request-state account, GET,
   no portal and no forced-password state. Unknown means no descriptor.
   It performs no account/role/resource queries and does not call the guard
   again. The internal guard-result argument must never be populated from
   HTTP/client flags. A presentation descriptor/URL is not authorization.
3. Host the resulting JSON privately as `#padi-fasilitas-parent-kerangka`,
   with `data-cap` and `data-konteks`. No role, tenant, record or business
   values are serialized. Preserve the original private/no-store policy.
4. Include versioned `kerangka-fasilitas-parent-ui.js` via Root metadata/head.
   Provider is `PadiKerangkaFasilitasParentUI.buat(target, baseHTML, ctx, CAP, token)`.
   It accepts only the four bare targets and exact current frame/address,
   CAP, context and contained session. It checks the current connected private
   host and source digest. Missing/mismatch returns null/native fallback.
5. Fresh HTML remains sameURL read-only GET with `X-Pindah: 1` through
   `PADI_BACA_NATIVE`; this keeps original native guards, data reads, scripts
   and error responses. No new endpoint or shell-on-X1 convention.

Pending roots have `[data-fasilitas-parent-kerangka]`, not native
`[data-pengaturan-form]`/`[data-fasilitas]`, no form/name/value/CSRF/operation
key or native transaction controller. Boolean values use neutral mixed state,
never a fake default. Only an inert fixed add-form shape is shown; per-record
edit/delete actions remain absent until actual native records are read.
Status and GET-only retry are explicit. No storage, POST or auto-save.

Factory removes the prior private line catalog; pending parent has no native
actual row links. The existing line-detail provider cannot adopt guessed rows.
After fresh native parent HTML the original decoration may emit a new catalog.
Root must retain native capture-phase draft guards/beforeunload before its
navigation handler: this family installs no listener to bypass those guards.

## Native empty-state and frozen line program

`fasilitas.html` has one include of `_fasilitas_parent_empty.html`.
The partial uses actual collections, only with no error, input draft,
line detail or dryer detail. Empty Mesin means BOTH `lini` and `dryer` are
empty; empty Jenis means `jenis` is empty. Populated/error/draft/detail
responses are unchanged. Gudang/Silo already have native empty messages.

Root owns regenerated **existing line** program after this native input
change, avoiding concurrent compiler output writes. Child did not modify
line runtime/helper/compiler/tests. The changed native template is an input
pin of that line compiler; its pending components need no layout change.
Root should record source/input digest and byte/diff comparison after regen.

## Pure verification and open runtime gates

41 Python tests (9 empty + 32 scope/shape/source/compiler), 6 Node protocol
checks pass. Compiler is source-only/no app import and deterministic;
new public program 39,831 bytes, metadata 2,452 bytes at this freeze.
No PG, browser, real account/role, remote, CI or production action was run.
These results are not UI geometry, authorization runtime or all-pages PASS.

Root runtime nodes, with safe disposable fixture only:

- Super and actual narrow recovery where allowed; normal Admin/Operator
  must not receive this descriptor or gain links/actions. Forced-password,
  invalid session, portal and scope changes stay native/default-deny.
- Four menu first clicks with HTML held separately from GET data; desktop
  and 390 px, heading/breadcrumb/back/field geometry vs native.
- Data success/true empty/read error + GET retry; data values/options only
  after authorized native data. Fresh original controllers activate once.
- Abort/late response and rapid parent-to-parent/line navigation; stale
  catalog/old frame/session cannot replace current scope.
- Existing dirty native settings input prevents navigation using its native
  guard; cancel/confirm semantics and keys are not silently changed.
- Fresh empty Mesin/Jenis native messages do not appear on error/form-draft,
  existing row, line or dryer detail. Normal edit/save flow remains native.
- PWA cold/warm/upgrade/rollback assets after Root's final aggregate compile.

No release readiness is claimed. Root owns global integration, runtime
coverage, final regeneration, official CI, rollback and eventual website gate.
Remaining direct-document waiting and per-row identity-dependent controls
are explicitly held to native fresh reading, not represented as completed.

## Fixed Root prototype contract (source correction)

Root provider passes its decoded `/barang-masuk` registry frame, not a snapshot
of `/pengaturan`. Factory therefore validates the parsed private prototype's
address as exactly `/barang-masuk`, retaining unique frame/main/session
containment and matching CAP/context/session. Separately the **current live
document** must still match `location.pathname + location.search`, and the
connected private family descriptor is checked there. The target remains one
of the four allowlisted bare URLs; its root/frame address and stamp are set
to that destination before SDK mount. A different prototype address, stale
identity or uncontained session declines. This changes no server target guard
or native GET. Browser acceptance barriers are unchanged; source checks are
not a runtime PASS.
