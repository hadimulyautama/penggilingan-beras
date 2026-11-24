"""Pure native source/shape tests only, no DB/browser/config/identity writes."""
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
from jinja2 import ChoiceLoader,Environment,FileSystemLoader,StrictUndefined
from starlette.requests import Request
from app.web.pengaturan_detail_kerangka import PATHS,VARIANTS,akun_native,kerangka,native_references,permintaan_kerangka,spesifikasi,susun
from app.web.pengaturan_detail_schema import load

ROOT=Path(__file__).parents[1]
REFS=load(ROOT)


def flags(tuan=True,peran='lihat'):
    return dict(tuan=tuan,peran=peran,**REFS)


def request(path=PATHS[0],query=b'',headers=(),state=None,method='GET'):
    return Request(dict(type='http',method=method,scheme='https',server=('fixture.invalid',443),path=path,query_string=query,headers=list(headers),state=state or {}))


def env():return Environment(loader=ChoiceLoader([FileSystemLoader(ROOT/'app/web/templates'),FileSystemLoader(ROOT/'hmu_tampilan/templates')]),autoescape=True,undefined=StrictUndefined)


def shape(path,native):
    spec=spesifikasi(path,native=native);template=env().get_template('pengaturan_detail_kerangka.html')
    return spec,BeautifulSoup(''.join(template.blocks['isi'](template.new_context(dict(PG_DETAIL_SHELL={**spec,'stamp':'fixture-stamp'},VERSI='fixture-cap')))),'html.parser')


@pytest.mark.parametrize('path',PATHS)
def test_native_first_paint_structure_without_config_or_writer_fields(path):
    spec,doc=shape(path,flags())
    assert doc.select_one('h1').get_text()==spec['heading']
    assert doc.select_one('.pg-lingkup').get_text()=='Pengaturan / '+spec['group']
    assert not doc.select('form,[name],input[type=hidden],[data-post],[data-kirim],[aria-checked],[data-jaga-isian]')
    assert all(n.has_attr('disabled') and not n.has_attr('value') for n in doc.select('input,select,textarea'))
    assert all(n.has_attr('disabled') and n['type']=='button' for n in doc.select('button:not([data-pengaturan-detail-retry])'))
    assert not doc.select('[data-record-ready="1"]')
    assert not doc.select('script[src*="pengaturan-alat.js"],script[src*="pengaturan-isian.js"]')
    assert doc.select_one('[data-pengaturan-detail-status]')['role']=='status'
    t=env().get_template('pengaturan_detail_kerangka.html')
    native_title=env().get_template('pengaturan.html')
    assert ''.join(t.blocks['judul'](t.new_context({})))==''.join(native_title.blocks['judul'](native_title.new_context({})))=='Pengaturan'


def test_actual_two_role_shapes_and_system_visibility_are_distinct_no_default_selection():
    for mode,title in [('lihat','Lihat sebagai'),('gudang','Kerja di gudang')]:
        spec,doc=shape('/pengaturan/peran',flags(False,mode))
        assert spec['heading']==title and doc.select_one('.lbl').get_text()==title
        assert [n.get_text() for n in doc.select('select option')]==['Belum dibaca']
        assert not doc.select('option[selected]')
    admin,doc=shape('/pengaturan/sistem',flags(True));assert admin['heading']=='Batas ubah & versi'
    assert 'Batas ubah catatan' in doc.get_text()
    normal,doc=shape('/pengaturan/sistem',flags(False,'gudang'));assert normal['heading']=='Informasi versi'
    assert 'Batas ubah catatan' not in doc.get_text() and not doc.select('input,button:not([data-pengaturan-detail-retry])')


def test_access_tables_and_reason_sections_follow_native_reference_headers_without_fake_rows():
    _,doc=shape('/pengaturan/akses',flags(False,None))
    assert [[n.get_text() for n in t.select('thead th')] for t in doc.select('table')]==[['Bagian',*REFS['columns']],['Tindakan',*REFS['columns']]]
    assert all(len(t.select('tbody tr'))==1 for t in doc.select('table'))
    assert not doc.select('th[aria-current]') and 'Diizinkan' not in doc.get_text() and 'Terkunci' not in doc.get_text()
    assert 'Rincian akses tindakan · belum dibaca' in doc.get_text()
    _,doc=shape('/pengaturan/sebab-berhenti',flags())
    assert [n.get_text() for n in doc.select('.pg-rincian>div>.lbl')]==[label for _,label in REFS['processes']]
    assert len(doc.select('input[disabled]'))==len(REFS['processes'])
    assert 'Buang' not in doc.get_text() and not doc.select('[data-record-id]')


