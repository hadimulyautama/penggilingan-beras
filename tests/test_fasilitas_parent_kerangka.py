"""Pure scope/shape/native source checks, not browser or authorization QA."""
import ast
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import pytest
from bs4 import BeautifulSoup
from starlette.requests import Request
from app.web.fasilitas_parent_kerangka import TARGETS,TITLES,blueprint,susun

ROOT=Path(__file__).parents[1]
REG=dict(cap='fixture-cap',konteks='fixture-context',sesi='fixture-session')

def request(akun,**delta):
    return Request({**dict(type='http',method='GET',scheme='https',server=('fixture.invalid',443),path='/pengaturan',query_string=b'',headers=[],state={'akun':akun}),**delta})

def descriptor():
    return dict(versi=1,**REG,sumber='a'*64,targets=['/pengaturan/alat'])

def prepare(monkeypatch):
    import app.web.fasilitas_parent_kerangka as family
    import app.web.pengaturan_alat_kerangka as alat
    monkeypatch.setattr(family,'aset',lambda:dict(sumber='b'*64))
    monkeypatch.setattr(alat,'aset',lambda:dict(sumber='a'*64))
    # Protocol-only actor sentinel; never a product ORM/account or role claim.
    akun=SimpleNamespace(harus_ganti_sandi=False)
    return akun


def test_same_native_alat_guard_descriptor_reused_without_role_inference_or_second_guard(monkeypatch):
    akun=prepare(monkeypatch)
    import app.web.pengaturan_alat_kerangka as alat
    monkeypatch.setattr(alat,'guard_native',lambda *a,**k:(_ for _ in ()).throw(AssertionError('Do not re-query native guard')))
    value=susun(request(akun),akun,registry=REG,guarded_alat=descriptor())
    assert value==dict(versi=1,**REG,sumber='b'*64,targets=list(TARGETS))
    assert set(value)=={'versi','cap','konteks','sesi','sumber','targets'}


@pytest.mark.parametrize('delta',[{'versi':True},{'versi':2},{'cap':'old'},{'konteks':'old'},{'sesi':'old'},{'sumber':'old'},{'targets':[]},{'targets':['/pengaturan/silo']},{'targets':['/pengaturan/alat','/pengaturan/silo']},{'is_admin':True}])
def test_missing_wrong_scope_old_program_or_admin_master_flag_declines(monkeypatch,delta):
    akun=prepare(monkeypatch)
    assert susun(request(akun),akun,registry=REG,guarded_alat={**descriptor(),**delta}) is None


@pytest.mark.parametrize('value',[None,{},True,{'allowed':True}])
def test_unknown_guard_result_cannot_open_parent_controls(monkeypatch,value):
    akun=prepare(monkeypatch)
    assert susun(request(akun),akun,registry=REG,guarded_alat=value) is None


def test_same_request_account_portal_password_and_method_remain_closed(monkeypatch):
    akun=prepare(monkeypatch)
    for req in [request(akun,method='POST'),request(akun,state={'akun':object()}),request(akun,state={'akun':akun,'portal_scope':object()})]:
        assert susun(req,akun,registry=REG,guarded_alat=descriptor()) is None
    akun.harus_ganti_sandi=True
    assert susun(request(akun),akun,registry=REG,guarded_alat=descriptor()) is None
    akun.harus_ganti_sandi=None
    assert susun(request(akun),akun,registry=REG,guarded_alat=descriptor()) is None


@pytest.mark.parametrize('address',[TARGETS[0]+'?err=1',TARGETS[1]+'#edit','/pengaturan/mesin/7','/pengaturan/dryer/7','/pengaturan/fasilitas','/pengaturan/alat','//other.invalid/pengaturan/silo'])
def test_only_four_bare_public_layout_shapes(address):assert blueprint(address) is None


def compiled():
    p=ROOT/'scripts/buat_kerangka_fasilitas_parent.py';spec=importlib.util.spec_from_file_location('facility_parent_compile_test',p);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    payload,meta=module.build()
    return payload,meta,json.loads(payload.decode().split('window.PadiKerangkaFasilitasParentData=',1)[1].split(';\n',1)[0])


