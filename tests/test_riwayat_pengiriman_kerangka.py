"""Pure presentation contracts only; no ORM/actors/readers/DB are instantiated."""
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, StrictUndefined
import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name, relative):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


page = load('journey_spec_test', 'app/web/riwayat_pengiriman_kerangka.py')
catalog = load('journey_catalog_test', 'app/web/riwayat_pengiriman_catalog.py')
compiler = load('journey_compiler_test', 'scripts/buat_kerangka_riwayat_pengiriman.py')


def env():
    return Environment(loader=ChoiceLoader([DictLoader({'base.html': '{% block isi %}{% endblock %}'}),
        FileSystemLoader([ROOT / 'app/web/templates', ROOT / 'hmu_tampilan/templates'])]),
        autoescape=True, undefined=StrictUndefined)


def metadata(**changes):
    return dict(id=17, kode='UNIT-OUT<&>', status='selesai', title='UNIT PLATE <&>',
                bersama=False, tiket=False, review=False, **changes)


@pytest.mark.parametrize('query', ['', 'status=selesai&q=unit&sejak=2026-11-24',
                                  'status=batal&sebelum=20', 'kembali_kerja=%2Fpekerjaan%3Ftab%3Dberjalan'])
def test_exact_default_read_query_and_native_back(query):
    spec = page.deskripsi('/barang-keluar/17', query)
    assert spec and spec['alamat'] == '/barang-keluar/17' + ('?' + query if query else '')
    assert spec['kembali'] == '/barang-keluar?' + spec['filter_query'] + '#judul-riwayat-keluar'


@pytest.mark.parametrize('query', ['rincian_perintah=1', 'rincian_perintah=0', 'tab_detail=barang',
    'buka=', 'buka=perintah_keluar', 'nilai=', 'tiket=', 'q=a&q=b', 'status=unknown',
    'sejak=2026-02-30', 'sebelum=-1', 'pelanggan_id=0', 'q=%FF', 'q=%XX',
    'kembali_kerja=https%3A%2F%2Felsewhere.invalid', 'unduh=1'])
def test_nonjourney_action_unknown_or_ambiguous_query_declines(query):
    assert page.deskripsi('/barang-keluar/17', query) is None


@pytest.mark.parametrize('path', ['/barang-keluar', '/barang-keluar/0', '/barang-keluar/2147483648',
    '/barang-keluar/17/serah-terima', '/barang-keluar/17/retur', '/barang-keluar/17/koreksi-selesai'])
def test_nondefault_resource_declines(path):
    assert page.deskripsi(path) is None


@pytest.mark.parametrize('headers, expected', [
    ({'sec-fetch-mode': 'navigate', 'sec-fetch-dest': 'document'}, True),
    ({'x-kerangka-halaman': '1'}, True),
    ({'x-pindah': '1', 'x-kerangka-halaman': '1'}, False),
    ({'x-pindah': '1', 'sec-fetch-mode': 'navigate', 'sec-fetch-dest': 'document'}, False),
    ({}, False),
])
def test_explicit_native_get_always_declines_shell(headers, expected):
    from starlette.requests import Request
    request = Request(dict(type='http', method='GET', path='/barang-keluar/17',
                           query_string=b'', headers=[(k.encode(), v.encode()) for k, v in headers.items()]))
    assert page.memakai_dokumen(request) is expected


@pytest.mark.parametrize('status', ['selesai', 'batal'])
@pytest.mark.parametrize('review', [False, True])
@pytest.mark.parametrize('group', [False, True])
def test_native_regions_unknown_is_not_empty_and_actions_inert(status, review, group):
    spec = page.deskripsi('/barang-keluar/17')
    spec.update(stamp='unit|/barang-keluar/17', meta={**metadata(), 'status': status, 'review': review, 'bersama': group})
    doc = BeautifulSoup(env().get_template('riwayat_pengiriman_kerangka.html').render(RP=spec, VERSI='unit'), 'html.parser')
    root = doc.select_one('[data-riwayat-pengiriman-kerangka]')
    assert root and root['data-url'] == spec['alamat']
    assert root.select_one('h1').text == spec['meta']['title']
    assert not doc.select('form,input,select,textarea,[data-post],[data-kirim],[data-item],.rk-customer,table tbody tr')
    assert all(b.has_attr('disabled') for b in doc.select('button:not([data-rp-retry])'))
    assert not doc.select('a[href^="/retur"],a[href*="/perbaikan"],a[href*="/koreksi-selesai"]')
    assert root.select_one('[data-rp-customers]') and 'bukan daftar kosong' in root.get_text()
    assert root.select_one('[data-rp-handover]').has_attr('hidden') is (status != 'selesai')
    assert bool(doc.select_one('.rk-returns')) is review
    assert bool(doc.find('h2', string='Koreksi pascaverifikasi')) is review
    assert [n.text for n in root.select('.rk-quantities dt')] == ['Perintah', 'Dikirim aktual', 'Tidak terkirim']
    assert all(n.text == 'Belum dibaca' for n in root.select('.rk-quantities dd'))
    assert root.select_one('.kontrol-tab [aria-disabled=true]').text == 'Barang Retur'
    if group:
        assert root.select_one('[data-rp-state]').text == 'Keadaan perjalanan belum dibaca'
    assert '0 kg' not in root.get_text() and not root.select('a[role=tab], [role=tabpanel]')


