"""Fresh native GET metadata contract; pure stubs are not authority/PG proof."""
import ast
import copy
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from starlette.background import BackgroundTask
from starlette.requests import Request
from starlette.responses import HTMLResponse

from app.web import pengguna_baca_native as ui

ROOT=Path(__file__).resolve().parents[1]
CAP='fixture-cap'
SOURCE='a'*64


def response_fixture(path='/pengaturan',query='',*,status=200):
    actor=SimpleNamespace(harus_ganti_sandi=False)
    request=Request(dict(type='http',method='GET',scheme='https',server=('fixture.invalid',443),
        path=path,query_string=query.encode(),headers=[(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'0')],state={'akun':actor}))
    address=path+('?' +query if query else '')
    rows=''
    if path=='/pengguna':
        rows='<div class="daftar-standar"><div class="daftar-standar__baris"><div class="baris__nama">Nama &lt;fixture&gt;</div><a href="/pengguna/12">Ubah</a><a href="/pengguna/13" hidden>Tersembunyi</a></div></div>'
    elif path=='/pengguna/pelanggan':
        rows='<div class="kelola-portal"><table><tbody><tr><td><a href="/pengguna/pelanggan/12">Ubah</a></td></tr></tbody></table></div>'
    body=('<!doctype html><html data-versi="'+CAP+'"><body><div class="bingkai" data-pindah-alamat="'+address.replace('&','&amp;')+'" data-pindah-konteks="fixture-context"><div id="formulir-sesi" data-token="fixture-session"></div><main id="isi-halaman"><!-- isi-halaman:mulai -->'+rows+'<!-- isi-halaman:akhir --></main></div></body></html>')
    response=HTMLResponse(body,status_code=status,headers={'Vary':'Accept-Language','X-Native-Fixture':'retained'},background=BackgroundTask(lambda:None))
    response.set_cookie('fixture-a','one');response.set_cookie('fixture-b','two')
    response.context=dict(akun=actor,CSRF='fixture-session',PINDAH_KONTEKS='fixture-context',PINDAH_ALAMAT=address)
    return request,actor,response


@pytest.fixture
def native_stubs(monkeypatch):
    import hmu_tampilan
    from app.web import tampilan
    calls=[]
    monkeypatch.setattr(hmu_tampilan,'CAP_ASET',CAP)
    monkeypatch.setattr(ui,'aset',lambda:dict(sumber=SOURCE))
    env=Environment(loader=FileSystemLoader(str(ROOT/'app/web/templates')),autoescape=True,undefined=StrictUndefined)
    monkeypatch.setattr(tampilan,'templates',env)
    async def actual_permission_contract(request,actor):
        calls.append((request,actor));return dict(staf=True,pelanggan=True)
    monkeypatch.setattr(ui,'pintu_native',actual_permission_contract)
    return calls


