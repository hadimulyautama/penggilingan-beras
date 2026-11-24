"""Kontrak murni dua fase; bukan bukti PG/browser/otorisasi produksi."""
import ast
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request

from app.web.pengeringan_native_html import FASE, TAB, deskripsi, fase_aktif, katalog, kerangka, metadata

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("phase", FASE)
@pytest.mark.parametrize("tab,label", TAB)
def test_native_labels_columns_and_four_tabs_without_values(phase, tab, label):
    value = deskripsi(f"/proses-aktif/{phase}/LOT-FIKTIF", "tab_detail=" + tab)
    value.update(metadata(), stamp="fixture-only")
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block isi %}{% endblock %}"}),
        FileSystemLoader(str(ROOT / "app/web/templates")),
        FileSystemLoader(str(ROOT / "hmu_tampilan/templates")),
    ]), autoescape=select_autoescape())
    html = env.get_template("pengeringan_native_html.html").render(
        DRYER_KERANGKA=value, VERSI="fixture-cap", kembali="/pekerjaan?tab=berjalan")
    doc = BeautifulSoup(html, "html.parser")
    assert doc.h1.get_text() == phase.title() + " aktif"
    assert [t.get_text() for t in doc.select('[role=tab]')] == [v for _, v in TAB]
    assert [p['data-dryer-panel'] for p in doc.select('[role=tabpanel]') if not p.has_attr('hidden')] == [tab]
    for title, columns in metadata()["tables"].items():
        table = doc.select_one(f'table[aria-label="{title}"]')
        assert [n.get_text() for n in table.select('th')] == columns
        assert len(table.select('tbody tr')) == 1 and 'Memuat catatan' in table.tbody.get_text()
    assert not doc.select('form,input,select,textarea,[name],[data-post],[data-kirim]')
    assert '0 kg' not in html and 'Belum ada' not in html
    assert not doc.select('a[href*="buka="],a[href*="/api/"]')
    assert all(b.get('type') == 'button' for b in doc.select('button'))


@pytest.mark.parametrize("query", ["buka=", "nilai=", "buka=kadar_air", "tenant_id=9", "tab_detail=bahan&tab_detail=riwayat", "halaman_ukur=0", "halaman_jeda=-1", "halaman_dingin=abc", "x=" + "a" * 3001, "kembali_kerja=%XX"])
def test_actions_and_non_equivalent_queries_remain_native(query):
    assert deskripsi('/proses-aktif/pengeringan/LOT', query) is None


@pytest.mark.parametrize("query,selected", [("", "ringkasan"), ("halaman_ukur=2", "pengukuran"), ("halaman_dingin=2", "riwayat"), ("halaman_jeda=2", "riwayat"), ("tab_detail=asing&halaman_ukur=2", "pengukuran"), ("tab_detail=bahan&halaman_ukur=2", "bahan")])
def test_native_default_tab_precedence(query, selected):
    assert deskripsi('/proses-aktif/pendinginan/LOT', query)['tab'] == selected


@pytest.mark.parametrize("phase,status,finished,dryer,allowed", [('pengeringan','proses',None,1,True), ('pendinginan','selesai',None,1,True), ('pendinginan','proses',None,1,False), ('pengeringan','selesai',None,1,False), ('pendinginan','selesai','finished',1,False), ('pengeringan','batal',None,1,False), ('pengeringan','proses',None,None,False)])
def test_only_native_active_phase_without_fabricated_rows(phase,status,finished,dryer,allowed):
    assert fase_aktif(phase,status,finished,dryer) is allowed


def test_x_pindah_declines_without_actor_or_database():
    request = Request(dict(type='http',method='GET',path='/proses-aktif/pengeringan/LOT',query_string=b'',headers=[(b'x-pindah',b'1')]))
    assert asyncio.run(kerangka(request,None,jenis='pengeringan',lot=None,db=None)) is None


def row(code='LOT', phase='pengeringan', href=None, hidden=''):
    href=href or f'/proses-aktif/{phase}/{code}'
    return f'<div class="proses-aktif-list__row" data-proses="{phase}" {hidden}><a class="proses-aktif-list__detail" href="{href}"><strong>{code}</strong></a><a class="proses-aktif-list__detail" href="{href}">Detail</a></div>'


def work(rows):
    return '<section data-blok aria-label="Proses aktif"><div class="proses-aktif-list">'+rows+'</div></section>'


