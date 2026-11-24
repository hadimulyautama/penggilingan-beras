"""Pure viewer structure/source contracts, not a native auth/browser proof."""
import ast
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined
from starlette.requests import Request
from starlette.responses import Response

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


page = load('pdf_viewer_spec_test', 'app/web/proses_pdf_kerangka.py')
catalog = load('pdf_viewer_catalog_test', 'app/web/proses_pdf_catalog.py')
compiler = load('pdf_viewer_compiler_test', 'scripts/buat_kerangka_proses_pdf.py')


def env():
    return Environment(loader=ChoiceLoader([DictLoader({'base.html': '{% block isi %}{% endblock %}'}),
        FileSystemLoader([ROOT / 'app/web/templates', ROOT / 'hmu_tampilan/templates'])]),
        autoescape=True, undefined=StrictUndefined)


@pytest.mark.parametrize('kind', page.KINDS)
def test_only_three_literal_html_viewers(kind):
    path = '/riwayat-' + kind + '/17/laporan'
    assert page.deskripsi(path) == dict(kind=kind, id=17, alamat=path,
        detail=path.removesuffix('/laporan'), parent='/riwayat-' + kind, pdf=path + '.pdf')


@pytest.mark.parametrize('path,query', [('/riwayat-transfer/17/laporan', ''),
    ('/riwayat-giling/17/laporan.pdf', ''), ('/riwayat-sosoh/17/laporan', 'unduh=1'),
    ('/riwayat-giling/0/laporan', ''), ('/riwayat-giling/2147483648/laporan', ''),
    ('/riwayat-giling/17/koreksi', ''), ('/riwayat-pengeringan/17/laporan', 'buka=')])
def test_binary_action_unknown_and_query_decline(path, query):
    assert page.deskripsi(path, query) is None


def native_fragment(kind, code='UNIT<&>'):
    return env().get_template('laporan_' + kind + '.html').render(
        kode=code, pdf_url='/riwayat-' + kind + '/17/laporan.pdf')


def response_pair(kind, headers):
    path = '/riwayat-' + kind + '/17/laporan'
    request = Request(dict(type='http', method='GET', path=path, query_string=b'',
                           headers=[(key.lower().encode(), value.encode()) for key, value in headers.items()]))
    # Identity sentinel only; no User, account, role or database fixture.
    identity = object()
    request.state.akun = identity
    request.state.portal_scope = None
    body = '<html><main id="isi-halaman"><!-- isi-halaman:mulai -->' + native_fragment(kind) + '<!-- isi-halaman:akhir --></main></html>'
    response = Response(body, media_type='text/html')
    response.context = dict(akun=identity, kode='UNIT<&>', pdf_url=path + '.pdf')
    return request, identity, response


@pytest.mark.parametrize('kind', page.KINDS)
@pytest.mark.parametrize('headers', [{}, {'X-Pindah': '1'}, {'X-Kerangka-Halaman': '0'},
                                    {'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'}])
def test_native_document_or_nonexplicit_x1_is_byte_identical(kind, headers):
    request, identity, response = response_pair(kind, headers)
    before, old_headers = response.body, dict(response.headers)
    assert page.native_response(request, identity, response) is response
    assert response.body == before and dict(response.headers) == old_headers


@pytest.mark.parametrize('kind', page.KINDS)
def test_explicit_x1_defers_only_original_iframe_source_and_keeps_share_program(kind):
    request, identity, response = response_pair(kind, {'X-Pindah': '1', 'X-Kerangka-Halaman': '0'})
    before = response.body
    native = BeautifulSoup(before, 'html.parser')
    script = native.select_one('script').get_text()
    frame = native.select_one('iframe')
    result = page.native_response(request, identity, response)
    actual = BeautifulSoup(result.body, 'html.parser')
    iframe = actual.select_one('iframe')
    assert not iframe.has_attr('src') and iframe['data-ppv-src'] == frame['src']
    assert iframe['data-ppv-url'] == request.url.path
    assert iframe['title'] == frame['title'] and iframe['style'] == frame['style']
    assert actual.select_one('script').get_text() == script
    assert script.count('fetch(pdfUrl,') == 1
    assert len(actual.select('script[src^="/static/proses-pdf-native.js?v="]')) == 1
    assert actual.select_one('a[href$="?unduh=1"]')['href'] == frame['src'] + '?unduh=1'
    needle = (' src="' + frame['src'] + '"').encode()
    replacement = (' data-ppv-src="' + frame['src'] + '" data-ppv-url="' + request.url.path + '"').encode()
    # Surgical byte change, not whole-document normalization masking drift.
    without_adapter = result.body[:result.body.rfind(b'<script src="/static/proses-pdf-native.js')] + result.body[result.body.rfind(b'<!-- isi-halaman:akhir -->'):]
    assert without_adapter == before.replace(needle, replacement, 1)
    assert result.headers['Cache-Control'] == 'private, no-store'


def test_defer_declines_wrong_identity_resource_or_unexpected_markup():
    headers = {'X-Pindah': '1', 'X-Kerangka-Halaman': '0'}
    for variation in ('identity', 'resource', 'duplicate', 'portal'):
        request, identity, response = response_pair('giling', headers)
        if variation == 'identity':
            request.state.akun = object()
        elif variation == 'resource':
            response.context['pdf_url'] = '/riwayat-giling/18/laporan.pdf'
        elif variation == 'duplicate':
            response.body += b'<iframe src="/riwayat-giling/17/laporan.pdf"></iframe>'
        else:
            request.state.portal_scope = object()
        before = response.body
        assert page.native_response(request, identity, response).body == before


