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
 '/pelanggan/riwayat-giling/12',
 '/pelanggan/riwayat-giling/12?tab_detail=qc&halaman_jeda=2&sebelum=-1#rhs-panel-qc',
])
def test_only_specific_native_read_addresses(value):
    d=deskripsi(value);assert d and d['address']+d['hash']==value

@pytest.mark.parametrize('value',[
 '/pelanggan/proses-aktif/sosoh/POL-1','/pelanggan/stok/pk/detail?id=1',
 '/pelanggan/barang-masuk/1?buka=terima','/pelanggan/barang-masuk/1?pelanggan_id=2&pelanggan_id=3',
 '/pelanggan/barang-masuk/1?tab_detail=qc#panel-qc','/pelanggan/barang-masuk/1?pemilik=pabrik',
 '/pelanggan/proses-aktif/giling/G1?tab_detail=bahan#panel-hasil','/pelanggan/barang-masuk/1?pelanggan_id=0',
 '/pelanggan/barang-masuk/1?tab_detail=%XX','https://other.invalid/pelanggan/barang-masuk/1',
 '/pelanggan/barang-masuk/1?tab_detail=nilai','/pelanggan/barang-masuk/01',
 '/pelanggan/riwayat-giling/0','/pelanggan/riwayat-giling/2147483648',
 '/pelanggan/riwayat-giling/12?tab_detail=tiket','/pelanggan/riwayat-giling/12?tab_detail=qc#panel-qc',
 '/pelanggan/riwayat-giling/12?halaman_hasil=2','/pelanggan/riwayat-giling/12?koreksi=berhasil',
])
def test_other_shapes_actions_and_malformed_addresses_decline(value):assert deskripsi(value) is None

# These are data-transfer samples, not fake ORM, readers or signed-in accounts.
# Collection can only narrow already-read source DTOs and projected links.
def scope():return SimpleNamespace(codes=frozenset({'GIL-UJI'}),resources={'timbangan_transaksi':frozenset({12}),'milling_process':frozenset({12})})
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


def test_closed_giling_list_requires_exact_scoped_native_row_link_and_never_active_kind():
    row=dict(jenis='giling',kode='GIL-UJI',judul='Penggilingan',href='/riwayat-giling/12',berat='PRIVATE-AMOUNT')
    html='<article class="pelanggan-catatan-baris" data-jenis="giling"><h2>Penggilingan</h2><p class="pelanggan-kode">GIL-UJI</p><a class="pelanggan-catatan-buka" href="/pelanggan/riwayat-giling/12">Lihat hasil</a></article>'
    ctx={'catatan':{'rows':[row]}}
    e=entries('portal/riwayat.html',ctx,html,scope())
    assert e==[dict(kind='giling-riwayat',resource='12',code='GIL-UJI',heading='Hasil penggilingan gabah',title='GIL-UJI',targets=['/pelanggan/riwayat-giling/12'])]
    assert 'PRIVATE-AMOUNT' not in json.dumps(e)
    for changed in ({**row,'jenis':'sosoh'},{**row,'kode':'OTHER'},{**row,'href':'/riwayat-giling/13'},
                    {**row,'href':'/proses-aktif/giling/GIL-UJI'},{**row,'href':None}):
        assert entries('portal/riwayat.html',{'catatan':{'rows':[changed]}},html,scope())==[]
    assert entries('portal/riwayat.html',ctx,html.replace('GIL-UJI','OTHER'),scope())==[]
    assert entries('portal/riwayat.html',ctx,html,SimpleNamespace(codes=scope().codes,resources={}))==[]
    assert entries('portal/riwayat.html',{'catatan':{'rows':[]}},html,scope())==[]


def test_closed_giling_detail_publishes_only_same_scoped_finished_native_tabs():
    href='/pelanggan/riwayat-giling/12?tab_detail=qc#rhs-panel-qc'
    html=f'<div class="riwayat-detail pelanggan-detail" data-riwayat-giling><h1>Hasil penggilingan gabah</h1><nav class="rhs-tabs"><a role="tab" href="{href}">QC asal</a><a role="tab" href="/pelanggan/riwayat-giling/13?tab_detail=qc#rhs-panel-qc">Asing</a><a role="tab" href="/pelanggan/proses-aktif/giling/GIL-UJI">Aktif</a></nav></div>'
    ctx={'jenis':'giling','k':SimpleNamespace(id=12,kode='GIL-UJI'),
         'portal_inti_proses':{'kode':'GIL-UJI','status':'Selesai'},'breadcrumb_detail':'GIL-UJI'}
    e=entries('riwayat_giling_detail.html',ctx,html,scope())
    assert e[0]['kind']=='giling-riwayat' and e[0]['resource']=='12' and e[0]['targets']==[href]
    for changed in ({**ctx,'jenis':'sosoh'},{**ctx,'k':SimpleNamespace(id=13,kode='GIL-UJI')},
                    {**ctx,'portal_inti_proses':{'kode':'GIL-UJI','status':'Sedang berjalan'}},
                    {**ctx,'portal_inti_proses':{'kode':'OTHER','status':'Selesai'}}):
        assert entries('riwayat_giling_detail.html',changed,html,scope())==[]