def test_qc_and_kledo_unknown_do_not_claim_off_disconnected_or_start_external_work():
    _,qc=shape('/pengaturan/mutu',flags())
    assert not qc.select('[aria-checked]')
    assert not qc.select('input[value],.saklar--nyala')
    assert 'belum dibaca' in qc.get_text()
    _,kledo=shape('/pengaturan/kledo',flags())
    assert 'belum dibaca' in kledo.get_text()
    assert 'Kledo belum tersambung' not in kledo.get_text() and 'KLEDO_API_KEY' not in kledo.get_text()
    assert not kledo.select('a[href*="railway"],form')


def test_unknown_or_malformed_structure_flags_decline_not_actor_or_configuration_defaults():
    for delta in ({'tuan':None},{'peran':[]},{'columns':[]},{'columns':['duplicate','duplicate']},{'processes':[['missinglabel']]},{'pages':None}):
        assert spesifikasi('/pengaturan/akses',native={**flags(),**delta}) is None


@pytest.mark.parametrize('path',('/pengaturan/sebab-berhenti','/pengaturan/mutu','/pengaturan/kledo'))
def test_native_admin_only_details_remain_denied_without_admin_predicate(path):
    assert spesifikasi(path,native=flags(False,'gudang')) is None


@pytest.mark.parametrize('path,query',[(p,'err=x') for p in PATHS]+[('/pengaturan',''),('/pengaturan/akun',''),('/pengaturan/sesi',''),('/pengaturan/gudang',''),('/pengguna',''),('/pengaturan/peran','company_id=1')])
def test_feedback_other_families_and_actions_stay_native(path,query):
    assert spesifikasi(path,query,native=flags()) is None
    assert not permintaan_kerangka(request(path,query.encode(),[(b'x-kerangka-halaman',b'1')]))


@pytest.mark.parametrize('headers,expected',[
    ([(b'x-kerangka-halaman',b'1')],True),([(b'sec-fetch-mode',b'navigate'),(b'sec-fetch-dest',b'document')],True),
    ([(b'x-pindah',b'1')],False),([(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'1')],False),([],False)])
def test_native_data_priority(headers,expected):assert permintaan_kerangka(request(headers=headers)) is expected


def actual_role_module():
    spec=importlib.util.spec_from_file_location('settings_native_roles_source',ROOT/'hmu_identitas/peran.py')
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


@pytest.mark.parametrize('effective,original,admin,mode',[
    ('admin',None,True,'lihat'),('superadmin',None,True,'lihat'),('operator',None,False,'gudang'),
    ('operator','admin',False,'lihat'),('unknown',None,False,None)])
def test_native_reference_adapter_uses_exact_effective_and_original_predicates(monkeypatch,effective,original,admin,mode):
    roles=actual_role_module();calls=[]
    def process(view):calls.append(view);assert view==roles.V_SUPER;return REFS['processes']
    # Only native source dependencies are protocol doubles, not live accounts.
    monkeypatch.setitem(sys.modules,'app.web.pengaturan',SimpleNamespace(PERAN_ADMIN_KEATAS=roles.PERAN_ADMIN_KEATAS,_P=roles,_proses_view=process,V_SUPER=roles.V_SUPER))
    monkeypatch.setitem(sys.modules,'app.web.akses',SimpleNamespace(PERAN_KOLOM=tuple(enumerate(REFS['columns']))))
    monkeypatch.setitem(sys.modules,'app.web.pengaturan_navigasi',SimpleNamespace(HALAMAN=REFS['pages']))
    account=SimpleNamespace(peran=effective,harus_ganti_sandi=False)
    req=request(state={'akun':account,'peran_asli':original})
    refs=native_references(req,account)
    assert refs['tuan'] is admin and refs['peran']==mode and calls==[roles.V_SUPER]
    assert refs['columns']==REFS['columns'] and refs['processes']==REFS['processes']
    if mode is None:assert spesifikasi('/pengaturan/peran',native=refs) is None


