# Shipping detail: owner acceptance handoff

Status: prepared for the integrator; **no PostgreSQL or browser execution in
this handoff**. This is implementation-owner acceptance, not scheduled or
independent QA, official CI, a PWA proof, or a release recommendation.

## Source and execution contract

- Shipping product: `714115e6505b82fa1211a8bf5af7eec52af8ef2b`, native-chrome
  correction `66d06e95e34f670a3f174a34df95a683e8d41ff4`.
- Root wiring reviewed when starting this test:
  `959e3a191264791910ea9c2393760baafba5f6b2`.
- Owned test: `tests/pg/test_pengiriman_detail_owner_acceptance.py`.
- Reuse the approved Stock `run_local.py`, its disposable `uji_*` SCRAM
  PostgreSQL, guard and teardown. Root chooses a free owned port/output and
  pins the final combined source **before** running. Run this file serially;
  repeat with the existing Chromium and compatible WebKit runtimes.
- Existing runner switches `OWNER_BROWSER`, `UJI_BROWSER`, `DETAIL_OUT` apply.
  There is no added opt-in, skip, new fixture runner or system setting.
- Six collected nodes per engine: Admin and G2 Operator at 390/1280, plus G1
  denial at 390/1280. No source or shared-harness editing while executing.

Suggested selection for Root's existing runner (not executed here):

```
--test tests/pg/test_pengiriman_detail_owner_acceptance.py
```

## Actual records and transport

The existing `test_barang_keluar.gudang` recipe supplies 400 bags of 25 kg,
the existing finished-goods SKU, native actors and seed warehouses. Existing
`_perintah`, `muat_semua` and `verifikasi` recipes prepare three records:
12 bags `perintah`, 13 bags `dimuat`, and 4 bags `selesai`. Final verification
uses the existing under-200 kg rule; no fabricated weighing ticket, return,
correction, PACK record or product grant is introduced. All setup, including
the existing `_klien` actor/account recipe, finishes before table fingerprints.
G1 must already exist in `seed_master`; otherwise setup fails explicitly.

The existing browser-to-ASGI `peramban` supplies the actual native HTML and
assets. Its origin is `https://uji`; this test gives the ASGI client's base URL
the same origin. Native absolute tab links are neither rewritten nor granted
cross-origin permission. Only panel fragments are removed for address
comparison. No browser setting, listener, external identity or network service
is introduced. Service workers are blocked by the existing transport, so
cold/warm/upgrade/rollback PWA remains outside these tests.

One labelled transport fault is returned **after** a genuine authorized native
GET completes: HTTP 503 instead of its successful response. No fake successful
identity, account, ORM row, count, stock or business DTO is substituted. This
tests read error/retry behavior; it is not evidence of a production outage.

## Assertions prepared

- Enter both active statuses from the actual visible authorized table link.
  Default and filtered lists are separate, preserving native query strings.
- While the native GET is held, all four permitted tabs and exact native
  table labels exist; record-dependent actions remain disabled, no form/CSRF
  input is added, and the generic H1/loading-only fallback is not accepted.
- Compare semantic native chrome before/after read using a genuine native
  GET: Beranda / Barang Keluar / actual code, span `aria-current=page`, desktop
  Back label/href, mobile menu or Back control and content Back. The separate
  native deep-link case preserves `kembali_kerja=/pekerjaan?tab=berjalan`.
- Keyboard selects a second tab before the first response is released. Late
  completion cannot replace the selected tab. Remaining native tab links are
  exercised, with one explicit GET-only keyboard retry per active status.
- Leave through the actual content Back while its native read is held. A late
  response cannot restore shipping content or change the new page address.
- Final records preserve the original journey DTO/native view, not the active
  four-tab shell. G1 receives the same 403 for active/final document and native
  reads, with no private catalogue/detail/journey disclosed.
- No browser non-GET, no page errors, and all public-table fingerprints remain
  identical after context teardown. Setup mutations are outside this boundary.

Passing runtime nodes may write width/role screenshots and observations to
`DETAIL_OUT`; these contain safe route paths and synthetic labels, not cookies,
session/CAP values, credentials or catalogue payloads. The Stock runner's
receipt and stopped/deleted cluster evidence remain Root's responsibility.

## Remaining limits

No runtime outcome is asserted yet. The test intentionally does not exercise
shipment editors, return/correction writes, portal/history adoption, physical
weighing, real business data or live permissions. Read navigation to Pekerjaan
is an existing route, not a claim that two warehouses are two tenants.
Failures must retain their receipt before any targeted revision. Root must
review the exact final combined source, execute both engines, and reconcile
any guard/transport/visual mismatch before considering a release gate.

Local checks of this test preparation: `py_compile` passed using the existing
production virtualenv (bytecode output only in `/tmp`); `pytest --collect-only
-q -o addopts= tests/pg/test_pengiriman_detail_owner_acceptance.py` collected
exactly six nodes without starting PostgreSQL, running fixture setup, or
launching a browser. No collected node has an added environment skip.
