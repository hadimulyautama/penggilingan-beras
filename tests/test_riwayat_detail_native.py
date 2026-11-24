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

from app.web.riwayat_detail_native import VARIANTS, deskripsi, kerangka, metadata, back_html, kembali_qc
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
    parent='/riwayat-'+value['jenis'] if variant.startswith('riwayat-') else '/riwayat-qc/'+value['jenis']
    value['back_html']=back_html(metadata(variant),parent,value['jenis'])
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
        expected=env.get_template('_breadcrumb.html').render(rantai=susun(path,dict(kembali=parent,breadcrumb_detail=judul(metadata(variant)['breadcrumb_parts'],'PADI-KODE')),metadata(variant)['title']))
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


@pytest.mark.parametrize('variant,target,raw_context,label', [
    ('riwayat-giling','/riwayat-giling',None,'← Kembali ke Riwayat Penggilingan'),
    ('riwayat-giling','/riwayat-giling?sebelum=20#giling-12',None,'← Kembali ke Riwayat Penggilingan'),
    ('riwayat-sosoh','/riwayat-sosoh',None,'← Kembali ke Riwayat Penyosohan'),
    ('riwayat-pengeringan','/riwayat-pengeringan',None,'← Kembali ke Riwayat Pengeringan'),
    ('riwayat-pengeringan','/pekerjaan?tab=berjalan','/pekerjaan?tab=berjalan','← Kembali ke Pekerjaan'),
    # Native uses raw query truthiness for its label even when href resolver
    # rejects a foreign target. Preserve that display rule, not its URL.
    ('riwayat-pengeringan','/riwayat-pengeringan','https://other.invalid','← Kembali ke Pekerjaan'),
    *[('qc-'+kind,'/riwayat-qc/'+kind,None,'← Kembali ke '+title) for kind,title in [
        ('gabah-basah','Riwayat QC Gabah Basah'),('gabah-kering','Riwayat QC Gabah Kering'),
        ('pk-luar','Riwayat QC PK Luar'),('pk-hasil-giling','Riwayat QC PK Hasil Giling')]],
    *[('qc-'+kind,'/barang-masuk/12?tab=qc',None,'← Kembali ke halaman asal') for kind in (
        'gabah-basah','gabah-kering','pk-luar','pk-hasil-giling')],
    ('qc-beras-hasil-sosoh','/riwayat-qc/beras-hasil-sosoh',None,'← Kembali ke daftar Riwayat QC beras'),
])
def test_body_back_uses_native_anchor_classes_href_text_and_order(variant,target,raw_context,label):
    shape=metadata(variant)
    kind=variant.removeprefix('riwayat-') if variant.startswith('riwayat-') else variant.removeprefix('qc-')
    html=back_html(shape,target,kind,raw_context)
    anchor=BeautifulSoup(html,'html.parser').select_one('a')
    assert anchor.get_text()==label
    assert anchor['href']==target
    native_classes=(['riwayat-detail__back','rhs-back'] if variant=='riwayat-pengeringan' else
                    ['riwayat-detail__back'] if variant.startswith('qc-') and variant!='qc-beras-hasil-sosoh' else ['rhs-back'])
    assert anchor['class']==native_classes
    assert list(anchor.attrs)==['class','href']
    assert '← Kembali ke daftar riwayat' not in html


def test_back_href_autoescapes_and_source_empty_qc_tables_are_not_changed():
    html=back_html(metadata('qc-gabah-basah'),'/barang-masuk/12?cari=a&tab=qc','gabah-basah')
    assert '?cari=a&amp;tab=qc' in html and '<script' not in html
    source=(ROOT/'app/web/templates/_qc_sosoh.html').read_text()
    # These native headers already exist outside tbody loops. This patch does
    # not change native empty rows/values or manufacture a QC sample.
    native=BeautifulSoup(source,'html.parser')
    assert len(native.select('table thead'))==3
    assert all(head.select('th') for head in native.select('table thead'))


