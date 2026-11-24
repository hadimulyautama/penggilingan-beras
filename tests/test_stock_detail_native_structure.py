"""Native source shape and pending-only exceptions; no PG/fake ORM/browser."""
import ast
import hashlib
import json
from pathlib import Path
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, nodes
import pytest
from app.web import stock_detail_native as ui
from tests.test_stock_detail_native import compiler, native_dto_classes, BIND

ROOT=Path(__file__).resolve().parents[1]


def public():
    payload,manifest=compiler().build()
    return json.loads(payload.decode().split('window.PadiKerangkaStockDetailData=',1)[1].split(';\n',1)[0]),json.loads(manifest)


@pytest.mark.parametrize('code,warehouse,bags,expected',[
    ('LOT-FIXTURE','g1',None,'LOT-FIXTURE'),
    ('Giling sendiri · LOT-FIXTURE','g2',None,'LOT-FIXTURE'),
    ('Giling sendiri tanpa separator','g2',None,'Giling sendiri tanpa separator'),
    ('Pemasok fixture · PKB-FIXTURE','g2',None,'Pemasok fixture · PKB-FIXTURE'),
    ('Pemasok fixture · PKB-FIXTURE','g2',12,'Pemasok fixture · PKB-FIXTURE'),
])
def test_actual_native_pk_body_title_differs_from_document_title(monkeypatch,code,warehouse,bags,expected):
    dto=native_dto_classes(monkeypatch)
    card=dto.LotPk(kode=code,tersedia=1500,dihasilkan=2500,dikirim=1000) if warehouse=='g1' else dto.LotPkG2(kode=code,tersedia=600,intake_id=42,jumlah_karung=bags)
    offer=ui.pk_offers([card] if warehouse=='g1' else [],[card] if warehouse=='g2' else [],mutu=False)[0]
    assert offer.body_title==expected
    if offer.meta['variant']!='pk-g2-karung':
        source=(ROOT/'hmu_tampilan/templates/_stok_pk_detail.html').read_text()
        prefix=source[:source.index('<main')]
        h1=source[source.index('<h1>'):source.index('</h1>')+5]
        rendered=Environment().from_string(prefix+h1).render(detail_kartu=card,detail_gudang=warehouse)
        assert BeautifulSoup(rendered,'html.parser').h1.text==offer.body_title
    else:
        assert '<h1>{{ t.kode }}</h1>' in (ROOT/'app/web/templates/stok_pk_karung.html').read_text()
    assert offer.title != offer.body_title


def test_public_warehouse_uses_actual_native_classes_and_no_pk_hero_or_h1():
    data,manifest=public()
    for variant in ('warehouse-g1','warehouse-g2'):
        doc=BeautifulSoup(data['variants'][variant]['html'],'html.parser')
        assert not doc.select('.pk-detail,.produk-detail,.pk-detail__hero,h1,[data-stock-detail-actions]')
        for selector in ['.gudang-ringkasan-alur>.alur-gudang','.alur-gudang__kepala','.alur-tahap','.alur-masuk','.alur-mesin','.alur-silo-area .alur-silos','.alur-stok','.alur-gudang__kaki','[data-blok].daftar-standar']:
            assert doc.select(selector),selector
        assert len(doc.select('[data-blok].daftar-standar'))==2
        assert bool(doc.select('.alur-pengering'))==(variant=='warehouse-g1')
        assert doc.select('template[data-stock-silo-reference] .alur-silo')
        assert not doc.select('[data-silo-id],[data-dryer-id],.alur-alat--terisi')
        assert not doc.select('a[href]')
        assert doc.select_one('style[data-stock-detail-style][data-stock-detail-style-ref]')
    assert 'hmu_tampilan/templates/_beranda_alur.html' in manifest['inputs']
    assert 'hmu_tampilan/static/beranda-alur.css' in manifest['inputs'] or 'app/web/static/beranda-alur.css' in manifest['inputs']
    css=(ROOT/'app/web/static/beranda-alur.css') if (ROOT/'app/web/static/beranda-alur.css').is_file() else ROOT/'hmu_tampilan/static/beranda-alur.css'
    assert list(data['styles'].values())==[css.read_text()]


def test_equipment_shapes_come_from_native_literal_macros_without_dummy_device():
    env=Environment(loader=FileSystemLoader(ROOT/'hmu_tampilan/templates'))
    shapes=compiler().native_shapes(env)
    source=env.loader.get_source(env,'_beranda_alur.html')[0]
    for name,key in [('bentuk_silo','silo'),('bentuk_dryer','dryer')]:
        macro=next(m for m in env.parse(source).find_all(nodes.Macro) if m.name==name)
        literal=''.join(n.data for out in macro.body for n in out.nodes if isinstance(n,nodes.TemplateData))
        assert shapes[key]==literal
        assert 'alur-alat--terisi' not in shapes[key]


