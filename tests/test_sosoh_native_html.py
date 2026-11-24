"""Pure proposal contracts only: no PG, native permission or browser proof."""
import ast
import asyncio
from html.parser import HTMLParser
from pathlib import Path

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape

from app.web.sosoh_native_html import (
    TABS, active_schema, deskripsi, kerangka, layout_schema, qc_headers,
)

ROOT = Path(__file__).resolve().parents[1]


class Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))


def schema():
    active = ('spek_fixture_z', 'spek_fixture_a', 'hasil_fixture_x')
    return active_schema(active, ['hasil_fixture_x'],
                         dict(zip(active, ['Beras uji Z', 'Beras uji A', 'Hasil uji X'])),
                         active[:2])


def render(operator=False, tab='ringkasan'):
    spec = deskripsi('/proses-aktif/sosoh/SOSOH-FIXTURE', 'tab_detail=' + tab)
    spec.update(layout_schema(schema(), operator), stamp='fixture-only', qc=qc_headers())
    env = Environment(loader=ChoiceLoader([
        DictLoader({'base.html': '{% block isi %}{% endblock %}',
                    '_panduan.html': '{% macro panel(id,judul,penutup) %}<dialog id="{{id}}"><h2>{{judul}}</h2>{{caller()}}<button type="button" data-sn-guide-close>Tutup panduan</button></dialog>{% endmacro %}'}),
        FileSystemLoader(str(ROOT / 'app/web/templates')),
    ]), autoescape=select_autoescape())
    return env.get_template('sosoh_native_html.html').render(
        SOSOH_KERANGKA=spec, VERSI='fixture-cap', kembali='/pekerjaan?tab=berjalan')


@pytest.mark.parametrize('path,query', [
    ('/proses-aktif/giling/X', ''), ('/proses-sosoh/X', ''),
    ('/proses-aktif/sosoh/', ''), ('/proses-aktif/sosoh/x/y', ''),
    ('/proses-aktif/sosoh/<x>', ''), ('/proses-aktif/sosoh/' + 'x' * 81, ''),
    ('/proses-aktif/sosoh/X', 'buka=hasil'), ('/proses-aktif/sosoh/X', 'nilai=2'),
    ('/proses-aktif/sosoh/X', 'tab_detail=hasil&tab_detail=qc'),
    ('/proses-aktif/sosoh/X', 'tenant_id=1'), ('/proses-aktif/sosoh/X', 'x=' + 'x' * 3001),
])
def test_unsupported_action_or_alias_declines_to_native(path, query):
    assert deskripsi(path, query) is None


def test_descriptor_same_native_address_and_no_context_data():
    address = '/proses-aktif/sosoh/X?tab_detail=hasil&kembali_kerja=%2Fpekerjaan%3Ftab%3Dberjalan'
    result = deskripsi(*address.split('?'))
    assert result['alamat'] == result['data_url'] == address
    assert set(result) == {'kode', 'tab', 'tabs', 'alamat', 'data_url', 'fakta'}
    assert deskripsi('/proses-aktif/sosoh/X', 'tab_detail=unknown')['tab'] == 'ringkasan'


def test_native_active_order_dynamic_labels_without_values():
    rows = schema()
    assert [row['jenis'] for row in rows] == ['spek_fixture_z', 'spek_fixture_a', 'hasil_fixture_x']
    assert all(set(row) == {'jenis', 'nama', 'beras'} for row in rows)
    assert [row['nama'] for row in rows] == ['Beras uji Z', 'Beras uji A', 'Hasil uji X']
    operator = layout_schema(rows, True)
    admin = layout_schema(rows, False)
    assert [row['jenis'] for row in operator['hasil_utama']] == ['spek_fixture_z', 'spek_fixture_a']
    assert operator['hasil_lain'] == rows[2:]
    assert admin['hasil_utama'] == rows and admin['hasil_lain'] == ()
    many = tuple(dict(jenis=str(i), nama=str(i), beras=True) for i in range(8))
    assert layout_schema(many, False)['hasil_utama'] == many[:6]
    with pytest.raises(ValueError):
        layout_schema(rows, 'operator')


@pytest.mark.parametrize('active,historical,labels', [
    ([], [], {}), (['a', 'a'], [], {'a': 'A'}), ([[]], [], {}),
    (['a'], ['inactive'], {'a': 'A'}), (['a'], ['unknown'], {'a': 'A'}),
    (['a'], [], {}), (['a'], [], {'a': ''}),
])
def test_common_active_metadata_rejects_unmerged_tail_or_invalid_master(active, historical, labels):
    assert active_schema(active, historical, labels, []) is None


