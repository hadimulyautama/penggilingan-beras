"""Pure native-DTO/presentation/build protocol, no PG/browser/permission proof."""
import ast
from dataclasses import dataclass, field
import gzip
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import ModuleType

from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, StrictUndefined
import pytest
from app.web import stock_detail_native as ui
from app.web import stock_detail_catalog as emitter

ROOT=Path(__file__).resolve().parents[1]
BIND=dict(source_address='/stok?tab=bahan', cap='fixture-cap', context='fixture-ctx', session='fixture-session')


def compiler():
    spec=importlib.util.spec_from_file_location('test_stock_detail_compiler', ROOT/'scripts/buat_kerangka_stock_detail.py')
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    return module


def test_compiler_current_deterministic_no_application_import_or_record_values():
    before=set(sys.modules);builder=compiler();payload,manifest=builder.build()
    assert not any(n.startswith('app.') for n in set(sys.modules)-before)
    assert builder.build()==(payload,manifest)
    assert payload==(ROOT/'app/web/static/kerangka-stock-detail-ui.js').read_bytes()
    meta=json.loads(manifest)
    assert meta==json.loads((ROOT/'app/web/static/kerangka-stock-detail-ui.meta.json').read_text())
    assert meta['aset_sha256']==hashlib.sha256(payload).hexdigest()
    for name,digest in meta['inputs'].items():assert hashlib.sha256((ROOT/name).read_bytes()).hexdigest()==digest
    data=json.loads(payload.decode().split('window.PadiKerangkaStockDetailData=',1)[1].split(';\n',1)[0])
    assert list(data['variants'])==list(ui.VARIANTS)
    assert len(payload)<524288 and len(gzip.compress(payload,mtime=0))<40000
    for variant,component in data['variants'].items():
        doc=BeautifulSoup(component['html'],'html.parser')
        assert doc.select_one('[data-stock-detail-native]')['data-variant']==variant
        assert not doc.select('form,input,select,textarea,[data-post],[data-kirim],#lembar,script[src],script[type="application/json"]')
        assert all(n.has_attr('disabled') for n in doc.select('button') if not n.has_attr('data-stock-detail-retry'))
        assert 'Belum dibaca' in component['html'] and '0 kg' not in component['html']
        assert 'Status simpan sebelumnya belum diperiksa' in component['html']


@pytest.mark.parametrize('value', [
    '/stok/pk/detail?gudang=g1&kode=LOT-FIXTURE&jasa=0',
    '/stok/pk/detail?gudang=g2&id=12&jasa=1&pemilik_id=5&gudang_filter=g2',
    '/stok-produk/detail?jenis=spek_fixture&kembali_stok=%2Fstok',
    '/stok-produk-jasa/detail?jenis=hs_fixture&pelanggan_id=12&sumber_page=2',
    '/gudang/g1', '/gudang/g2',
])
def test_exact_native_read_address(value):
    assert ui.address(value) is not None


@pytest.mark.parametrize('value', [
    '/stok/karung/detail?material=x&ukuran=50', '/stok/sumber/barang/1',
    '/stok/pk/detail?gudang=g1&kode=LOT&buka=verify_output',
    '/stok-produk/detail?jenis=x&buka=catat_packing',
    '/stok-produk/detail?jenis=x&sumber_stok=curah',
    '/gudang/g1?buka=aksi', '/gudang/g3', '//outside.invalid/gudang/g1',
    '/stok/pk/detail?gudang=g2&id=-1', '/stok/pk/detail?gudang=g1',
    '/stok/pk/detail?gudang=g1&kode=A&kode=B', '/stok/pk/detail?gudang=g1&kode=A&tenant=1',
    '/stok-produk-jasa/detail?jenis=x', '/stok-produk/detail?jenis=x&pelanggan_id=5',
    '/stok-produk/detail?jenis=x&sumber_page=0', '/gudang/g1#aksi',
])
def test_held_action_or_unproved_address_stays_native(value):
    assert ui.address(value) is None


def native_dto_classes(monkeypatch):
    """Execute exact native dataclass definitions only, not readers/ORM/models."""
    source=(ROOT/'app/services/stok.py').read_text();tree=ast.parse(source)
    classes=[n for n in tree.body if isinstance(n,ast.ClassDef) and n.name in ('LotPk','LotPkG2','RincianProduk','KartuProduk')]
    module=ModuleType('native_stock_dto_fixture');module.__dict__.update(dataclass=dataclass,field=field)
    monkeypatch.setitem(sys.modules,module.__name__,module)
    future=ast.ImportFrom(module='__future__',names=[ast.alias(name='annotations')],level=0)
    code=ast.fix_missing_locations(ast.Module(body=[future,*classes],type_ignores=[]))
    exec(compile(code,str(ROOT/'app/services/stok.py'),'exec'),module.__dict__)
    return module


