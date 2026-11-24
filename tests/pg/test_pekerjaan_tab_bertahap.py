"""Dua tab memakai kerangka, pembaca/izin serta transaksi tetap native."""
import json
from urllib.parse import urlsplit

import pytest
from bs4 import BeautifulSoup

from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik, _isi

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('role,warehouse', [('operator','g1'), ('operator','g2'), ('admin',None), ('superadmin',None)])
async def test_dua_tab_kerangka_tanpa_antrean_dan_isi_setara_native(pg,lengkap,monkeypatch,role,warehouse):
    from app.web import layar_pekerjaan as layar
    async with await _klien(pg,role=role,gudang_id=lengkap['gudang'].get(warehouse)) as c:
        before=await _sidik(pg)
        for query,tab in [('', 'tindakan'), ('tab=tindakan','tindakan'), ('tab=berjalan','berjalan'),
                          ('tab=asing','tindakan'), ('tab=tindakan&jenis=packing&cari=tidak-ada&pemasok=Nama+uji&gudang=g2','tindakan'),
                          ('tab=berjalan&informasi=1&kepemilikan=jasa&halaman=2','berjalan')]:
            path='/pekerjaan'+('?' +query if query else '')
            async def no_operational_read(*a,**kw):
                pytest.fail('Kerangka menunggu antrean/data operasional')
            with monkeypatch.context() as m:
                m.setattr(layar,'siapkan_daftar_pekerjaan',no_operational_read)
                shell=await c.get(path,headers={'X-Kerangka-Halaman':'1'})
            assert shell.status_code==200
            doc=BeautifulSoup(shell.text,'html.parser');root=doc.select_one('[data-halaman-bertahap]')
            assert root and len(root.select('thead th'))==5
            selected=root.select_one('nav[aria-label="Tab pekerjaan"] [aria-current="page"]')
            assert selected and ('Perlu tindakan' if tab=='tindakan' else 'Berjalan') in selected.get_text(), (query, [str(n) for n in root.select('nav')])
            assert root.select_one('input[name=cari]') is not None
            assert len(root.select('select[name=jenis]'))==1
            assert root.select_one('select[name=pemasok]').has_attr('disabled')
            assert all(x.has_attr('disabled') for x in root.select('[data-pk-cetak]'))
            assert not root.select('[data-post],[data-kirim],.benda[data-cari],.proses-aktif-list__row')
            native=await c.get(path,headers={'X-Pindah':'1'})
            data=await c.get('/api/halaman-bertahap/pekerjaan'+('?' +query if query else ''))
            assert native.status_code==data.status_code==200
            assert data.json()['stamp']==root['data-stamp']
            assert _isi(data.json()['html'])==_isi(native.text)
            assert data.headers['cache-control']=='private, no-store'
        assert await _sidik(pg)==before


async def test_katalog_dua_tab_filter_native_tanpa_wildcard_atau_aksi(pg,lengkap):
    from app.web import kerangka_langsung as registry
    async with await _klien(pg,role='admin') as c:
        before=await _sidik(pg)
        source='/pekerjaan?tab=berjalan&jenis=packing&cari=Nama+%26+uji&kepemilikan=jasa&gudang=g2&halaman=2'
        response=await c.get(source,headers={'X-Pindah':'0'})
        doc=BeautifulSoup(response.text,'html.parser')
        data=json.loads(doc.select_one('#padi-kerangka-langsung').string)
        assert registry.sah_rujukan(data)
        links={x['href'] for x in doc.select('nav[aria-label="Tab pekerjaan"] a') if urlsplit(x['href']).path=='/pekerjaan'}
        assert links.issubset(data['frames'])
        assert len(data['frames'])==len(registry.LITERAL)+2
        for address in set(data['frames'])-set(registry.LITERAL):
            assert 'halaman=' not in address and 'buka=' not in address and 'nilai=' not in address
            html=''.join(data['potongan'][i] for i in data['frames'][address])
            frame=BeautifulSoup(html,'html.parser')
            root=frame.select_one('[data-halaman-bertahap]')
            assert frame.select_one('.bingkai')['data-pindah-alamat']==address
            assert root['data-url']=='/api/halaman-bertahap/pekerjaan?'+urlsplit(address).query
            assert root.select_one('input[name=cari]')['value']=='Nama & uji'
            assert root.select_one('select[name=jenis] option[selected]')['value']=='packing'
            assert not root.select('[data-post],.benda[data-cari]')
        # Parameter non-kontrak tidak membuang enam kerangka dasar.
        extra=await c.get('/pekerjaan?token_fixture=tidak-dicatat')
        inert=json.loads(BeautifulSoup(extra.text,'html.parser').select_one('#padi-kerangka-langsung').string)
        assert set(inert['frames'])==set(registry.LITERAL)
        assert await _sidik(pg)==before


async def test_default_dan_tab_tidak_membuka_data_tanpa_sesi(pg,lengkap):
    async with await _klien(pg,role='admin') as c:
        c.cookies.clear()
        for path in ('/pekerjaan','/pekerjaan?tab=tindakan','/pekerjaan?tab=berjalan',
                     '/api/halaman-bertahap/pekerjaan','/api/halaman-bertahap/pekerjaan?tab=tindakan'):
            response=await c.get(path,headers={'X-Kerangka-Halaman':'1'},follow_redirects=False)
            assert response.status_code==303 and response.headers['location'].startswith('/masuk')
            assert 'POL-UJIP-' not in response.text