def cat(html, **values):
    args=dict(source_address='/pekerjaan?tab=berjalan',cap='fixture-cap',context='fixture-context',session='fixture-session')
    return katalog(html, **(args | values))


def test_catalog_requires_matching_visible_row_and_binds_source_without_database():
    out=cat(work(row()+row('DINGIN','pendinginan')+row('LAIN','giling')))
    assert [(v['kode'],v['fase']) for v in out['entries']] == [('LOT','pengeringan'),('DINGIN','pendinginan')]
    assert out['sumber_sha256'] == hashlib.sha256(b'/pekerjaan?tab=berjalan').hexdigest()
    assert all(set(e)=={'alamat','kode','fase','label'} for e in out['entries'])
    assert cat(work(row(href='/proses-aktif/pengeringan/LAIN')))['entries'] == []
    assert cat(work(row(hidden='hidden')))['entries'] == []
    assert cat(work(row(phase='pendinginan',href='/proses-aktif/pengeringan/LOT')))['entries'] == []
    assert cat(work(row(href='/proses-aktif/pengeringan/LOT?buka=kadar_air')))['entries'] == []
    assert cat(work(row()*51)) is None
    assert cat(work(row()),source_address='/pelanggan/pekerjaan') is None
    assert cat(work(row()),source_address='https://other.invalid/pekerjaan') is None


def test_caller_reuses_original_guards_and_redirect_before_shell_before_aggregates():
    source=(ROOT/'app/web/layar_berjalan.py').read_text()
    start=source.index('async def detail_proses_aktif')
    text=source[start:]
    assert text.index('await (_is_drying_operator') < text.index('kerangka_dryer(request, akun')
    assert text.index('if p.waktu_selesai_pendinginan is not None') < text.index('kerangka_dryer(request, akun')
    assert text.index('kerangka_dryer(request, akun') < text.index('b = await svc.untuk')
    own=(ROOT/'app/web/pengeringan_native_html.py').read_text()
    ast.parse(own)
    assert 'await _is_drying_operator(akun.user, kode_lot=spec["kode"])' in own
    assert 'SiloStorage.drying_lot_id == lot.id' in own
    assert 'is_customer_read(request)' in own
    assert all(term not in own for term in ('await db.commit(', 'await db.flush(', 'SimpleNamespace', 'APIRouter', 'create_all'))


def test_generated_package_exact_data_free_and_bounded():
    spec=importlib.util.spec_from_file_location('drying_compiler',ROOT/'scripts/buat_kerangka_pengeringan.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    payload,manifest=module.build()
    assert payload==(ROOT/'app/web/static/kerangka-pengeringan-ui.js').read_bytes()
    assert manifest==(ROOT/'app/web/static/kerangka-pengeringan-ui.meta.json').read_bytes()
    assert module.build()==(payload,manifest)
    meta=json.loads(manifest)
    for path,sha in meta['inputs'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==sha
    assert len(payload)<=600000
    data=json.loads(payload.decode().split('window.PadiKerangkaPengeringanData=',1)[1].split(';\n',1)[0])
    assert set(data['variants'])==set(FASE)
    for part in data['variants'].values():
        doc=BeautifulSoup(part['html'],'html.parser')
        assert not doc.select('form,input,select,textarea,[name],script[src],link[rel=stylesheet]')
        assert doc.select_one('[data-dryer-native-html]')
    from app.web.breadcrumb import susun
    env=Environment(loader=ChoiceLoader([FileSystemLoader(str(ROOT/'app/web/templates')),FileSystemLoader(str(ROOT/'hmu_tampilan/templates'))]),autoescape=select_autoescape())
    for phase in FASE:
        expected=env.get_template('_breadcrumb.html').render(rantai=susun('/proses-aktif/'+phase+'/PADI-KODE',dict(kembali='/pekerjaan?tab=berjalan',breadcrumb_detail='PADI-KODE'),phase.title()+' aktif'))
        assert data['variants'][phase]['breadcrumb']==expected
        crumb=BeautifulSoup(expected,'html.parser')
        assert [n.get_text(strip=True).lstrip('›') for n in crumb.select('li')]==['Beranda','Pekerjaan','PADI-KODE']
        assert len(crumb.select('.nav-rantai__pemisah'))==2 and crumb.select_one('a.desktop-back')
    js=(ROOT/'app/web/static/pengeringan-native-html.js').read_text()
    assert all(k not in js for k in ('fetch(', 'localStorage', 'sessionStorage', 'history.pushState', 'history.replaceState', 'beforeunload'))
