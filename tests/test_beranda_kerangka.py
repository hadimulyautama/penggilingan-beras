"""Pure presentation contracts; no DB, account provisioning or browser claim."""
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
spec=importlib.util.spec_from_file_location('home_native_spec',ROOT/'app/web/beranda_kerangka.py')
home=importlib.util.module_from_spec(spec);spec.loader.exec_module(home)
REF=dict(sapaan='Selamat pagi, Contoh',tanggal='Selasa, 24 November 2026',scope='Semua gudang',semua_gudang=True)
REG=dict(cap='cap-example',konteks='context-example',sesi='session-example')


def request(*,path='/',query='',headers=None,account=None,view='admin'):
 return NS(method='GET',url=NS(path=path,query=query),headers=headers or {},state=NS(akun=account,view=view,portal_scope=None))

@pytest.mark.parametrize('view,scope,all_warehouses',[
 ('admin','Semua gudang',True),('super','Semua gudang',True),
 ('selepan','Gudang 1 · Selepan',False),('polesan','Gudang 2 · Penyosohan',False),('tamu','Belum punya gudang',False)])
def test_projection_matches_native_header_without_domain_data(view,scope,all_warehouses):
 result=home.project(view=view,meja=('admin','super'),selepan='selepan',polesan='polesan',tamu='tamu',greeting=REF['sapaan'],date=REF['tanggal'])
 assert result==dict(REF,scope=scope,semua_gudang=all_warehouses)
 assert set(result)=={'sapaan','tanggal','scope','semua_gudang'}
 native=(ROOT/'hmu_tampilan/templates/beranda.html').read_text()
 assert scope in native

@pytest.mark.parametrize('view',[None,'unknown','pelanggan',2])
def test_unknown_view_is_not_defaulted_to_a_granted_warehouse(view):
 assert home.project(view=view,meja=('admin',),selepan='selepan',polesan='polesan',tamu='tamu',greeting='Sapaan',date='Tanggal') is None

@pytest.mark.parametrize('query,headers,allowed',[
 ('',{'X-Kerangka-Halaman':'1'},True),('',{'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'},True),
 ('',{'X-Kerangka-Halaman':'1','X-Pindah':'1'},False),('',{'X-Pindah':'1'},False),
 ('buka=packing',{'X-Kerangka-Halaman':'1'},False),('pesan=ok',{'X-Kerangka-Halaman':'1'},False),
 ('',{},False)])
def test_document_shape_does_not_intercept_native_data_feedback_or_actions(query,headers,allowed):
 assert home.permitted_document(request(query=query,headers=headers)) is allowed
 assert not home.permitted_document(request(path='/beranda',headers=headers))


def test_native_reference_adapter_consumes_already_bound_values_only(monkeypatch):
 monkeypatch.setitem(sys.modules,'app.web.portal.scope',NS(is_customer_read=lambda r:False))
 monkeypatch.setitem(sys.modules,'app.web.layar',NS(MEJA=('admin','super'),SELEPAN='selepan',POLESAN='polesan',TAMU='tamu'))
 calls=[]
 monkeypatch.setitem(sys.modules,'app.services.beranda',NS(sapaan_dan_tanggal=lambda name:(calls.append(name) or REF['sapaan'],REF['tanggal'])))
 actor=NS(harus_ganti_sandi=False,user=NS(nama='Contoh Sintetis'))
 req=request(account=actor)
 assert home.native_references(req,actor,{'MUTU_AKTIF':True})==REF
 assert calls==['Contoh Sintetis']
 req.state.view=None
 assert home.native_references(req,actor,{'MUTU_AKTIF':True}) is None
 req.state.view='admin';req.state.akun=NS()
 assert home.native_references(req,actor,{'MUTU_AKTIF':True}) is None
 req.state.akun=actor;req.state.portal_scope=NS()
 assert home.native_references(req,actor,{'MUTU_AKTIF':True}) is None
 req.state.portal_scope=None;actor.harus_ganti_sandi=True
 assert home.native_references(req,actor,{'MUTU_AKTIF':True}) is None
 actor.harus_ganti_sandi=False
 assert home.native_references(req,actor,{'MUTU_AKTIF':None}) is None


def test_private_descriptor_is_exact_and_htmlsafe_not_a_public_identity_cache():
 desc=home.descriptor(REF,registry=REG,source='a'*64)
 assert desc==dict(versi=1,sumber='a'*64,**REG,references=REF)
 for bad in [dict(REF,rows=[]),dict(REF,warehouse_id=1),dict(REF,scope='Invented warehouse'),dict(REF,semua_gudang=False),dict(REF,sapaan='')]:
  assert home.descriptor(bad,registry=REG,source='a'*64) is None
 assert home.descriptor(REF,registry=dict(REG,sesi=''),source='a'*64) is None
 assert home.descriptor(REF,registry=REG,source='not-a-digest') is None
 assert home.descriptor(dict(REF,sapaan='<script>'),registry=REG,source='a'*64) is not None