@pytest.mark.parametrize('query,referer,expected', [
    ({},'https://uji/pekerjaan?tab=berjalan','/pekerjaan?tab=berjalan'),
    ({'kembali_qc':'/riwayat-qc/pk-luar'},'https://uji/pekerjaan?tab=berjalan','/pekerjaan?tab=berjalan'),
    ({'kembali_qc':'/stok?tab=produk'},'https://uji/pekerjaan','/stok?tab=produk'),
    ({'kembali_qc':'/riwayat-qc/pk-luar'},'https://other.invalid/pekerjaan','/riwayat-qc/pk-luar'),
    ({'kembali_qc':'/pengaturan','kembali_jasa':'/jasa?cari=contoh'},'https://uji/pekerjaan','/jasa?cari=contoh'),
    ({},'https://uji/pengaturan','/riwayat-qc/pk-luar'),
    ({},'https://uji/pelanggan/pekerjaan','/riwayat-qc/pk-luar'),
    ({},'https://uji/riwayat-qc/pk-luar/PK-1','/riwayat-qc/pk-luar'),
    ({},'https://[broken','/riwayat-qc/pk-luar'),
])
def test_qc_return_referer_matches_exact_native_navigation_ast(query,referer,expected):
    from urllib.parse import urlencode, urlsplit
    from app.web.detail_qc import ASAL
    request=Request(dict(type='http',scheme='https',method='GET',path='/riwayat-qc/pk-luar/PK-1',
                         query_string=urlencode(query).encode(),headers=[(b'host',b'uji'),(b'referer',referer.encode())]))
    # Execute only the exact native navigation AST. No synthetic kartu/rounds
    # DTO is fabricated just to call unrelated mean/selection code.
    tree=ast.parse((ROOT/'app/web/detail_qc.py').read_text())
    native=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='konteks')
    q=next(n for n in native.body if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='q' for t in n.targets))
    start=next(i for i,n in enumerate(native.body) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='kembali' for t in n.targets))
    body=native.body[start:start+3]
    assert [type(n) for n in body]==[ast.Assign,ast.For,ast.If]
    function=ast.FunctionDef(name='native_back',args=ast.arguments(posonlyargs=[],args=[ast.arg(arg='request'),ast.arg(arg='jenis')],kwonlyargs=[],kw_defaults=[],defaults=[]),body=[q,*body,ast.Return(value=ast.Name(id='kembali',ctx=ast.Load()))],decorator_list=[])
    program=ast.fix_missing_locations(ast.Module(body=[function],type_ignores=[]))
    scope={'re':re,'urlsplit':urlsplit,'ASAL':ASAL}
    exec(compile(program,'native_detail_qc_navigation','exec'),scope)
    actual=kembali_qc(request,'pk-luar')
    assert actual==expected==scope['native_back'](request,'pk-luar')
    label=BeautifulSoup(back_html(metadata('qc-pk-luar'),actual,'pk-luar'),'html.parser').a.get_text()
    assert label==('← Kembali ke Riwayat QC PK Luar' if actual=='/riwayat-qc/pk-luar' else '← Kembali ke halaman asal')


