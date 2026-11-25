"""Pure user-layout contracts; not a proof of native auth or database scope."""
import ast
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from dataclasses import dataclass
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,DictLoader,Environment,FileSystemLoader,select_autoescape
from starlette.requests import Request
from app.web.pengguna_baca_native import VARIANTS,spesifikasi,kerangka,catat_guard,akun_native,katalog,metadata
ROOT=Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('path,query,kind,search',[
    ('/pengguna','','staf',''),('/pengguna/12','','staf-detail',''),
    ('/pengguna/pelanggan','','pelanggan',''),('/pengguna/pelanggan/12','','pelanggan-detail',''),
    ('/pengguna/pelanggan','cari_akun=%20Budi%20&halaman_akun=2','pelanggan','Budi'),
    ('/pengguna/pelanggan','halaman_akun=0','pelanggan',''),
])
def test_actual_read_paths_only(path,query,kind,search):
    spec=spesifikasi(path,query);assert spec['kind']==kind and spec['search']==search
    assert spec['alamat']==path+('?' +query if query else '')


@pytest.mark.parametrize('path,query',[
    ('/pengguna/buat',''),('/pengguna/reset',''),('/pengguna/pelanggan/kontak',''),('/pengguna/pelanggan/buat',''),
    ('/pengguna/pelanggan/12/status',''),('/pengguna/0',''),('/pengguna/2147483648',''),
    ('/pengguna','ok=1'),('/pengguna/12','err=nama'),('/pengguna/pelanggan','ok=dibuat'),
    ('/pengguna/pelanggan','cari_akun=a&cari_akun=b'),('/pengguna/pelanggan','halaman_akun=xyz'),
    ('/pengguna/pelanggan','cari_akun=%FF'),('/pengguna/pelanggan','company_id=2'),
])
def test_actions_feedback_invalid_queries_remain_native(path,query):assert spesifikasi(path,query) is None


@pytest.mark.parametrize('variant',VARIANTS)
def test_native_fields_disabled_unknown_values_not_false_empty_or_one_time_credentials(variant):
    shape=metadata();kind='staf' if variant in {'staf','staf-super'} else variant
    path='/pengguna' if kind=='staf' else '/pengguna/12' if kind=='staf-detail' else '/pengguna/pelanggan' if kind=='pelanggan' else '/pengguna/pelanggan/12'
    value=spesifikasi(path);value.update(variant=variant,title='Nama fixture' if kind=='staf-detail' else shape['titles'][variant],nama='Nama fixture',customer=variant!='staf',roles=shape['roles'],columns=shape['columns'],stamp='fixture')
    env=Environment(loader=ChoiceLoader([DictLoader({'base.html':'{% block isi %}{% endblock %}'}),FileSystemLoader(str(ROOT/'app/web/templates')),FileSystemLoader(str(ROOT/'hmu_tampilan/templates'))]),autoescape=select_autoescape())
    html=env.get_template('pengguna_baca_native.html').render(PENGGUNA_BACA=value,VERSI='fixture-cap')
    doc=BeautifulSoup(html,'html.parser')
    assert len(doc.select('[data-pengguna-baca-native]'))==1
    assert doc.select_one('[data-pengguna-baca-native]').get('aria-label')==value['title']
    assert not doc.select('form,[name],input[type=hidden],[data-post],[data-kirim]')
    assert all(n.has_attr('disabled') for n in doc.select('input,select,textarea'))
    assert all(n.has_attr('disabled') and n.get('type')=='button' for n in doc.select('button:not([data-pengguna-baca-retry])'))
    assert not any(n.has_attr('value') for n in doc.select('input:not([data-pengguna-cari])'))
    assert 'Semua orang yang aktif sudah punya akun' not in html
    assert 'Belum ada akun pelanggan' not in html
    assert not doc.select('.sandi-awal,[name=_csrf]')
    ids=[n['id'] for n in doc.select('[id]')]
    assert len(ids)==len(set(ids)), 'Pending structure may not duplicate native field IDs'
    for field in doc.select('input,select,textarea'):
        wraps=field.find_parent('label')
        explicit=doc.find_all('label',attrs={'for':field.get('id')}) if field.has_attr('id') else []
        assert (1 if wraps else 0)+len(explicit)==1, str(field)
        label=wraps or explicit[0]
        assert label.get_text(' ',strip=True), 'Every disabled field still needs an actual accessible label'
    assert bool(doc.select('nav[aria-label="Jenis pengguna"] a[href="/pengguna/pelanggan"]'))==(variant!='staf' and variant!='staf-detail')
    if kind.startswith('pelanggan'):
        assert [n.get_text() for n in doc.select('thead th')]==shape['columns']
        assert doc.select_one('tbody td')['colspan']=='5'
    if kind=='staf':assert [n.get_text() for n in doc.select('h2')]==['Daftarkan orang baru','Buatkan akun','Akun yang ada']
    if kind=='staf-detail':
        assert doc.select_one('#peran option[selected]').get_text()=='Peran belum dibaca'
        assert doc.select_one('#mode option[selected]').get_text()=='Jenis perangkat belum dibaca'


