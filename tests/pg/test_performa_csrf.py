import pytest
from bs4 import BeautifulSoup
from tests.pg.test_portal_pelanggan import portal,qc,client
pytestmark=pytest.mark.asyncio
async def test_meta_sesi_dan_form_keluar_selaras(pg,portal):
    async with client(portal.accounts[0]) as c:
        for path in ['/pelanggan/','/pelanggan/barang-masuk','/pelanggan/riwayat-giling/1','/pelanggan/laporan']:
            r=await c.get(path);assert r.status_code==200
            s=BeautifulSoup(r.text,'html.parser')
            m=s.select_one('head meta[name=formulir-sesi]')
            f=s.select_one('form[action="/pelanggan/keluar"] input[name=_csrf]')
            assert m and f
            assert m['content']==f['value'],(path,len(m['content']),len(f['value']))