def test_public_compiler_is_exact_bounded_data_free_readonly():
    a,m=compiler().build();assert (a,m)==compiler().build()
    assert a==(ROOT/'app/web/static/kerangka-portal-detail-ui.js').read_bytes()
    meta=json.loads(m);assert meta==json.loads((ROOT/'app/web/static/kerangka-portal-detail-ui.meta.json').read_text())
    assert meta['aset_sha256']==hashlib.sha256(a).hexdigest() and len(a)<49152
    data=json.loads(a.decode().split('window.PadiKerangkaPortalDetailData=')[1].split(';\n')[0])
    assert set(data['variants'])=={'giling','penerimaan','giling-riwayat'}
    for kind,html in data['variants'].items():
        s=BeautifulSoup(html,'html.parser');assert len(s.select('[role=tab]'))==len(TABS[kind])
        assert [x.get_text(strip=True) for x in s.select('[role=tab]')]==[label for _,label in TABS[kind]]
        assert all(n.has_attr('disabled') for n in s.select('[role=tab]'))
        assert not s.select('script,iframe,form,input,[name=_csrf],[data-post],[data-kirim]')
        assert not s.select_one('[data-portal-detail-heading]').get_text()
        assert s.select_one('[data-portal-read-retry]').has_attr('hidden')
        assert '[data-portal-detail-frame] [hidden]{display:none!important}' in s.style.get_text()


def test_closed_family_keeps_active_and_receipt_variant_HTML_byte_identical():
    data=json.loads(compiler().build()[0].decode().split('window.PadiKerangkaPortalDetailData=')[1].split(';\n')[0])
    expected={'giling':'6223c6f3d661c4e8bdc346ea9be9c104adb567f2ac0473101a3147ed1225d71e',
              'penerimaan':'ea145d910aba3fbdbbc3bb98f7ccf1e09b78e65ce7d88189d674fd46d4759eaa'}
    for kind,digest in expected.items():assert hashlib.sha256(data['variants'][kind].encode()).hexdigest()==digest
    closed=BeautifulSoup(data['variants']['giling-riwayat'],'html.parser')
    schema=compiler().closed_giling_schema()
    assert len(closed.select('.rhs-tabs [role=tab]'))==5
    assert closed.select_one('[data-portal-detail-frame].riwayat-detail.rhs')
    assert closed.select_one('style[data-portal-closed-native-style]').string=='\n'.join((ROOT/'app/web/static'/name).read_text() for name in ('riwayat.css','riwayat-sosoh-desain.css'))
    assert [n.get_text(' ',strip=True) for n in closed.select('#rhs-panel-hasil dt')]==schema['result_fields']
    assert [n.get_text(' ',strip=True) for n in closed.select('.riwayat-detail__table-head span')]==schema['columns']
    assert 'ID jasa' not in closed.get_text()
    assert not closed.select('[data-editor-perintah],[data-rhs-edit],form,input,[name],script,iframe')
    assert all(n.get_text(strip=True)=='—' for n in closed.select('dd,strong[aria-label="Belum dibaca"]'))


def test_caller_decoration_follows_native_scope_and_projection_not_early_read():
    route=ast.parse((ROOT/'app/web/portal/routes.py').read_text());read=next(n for n in route.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='read')
    source=ast.get_source_segment((ROOT/'app/web/portal/routes.py').read_text(),read)
    assert source.index('scope=await load_scope(reader)')<source.index('request.state.portal_native_address=')<source.index('req=native_request(request,path,scope)')
    assert 'await own_ticket(scope,tid)' in source and 'await own_model(scope,m[1],m[2],by_code=True)' in source
    closed_guard=[n for n in ast.walk(read) if isinstance(n,ast.Await) and isinstance(n.value,ast.Call)
                  and isinstance(n.value.func,ast.Name) and n.value.func.id=='own_model'
                  and [ast.unparse(a) for a in n.value.args]==['scope','kind','ident']]
    closed_reader=[n for n in ast.walk(read) if isinstance(n,ast.Await) and isinstance(n.value,ast.Call)
                   and isinstance(n.value.func,ast.Name) and n.value.func.id=='fn']
    assert len(closed_guard)==len(closed_reader)==1 and closed_guard[0].lineno<closed_reader[0].lineno
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
 ('giling-riwayat','riwayat_giling_detail.html','riwayat-detail','rhs-panel-'),
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
            if len(v)==len(TABS[kind]) and v[0][0]=='ringkasan':candidates.append(v)
    assert len(candidates)==1
    hrefbase='/proses-aktif/giling/GIL-UJI' if kind=='giling' else '/riwayat-giling/12' if kind=='giling-riwayat' else '/barang-masuk/12'
    nav=''.join(f'<a role="tab" aria-controls="{prefix}{key}" href="{hrefbase}?tab_detail={key}">{label}</a>' for key,label in candidates[0])
    html=f'<main class="{klass}"><header><h1>Source label only</h1></header><nav>{nav}</nav></main>'
    dom=BeautifulSoup(read_only(html,hrefbase),'html.parser')
    assert [a.get_text(strip=True) for a in dom.select('[role=tab]')]==[label for _,label in TABS[kind]]
