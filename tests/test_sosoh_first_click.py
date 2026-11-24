"""Pure source/build/schema/catalog contracts, not native auth or browser proof."""
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

from bs4 import BeautifulSoup
import pytest
from app.web.sosoh_kerangka_langsung import descriptor
from app.web.sosoh_work_catalog import catalog

ROOT = Path(__file__).resolve().parents[1]
BINDING = dict(source_address='/pekerjaan?tab=berjalan', cap='fixture-cap',
               context='fixture-context', session='fixture-session')
REGISTRY = dict(cap=BINDING['cap'], konteks=BINDING['context'], sesi=BINDING['session'])
SCHEMA = [dict(jenis='spek_fixture_z', nama='Label uji Z', beras=True),
          dict(jenis='samping_fixture_x', nama='Label uji X', beras=False)]


def row(code='SOSOH-FIXTURE', href=None, kind='sosoh', attrs='', anchor=False):
    href = href or '/proses-aktif/sosoh/' + code
    if anchor:
        html = f'<a class="proses-aktif-list__row" data-proses="{kind}" href="{href}" {attrs}><strong>{code}</strong></a>'
    else:
        html = f'<div class="proses-aktif-list__row" data-proses="{kind}" {attrs}><a class="proses-aktif-list__detail" href="{href}"><strong>{code}</strong></a><span>PRIVATE OWNER · BALANCE 4567</span><a class="proses-aktif-list__detail" href="{href}">Detail</a></div>'
    return '<section data-blok aria-label="Proses aktif"><div class="proses-aktif-list">' + html + '</div></section>'


def build():
    spec = importlib.util.spec_from_file_location('test_sosoh_public_compiler', ROOT/'scripts/buat_kerangka_sosoh.py')
    compiler = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(compiler)
    before = set(sys.modules)
    payload, manifest = compiler.build()
    assert not any(n.startswith('app.') for n in set(sys.modules) - before)
    data = json.loads(payload.decode().split('window.PadiKerangkaSosohData=', 1)[1].split(';\n', 1)[0])
    return compiler, payload, json.loads(manifest), data


def test_public_build_is_deterministic_pinned_and_label_free():
    compiler, payload, meta, data = build()
    assert compiler.build()[0] == payload
    assert payload == (ROOT/'app/web/static/kerangka-sosoh-ui.js').read_bytes()
    assert meta == json.loads((ROOT/'app/web/static/kerangka-sosoh-ui.meta.json').read_text())
    assert meta['aset_sha256'] == hashlib.sha256(payload).hexdigest()
    assert meta['variants'] == ['admin', 'operator']
    assert len(payload) < 524288 and len(gzip.compress(payload, mtime=0)) < 40000
    for name, digest in meta['inputs'].items():
        assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest() == digest
    for layout, variant in data['variants'].items():
        doc = BeautifulSoup(variant['html'], 'html.parser')
        native = doc.select_one('[data-sosoh-native-html]')
        assert native['data-layout'] == layout
        assert not native.select('[data-sn-output-kind]')
        prototype = doc.select_one('template[data-sn-output-template]')
        assert prototype.select_one('[data-sn-output-kind]')['data-sn-output-kind'] == ''
        assert prototype.select_one('[data-sn-output-label]').text == ''
        field = prototype.select_one('input')
        assert field.has_attr('disabled') and not field.has_attr('value') and not field.has_attr('name')
        assert not doc.select('form,#sosoh-awal,[data-sosoh-ringkas],input:not([disabled]),script[src],link[rel=stylesheet]')
        assert len(native.select('[role=tab]')) == (5 if layout == 'admin' else 0)
        assert native.select_one('[data-sn-legacy-unread]')
        assert '0 kg' not in variant['html'] and 'Label uji' not in variant['html']
        assert 'Status simpan sebelumnya belum diperiksa' in variant['html']


def test_private_schema_contains_reference_metadata_only():
    data = descriptor(SCHEMA, layout='operator', source='a'*64, registry=REGISTRY)
    assert set(data) == {'versi', 'sumber', 'cap', 'konteks', 'sesi', 'layout', 'hasil'}
    assert data['hasil'] == SCHEMA and data['layout'] == 'operator'
    assert data['cap'] == REGISTRY['cap'] and data['konteks'] == REGISTRY['konteks'] and data['sesi'] == REGISTRY['sesi']


@pytest.mark.parametrize('patch', [
    dict(schema=[]), dict(schema=SCHEMA*2), dict(schema=[{**SCHEMA[0], 'kg': 0}]),
    dict(schema=[{**SCHEMA[0], 'id': 1}]), dict(schema=[{**SCHEMA[0], 'beras': 1}]),
    dict(layout='platform'), dict(source='x'*64), dict(registry={}), dict(registry=None),
    dict(schema=[{**SCHEMA[0], 'nama': 'x'*257}]),
])
def test_private_schema_wrong_or_overbroad_shape_declines(patch):
    args = dict(schema=SCHEMA, layout='admin', source='a'*64, registry=REGISTRY)
    assert descriptor(**{**args, **patch}) is None


