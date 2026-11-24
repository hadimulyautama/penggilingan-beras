# Akun native: proposal wiring untuk root, belum diterapkan

Base child: `d2d036d78f299373bfbd23d6e4512293f515d944`.
Proposal awal `7fe766c6` tetap utuh. Empat file awal disalin melalui cherry-pick lokal `8f74be6`; delta consumer berada di child baru ini. Tidak ada endpoint/registry/handler/core/vendor yang diubah.

## Root saja: titik gate yang diusulkan

Pada `pengaturan.halaman_pengaturan`, **sesudah** dependency `butuh_akun` telah mengisi `request.state.akun`, sebelum baca referensi Pengaturan:

```python
# Proposal, bukan patch otomatis. Root menguji gate/scope pada fixture.
# Jangan gunakan kind ALAMAT generic yang belum mendaftarkan route ini.
if (request.method == 'GET'
        and request.url.path == '/pengaturan/akun'
        and not request.url.query
        and not getattr(request.state, 'isi_halaman_bertahap', False)
        and (request.headers.get('X-Kerangka-Halaman') == '1'
             or request.headers.get('X-Pindah') != '1'
             and request.headers.get('Sec-Fetch-Mode') == 'navigate'
             and request.headers.get('Sec-Fetch-Dest') in {'document', 'empty'})):
    from app.web.pengaturan_akun_kerangka import kerangka
    from app.web.halaman_bertahap import konteks_kerangka, penanda_konteks
    context = await konteks_kerangka(request, akun)  # native navigation metadata
    context['SHELL'] = {
        'stamp': penanda_konteks(request, akun) + '|/pengaturan/akun',
        'data_url': '/pengaturan/akun',
    }
    response = await kerangka(request, akun, context)
    if response is not None:
        return response
# Semua jalur lainnya tetap handler native persis.
```

Builder sendiri menolak portal, non-GET, query apa pun, state akun yang bukan object hasil dependency native, serta `harus_ganti_sandi` true/tidak diketahui. Query hasil POST/error/sukses selalu native agar pesan/draf tidak diganti shell. Tidak ada perubahan forced-password middleware, POST atau guard draft.

GET data **route sama** `/pengaturan/akun`, `X-Pindah: 1`, no-store, credentials same-origin. Karena tidak membawa X-Kerangka dan request browser fetch bukan document navigation, request ini tetap reader native. Reader mengulang dependency/account/product/session authorization dan render asli. Tidak ada API baru, query bypass, credential atau status yang disalin ke blueprint/storage. Root boleh mengadopsi metadata first-click hanya melalui boundary registry yang direview terpisah; consumer ini sendiri tidak membuat registry.

## Consumer scoped baru

`pengaturan-akun-native.js` hanya hidup jika `[data-pengaturan-akun-kerangka]` ada. Native account values dari reader tidak pernah dimasukkan ke local/sessionStorage atau cache khusus. Consumer memverifikasi:

- exact alamat `/pengaturan/akun`, cap release HTML, `.bingkai` context, current session token dan root/stamp masih sama;
- GET 200 HTML tanpa redirect, satu frame/main/session, marker content berurutan, bukan shell berulang;
- fresh native identity cocok sebelum prepare, dan current root/address/context/session/cap diperiksa lagi setelah seluruh GET aset;
- assets same-origin `/static/` dan `?v=` exact release; styles/scripts dibaca sebelum swap. Native scripts diaktifkan hanya setelah fresh HTML tervalidasi dan swap tanpa await;
- leaving/pagehide abort GET dan respons lama diabaikan. Retry mengulang GET, bukan transaksi. Satu read aktif mengalahkan yang lama;
- nilai/form aktif baru hadir dari native HTML; loading/error mempertahankan input disabled dan alasan. Tidak pernah menyimpan form atau menjalankan auto-save.

Tidak ada perubahan pada policy/beforeunload. Data belum dapat diketik di shell, jadi tidak ada draft yang ditimpa. Setelah swap, kontrol native beserta semantics awalnya yang berlaku. Nama/role/perusahaan/saldo tidak dipalsukan. Tautan Ganti kata sandi tetap native dengan fresh dependency; tidak mengadopsi password form.

## Proof dan gap

Pure Python menguji shape tanpa account/value/credential, decline route/query/POST/portal/forced state, same URL contract dan private header. Pure JS dengan ops doubles menguji latest-only, abort saat leave, fresh identity mismatch, retry, serta perubahan konteks ketika assets tertunda. Ini bukan DOM/ACL/browser PASS.

Root harus menjalankan berurutan: shell entry Admin/Operator sah; cold/warm first click HTML tertunda lalu GET data tertunda; stale setelah menu/context berubah; retry 401/403/500 tanpa form aktif; desktop/390/keyboard; actual assets/header/CSRF; native query error/draft; forced-password decline; nama ready setelah GET; tidak ada POST saat loading/retry/navigation. Jangan memutuskan semua Pengaturan/halaman selesai dari satu route.

Sisa keluarga tetap audit-only: index/sesi/peran/akses/Pengaturan master, perusahaan/anggota/organisasi, users, portal, recovery/offline, Serah Terima/Kabar. Security/row-bound variants bukan cakupan consumer ini.