@pytest.mark.asyncio
async def test_bad_session_context_no_import_no_render_and_actual_metadata_drift_declines(monkeypatch):
    import app.web.pengaturan_detail_kerangka as module
    account=SimpleNamespace(harus_ganti_sandi=False)
    req=request(state={'akun':object()});assert not akun_native(req,account)
    assert await kerangka(req,account,{}) is None
    req.state.akun=account;req.state.portal_scope=object();assert native_references(req,account) is None
    req.state.portal_scope=None;account.harus_ganti_sandi=True;assert native_references(req,account) is None
    account.harus_ganti_sandi=False
    monkeypatch.setattr(module,'native_references',lambda *_:flags(False,'gudang'))
    monkeypatch.setattr(module,'aset',lambda:dict(sumber='a'*64,references={k:REFS[k] for k in ('columns','processes')}))
    registry=dict(cap='cap',konteks='ctx',sesi='fixture-token')
    data=await susun(req,account,registry=registry)
    assert data['targets']=={'/pengaturan/peran':'peran-gudang','/pengaturan/akses':'akses','/pengaturan/sistem':'sistem-umum'}
    monkeypatch.setattr(module,'aset',lambda:dict(sumber='a'*64,references={'columns':['wrong'],'processes':REFS['processes']}))
    assert await susun(req,account,registry=registry) is None


@pytest.mark.asyncio
async def test_direct_document_render_keeps_native_generic_blocktitle_and_no_invented_mobile_back(monkeypatch):
    from starlette.responses import HTMLResponse
    import app.web.pengaturan_detail_kerangka as module
    seen=[]
    def render(req,name,**context):seen.append((name,context));return HTMLResponse('pure-render-double')
    monkeypatch.setitem(sys.modules,'app.web.tampilan',SimpleNamespace(render=render))
    monkeypatch.setattr(module,'native_references',lambda *_:flags(False,'gudang'))
    account=SimpleNamespace(harus_ganti_sandi=False)
    req=request('/pengaturan/sistem',headers=[(b'x-kerangka-halaman',b'1')],state={'akun':account})
    context={'SHELL':{'data_url':'/pengaturan/sistem','stamp':'ctx|/pengaturan/sistem'}}
    result=await kerangka(req,account,context)
    assert result.headers['cache-control']=='private, no-store'
    assert seen[0][0]=='pengaturan_detail_kerangka.html'
    assert seen[0][1]['PG_DETAIL_SHELL']['heading']=='Informasi versi'
    assert seen[0][1]['PG_DETAIL_SHELL']['title']=='Pengaturan'
    assert 'kembali' not in seen[0][1] and set(context)=={'SHELL'}


def _ast_shape(value):
    """Semantic fields only; keep nonempty generic parameters on newer Python."""
    if isinstance(value,ast.AST):
        return [type(value).__name__,[[key,_ast_shape(item)] for key,item in ast.iter_fields(value)
            if key not in {'lineno','end_lineno','col_offset','end_col_offset'} and not (key=='type_params' and not item)]]
    if isinstance(value,list):return [_ast_shape(item) for item in value]
    if value is Ellipsis:return ['literal','Ellipsis']
    if isinstance(value,bytes):return ['literal-bytes',value.hex()]
    if isinstance(value,complex):return ['literal-complex',repr(value)]
    return value


def _ast_fingerprint(node):
    return hashlib.sha256(json.dumps(_ast_shape(node),ensure_ascii=True,separators=(',',':')).encode()).hexdigest()


def _native_functions(tree):
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))]
    functions={n.name:n for n in nodes}
    assert len(nodes)==len(functions), 'Duplicate native function definition'
    return functions


def _native_envelope(tree):
    return ast.Module(body=[n for n in tree.body if not isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))],type_ignores=tree.type_ignores)


def _baseline():
    receipt=json.loads((ROOT/'tests/fixtures/pengaturan_detail_prechange/baseline.json').read_text())
    assert receipt['version']==1 and receipt['module']=='app/web/pengaturan.py'
    assert receipt['baseline_commit']=='144d5f17bcca6eb8c2c0cf2d278246548310529a'
    assert receipt['baseline_git_blob']=='e8ed57ce6913fff0fe09d7700c970a2214cb52d7'
    assert receipt['baseline_source_sha256']=='49bce60991dccf0faedae57d7f1687e9113ef245a7daabfef60ad16ef70eaae6'
    assert receipt['adopted_commit']=='7cddbb56aad9141631b09adcb2a9b99a8378d5eb'
    return receipt


