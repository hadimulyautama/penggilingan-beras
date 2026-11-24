# Local Settings handler binding delta

Pre-edit recovery read proved `2d345de38fef87f51f9b859b2013aa13212cebfe` and clean Git state. The earlier disconnected edit did not leave a diff; it was not repeated until that readback. This delta stays in the existing child worktree/branch, preserving 2d and 5f commits.

## Actual native call path

`pengaturan.halaman_pengaturan(request, akun=Depends(butuh_akun))` retains its decorators, dependency and all existing guards. Added early document branch is GET `/pengaturan` or `/pengaturan/sesi`, no query, `akun.harus_ganti_sandi is False`, no `isi_halaman_bertahap` state, and either explicit `X-Kerangka-Halaman:1` or browser navigate/document without `X-Pindah:1`.

Same-URL consumer GET `X-Pindah:1` has no explicit shell header and still executes native data reads/render, fresh dependency and product/session checks. POST, query success/error feedback, mandatory/unknown password, access/peran/master routes and portal builder paths are not adopted. Existing peran route's `_P.boleh_ganti_gudang(peran_asli)` 403 and business/identity writers remain unchanged.

New `_metadata_menu_native` centralizes only the old native presentation expressions. Both early shape and ordinary native HTML call it, bound to:

```python
view = await view_untuk(akun.user)
peran_asli = getattr(request.state, 'peran_asli', None) or akun.peran
menu = await _metadata_menu_native(
    view=view, peran_asli=peran_asli,
    tuan=akun.peran in PERAN_ADMIN_KEATAS,
    is_super=akun.is_super, sesi_pendek=akun.sesi_pendek,
    pemulihan=pemulihan_lama_diizinkan,
)
```

`blok_kelola` still short-circuits actual SUPER view or, only for tuan, awaits the existing `pemulihan_lama_diizinkan` predicate. No absent-Super assumption, new role map, recovery override, grant, company ID or fake ORM is introduced. Other BLOK flags, `kelola_darurat`, Console HTTPS URL and test-mode availability retain their exact previous expressions. `TAMPILAN_INDUK=True` is the same previous `render(...).setdefault` for this handler; `sesi_pendek` is a primitive native property exposed solely as pending-control label metadata.

Early shape adds existing native navigation metadata and:

```python
context['PENGATURAN_NATIVE_FLAGS'] = menu
context['console_url'] = menu['console_url']
context['SHELL'] = {
    'stamp': penanda_konteks(request, akun) + '|' + request.url.path,
    'data_url': request.url.path,
}
```

Reader snapshot values are never put into the shell. The body keeps unknown name/theme/version, disabled session controls, native allowed anchors/locked spans and no form POST until actual native HTML arrives. The helper only supplies flags; it is not a server authorization dependency.

## Evidence and next gate

- 44 pure Python PASS: 14 extracted-native-function/source binding/gate checks + 30 shape/native macro parity checks. No whole product handler, ORM surrogate, DB or listener runs in the new tests.
- Metadata tests execute only its AST function with actual pure `hmu_identitas.peran` helpers, primitive fixture values and an awaited synthetic boundary callback; they check real callback short-circuit order, not real database recovery eligibility.
- Gate checks evaluate the exact new source conditional on synthetic Request/scalar password state; caller source binds actual account properties and unchanged `Depends(butuh_akun)`.
- These tests are not actual authenticated HTTP/PG/browser or production evidence. Root must review and run its sequential private fixture before accepting the new path. Public compiler/first-click registry/handlers outside this module remain root-owned and untouched. No CI, push, deployment or website action.
