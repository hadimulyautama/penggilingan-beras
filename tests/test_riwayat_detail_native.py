"""Kontrak murni; tidak membuka DB/browser atau membuat model/DTO pengganti."""
import ast
import asyncio
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader, select_autoescape
from starlette.requests import Request

from app.web.riwayat_detail_native import VARIANTS, deskripsi, kerangka, metadata
from app.web.riwayat_detail_catalog import katalog
from app.web.native_detail_chrome import judul, kontrol_bar, bagian_judul

ROOT = Path(__file__).resolve().parents[1]


def path_for(variant):
    return ('/riwayat-' + variant.removeprefix('riwayat-') + '/12' if variant.startswith('riwayat-') else
            '/riwayat-qc/beras-hasil-sosoh' if variant == 'qc-beras-daftar' else
            '/riwayat-qc/' + variant.removeprefix('qc-') + '/KODE-FIKTIF')


def html_for(variant, tab=None, admin=True):
    query = '' if not tab else ('tab_detail=' if variant.startswith('riwayat-') else 'tab_qc=') + tab
    value = deskripsi(path_for(variant), query)
    value.update(meta=metadata(variant), document_title=judul(metadata(variant)['document_parts'], 'KODE-FIKTIF'), kode='KODE-FIKTIF', stamp='fixture-stamp', boleh_koreksi=admin, boleh_qc=admin)
    template = ('riwayat_detail_native.html' if variant.startswith('riwayat-') else
                'qc_beras_native.html' if variant in ('qc-beras-daftar', 'qc-beras-hasil-sosoh') else 'qc_detail_native.html')
    env = Environment(loader=ChoiceLoader([DictLoader({'base.html': '{% block isi %}{% endblock %}'}),
        FileSystemLoader(str(ROOT/'app/web/templates')), FileSystemLoader(str(ROOT/'hmu_tampilan/templates'))]), autoescape=select_autoescape())
    return env.get_template(template).render(DETAIL_RIWAYAT=value, VERSI='fixture-cap', kembali='/riwayat')


@pytest.mark.parametrize('variant', VARIANTS)
def test_native_titles_tabs_source_pins_and_non_writing_structure(variant):
    meta = metadata(variant)
    for path, sha in meta['inputs'].items():
        assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest() == sha
    keys = [t[0] for t in meta['tabs']]
    for key in keys or [None]:
        doc = BeautifulSoup(html_for(variant, key), 'html.parser')
        assert not doc.select('form,[name],[data-post],[data-kirim],a[href*="buka="]')
        assert all(f.has_attr('disabled') and not f.has_attr('value') for f in doc.select('input,select,textarea'))
        assert [n['data-rdn-tab'] for n in doc.select('a[data-rdn-tab]')] == keys
        assert [p['data-rdn-panel'] for p in doc.select('[data-rdn-panel]') if not p.has_attr('hidden')] == ([key] if key else [])
        assert '0 kg' not in str(doc) and 'Belum ada catatan' not in str(doc)
        assert doc.select_one('[data-rdn-status]') and doc.select_one('[data-rdn-retry]')
        if variant != 'qc-beras-daftar':
            assert doc.h1.get_text() == meta['title']
        else:
            assert not doc.select('h1')  # Native daftar memakai heading bilah, bukan H1 baru.


@pytest.mark.parametrize('variant', ('riwayat-giling','riwayat-sosoh','qc-beras-daftar'))
def test_operator_does_not_receive_admin_controls_or_edit_fields(variant):
    doc = BeautifulSoup(html_for(variant, admin=False), 'html.parser')
    assert not doc.select('[data-rdn-privilege],input,textarea')
    assert not any('Koreksi' in n.get_text() for n in doc.select('button'))


@pytest.mark.parametrize('path,query', [('/riwayat-transfer/12',''),('/riwayat-giling/0',''),('/riwayat-giling/2147483648',''),('/riwayat-giling/12','koreksi=berhasil'),('/riwayat-sosoh/12','buka='),('/riwayat-pengeringan/12','nilai=LOT'),('/riwayat-qc/pk-luar/KODE','tab_qc=asal&tab_qc=putaran'),('/riwayat-qc/pk-luar/KODE','company_id=1'),('/riwayat-qc/beras-hasil-sosoh/KODE','buka=qc_sosoh'),('/riwayat-qc/beras-hasil-sosoh','tab_qc=asal'),('/riwayat-qc/gabah-basah',''),('/riwayat-qc/pk-luar/KODE','putaran=-1'),('/riwayat-giling/12','halaman_jeda=0'),('/riwayat-qc/pk-luar/KODE','kembali_qc=%XX')])
def test_other_routes_feedback_actions_and_non_equivalent_query_decline(path,query):
    assert deskripsi(path, query) is None


@pytest.mark.parametrize('query,tab', [('', 'ringkasan'),('halaman_ukur=2','pengukuran'),('halaman_dingin=2','riwayat'),('halaman_jeda=2','riwayat'),('tab_detail=bahan&halaman_ukur=2','bahan')])
def test_drying_native_tab_precedence(query,tab):
    assert deskripsi('/riwayat-pengeringan/12',query)['tab'] == tab