def test_reference_roles_and_titles_are_pinned_native_source_not_actor_roles():
    from app.web.pengguna import PERAN
    shape=metadata();assert shape['roles']==[list(row) for row in PERAN]
    assert shape['titles']['staf-detail']=='__PADI_NAMA__'
    for p,digest in shape['inputs'].items():assert hashlib.sha256((ROOT/p).read_bytes()).hexdigest()==digest


def test_caller_dependencies_guards_and_data_negotiation_do_not_enter_writers():
    targets={'app/web/pengguna.py':{'halaman_pengguna','halaman_ubah'},'app/web/portal/admin.py':{'index','detail'}}
    for path,names in targets.items():
        tree=ast.parse((ROOT/path).read_text());seen=set()
        for node in tree.body:
            if not isinstance(node,(ast.AsyncFunctionDef,ast.FunctionDef)):continue
            code=ast.unparse(node)
            if 'await kerangka(' not in code:continue
            assert node.name in names
            assert 'Depends(butuh_super)' in code or 'Depends(super_only)' in code
            assert code.index('catat_guard(')<code.index('await kerangka(')
            seen.add(node.name)
        assert seen==names
    code=(ROOT/'app/web/pengguna.py').read_text().split('async def halaman_ubah',1)[1].split('_ERR_UBAH =',1)[0]
    assert code.index('if a is None:')<code.index('await kerangka(')
    assert 'if not early:' in code and 'if early:' in code
    assert code.count('select(ProduksiAkun)')==1
    own=(ROOT/'app/web/pengguna_baca_native.py').read_text()
    assert not any(n in own for n in ('db.commit(', 'db.flush(', 'PortalAccount(', 'ProduksiAkun(', 'password_hash', 'create_all', 'APIRouter'))
    assert own.index('if not permintaan(request)')<own.index('from sqlalchemy import select')
    original=(ROOT/'app/web/templates/pengguna_pelanggan.html').read_text()
    assert '-kontak1' not in original and '/static/akun-pelanggan.js?v={{ VERSI }}' in original


@dataclass
class PrincipalMarker:
    harus_ganti_sandi:bool=False


def request(actor=None,path='/pengguna',headers=()):
    req=Request(dict(type='http',method='GET',path=path,query_string=b'',headers=list(headers)))
    req.state.akun=actor
    return req


def test_note_is_request_object_bound_not_an_id_or_role_inference():
    actor=PrincipalMarker();other=PrincipalMarker();req=request(actor)
    catat_guard(req,other,'staf');assert not hasattr(req.state,'pengguna_guard_staf')
    catat_guard(req,actor,'staf');assert req.state.pengguna_guard_staf is actor
    assert not akun_native(request(other),actor)
    req.state.portal_scope={};assert not akun_native(req,actor)
    actor.harus_ganti_sandi=True;assert not akun_native(request(actor),actor)


