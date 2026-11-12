"""Akses pengiriman tetap ditolak, dengan pemulihan HTML dan respons API semula."""
import pytest
from bs4 import BeautifulSoup
from tests.pg.test_riwayat_giling import _klien

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('path',['/barang-keluar','/barang-keluar/999999'])
async def test_operator_gudang1_mendapat_penjelasan_dan_pemulihan(pg,path):
    async with await _klien(pg,peran='operator',gudang='Gudang 1',lihat='operator:g1') as c:
        r=await c.get(path,headers={'Accept':'text/html'})
        assert r.status_code==403
        assert r.headers['content-type'].startswith('text/html')
        s=BeautifulSoup(r.text,'html.parser')
        assert s.html.get('lang')=='id'
        assert s.title.get_text(strip=True)
        assert 'Pengiriman tersedia untuk Admin dan Operator Gudang 2' in s.main.get_text()
        assert s.select_one('main a[href="/pengaturan/peran"]').get_text(strip=True)=='Kerja di gudang'
        assert s.select_one('main a[href="/"]')
        assert not s.select('main .keluar-tabel,main [data-detail-keluar]')
        api=await c.get(path,headers={'Accept':'application/json'})
        assert api.status_code==403
        assert api.headers['content-type'].startswith('application/json')
        assert api.json()=={'detail':'Pengiriman tersedia untuk Admin dan Operator Gudang 2. Pilih gudang kerja melalui menu Kerja di gudang.'}
