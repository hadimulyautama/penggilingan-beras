"""Pure/source only: no PostgreSQL, browser, server or identity fixture."""
import ast
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
import pytest
from bs4 import BeautifulSoup
from jinja2 import Environment,FileSystemLoader,StrictUndefined
from starlette.requests import Request
from app.web.pengaturan_master_kerangka import PATHS,akun_native,kerangka,permintaan_kerangka,spesifikasi,susun

ROOT=Path(__file__).parents[1]


def request(path=PATHS[0],query=b'',headers=(),state=None,method='GET'):
    return Request(dict(type='http',method=method,scheme='https',server=('fixture.invalid',443),path=path,
        query_string=query,headers=list(headers),state=state or {}))


def layout(path):
    env=Environment(loader=FileSystemLoader(ROOT/'app/web/templates'),undefined=StrictUndefined,autoescape=True)
    template=env.get_template('pengaturan_master_kerangka.html')
    context=template.new_context(dict(PG_MASTER_SHELL={**spesifikasi(path),'stamp':'synthetic-context|'+path},VERSI='synthetic-cap'))
    return BeautifulSoup(''.join(template.blocks['isi'](context)),'html.parser')


@pytest.mark.parametrize('path',PATHS)
def test_real_master_labels_and_unknown_values_without_account_or_records(path):
    doc=layout(path);kind=spesifikasi(path)['jenis']
    native=(ROOT/'app/web/templates'/('spesifikasi_beras.html' if kind=='beras' else 'jenis_hasil_samping.html')).read_text()
    assert doc.h1.get_text()==spesifikasi(path)['title']
    assert doc.select_one('summary').get_text()==spesifikasi(path)['add_summary']
    assert doc.select_one('h2').get_text().endswith('(belum dibaca)')
    assert 'Belum ada' not in doc.get_text() and '(0)' not in doc.get_text()
    for label in doc.select('label'):
        assert label.get_text() in native
        assert doc.find(id=label['for']).has_attr('disabled')
    assert not doc.select('form,[name],input[type=hidden],[data-post],[data-kirim],[data-jaga-isian]')
    assert all(n.has_attr('disabled') and not n.has_attr('value') for n in doc.select('input,select'))
    assert all(n.has_attr('disabled') and n['type']=='button' for n in doc.select('button:not([data-master-native-retry])'))
    assert doc.select_one('[data-master-native-retry]')['type']=='button'
    assert doc.select_one('[data-master-native-status]')['role']=='status'
    assert doc.select_one('[data-record-ready]')['data-record-ready']=='0'
    assert not doc.select('script[src*="pengaturan-isian"]') # activate native draft guard only after native HTML


@pytest.mark.parametrize('path,query',[(PATHS[0],'berhasil=tambah'),(PATHS[1],'err=x'),('/pengaturan',''),('/pengaturan/akun',''),('/pengguna',''),('/pelanggan'+PATHS[0],''),(PATHS[0]+'/ubah',''),(PATHS[1],'company_id=1')])
def test_other_families_feedback_or_actions_decline(path,query):
    assert spesifikasi(path,query) is None
    assert not permintaan_kerangka(request(path,query.encode(),[(b'x-kerangka-halaman',b'1')]))


@pytest.mark.parametrize('headers,expected',[
    ([(b'x-kerangka-halaman',b'1')],True),
    ([(b'sec-fetch-mode',b'navigate'),(b'sec-fetch-dest',b'document')],True),
    ([(b'x-pindah',b'1')],False),
    ([(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'1')],False),
    ([(b'x-pindah',b'1'),(b'sec-fetch-mode',b'navigate'),(b'sec-fetch-dest',b'document')],False),([],False)])
def test_native_data_always_wins_and_no_plain_get_recursion(headers,expected):
    assert permintaan_kerangka(request(headers=headers)) is expected


@pytest.mark.parametrize('account',[
    SimpleNamespace(is_admin=False,harus_ganti_sandi=False),SimpleNamespace(is_admin=True,harus_ganti_sandi=True),
    SimpleNamespace(is_admin=True),SimpleNamespace(is_admin=1,harus_ganti_sandi=False),object(),None])
@pytest.mark.asyncio
async def test_unknown_or_denied_accounts_decline_before_render_import(account):
    req=request(headers=[(b'x-kerangka-halaman',b'1')],state={'akun':account})
    assert not akun_native(req,account)
    assert await kerangka(req,account,{}) is None
    assert await susun(req,account,registry={}) is None


