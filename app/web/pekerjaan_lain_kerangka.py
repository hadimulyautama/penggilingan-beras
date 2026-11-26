"""Katalog tujuan tanpa antrean; spesifikasi dan izin tetap dari menu native."""
from functools import lru_cache
from pathlib import Path
import re

PATH = '/pekerjaan/catat-lain'


async def katalog(user):
    from app.web.api import actions_menu
    # Hanya label/struktur untuk kerangka, tidak menyimpan spesifikasi borang
    # atau saldo. Menu dibaca ulang sesudah klik sebelum tombol diaktifkan.
    menu = await actions_menu(user)
    urut = menu[0].get('urut_grup', []) if menu else []
    kelompok = {}
    for aksi in menu:
        if not aksi.get('kartu'):
            kelompok.setdefault(aksi.get('grup') or 'Lain-lain', []).append({
                k: aksi.get(k, '') for k in ('id', 'label', 'hint')})
    return [(g, kelompok[g]) for g in dict.fromkeys([*urut, *kelompok]) if g in kelompok]


@lru_cache(maxsize=1)
def aset():
    root = Path(__file__).resolve().parents[2]
    code = (root/'hmu_tampilan/static/aksi.js').read_text()
    awal = code.index('  async function muat() {')
    akhir = code.index('  /* ── Yang sudah ditunjuk kartunya', awal)
    # Adapter hanya pada template katalog baru, bukan salinan paket yang
    # disunting. Mesin borang/kirim native sesudah bagian ini tetap persis.
    asli = code[awal:akhir]
    if asli.count('  function gambar() {') != 1 or asli.count('"/api/dashboard"') != 1:
        raise ValueError('Kontrak katalog paket berubah')
    code = code[:awal] + '''  var katalogTujuan = document.querySelector('[data-pekerjaan-lain]')?.padiKatalog;
  if (katalogTujuan) katalogTujuan.ulangi = muat;
  async function muat() {
    if (!katalogTujuan) return;
    var menu = await katalogTujuan.baca();
    if (!menu) return;
    MENU = {}; menu.forEach(function (a) { MENU[a.id] = a; });
    DATA = {menu: menu, urutGrup: (menu[0] && menu[0].urut_grup) || []};
    gambar();
  }
  function gambar() { katalogTujuan.gambar(DATA, bukaAksi); }

''' + code[akhir:]
    controller = (root/'app/web/static/pekerjaan-lain-kerangka.js').read_text()
    styles = []
    for name in ('laporan-riwayat.css', 'laporan-kontrol.css', 'pekerjaan-kontrol.css'):
        css = (root/'hmu_tampilan/static'/name).read_text()
        if '</style' in css.lower() or re.search(r'@import|url\s*\(', css, re.I):
            raise ValueError('Aset katalog tidak mandiri')
        styles.append((name, css))
    if any('</script' in s.lower() for s in (code, controller)):
        raise ValueError('Aset katalog mengandung penutup skrip')
    return dict(engine=code, controller=controller, styles=styles)


async def susun(request, akun, *, navigasi):
    from fastapi import Request
    from app.web.retur_supplier_kerangka import pembaca
    from app.web.kerangka_langsung import kemas_frame
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.security import NAMA_COOKIE, baca_token
    from app.web import csrf
    from app.web.tampilan import render
    from hmu_tampilan import CAP_ASET
    from jinja2.utils import htmlsafe_json_dumps
    if not pembaca(request, akun):
        return None
    state = {**request.scope.get('state', {}), 'menyusun_kerangka_langsung': True,
             'frame_kerangka_langsung': True}
    native = Request({**request.scope, 'path': PATH, 'raw_path': PATH.encode(),
                      'query_string': b'', 'state': state})
    context = dict(navigasi)
    context.update(layar='pekerjaan', kembali='', tab_tindakan='/pekerjaan?tab=tindakan',
                   tab_berjalan='/pekerjaan?tab=berjalan', pl_shell=True,
                   pl_context=penanda_konteks(request, akun), pl_katalog=await katalog(akun.user),
                   pl_aset=aset())
    body = render(native, 'pekerjaan_lain.html', **context).body.decode()
    body = re.sub(r'(<span class="kontrol-tab__jumlah"[^>]*>).*?(</span>)', r'\1—\2', body)
    if len(body.encode()) > 524288:
        return None
    nonce = request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state, 'csrf', None)
    result = dict(versi=1, cap=CAP_ASET, konteks=penanda_konteks(request, akun),
                  sesi=csrf.untuk_sesi(nonce, baca_token(request.cookies.get(NAMA_COOKIE)), request.cookies.get('produksi_lihat', '')),
                  **kemas_frame({PATH: body}))
    return result if len(htmlsafe_json_dumps(result).encode()) <= 786432 else None