def test_product_detail_keeps_native_preopened_fifo_and_actual_packaging_headers():
    data,_=public();native=(ROOT/'hmu_tampilan/templates/_produk_kemasan.html').read_text()
    assert ui.native_table_headers()['product']==[n.text for n in BeautifulSoup(native,'html.parser').select('thead th')]
    for variant in ('product-auto','product-curah','product-packed'):
        doc=BeautifulSoup(data['variants'][variant]['html'],'html.parser')
        assert doc.select_one('.pk-detail.produk-detail section[aria-labelledby="rincian-produk"] .stok-produk-kartu--terbuka details.padat[open] summary.stok-produk-kartu__ringkas')
        assert doc.select_one('details.padat[open]>.anak>.anak__kepala').get_text(' ',strip=True).startswith('Perkiraan asal stok (FIFO)')
        assert [n.text for n in doc.select('.produk-kemasan table thead th')]==ui.native_table_headers()['product']
        assert not doc.select('[data-stock-detail-actions]')
        assert doc.select_one('[data-stock-body-title]')


def test_qc_pending_exception_tracks_real_native_condition_and_does_not_claim_empty():
    source=(ROOT/'hmu_tampilan/templates/_stok_pk_qc.html').read_text();tree=Environment().parse(source)
    guarded=[n for n in tree.find_all(nodes.If) if isinstance(n.test,nodes.Getattr) and isinstance(n.test.node,nodes.Name) and n.test.node.name=='riwayat_qc' and n.test.attr=='rows']
    assert len(guarded)==1 and '<table' in ''.join(n.data for n in guarded[0].find_all(nodes.TemplateData))
    condition=next(n for n in tree.find_all(nodes.CondExpr) if isinstance(n.test,nodes.Getattr) and n.test.attr=='hasil_terbaru_saja')
    headers=ui.native_table_headers()
    assert (headers['qc_latest'],headers['qc_history'])==(condition.expr1.value,condition.expr2.value)
    data,_=public()
    for variant in ('pk-g1','pk-g2-curah','pk-g2-karung'):
        doc=BeautifulSoup(data['variants'][variant]['html'],'html.parser')
        pending=doc.select_one('[data-stock-qc-shape="unread"]')
        assert pending
        assert [n.text for n in pending.select('thead th')]==headers['qc']+['Catatan · menunggu data']
        assert 'belum diketahui kosong atau berisi' in pending.select_one('tbody').text
        assert 'Pencatat & catatan / Catatan lab' not in pending.text
    # Native no-row hides table: intentionally recorded remaining true-empty
    # UX gap. No fake zero/row or changed native expectation closes this gap.
    assert '{% else %}<p class="bantu">Belum ada pemeriksaan QC untuk stok PK ini.</p>' in source


def actual_group():
    return dict(id='g1',nama='PRIVATE GUDANG',fungsi='Selepan',terkunci=False,
        langkah=[dict(nama='Gabah masuk',href='/barang-masuk?gudang=g1',ket='123 proses')],
        masuk=dict(label='Gabah masuk',nilai='98765'),stok=dict(label='Stok PK',nilai='87654'),
        dryers=[dict(nama='PRIVATE TUNGKU',dryers=[dict(id=19,nama='PRIVATE DRYER',terisi=True,kapasitas=54321,bobot='12345 kg',kode='PRIVATE PROCESS')])],
        silos=[dict(id=29,nama='PRIVATE SILO',kg=45678,terisi=True)])


def test_actual_authorized_warehouse_reference_only_and_bounded():
    group=actual_group();offer=ui.warehouse_offer('g1',[group]);assert offer.body_title is None
    assert offer.meta['warehouse_refs']==dict(name='PRIVATE GUDANG',function='Selepan',steps=['Gabah masuk'],dryers=[dict(name='PRIVATE TUNGKU',units=['PRIVATE DRYER'])],silos=['PRIVATE SILO'])
    text=json.dumps(offer.meta)
    for value in ('98765','87654','54321','12345','45678','PRIVATE PROCESS','terisi','kapasitas','bobot','"id"','href'):
        assert value not in text
    group['silos']*=51;assert ui.warehouse_offer('g1',[group]) is None
    group=actual_group();group['dryers'][0]['dryers']*=51;assert ui.warehouse_offer('g1',[group]) is None
    group=actual_group();group['terkunci']=True;assert ui.warehouse_offer('g1',[group]) is None


