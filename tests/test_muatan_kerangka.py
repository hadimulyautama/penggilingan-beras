"""Pure Muatan shape/guard plumbing; no DB/device/runtime execution."""
import ast
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace as NS
import sys

import pytest
from bs4 import BeautifulSoup

ROOT=Path(__file__).resolve().parents[1]
def module(name,path):
 spec=importlib.util.spec_from_file_location(name,ROOT/path);value=importlib.util.module_from_spec(spec);spec.loader.exec_module(value);return value
shape=module('muat_native_spec','app/web/muatan_kerangka.py')
REG=dict(cap='cap-example',konteks='context-example',sesi='session-example')
def request(*,path='/muatan',query='',headers=None,account=None):
 return NS(method='GET',url=NS(path=path,query=query),headers=headers or {},state=NS(akun=account,portal_scope=None))

@pytest.mark.parametrize('record,financial,expected',[(True,False,True),(True,True,True),(False,True,False),(False,False,None),(1,False,None),(False,None,None)])
def test_only_exact_native_predicate_outcome_controls_structure(record,financial,expected):
 p=shape.project(can_record=record,can_read_financial=financial)
 assert p==({'can_record':expected} if expected is not None else None)

@pytest.mark.parametrize('query,headers,allowed',[
 ('',{'X-Kerangka-Halaman':'1'},True),('',{'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'},True),
 ('',{'X-Kerangka-Halaman':'1','X-Pindah':'1'},False),('',{'X-Pindah':'1'},False),
 ('perintah=7',{'X-Kerangka-Halaman':'1'},False),('item=2&semua=1',{'X-Kerangka-Halaman':'1'},False),
 ('buka=1',{'X-Kerangka-Halaman':'1'},False),('',{},False)])
def test_bare_canonical_only_native_data_and_deep_action_links_unchanged(query,headers,allowed):
 assert shape.permitted_document(request(query=query,headers=headers)) is allowed
 assert not shape.permitted_document(request(path='/barang-keluar/7/muatan',headers=headers))


def native_guard(monkeypatch):
 # Execute actual role predicates and actual boleh_catat function. Warehouse
 # predicates are explicit isolated outcome stubs; this is no SQL/ACL claim.
 P=module('muat_native_peran','hmu_identitas/peran.py')
 monkeypatch.setitem(sys.modules,'hmu_identitas',NS(peran=P))
 tree=ast.parse((ROOT/'app/peran.py').read_text());fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='can_see_financials')
 ns={'User':object,'P':P,'PERAN_UANG':P.PERAN_UANG};exec(compile(ast.Module(body=[fn],type_ignores=[]),'native-financial-predicate','exec'),ns)
 financial=ns['can_see_financials'];calls=[]
 async def g1(user):calls.append('g1');return user.scope=='g1'
 async def g2(user):calls.append('g2');return user.scope=='g2'
 tree=ast.parse((ROOT/'app/web/muatan.py').read_text());fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='boleh_catat')
 ns={'can_see_financials':financial,'_is_g1_operator':g1,'_is_g2_operator':g2};exec(compile(ast.Module(body=[fn],type_ignores=[]),'actual-boleh-catat','exec'),ns)
 monkeypatch.setitem(sys.modules,'app.web.muatan',NS(boleh_catat=ns['boleh_catat']))
 monkeypatch.setitem(sys.modules,'app.peran',NS(can_see_financials=financial))
 monkeypatch.setitem(sys.modules,'app.web.portal.scope',NS(is_customer_read=lambda req:False))
 return calls

@pytest.mark.parametrize('role,scope,expected,calls',[
 ('superadmin','none',True,[]),('admin','g1',False,[]),
 ('operator','g1',True,['g1']),('operator','g2',True,['g1','g2']),('operator','none',None,['g1','g2'])])
def test_actual_guard_not_view_or_outbound_permission_inference(monkeypatch,role,scope,expected,calls):
 seen=native_guard(monkeypatch);actor=NS(harus_ganti_sandi=False,user=NS(role=role,scope=scope))
 req=request(account=actor);req.state.view='wrong-view-that-must-never-grant'
 permission=asyncio.run(shape.native_permission(req,actor))
 assert permission==({'can_record':expected} if expected is not None else None)
 assert seen==calls


def test_wrong_context_portal_and_mandatory_password_decline_before_guard(monkeypatch):
 async def forbidden(user):raise AssertionError('No guard reads for an unsupported context')
 monkeypatch.setitem(sys.modules,'app.web.muatan',NS(boleh_catat=forbidden))
 monkeypatch.setitem(sys.modules,'app.web.portal.scope',NS(is_customer_read=lambda req:False))
 actor=NS(harus_ganti_sandi=False,user=NS());req=request(account=NS())
 assert asyncio.run(shape.native_permission(req,actor)) is None
 req.state.akun=actor;req.state.portal_scope=NS()
 assert asyncio.run(shape.native_permission(req,actor)) is None
 req.state.portal_scope=None;actor.harus_ganti_sandi=True
 assert asyncio.run(shape.native_permission(req,actor)) is None


def test_private_descriptor_is_bound_small_and_contains_no_business_identity():
 p=shape.descriptor({'can_record':True},registry=REG,source='a'*64)
 assert p==dict(versi=1,sumber='a'*64,**REG,permission={'can_record':True})
 for bad in [{'can_record':1},{'can_record':True,'outgoing_id':2},{'role':'operator'}]:
  assert shape.descriptor(bad,registry=REG,source='a'*64) is None
 assert shape.descriptor({'can_record':False},registry=dict(REG,sesi=''),source='a'*64) is None
 assert shape.descriptor({'can_record':False},registry=REG,source='bad') is None