def test_pk_variant_uses_actual_native_dto_never_url_or_stock_math(monkeypatch):
    dto=native_dto_classes(monkeypatch)
    g1=dto.LotPk(kode='LOT-FIXTURE',tersedia=1500,dihasilkan=2500,dikirim=1000)
    g2=dto.LotPkG2(kode='PKB-FIXTURE',tersedia=600,intake_id=42,jumlah_karung=12)
    offers=ui.pk_offers([g1],[g2],mutu=True)
    assert [o.meta['variant'] for o in offers]==['pk-g1','pk-g2-karung']
    assert offers[1].identity==('pk','g2','42','0','')
    assert '1500' not in str(offers) and '2500' not in str(offers) and '600' not in str(offers)
    g2.jumlah_karung=None
    assert ui.pk_offers([], [g2],mutu=False)[0].meta['variant']=='pk-g2-curah'
    for o in offers:
        assert set(o.meta)=={'variant','mutu','jasa','beras','qc_latest','stages','incoming','stock','warehouse_refs'}


def test_product_variant_and_classification_reuse_native_dto_source(monkeypatch):
    dto=native_dto_classes(monkeypatch);calls=[]
    stock=ModuleType('app.services.stok')
    stock.adalah_beras=lambda kind:calls.append(kind) or kind=='spek_fixture'
    monkeypatch.setitem(sys.modules,'app.services.stok',stock)
    card=dto.KartuProduk(jenis='spek_fixture',nama='PRIVATE PRODUCT NAME',hasil_kg=501,hasil=[],belum_final_kg=201,dikemas_kg=400,curah_kg=101,keluar_kg=50,keluar=[],sisa_kg=451)
    assert ui.product_offer(card).meta['variant']=='product-packed'
    assert ui.product_offer(card).body_title==card.nama
    assert ui.product_offer(card).title=='Detail '+card.nama
    card.curah_saja=True
    assert ui.product_offer(card,customer=5).meta['variant']=='product-curah'
    card.jenis=ui.automatic_kinds()[0]
    offer=ui.product_offer(card)
    assert offer.meta['variant']=='product-auto' and calls[-1]==card.jenis
    assert 'PRIVATE PRODUCT NAME' not in str(offer) and '501' not in str(offer)
    template=(ROOT/'hmu_tampilan/templates/stok_produk_detail.html').read_text()
    for kind in ui.automatic_kinds():assert repr(kind) in template


def test_warehouse_metadata_keeps_actual_reference_labels_but_discards_counts_ids_status():
    actual=[dict(id='g1',nama='PRIVATE WAREHOUSE',fungsi='Selepan',dryers=[],langkah=[dict(nama='Gabah masuk',href='/barang-masuk?gudang=g1',ket='PRIVATE COUNT')],masuk=dict(label='Gabah masuk',nilai='12345'),stok=dict(label='Stok PK',nilai='98765'),silos=[dict(id=99,nama='PRIVATE SILO')])]
    offer=ui.warehouse_offer('g1',actual)
    assert offer.identity==('warehouse','g1') and offer.meta['stages']==['Gabah masuk']
    assert offer.meta['warehouse_refs']==dict(name='PRIVATE WAREHOUSE',function='Selepan',steps=['Gabah masuk'],dryers=[],silos=['PRIVATE SILO'])
    assert '12345' not in str(offer) and '98765' not in str(offer) and '99' not in str(offer)
    assert ui.warehouse_offer('g2',actual) is None
    actual[0]['terkunci']=True
    assert ui.warehouse_offer('g1',actual) is None


def native_html(href='/stok/pk/detail?gudang=g2&id=42&jasa=0',attrs='',cls='stok-baris__tautan'):
    return '<html><body><main id="isi-halaman"><a class="'+cls+'" href="'+href+'" '+attrs+'><strong>PRIVATE LOT</strong><span>PRIVATE OWNER · 12345 kg</span></a></main></body></html>'


