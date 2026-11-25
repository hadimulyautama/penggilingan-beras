"""Pure proposal checks: no database, browser, server or credentials."""
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from starlette.requests import Request

from app.web.pengaturan_akun_kerangka import data_url_sah, kerangka, spesifikasi

ROOT = Path(__file__).parents[1]


def isi():
    env = Environment(loader=FileSystemLoader(str(ROOT/'app/web/templates')),
                      undefined=StrictUndefined, autoescape=True)
    spec = {**spesifikasi('/pengaturan/akun'), 'stamp': 'fixture-stamp',
            'data_url': '/pengaturan/akun'}
    return env.get_template('_pengaturan_akun_kerangka_isi.html').render(AKUN_KERANGKA=spec)


def test_native_labels_without_account_or_personal_defaults():
    page = BeautifulSoup(isi(), 'html.parser')
    assert page.h1.get_text() == 'Nama & kata sandi'
    assert page.select_one('label[for=pg-akun-nama-pending]').get_text() == 'Nama Anda'
    field = page.select_one('#pg-akun-nama-pending')
    assert field.has_attr('disabled')
    assert not field.has_attr('value') and not field.has_attr('name')
    save = page.find('button', string='Simpan nama')
    assert save['type'] == 'button' and save.has_attr('disabled')
    assert page.select_one('form').get('action') is None
    assert page.select_one('form').get('method') is None
    assert page.select_one('a.tindakan')['href'] == '/ganti-sandi?kembali_pengaturan=/pengaturan/akun'
    assert 'setiap catatan timbang dan pekerjaan' in page.get_text(' ', strip=True)
    assert not page.select('input[type=password],input[name=_csrf],input[name=user_id]')
    assert not page.select('[data-editor-perintah],[data-halaman-bertahap]')


@pytest.mark.parametrize('path,query', [
    ('/ganti-sandi', ''), ('/pengaturan', ''), ('/pengaturan/sesi', ''),
    ('/pengaturan/perusahaan', ''), ('/pelanggan/pengaturan/akun', ''),
    ('/pengaturan/akun', 'err=nama'), ('/pengaturan/akun', 'pesan=nama-diubah'),
    ('/pengaturan/akun', 'company_id=1'), ('/pengaturan/akun', 'kembali=/pengguna'),
])
def test_native_post_results_and_other_authority_are_not_adopted(path, query):
    assert spesifikasi(path, query) is None


@pytest.mark.parametrize('url', [
    None, 'https://uji.invalid/api/halaman-bertahap/pengaturan-akun',
    '//uji.invalid/api/halaman-bertahap/pengaturan-akun',
    '/api/halaman-bertahap/pengaturan-akun?company_id=1',
    '/api/halaman-bertahap/pengaturan-akun#draft', '/pengaturan/nama', 'https://[',
])
def test_only_integrator_owned_read_address_is_accepted(url):
    assert not data_url_sah(url)


def test_exact_pure_model_has_no_actor_values():
    assert data_url_sah('/pengaturan/akun')
    assert set(spesifikasi('/pengaturan/akun')) == {'kind', 'title', 'alamat', 'kembali', 'sandi'}


@pytest.mark.asyncio
async def test_unverified_or_portal_context_declines_before_product_import():
    request = Request(dict(type='http', method='GET', scheme='https', server=('uji', 443),
                           path='/pengaturan/akun', query_string=b'', headers=[], state={}))
    account = object()
    assert await kerangka(request, account, {}) is None
    request.state.akun = account
    request.state.portal_scope = object()
    assert await kerangka(request, account, {}) is None
    request.state.portal_scope = None
    assert await kerangka(request, account, {'SHELL': {'stamp': 'fixture', 'data_url': '/pengaturan/nama'}}) is None


@pytest.mark.asyncio
async def test_renderer_receives_structure_and_keeps_private_headers(monkeypatch):
    from starlette.responses import HTMLResponse
    seen = []
    def render(request, name, **context):
        seen.append((name, context))
        return HTMLResponse('<section>pure renderer double</section>')
    monkeypatch.setitem(sys.modules, 'app.web.tampilan', SimpleNamespace(render=render))
    account = SimpleNamespace(harus_ganti_sandi=False)
    request = Request(dict(type='http', method='GET', scheme='https', server=('uji', 443),
                           path='/pengaturan/akun', query_string=b'', headers=[], state={'akun': account}))
    context = {'SHELL': {'stamp': 'ctx-fixture', 'data_url': '/pengaturan/akun'}}
    result = await kerangka(request, account, context)
    assert result.headers['cache-control'] == 'private, no-store'
    assert result.headers['vary'] == 'Cookie'
    assert seen[0][0] == 'pengaturan_akun_kerangka.html'
    assert seen[0][1]['AKUN_KERANGKA']['stamp'] == 'ctx-fixture'
    assert set(context) == {'SHELL'}
    # A form submit or a different route cannot turn this proposal into a writer.
    request.scope['method'] = 'POST'
    assert await kerangka(request, account, context) is None
    assert len(seen) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('account', [SimpleNamespace(harus_ganti_sandi=True), SimpleNamespace()])
async def test_forced_or_unknown_password_state_stays_native(account):
    request = Request(dict(type='http', method='GET', scheme='https', server=('uji', 443),
                           path='/pengaturan/akun', query_string=b'', headers=[], state={'akun': account}))
    context = {'SHELL': {'stamp': 'ctx-fixture', 'data_url': '/pengaturan/akun'}}
    assert await kerangka(request, account, context) is None
