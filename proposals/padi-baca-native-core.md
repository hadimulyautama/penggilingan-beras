# Scoped native read core proposal

Base `cffdd748f22c971bbeb8fe959793d4f5d9771b71`. Extraction from the Account consumer after root's account runtime proof; not a new server endpoint or permission rule.

Files: `app/web/static/padi-baca-native.js` (actual static path in this repository), thin `pengaturan-akun-native.js`, Account shell script order, and pure core tests. No handler/compiler/registry/loader/vendor changes. No other route is adopted.

## Explicit adapter contract

Load versioned `/static/padi-baca-native.js` before the family adapter. Core import alone installs nothing and discovers no routes. A reviewed family adapter calls:

```js
PADI_BACA_NATIVE.mount({
  address: '/declared-native-route', // literal same-origin path + exact query
  rootSelector: '[data-reviewed-family-shell]',
  statusSelector: '[data-reviewed-family-status]',
  retrySelector: '[data-reviewed-family-retry]',
  shellSelector: '[data-reviewed-family-shell]',
  // Optional data-* marker, messages and family-only focus callback.
});
```

The declaration is an allowlist entry owned by root, **not authorization**. It must never be built from arbitrary links/request IDs, role claims, URL parameters or storage. Each server native GET must still authenticate and authorize scope/row fresh. A new family's native scripts must be reviewed to avoid auto-transactions; this core does not invent transaction policy or auto-adopt controllers.

The shell supplies immutable `data-stamp` + exact `data-url`, native frame/main/session metadata and a loading structure whose actions requiring data are unavailable. Core compares current exact address/root/CAP/frame-context/session, then verifies fresh 200 nonredirected HTML and one frame/main/session, ordered content markers, matching fresh metadata and absence of shell/generic loading. CSS/JS are prepared by same-origin versioned GET before a final current check. DOM swap and native script activation run without another await. URL equality and stamp are correlation only; they do not create access.

Leaving/pagehide aborts optional reads and disposes listener/observer; late responses cannot install. Retry uses GET `X-Pindah: 1`, no-store and same-origin credentials. No cache, persistence, business ID, actor/role, permission inference, POST or policy state belongs to the core. Read failure retains the disabled shell and retry explanation.

## Account compatibility

The thin adapter declares only `/pengaturan/akun`, supplies the previous Account messages, `data-akun-native-isi`, and identical retry focus behavior: focus native `input[name=nama]` when retry had focus; otherwise restore the matching native link if the old shell link had focus and focus fell to body. It preserves `PF_AKUN_NATIVE.sameIdentity/createReader` and CommonJS exports so the six original pure tests are unchanged. Password/forced-password/draft/server gate semantics are untouched.

Only template change: versioned core script precedes versioned Account adapter. Root's native title, shortened geometry copy and footer help remain unchanged.

## Proof and remaining gate

- Six original Account Node tests unchanged and PASS through the thin adapter.
- Eight new pure core tests PASS: explicit same-origin/canonical URL, expected-address requirement, cross-origin/undeclared factory refusal, one install on a declared second synthetic route, cross-address response refusal before assets, CAP/context/session mismatch refusal, late prepared response ignored and stopped reader inert.
- Existing 22 Python Account structure tests PASS. Diff whitespace check and JS syntax checks PASS.
- Used the existing Node bundled with approved Playwright environment; no installation or browser/PG/network execution.

These are pure factory/shape checks. Root must run focused existing Account runtime/browser proof after integrating this extraction, plus the next explicit Laporan adapter tests. No claim that Laporan, arbitrary routes, actual native DOM/asset hydration, PWA or all-pages adoption now passes. No CI, release, website or live access.
