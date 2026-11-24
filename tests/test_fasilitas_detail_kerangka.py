"""Pure first-click protocol/source proof; no PG, browser or account provisioning."""
import ast
import copy
import hashlib
import html
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
from starlette.responses import HTMLResponse
from tests.native_source_oracle import legacy_dump_fingerprint
from app.web.fasilitas_detail_kerangka import PARENT,VARIANTS,blueprint,deskripsi,valid_entry
from app.web.fasilitas_detail_catalog import HOST,LIMIT,pasang,susun_data

ROOT=Path(__file__).parents[1]
CAP='fixture-cap';CTX='fixture-context';TOKEN='fixture-token';PROGRAM='a'*64


def fixture(rows=None,dryers=None,labels=None):
    # Already-loaded column protocol doubles, never fabricated product ORM.
    rows=rows if rows is not None else [SimpleNamespace(id=17,nama='Line A',dryer_id=None)]
    dryers=dryers if dryers is not None else []
    names={vars(d)['id']:vars(d)['nama'] for d in dryers}
    links=[]
    for i,row in enumerate(rows):
        values=vars(row);label=(labels or {}).get(values['id'],names.get(values.get('dryer_id'),values.get('nama','?')))
        links.append(f'<a class="pg-pintu" href="/pengaturan/mesin/{values["id"]}"><span class="pg-pintu__isi"><strong>{html.escape(label)}</strong><small>native description</small></span></a>')
    body=('<html data-versi="'+CAP+'"><body><div class="bingkai" data-pindah-alamat="'+PARENT+'" data-pindah-konteks="'+CTX+'"><div id="formulir-sesi" data-token="'+TOKEN+'"></div><main id="isi-halaman"><!-- isi-halaman:mulai --><section data-fasilitas><h1>Mesin &amp; line produksi</h1><section class="pg-grup">'+''.join(links)+'</section></section><!-- isi-halaman:akhir --></main></div></body></html>').encode()
    context=dict(mode='mesin',detail=None,pengering=None,err='',isian={},lini=rows,dryer=dryers)
    return body,context


def catalog(body=None,context=None,**delta):
    default_body,default_context=fixture()
    args=dict(source=PARENT,body=body if body is not None else default_body,context=context if context is not None else default_context,cap=CAP,konteks=CTX,sesi=TOKEN,sumber=PROGRAM)
    return susun_data(**{**args,**delta})


@pytest.mark.parametrize('path',[
    '/pengaturan/mesin/0','/pengaturan/mesin/017','/pengaturan/mesin/-1','/pengaturan/mesin/2147483648',
    '/pengaturan/mesin','/pengaturan/dryer/17','/pengaturan/jenis-proses','/pengaturan/mesin/17/edit',
    '/pengaturan/mesin/17?tersimpan=1','/pengaturan/mesin/17#edit','//other.invalid/pengaturan/mesin/17'])
def test_only_actual_bare_line_targets_are_described(path):assert deskripsi(path) is None


def test_public_schema_contains_no_record_or_direct_reader():
    assert deskripsi('/pengaturan/mesin/17')==dict(id=17,alamat='/pengaturan/mesin/17')
    assert deskripsi('/pengaturan/mesin/17','pesan=tersimpan') is None
    assert blueprint('unknown') is None
    source=(ROOT/'app/web/fasilitas_detail_kerangka.py').read_text()
    assert not any(word in source for word in ('SessionLocal','select(','async def','butuh_super','from app.models'))
    assert valid_entry(dict(id=17,label='Actual native label',variant='line',target='/pengaturan/mesin/17'))
    assert not valid_entry(dict(id=True,label='x',variant='line',target='/pengaturan/mesin/1'))


