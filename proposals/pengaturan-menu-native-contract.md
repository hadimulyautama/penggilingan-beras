# Settings index/session native structure proposal

Base: `d147691f1650d623df2a2f5ebda5b0665e43404f`. New child `remaining-settings/produksi`. Nothing changes in `pengaturan.py`, native writers, shared reader/compiler/registry, core or vendor. This is an unwired two-route proposal, not completed Settings coverage.

## Scope / authority boundary

Only GET `/pengaturan` and `/pengaturan/sesi` without query. Root must first run existing `butuh_akun` and the actual native metadata predicates. Builder asserts the same request-state account object, rejects portal/non-GET/forced or unknown password state and queries. It never reads an account record, warehouse, tenant or settings value. Native GET on the same exact URL with `X-Pindah: 1` still owns fresh session/product/role/scope authorization and actual HTML; all POST behavior stays native.

Root integration may call `pengaturan_menu_kerangka.kerangka(request, akun, konteks)` only under normal document/X-Kerangka negotiation. Required `SHELL`: `stamp` nonempty, `data_url` exactly the route. `PENGATURAN_NATIVE_FLAGS` contains booleans from the **same exact native caller**, not request/browser/claimed roles. New pure helper `spesifikasi(path, query, flags)` compiles shape; it is not permission validation.

Native metadata inventory in `app/web/pengaturan.py:halaman_pengaturan`:

| Flag supplied by owner | Actual native source / meaning |
|---|---|
| `blok_kelola` | `view == V_SUPER or (tuan and await pemulihan_lama_diizinkan())`; requires the real fresh recovery predicate, never assume absent Super |
| `blok_perusahaan` | `akun.is_super` |
| `blok_lihat_sebagai` | `_P.admin_keatas(peran_asli)` |
| `blok_kerja_gudang` | `_P.boleh_ganti_gudang(peran_asli)` |
| `blok_setelan`, `tuan` | exact `akun.peran in PERAN_ADMIN_KEATAS` computation |
| `TAMPILAN_INDUK` | actual native rendering context flag (defaulted by render), not inferred from role |
| `blok_mode_uji` | `settings.mode_uji and view == V_SUPER` |
| `kelola_darurat` | native `view != V_SUPER`, used only with true `blok_kelola` for the existing explanatory paragraph |
| `mode_uji_tersedia` | exact `settings.mode_uji`, separate from `blok_mode_uji`; available-but-denied Mode uji stays a locked span |
| `sesi_pendek` | optional boolean of the authenticated native account property, used only to choose the existing button label |

Each conditional flag must be literal Boolean true; absent, string, integer or arbitrary role claims cannot enable conditional doors. False/unknown doors retain the native disabled span, labels, order and `akses-terkunci` class instead of disappearing. No role enum or role-to-access map is introduced. The caller must not take shortcuts around the legacy recovery/last-Super/membership checks to generate these booleans.

The five native unconditional read doors remain after `butuh_akun`: own Account, Session, Perusahaan saya, Daftar akses, Batas ubah & versi. `Perusahaan saya` is already unconditional in the native template; its list/detail reader still rechecks actual membership/scope and may show no eligible membership. A menu link does not grant membership or actions.

## Native shape without configured values

- Index keeps native group order/classes, labels, descriptions, icons from `_pengaturan_ikon.html`, and native company/personal navigation literals. Every conditional door is the native allowed anchor or disabled `span.pg-pintu.akses-terkunci` with exact native title/aria-disabled; no denied anchor is opened. Advanced summary is always present with anchor/span inside. For complete Boolean metadata the operation group follows actual `blok_setelan or TAMPILAN_INDUK`; if group flags are unknown, only an inert locked shape is reserved. Root must resolve these metadata before acceptance.
- Account name/role and version are not invented. Identity displays explicit pending text. Mode terik is an unavailable switch with unread-state explanation in the footer, no extra line between native controls, no value/aria-pressed, action or POST. Native GET supplies the actual switch/form later.
- Optional Console door mirrors native `blok_perusahaan and console_url`. Public navigation metadata `console_url` must be supplied by the same native caller via `konteks["console_url"]` (or explicit pure helper parameter); no URL is invented or read from configuration/request here. It is an allowed native anchor only for the verified native flag plus existing HTTPS target. Empty target means no native Console slot. Pure tests use only a synthetic HTTPS fixture URL. This is metadata parity, not an authorization rule or settings write; missing actual owner metadata remains an adoption blocker.
- Native recovery explanatory paragraph appears only when **both** owner-supplied native booleans are true; otherwise absent. This is not proof the recovery condition holds in any real installation.
- Session preserves heading/help and both control slots. Buttons are disabled `type=button`, with no form, action, token or auto-logout. First label is native `Ganti pengguna`/`Keluar` only when `sesi_pendek` Boolean is supplied; otherwise explicitly unread. Native GET owns actual session forms, CSRF and logout-all confirmation. No logout action is executed by this proposal.
- Existing `PADI_BACA_NATIVE` is the sole consumer. New adapter explicitly adopts just the two literal URLs, same-origin GET, stamp/session/context/CAP checks, native assets and late-result guards. Retry-focus goes to read content, never a logout button. No storage, policy/beforeunload change, permissions, real options or values.

## Exact HOLDs / remaining settings

- `/pengaturan/peran`: HOLD. Native rejects `not _P.boleh_ganti_gudang(peran_asli)` **after** computing original role; branch/title differs by original Admin vs warehouse-work permission. Options/current selection come from native LIHAT_PILIHAN/PILIHAN_GUDANG + effective/request warehouse context. No guessed options/current warehouse or role; requires a separately reviewed binding from the actual caller before adoption.
- `/pengaturan/akses`: HOLD for this batch. Native static matrix columns/rows come from `daftar_umum()/PERAN_KOLOM` and current VIEW highlight, with per-user `actions_menu(akun.user)` details/count. The current partial says a broad legacy recovery sentence; this proposal neither repeats it as authority nor revises policy. A follow-up can provide exact static header shape with current-role highlight/details count pending, after owner reviews the native projection contract.
- Other Settings/master/company/user/recovery pages remain audit-only; their record/version/draft, recovery or row-authority boundaries are not generalized into this two-route consumer. No new rule on last-Super, passwords or membership.

## Proof / root next step

Pure Python tests: 30 PASS (strict native flags, no fake account/ORM or configured values, native labels, two-route/query and caller/portal/password/POST decline; plus exact comparison against native vendor macro/group fragments for all enabled hrefs and every anchor/disabled-span label/order/class/title/aria over ten Boolean/ConsoleURL combinations). Pure Node: 2 PASS (explicit route configuration and non-mutating retry focus). No browser/PG/CLI/network/remote/CI/deploy.

Root owns wiring and schedules runtime sequentially: actual Admin/Operator flags and label variant, HTML/data delayed separately, new GET stale after navigation/context, error/retry, desktop/390 keyboard, session-expiry/forced-password/native query feedback, correct final forms/CSRF and zero POST while loading/retry/leaving. Default unknown conditional flags use safe locked spans, but not evidence a complete native menu was presented. Native permission booleans must be computed before acceptance, rather than keeping real allowed controls hidden forever. Inspect resulting no-data geometry before release; pure menu parity does not prove pixel layout. The original 5f4ff324 artifact stays intact; this delta corrects omitted native disabled slots without changing access policy.
