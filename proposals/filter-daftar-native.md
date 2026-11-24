# Native filtered Pekerjaan / Barang Masuk — Root integration handoff

This is a presentation-only proposal in Root's existing review branch. No native caller, global provider, registry, server endpoint, vendor, core, writer, role, data, or configuration is changed by this family. No PG/browser or remote operations were run by this owner.

## Scope and true limitations

- Canonical `/pekerjaan` read queries: `tab`, `jenis`, `kepemilikan`, `gudang`, `pemasok`, `cari`, `pelanggan_id`, `kembali_jasa`, `halaman`, `asal`, `kategori`, `grup`, `informasi`.
- Canonical `/barang-masuk` read queries: `status`, the same common read filters, and paging. Query order and original percent encoding are retained for address correlation. A single duplicate, unknown/action key (even `buka=`), unsupported enum/bounds, malformed UTF-8/percent encoding or origin/hash declines to native.
- This family does not pretend to know server counts, clamped last page, customer identity, warehouse identity or stock. Query-selected supplier values remain hidden read-filter values; their visible remote option explicitly says **Nama terpilih belum dibaca**. Customer query IDs are labeled **Filter pelanggan ID … belum dibaca**, never as an authorized owner's name.
- Type/owner/warehouse controls are selected only from the bound native prototype's existing enabled options. An unknown type or unavailable option declines. If native Operator markup omits the warehouse select, an already requested read filter is preserved as a hidden value; it does not introduce an accessible warehouse or action. The fresh GET still applies native role/scope policy.
- Native order and row selection remain wholly server-owned: native filtering happens before the existing 50-card / 25-receipt slice. The adapter neither sorts nor fabricates rows.
- **Form submit stays the native GET form contract.** This proposal does not manufacture a click, call a private navigation API, change history itself or promise a pre-HTML shell for a full-document form submit. Root must separately decide/verify that UX if required. Supported filtered *link / Back* navigation can be adopted by the existing provider immediately.
- A dirty GET filter stops its optional read and retains input. There is no auto-apply, save, write, cache or POST. Existing form controllers still synchronize the search field on explicit submit. Pending retry stops being offered after a filter changes; apply/search reads the new choice through native GET.

## Root wiring (not done by this owner)

1. Load `/static/filter-daftar-native.js?v=<CAP>` and the current `/static/padi-baca-native.js?v=<CAP>` as versioned program assets through Root's existing head loader. The new factory declines if the shared native reader is missing. Do not cache any derived frame, account, query result, draft or transaction HTML.
2. Inside the already-bound provider, for only the two canonical list paths:

   ```js
   const program = window.PadiFilterDaftarNative;
   const prototype = program?.baseAddress(target, location.origin);
   const base = prototype && decodeFrame(registry, prototype);
   const result = base && program.buat(target, base, context, cap, token);
   ```

   `null` preserves native fallback. The six existing mandatory frames remain authoritative and unchanged. The base must be decoded from the current Root-validated private registry; do not accept caller-supplied/free HTML as a registry substitute.
3. The derived frame retains exact native control markup and per-document binding, replaces only displayed read filters/tab links and adds the unique `[data-filter-daftar-native]` reader marker. Its stamp is explicitly the shared reader's **correlation string** `context + '|' + target`, not a minted server JSON stamp.
4. Only in this isolated derived frame, old `halaman-bertahap.js` / `barang-masuk-pencarian.js` JSON shell loaders are removed. Their root ready flags are set so an old loader cannot double-fetch. The existing Work `[data-halaman-bertahap]` marker remains, so the legacy `PadiDaftarKosong` auto-initializer gate remains false; this invariant is covered by a focused source-boundary test. Original `data-bm-stamp` / JSON data URL are removed, never regenerated. The initializer calls the new thin native reader. Native same-URL HTML is fetched once by `PADI_BACA_NATIVE` using its existing `X-Pindah:1`, `X-Kerangka-Halaman:0`, no-store, credential, identity, abort/stale and final activation checks.
5. The fresh native document is installed by the existing shared reader. It receives its original unmodified native controllers, enabled actions and filter values only after native access/scope/data validation. Pending root has no fake data/version/transaction/CSRF setup. Core error and retry remain read-only. A failed GET keeps the real table/filter structure and explains that the list is not an empty result.
6. Root's global native chrome normalization still applies to a derived result, including the existing desktop-theme hidden return address. This family does not edit that shared code.

## Alias audit: deliberately not guessed

- `/berjalan`: `layar_berjalan.halaman_berjalan` calls `halaman_pekerjaan(..., awal='berjalan')`; its document address and native alias behavior differ from the canonical `/pekerjaan` data address.
- `/aksi`: `main.halaman_aksi` can select Barang Masuk for `grup=bahan`, and a data-dependent native work branch can select an information tab. It also redirects action editor requests.
- `/keputusan`, `/mutu`: actual `Depends(butuh_admin)` and native `alias_keputusan` origin/category filters must execute; accepting a URL-shaped alias as the normal staff list would obscure the boundary.
- `/aksi-lain`: actual redirect to `/pekerjaan/catat-lain`; the action catalogue has separate controls and is not a table alias.

No alias path is returned by the new descriptor or public factory. These are recorded as remaining adoption work, not silently marked done.

## Owner proof and pending acceptance

Pure tests: 40 Python PASS (including descriptor/URL boundary, direct AST-loaded equivalence with actual `layar_pekerjaan.tautan`, and Python/Node contract parity); 24 Node PASS (including exact query correlation, alias/action decline and selecting only existing enabled native options). JavaScript syntax PASS. No skips, no browser, no PG fixture.

Root still needs actual-registry positive DOM proof, both roles and warehouses, 390/desktop, filtered URL click / Back, held HTML vs held native GET, error/retry, stale/abandon response, dirty-filter retention and no POST/fingerprint change. Verify current/cold/warm program loading and rollback separately; existing old hashes are not evidence of this family's integration.

**Pemilik:** Flow; Root integrator. **Bukti terakhir:** pure proposal source and tests only. **Berikutnya:** Root wiring and serial fixture/browser. **Status rilis:** LOCAL_FROZEN_PENDING_INTEGRATION; no CI, push or deploy.
