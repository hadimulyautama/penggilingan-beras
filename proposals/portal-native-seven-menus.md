# Portal native framework: seven menu doors

Owner: Flow/root integrator. This family is a local presentation proposal on the existing Root branch. It does not adopt staff manifests, create an endpoint, run PostgreSQL/browser, or change auth/ownership/writers. Source baseline inspected: `8b671f6c14398e941fad7d89e02ee315f4d03c12`. Other Root family commits may be ancestors of the final commit because all owners share this one branch.

## Implemented scope

- `/pelanggan`, `/pelanggan/`, `/pelanggan/ringkasan`: Beranda, Barang di pabrik, Proses berjalan.
- `/pelanggan/barang-masuk`: native jenis/cari controls and existing seven-column grid header; no receipt row/count.
- `/pelanggan/barang-saya`: native Barang di pabrik / Karung kosong sections, no commodity, packaging or balance values.
- `/pelanggan/jasa-saya`: native Proses berjalan / Menunggu giliran regions, no invented process card/count/status.
- `/pelanggan/riwayat-proses`: native jenis/q controls and list region, no count/page limit inferred from missing data.
- `/pelanggan/barang-keluar`: native q/status/sejak controls, active four-column table and seven-column history table, each with one unread row. Native presentation CSS is embedded in the data-free public program so the first structure does not wait for its GET.
- `/pelanggan/laporan`: native document-kind/q controls and document list region; no document/PDF generated or fetched by a framework.

All forms are GET-only. Known read filters retain their raw target URL; repeated/unknown/action/resource selection keys decline. Native source option lists and headers are extracted by the compiler, not inferred from dummy rows. Native H1 is persistent, not a generic transient title page. Counts, owner names, source IDs, units and balances are never fabricated as zero.

`portal/routes.py::read` calls the optional document helper **after** `require_customer`, `READS`, `load_scope` and `native_request`, before existing business readers. `X-Portal-Navigasi: 1` always goes to the original native data dispatcher. The early document uses the existing portal shell; normal client navigation can use its already available public program before target HTML or data returns.

## Private/public boundary and router behavior

- Public program: `kerangka-portal-ui.js`, compiler-owned and versioned with CAP. No account, token, resource ID, response rows, history, grant or business data.
- Private inert `#padi-portal-kerangka` binds program source/CAP/current account/current CSRF-session and the exact seven native menu URLs. It is only produced from the existing `ReadScope` and the matching native account. It remains in a no-store private document.
- HP sidebar closes before delegated navigation, so the seven universally available native portal menu hrefs must be present in the current DOM, not computed-visible after that close. This is menu presentation provenance; it grants no resource. Every data GET still re-runs customer/session/namespace/source ownership checks.
- Adopted `freshOnly` routes opt out of the existing private HTML memory cache and its prefetch. They show the structure and perform a fresh GET even when warm. Default router/cache semantics for unadopted routes stay unchanged. This is not a claim that all live revoke paths or portal resources were tested.
- Server 401/login and native permission/resource errors keep native behavior. Temporary adopted read failure keeps the framework and filter input with one explicit read-only retry. No automatic retry/POST.
- A changed pending filter holds the older result and says to click Cari. New GET submission is explicit; refresh does not overwrite that input. Retry on the same URL retains its pending form.
- The existing navigation sequence defeats late responses after menu/Back. Native installation additionally checks current CAP/account/CSRF-session/program binding; changed context/version falls back to a native full document.
- Unknown deep variants no longer get an invented generic heading + “Memuat data” page. Their previous content remains until the existing native GET is ready. **This is not yet immediate target structure for those variants.**

## Integration owned by this family

Files: new `portal/kerangka.py`, `templates/portal/kerangka.html`, `static/portal-kerangka.js`, compiler/public generated pair, two pure test files; scoped calls in `portal/routes.py`, `portal/presentation.py::shell`, portal shell template and `portal-navigasi.js` only. Root does not need staff head/provider wiring for this family.

`python scripts/buat_kerangka_portal.py` / `--check` must run after any source input changes. The metadata pins native templates/options/CSS and compiler/runtime source. No DB access is used by this compiler.