def test_data_get_declines_before_actor_queries_or_metadata():
    req=request(headers=[(b'x-pindah',b'1')])
    assert asyncio.run(kerangka(req,None,jenis='staf')) is None


@pytest.mark.parametrize('method,headers,expected',[
    ('GET',[(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'1')],True),
    ('GET',[(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'0')],False),
    ('GET',[(b'x-pindah',b'1')],False),
    ('GET',[(b'x-kerangka-halaman',b'1')],True),
    ('GET',[],False),
    ('GET',[(b'x-kerangka-halaman',b'true')],False),
    ('GET',[(b'sec-fetch-mode',b'navigate'),(b'sec-fetch-dest',b'document')],True),
    ('GET',[(b'x-pindah',b'1'),(b'sec-fetch-mode',b'navigate'),(b'sec-fetch-dest',b'document')],False),
    ('POST',[(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'1')],False),
])
def test_named_native_sdk_document_data_and_plain_x1_protocol(method,headers,expected):
    from app.web.pengguna_baca_native import permintaan
    req=request(headers=headers);req.scope['method']=method
    assert permintaan(req) is expected


def test_existing_settings_get_already_honors_the_same_explicit_document_protocol():
    from tests.test_pengaturan_menu_native_binding import eligible
    assert eligible('/pengaturan',headers=[(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'1')])
    assert not eligible('/pengaturan',headers=[(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'0')])
    assert not eligible('/pengaturan',headers=[(b'x-pindah',b'1')])
    assert not eligible('/pengaturan',headers=[(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'1')],method='POST')


@pytest.mark.parametrize('path,jenis',[
    ('/pengguna','staf'),('/pengguna/12','staf'),
    ('/pengguna/pelanggan','pelanggan'),('/pengguna/pelanggan/12','pelanggan'),
])
@pytest.mark.parametrize('method,headers',[
    ('GET',[(b'x-pindah',b'1')]),
    ('GET',[(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'0')]),
    ('POST',[(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'1')]),
])
def test_data_or_post_cannot_enter_document_metadata_or_any_resource_read(monkeypatch,path,jenis,method,headers):
    import app.web.pengguna_baca_native as module
    async def forbidden(*args,**kwargs):raise AssertionError('Data request entered optional document work')
    monkeypatch.setattr(module,'pintu_native',forbidden)
    monkeypatch.setattr(module,'metadata',lambda:(_ for _ in ()).throw(AssertionError('Data read entered source metadata')))
    actor=PrincipalMarker();req=request(actor,path,headers=headers);req.scope['method']=method
    catat_guard(req,actor,jenis)
    assert asyncio.run(kerangka(req,actor,jenis=jenis,staff_row=SimpleNamespace(id=12,nama='Fixture'),customer_id=12)) is None


@pytest.mark.parametrize('case',['unknown-actor','portal','forced-password','feedback-query','foreign-route'])
def test_explicit_document_does_not_bypass_native_actor_or_route_boundaries(monkeypatch,case):
    import app.web.pengguna_baca_native as module
    async def forbidden(*args,**kwargs):raise AssertionError('Rejected document entered a native guard/read')
    monkeypatch.setattr(module,'pintu_native',forbidden)
    actor=PrincipalMarker();req=request(actor,headers=[(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'1')])
    catat_guard(req,actor,'staf')
    if case=='unknown-actor':req.state.akun=PrincipalMarker()
    elif case=='portal':req.state.portal_scope={}
    elif case=='forced-password':actor.harus_ganti_sandi=True
    elif case=='feedback-query':req.scope['query_string']=b'ok=1'
    else:req.scope['path']='/pengguna/reset'
    assert asyncio.run(kerangka(req,actor,jenis='staf')) is None


