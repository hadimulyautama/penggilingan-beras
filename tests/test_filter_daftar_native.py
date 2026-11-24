"""Pure contract only; browser/current native registry proof belongs to Root."""
from pathlib import Path
import ast
import importlib.util
import json
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('filter_native_spec',ROOT/'app/web/filter_daftar_native.py')
native=importlib.util.module_from_spec(spec);spec.loader.exec_module(native)

@pytest.mark.parametrize('path,query,family,selection',[
 ('/pekerjaan','','pekerjaan','tindakan'),
 ('/pekerjaan','tab=berjalan&jenis=giling&gudang=g1&kepemilikan=pabrik&halaman=3','pekerjaan','berjalan'),
 ('/pekerjaan','cari=LOT+Nomor+2&pemasok=Nama+belum+dibaca&pelanggan_id=23&grup=packing_jasa&informasi=1','pekerjaan','tindakan'),
 ('/barang-masuk','','masuk','belum'),
 ('/barang-masuk','status=diterima&jenis=pk&kepemilikan=jasa&gudang=g2&pelanggan_id=7&halaman=2','masuk','diterima'),
 ('/barang-masuk','status=belum&cari=GA%2B12&pemasok=Contoh%20sintetis&kembali_jasa=%2Fjasa%2Fpelanggan%2F7%3Ftab%3Dpenerimaan','masuk','belum'),
])
def test_descriptor_preserves_exact_query_order_and_unread_reference(path,query,family,selection):
 d=native.describe(path,query)
 assert d['address']==path+('?' +query if query else '')
 assert d['family']==family and d['selection']==selection
 assert not {'rows','names','status_count','warehouse_id','allowed','actor','tenant'}&set(d)
 assert d['prototype']==path+'?'+('status' if family=='masuk' else 'tab')+'='+selection

@pytest.mark.parametrize('path,query',[
 ('/pekerjaan','buka='),('/pekerjaan','nilai='),('/barang-masuk','company_id=2'),
 ('/pekerjaan','tab=tindakan&tab=berjalan'),('/barang-masuk','status=unknown'),
 ('/pekerjaan','tab='),('/barang-masuk','status='),('/pekerjaan','halaman=0'),
 ('/pekerjaan','halaman=٢'),('/pekerjaan','pelanggan_id=-1'),('/pekerjaan','pelanggan_id=2147483648'),
 ('/pekerjaan','cari='+('x'*201)),('/pekerjaan','pemasok='+('x'*201)),
 ('/barang-masuk','gudang=g3'),('/barang-masuk','kepemilikan=other'),
 ('/pekerjaan','cari=%XX'),('/pekerjaan','cari=%E0%A4'),('/pekerjaan','informasi=2'),
 ('/barang-masuk','kembali_jasa=%2F%2Fexternal.invalid'),('/barang-masuk','kembali_jasa=%2Fpengguna'),
 ('/barang-masuk','kembali_jasa=https%3A%2F%2Fuji%2Fjasa'),
])
def test_unsupported_input_is_left_to_native_handler_without_policy_change(path,query):
 assert native.describe(path,query) is None

@pytest.mark.parametrize('path',list(native.ALIASES)+['/pelanggan/barang-masuk','/barang-masuk/2','/pekerjaan/permintaan/2','/pekerjaan/catat-lain'])
def test_alias_or_resource_is_not_mapped_by_presentation_guess(path):
 assert native.describe(path) is None


def test_native_link_matches_real_tautan_function_without_importing_application_runtime():
 tree=ast.parse((ROOT/'app/web/layar_pekerjaan.py').read_text())
 fn=next(n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name=='tautan')
 module=ast.Module(body=[fn],type_ignores=[])
 from urllib.parse import urlencode
 from types import SimpleNamespace
 namespace={'urlencode':urlencode};exec(compile(module,'native-tautan','exec'),namespace)
 descriptor=native.describe('/pekerjaan','halaman=3&cari=Bu+Uji%7E&pemasok=ABC&tab=berjalan&asal=keputusan&kategori=packing')
 changes=dict(tab='tindakan',asal='',kategori='',grup='',informasi='')
 expected=namespace['tautan'](SimpleNamespace(query_params=dict(descriptor['pairs'])),'/pekerjaan',**changes)
 assert native.native_link(descriptor,**changes)==expected
 assert 'halaman=' not in expected and 'cari=Bu+Uji~' in expected


def test_javascript_and_python_descriptors_keep_the_same_read_contract():
 cases=[('/pekerjaan','tab=berjalan&halaman=3&gudang=g2&pelanggan_id=7'),('/barang-masuk','status=diterima&cari=Bu+Uji%7E'),('/pekerjaan','cari=%E0%A4'),('/barang-masuk','buka='),('/aksi','grup=bahan')]
 script="const {address,nativeLink}=require('./app/web/static/filter-daftar-native.js');const cases="+json.dumps(cases)+";process.stdout.write(JSON.stringify(cases.map(([p,q])=>{const s=address(p+(q?'?'+q:''),'https://uji');return s?{path:s.path,address:s.address,family:s.family,selection:s.selection,prototype:s.prototype,pairs:s.pairs,link:nativeLink(s,{status:'diterima'})}:null;})));"
 run=subprocess.run(['node','-e',script],cwd=ROOT,capture_output=True,text=True,check=True)
 output=json.loads(run.stdout)
 for args,actual in zip(cases,output):
  expected=native.describe(*args)
  if expected is None:assert actual is None
  else:
   expected['pairs']=[list(x) for x in expected['pairs']]
   expected['link']=native.native_link(expected,status='diterima')
   assert actual==expected


def test_proposal_adds_no_native_route_writer_server_stamp_or_cache():
 source=(ROOT/'app/web/filter_daftar_native.py').read_text()
 assert '@router' not in source and 'SessionLocal' not in source and 'hashlib' not in source
 script=(ROOT/'app/web/static/filter-daftar-native.js').read_text()
 assert 'localStorage' not in script and 'sessionStorage' not in script
 assert 'sha256' not in script and 'crypto.' not in script
 assert "headers:" not in script and 'fetch(' not in script
 assert "root.dataset.stamp=context+'|'+target" in script
 assert 'data-bm-stamp' in script and "root.removeAttribute('data-bm-stamp')" in script
 assert "shellSelector:'[data-filter-daftar-native]'" in script


def test_existing_work_placeholder_initializer_stays_inert_in_the_derived_frame():
    script=(ROOT/'app/web/static/filter-daftar-native.js').read_text()
    assert "'[data-halaman-bertahap][data-kind=\"pekerjaan\"]'" in script
    assert "root.dataset.ready='1'" in script
    assert "removeAttribute('data-halaman-bertahap')" not in script
    assert "root.dataset.siap='1'" in script
    assert "'/static/halaman-bertahap.js','/static/barang-masuk-pencarian.js'" in script
    native=(ROOT/'app/web/static/navigasi-daftar-bertahap.js').read_text()
    assert "if(schema&&!document.querySelector('[data-halaman-bertahap]'))" in native