@pytest.mark.asyncio
async def test_render_context_is_shape_only_and_metadata_requires_same_verified_account(monkeypatch):
    from starlette.responses import HTMLResponse
    import app.web.pengaturan_master_kerangka as module
    seen=[]
    def render(req,name,**context):seen.append((name,context));return HTMLResponse('pure-render-double')
    monkeypatch.setitem(sys.modules,'app.web.tampilan',SimpleNamespace(render=render))
    monkeypatch.setattr(module,'aset',lambda:{'sumber':'a'*64})
    account=SimpleNamespace(is_admin=True,harus_ganti_sandi=False)
    req=request(headers=[(b'x-kerangka-halaman',b'1')],state={'akun':account})
    context={'SHELL':{'stamp':'ctx|'+PATHS[0],'data_url':PATHS[0]}}
    result=await kerangka(req,account,context)
    assert result.headers['cache-control']=='private, no-store'
    assert seen[0][0]=='pengaturan_master_kerangka.html'
    assert 'akun' not in seen[0][1]['PG_MASTER_SHELL']
    assert set(context)=={'SHELL'}
    registry={'cap':'synthetic-cap','konteks':'synthetic-context','sesi':'synthetic-session'}
    assert await susun(req,account,registry=registry)==dict(versi=1,**registry,sumber='a'*64,allowed=True)
    req.state.portal_scope=object()
    assert await kerangka(req,account,context) is None
    assert await susun(req,account,registry=registry) is None
    req.state.portal_scope=None;req.state.akun=object()
    assert await kerangka(req,account,context) is None
    req.state.akun=account;req.scope['method']='POST'
    assert await kerangka(req,account,context) is None
    assert await susun(req,account,registry=registry) is None


def test_actual_get_dependency_preserved_writers_and_heavy_readers_unchanged():
    for name in ('spesifikasi_beras.py','jenis_hasil_samping.py'):
        path='app/web/'+name;new=ast.parse((ROOT/path).read_text())
        old=ast.parse(subprocess.run(['git','show','HEAD:'+path],cwd=ROOT,text=True,capture_output=True,check=True).stdout)
        get=lambda tree:{n.name:ast.dump(n,include_attributes=False) for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
        before,after=get(old),get(new)
        assert 'Depends(butuh_admin)' in ast.unparse(next(n for n in new.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='lihat').args)
        assert all(after[k]==v for k,v in before.items() if k!='lihat')
        assert ast.unparse(next(n for n in new.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='lihat').body[-1])=='return await halaman(request)'


def test_helper_uses_no_database_orm_or_role_catalog():
    source=(ROOT/'app/web/pengaturan_master_kerangka.py').read_text()
    assert not any(s in source for s in ('SessionLocal','from app.models','from hmu_','akun.peran','users.role'))
    assert "getattr(akun,'is_admin',None) is True" in source


def test_public_compiler_source_only_and_outputs_current():
    code=r'''
import importlib.abc,importlib.util,json,sys
from pathlib import Path
from bs4 import BeautifulSoup
class NoApp(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='app' or fullname.startswith('app.'):raise AssertionError('App runtime import: '+fullname)
sys.meta_path.insert(0,NoApp())
p=Path('scripts/buat_kerangka_pengaturan_master.py')
s=importlib.util.spec_from_file_location('public_master_compile',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
payload,meta=m.build()
assert payload==Path('app/web/static/kerangka-pengaturan-master-ui.js').read_bytes()
assert meta==Path('app/web/static/kerangka-pengaturan-master-ui.meta.json').read_bytes()
data=json.loads(payload.decode().split('window.PadiKerangkaPengaturanMasterData=',1)[1].split(';\n',1)[0])
assert list(data['variants'])==['/pengaturan/spesifikasi-beras','/pengaturan/hasil-samping']
for v in data['variants'].values():
 d=BeautifulSoup(v['html'],'html.parser')
 assert not d.select('form,[name],input[type=hidden],[data-post],[data-kirim],script[src],link[rel=stylesheet]')
 assert all(n.has_attr('disabled') and not n.has_attr('value') for n in d.select('input,select'))
 assert '(belum dibaca)' in d.get_text() and 'Belum ada' not in d.get_text()
assert len(data['styles'])==1 and len(data['scripts'])==2 and len(payload)<=262144
print('SOURCE_ONLY_MASTER_PAIR_PASS')
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'SOURCE_ONLY_MASTER_PAIR_PASS' in result.stdout
