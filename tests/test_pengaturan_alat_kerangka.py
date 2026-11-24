"""Source/pure tests only; native guard body, synthetic recovery predicate."""
import ast
import copy
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,FileSystemLoader,StrictUndefined
from starlette.requests import Request
from app.web.pengaturan_alat_kerangka import ALAMAT,guard_native,kerangka,permintaan_kerangka,susun

ROOT=Path(__file__).parents[1]
from tests.native_source_oracle import baseline,fingerprint,functions,remove_declared_shape


def request(path=ALAMAT,query=b'',headers=(),state=None,method='GET'):
    return Request(dict(type='http',method=method,scheme='https',server=('fixture.invalid',443),path=path,query_string=query,headers=list(headers),state=state or {}))


def template(name,context):
    env=Environment(loader=ChoiceLoader([FileSystemLoader(ROOT/'app/web/templates'),FileSystemLoader(ROOT/'hmu_tampilan/templates')]),autoescape=True,undefined=StrictUndefined)
    t=env.get_template(name);return BeautifulSoup(''.join(t.blocks['isi'](t.new_context(context))),'html.parser')


def test_hub_has_exact_native_three_links_and_no_machine_or_stock_fields():
    original=template('alat.html',dict(pesan_err=None,pesan_ok=None))
    shape=template('pengaturan_alat_kerangka.html',dict(ALAT_SHELL={'alamat':ALAMAT,'stamp':'fixture-context|'+ALAMAT},VERSI='fixture-cap'))
    assert shape.h1.get_text()==original.h1.get_text()=='Pengaturan alat'
    links=lambda d:[(a['href'],a.get_text()) for a in d.select('a[href]')]
    assert links(shape)==links(original)==[('/pengaturan/mesin','Mesin & line produksi'),('/pengaturan/silo','Silo'),('/pengaturan/sebab-berhenti','Sebab berhenti proses')]
    assert not shape.select('form,input,select,textarea,[name],[data-post],[data-kirim],[data-simpan-alat],[data-jaga-isian]')
    assert shape.select_one('[data-alat-native-status]')['role']=='status'
    assert shape.select_one('button')['type']=='button'
    assert not shape.select('script[src*="pengaturan-alat.js"],script[src*="pengaturan-isian.js"]')


@pytest.mark.parametrize('headers,expected',[
    ([(b'x-kerangka-halaman',b'1')],True),([(b'sec-fetch-mode',b'navigate'),(b'sec-fetch-dest',b'document')],True),
    ([(b'x-pindah',b'1')],False),([(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'1')],False),([],False)])
def test_data_get_always_native(headers,expected):
    assert permintaan_kerangka(request(headers=headers)) is expected


@pytest.mark.parametrize('path,query,method',[
    ('/pengaturan/silo',b'','GET'),('/pengaturan/mesin',b'','GET'),('/pengaturan/alat/status-simpan/x',b'','GET'),
    (ALAMAT,b'pesan=silo-ditambah','GET'),(ALAMAT,b'err_teks=x','GET'),(ALAMAT,b'company_id=1','GET'),(ALAMAT,b'','POST')])
def test_no_other_settings_feedback_or_transaction_coverage(path,query,method):
    assert not permintaan_kerangka(request(path,query,[(b'x-kerangka-halaman',b'1')],method=method))


def native_guard(recovery):
    """Execute exact native guard body; only its DB recovery read is a double."""
    tree=ast.parse((ROOT/'app/web/security.py').read_text())
    fn=copy.deepcopy(next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='butuh_super'))
    fn.decorator_list=[];fn.returns=None;fn.args.defaults=[]
    for arg in fn.args.args:arg.annotation=None
    calls=[]
    async def recovery_read():calls.append('native-recovery-predicate');return recovery
    class Denied(Exception):pass
    namespace={'pemulihan_lama_diizinkan':recovery_read,'AksesDitolak':Denied}
    module=ast.fix_missing_locations(ast.Module(body=[fn],type_ignores=[]));exec(compile(module,'<exact-native-butuh-super>','exec'),namespace)
    return SimpleNamespace(butuh_super=namespace['butuh_super'],AksesDitolak=Denied),calls


@pytest.mark.asyncio
@pytest.mark.parametrize('super_,admin,recovery,expected,reads',[
    (True,True,False,True,0),(False,True,False,False,1),(False,True,True,True,1),(False,False,True,False,0)])
async def test_exact_super_guard_not_master_admin_boolean(monkeypatch,super_,admin,recovery,expected,reads):
    import app.web.pengaturan_alat_kerangka as module
    security,calls=native_guard(recovery);monkeypatch.setitem(sys.modules,'app.web.security',security)
    monkeypatch.setattr(module,'aset',lambda:{'sumber':'a'*64})
    account=SimpleNamespace(is_super=super_,is_admin=admin,harus_ganti_sandi=False)
    req=request(state={'akun':account});assert await guard_native(req,account) is expected
    assert len(calls)==reads
    metadata=await susun(req,account,registry={'cap':'cap','konteks':'ctx','sesi':'fixture-token'})
    assert (metadata is not None) is expected
    if metadata:assert metadata==dict(versi=1,cap='cap',konteks='ctx',sesi='fixture-token',sumber='a'*64,targets=[ALAMAT])