@pytest.mark.asyncio
@pytest.mark.parametrize('path,query',[
    ('/pengaturan',''),('/pengguna',''),('/pengguna/12',''),
    ('/pengguna/pelanggan',''),('/pengguna/pelanggan/12',''),
    ('/pengguna/pelanggan','cari_akun=Nama&halaman_akun=2'),
])
async def test_fresh_native_handoff_preserves_response_and_binds_exact_private_host(native_stubs,path,query):
    request,actor,response=response_fixture(path,query)
    original=response.body;context=copy.copy(response.context);background=response.background
    cookies=[v for k,v in response.raw_headers if k==b'set-cookie']
    result=await ui.pasang_native(request,actor,response)
    assert result is response and result.status_code==200 and result.background is background
    assert result.context==context and len(native_stubs)==1 and native_stubs[0]==(request,actor)
    assert result.headers['X-Native-Fixture']=='retained'
    assert [v for k,v in result.raw_headers if k==b'set-cookie']==cookies
    assert result.headers['content-length']==str(len(result.body))
    assert result.headers['cache-control']=='private, no-store'
    assert result.headers['vary']=='Accept-Language, Cookie'
    doc=BeautifulSoup(result.body,'html.parser')
    hosts=doc.select('#padi-pengguna-kerangka');assert len(hosts)==1
    host=hosts[0];assert host.get('type')=='application/json'
    permission=json.loads(host.string)
    assert permission==dict(versi=1,cap=CAP,konteks='fixture-context',sesi='fixture-session',sumber=SOURCE,
        targets={'/pengguna':'staf-super','/pengguna/pelanggan':'pelanggan'})
    assert host.get('data-cap')==CAP and host.get('data-konteks')=='fixture-context'
    assert not any(key in permission for key in ('nama','username','user_id','company_id','password','accounts'))
    cats=doc.select('[data-pengguna-native-catalog]')
    if path in {'/pengguna','/pengguna/pelanggan'}:
        assert len(cats)==1
        catalog=json.loads(cats[0].string)
        assert catalog['source_address']==path+('?' +query if query else '')
        assert catalog['entries']==[dict(alamat=path+'/12',variant='staf-detail' if path=='/pengguna' else 'pelanggan-detail',title='Nama <fixture>' if path=='/pengguna' else ui.metadata()['titles']['pelanggan-detail'])]
        assert b'Nama <fixture>' not in result.body
        assert cats[0].get('data-source-sha')==catalog['source_sha256']
    else:assert not cats
    # Exact native bytes on either side stay intact; only the two private
    # metadata scripts are inserted immediately before the native marker.
    start,end=original.split(b'<!-- isi-halaman:akhir -->')
    assert result.body.startswith(start) and result.body.endswith(b'<!-- isi-halaman:akhir -->'+end)
    previous=result.body
    assert await ui.pasang_native(request,actor,result) is result
    assert result.body==previous and len(native_stubs)==1, 'Second decoration must not duplicate or rerun guards'


@pytest.mark.asyncio
@pytest.mark.parametrize('case',[
    'post','not-x1','not-data','settings-query','foreign-route','feedback-query','error','portal','forced-password',
    'actor-mismatch','response-actor-mismatch','address','context','session','cap','missing-marker','duplicate-main',
    'encoded','attachment','not-html','oversized','pending-frame','duplicate-host',
])
async def test_ineligible_or_stale_response_declines_before_optional_permission_read(native_stubs,case):
    request,actor,response=response_fixture()
    if case=='post':request.scope['method']='POST'
    elif case=='not-x1':request.scope['headers']=[(b'x-kerangka-halaman',b'0')]
    elif case=='not-data':request.scope['headers']=[(b'x-pindah',b'1')]
    elif case=='settings-query':request.scope['query_string']=b'err=fixture'
    elif case=='foreign-route':request.scope['path']='/barang-masuk'
    elif case=='feedback-query':request.scope['path']='/pengguna';request.scope['query_string']=b'ok=1'
    elif case=='error':response.status_code=403
    elif case=='portal':request.state.portal_scope={}
    elif case=='forced-password':actor.harus_ganti_sandi=True
    elif case=='actor-mismatch':request.state.akun=SimpleNamespace(harus_ganti_sandi=False)
    elif case=='response-actor-mismatch':response.context['akun']=SimpleNamespace(harus_ganti_sandi=False)
    elif case=='address':response.context['PINDAH_ALAMAT']='/pengguna'
    elif case=='context':response.body=response.body.replace(b'data-pindah-konteks="fixture-context"',b'data-pindah-konteks="stale"')
    elif case=='session':response.body=response.body.replace(b'data-token="fixture-session"',b'data-token="stale"')
    elif case=='cap':response.body=response.body.replace(b'data-versi="fixture-cap"',b'data-versi="stale"')
    elif case=='missing-marker':response.body=response.body.replace(b'<!-- isi-halaman:akhir -->',b'')
    elif case=='duplicate-main':response.body=response.body.replace(b'</body>',b'<main id="isi-halaman"></main></body>')
    elif case=='encoded':response.headers['content-encoding']='gzip'
    elif case=='attachment':response.headers['content-disposition']='attachment'
    elif case=='not-html':response.headers['content-type']='application/json'
    elif case=='oversized':response.body=b'x'*(8*1024*1024+1)
    elif case=='pending-frame':response.body=response.body.replace(b'<main id="isi-halaman">',b'<main id="isi-halaman"><div data-pengaturan-menu-kerangka></div>')
    elif case=='duplicate-host':response.body=response.body.replace(b'</main>',b"<script type='application/json' id='padi-pengguna-kerangka'>{}</script></main>")
    else:raise AssertionError(case)
    original=response.body;headers=list(response.raw_headers);status=response.status_code
    assert await ui.pasang_native(request,actor,response) is response
    assert response.body==original and list(response.raw_headers)==headers and response.status_code==status
    assert not native_stubs