@pytest.mark.parametrize('address',TARGETS)
def test_each_shape_has_native_title_breadcrumb_fields_but_no_config_or_mutation(address):
    _,_,data=compiled();v=data['variants'][address];doc=BeautifulSoup(v['html'],'html.parser');crumb=BeautifulSoup(v['breadcrumb'],'html.parser')
    assert v['title']==TITLES[TARGETS.index(address)]
    assert doc.h1.get_text()==('Gudang' if address.endswith('/gudang') else v['title'])
    assert crumb.select_one('a')['href']=='/' and crumb.select_one('[aria-current=page]').get_text()==v['title']
    assert crumb.select_one('.desktop-back')['href']=='/pengaturan'
    assert not doc.select('form,[name],input[value],input[type=hidden],[checked],[data-post],[data-kirim],[data-fasilitas],[data-simpan-alat],[data-pengaturan-form],script[src]')
    assert all(n.has_attr('disabled') for n in doc.select('input,textarea,select'))
    assert all(n.get('aria-checked')=='mixed' for n in doc.select('input[type=checkbox]'))
    assert all(n.has_attr('disabled') and n.get('type')=='button' for n in doc.select('button:not([data-fp-retry])'))
    assert all(n.get('href')=='/pengaturan' for n in doc.select('a[href]'))
    ids=[n['id'] for n in doc.select('[id]')];assert len(ids)==len(set(ids))
    for label in doc.select('label[for]'):assert doc.select_one('#'+label['for']) is not None
    assert doc.select_one('[data-fp-status]').get_text()=='Memuat pengaturan…'
    assert doc.select_one('[data-fp-retry]').has_attr('hidden')
    assert 'belum ada' not in doc.get_text().lower() and 'belum dibaca' in doc.get_text().lower()
    assert all('pengaturan-alat.js' not in s and 'pengaturan-isian.js' not in s for s in data['scripts'].values())
    if address.endswith('/gudang'):
        assert not doc.section.has_attr('class')
        assert [n.get_text() for n in doc.select('h2')]==['Daftar gudang','Tambah gudang']
        assert len(doc.select('textarea'))==1
        for name in ('Nama gudang','Alamat','Latitude','Longitude'):assert name in doc.get_text()
    elif address.endswith('/silo'):
        assert [n.get_text() for n in doc.select('span.lbl')]==['Silo gabah','Silo bahan penyosohan']
        assert len(doc.select('select'))==1 and len(doc.select('input'))==2
        assert 'Kapasitas' not in doc.get_text()
    elif address.endswith('/mesin'):
        assert [n.get_text() for n in doc.select('summary')]==['Tambah mesin / line','Tambah dryer']
        assert len(doc.select('input[type=checkbox]'))==1 and len(doc.select('select'))==4
    else:
        assert [n.get_text() for n in doc.select('summary')]==['Tambah jenis proses']
        assert len(doc.select('input[type=checkbox]'))==1 and not doc.select('select')


def digest(node):return hashlib.sha256(ast.dump(node,include_attributes=False).encode()).hexdigest()


def test_immutable_native_guard_reader_and_writer_baseline_no_git_runtime():
    receipt=json.loads((ROOT/'tests/fixtures/fasilitas_parent_prechange.json').read_text())
    assert receipt['baseline_commit']=='cafdb911c33a422b984c078c03b72ed568d82912'
    for path,functions in receipt['functions'].items():
        nodes={n.name:n for n in ast.parse((ROOT/path).read_text()).body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))}
        if path=='app/web/pengaturan.py':
            from tests.test_pengguna_native_handoff import strip_declared_handoff
            nodes['halaman_pengaturan']=strip_declared_handoff(nodes['halaman_pengaturan'],'akun',1)
        for name,expected in functions.items():assert digest(nodes[name])==expected,(path,name)
    for path,expected in receipt['controllers'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==expected
    parent=ast.parse((ROOT/'app/web/pengaturan.py').read_text());facility=ast.parse((ROOT/'app/web/fasilitas.py').read_text())
    nodes={n.name:n for tree in (parent,facility) for n in tree.body if isinstance(n,ast.AsyncFunctionDef)}
    for name in ('halaman_gudang_pengaturan','halaman_alat','daftar'):assert 'Depends(butuh_super)' in ast.unparse(nodes[name].args)
    changed=copy.deepcopy(nodes['daftar']);changed.args.defaults[-1]=ast.Constant(value=None)
    assert digest(changed)!=receipt['functions']['app/web/fasilitas.py']['daftar']
    native=(ROOT/'app/web/templates/fasilitas.html').read_bytes().replace(b"{% include '_fasilitas_parent_empty.html' %}\n",b'')
    assert hashlib.sha256(native).hexdigest()==receipt['native_template_before_empty_sha256']
    helper=ast.parse((ROOT/'app/web/fasilitas_parent_kerangka.py').read_text())
    assert not any(isinstance(n,ast.Await) for n in ast.walk(helper))
    assert not any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr in {'execute','scalar','scalars','commit','flush','delete','add'} for n in ast.walk(helper))


def test_source_only_compiler_without_product_import_is_deterministic_and_bounded():
    code=r'''
import importlib.abc,importlib.util,sys
from pathlib import Path
class NoApp(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='app' or fullname.startswith('app.'):raise AssertionError('Application import '+fullname)
sys.meta_path.insert(0,NoApp())
p=Path('scripts/buat_kerangka_fasilitas_parent.py');s=importlib.util.spec_from_file_location('parent_source_compile_only',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
a,b=m.build()
assert a==Path('app/web/static/kerangka-fasilitas-parent-ui.js').read_bytes()
assert b==Path('app/web/static/kerangka-fasilitas-parent-ui.meta.json').read_bytes()
assert len(a)<=262144
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr


@pytest.mark.parametrize('key',('cap','konteks','sesi'))
def test_unknown_empty_or_unbounded_registry_binding_declines(monkeypatch,key):
    akun=prepare(monkeypatch)
    for value in ('',None,True,'x'*2049):
        assert susun(request(akun),akun,registry={**REG,key:value},guarded_alat=descriptor()) is None
