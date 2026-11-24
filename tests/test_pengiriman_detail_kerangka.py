"""Pure active-shipping contracts. Native authority/runtime parity is not mocked PASS."""
import asyncio
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
from types import ModuleType,SimpleNamespace

from bs4 import BeautifulSoup
from jinja2 import ChoiceLoader,DictLoader,Environment,FileSystemLoader,StrictUndefined
import pytest
from starlette.requests import Request

from app.web import pengiriman_detail_kerangka as page
from app.web import pengiriman_detail_catalog as catalog
ROOT=Path(__file__).parents[1]


def meta(**changes):
    # Metadata protocol fixture, not an ORM/stock DTO or proof of authorization.
    return dict(id=17,kode='SYNTHETIC-OUT',status='perintah',keadaan='Menunggu dimuat',jasa=False,
        cepat=False,bersama=False,tiket=False,boleh_perintah=False,boleh_muat=True,
        actions=[dict(label='Catat muatan',bagian='ringkasan')],**changes)


def env():
    return Environment(loader=ChoiceLoader([DictLoader({'base.html':'{% block isi %}{% endblock %}'}),
        FileSystemLoader([ROOT/'app/web/templates',ROOT/'hmu_tampilan/templates'])]),autoescape=True,undefined=StrictUndefined)


@pytest.mark.parametrize('tab',dict(page.TABS))
@pytest.mark.parametrize('command',[False,True])
def test_native_read_structure_all_four_tabs_without_values_or_enabled_actions(tab,command):
    spec=page.deskripsi('/barang-keluar/17','tab_detail='+tab+'&q=synthetic&sejak=2026-11-24')
    data=meta();data['boleh_perintah']=command
    spec.update(meta=data,stamp='context|'+spec['alamat'])
    html=env().get_template('pengiriman_detail_kerangka.html').render(PD=spec,VERSI='fixture')
    doc=BeautifulSoup(html,'html.parser');root=doc.select_one('[data-pengiriman-detail-kerangka]')
    assert root and root['data-url']==spec['alamat']
    assert len(root.select('[role=tabpanel]'))==4 and len(root.select('[role=tab]'))==4
    assert [p['id'] for p in root.select('[role=tabpanel]:not([hidden])')]==['panel-'+tab]
    assert not root.select('form,input,select,textarea,[data-post],[data-kirim]')
    assert all(b.has_attr('disabled') for b in root.select('[data-pd-actions] button'))
    assert [th.text for th in root.select('table th')]==['Barang','Perintah','Dimuat aktual','Sisa perintah']
    assert len(root.select('table tbody tr'))==1 and root.select_one('table td')['colspan']=='4'
    assert len(root.select('.pd-unread-fields dt'))==4 and {x.text for x in root.select('.pd-unread-fields dd')}=={'Belum dibaca'}
    assert '>0<' not in html and '0 kg' not in html and 'SYNTHETIC-OUT' in html
    assert bool(root.select_one('a[href="/retur"]')) is command


@pytest.mark.parametrize('path,query',[
    ('/barang-keluar/17',''),('/barang-keluar/17','q=a%20b&status=perintah&sejak=2026-11-24'),
    ('/barang-keluar/17','tab_detail=barang&sebelum=30'),
    ('/barang-keluar/17','kembali_kerja=%2Fpekerjaan%3Ftab%3Dberjalan')])
def test_bounded_read_address_preserves_raw_query_and_native_filter_context(path,query):
    spec=page.deskripsi(path,query);assert spec and spec['alamat']==path+('?' +query if query else '')


@pytest.mark.parametrize('path,query',[
    ('/barang-keluar',''),('/barang-keluar/0',''),('/barang-keluar/017',''),('/barang-keluar/2147483648',''),
    ('/barang-keluar/17/muatan',''),('/muatan','perintah=17'),('/selesai-muat','perintah=17'),
    ('/barang-keluar/17','buka='),('/barang-keluar/17','nilai=17'),('/barang-keluar/17','tiket=1'),
    ('/barang-keluar/17','rincian_perintah=1'),('/barang-keluar/17','tab_detail=unknown'),
    ('/barang-keluar/17','tab_detail=barang&tab_detail=tiket'),('/barang-keluar/17','sejak=20261124'),
    ('/barang-keluar/17','sejak=2026-02-30'),('/barang-keluar/17','q=%FF'),
    ('/barang-keluar/17','kembali=https://other.invalid'),('/barang-keluar/17','company_id=2')])