@pytest.mark.parametrize('variant',VARIANTS)
def test_inert_fields_native_labels_and_title_no_default_config_or_operation_keys(variant):
    env=Environment(loader=ChoiceLoader([FileSystemLoader(ROOT/'app/web/templates'),FileSystemLoader(ROOT/'hmu_tampilan/templates')]),autoescape=True,undefined=StrictUndefined)
    template=env.get_template('fasilitas_detail_kerangka.html')
    spec=blueprint(variant)
    doc=BeautifulSoup(''.join(template.blocks['isi'](template.new_context(dict(FD_SHELL=spec,VERSI=CAP)))),'html.parser')
    native=env.get_template('fasilitas.html')
    assert ''.join(template.blocks['judul'](template.new_context({})))==''.join(native.blocks['judul'](native.new_context({'mode':'mesin'})))
    assert doc.h1.get_text()=='__PADI_FASILITAS_LABEL__'
    assert [n.get_text() for n in doc.select('dt')]==['Gudang','Jenis proses','Status line']+(['Status dryer'] if variant=='dryer' else [])
    assert all(n.get_text()=='Belum dibaca' for n in doc.select('dd'))
    assert not doc.select('form,[name],input[value],input[type=hidden],[data-simpan-alat],[data-jaga-isian],[data-pengaturan-form]')
    assert all(n.has_attr('disabled') and not n.has_attr('checked') for n in doc.select('input,select'))
    assert all(n['aria-checked']=='mixed' for n in doc.select('input[type=checkbox]'))
    assert all(n.has_attr('disabled') and n['type']=='button' for n in doc.select('button:not([data-fd-retry])'))
    assert doc.select_one('summary').get_text()=='Hubungan proses & kode'
    assert doc.select_one('.pg-kembali')['href']==PARENT
    assert ('Pengaturan pengering' in doc.get_text()) is (variant=='dryer')
    assert not doc.select('script[src*="pengaturan-alat.js"],script[src*="pengaturan-isian.js"]')
    if variant=='dryer':
        assert 'Status dryer belum dibaca' in doc.get_text() and 'Nonaktifkan dryer' not in doc.get_text()
    macro=(ROOT/'app/web/templates/_fasilitas_form.html').read_text()
    for label in ('Nama','Kode','Gudang','Jenis proses','Dryer terkait (pengeringan)','Aktif'):
        assert label in doc.get_text() and label in macro


def test_parent_actual_columns_select_native_h1_and_dryer_variant_not_url_type():
    rows=[SimpleNamespace(id=17,nama='Line A',dryer_id=None),SimpleNamespace(id=18,nama='Line B',dryer_id=3)]
    body,context=fixture(rows,[SimpleNamespace(id=3,nama='Pengering Aktual')])
    data=catalog(body,context)
    assert data['entries']==[dict(id=17,label='Line A',variant='line',target=PARENT+'/17'),dict(id=18,label='Pengering Aktual',variant='dryer',target=PARENT+'/18')]
    assert set(data)=={'versi','cap','konteks','sesi','sumber','source_address','sumber_sha256','entries'}
    assert data['sumber_sha256']==hashlib.sha256(PARENT.encode()).hexdigest()
    assert all(set(row)=={'id','label','variant','target'} for row in data['entries'])


def test_loaded_columns_only_no_property_or_relationship_access():
    class ColumnsOnly:
        def __init__(self):self.__dict__.update(id=17,nama='Loaded only',dryer_id=None)
        def __getattribute__(self,key):
            if key in {'id','nama','dryer_id'}:raise AssertionError('Lazy/property access forbidden')
            return object.__getattribute__(self,key)
    body,context=fixture([ColumnsOnly()])
    assert catalog(body,context)['entries'][0]['label']=='Loaded only'


@pytest.mark.parametrize('delta',[
    {'mode':'jenis'},{'detail':object()},{'pengering':object()},{'err':'failed'},{'isian':{'nama':'draft'}},{'isian':None},{'lini':None},{'dryer':None}])
def test_other_contexts_or_error_drafts_cannot_issue_parent_catalog(delta):
    body,context=fixture();assert catalog(body,{**context,**delta}) is None


def test_missing_reference_unknown_link_mismatched_label_and_hidden_sources_decline():
    body,context=fixture()
    for key in ('mode','detail','pengering','err','isian','lini','dryer'):
        missing={**context};missing.pop(key);assert catalog(body,missing) is None
    assert catalog(body.replace(b'/mesin/17',b'/mesin/18'),context) is None
    assert catalog(body.replace(b'Line A',b'Other'),context) is None
    assert catalog(body.replace(b'class="pg-pintu"',b'class="pg-pintu" hidden'),context) is None
    assert catalog(body,{**context,'lini':[SimpleNamespace(id=17,nama='Line A')]}) is None
    assert catalog(body,{**context,'lini':[SimpleNamespace(id=True,nama='Line A',dryer_id=None)]}) is None
    assert catalog(body,{**context,'lini':[context['lini'][0],context['lini'][0]]}) is None