def test_x_pindah_no_actor_and_no_database(monkeypatch):
    import app.web.riwayat_detail_native as module
    def forbidden(*args):raise AssertionError('Native read tidak boleh memuat metadata adapter')
    monkeypatch.setattr(module,'metadata',forbidden)
    r = Request(dict(type='http',method='GET',path='/riwayat-giling/12',query_string=b'',headers=[(b'x-pindah',b'1')]))
    assert asyncio.run(kerangka(r,None)) is None


def catalog(html, source='/riwayat-giling', **options):
    return katalog(html,source_address=source,cap='cap',context='context',session='session',**options)


def history_row(code='GL-1', ident=1, kind='giling', hidden=''):
    return f'<article class="padat" data-rg-proses="{ident}" {hidden}><span class="padat__nama--kode"><a href="/riwayat-{kind}/{ident}">{code}</a></span></article>'


def test_history_catalog_actual_code_doors_bounds_and_no_fabricated_actions():
    wrap = lambda rows:'<div data-daftar-riwayat-proses>'+rows+'</div>'
    out = catalog(wrap(history_row()+history_row()+history_row('GL-2',2)))
    assert len(out['entries']) == 2 and out['batas'] == 30
    assert out['entries'][0] == dict(alamat='/riwayat-giling/1',kode='GL-1',variant='riwayat-giling',boleh_koreksi=False)
    assert catalog(wrap(history_row()),boleh_koreksi=True)['entries'][0]['boleh_koreksi'] is True
    assert not catalog(wrap(history_row(hidden='hidden')))['entries']
    assert catalog(wrap(''.join(history_row('GL-'+str(i),i) for i in range(1,32)))) is None
    assert catalog(wrap(history_row()),source='/pelanggan/riwayat-giling') is None
    assert catalog(wrap(history_row()),source='/riwayat-giling?buka=x') is None
    assert not catalog('<div data-daftar-riwayat-proses><a href="/riwayat-giling/1">FAKE</a></div>')['entries']


def test_qc_catalog_requires_real_kind_reference_and_preserves_native_200_cap():
    def row(code):
        return f'<a class="tabel-standar__baris" href="/riwayat-qc/pk-luar/{code}"><strong class="tabel-standar__kode">{code}</strong></a>'
    wrap=lambda body:'<main data-riwayat-qc>'+body+'</main>'
    out=catalog(wrap(row('PK-1')),source='/riwayat-qc/pk-luar')
    assert out['batas']==200 and out['entries'][0]['kode']=='PK-1'
    assert len(catalog(wrap(''.join(row('PK-'+str(i)) for i in range(200))),source='/riwayat-qc/pk-luar')['entries'])==200
    assert catalog(wrap(''.join(row('PK-'+str(i)) for i in range(201))),source='/riwayat-qc/pk-luar') is None
    assert not catalog(wrap(row('PK-1').replace('>PK-1<','>OTHER<')),source='/riwayat-qc/pk-luar')['entries']
    rice='<main data-riwayat-qc data-rqd-beras><section class="riwayat-detail__card"><h2><a href="/riwayat-qc/beras-hasil-sosoh/SH-1">SH-1</a></h2></section></main>'
    assert catalog(rice,source='/riwayat-qc/beras-hasil-sosoh')['entries'][0]['variant']=='qc-beras-hasil-sosoh'


def test_minimum_resource_predicates_and_call_order_are_native_scoped():
    source=(ROOT/'app/web/riwayat_detail_native.py').read_text()
    for literal in ("model.status == 'selesai'", 'model.waktu_selesai_pendinginan.is_not(None)', 'batas(user, model)', 'PurchaseBatchQcSample.purchase_batch_qc_id == PurchaseBatchQc.id', 'PurchaseBatch.dibatalkan_pada.is_(None)', 'PkPurchaseQcLog.pk_purchase_batch_id == PkPurchaseBatch.id', 'MillingQcLog.milling_process_id == MillingProcess.id', 'SampelQcSosoh.polishing_process_id == PolishingProcess.id'):
        assert literal in source
    assert source.index('if code is None:') < source.index('await konteks_kerangka')
    assert not any(x in source for x in ('db.commit(', 'db.flush(', 'SimpleNamespace', 'data_proses(', 'petakan(', 'riwayat_giling(db'))
    tree=ast.parse((ROOT/'app/web/layar_riwayat.py').read_text())
    for name in ('detail_riwayat_giling','detail_riwayat_pengeringan','halaman_riwayat_qc'):
        function=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name==name)
        text=ast.unparse(function)
        assert text.index('_is_jenis_operator' if name!='halaman_riwayat_qc' else 'if not is_customer_read(request) and (not boleh)') < text.index('await kerangka_detail')
    s=(ROOT/'app/web/layar_sosoh.py').read_text()
    body=s[s.index('async def detail_riwayat_sosoh'):s.index('@router.post("/riwayat-sosoh/{process_id}/koreksi")')]
    assert body.index('await _izin_lokasi') < body.index('await kerangka_detail') and body.index('await _pastikan_akses_sosoh') < body.index('await kerangka_detail')