def test_editor_history_unknown_and_cross_scope_queries_decline_to_native(path,query):
    assert page.deskripsi(path,query) is None


def test_only_active_metadata_and_strict_boolean_flags_are_accepted():
    data=meta();assert page.valid_meta(data)
    for key,value in [('status','selesai'),('status','batal'),('id',True),('boleh_muat',1),('actions',[{'label':'X','bagian':'write'}])]:
        assert not page.valid_meta({**data,key:value})
    assert not page.valid_meta({**data,'weight':50})


def test_x1_and_unsupported_queries_decline_before_any_record_access():
    for headers,query in [([(b'x-pindah',b'1'),(b'x-kerangka-halaman',b'1')],''),([], 'buka=muat_barang')]:
        req=Request(dict(type='http',method='GET',path='/barang-keluar/17',query_string=query.encode(),headers=headers,state={}))
        assert asyncio.run(page.kerangka(req,None,object(),object(),boleh_perintah=False,boleh_muat=False)) is None


@pytest.mark.parametrize('status',['selesai','batal'])
def test_historical_native_row_is_declined_without_building_a_shell(status,monkeypatch):
    actor=SimpleNamespace(user=object(),harus_ganti_sandi=False)
    req=Request(dict(type='http',method='GET',path='/barang-keluar/17',query_string=b'',
        headers=[(b'x-kerangka-halaman',b'1')],state={'akun':actor}))
    monkeypatch.setattr(page,'row_metadata',lambda *a,**k:pytest.fail('Historical row must stay native'))
    row=SimpleNamespace(id=17,status=status)
    assert asyncio.run(page.kerangka(req,actor,row,object(),boleh_perintah=True,boleh_muat=False)) is None


def test_positive_native_read_predicate_is_rechecked_before_any_metadata(monkeypatch):
    actor=SimpleNamespace(user=object(),harus_ganti_sandi=False)
    req=Request(dict(type='http',method='GET',path='/barang-keluar/17',query_string=b'',
        headers=[(b'x-kerangka-halaman',b'1')],state={'akun':actor}))
    portal=ModuleType('app.web.portal.scope');portal.is_customer_read=lambda request:False
    native=ModuleType('app.web.pengiriman_bertahap');calls=[]
    async def deny(user):calls.append(user is actor.user);return False
    native.boleh_baca=deny
    monkeypatch.setitem(sys.modules,'app.web.portal.scope',portal);monkeypatch.setitem(sys.modules,'app.web.pengiriman_bertahap',native)
    monkeypatch.setattr(page,'row_metadata',lambda *a,**k:pytest.fail('Denied actor must not reach metadata'))
    assert asyncio.run(page.kerangka(req,actor,SimpleNamespace(id=17,status='perintah'),object(),boleh_perintah=False,boleh_muat=False)) is None
    assert calls==[True]


def native_projection():
    # Source DTO protocol sentinel exposes no database/query interface.
    record=SimpleNamespace(id=17,kode='SYNTHETIC-OUT',status='perintah',timbangan_transaksi_id=None)
    return dict(rec=record,keadaan='Menunggu dimuat',jasa=False,cepat=False,kiriman_bersama=[],
                tombol=[('muat_barang','17','Catat muatan',True)])


def body(source,content):
    return ('<html data-versi="cap"><body><div class="bingkai" data-pindah-konteks="ctx" data-pindah-alamat="'+source+'">'
            '<div id="formulir-sesi" data-token="session"></div><main id="isi-halaman">'+content+'</main></div></body></html>').encode()


def bind(source,content,**context):
    return catalog.susun_data(source,body(source,content),dict(kartu=[native_projection()],BOLEH_PERINTAH=False,BOLEH_MUAT=True,**context),
        origin='https://fixture.invalid',cap='cap',konteks='ctx',sesi='session',sumber='a'*64)


