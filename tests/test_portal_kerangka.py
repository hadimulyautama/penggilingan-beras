"""Pure portal structure contracts; no DB/user/token or listener is created."""
import ast,hashlib,importlib.util,json
from pathlib import Path
import pytest
from bs4 import BeautifulSoup
ROOT=Path(__file__).resolve().parents[1]
def load(name,path):
    s=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);return m
module=load('portal_structure_spec',ROOT/'app/web/portal/kerangka.py')
compiler=load('portal_structure_compiler',ROOT/'scripts/buat_kerangka_portal.py')

@pytest.mark.parametrize('path',['/pelanggan','/pelanggan/','/pelanggan/ringkasan','/pelanggan/barang-masuk','/pelanggan/barang-saya','/pelanggan/jasa-saya','/pelanggan/riwayat-proses','/pelanggan/barang-keluar','/pelanggan/laporan'])
def test_only_native_menu_shapes_preserve_actual_address(path):
    v=module.deskripsi(path)
    assert v and v['alamat']==path
    assert set(v)=={'page','alamat','query','title','intro','sections','filters'}
    assert not {'rows','reader','saldo','jasa_ids','count'}&set(v)

@pytest.mark.parametrize('path,query',[('/pelanggan/proses-aktif/sosoh/POL-1',''),('/pelanggan/stok/pk/detail','id=7'),('/pelanggan/jasa/1/nota',''),('/pelanggan/ringkasan','tab=stok'),('/pelanggan/laporan','q=x&q=y'),('/pelanggan/laporan','buka=koreksi'),('/pelanggan/barang-masuk','pelanggan_id=2'),('/pelanggan/barang-masuk','cari=%XX'),('/pelanggan/laporan','q=%E0%A4'),('/pelanggan/laporan','halaman=0'),('/pelanggan/barang-keluar','sejak=2026-02-30'),('/pelanggan/barang-keluar','sebelum=0'),('/pelanggan/barang-keluar','status=x&aksi=simpan'),('/pelanggan/masuk','')])
def test_resource_alias_action_malformed_queries_decline(path,query):
    assert module.deskripsi(path,query) is None

@pytest.mark.parametrize('path,query',[('/pelanggan/barang-masuk','jenis=pk&cari=LOT-UJI&halaman=2'),('/pelanggan/laporan','q=UJI&jenis=proses&halaman=2'),('/pelanggan/barang-keluar','status=selesai&sejak=2026-01-01&sebelum=12')])
def test_existing_read_filters_are_correlation_not_authority(path,query):
    value=module.deskripsi(path,query)
    assert value['alamat']==path+'?'+query


def test_generated_program_is_exact_deterministic_data_free_native_structure():
    first,meta=compiler.build();second,meta2=compiler.build()
    assert (first,meta)==(second,meta2)
    assert first==(ROOT/'app/web/static/kerangka-portal-ui.js').read_bytes()
    saved=json.loads(meta);assert saved==json.loads((ROOT/'app/web/static/kerangka-portal-ui.meta.json').read_text())
    assert saved['aset_sha256']==hashlib.sha256(first).hexdigest()
    assert set(saved['schemas'])==set(module.PAGES)
    data=json.loads(first.decode().split('window.PadiKerangkaPortalData=',1)[1].split(';\n',1)[0])
    for path,html in data['variants'].items():
        doc=BeautifulSoup(html,'html.parser');root=doc.select_one('[data-portal-native-frame]')
        assert root and root['data-portal-page']==path
        # The factory returns root.outerHTML: this override must live inside
        # that root, where author .btn display:flex cannot defeat hidden.
        assert any('[data-portal-native-frame] [hidden]{display:none!important}' in (style.string or '') for style in root.select('style'))
        assert doc.select_one('h1').get_text()==module.PAGES[path]['title']
        assert len(doc.select('[data-portal-read-retry][hidden]'))==1
        assert not doc.select('script,iframe,form[method=post],[name=_csrf],[data-post],[data-kirim]')
        assert not doc.select('.halaman-memuat,.pelanggan-batch,.pelanggan-proses-ringkas')
        for table in doc.select('table'):
            assert len(table.select('tbody tr'))==1
            assert int(table.select_one('tbody td')['colspan'])==len(table.select('thead th'))
    assert data['schemas']['/barang-keluar']['tables']['Pengambilan berjalan']==['Pelanggan / pengambilan','Isi muatan','Rencana / dimuat','Status']
    assert data['schemas']['/barang-masuk']['columns']==['Nama / tiket','Status','Barang','Armada','Bobot diterima','Penerimaan','']


def test_early_call_follows_existing_verified_scope_and_does_not_change_dispatch():
    tree=ast.parse((ROOT/'app/web/portal/routes.py').read_text())
    read=next(n for n in tree.body if isinstance(n,ast.AsyncFunctionDef) and n.name=='read')
    source=ast.get_source_segment((ROOT/'app/web/portal/routes.py').read_text(),read)
    assert source.index('scope=await load_scope(reader)')<source.index('req=native_request(request,path,scope)')<source.index('awal=await dokumen_kerangka(request,req)')<source.index("if path=='/serah-terima'")
    helper=(ROOT/'app/web/portal/kerangka.py').read_text()
    assert "original.headers.get('X-Portal-Navigasi')=='1'" in helper
    assert not any(x in helper for x in ('SessionLocal','await db.','db.commit','issue(','.active='))