def test_finish_correlates_current_source_digest_host_to_payload(monkeypatch):
    from types import ModuleType
    from starlette.requests import Request
    from starlette.responses import HTMLResponse
    from app.web.stock_detail_native import Offer
    portal=ModuleType('app.web.portal.scope');portal.is_customer_read=lambda request:False
    monkeypatch.setitem(__import__('sys').modules,'app.web.portal.scope',portal)
    request=Request(dict(type='http',method='GET',path='/stok',query_string=b'',headers=[],scheme='http',server=('fixture.invalid',80),state={}))
    html='''<html data-versi="fixture-cap"><body><div class="bingkai" data-pindah-konteks="fixture-ctx"><div id="formulir-sesi" data-token="fixture-session"></div><main id="isi-halaman"><!-- isi-halaman:mulai --><a class="stok-baris__tautan" href="/stok/pk/detail?gudang=g1&amp;kode=LOT">LOT</a><!-- isi-halaman:akhir --></main></div></body></html>'''
    response=ui.finish(HTMLResponse(html),request,offers=[Offer(('pk','g1','LOT','0',''),ui.metadata('pk-g1'),title='Stok',leaf='Detail PK',body_title='LOT')])
    host=BeautifulSoup(response.body,'html.parser').select_one('#padi-stock-detail-catalog');assert host
    payload=json.loads(host.string)
    assert host['data-source-sha']==payload['asal_sha256']==hashlib.sha256(b'/stok').hexdigest()
    assert payload['entries'][0]['body_title']=='LOT'
    assert payload['entries'][0]['chrome']['title']=='Stok'


def test_pending_calculation_retains_six_actual_native_table_headers_no_dto():
    """Headers render from native literal thead fragments only, no p object."""
    import re
    env=Environment(loader=FileSystemLoader(ROOT/'hmu_tampilan/templates'))
    source=env.loader.get_source(env,'_penilaian_pk.html')[0]
    headers=re.findall(r'<thead>.*?</thead>',source,re.S)
    assert len(headers)==4
    literal=[]
    for header in headers:
        # The one header expression depends only on macro mode (not data).
        assert not any(isinstance(n,nodes.Name) and n.name=='p' for n in env.parse(header).find_all(nodes.Name))
        doc=BeautifulSoup(env.from_string(header).render(tunggal=False),'html.parser')
        literal.append([n.get_text(' ',strip=True) for n in doc.select('th')])
    native_config=ast.parse((ROOT/'app/services/mutu_pk.py').read_text())
    values={n.targets[0].id:ast.literal_eval(n.value) for n in native_config.body if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id in {'ATURAN_ANGKA','KOMPONEN_ANGKA','KOMPONEN_KUALITATIF'}}
    expected=[literal[0],literal[1],*[literal[2] for label in values['ATURAN_ANGKA']],literal[3]]
    assert len(expected)==6
    data,manifest=public()
    for key in ('pk-g1','pk-g2-curah','pk-g2-karung'):
        doc=BeautifulSoup(data['variants'][key]['html'],'html.parser')
        tables=doc.select('[data-stock-qc-calculation]')
        assert [[n.get_text(' ',strip=True) for n in table.select('thead th')] for table in tables]==expected
        assert tables[0]['aria-label']=='Rincian skor enam komponen QC PK'
        assert [n['data-komponen'] for n in tables[0].select('tbody tr')]==[label for label,field in (*values['KOMPONEN_ANGKA'],*values['KOMPONEN_KUALITATIF'])]
        assert [n.get_text(' ',strip=True) for n in doc.select('.penilaian-pk__aturan h3')]==list(values['ATURAN_ANGKA'])
        assert doc.select_one('details.penilaian-pk__pedoman summary').get_text(' ',strip=True)=='Lihat aturan skor dan kelas kualitas'
        assert doc.select_one('.penilaian-pk__rumus strong').text=='Perhitungan nilai kualitas'
        assert 'Perhitungan menunggu data QC terbaru.' in doc.text
        for table in tables:
            for row in table.select('tbody tr'):
                # Real reference labels/ranges only; every operational value
                # or derived score cell remains explicitly unread.
                for td in row.select('td')[1:]:
                    assert 'Belum dibaca' in td.text
                    assert not re.fullmatch(r'[\s0.,%—-]+',td.text)
        assert not doc.select('[data-kod-awal],form,input,script[type="application/json"]')
    assert 'hmu_tampilan/templates/_penilaian_pk.html' in manifest['inputs']
    assert 'app/services/mutu_pk.py' in manifest['inputs']
    public_program=(ROOT/'app/web/static/kerangka-stock-detail-ui.js').read_text()
    assert 'p.nilai' not in public_program and 'penilaian_dari_log(' not in public_program