def test_public_native_viewer_controls_geometry_and_chrome_without_pdf_fetch():
    payload, manifest = compiler.build()
    assert (ROOT / 'app/web/static/kerangka-proses-pdf-ui.js').read_bytes() == payload
    assert (ROOT / 'app/web/static/kerangka-proses-pdf-ui.meta.json').read_bytes() == manifest
    meta = json.loads(manifest)
    assert hashlib.sha256(payload).hexdigest() == meta['aset_sha256']
    data, _ = json.JSONDecoder().raw_decode(payload.decode().split('window.PadiKerangkaProsesPDFData=', 1)[1])
    from app.web.breadcrumb import susun
    for kind, variant in data['variants'].items():
        actual = BeautifulSoup(variant['html'], 'html.parser')
        native = BeautifulSoup(native_fragment(kind, '__PADI_CODE__'), 'html.parser')
        assert actual.select_one('h2').get_text() == native.select_one('h2').get_text()
        assert actual.select_one('iframe')['style'] == native.select_one('iframe')['style']
        assert actual.select_one('iframe')['title'] == native.select_one('iframe')['title']
        assert actual.select_one('a[href]')['href'] == native.select_one('a[href]')['href']
        assert actual.select_one('#bagikan-pdf').has_attr('disabled')
        assert not actual.select('iframe[src],iframe[srcdoc],form,input,select,textarea,[data-post],[data-kirim]')
        assert not actual.select_one('[data-ppv-download]').has_attr('href')
        assert actual.select_one('[data-ppv-download]')['aria-disabled'] == 'true'
        crumb = BeautifulSoup(env().get_template('_breadcrumb.html').render(rantai=susun(
            '/riwayat-' + kind + '/1/laporan', dict(kode='__PADI_CODE__'), 'Laporan __PADI_CODE__')), 'html.parser')
        for a in crumb.select('a[href="/riwayat-' + kind + '/1"]'):
            a['href'] = '__PADI_DETAIL__'
        assert BeautifulSoup(variant['breadcrumb'], 'html.parser') == crumb
        assert 'Detail proses' in crumb.get_text()
    assert all('fetch(pdfUrl,' not in script for script in data['scripts'].values())


@pytest.mark.parametrize('kind', page.KINDS)
def test_parent_catalogue_requires_actual_dto_code_and_visible_native_report_link(kind):
    # Metadata protocol test only: not an ORM, native reader or role assertion.
    source = '/riwayat-' + kind + '/17'
    root = 'data-riwayat-' + kind
    body = f'''<html data-versi="cap"><div class="bingkai" data-pindah-alamat="{source}" data-pindah-konteks="ctx"><form id="formulir-sesi" data-token="session"></form><main id="isi-halaman"><div class="laporan-riwayat"><section data-laporan-kontrol data-aktif="proses"></section><div class="laporan-isi"><main {root}><header><p class="rhs-code">UNIT</p></header><div class="rhs-actions"><a href="{source}/laporan">PDF proses</a></div></main></div></div></main></div></html>'''.encode()
    context = (dict(d=dict(lot_id=17, kode='UNIT', laporan_tersedia=True)) if kind == 'pengeringan'
               else dict(k=SimpleNamespace(id=17, kode='UNIT')))
    kwargs = dict(origin='https://unit.invalid', cap='cap', konteks='ctx', sesi='session', sumber='a' * 64)
    data = catalog.susun_data(source, body, context, **kwargs)
    assert data and data['entry'] == dict(kind=kind, id=17, kode='UNIT', target=source + '/laporan')
    assert catalog.susun_data(source, body.replace(b'class="rhs-actions"', b'class="rhs-actions" hidden'), context, **kwargs) is None
    assert catalog.susun_data(source, body.replace(b'>UNIT<', b'>OTHER<'), context, **kwargs) is None
    assert catalog.susun_data(source + '?buka=', body, context, **kwargs) is None
    if kind == 'pengeringan':
        context['d']['laporan_tersedia'] = False
        assert catalog.susun_data(source, body, context, **kwargs) is None


def test_completed_dryer_optional_metadata_not_inside_outer_database_session():
    tree = ast.parse((ROOT / 'app/web/layar_riwayat.py').read_text())
    function = next(node for node in tree.body if isinstance(node, ast.AsyncFunctionDef)
                    and node.name == 'detail_riwayat_pengeringan')
    helpers = [node for node in ast.walk(function) if isinstance(node, ast.Await)
               and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
               and node.value.func.id == 'kerangka_detail']
    assert len(helpers) == 1
    outer = [node for node in function.body if isinstance(node, ast.AsyncWith)]
    assert outer and helpers[0].lineno < outer[0].lineno
    assert all(helpers[0] not in list(ast.walk(session)) for session in outer)
    location = next(node for node in ast.walk(function) if isinstance(node, ast.Await)
                    and isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == '_izin_lokasi')
    assert location.lineno < helpers[0].lineno