@pytest.mark.asyncio
@pytest.mark.parametrize('case',['no-permission','guard-unavailable','bad-cap','bad-source','empty-targets'])
async def test_optional_metadata_failure_leaves_native_settings_usable(native_stubs,monkeypatch,case):
    request,actor,response=response_fixture()
    if case in {'no-permission','guard-unavailable'}:
        async def declined(*args):
            if case=='guard-unavailable':raise RuntimeError('fixture private detail must not be exposed')
            return dict(staf=False,pelanggan=False)
        monkeypatch.setattr(ui,'pintu_native',declined)
    else:
        async def stale(*args,**kwargs):
            value=dict(versi=1,cap=CAP,konteks='fixture-context',sesi='fixture-session',sumber=SOURCE,targets={'/pengguna':'staf-super'})
            if case=='bad-cap':value['cap']='stale'
            elif case=='bad-source':value['sumber']='b'*64
            else:value['targets']={}
            return value
        monkeypatch.setattr(ui,'susun',stale)
    original=response.body;headers=list(response.raw_headers)
    assert await ui.pasang_native(request,actor,response) is response
    assert response.body==original and list(response.raw_headers)==headers and response.status_code==200


@pytest.mark.asyncio
async def test_metadata_post_addition_budget_declines_without_partial_response_change(native_stubs,monkeypatch):
    from app.web import tampilan
    request,actor,response=response_fixture()
    monkeypatch.setattr(tampilan,'templates',SimpleNamespace(get_template=lambda _:SimpleNamespace(render=lambda **kw:'x'*139265)))
    original=response.body;headers=list(response.raw_headers)
    assert await ui.pasang_native(request,actor,response) is response
    assert response.body==original and list(response.raw_headers)==headers and len(native_stubs)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('super_,admin,recovery,memo,targets,reads',[
    (True,True,False,False,{'/pengguna':'staf-super','/pengguna/pelanggan':'pelanggan'},0),
    (False,True,True,False,{'/pengguna':'staf'},1),
    (False,True,False,False,None,1),
    (False,False,False,False,None,0),
    (False,True,True,True,{'/pengguna':'staf'},0),
])
async def test_actual_native_guard_body_and_same_request_memo_keep_door_read_cost_bounded(monkeypatch,super_,admin,recovery,memo,targets,reads):
    import sys
    # Import the unchanged native customer guard before replacing only the
    # staff guard module with its exact-body callback harness.
    from app.web.portal import admin as native_customer_guard
    from tests.test_pengaturan_alat_kerangka import native_guard
    security,calls=native_guard(recovery)
    monkeypatch.setitem(sys.modules,'app.web.security',security)
    monkeypatch.setattr(ui,'aset',lambda:dict(sumber=SOURCE))
    actor=SimpleNamespace(is_super=super_,is_admin=admin,harus_ganti_sandi=False)
    request=Request(dict(type='http',method='GET',path='/pengaturan',query_string=b'',headers=[],state={'akun':actor}))
    if memo:ui.catat_guard(request,actor,'staf')
    result=await ui.susun(request,actor,registry=dict(cap=CAP,konteks='fixture-context',sesi='fixture-session'))
    assert (result['targets'] if result else None)==targets and len(calls)==reads
    # A successful same-request predicate is memoized on the exact actor.
    if result:
        await ui.susun(request,actor,registry=dict(cap=CAP,konteks='fixture-context',sesi='fixture-session'))
        assert len(calls)==reads