@pytest.mark.parametrize('operator', [False, True])
@pytest.mark.parametrize('tab,label', TABS)
def test_two_native_layouts_without_fake_initial_data(operator, tab, label):
    html = render(operator, tab)
    tags = Tags()
    tags.feed(html)
    tabs = [a for _, a in tags.tags if a.get('role') == 'tab']
    assert [a['data-sn-tab-pilih'] for a in tabs] == ([] if operator else [k for k, _ in TABS])
    if not operator:
        assert [a['data-sn-tab-pilih'] for a in tabs if a['aria-selected'] == 'true'] == [tab]
    inputs = [a for t, a in tags.tags if t == 'input']
    assert len(inputs) == 3
    assert all('disabled' in a and 'value' not in a and 'name' not in a for a in inputs)
    assert all(a['step'] == '0.01' for a in inputs)
    assert 'Simpan perubahan hasil' in html if operator else 'Catat perubahan hasil' in html
    assert 'data-editor-perintah' in html and 'data-proses-isi' in html
    for forbidden in ['data-sosoh-ringkas', 'sosoh-awal', '<form', 'sosoh-ringkas.js',
                      'qc-sosoh.js', 'koreksi-di-detail.js', '0 kg', 'Belum ada hasil']:
        assert forbidden not in html
    assert 'Status simpan sebelumnya belum diperiksa' in html
    assert 'jangan kirim ulang' in html
    assert 'data-url="/proses-aktif/sosoh/SOSOH-FIXTURE?tab_detail=' + tab + '"' in html
    assert 'Catatan asal pengemasan otomatis' in html


def test_qc_headers_exact_native_and_read_only():
    html = render(False, 'qc')
    headers = qc_headers()
    assert [len(h['columns']) for h in headers] == [3, 5, 6]
    for row in headers:
        assert row['header'] in html
        assert row['title'] in html
    assert 'Catat QC' not in html and 'data-qc-sosoh-form' not in html
    native = (ROOT / 'app/web/static/sosoh-desain.js').read_text()
    for key, label in TABS:
        assert "['" + key + "','" + label + "']" in native
    for label in ['Catat hasil & neraca', 'Periksa & selesaikan penyosohan']:
        assert label in native


def test_native_direct_schema_read_and_scope_preserve_boundary():
    source = (ROOT / 'app/web/sosoh_native_html.py').read_text()
    ast.parse(source)
    assert source.index('await izin(akun.user, spec["kode"])') < source.index('select(PolishingProcess.id, PolishingProcess.status)')
    assert 'batas(akun.user, PolishingProcess)' in source
    assert 'process.status != "proses"' in source
    direct = source[source.index('async def baca_schema_hasil'):source.index('@lru_cache')]
    assert direct.index('historical = await output_sosoh(db, process_id)') < direct.index('active = await p.jenis_hasil(db)')
    assert 'ordered = [*active, *(kind for kind in historical if kind not in active)]' in direct
    assert 'select(' not in direct and 'order_by' not in direct and 'PolishingOutputLog' not in direct
    assert 'active = await jenis_hasil(db)' in source
    assert 'nama_produk(kind)' in source and 'adalah_spek(kind)' in source
    for forbidden in ['.berat_kg', 'await baca(', 'await db.commit(', 'await db.flush(',
                      'SimpleNamespace', 'create_all', 'APIRouter', 'sidik(', 'ringkasan(']:
        assert forbidden not in source