## Deep inventory: still not adopted

| Family | Native guard/source | Required next presentation/catalog facts |
|---|---|---|
| Legacy landing/tab aliases: `/pekerjaan`, `/ringkasan?tab=penerimaan/proses/pengambilan/stok`, `/jasa/pelanggan/{pid}` | Dispatch rewrites to different native menu composers; PID must equal reader | Normalize only after actual native dispatch facts; do not map arbitrary aliases by regex. Current proposal declines them. |
| BM `/barang-masuk/{tid}` four tabs | `own_ticket` uses ReadScope + exact MASUK ticket SQL; staff composer then portal read-only projection | Actual visible portal receipt href/code + typed tab query, CAP/account/session/source digest; native ticket status/legacy presence decides sections. No staff manifest. |
| PK/product/karung stock aliases and details | Scoped stock readers; PK G1 `own_model(giling,code)` vs G2 intake ID in scope; product-specific native DTO + portal commodity projection | Actual card kind, bagged/curah, owner/location and permitted read links from already scoped DTO; source after portal projection, not raw staff HTML. Neutral guessed G2 layout is unsafe. |
| Four active process kinds | `own_model(...,by_code=True)` checks scoped actual model; native phase/finished redirects remain | Actual visible portal code/href + phase; pure labels from portal `identitas_proses` and projected readonly tabs. Staff worksheet/controller must never mount. |
| Three history process lists/details, transfer separate | Scoped allowed IDs; details `own_model`, native finished semantics differ for dryer | Visible exact resource href/code and actual native kind/status/phase; preserve projected no-edit tabs, QC/measure/history paging. Transfer remains its owner. |
| QC lists/details (five native kind labels) | Parent validates `QC_PAGES`, detail calls `own_model`; QC-specific joins/native sources | Use exact scoped sample/process/batch and projected native sections. Existing `MODELS` has no `beras-hasil-sosoh`, so that referenced portal detail currently reaches `missing()`; do not silently invent a scope mapping in this presentation proposal. |
| Shipping detail and historical journey | `own_outgoing` exact all-items-safe source scope; native OUT_HIDUP four-tab vs final/batal journey/returns differ | Resource/status variant metadata from actual scoped DTO and visible portal links. Do not force every ID into a four-tab template or expose staff mutators. |
| Retur list/detail/ticket/application | Exact `CustomerReturn`, `ReturRincian`, RTP ticket scoped IDs; outgoing source semantics | Own readonly family with real origin/capacity/status fields; held partial-return/business fixes stay separate. No assumptions about fractional karung, QC hold, credit or responsibility. |
| Dokumen/HTML viewer/nota/PDF | `own_ticket`, `own_outgoing`, `own_order`, `own_model`; finished checks; Sosoh PDF needs real silo usage | Actual document type, current visible link and known PDF availability. Do not create automatic PDF work/iframe from guessed IDs; native download/render/error tests remain separate. |
| Audit/Kabar extra portal read routes | `PortalOwnershipEvent` customer predicate; notification source predicate per scope | Own private portal list/filter structures; do not borrow staff Audit admin entitlement. Kabar mark/open POST stays unchanged and explicit. |
| Login | Standalone `/pelanggan/masuk` has native username/password fields immediately, excluded by soft-nav | Preserve explicit native POST/throttle/CSRF. No portal self-password route exists in the inspected source; do not invent one. |

Public READS is a closed source regex in `portal/navigation.py`, not an authorization substitute. `require_customer` validates product/session/account/version/namespace; `load_scope` checks source ownership before composers; `presentation.read_only` removes staff actions and rewrites only allowed portal reads. None of those policies was changed.

## Remaining owner acceptance gates