def test_fresh_data_and_action_queries_bypass_shape_without_extra_read(monkeypatch):
 async def forbidden(*args,**kwargs):raise AssertionError('No optional reference/guard read for X1/query')
 monkeypatch.setitem(sys.modules,'app.web.halaman_bertahap',NS(konteks_kerangka=forbidden))
 actor=NS(harus_ganti_sandi=False,user=NS())
 for req in [request(account=actor,headers={'X-Pindah':'1'}),request(account=actor,headers={'X-Kerangka-Halaman':'1'},query='perintah=7')]:
  assert asyncio.run(shape.kerangka(req,actor,boleh=True)) is None


def test_direct_shape_uses_already_evaluated_native_boleh_and_actual_navigation(monkeypatch):
 actor=NS(harus_ganti_sandi=False,user=NS());req=request(account=actor,headers={'X-Kerangka-Halaman':'1'})
 nav={'EXACT_NATIVE_REFERENCE':object()};calls=[]
 async def light(r,a):assert r is req and a is actor;calls.append('nav');return nav
 async def forbidden(*args):raise AssertionError('Direct helper must not repeat native guard')
 monkeypatch.setitem(sys.modules,'app.web.portal.scope',NS(is_customer_read=lambda r:False))
 monkeypatch.setitem(sys.modules,'app.web.muatan',NS(boleh_catat=forbidden))
 monkeypatch.setitem(sys.modules,'app.web.halaman_bertahap',NS(konteks_kerangka=light,penanda_konteks=lambda r,a:REG['konteks']))
 result=NS(headers={})
 def render(r,template,**ctx):
  assert ctx['EXACT_NATIVE_REFERENCE'] is nav['EXACT_NATIVE_REFERENCE']
  assert ctx['MUAT_SHELL']=={'alamat':'/muatan','stamp':REG['konteks']+'|/muatan','can_record':False}
  assert not {'awal','perintah','actor','data','kiriman'}&set(ctx)
  calls.append(template);return result
 monkeypatch.setitem(sys.modules,'app.web.tampilan',NS(render=render))
 assert asyncio.run(shape.kerangka(req,actor,boleh=False)) is result
 assert calls==['nav','muatan_kerangka.html']
 assert result.headers=={'Cache-Control':'private, no-store','Vary':'Cookie'}


def test_native_handler_keeps_guard_and_every_original_data_statement():
 current=ast.parse((ROOT/'app/web/muatan.py').read_text());fn=next(n for n in current.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='halaman')
 before=ast.parse((ROOT/'tests/fixtures/muatan_prechange/halaman.py').read_text()).body[0]
 early=next(i for i,n in enumerate(fn.body) if isinstance(n,ast.ImportFrom) and n.module=='app.web.muatan_kerangka')
 assert 'wajib(' in ast.unparse(fn.body[early-1]) and isinstance(fn.body[early+3],ast.AsyncWith)
 cleaned=ast.AsyncFunctionDef(**{**fn.__dict__,'body':fn.body[:early]+fn.body[early+3:]})
 assert ast.dump(cleaned,include_attributes=False)==ast.dump(before,include_attributes=False)
 helper=(ROOT/'app/web/muatan_kerangka.py').read_text()
 assert 'SessionLocal' not in helper and 'await papan' not in helper and '.commit(' not in helper


def test_compiler_keeps_two_exact_permission_shapes_and_inert_native_columns():
 compiler=module('muat_compiler_spec','scripts/buat_kerangka_muatan.py');first=compiler.build();assert first==compiler.build()
 payload,meta_raw=first;meta=json.loads(meta_raw)
 assert meta['variants']==['/muatan'] and hashlib.sha256(payload).hexdigest()==meta['aset_sha256']
 data=json.loads(payload.decode().split('window.PadiKerangkaMuatanData=',1)[1].split(';\n',1)[0]);variant=data['variants']['/muatan']
 read=BeautifulSoup(variant['read'],'html.parser');record=BeautifulSoup(variant['record'],'html.parser')
 for doc in (read,record):
  assert doc.select_one('h1').text=='Muat pengiriman'
  assert [n.text for n in doc.select('thead th')]==['Barang','Perintah','Total dimuat','Status sisa belum dibaca']
  assert len(doc.select('tbody tr'))==1 and doc.select_one('tbody td')['colspan']=='4'
  assert not doc.select('form,input,select,textarea,[name],[data-editor-perintah],[data-lembar-muatan],[data-catat-muatan],#lembar-awal,[data-perintah],[data-actor]')
  assert all(n.has_attr('disabled') for n in doc.select('button:not([data-muat-native-retry])'))
  assert doc.select_one('[data-muat-native-retry]').has_attr('hidden')
 assert len(read.select('.mr-actions button'))==0 and len(record.select('.mr-actions button'))==2
 assert set(variant['breadcrumbs'])=={'/muatan','/barang-keluar'}
 assert 'Muatan' in variant['breadcrumbs']['/muatan']
 assert 'Barang Keluar' in variant['breadcrumbs']['/barang-keluar']
 assert all('sessionStorage' not in s and 'muat-semua' not in s for s in data['scripts'].values())
 native=(ROOT/'app/web/static/muat-ringkas.js').read_text()
 assert "const storage='lembar-muatan-v1:'" in native and 'lastRequest' in native and 'uncertain' in native
 assert not any('muat-ringkas.js' in s for s in data['scripts'].values())
 assert any('[data-muatan-native] .mr-table thead{display:table-header-group}' in s for s in data['styles'].values())