def test_shared_caller_keeps_all_original_guards_readers_and_writers_except_declared_get_block(monkeypatch):
    # Works in a sealed source export or shallow CI checkout. A command here
    # would be an error: baseline provenance was verified once and recorded.
    def no_command(*_,**__):raise AssertionError('Native baseline proof must not call Git or any command')
    monkeypatch.setattr(subprocess,'run',no_command)
    receipt=_baseline();new=ast.parse((ROOT/receipt['module']).read_text())
    after=_native_functions(new)
    assert set(after)==set(receipt['functions'])
    assert _ast_fingerprint(_native_envelope(new))==receipt['module_envelope_sha256']
    for name,function in after.items():
        if name!='halaman_pengaturan':assert _ast_fingerprint(function)==receipt['functions'][name], name
    caller=after['halaman_pengaturan']
    assert 'Depends(butuh_akun)' in ast.unparse(caller.args)
    remove=[n for n in caller.body if isinstance(n,ast.ImportFrom) and n.module=='app.web.pengaturan_detail_kerangka' or isinstance(n,ast.If) and ast.unparse(n.test)=='permintaan_kerangka(request)']
    assert len(remove)==2
    added=remove[1];source=ast.unparse(added)
    assert _ast_fingerprint(ast.Module(body=remove,type_ignores=[]))==receipt['declared_get_block_sha256']
    assert "bagian == 'peran' and (not _P.boleh_ganti_gudang(peran_asli_detail))" in source
    assert 'Pilihan tampilan dan gudang tidak tersedia untuk akun ini.' in source
    assert caller.body.index(added)>next(i for i,n in enumerate(caller.body) if isinstance(n,ast.If) and "'sebab-berhenti'" in ast.unparse(n.test))
    caller.body=[n for n in caller.body if n not in remove]
    assert _ast_fingerprint(caller)==receipt['functions']['halaman_pengaturan']


def test_fixed_baseline_oracle_detects_writer_commit_or_declared_guard_changes():
    receipt=_baseline();tree=ast.parse((ROOT/receipt['module']).read_text());functions=_native_functions(tree)
    writer=copy.deepcopy(functions['tambah_gudang'])
    commits=[n for n in ast.walk(writer) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='commit']
    assert commits, 'Control must exercise an actual native writer commit'
    commits[0].func.attr='rollback' # AST-only negative control, never executed
    assert _ast_fingerprint(writer)!=receipt['functions']['tambah_gudang']
    caller=functions['halaman_pengaturan']
    block=[n for n in caller.body if isinstance(n,ast.ImportFrom) and n.module=='app.web.pengaturan_detail_kerangka' or isinstance(n,ast.If) and ast.unparse(n.test)=='permintaan_kerangka(request)']
    assert len(block)==2
    altered=copy.deepcopy(block)
    altered[1].body.append(ast.Pass())
    assert _ast_fingerprint(ast.Module(body=altered,type_ignores=[]))!=receipt['declared_get_block_sha256']


def test_public_source_only_compiler_and_current_native_breadcrumbs():
    code=r'''
import importlib.abc,importlib.util,json,sys
from pathlib import Path
from bs4 import BeautifulSoup
class NoApp(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='app' or fullname.startswith('app.'):raise AssertionError('Application runtime import '+fullname)
sys.meta_path.insert(0,NoApp())
p=Path('scripts/buat_kerangka_pengaturan_detail.py');s=importlib.util.spec_from_file_location('settings_detail_public',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
payload,meta=m.build()
assert payload==Path('app/web/static/kerangka-pengaturan-detail-ui.js').read_bytes()
assert meta==Path('app/web/static/kerangka-pengaturan-detail-ui.meta.json').read_bytes()
data=json.loads(payload.decode().split('window.PadiKerangkaPengaturanDetailData=',1)[1].split(';\n',1)[0])
assert len(data['variants'])==8 and len(data['styles'])==1 and len(data['scripts'])==2
for v in data['variants'].values():
 d=BeautifulSoup(v['html'],'html.parser');b=BeautifulSoup(v['breadcrumb'],'html.parser')
 assert v['title']=='Pengaturan' and not d.select('form,[name],[data-post],[data-kirim],[aria-checked]')
 assert all(n.has_attr('disabled') and not n.has_attr('value') for n in d.select('input,select,textarea'))
 assert [n.get_text() for n in b.select('.nav-rantai li')]==['\nBeranda\n','›\nPengaturan\n','›\nDetail\n'] or [' '.join(n.get_text().split()).replace('› ','') for n in b.select('.nav-rantai li')]==['Beranda','Pengaturan','Detail']
 assert b.select_one('.desktop-back')['href']=='/pengaturan'
assert len(payload)<=262144
print('SOURCE_ONLY_SETTINGS_6_ROUTES_8_VARIANTS_PASS')
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'SOURCE_ONLY_SETTINGS_6_ROUTES_8_VARIANTS_PASS' in result.stdout