@pytest.mark.parametrize('path,jenis,row',[
    ('/pengguna','staf',None),('/pengguna/12','staf',SimpleNamespace(id=12,nama='Fixture')),
    ('/pengguna/pelanggan','pelanggan',None),
])
def test_sdk_x1_document_enters_existing_admitted_shell_without_extra_business_reader(monkeypatch,path,jenis,row):
    import sys
    import app.web.pengguna_baca_native as module
    from starlette.responses import HTMLResponse
    seen=[]
    async def doors(req,actor):seen.append('existing-native-door-boundary');return dict(staf=True,pelanggan=True)
    async def context(req,actor):seen.append('existing-light-context-boundary');return {}
    def render(req,name,**values):seen.append((name,values['PENGGUNA_BACA']));return HTMLResponse('pure fixture shell')
    monkeypatch.setattr(module,'pintu_native',doors)
    monkeypatch.setitem(sys.modules,'app.web.halaman_bertahap',SimpleNamespace(konteks_kerangka=context,penanda_konteks=lambda *args:'fixture-context'))
    monkeypatch.setitem(sys.modules,'app.web.tampilan',SimpleNamespace(render=render))
    actor=PrincipalMarker();req=request(actor,path,headers=[(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'1')]);catat_guard(req,actor,jenis)
    response=asyncio.run(kerangka(req,actor,jenis=jenis,staff_row=row))
    assert response.status_code==200 and response.headers['Cache-Control']=='private, no-store'
    assert seen[:2]==['existing-native-door-boundary','existing-light-context-boundary']
    assert seen[2][0]=='pengguna_baca_native.html' and seen[2][1]['alamat']==path
    # Customer detail deliberately is not replaced by an ORM stub here: its
    # pre-shell native existence join stays covered by the fixed source proof
    # below, and requires Root's real PG browser Back case for runtime proof.