def ast_shape(value):
    if isinstance(value,ast.AST):return [type(value).__name__,[[k,ast_shape(x)] for k,x in ast.iter_fields(value) if k not in {'lineno','end_lineno','col_offset','end_col_offset'} and not (k=='type_params' and not x)]]
    if isinstance(value,list):return [ast_shape(x) for x in value]
    if value is Ellipsis:return ['literal','Ellipsis']
    if isinstance(value,bytes):return ['literal-bytes',value.hex()]
    if isinstance(value,complex):return ['literal-complex',repr(value)]
    return value


def ast_fingerprint(node):
    return hashlib.sha256(json.dumps(ast_shape(node),ensure_ascii=True,separators=(',',':')).encode()).hexdigest()


def strip_declared_handoff(function,actor,expected):
    """Remove only this exact additive wrapper, retaining original calls/args."""
    function=copy.deepcopy(function);imports=[];calls=[]
    class Strip(ast.NodeTransformer):
        def visit_ImportFrom(self,node):
            if node.module=='app.web.pengguna_baca_native' and [n.name for n in node.names]==['pasang_native'] and all(n.asname is None for n in node.names):
                imports.append(node);return None
            return node
        def visit_Return(self,node):
            value=node.value
            if isinstance(value,ast.Await) and isinstance(value.value,ast.Call) and isinstance(value.value.func,ast.Name) and value.value.func.id=='pasang_native':
                call=value.value
                assert not call.keywords and len(call.args)==3
                assert ast.unparse(call.args[0])=='request' and ast.unparse(call.args[1])==actor
                assert isinstance(call.args[2],(ast.Call,ast.Await))
                calls.append(call);node.value=call.args[2]
            return self.generic_visit(node)
    function=Strip().visit(function)
    assert len(imports)==1 and len(calls)==expected
    return function


def test_only_five_native_get_functions_add_response_handoff_all_other_ast_unchanged():
    raw=(ROOT/'tests/fixtures/pengguna_native_handoff_prechange.json').read_bytes()
    assert hashlib.sha256(raw).hexdigest()=='6b2896b77c694ab901bd5d03b8d81a8b5ea97c13216f6e10d906643c6dd2ac0c'
    receipt=json.loads(raw)
    assert receipt['version']==1 and receipt['source_commit']=='398a9f157117c3b1cf9aec7eada6e92745fa6708'
    allowed={'app/web/pengaturan.py':{'halaman_pengaturan':('akun',1)},
        'app/web/pengguna.py':{'halaman_pengguna':('_',1),'halaman_ubah':('_',2)},
        'app/web/portal/admin.py':{'index':('actor',1),'detail':('actor',1)}}
    for path,baseline in receipt['entries'].items():
        tree=ast.parse((ROOT/path).read_text())
        functions={n.name:n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
        assert set(functions)==set(baseline['functions'])
        envelope=ast.Module(body=[n for n in tree.body if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))],type_ignores=tree.type_ignores)
        assert ast_fingerprint(envelope)==baseline['envelope_sha256']
        for name,node in functions.items():
            if name in allowed[path]:
                assert any(isinstance(d,ast.Call) and isinstance(d.func,ast.Attribute) and d.func.attr=='get' for d in node.decorator_list)
                node=strip_declared_handoff(node,*allowed[path][name])
            assert ast_fingerprint(node)==baseline['functions'][name], (path,name)


def test_wrapper_oracle_rejects_foreign_actor_and_unrelated_native_change():
    tree=ast.parse((ROOT/'app/web/pengguna.py').read_text())
    function=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='halaman_pengguna')
    altered=copy.deepcopy(function)
    call=next(n for n in ast.walk(altered) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='pasang_native')
    call.args[1]=ast.Name(id='other_actor',ctx=ast.Load())
    with pytest.raises(AssertionError):strip_declared_handoff(altered,'_',1)
    normal=strip_declared_handoff(function,'_',1)
    changed=copy.deepcopy(normal);changed.body.append(ast.Pass())
    assert ast_fingerprint(changed)!=ast_fingerprint(normal)
