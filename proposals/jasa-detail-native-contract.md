# Pesanan Jasa customer detail: scoped native structure proposal

Audit start pin `bf874d5718e9bf9d6cfa18f4cc1ef43b5c5e99f1`, in the existing Root worktree/branch; no new checkout. Other agents write unrelated paths. Only the six assigned family/test/doc files belong to this change; no caller/handler/registry/compiler/SDK/vendor edits.

Audited native sources were unchanged from bf874d5 at test readback (Root had advanced to d6455ce7):

| Source | Git blob |
|---|---|
| app/web/layar_jasa.py | 5087e2dd5e8ae33dded11682d2c400e1039e53a2 |
| app/services/jasa_pelanggan.py | 02a0f9af28c298458b7954f6cc912346b1d155b3 |
| hmu_tampilan/templates/jasa_pelanggan_detail.html | 18c0c5f447e5e7240b81861333196a7bbfce01c4 |
| app/web/static/padi-baca-native.js used by pure adapter tests | 47381f563ece85de5dafaf7f3cdd4e38b4fdbd58 |

## Actual reachable family

- `/jasa`: existing list, outside this slice.
- `/jasa/pelanggan/{pelanggan_id:int}`: native customer detail with **Ringkasan, Penerimaan, Proses, Stok, Pengambilan & retur**. Native dependency `butuh_akun`; staff reader requires actual `can_see_financials(akun.user)`. This is not an Operator permission expansion.
- `/jasa/{jasa_id:int}` is a resource lookup and redirect to customer Ringkasan with `pesanan_id` and `#pesanan-id`. It is not a separate order-edit page; kept native.
- `/jasa/{id}/nota` and `.pdf`: separate rekap readers, including merged-order PDF redirect. No adoption or invoice/financial policy change here.
- Portal has a separate authenticated customer namespace/closed read scope. Its legacy customer link dispatches to own portal composers; this proposal declines every portal scope instead of reusing the staff adapter.

## Minimum positive guard / source contract

Root must wire **after** the existing native dependency/financial-read guard and before heavy `svc.pelanggan` + `berjalan.untuk`, only under document/X-Kerangka negotiation. Proposed call: `await jasa_detail_kerangka.kerangka(request, akun, native_navigation_context)`. None means continue native; no guard/error is turned into a fake success.

Builder additionally requires same verified request-state account, mandatory-password false, GET, no X-Pindah:1, no portal. It calls the actual financial-read predicate before any DB read. It uses actual `SessionLocal` (app.database.pasang_pagar per-transaction local namespace). No request company ID or tenant selection is accepted. Tenant isolation here is the existing per-DB RuangData/session/product boundary, **not newly invented customer row RLS**.

Native `_pelanggan` existence is `Pelanggan exists` AND `(any Jasa for that customer OR a MASUK jasa ticket for that customer)`. The proposal mirrors this predicate with primitive `Pelanggan.id`, at most 21 `Jasa.id`, and the **identical bound EXISTS SQL** for a customer with no Jasa. No name/row objects, saldo, packing, silo, process, outgoing, return or ledger composition is read. No active/deleted/status filter is added, because native does not add one here. The 21-id sample supplies only the native `more than 20 orders` filter-visibility Boolean, never a total.

This bounds returned IDs, **not necessarily rows scanned or latency**. The audited model/migration exposes the partial `ix_jasa_pelanggan_berjalan`, not proof of a full-history customer-id index. Root must measure/explain query plan on a private fixture before treating this as a fast first-stage read. No production DB query, new index or schema change is proposed. Existing caller/data GET remains the final authority if a customer disappears/changes after the light read.

## Descriptor, fields and native shape

Only canonical positive integer customer path, five exact tabs, and the existing read/filter keys are adopted. Known status catalog is pinned to native `svc.STATUS`. Duplicate/unknown fields, malformed values, noncanonical page IDs, feedback/action keys (`buka`, `nilai`, `err`, etc.), focused `pesanan_id`, redirect/nota/PDF, and portal paths decline to native. No action deep link is swallowed.

The shell reuses native `_jasa_kontrol.kontrol(detail=True, nama=explicit-unread-text)` and disables both native print entry points. Its optional guide is the native read-only guide/controller; no action launcher, dialog transaction, fake `d`, fake ORM/customer/order, count zero or saved status is rendered. Fields/search values are only known URL filter intent, disabled until native HTML. Static status choices equal the native catalog. Card lists remain cards; the Stok native three-column div header (Barang / sumber, Lokasi, Saldo) is retained rather than inventing a financial table. Data-driven row close/cancel actions are not invented before their individual native guards.

Ringkasan retains material/stock label sections, follow-up region, shipment/return summary labels, order/rekap region, and conditional order filter (21-id metadata or known nonempty filter). Other tabs retain their native headings, filters where native always supplies pagination, and their card/stock regions. Counts/weights/customer identity remain explicitly unread; loading is never presented as empty/zero. Related/sourcing/transaction actions are unavailable until fresh native data.

The thin `jasa-detail-native.js` declares only this customer read family to `PADI_BACA_NATIVE`. It does not intercept tabs or mutate history/URL during a read. SameURL GET `X-Pindah:1` must remain native. Root shared SDK owns exact URL/CAP/session/context checks, versioned assets-before-swap, stale/abort handling, GET retry and native script activation. After fresh native data, original Jasa scripts/forms and guards are restored; this proposal creates no writer or auto-save.

## Evidence / held acceptance

**27 Python pure tests + 3 Node pure tests PASS**, JS syntax and diff checks pass. Tests render real header/control partials under StrictUndefined without any customer record; verify all five tabs, labels/stock columns, unknown values, locked controls/print, strict descriptor negatives, native status catalog equality and source-level guard/predicate/namespace pins. They do not execute SQL, HTTP, auth fixtures, browsers, invoices or business operations.

Still required by Root, sequentially: actual authorized staff and denied Operator/portal; existing/no-customer/no-Jasa/ticket-only resources; both private namespaces without cross-scope data; query plan + stage timing; 20/21-order filter boundary; five tabs desktop/390, keyboard, delayed HTML/data, fast tab/Back/refresh/deep-link behavior, stale/error/retry, native asset/control activation with **zero POST during loading/navigation**, correct totals after native data and no writer changes. Initial card placeholders/native conditional geometry require visual review. No claim all Jasa/detail/edit/report pages are complete.

Root public first-click binding is a separate gate: do not infer customer existence from a regex/number alone. Bind only a source-native verified link/resource in the same context or keep native guarded navigation until positive resource metadata is available. No public catalog/registry is changed here.