def test_public_compiler_reproducible_native_source_and_no_records():
    s=importlib.util.spec_from_file_location('public_detail_compiler',ROOT/'scripts/buat_kerangka_riwayat_detail.py')
    m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
    payload,manifest=m.build()
    assert payload==(ROOT/'app/web/static/kerangka-riwayat-detail-ui.js').read_bytes()
    assert manifest==(ROOT/'app/web/static/kerangka-riwayat-detail-ui.meta.json').read_bytes()
    assert m.build()==(payload,manifest)
    pin=json.loads(manifest)
    assert pin['variants']==list(VARIANTS)
    for p,sha in pin['inputs'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==sha
    d=json.loads(payload.decode().split('window.PadiKerangkaRiwayatDetailData=',1)[1].split(';\n',1)[0])
    assert set(d['variants'])==set(VARIANTS)
    assert len(payload)<=800000
    for v in d['variants'].values():
        doc=BeautifulSoup(v['html'],'html.parser')
        assert len(doc.select('[data-riwayat-detail-native]'))==1
        assert not doc.select('form,[name],[data-post],[data-kirim],script[src],link[rel=stylesheet]')
        assert not doc.select('script[type="application/json"]')
    from app.web.breadcrumb import susun
    env=Environment(loader=ChoiceLoader([FileSystemLoader(str(ROOT/'app/web/templates')),FileSystemLoader(str(ROOT/'hmu_tampilan/templates'))]),autoescape=select_autoescape())
    for variant in VARIANTS:
        path=path_for(variant)
        # Compiler memakai id1 untuk struktur; tidak ada ID/catatan nyata.
        if variant.startswith('riwayat-'):path=path.rsplit('/',1)[0]+'/1'
        else:path=path.replace('KODE-FIKTIF','PADI-KODE')
        parent=path.rsplit('/',1)[0] if variant!='qc-beras-daftar' else path
        if variant=='riwayat-giling':parent+='#giling-1'
        expected=env.get_template('_breadcrumb.html').render(rantai=susun(path,dict(kembali=parent,breadcrumb_detail='PADI-KODE'),metadata(variant)['title']))
        assert d['variants'][variant]['breadcrumb']==expected
        crumb=BeautifulSoup(expected,'html.parser')
        assert crumb.select_one('a[href="/"]').get_text()=='Beranda'
        assert crumb.select_one('a.desktop-back') and crumb.select('.nav-rantai__pemisah')
    for name in ('riwayat-detail-native.js','riwayat-detail-katalog.js'):
        code=(ROOT/'app/web/static'/name).read_text()
        assert not any(x in code for x in ('fetch(', 'localStorage', 'sessionStorage', 'history.pushState', 'history.replaceState', 'beforeunload', 'location.assign'))


@pytest.mark.parametrize('variant', VARIANTS)
def test_document_title_native_block_and_mobile_menu_not_generic(variant):
    meta=metadata(variant)
    native=('riwayat_'+variant.removeprefix('riwayat-')+'_detail.html' if variant.startswith('riwayat-')
            else 'qc_sosoh_riwayat.html' if variant in ('qc-beras-daftar','qc-beras-hasil-sosoh')
            else 'riwayat_qc_detail.html')
    own=('riwayat_detail_native.html' if variant.startswith('riwayat-') else
         'qc_beras_native.html' if variant in ('qc-beras-daftar','qc-beras-hasil-sosoh') else 'qc_detail_native.html')
    env=Environment(loader=ChoiceLoader([FileSystemLoader(str(ROOT/'app/web/templates')),FileSystemLoader(str(ROOT/'hmu_tampilan/templates'))]),autoescape=True)
    # Hanya nilai judul skalar; bukan objek domain/DTO pengganti.
    block=re.search(r'{% block judul %}.*?{% endblock %}',(ROOT/'app/web/templates'/native).read_text(),re.S)[0]
    source=env.from_string(block).render(k={'kode':'LOT-17','ref':'LOT-17'},d={'kode':'LOT-17'})
    title=judul(meta['document_parts'],'LOT-17')
    assert title==source
    shell=env.get_template(own)
    assert ''.join(shell.blocks['judul'](shell.new_context(dict(DETAIL_RIWAYAT={'document_title':title}))))==source
    control=BeautifulSoup(kontrol_bar((ROOT/'hmu_tampilan/templates/base.html').read_text(),laporan=True),'html.parser')
    assert control.select_one('button#buka-laci[aria-label="Buka menu"]')
    assert not control.select('.bar__balik')
    if variant.startswith('riwayat-') or variant not in ('qc-beras-daftar','qc-beras-hasil-sosoh'):
        assert 'LOT-17' in title
    else:
        assert title=='QC beras hasil sosoh'


def test_title_source_expression_drift_declines_instead_of_generic_fallback():
    with pytest.raises(ValueError):
        bagian_judul('{% block judul %}{{ akun.nama }}{% endblock %}',{('k','ref'):None})
    with pytest.raises(ValueError):
        bagian_judul('{% block judul %}{{ k.ref|upper }}{% endblock %}',{('k','ref'):None})