def test_native_gate_and_schema_reads_do_not_use_process_or_stock_reader():
    source = (ROOT/'app/web/sosoh_kerangka_langsung.py').read_text()
    assert source.index("await _is_jenis_operator(akun.user, 'penyosohan')") < source.index('async with SessionLocal()')
    assert 'P.operator_saja(akun.user.role)' in source and 'baca_schema_aktif(db)' in source
    assert "is_customer_read(request)" in source and 'portal_scope' in source and 'harus_ganti_sandi' in source
    for forbidden in ['PolishingProcess', 'FinishedGoodsStock', 'output_sosoh', 'ringkasan(', '.commit(', '.flush(']:
        assert forbidden not in source
    native = (ROOT/'app/web/sosoh_native_html.py').read_text()
    common = native[native.index('async def baca_schema_aktif'):native.index('async def baca_schema_hasil')]
    assert 'await jenis_hasil(db)' in common and 'nama_produk(kind)' in common and 'adalah_spek(kind)' in common
    assert 'process_id' not in common and 'select(' not in common and '.berat_kg' not in common


def test_catalog_requires_actual_native_work_row_and_carries_no_data():
    value = catalog(row() + row(kind='giling') + '<a href="/proses-aktif/sosoh/OUTSIDE">outside</a>', **BINDING)
    assert value['entries'] == [dict(alamat='/proses-aktif/sosoh/SOSOH-FIXTURE', kode='SOSOH-FIXTURE', label='Penyosohan aktif')]
    assert set(value) == {'versi', 'cap', 'konteks', 'sesi', 'sumber_sha256', 'entries'}
    assert 'PRIVATE' not in str(value) and '4567' not in str(value)
    assert value['sumber_sha256'] == hashlib.sha256(BINDING['source_address'].encode()).hexdigest()
    assert catalog(row(anchor=True), **BINDING)['entries'] == value['entries']


@pytest.mark.parametrize('href', ['/proses-aktif/sosoh/OTHER', '/proses-aktif/giling/SOSOH-FIXTURE',
    '/proses-aktif/sosoh/SOSOH-FIXTURE?buka=hasil', '/proses-aktif/sosoh/SOSOH-FIXTURE?nilai=2',
    '/proses-aktif/sosoh/SOSOH-FIXTURE?tenant_id=1', '/proses-aktif/sosoh/SOSOH-FIXTURE#hasil',
    '/proses-aktif/sosoh/SOSOH-FIXTURE?tab_detail=hasil&tab_detail=qc', '//external.invalid/proses-aktif/sosoh/SOSOH-FIXTURE'])
def test_unproved_or_action_link_not_catalogued(href):
    assert catalog(row(href=href), **BINDING)['entries'] == []


@pytest.mark.parametrize('wrapper', ['<div hidden>{}</div>', '<div inert>{}</div>',
    '<template>{}</template>', '<div style="visibility:hidden">{}</div>', '<div aria-hidden="true">{}</div>'])
def test_structurally_hidden_catalog_declines(wrapper):
    assert catalog(wrapper.format(row()), **BINDING)['entries'] == []


def test_catalog_limit_scope_and_native_markup_contract():
    html = ''.join(row(code='S-' + str(i)) for i in range(50))
    assert len(catalog(html, **BINDING)['entries']) == 50
    assert catalog(html + row(code='S-51'), **BINDING) is None
    assert catalog(row(), **{**BINDING, 'context': ''}) is None
    assert catalog(row(), **{**BINDING, 'source_address': '/stok'}) is None
    assert catalog(row().replace('data-blok aria-label="Proses aktif"', 'aria-label="Other"'), **BINDING)['entries'] == []
    for path in ('_pekerjaan_berjalan_ringkas.html', 'berjalan.html'):
        native = (ROOT/'app/web/templates'/path).read_text()
        for literal in ['proses-aktif-list__row', 'data-proses="{{ visual.jenis(b) }}"', 'alamat_detail_proses(b)', '<strong>{{ b.kode }}</strong>']:
            assert literal in native


def test_native_caller_early_doc_does_not_change_reader_or_writers():
    source = (ROOT/'app/web/sosoh_ringkas.py').read_text()
    caller = source[source.index('async def halaman('):source.index("@router.get('/api/actions")]
    assert caller.index('await izin(akun.user,kode)') < caller.index('if memakai_dokumen(request)') < caller.index('data=await baca(db,kode)')
    assert 'shell=await kerangka(request,akun,await konteks_kerangka(request,akun))' in caller
    assert 'if shell is not None:return shell' in caller
    runtime = (ROOT/'app/web/static/kerangka-sosoh-ui-runtime.js').read_text()
    for forbidden in ['fetch(', 'sessionStorage', 'localStorage', 'beforeunload', 'history.pushState', 'history.replaceState', 'innerHTML=field.nama']:
        assert forbidden not in runtime
    assert 'label.textContent=field.nama' in runtime
    assert 'inputs[0].hasAttribute(\'value\')' in runtime
