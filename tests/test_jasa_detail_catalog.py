"""Private catalog binding from primitive synthetic native context; no DB/ORM."""
import ast
import hashlib
import html
import json
from pathlib import Path
from bs4 import BeautifulSoup
import pytest
from app.web.jasa_detail_catalog import susun_data,private_host

ROOT=Path(__file__).parents[1]
SOURCE='/jasa?status=&cari=&halaman=1'
TARGET='/jasa/pelanggan/17?status=&cari=&halaman=1'
BOUND=dict(cap='fixture-cap',konteks='fixture-context',sesi='fixture-session',sumber='a'*64)


def body(source,inside,*,cap='fixture-cap',context='fixture-context',token='fixture-session'):
    return (f'<html data-versi="{cap}"><body><div class="bingkai" data-pindah-konteks="{context}" data-pindah-alamat="{html.escape(source,quote=True)}">'
        '<main id="isi-halaman"><!-- isi-halaman:mulai -->'+inside+'<!-- isi-halaman:akhir --></main>'
        f'<div id="formulir-sesi" data-token="{token}"></div></div></body></html>').encode()


def list_body(name='Fixture A',target=TARGET,hidden=''):
    return body(SOURCE,f'<div class="jasa-daftar" {hidden}><a class="jasa-pelanggan" href="{html.escape(target,quote=True)}"><div class="baris"><h2>{html.escape(name)}</h2></div><p>99999 pesanan bukan sumber metadata</p></a></div>')


def row(count=21):return dict(id=17,nama='Fixture A',pesanan_jumlah=count)


def test_list_catalog_uses_already_read_fields_not_text_counts_or_guess_names():
    data=susun_data(SOURCE,list_body(),{'kartu':[row(20)]},**BOUND)
    assert data['entries']==[dict(id=17,label='Fixture A',filter=False,targets=[TARGET])]
    assert data['source_address']==SOURCE
    assert data['sumber_sha256']==hashlib.sha256(SOURCE.encode()).hexdigest()
    assert susun_data(SOURCE,list_body(),{'kartu':[row(21)]},**BOUND)['entries'][0]['filter'] is True


@pytest.mark.parametrize('record',[
    dict(id=17,nama='Fixture A',pesanan=[]),dict(id=17,nama='Fixture A',pesanan_jumlah=None),
    dict(id=17,nama='Fixture A',pesanan_jumlah=True),dict(id=17,nama='',pesanan_jumlah=2),
    dict(id=18,nama='Fixture A',pesanan_jumlah=2),dict(id=17,nama='Other name',pesanan_jumlah=2),
])
def test_unknown_mismatched_record_metadata_declines_instead_of_parsing_html(record):
    assert susun_data(SOURCE,list_body(),{'kartu':[record]},**BOUND) is None


@pytest.mark.parametrize('hidden',['hidden','inert','aria-hidden="true"'])
def test_non_visible_native_link_never_issues_catalog(hidden):
    assert susun_data(SOURCE,list_body(hidden=hidden),{'kartu':[row()]},**BOUND) is None


def test_native_detail_issues_only_current_pid_five_exact_tab_hrefs():
    source='/jasa/pelanggan/17?tab=stok'
    tabs=['ringkasan','penerimaan','proses','stok','pengambilan']
    links=''.join(f'<a href="?tab={tab}&amp;status=&amp;cari=&amp;halaman=">{tab}</a>' for tab in tabs)
    markup=body(source,'<section class="jasa-kontrol"><h1>Fixture A</h1></section><nav class="jasa-detail-tab">'+links+'</nav>')
    data=susun_data(source,markup,{'d':row(),'tab':'stok'},**BOUND)
    assert data['mode']=='detail' and len(data['entries'])==1 and len(data['entries'][0]['targets'])==5
    assert susun_data(source,markup,{'d':row(),'tab':'proses'},**BOUND) is None
    assert susun_data(source,markup.replace(b'?tab=stok',b'?tab=stock-unknown'),{'d':row(),'tab':'stok'},**BOUND) is None


@pytest.mark.parametrize('field,value',[('cap','old'),('konteks','other'),('sesi','old-session'),('sumber','unknown')])
def test_catalog_metadata_and_actual_document_must_match(field,value):
    args={**BOUND,field:value}
    assert susun_data(SOURCE,list_body(),{'kartu':[row()]},**args) is None


def test_bound25_no_db_lookup_and_private_json_escape_are_explicit():
    assert susun_data(SOURCE,list_body(),{'kartu':[row()]*26},**BOUND) is None
    name='Fixture </script><img src=x onerror=bad>&'
    data=susun_data(SOURCE,list_body(name),{'kartu':[{**row(), 'nama':name}]},**BOUND)
    raw=private_host(data,'fixture-cap')
    doc=BeautifulSoup(raw,'html.parser')
    assert len(doc.select('script'))==2 and not doc.select('img')
    parsed=json.loads(doc.select_one('#padi-jasa-detail-catalog').string)
    assert parsed['entries'][0]['label']==name
    tree=ast.parse((ROOT/'app/web/jasa_detail_catalog.py').read_text())
    assert not any(isinstance(n,ast.Attribute) and n.attr in {'execute','scalars','scalar','commit','flush','add','delete'} for n in ast.walk(tree))