@pytest.mark.parametrize('delta',[
    {'source':'/pengaturan/mesin?tersimpan=1'},{'source':'/pengaturan/mesin/17'},{'cap':'old'},{'konteks':'old'},{'sesi':'old'},{'sumber':'not-a-program-sha'}])
def test_private_scope_and_program_identity_must_match_actual_native_frame(delta):assert catalog(**delta) is None


def test_catalog_bound_does_not_modify_or_drop_extra_native_links():
    rows=[SimpleNamespace(id=i,nama='Line '+str(i),dryer_id=None) for i in range(1,LIMIT+4)]
    body,context=fixture(rows);original=body
    data=catalog(body,context)
    assert len(data['entries'])==LIMIT and [r['id'] for r in data['entries']]==list(range(1,LIMIT+1))
    assert body==original and len(BeautifulSoup(body,'html.parser').select('a.pg-pintu'))==LIMIT+3


def test_decoration_requires_actual_native_parent_endpoint_not_admin_boolean(monkeypatch):
    import app.web.fasilitas_detail_catalog as module
    def owner():pass
    monkeypatch.setitem(sys.modules,'app.web.fasilitas',SimpleNamespace(daftar=owner))
    monkeypatch.setitem(sys.modules,'hmu_tampilan',SimpleNamespace(CAP_ASET=CAP))
    monkeypatch.setattr(module,'aset',lambda:dict(sumber=PROGRAM))
    body,context=fixture([SimpleNamespace(id=17,nama='Name <img> & "x"',dryer_id=None)])
    account=SimpleNamespace(harus_ganti_sandi=False,is_admin=True)
    req=Request(dict(type='http',method='GET',scheme='https',server=('fixture.invalid',443),path=PARENT,query_string=b'',headers=[],state={'akun':account},endpoint=object()))
    def response():
        value=HTMLResponse(body);value.context={**context,'akun':account,'PINDAH_KONTEKS':CTX,'CSRF':TOKEN};return value
    denied=response();assert pasang(req,account,denied).body==body
    req.scope['endpoint']=owner;result=pasang(req,account,response())
    assert result.headers['cache-control']=='private, no-store'
    doc=BeautifulSoup(result.body,'html.parser');host=doc.select_one('#'+HOST)
    assert host and '\\u003cimg\\u003e' in host.string
    assert json.loads(host.string)['entries'][0]['label']=='Name <img> & "x"'
    assert int(result.headers['content-length'])==len(result.body)
    for key,value in [('method','POST'),('path',PARENT+'/17'),('query_string',b'err=x')]:
        # Each real ASGI request owns its URL cache; do not mutate one that
        # Starlette has already resolved while pretending it is a new request.
        other=Request({**req.scope,key:value})
        assert pasang(other,account,response()).body==body
    req.state.portal_scope=object();assert pasang(req,account,response()).body==body


def _digest(node):return legacy_dump_fingerprint(node)