def test_public_history_navigation_is_inert_until_private_menu_validation():
    spec=importlib.util.spec_from_file_location('history_detail_program_inert',ROOT/'scripts/buat_kerangka_riwayat_detail.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    data=json.JSONDecoder().raw_decode(module.build()[0].decode().split('window.PadiKerangkaRiwayatDetailData=',1)[1])[0]
    for component in data['variants'].values():
        doc=BeautifulSoup(component['html'],'html.parser')
        controls=doc.select('input,select,textarea')
        assert all(node.has_attr('disabled') and not node.has_attr('name') and not node.has_attr('value') for node in controls)


@pytest.mark.parametrize('variant',VARIANTS)
def test_breadcrumb_leaf_uses_actual_native_identity_contract(variant):
    from app.web.breadcrumb import susun
    meta=metadata(variant)
    path=path_for(variant)
    # Only identity scalars. Native QC references are k.ref or qc_kode,
    # neither is a breadcrumb kode. No rounds/results DTO is fabricated.
    ctx=({'breadcrumb_detail':'LOT-17'} if variant.startswith('riwayat-') else
         {'qc_kode':'LOT-17'} if 'beras' in variant else {'k':{'ref':'LOT-17'}})
    native_title=judul(meta['document_parts'],'LOT-17')
    native=susun(path,ctx,native_title)
    own=susun(path,{'breadcrumb_detail':judul(meta['breadcrumb_parts'],'LOT-17')},native_title)
    assert own['items'][-1]==native['items'][-1]
    if variant.startswith('riwayat-'):assert native['items'][-1]['nama']=='LOT-17'
    elif variant!='qc-beras-daftar':assert native['items'][-1]['nama']==native_title

def test_native_qc_callers_do_not_override_breadcrumb_reference_as_kode():
    paths=[ROOT/'app/web/layar_riwayat.py',ROOT/'app/web/riwayat_qc_sosoh.py']
    calls=[]
    for path in paths:
        for call in ast.walk(ast.parse(path.read_text())):
            if (isinstance(call,ast.Call) and isinstance(call.func,ast.Name) and call.func.id=='render_laci'
                and len(call.args)>1 and isinstance(call.args[1],ast.Constant)
                and call.args[1].value in {'riwayat_qc_detail.html','qc_sosoh_riwayat.html'}):
                assert 'breadcrumb_detail' not in {keyword.arg for keyword in call.keywords}
                calls.append(call.args[1].value)
    assert calls.count('riwayat_qc_detail.html')==1
    assert calls.count('qc_sosoh_riwayat.html')==2


@pytest.mark.parametrize('variant',['qc-pk-luar','qc-pk-hasil-giling'])
def test_pk_qc_table_frameworks_are_native_before_any_assessment_is_read(variant):
    from app.web.riwayat_detail_native import qc_pk_table_structure
    shape=qc_pk_table_structure()
    assert len(shape['aggregate'])==6
    assert shape['aggregate'][0]['columns']==['Komponen','Hasil rata-rata QC','Skor / 100']
    assert shape['selected_round']['columns']==['Komponen','Hasil pemeriksaan','Skor / 100']
    assert [v['title'] for v in shape['aggregate']][2:5]==['Aturan skor Kadar air','Aturan skor Butir patah','Aturan skor Susut']
    doc=BeautifulSoup(html_for(variant),'html.parser')
    tables=doc.select('[data-rdn-panel="perhitungan"] table')
    assert len(tables)==6
    assert [[n.get_text() for n in table.select('th')] for table in tables]==[v['columns'] for v in shape['aggregate']]
    round_table=doc.select('[data-rdn-panel="putaran"] table')
    assert len(round_table)==1
    assert [n.get_text() for n in round_table[0].select('th')]==shape['selected_round']['columns']
    assert all('Memuat catatan' in table.tbody.get_text() for table in [*tables,*round_table])
    assert not doc.select('table [data-komponen]')
    for path in ('hmu_tampilan/templates/_penilaian_pk.html','app/services/mutu_pk.py'):
        assert path in metadata(variant)['inputs']

@pytest.mark.parametrize('variant',['qc-gabah-basah','qc-gabah-kering'])
def test_gabah_does_not_advertise_pk_score_tables(variant):
    assert metadata(variant)['qc_tables']=={}
    assert not BeautifulSoup(html_for(variant),'html.parser').select('table')

def test_qc_header_compilation_does_not_call_assessment_or_fabricate_rows():
    tree=ast.parse((ROOT/'app/web/riwayat_detail_native.py').read_text())
    function=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='qc_pk_table_structure')
    source=ast.unparse(function)
    assert 'penilaian_dari_log(' not in source
    assert 'SimpleNamespace' not in source and 'p.nilai' not in source
    assert ".select('th')" in source