def test_catalog_requires_native_link_and_matching_already_read_offer():
    meta=ui.metadata('pk-g2-karung',mutu=True)
    offer=ui.Offer(('pk','g2','42','0',''),meta,body_title='LOT-FIXTURE')
    c=emitter.catalog(native_html(),offers=[offer],**BIND)
    assert [{k:e[k] for k in ('alamat','metadata')} for e in c['entries']]==[dict(alamat='/stok/pk/detail?gudang=g2&id=42&jasa=0',metadata=meta)]
    assert [i['nama'] for i in c['entries'][0]['chrome']['chain']['items']]==['Beranda','Stok','Detail PK beli luar']
    assert 'PRIVATE' not in str(c) and '12345' not in str(c)
    assert c['asal']==BIND['source_address'] and c['asal_sha256']==hashlib.sha256(c['asal'].encode()).hexdigest()
    assert emitter.catalog(native_html(),offers=[],**BIND) is None
    assert emitter.catalog(native_html(cls='invented-link'),offers=[offer],**BIND) is None
    assert emitter.catalog(native_html(attrs='hidden'),offers=[offer],**BIND) is None
    assert emitter.catalog(native_html(attrs='target="_blank"'),offers=[offer],**BIND) is None
    assert emitter.catalog(native_html('/stok/pk/detail?gudang=g2&id=43&jasa=0'),offers=[offer],**BIND) is None


def test_public_structure_native_labels_without_empty_rows_or_false_empty():
    env=Environment(loader=FileSystemLoader(ROOT/'app/web/templates'),undefined=StrictUndefined,autoescape=True)
    shapes=compiler().native_shapes(Environment(loader=FileSystemLoader(ROOT/'hmu_tampilan/templates')))
    for key in ui.VARIANTS:
        meta=ui.metadata(key,mutu=key.startswith('pk-'),jasa=True,qc_latest=True)
        html=env.get_template('stock_detail_native.html').render(STOCK_DETAIL=meta,STOCK_STRUCTURE=ui.structure(meta),STOCK_SHAPES=shapes,STOCK_QC_CALCULATION=compiler().native_qc_calculation(Environment(loader=FileSystemLoader(ROOT/'hmu_tampilan/templates'))),DETAIL_URL='/fixture',DETAIL_STAMP='ctx|/fixture',VERSI='fixture',ACTION_LABELS=['Native allowed action'])
        doc=BeautifulSoup(html,'html.parser')
        assert not doc.select('form,input,select,textarea,script[type="application/json"],a[href]')
        assert all('Belum dibaca'==dd.text for dd in doc.select('dd'))
        assert all(b.has_attr('disabled') for b in doc.select('[data-stock-detail-actions] button'))
        assert '0 kg' not in html and 'Tidak ada stok' not in html
        if key.startswith('product-'):
            assert [n.text for n in doc.select('table th')]==['Bentuk stok / merek','Isi kemasan','Jumlah','Berat','Aksi']
        if key.startswith('pk-'):
            assert doc.select_one('[data-stock-qc-note]').text=='Catatan lab'


@pytest.mark.parametrize('file,names',[
    ('layar_stok.py',['halaman_stok','halaman_stok_pk_jasa','halaman_detail_stok_pk']),
    ('layar_produk.py',['halaman_stok_produk','halaman_stok_produk_jasa','_detail_produk','halaman_stok_semua']),
    ('layar_gudang.py',['halaman_gudang']),
])
def test_original_guard_reader_and_native_render_arguments_unchanged(file,names):
    old=subprocess.check_output(['git','show','88560d9:app/web/'+file],cwd=ROOT,text=True)
    new=(ROOT/'app/web'/file).read_text()
    def presentation_boundary(text,name):
        func=next(n for n in ast.parse(text).body if isinstance(n,ast.AsyncFunctionDef) and n.name==name)
        for i,node in enumerate(func.body):
            value=node.value if isinstance(node,(ast.Return,ast.Assign)) else None
            if isinstance(value,ast.Await):value=value.value
            if isinstance(value,ast.Call) and isinstance(value.func,ast.Name) and value.func.id in ('render','render_laci'):
                return [ast.dump(n,include_attributes=False) for n in func.body[:i]],ast.dump(value,include_attributes=False)
        raise AssertionError('Native render boundary not found')
    for name in names:assert presentation_boundary(old,name)==presentation_boundary(new,name)