def test_fixed_native_baseline_no_direct_shortcut_guard_change_or_writer_and_no_git(monkeypatch):
    monkeypatch.setattr(subprocess,'run',lambda *a,**k:(_ for _ in ()).throw(AssertionError('No command/Git in baseline proof')))
    receipt=json.loads((ROOT/'tests/fixtures/fasilitas_detail_prechange/baseline.json').read_text())
    assert receipt['baseline_commit']=='ef7e9c7a0d9cf4bce67f63c159a7b55966f78655'
    assert receipt['baseline_git_blob']=='c55a7dcd255585741a68e2d57aa3c1aafeab6265'
    tree=ast.parse((ROOT/receipt['module']).read_text())
    nodes=[n for n in tree.body if isinstance(n,(ast.FunctionDef,ast.AsyncFunctionDef))];functions={n.name:n for n in nodes}
    assert len(nodes)==len(functions) and set(functions)==set(receipt['functions'])
    assert _digest(ast.Module(body=[n for n in tree.body if n not in nodes],type_ignores=tree.type_ignores))==receipt['module_envelope_sha256']
    for name,node in functions.items():
        if name!='halaman':assert _digest(node)==receipt['functions'][name],name
    caller=functions['halaman'];tail=caller.body[-3:]
    assert _digest(ast.Module(body=tail,type_ignores=[]))==receipt['decoration_tail_sha256']
    assert isinstance(tail[0],ast.Assign) and ast.unparse(tail[2])=='return pasang(request, akun, response)'
    caller.body=caller.body[:-3]+[ast.Return(value=tail[0].value)]
    assert _digest(caller)==receipt['functions']['halaman']
    guards=ast.parse((ROOT/receipt['native_guard_module']).read_text())
    guard_functions={node.name:node for node in guards.body if isinstance(node,ast.AsyncFunctionDef)}
    assert set(receipt['native_guard_functions'])<=guard_functions.keys()
    for name,expected in receipt['native_guard_functions'].items():assert _digest(guard_functions[name])==expected
    for path,expected in receipt['original_controller_sha256'].items():assert hashlib.sha256((ROOT/path).read_bytes()).hexdigest()==expected,path
    assert 'Depends(butuh_super)' in ast.unparse(functions['daftar'].args)
    source=(ROOT/'app/web/fasilitas_detail_catalog.py').read_text()
    assert "request.scope.get('endpoint') is not daftar" in source
    catalog_tree=ast.parse(source)
    imports={node.module for node in ast.walk(catalog_tree) if isinstance(node,ast.ImportFrom)}
    assert imports<={'functools','pathlib','bs4','app.web.fasilitas_detail_kerangka','app.web.fasilitas','hmu_tampilan','jinja2.utils'}
    assert not any(isinstance(node,ast.Await) or isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in {'execute','scalar','scalars','commit','flush','add','delete'} for node in ast.walk(catalog_tree))
    assert not any(token in source for token in ('SessionLocal','is_admin','is_super','token_baru(','db.'))
    # Nonexecuted control: the oracle detects a native writer commit change.
    changed=copy.deepcopy(functions['simpan'])
    commit=next(n for n in ast.walk(changed) if isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='commit')
    commit.func.attr='rollback';assert _digest(changed)!=receipt['functions']['simpan']


def test_source_only_compiler_current_native_title_breadcrumb_and_no_original_controllers():
    code=r'''
import importlib.abc,importlib.util,json,sys
from pathlib import Path
from bs4 import BeautifulSoup
class NoApp(importlib.abc.MetaPathFinder):
 def find_spec(self,fullname,path=None,target=None):
  if fullname=='app' or fullname.startswith('app.'):raise AssertionError('Application runtime import '+fullname)
sys.meta_path.insert(0,NoApp())
p=Path('scripts/buat_kerangka_fasilitas_detail.py');s=importlib.util.spec_from_file_location('facility_compile_only',p);m=importlib.util.module_from_spec(s);s.loader.exec_module(m)
payload,meta=m.build()
assert payload==Path('app/web/static/kerangka-fasilitas-detail-ui.js').read_bytes()
assert meta==Path('app/web/static/kerangka-fasilitas-detail-ui.meta.json').read_bytes()
data=json.loads(payload.decode().split('window.PadiKerangkaFasilitasDetailData=',1)[1].split(';\n',1)[0])
assert list(data['variants'])==['line','dryer'] and len(data['styles'])==1 and len(data['scripts'])==2
for v in data['variants'].values():
 d=BeautifulSoup(v['html'],'html.parser');b=BeautifulSoup(v['breadcrumb'],'html.parser')
 assert v['title']=='Mesin & line produksi' and d.h1.get_text()=='__PADI_FASILITAS_LABEL__'
 assert not d.select('form,[name],input[value],[data-simpan-alat],[data-pengaturan-form],script[src]')
 assert b.select_one('a')['href']=='/' and b.select_one('[aria-current=page]').get_text()=='Mesin & line produksi'
 assert b.select_one('.desktop-back')['href']=='/pengaturan'
 assert '/pengaturan/mesin/1' not in v['html']+v['breadcrumb']
assert not any('randomUUID' in s or "method: 'POST'" in s for s in data['scripts'].values())
assert len(payload)<=262144
print('SOURCE_ONLY_LINE_FIRST_CLICK_PASS')
'''
    result=subprocess.run([sys.executable,'-c',code],cwd=ROOT,text=True,capture_output=True,timeout=30)
    assert result.returncode==0,result.stdout+result.stderr
    assert 'SOURCE_ONLY_LINE_FIRST_CLICK_PASS' in result.stdout
