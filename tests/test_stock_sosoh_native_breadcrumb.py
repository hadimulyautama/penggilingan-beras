"""Exact native hierarchy/Back contracts, pure template/navigation metadata."""
import ast
import json
from pathlib import Path
import sys
from types import ModuleType
from urllib.parse import urlsplit, parse_qs, urlencode, quote
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader, Environment, FileSystemLoader
import pytest
from app.web import breadcrumb
from app.web import stock_sosoh_chrome as chrome
ROOT=Path(__file__).resolve().parents[1]

@pytest.fixture
def native_resolvers(monkeypatch):
    """Execute exact pure resolver definitions without app/DB import graphs."""
    for file,name,functions in [('layar_pekerjaan.py','app.web.layar_pekerjaan',{'konteks_aman'}),('stok_navigasi.py','app.web.stok_navigasi',{'alamat','kembali_aman'})]:
        tree=ast.parse((ROOT/'app/web'/file).read_text())
        nodes=[n for n in tree.body if isinstance(n,ast.FunctionDef) and n.name in functions]
        assert {n.name for n in nodes}==functions
        module=ModuleType(name);module.__dict__.update(urlsplit=urlsplit,parse_qs=parse_qs,urlencode=urlencode)
        exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),str(ROOT/'app/web'/file),'exec'),module.__dict__)
        monkeypatch.setitem(sys.modules,name,module)

def public_data(script,prefix):
    return json.loads((ROOT/'app/web/static'/script).read_text().split(prefix,1)[1].split(';\n',1)[0])

def environment():
    return Environment(loader=ChoiceLoader([FileSystemLoader(ROOT/'app/web/templates'),FileSystemLoader(ROOT/'hmu_tampilan/templates')]),autoescape=True)

def fill_native(component,metadata):
    doc=BeautifulSoup(component['breadcrumb'],'html.parser');rows=doc.select('.nav-rantai>li')
    assert len(rows)==len(metadata['chain']['items'])
    for row,item in zip(rows,metadata['chain']['items']):
        node=row.select_one('a,[aria-current="page"]');assert bool(item['alamat'])==(node.name=='a')
        node.string=item['nama']
        if item['alamat']:node['href']=item['alamat']
    doc.select_one('.desktop-back')['href']=metadata['chain']['kembali']
    return doc

@pytest.mark.parametrize('back',['/pekerjaan?tab=berjalan&jenis=sosoh&halaman=3','/pekerjaan?tab=pengecualian','/barang-masuk?cari=fixture','/kabar?status=baru','//outside.invalid/pekerjaan'])
def test_sosoh_native_hierarchy_and_distinct_back_contexts(native_resolvers,back):
    address='/proses-aktif/sosoh/SOSOH-FIXTURE?kembali_kerja='+quote(back,safe='')
    meta=chrome.sosoh(address,'SOSOH-FIXTURE')
    from app.web.layar_pekerjaan import konteks_aman
    native_back=konteks_aman(back) or '/pekerjaan?tab=berjalan'
    expected=breadcrumb.susun(address,dict(kembali=native_back,breadcrumb_detail='SOSOH-FIXTURE'),'Penyosohan SOSOH-FIXTURE')
    assert meta['chain']==expected and meta['back']==native_back
    assert [n['nama'] for n in expected['items']]==['Beranda','Pekerjaan','SOSOH-FIXTURE']
    data=public_data('kerangka-sosoh-ui.js','window.PadiKerangkaSosohData=')
    for component in data['variants'].values():
        actual=fill_native(component,meta)
        native=BeautifulSoup(environment().get_template('_breadcrumb.html').render(rantai=expected),'html.parser')
        assert str(actual)==str(native)
        mobile=BeautifulSoup(component['back_markup'],'html.parser')
        assert mobile.select_one('a.bar__balik svg') and mobile.select_one('a.bar__balik')['aria-label']=='Kembali'

@pytest.mark.parametrize('variant,path,title,leaf',[
 ('pk-g1','/stok/pk/detail?gudang=g1&kode=LOT&jasa=0','Stok','Detail PK'),
 ('pk-g2-karung','/stok/pk/detail?gudang=g2&id=3&jasa=0','PK beli luar · PKB-FIXTURE','Detail PK'),
 ('product-packed','/stok-produk/detail?jenis=spek_fixture','Detail Beras fixture','Beras fixture'),
 ('product-auto','/stok-produk-jasa/detail?jenis=broken&pelanggan_id=5','Detail Broken','Broken'),
 ('warehouse-g1','/gudang/g1','Gudang 1',None)])
def test_stock_native_hierarchy_with_bound_variant_metadata(native_resolvers,variant,path,title,leaf):
    back='/stok?tab=produk&pemilik=jasa&cari=fixture'
    address=path+('&' if '?' in path else '?')+'kembali_stok='+quote(back,safe='') if not variant.startswith('warehouse') else path
    meta=chrome.stock(address,title=title,leaf=leaf)
    expected=breadcrumb.susun(address,dict(kembali=meta['back'],breadcrumb_detail=leaf or title),title)
    assert meta['chain']==expected
    data=public_data('kerangka-stock-detail-ui.js','window.PadiKerangkaStockDetailData=')
    actual=fill_native(data['variants'][variant],meta)
    native=BeautifulSoup(environment().get_template('_breadcrumb.html').render(rantai=expected),'html.parser')
    assert str(actual)==str(native)

def test_inputs_pin_native_chrome_and_no_runtime_manual_nav():
    for file in ['kerangka-sosoh-ui.meta.json','kerangka-stock-detail-ui.meta.json']:
        pins=json.loads((ROOT/'app/web/static'/file).read_text())['inputs']
        assert {'app/web/breadcrumb.py','hmu_tampilan/templates/_breadcrumb.html','hmu_tampilan/templates/base.html','scripts/stock_sosoh_native_chrome.py'}<=set(pins)
    for file in ['kerangka-sosoh-ui-runtime.js','kerangka-stock-detail-ui-runtime.js']:
        source=(ROOT/'app/web/static'/file).read_text()
        assert 'part.innerHTML=component.breadcrumb' in source and 'mobile.innerHTML=component.back_markup' in source
        assert "createTextNode(' › ')" not in source and "doc.createElement('strong')" not in source