def test_loaded_scalar_protocol_never_invokes_relationship_property():
    # A plain in-memory loaded-state protocol, not an ORM/identity fixture.
    class NoLazy:
        @property
        def kiriman(self):
            raise AssertionError('lazy relationship access')
    loaded = NoLazy()
    loaded.__dict__.update(id=17, kode='UNIT', status='selesai', no_polisi='UNIT PLATE',
                           kiriman_id=23, timbangan_transaksi_id=None)
    assert page.row_metadata(loaded, review=False) is None
    loaded.__dict__['kiriman'] = SimpleNamespace(no_polisi='GROUP UNIT')
    assert page.row_metadata(loaded, review=False)['title'] == 'GROUP UNIT'
    del loaded.__dict__['status']
    assert page.row_metadata(loaded, review=False) is None


@pytest.mark.parametrize('change', [dict(status='dimuat'), dict(id=True), dict(title=''),
    dict(review=1), dict(extra='unexpected')])
def test_metadata_rejects_other_status_or_extra_authority(change):
    assert not page.valid_meta({**metadata(), **change})


def test_navigation_uses_authoritative_native_breadcrumb_and_separate_header_back():
    from app.web.breadcrumb import susun
    address = '/barang-keluar/17?status=selesai&q=unit&sebelum=20'
    spec = page.deskripsi(*address.partition('?')[::2])
    nav = page.navigasi_native(address, 'UNIT', filter_query=spec['filter_query'], header_back='/pekerjaan?tab=berjalan')
    assert nav['body_back'].endswith('#judul-riwayat-keluar')
    assert nav['header_back'] == '/pekerjaan?tab=berjalan'
    assert nav['chrome_back'] == susun(address, dict(filter_query=spec['filter_query']), 'UNIT')['kembali']


def test_generated_package_reproducible_and_source_native_chrome():
    payload, manifest = compiler.build()
    assert (ROOT / 'app/web/static/kerangka-riwayat-pengiriman-ui.js').read_bytes() == payload
    assert (ROOT / 'app/web/static/kerangka-riwayat-pengiriman-ui.meta.json').read_bytes() == manifest
    meta = json.loads(manifest)
    assert hashlib.sha256(payload).hexdigest() == meta['aset_sha256']
    data, _ = json.JSONDecoder().raw_decode(payload.decode().split('window.PadiKerangkaRiwayatPengirimanData=', 1)[1])
    from app.web.breadcrumb import susun
    expected = BeautifulSoup(env().get_template('_breadcrumb.html').render(rantai=susun(
        '/barang-keluar/1', dict(breadcrumb_detail='__PADI_CODE__', PENGIRIMAN_URL='/barang-keluar'), 'UNIT')), 'html.parser')
    for anchor in expected.select('a[href="/barang-keluar"]'):
        anchor['href'] = '__PADI_CHROME_BACK__'
    for variant in data['variants'].values():
        assert BeautifulSoup(variant['breadcrumb'], 'html.parser') == expected
        doc = BeautifulSoup(variant['html'], 'html.parser')
        assert not doc.select('form,input,select,textarea,[data-item],.rk-customer,script[src],link[rel=stylesheet]')
        assert '__PADI_TITLE__' in variant['html']
    assert 'hmu_tampilan/templates/_riwayat_kiriman.html' in meta['inputs']
    assert len(payload) <= 524288


def test_catalogue_binds_visible_native_parent_dto_without_queries():
    # Minimal metadata contract fixture only, no claim about a real native
    # role/ORM/HTTP reader. Root's runtime must prove those separately.
    record = SimpleNamespace(id=17, kode='UNIT', status='selesai', no_polisi='UNIT PLATE',
                             kiriman_id=None, timbangan_transaksi_id=None)
    source = '/barang-keluar?status=selesai'
    target = '/barang-keluar/17?q=&status=selesai&sejak='
    body = f'''<html data-versi="cap"><div class="bingkai" data-pindah-alamat="{source}" data-pindah-konteks="ctx"><form id="formulir-sesi" data-token="session"></form><main id="isi-halaman"><section aria-labelledby="judul-riwayat-keluar"><table><tr data-detail-keluar="{target}"><td><a href="{target}">UNIT</a></td></tr></table></section></main></div></html>'''.encode()
    kwargs = dict(origin='https://unit.invalid', cap='cap', konteks='ctx', sesi='session', sumber='a' * 64)
    context = dict(riwayat=[dict(rec=record)], BOLEH_PERINTAH=False)
    data = catalog.susun_data(source, body, context, **kwargs)
    assert data and data['entries'][0]['target'] == target
    assert data['entries'][0]['meta'] == {**metadata(), 'kode': 'UNIT', 'title': 'UNIT PLATE'}
    for broken in [body.replace(b'<tr ', b'<tr hidden '), body.replace(b'>UNIT<', b'>OTHER<'),
                   body.replace(b'data-token="session"', b'data-token="old"')]:
        assert catalog.susun_data(source, broken, context, **kwargs) is None
    assert catalog.susun_data(source, body, dict(context, BOLEH_PERINTAH=None), **kwargs) is None
    assert catalog.susun_data(source + '&buka=', body, context, **kwargs) is None