def test_direct_schema_injected_native_reader_order_labels_and_no_values(monkeypatch):
    """Function spies, not fake ORM: native result keys alone cross boundary."""
    import sys
    from types import ModuleType
    from decimal import Decimal
    from app.web.sosoh_native_html import baca_schema_hasil

    calls, db, pid = [], object(), 712
    labels = {'active_b': 'Aktif B', 'active_a': 'Aktif A',
              'legacy_z': 'Historis Z', 'legacy_y': 'Historis Y'}

    class KeysOnly(dict):
        def get(self, *args):
            raise AssertionError('Schema must not read a quantity')
        def values(self):
            raise AssertionError('Schema must not read quantities')
        def items(self):
            raise AssertionError('Schema must not read quantities')

    original = KeysOnly([('legacy_z', Decimal('312.45')), ('active_a', Decimal('18.50')),
                         ('legacy_y', Decimal('6.25'))])

    async def output(session, process_id):
        assert session is db and process_id == pid
        calls.append('native-output')
        return original

    async def active(session):
        assert session is db
        calls.append('native-active')
        return ['active_b', 'active_a']

    def name(kind):
        calls.append(('native-label', kind))
        return labels[kind]

    def rice(kind):
        calls.append(('native-classification', kind))
        return kind in ('active_a', 'legacy_y')

    polishing = ModuleType('app.penggilingan.gudang2.polishing')
    polishing.jenis_hasil, polishing.adalah_spek = active, rice
    package = ModuleType('app.penggilingan.gudang2')
    package.polishing = polishing
    stock = ModuleType('app.services.stok')
    stock.output_sosoh, stock.nama_produk = output, name
    monkeypatch.setitem(sys.modules, 'app.penggilingan.gudang2', package)
    monkeypatch.setitem(sys.modules, 'app.penggilingan.gudang2.polishing', polishing)
    monkeypatch.setitem(sys.modules, 'app.services.stok', stock)
    rows = asyncio.run(baca_schema_hasil(db, pid))
    assert calls[:2] == ['native-output', 'native-active']
    assert [r['jenis'] for r in rows] == ['active_b', 'active_a', 'legacy_z', 'legacy_y']
    assert [r['nama'] for r in rows] == ['Aktif B', 'Aktif A', 'Historis Z', 'Historis Y']
    assert [r['beras'] for r in rows] == [False, True, False, True]
    assert all(set(r) == {'jenis', 'nama', 'beras'} for r in rows)
    assert all('kg' not in r and 'aktif' not in r and 'boleh_catat' not in r for r in rows)
    assert all(('native-label', r['jenis']) in calls and ('native-classification', r['jenis']) in calls for r in rows)
    spec = deskripsi('/proses-aktif/sosoh/SOSOH-FIXTURE')
    spec.update(layout_schema(rows, False), stamp='fixture-only', qc=qc_headers())
    env = Environment(loader=ChoiceLoader([
        DictLoader({'base.html': '{% block isi %}{% endblock %}',
                    '_panduan.html': '{% macro panel(id,judul,penutup) %}<dialog>{{caller()}}</dialog>{% endmacro %}'}),
        FileSystemLoader(str(ROOT/'app/web/templates')),
    ]), autoescape=select_autoescape())
    html = env.get_template('sosoh_native_html.html').render(SOSOH_KERANGKA=spec, VERSI='fixture-cap', kembali='/pekerjaan')
    tags = Tags();tags.feed(html)
    fields = [attrs for tag, attrs in tags.tags if tag == 'input']
    assert len(fields) == 4 and all('disabled' in f and 'value' not in f for f in fields)
    assert 'Historis Z' in html and 'Historis Y' in html and '312.45' not in html and '0 kg' not in html


def test_original_output_aggregate_dependency_is_readonly_and_shared_native_order():
    stock = (ROOT/'app/services/stok.py').read_text()
    many = stock[stock.index('async def output_sosoh_banyak'):stock.index('async def output_sosoh(', stock.index('async def output_sosoh_banyak'))]
    single = stock[stock.index('async def output_sosoh('):stock.index('async def _dipindah_silo_proc')]
    assert 'return (await output_sosoh_banyak(db, [proc_id])).get(proc_id, {})' in single
    assert 'await db.execute(q)' in many and 'q = (select(' in many
    for forbidden in ['db.add(', 'db.delete(', 'db.commit(', 'db.flush(', 'pg_advisory', 'for_update', 'insert(', 'update(', 'delete(']:
        assert forbidden not in many + single
    native = (ROOT/'app/web/form_selesai_penyosohan.py').read_text()
    assert native.index('hasil = await output_sosoh(db, proc.id)') < native.index('pilihan_aktif = await p.jenis_hasil(db)')
    assert 'pilihan = [*pilihan_aktif, *(j for j in hasil if j not in pilihan_aktif)]' in native


def test_native_get_declines_before_actor_database():
    from starlette.requests import Request
    request = Request(dict(type='http', method='GET', path='/proses-aktif/sosoh/FIXTURE',
        raw_path=b'/proses-aktif/sosoh/FIXTURE', query_string=b'', headers=[(b'x-pindah', b'1')],
        scheme='http', server=('fixture.invalid', 80)))
    assert asyncio.run(kerangka(request, None, {})) is None


def test_adapter_never_owns_storage_writer_or_guard():
    source = (ROOT / 'app/web/static/sosoh-native-html.js').read_text()
    for forbidden in ['sessionStorage', 'localStorage', 'beforeunload', 'fetch(',
                      'history.pushState', 'history.replaceState', 'sosoh-awal', 'PadiKoreksiBahan']:
        assert forbidden not in source
    assert 'core.mount({address' in source and 'afterInstall({content})' in source