1. Root must run actual existing synthetic customer fixture, not staff Operator masquerading: all seven menus at desktop/390, separate HTML/data delays, no generic transition, empty/filter-empty/error/retry/Back/deep read, dirty filter preservation, no POST/fingerprint change.
2. Cold/warm portal loading and upgrade/rollback exact source. Old already-running portal JS does not check CAP; it cannot be claimed to self-replace until a fresh document/program load. No server protocol bypass was added to force an old client.
3. Scope/token/namespace change between source and fresh GET must not install a foreign document. No role/access fixture was created here.
4. Resource variants above need dedicated adoption and proof. Seven menus is not all portal pages.
5. Raw/gzip package and private metadata size, query count and elapsed runtime are separate evidence; no production latency/SLA claim.

Pemilik: Flow/root. Bukti terakhir: 66 Python pure tests (28 new contracts +38 existing presentation/detail/beranda/QC regressions) +25 Node tests (7 new +18 existing router), compiler deterministic/check and syntax. Browser/PG have not run in this family. Berikutnya: Root combined native acceptance and remaining deep families. Status rilis: FROZEN LOCAL PROPOSAL, no PR/CI/push/deploy or production change.

## Prepared owner browser acceptance (not executed by child)

New single file: `tests/pg/test_portal_kerangka_browser.py`. `py_compile` and pytest `--collect-only` succeeded: **7 collected**, zero fixture/browser execution. This is preparation evidence, not 7 PASS.

Exact existing recipe is imported unchanged from `tests/pg/test_portal_pelanggan.py::portal` with its existing `qc` dependency from `test_riwayat_qc_detail.py`. It already creates Customer A, Customer B and a no-data customer, their original three `PortalAccount` rows, native `Jasa`/process/QC/notification source records and actual signed portal sessions via its original `client(account)` factory. No new actor, account type, membership/role or access rule is added. These are **different customers/owners in one fixture**, not proof of two company tenants.

The existing staff `peramban` is unsuitable because its forwarding allowlist omits `X-Portal-Navigasi`. The new narrow helper preserves the existing portal client/session and browser profile and forwards actual browser headers (except host/cookie/content-length); the real ASGI `require_customer` and `load_scope` remain active. It records only route/method/phase and nonsecret negotiation headers, not cookies/CSRF/session values.

Coverage prepared:

1. Four browser profiles: Customer A/B ×390/1280. Each profile actually clicks all seven native sidebar menu links. Separate HTML/data holds are armed on each exact target. The structure/labels/columns/GET controls must appear while actual data delivery is held; **no target HTML GET should be needed at all**. X-Portal negotiation is read from the actual browser request, not synthesized. Native data is then released and the persistent native H1 compared. No foreign customer values, POST/action forms, JS errors or fingerprint changes are allowed. Fourteen synthetic screenshots can be saved through the existing `DETAIL_OUT`.
2. 390/1280: temporary 503 **only after** a genuine successful native auth/read; framework/filter must survive, retry is one explicit GET. A pending search edited before old data returns must retain its input and wait for Cari. Explicit search obtains native filter-empty output. A late response after switching menu cannot restore the old screen; Back must reenter a framework/fresh GET. No POST or table fingerprint changes.
3. Explicit ASGI HTTP negotiation contract for all seven routes: actual document headers select structure, X-Portal-Navigasi1 still wins when both are present and selects native data. This is protocol evidence, deliberately separate from browser Sec-Fetch claims. Existing Customer A/B foreign process and wrong-customer query guards must return404. Existing no-data customer must retain native true-empty output for history/documents.

Root runs it serially only after **all** shared source is clean/frozen, using the already approved `output/padiflow-stok-first-click-20261124/run_local.py` and a unique run directory/free approved port. Example shape (do not reuse a completed directory or assume the port is free):

```
produksi/.venv/bin/python output/padiflow-stok-first-click-20261124/run_local.py \
  --source ../padiflow-all-pages-navigation-20261124/produksi \
  --out <unique-portal-owner-run> --port <verified-free-approved-loopback-port> \
  --browser chromium --test tests/pg/test_portal_kerangka_browser.py
```

Repeat with the approved existing WebKit runtime through the same runner when required. SW remains blocked for deterministic interception; ordinary native HTTP/cold-warm PWA upgrade/rollback, real Safari/iPhone, hosted behavior and production throughput are **not** established by this file. No dependency gap was found in the existing customer fixture. Execution/cleanup receipts are Root's remaining gate.