def test_catalog_binds_only_native_row_dto_and_exact_authorized_visible_list_href():
    markup='<section class="keluar-daftar"><table><tr class="keluar-baris" data-detail-keluar="/barang-keluar/17"><td><a href="/barang-keluar/17"><strong>Native customer</strong><small>SYNTHETIC-OUT · 1 macam</small></a></td></tr></table></section>'
    result=bind('/barang-keluar',markup)
    assert result and result['entries'][0]['targets']==['/barang-keluar/17']
    assert result['entries'][0]['meta']['actions']==[dict(label='Catat muatan',bagian='ringkasan')]
    assert not any(k in json.dumps(result) for k in ('berat_kg','dasar','Native customer','jumlah_karung'))
    assert result['sumber_sha256']==hashlib.sha256(b'/barang-keluar').hexdigest()
    assert bind('/barang-keluar',markup.replace('SYNTHETIC-OUT ·','wrong ·')) is None
    assert bind('/barang-keluar',markup.replace('class="keluar-baris"','class="keluar-baris" hidden')) is None
    assert bind('/barang-keluar',markup.replace('href="/barang-keluar/17"','href="/barang-keluar/18"')) is None
    assert bind('/barang-keluar?buka=perintah_keluar',markup) is None


def test_native_absolute_detail_tab_links_are_bound_without_fabricating_a_route():
    source='/barang-keluar/17?q=synthetic'
    markup='<article data-detail-tab><h1 id="judul-perintah">SYNTHETIC-OUT</h1><nav class="detail-kirim-tabs">'+''.join(
        '<a href="https://fixture.invalid/barang-keluar/17?q=synthetic&amp;tab_detail='+key+'#panel-'+key+'">'+label+'</a>' for key,label in page.TABS)+'</nav></article>'
    result=bind(source,markup)
    assert result and len(result['entries'][0]['targets'])==4
    assert all('#' not in target for target in result['entries'][0]['targets'])
    assert bind(source,markup.replace('https://fixture.invalid','https://other.invalid')) is None


def test_caller_adopts_after_native_positive_guard_and_actual_row_and_before_enrichment():
    source=(ROOT/'app/web/layar_keluar.py').read_text()
    assert source.index('not await boleh_baca') < source.index('dokumen_baris = await svc.daftar(db, transaksi_id=transaksi_id') < source.index('shell=await detail_kerangka') < source.index('await baca(db,rec,scope=')
    import ast
    tree=ast.parse(source)
    parent={child:node for node in ast.walk(tree) for child in ast.iter_child_nodes(node)}
    shell=next(n for n in ast.walk(tree) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name) and n.func.id=='detail_kerangka')
    current=parent[shell]
    while current in parent:
        assert not isinstance(current,ast.AsyncWith)
        current=parent[current]
    assert 'baris = (dokumen_baris if dokumen_baris is not None else' in source
    assert source.index('if not dokumen_baris:') < source.index('shell=await detail_kerangka')
    assert 'return pasang_detail_catalog(request,akun,response)' in source
    # No direct-row replacement or ledger read hidden in family helpers.
    own=(ROOT/'app/web/pengiriman_detail_kerangka.py').read_text()+(ROOT/'app/web/pengiriman_detail_catalog.py').read_text()
    assert 'SessionLocal' not in own and 'db.' not in own and 'commit(' not in own


def test_public_compiler_is_fresh_and_contains_no_business_identity_or_numbers():
    spec=importlib.util.spec_from_file_location('shipping_compile',ROOT/'scripts/buat_kerangka_pengiriman_detail.py')
    compiler=importlib.util.module_from_spec(spec);spec.loader.exec_module(compiler)
    payload,manifest=compiler.build()
    assert payload==(ROOT/'app/web/static/kerangka-pengiriman-detail-ui.js').read_bytes()
    assert manifest==(ROOT/'app/web/static/kerangka-pengiriman-detail-ui.meta.json').read_bytes()
    assert len(payload)<524288 and b'/barang-keluar/17' not in payload and b'SYNTHETIC' not in payload
    assert b'__PADI_CODE__' in payload and b'__PADI_NATIVE_READ_ADDRESS__' not in payload
