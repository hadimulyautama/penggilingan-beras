"""Pure detail presentation contracts. No DB, identities or native readers run."""
import ast,hashlib,importlib.util,json
from pathlib import Path
from types import SimpleNamespace
from bs4 import BeautifulSoup
import pytest
from app.web.portal.detail_catalog import entries
from app.web.portal.detail_kerangka import deskripsi,TABS
ROOT=Path(__file__).resolve().parents[1]

def compiler():
    spec=importlib.util.spec_from_file_location('portal_detail_compiler',ROOT/'scripts/buat_kerangka_portal_detail.py');m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

@pytest.mark.parametrize('value',[
 '/pelanggan/proses-aktif/giling/GIL-UJI',
 '/pelanggan/proses-aktif/giling/GIL-UJI?tab_detail=hasil&halaman_hasil=2#panel-hasil',
 '/pelanggan/barang-masuk/12?pelanggan_id=4&pemilik=jasa&kepemilikan=jasa&tab_detail=tiket',
])
def test_only_specific_native_read_addresses(value):
    d=deskripsi(value);assert d and d['address']+d['hash']==value

@pytest.mark.parametrize('value',[
 '/pelanggan/proses-aktif/sosoh/POL-1','/pelanggan/riwayat-giling/1','/pelanggan/stok/pk/detail?id=1',
 '/pelanggan/barang-masuk/1?buka=terima','/pelanggan/barang-masuk/1?pelanggan_id=2&pelanggan_id=3',
 '/pelanggan/barang-masuk/1?tab_detail=qc#panel-qc','/pelanggan/barang-masuk/1?pemilik=pabrik',
 '/pelanggan/proses-aktif/giling/G1?tab_detail=bahan#panel-hasil','/pelanggan/barang-masuk/1?pelanggan_id=0',
 '/pelanggan/barang-masuk/1?tab_detail=%XX','https://other.invalid/pelanggan/barang-masuk/1',
 '/pelanggan/barang-masuk/1?tab_detail=nilai','/pelanggan/barang-masuk/01',
])
def test_other_shapes_actions_and_malformed_addresses_decline(value):assert deskripsi(value) is None

# These are data-transfer samples, not fake ORM, readers or signed-in accounts.
# Collection can only narrow already-read source DTOs and projected links.
def scope():return SimpleNamespace(codes=frozenset({'GIL-UJI'}),resources={'timbangan_transaksi':frozenset({12})})
def test_giling_catalog_requires_dto_scope_and_exact_projected_link():
    row=dict(jenis='giling',kode='GIL-UJI',judul='Penggilingan gabah',href='/pelanggan/proses-aktif/giling/GIL-UJI',berat='SECRET-AMOUNT',pemilik='SECRET-OWNER')
    ctx={'progres':[row]};html='<article data-kode-proses="GIL-UJI"><h2>Penggilingan gabah</h2><a href="'+row['href']+'">Lihat detail</a></article>'
    e=entries('portal/jasa.html',ctx,html,scope())
    assert e==[dict(kind='giling',resource='GIL-UJI',code='GIL-UJI',heading='Penggilingan gabah',title='GIL-UJI',targets=[row['href']])]
    assert 'SECRET' not in json.dumps(e)
    assert entries('portal/jasa.html',ctx,html.replace('Penggilingan gabah','OTHER'),scope())==[]
    assert entries('portal/jasa.html',ctx,html,SimpleNamespace(codes=frozenset(),resources={}))==[]
    assert entries('portal/jasa.html',ctx,html.replace('GIL-UJI','OTHER'),scope())==[]
    assert entries('portal/jasa.html',{'progres':[{**row,'jenis':'sosoh'}]},html,scope())==[]

def test_receipt_catalog_requires_actual_ticket_row_not_legacy_or_scope_enumeration():
    href='/pelanggan/barang-masuk/12';html=f'<a class="masuk-baris" href="{href}"><span class="masuk-identitas"><small>TKT-UJI</small></span><span class="masuk-jenis">PK</span></a>'
    row=dict(id=12,kode='TKT-UJI',jenis='pk',jenis_nama='PK',jenis_kode='BERAS_PK',href='/barang-masuk/12',berat=999)
    ctx={'daftar_masuk':{'riwayat':[row]}}
    e=entries('portal/masuk.html',ctx,html,scope());assert len(e)==1
    assert e[0]['heading']=='Beras pecah kulit (PK)' and e[0]['title']=='Portal pelanggan'
    for r in ({**row,'id':None},{**row,'id':13},{**row,'href':'/barang-masuk/13'}):assert entries('portal/masuk.html',{'daftar_masuk':{'riwayat':[r]}},html,scope())==[]
    assert entries('portal/masuk.html',ctx,html.replace('TKT-UJI','OTHER'),scope())==[]

def test_native_detail_tabs_only_exact_resource_no_new_target_generation():
    href='/pelanggan/proses-aktif/giling/GIL-UJI?tab_detail=hasil#panel-hasil'
    html=f'<main class="pelanggan-proses-detail-ringkas"><h1>Penggilingan gabah</h1><a role="tab" href="{href}">Hasil &amp; mutu</a><a role="tab" href="/pelanggan/proses-aktif/giling/OTHER?tab_detail=hasil#panel-hasil">Asing</a></main>'
    ctx={'d':{'jenis':'giling','kode':'GIL-UJI'},'portal_inti_proses':{'ringkas_aktif':True,'judul':'Penggilingan gabah'},'breadcrumb_detail':'GIL-UJI'}
    e=entries('detail_giling.html',ctx,html,scope());assert e[0]['targets']==[href] and e[0]['title']=='GIL-UJI'
    assert entries('detail_giling.html',{**ctx,'portal_inti_proses':{}},html,scope())==[]