def test_fresh_native_get_and_queries_never_read_navigation_context(monkeypatch):
 async def forbidden(*args,**kwargs):raise AssertionError('Native data or action query must bypass the optional shell')
 monkeypatch.setitem(sys.modules,'app.web.halaman_bertahap',NS(konteks_kerangka=forbidden))
 actor=NS(harus_ganti_sandi=False)
 for req in [request(account=actor,headers={'X-Pindah':'1'}),request(account=actor,headers={'X-Kerangka-Halaman':'1'},query='buka=isi-silo')]:
  assert asyncio.run(home.kerangka(req,actor)) is None


def test_direct_document_passes_actual_navigation_values_without_domain_dto(monkeypatch):
 actor=NS(harus_ganti_sandi=False)
 req=request(account=actor,headers={'X-Kerangka-Halaman':'1'})
 nav={'MUTU_AKTIF':True,'EXACT_NATIVE_REFERENCE':object()};calls=[]
 async def light(r,a):assert r is req and a is actor;calls.append('read-nav');return nav
 monkeypatch.setitem(sys.modules,'app.web.portal.scope',NS(is_customer_read=lambda r:False))
 monkeypatch.setitem(sys.modules,'app.web.halaman_bertahap',NS(konteks_kerangka=light,penanda_konteks=lambda r,a:REG['konteks']))
 monkeypatch.setattr(home,'native_references',lambda r,a,n:REF if n is nav else None)
 result=NS(headers={})
 def render(r,template,**context):
  assert context['EXACT_NATIVE_REFERENCE'] is nav['EXACT_NATIVE_REFERENCE']
  assert context['HOME_SHELL']==dict(REF,alamat='/',stamp=REG['konteks']+'|/')
  assert not {'berjalan','transit','gudang','petak','muat'}&set(context)
  calls.append(template);return result
 monkeypatch.setitem(sys.modules,'app.web.tampilan',NS(render=render))
 assert asyncio.run(home.kerangka(req,actor)) is result
 assert calls==['read-nav','beranda_kerangka.html']
 assert result.headers=={'Cache-Control':'private, no-store','Vary':'Cookie'}


def test_native_home_early_shape_preserves_the_existing_data_function_remainder():
 tree=ast.parse((ROOT/'app/main.py').read_text());fn=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='beranda')
 sources=[ast.unparse(n) for n in fn.body]
 auth=next(i for i,s in enumerate(sources) if 'await akun_opsional' in s)
 login=next(i for i,s in enumerate(sources) if "RedirectResponse('/masuk'" in s)
 shell=next(i for i,s in enumerate(sources) if 'await kerangka_beranda' in s)
 domain=next(i for i,s in enumerate(sources) if s=='from app.services import berjalan as svc')
 assert auth<login<shell<domain
 module=(ROOT/'app/web/beranda_kerangka.py').read_text()
 assert 'SessionLocal' not in module and 'Berjalan(' not in module and '.commit(' not in module


def test_compiler_is_deterministic_and_invariant_markup_is_not_fake_data():
 spec=importlib.util.spec_from_file_location('home_compiler_spec',ROOT/'scripts/buat_kerangka_beranda.py')
 compiler=importlib.util.module_from_spec(spec);spec.loader.exec_module(compiler)
 first=compiler.build();second=compiler.build();assert first==second
 payload,meta_raw=first;meta=json.loads(meta_raw)
 assert meta['variants']==['/'] and hashlib.sha256(payload).hexdigest()==meta['aset_sha256']
 encoded=payload.decode().split('window.PadiKerangkaBerandaData=',1)[1].split(';\n',1)[0]
 data=json.loads(encoded);doc=BeautifulSoup(data['variants']['/']['html'],'html.parser')
 assert data['variants']['/']['brand']=='PT Hadi Mulya Utama'
 assert len(doc.select('#judul-beranda[data-home-greeting]'))==1
 assert len(doc.select('.beranda-tindaklanjut,.beranda-aktivitas,.beranda-ringkasan'))==3
 assert not doc.select('form,input,select,textarea,[name],[data-post],[data-kirim],iframe')
 assert not doc.select('[data-machine-id],[data-silo-id],.beranda-gudang-padat,table')
 assert 'session-example' not in payload.decode() and 'Contoh Sintetis' not in payload.decode()
 assert doc.select_one('[data-home-native-retry]')['type']=='button'
 assert doc.select_one('[data-home-native-retry]').has_attr('hidden')
 for script in data['scripts'].values():assert "method:'POST'" not in script and 'sessionStorage' not in script
