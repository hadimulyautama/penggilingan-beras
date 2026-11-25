"""Native source parity for three owned compilers; no PG/browser/app runtime."""
import importlib.util
import json
from pathlib import Path
from urllib.parse import urlencode
import pytest
from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,Environment,FileSystemLoader,StrictUndefined

ROOT=Path(__file__).parents[1]


def module(name,path):
    spec=importlib.util.spec_from_file_location(name,ROOT/path)
    result=importlib.util.module_from_spec(spec);spec.loader.exec_module(result);return result


def native_breadcrumb(path,title,back):
    native=module('owned_native_breadcrumb_source','app/web/breadcrumb.py')
    env=Environment(loader=ChoiceLoader([FileSystemLoader(ROOT/'app/web/templates'),FileSystemLoader(ROOT/'hmu_tampilan/templates')]),autoescape=True,undefined=StrictUndefined)
    return env.get_template('_breadcrumb.html').render(rantai=native.susun(path,dict(kembali=back),title))


@pytest.mark.parametrize('compiler,global_name,paths',[
    ('pengaturan_master','PadiKerangkaPengaturanMasterData',['/pengaturan/spesifikasi-beras','/pengaturan/hasil-samping']),
    ('pengaturan_alat','PadiKerangkaPengaturanAlatData',['/pengaturan/alat']),
    ('jasa_detail','PadiKerangkaJasaDetailData',['ringkasan','penerimaan','proses','stok','pengambilan'])])
def test_generated_native_breadcrumb_has_exact_template_hierarchy_back_and_current(compiler,global_name,paths):
    build=module('owned_compile_'+compiler,'scripts/buat_kerangka_'+compiler+'.py').build
    payload,raw_meta=build();meta=json.loads(raw_meta)
    assert 'app/web/breadcrumb.py' in meta['inputs']
    assert 'hmu_tampilan/templates/_breadcrumb.html' in meta['inputs']
    data=json.loads(payload.decode().split('window.'+global_name+'=',1)[1].split(';\n',1)[0])
    for path in paths:
        item=data['variants'][path]
        source='/jasa/pelanggan/1' if compiler=='jasa_detail' else path
        back='/jasa?__PADI_BACK_QUERY__' if compiler=='jasa_detail' else '/pengaturan'
        assert item['breadcrumb']==native_breadcrumb(source,item['title'],back)
        doc=BeautifulSoup(item['breadcrumb'],'html.parser')
        nav=doc.select_one('nav.desktop-breadcrumb[aria-label="Jejak halaman"]')
        assert nav.select_one('ol.nav-rantai')
        assert nav.select_one('a')['href']=='/' and nav.select_one('a').get_text()=='Beranda'
        assert len(nav.select('li'))==3 and len(nav.select('[aria-current=page]'))==1
        assert nav.select_one('[aria-current=page]').get_text()==item['title']
        assert doc.select_one('a.desktop-back')['href']==back
        assert doc.select_one('a.desktop-back')['aria-label']=='Kembali ke '+('Pesanan Jasa' if compiler=='jasa_detail' else 'Pengaturan')


@pytest.mark.parametrize('label,query',[
    ('Fixture A',{}),('Nama <img src=x onerror=alert(1)> & "mitra"',{'cari':'A&B "x" *','status':'berjalan','halaman':'2'}),
    ('Nama\n  Dua',{'halaman':'3','cari':'é / gudang'})])
def test_jasa_dynamic_placeholder_binds_only_text_and_native_parent_query(label,query):
    build=module('owned_compile_jasa_dynamic','scripts/buat_kerangka_jasa_detail.py').build
    payload,_=build();data=json.loads(payload.decode().split('window.PadiKerangkaJasaDetailData=',1)[1].split(';\n',1)[0])
    doc=BeautifulSoup(data['variants']['ringkasan']['breadcrumb'],'html.parser')
    back='/jasa?'+urlencode(query);title=label+' · Pesanan Jasa'
    leaf=doc.select_one('[aria-current=page]');assert leaf.get_text()=='__PADI_JASA_LABEL__ · Pesanan Jasa'
    leaf.string=' '.join(title.split())
    for link in doc.select('a[href="/jasa?__PADI_BACK_QUERY__"]'):link['href']=back
    actual=BeautifulSoup(native_breadcrumb('/jasa/pelanggan/17',title,back),'html.parser')
    assert str(doc)==str(actual)
    assert not doc.select('img,script')
    assert doc.select_one('[aria-current=page]').get_text()==' '.join(title.split())


def test_native_jasa_title_contract_and_no_manual_crumb_reconstruction():
    source=(ROOT/'hmu_tampilan/templates/jasa_pelanggan_detail.html').read_text()
    assert '{% block judul %}{{ d.nama }} · Pesanan Jasa{% endblock %}' in source
    for name in ('jasa-detail','pengaturan-master','pengaturan-alat'):
        text=(ROOT/'app/web/static'/('kerangka-'+name+'-ui-runtime.js')).read_text()
        assert "crumb.replaceChildren(html.content)" in text
        assert "crumb.replaceChildren(a," not in text
        assert "className='bar__balik'" in text
        assert "setAttribute('aria-label','Kembali')" in text
    jasa=(ROOT/'app/web/static/kerangka-jasa-detail-ui-runtime.js').read_text()
    assert 'bar.textContent=title' in jasa and "bar.textContent='Pesanan Jasa'" not in jasa
    assert "leaves[0].textContent=nativeTitle(label)" in jasa
    assert "link.setAttribute('href',back)" in jasa


@pytest.mark.parametrize('label',['Fixture A','Nama <img src=x> & "mitra"'])
def test_direct_document_jasa_block_title_and_h1_match_actual_native_label(label):
    env=Environment(loader=ChoiceLoader([FileSystemLoader(ROOT/'app/web/templates'),FileSystemLoader(ROOT/'hmu_tampilan/templates')]),autoescape=True,undefined=StrictUndefined)
    template=env.get_template('jasa_detail_kerangka.html')
    title=''.join(template.blocks['judul'](template.new_context({'JASA_DETAIL_SHELL':{'nama':label}})))
    native=env.get_template('jasa_pelanggan_detail.html')
    expected=''.join(native.blocks['judul'](native.new_context({'d':{'nama':label}})))
    assert title==expected
    helper=module('native_jasa_title_spec','app/web/jasa_detail_kerangka.py')
    spec=helper.deskripsi('/jasa/pelanggan/17','tab=stok')
    spec.update(nama=label,stamp='fixture-stamp',filter_pesanan=False)
    html=''.join(template.blocks['isi'](template.new_context(dict(JASA_DETAIL_SHELL=spec,VERSI='fixture-cap'))))
    doc=BeautifulSoup(html,'html.parser')
    assert doc.select_one('.jasa-kontrol h1').get_text()==label
    assert not doc.select('img')