def test_receipt_detail_uses_native_final_title_and_same_ticket_tabs():
    href='/pelanggan/barang-masuk/12?tab_detail=qc';html=f'<div class="penerimaan-detail"><h1>Gabah kering</h1><a role="tab" href="{href}">Pemeriksaan mutu</a></div>'
    e=entries('barang_masuk_detail_lama.html',{'tiket':{'id':12,'kode':'TKT-UJI'}},html,scope())
    assert e[0]['heading']=='Gabah kering' and e[0]['targets']==[href]
    assert entries('barang_masuk_detail_lama.html',{'tiket':{'id':13,'kode':'TKT-OTHER'}},html,scope())==[]

def test_public_compiler_is_exact_bounded_data_free_readonly():
    a,m=compiler().build();assert (a,m)==compiler().build()
    assert a==(ROOT/'app/web/static/kerangka-portal-detail-ui.js').read_bytes()
    meta=json.loads(m);assert meta==json.loads((ROOT/'app/web/static/kerangka-portal-detail-ui.meta.json').read_text())
    assert meta['aset_sha256']==hashlib.sha256(a).hexdigest() and len(a)<49152
    data=json.loads(a.decode().split('window.PadiKerangkaPortalDetailData=')[1].split(';\n')[0])
    assert set(data['variants'])=={'giling','penerimaan'}
    for kind,html in data['variants'].items():
        s=BeautifulSoup(html,'html.parser');assert len(s.select('[role=tab]'))==4
        assert [x.get_text(strip=True) for x in s.select('[role=tab]')]==[label for _,label in TABS[kind]]
        assert all(n.has_attr('disabled') for n in s.select('[role=tab]'))
        assert not s.select('script,iframe,form,input,[name=_csrf],[data-post],[data-kirim]')
        assert not s.select_one('[data-portal-detail-heading]').get_text()
        assert s.select_one('[data-portal-read-retry]').has_attr('hidden')
        assert '[data-portal-detail-frame] [hidden]{display:none!important}' in s.style.get_text()


def test_caller_decoration_follows_native_scope_and_projection_not_early_read():
    route=ast.parse((ROOT/'app/web/portal/routes.py').read_text());read=next(n for n in route.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='read')
    source=ast.get_source_segment((ROOT/'app/web/portal/routes.py').read_text(),read)
    assert source.index('scope=await load_scope(reader)')<source.index('request.state.portal_native_address=')<source.index('req=native_request(request,path,scope)')
    assert 'await own_ticket(scope,tid)' in source and 'await own_model(scope,m[1],m[2],by_code=True)' in source
    p=(ROOT/'app/web/portal/presentation.py').read_text()
    assert p.index('content=read_only(body,path')<p.index('content=tampilkan_detail(content,ctx,env)')<p.index('content=detail_catalog(request,name,ctx,content)')
    catalog=(ROOT/'app/web/portal/detail_catalog.py').read_text()
    tree=ast.parse(catalog)
    assert not any(isinstance(n,(ast.Import,ast.ImportFrom)) and 'sqlalchemy' in ast.unparse(n) for n in ast.walk(tree))
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id in {'select','SessionLocal'} for n in ast.walk(tree))
    assert 'scope.ids(' not in catalog
    assert 'isinstance(scope,ReadScope)' in catalog and 'request.state.akun.user is not scope.reader' in catalog

@pytest.mark.parametrize('kind,native,klass,prefix',[
 ('giling','detail_giling.html','proses-detail','panel-'),
 ('penerimaan','barang_masuk_detail_lama.html','penerimaan-detail','terima-panel-'),
])
def test_tabs_match_actual_native_literal_labels_after_customer_projection(kind,native,klass,prefix):
    # No native template/reader is faked: extract only the source's literal
    # label list, then apply the real pure customer translation/projection.
    from jinja2 import Environment,nodes
    from app.web.portal.presentation import read_only
    tree=Environment().parse((ROOT/'app/web/templates'/native).read_text())
    candidates=[]
    for n in tree.find_all(nodes.For):
        if isinstance(n.target,nodes.Tuple) and [t.name for t in n.target.items] in (['id','label'],['key','label']):
            try:v=n.iter.as_const()
            except nodes.Impossible:continue
            if len(v)==4 and v[0][0]=='ringkasan':candidates.append(v)
    assert len(candidates)==1
    hrefbase='/proses-aktif/giling/GIL-UJI' if kind=='giling' else '/barang-masuk/12'
    nav=''.join(f'<a role="tab" aria-controls="{prefix}{key}" href="{hrefbase}?tab_detail={key}">{label}</a>' for key,label in candidates[0])
    html=f'<main class="{klass}"><header><h1>Source label only</h1></header><nav>{nav}</nav></main>'
    dom=BeautifulSoup(read_only(html,hrefbase),'html.parser')
    assert [a.get_text(strip=True) for a in dom.select('[role=tab]')]==[label for _,label in TABS[kind]]