@pytest.mark.asyncio
async def test_unverified_portal_forced_password_or_post_declines_before_native_import(monkeypatch):
    async def forbidden(*_):raise AssertionError('Native guard must not be called')
    monkeypatch.setitem(sys.modules,'app.web.security',SimpleNamespace(butuh_super=forbidden,AksesDitolak=Exception))
    account=SimpleNamespace(harus_ganti_sandi=False)
    req=request(state={'akun':object()});assert not await guard_native(req,account)
    req.state.akun=account;req.state.portal_scope=object();assert not await guard_native(req,account)
    req.state.portal_scope=None;account.harus_ganti_sandi=True;assert not await guard_native(req,account)
    account.harus_ganti_sandi=False;req.scope['method']='POST';assert not await guard_native(req,account)


@pytest.mark.asyncio
async def test_scoped_shape_render_only_after_exact_native_guard_and_bound_shell(monkeypatch):
    from starlette.responses import HTMLResponse
    security,_=native_guard(False);monkeypatch.setitem(sys.modules,'app.web.security',security)
    seen=[]
    def render(req,name,**context):seen.append((name,context));return HTMLResponse('pure-render-double')
    monkeypatch.setitem(sys.modules,'app.web.tampilan',SimpleNamespace(render=render))
    account=SimpleNamespace(is_super=True,is_admin=True,harus_ganti_sandi=False)
    req=request(headers=[(b'x-kerangka-halaman',b'1')],state={'akun':account})
    assert await kerangka(req,account,{'SHELL':{'data_url':'/pengaturan/silo','stamp':'ctx'}}) is None
    context={'SHELL':{'data_url':ALAMAT,'stamp':'ctx|'+ALAMAT}}
    response=await kerangka(req,account,context)
    assert response.headers['cache-control']=='private, no-store'
    assert seen[0][0]=='pengaturan_alat_kerangka.html'
    assert seen[0][1]['ALAT_SHELL']==dict(alamat=ALAMAT,stamp='ctx|'+ALAMAT)
    assert set(context)=={'SHELL'}


def test_only_native_get_wrapper_changes_not_stock_readers_or_any_writer(monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:(_ for _ in ()).throw(AssertionError('No Git/command in native baseline proof')))
    receipt=baseline('alat')
    assert receipt['baseline_commit']=='59a15198fda21a6e0afc0a7732aa2e856d2b4eed'
    after=functions((ROOT/receipt['module']).read_text());assert after.keys()==receipt['functions'].keys()
    caller=after['halaman_alat']
    assert 'Depends(butuh_super)' in ast.unparse(caller.args)
    assert ast.unparse(caller.body[-1])=='return await _halaman_alat(request, akun)'
    remove_declared_shape(caller,'app.web.pengaturan_alat_kerangka',receipt['declared_alat_block_sha256'])
    # The separately tested six-settings presentation was adopted later.
    # Strip only its pinned two-node block; native reads/writers stay compared.
    remove_declared_shape(after['halaman_pengaturan'],'app.web.pengaturan_detail_kerangka',receipt['declared_detail_block_sha256'])
    for name,node in after.items():assert fingerprint(node)==receipt['functions'][name],name
    changed=copy.deepcopy(after['tambah_gudang'])
    commit=next(n for n in ast.walk(changed) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='commit')
    commit.func.attr='rollback';assert fingerprint(changed)!=receipt['functions']['tambah_gudang']
    changed=copy.deepcopy(caller)
    guard=next(n for n in ast.walk(changed.args) if isinstance(n,ast.Name) and n.id=='butuh_super')
    guard.id='butuh_akun'
    assert fingerprint(changed)!=receipt['functions']['halaman_alat']
    helper=(ROOT/'app/web/pengaturan_alat_kerangka.py').read_text()
    assert not any(s in helper for s in ('SessionLocal','from app.models','stok','is_admin','pemulihan_lama_diizinkan'))
    assert 'await butuh_super(akun)' in helper


def test_public_compiler_source_only_and_current():
    code=r'''
import importlib.abc,importlib.util,json,sys
from pathlib import Path
from bs4 import BeautifulSoup
class NoApp(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='app' or fullname.startswith('app.'):raise AssertionError('Application import '+fullname)
sys.meta_path.insert(0,NoApp())
p=Path('scripts/buat_kerangka_pengaturan_alat.py');s=importlib.util.spec_from_file_location('public_hub',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
payload,meta=m.build()
assert payload==Path('app/web/static/kerangka-pengaturan-alat-ui.js').read_bytes()
assert meta==Path('app/web/static/kerangka-pengaturan-alat-ui.meta.json').read_bytes()
data=json.loads(payload.decode().split('window.PadiKerangkaPengaturanAlatData=',1)[1].split(';\n',1)[0])
assert list(data['variants'])==['/pengaturan/alat'] and data['styles']=={} and len(data['scripts'])==2
d=BeautifulSoup(data['variants']['/pengaturan/alat']['html'],'html.parser')
assert len(d.select('a[href]'))==3 and not d.select('form,input,select,textarea,[name],[data-post],[data-kirim],script[src]')
assert len(payload)<=131072
print('SOURCE_ONLY_ALAT_HUB_PASS')
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'SOURCE_ONLY_ALAT_HUB_PASS' in result.stdout