def test_adapters_have_no_readers_writers_storage_or_editor_data():
    source=(ROOT/'app/web/stock_detail_native.py').read_text()
    for forbidden in ['SessionLocal','db.execute(','.commit(','.flush(','create_all','SimpleNamespace','FinishedGoodsStock']:
        assert forbidden not in source
    for name in ['stock-detail-native.js','kerangka-stock-detail-ui-runtime.js']:
        program=(ROOT/'app/web/static'/name).read_text()
        for forbidden in ['fetch(','sessionStorage','localStorage','beforeunload','history.pushState','history.replaceState']:
            assert forbidden not in program
    caller=(ROOT/'app/web/kepemilikan_detail.py').read_text()
    assert 'stock_detail_native' not in caller  # Held source/karung controllers unchanged.


def test_direct_document_preserves_paid_native_data_and_has_no_second_reader(monkeypatch):
    """Synthetic HTML protocol plus injected portal guard, not auth/DTO proof."""
    from starlette.requests import Request
    from starlette.responses import HTMLResponse
    portal=ModuleType('app.web.portal.scope');portal.is_customer_read=lambda r:bool(getattr(r.state,'customer',False))
    monkeypatch.setitem(sys.modules,'app.web.portal.scope',portal)
    def request(headers=(),method='GET',state=None):
        return Request(dict(type='http',method=method,path='/stok/pk/detail',query_string=b'gudang=g2&id=42&jasa=0',headers=headers,scheme='http',server=('fixture.invalid',80),state=state or {}))
    html='''<!doctype html><html data-versi="cap-fixture"><body><div class="bingkai" data-pindah-konteks="ctx-fixture"><div id="formulir-sesi" data-token="session-fixture"></div><main id="isi-halaman"><!-- isi-halaman:mulai --><main class="pk-detail"><p>PRIVATE NATIVE RECORD 12345</p><section class="pk-detail__actions"><a href="/native-writer?value=12345">Native existing action</a></section><form method="post" action="/existing-writer"><input value="PRIVATE DRAFT"></form><script src="/static/aksi.js?v=cap-fixture"></script></main><!-- isi-halaman:akhir --></main></div></body></html>'''
    meta=ui.metadata('pk-g2-karung',mutu=False)
    response=ui.finish(HTMLResponse(html),request([(b'x-kerangka-halaman',b'1')]),detail=meta)
    doc=BeautifulSoup(response.body,'html.parser')
    assert not doc.select_one('[data-stock-detail-native]')
    assert 'PRIVATE NATIVE RECORD 12345' in response.body.decode()
    assert doc.select_one('form[action="/existing-writer"] input')['value']=='PRIVATE DRAFT'
    assert doc.select_one('[src="/static/aksi.js?v=cap-fixture"]')
    assert not doc.select('[src*="padi-baca-native"],[src*="stock-detail-native"]')
    metadata=json.loads(doc.select_one('script[data-stock-detail-read]').string)
    assert metadata['metadata']==meta and metadata['alamat']=='/stok/pk/detail?gudang=g2&id=42&jasa=0'
    assert 'PRIVATE' not in str(metadata) and '12345' not in str(metadata)
    # Only an inert metadata host is appended; original native document bytes
    # and all business controls/keys are unchanged, including fresh X-Pindah.
    start=response.body.index(b'<script type="application/json" data-stock-detail-read>')
    end=response.body.index(b'</script>',start)+len(b'</script>')
    assert response.body[:start]+response.body[end:]==html.encode()
    assert response.body.count(b'<!-- isi-halaman:mulai -->')==response.body.count(b'<!-- isi-halaman:akhir -->')==1
    assert response.headers['cache-control']=='private, no-store'
    assert int(response.headers['content-length'])==len(response.body)
    refresh=ui.finish(HTMLResponse(html),request([(b'x-pindah',b'1')]),detail=meta)
    fresh=BeautifulSoup(refresh.body,'html.parser')
    assert not fresh.select('[data-stock-detail-native],[src*="padi-baca-native"]')
    assert fresh.select_one('form[action="/existing-writer"] input')['value']=='PRIVATE DRAFT'
    for req,status in [(request([(b'x-kerangka-halaman',b'1')],method='POST'),200),
                       (request([(b'x-kerangka-halaman',b'1')],state={'customer':True}),200),
                       (request([(b'x-kerangka-halaman',b'1')],state={'portal_scope':object()}),200),
                       (request([(b'x-kerangka-halaman',b'1')]),404)]:
        original=HTMLResponse(html,status_code=status);before=original.body
        assert ui.finish(original,req,detail=meta).body==before