def test_document_protocol_delta_keeps_existing_resource_guards_and_reader_functions_exact():
    from tests.native_source_oracle import fingerprint
    nodes={n.name:n for n in ast.parse((ROOT/'app/web/pengguna_baca_native.py').read_text()).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
    unchanged={
        'spesifikasi':'72cf5ec487137fd16c4b091ae36986f93c80719890cd7fd7a70b34174bd87323',
        'catat_guard':'4e82c99f002fbd565d7f2233095996b4b18d31b88e3d9edc33f9dff713476fd7',
        'pintu_native':'6d08e7047a0d5f6eb9c326a2c2496ebcb623b211bed4a88de0a9ff1d7f81ac2a',
        'kerangka':'39743c6e05512ec325482b5a872360c30120b52338f0ae0330c4447db85f2344',
        'susun':'33405064cbb89922c2b3b317ee6bf1ea6a4d7598008f9e86b9c6215b5c5319b4',
        '_native_binding':'c87d4ae8c03e8dcc6b4d525f7df7e5241ff599f67ee5cb808fbddc318cfd0c3e',
        'pasang_native':'e89e8f74b27a9253d932436f14ff41ed88897745a74fc74d8a8dec94f057cb48',
    }
    for name,digest in unchanged.items():assert fingerprint(nodes[name])==digest,name
    # Exact installed SDK sends both headers for the document fallback. No
    # SDK/popstate/resource guard is changed to accommodate the application.
    sdk=(ROOT/'hmu_tampilan/static/pindah.js').read_text()
    assert '? { "X-Pindah": "1", "X-Kerangka-Halaman": "1" }' in sdk
    assert ': { "X-Pindah": "1" }' in sdk


def test_actual_guard_functions_are_reused_and_wrong_marker_not_accepted(monkeypatch):
    from app.web import security
    from app.web.portal import admin
    from app.web.pengguna_baca_native import pintu_native
    from fastapi import HTTPException
    actor=PrincipalMarker();req=request(actor);calls=[]
    async def staff(got):assert got is actor;calls.append('staff')
    async def customer(got):assert got is actor;calls.append('customer');raise HTTPException(403,'fixture native denial')
    monkeypatch.setattr(security,'butuh_super',staff);monkeypatch.setattr(admin,'super_only',customer)
    assert asyncio.run(pintu_native(req,actor))=={'staf':True,'pelanggan':False}
    assert asyncio.run(pintu_native(req,actor))=={'staf':True,'pelanggan':False}
    assert calls==['staff','customer','customer']


def permission():
    return dict(versi=1,cap='cap',konteks='context',sesi='session',sumber=__import__('app.web.pengguna_baca_native',fromlist=['aset']).aset()['sumber'],targets={'/pengguna':'staf-super','/pengguna/pelanggan':'pelanggan'})


def test_catalog_requires_actual_native_rows_not_route_shaped_ids_or_hidden_names():
    row='<div class="daftar-standar__baris baris"><div class="baris__isi"><div class="baris__nama">Nama asli fixture</div></div><a href="/pengguna/12">Ubah</a></div>'
    wrap=lambda body:'<div class="daftar-standar">'+body+'</div>'
    cat=lambda html:katalog(html,source_address='/pengguna',permission=permission())
    value=cat(wrap(row));assert value['entries']==[dict(alamat='/pengguna/12',variant='staf-detail',title='Nama asli fixture')]
    assert cat('<a href="/pengguna/12">Ubah</a>')['entries']==[]
    assert cat(wrap(row.replace('class="daftar-standar__baris baris"','class="daftar-standar__baris baris" hidden')))['entries']==[]
    assert cat(wrap(row.replace('/pengguna/12','/pengguna/reset')))['entries']==[]
    assert katalog(wrap(row),source_address='/pengguna',permission={**permission(),'targets':{}}) is None
    many=''.join(row.replace('/12','/'+str(i)) for i in range(1,202));assert cat(wrap(many)) is None


def test_customer_catalog_is_separate_and_keeps_native_page_limit():
    row='<tr><td>Nama pelanggan privat</td><td><a class="btn" href="/pengguna/pelanggan/12">Ubah akun / sandi</a></td></tr>'
    value=katalog('<section class="kelola-portal"><table><tbody>'+row+'</tbody></table></section>',source_address='/pengguna/pelanggan?cari_akun=Nama',permission=permission())
    assert len(value['entries'])==1 and value['entries'][0]['variant']=='pelanggan-detail'
    assert value['entries'][0]['title']==metadata()['titles']['pelanggan-detail']
    assert 'Nama pelanggan privat' not in json.dumps(value)


def test_generated_public_package_is_data_free_bounded_and_current():
    spec=importlib.util.spec_from_file_location('users_compiler',ROOT/'scripts/buat_kerangka_pengguna.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    payload,meta=module.build();assert payload==(ROOT/'app/web/static/kerangka-pengguna-ui.js').read_bytes();assert meta==(ROOT/'app/web/static/kerangka-pengguna-ui.meta.json').read_bytes()
    assert module.build()==(payload,meta) and len(payload)<=262144
    manifest=json.loads(meta)
    for path,digest in manifest['inputs'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==digest
    data=json.loads(payload.decode().split('window.PadiKerangkaPenggunaData=',1)[1].split(';\n',1)[0])
    assert set(data['variants'])==set(VARIANTS)
    for variant,entry in data['variants'].items():
        doc=BeautifulSoup(entry['html'],'html.parser');assert not doc.select('form,[name],input[type=hidden],[data-post],[data-kirim]')
        assert not any(s in entry['html'] for s in ('sandi_awal','password_hash','csrf','Nama asli fixture'))
        assert BeautifulSoup(entry['bar'],'html.parser').select_one('a.bar__balik')
        assert BeautifulSoup(entry['breadcrumb'],'html.parser').select_one('nav.desktop-breadcrumb')
    readonly=(ROOT/'app/web/static/pengguna-baca-native.js').read_text()
    assert not any(s in readonly for s in ('fetch(', 'sessionStorage', 'localStorage', 'history.pushState', 'submit('))


@pytest.mark.parametrize('path,allowed',[('/pengaturan',True),('/pengguna',True),('/pengguna/12',True),('/pengguna/pelanggan',True),('/pengguna/pelanggan/12',True),('/pengaturan/peran',False),('/barang-masuk',False),('/pengguna/pelanggan/kontak',False),('/pelanggan',False)])
def test_private_door_metadata_is_scoped_and_does_not_contain_accounts(path,allowed):
    from app.web.pengguna_baca_native import susun
    actor=PrincipalMarker();req=request(actor,path)
    catat_guard(req,actor,'staf');catat_guard(req,actor,'pelanggan')
    result=asyncio.run(susun(req,actor,registry=dict(cap='cap',konteks='context',sesi='session')))
    assert bool(result)==allowed
    if result:
        assert set(result)=={'versi','cap','konteks','sesi','sumber','targets'}
        assert result['targets']=={'/pengguna':'staf-super','/pengguna/pelanggan':'pelanggan'}
        assert not any(k in json.dumps(result) for k in ('nama','username','user_id','password'))


def test_catalog_overbudget_declines_without_truncating_or_guessing_rows():
    row=lambda i:'<div class="daftar-standar__baris"><div class="baris__nama">'+('&lt;'*200)+'</div><a href="/pengguna/'+str(i)+'">Ubah</a></div>'
    body='<div class="daftar-standar">'+''.join(row(i) for i in range(1,201))+'</div>'
    assert katalog(body,source_address='/pengguna',permission=permission()) is None


@pytest.mark.parametrize('html',[
    '<label>Username</label><input disabled>',
    '<label for="x">Nama</label><input id="x" disabled><input id="x" disabled>',
    '<label for="x">Nama</label><label for="x">Nama kedua</label><input id="x" disabled>',
    '<label><input disabled></label>',
])
def test_compiler_declines_missing_ambiguous_or_duplicate_field_labels(html):
    spec=importlib.util.spec_from_file_location('users_a11y_compiler',ROOT/'scripts/buat_kerangka_pengguna.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    with pytest.raises(ValueError):module.validate_fields(BeautifulSoup(html,'html.parser'))


def test_all_five_compiled_frames_satisfy_actual_installed_sdk_structure_without_extra_visual_heading(monkeypatch):
    spec=importlib.util.spec_from_file_location('users_sdk_frame_compiler',ROOT/'scripts/buat_kerangka_pengguna.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    selector=module.native_frame_selector()
    assert selector=='h1,section[aria-label],[role=region][aria-label]'
    payload,manifest=module.build()
    meta=json.loads(manifest)
    assert 'hmu_tampilan/static/pindah.js' in meta['inputs']
    data=json.loads(payload.decode().split('window.PadiKerangkaPenggunaData=',1)[1].split(';\n',1)[0])
    for variant,component in data['variants'].items():
        doc=BeautifulSoup(component['html'],'html.parser')
        root=doc.select_one('[data-pengguna-baca-native]')
        assert root and root.get('aria-label')==component['title'] and doc.select_one(selector)
        # Preserve native visual heading count. Naming the existing section
        # must not reintroduce a transient extra H1 on the three staff shapes.
        assert len(doc.select('h1'))==(0 if variant.startswith('staf') else 1)
        # A deliberately unnamed, heading-less synthetic negative fails the
        # *same* SDK selector; do not loosen that selector to make it pass.
        for heading in doc.select('h1'):heading.decompose()
        for region in doc.select('section[aria-label],[role=region][aria-label]'):del region['aria-label']
        assert not doc.select_one(selector)
    # Prove the compiler actually enforces the installed selector before it
    # can emit a package, rather than merely recording its source hash.
    monkeypatch.setattr(module,'native_frame_selector',lambda:'#not-a-native-framework')
    with pytest.raises(ValueError,match='SDK cannot recognize'):
        module.build()
