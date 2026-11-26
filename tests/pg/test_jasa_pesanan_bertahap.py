"""Adapter berscope baca; tab/editor/portal dan hak native tidak diperluas."""
import pytest
from bs4 import BeautifulSoup
from tests.pg.test_jasa_ringkasan_banyak import banyak
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_halaman_bertahap import _sidik
pytestmark=pytest.mark.asyncio

async def test_scoped_native_output_and_no_writes(pg,banyak):
    async with await _klien(pg,role='admin') as c:
        before=await _sidik(pg)
        for q,enabled in [('',True),('?pesanan_halaman=2',True),('?pesanan_status=dibatalkan',True),('?tab=stok',False),('?pesanan_id=1',False),('?buka=tutup_jasa&nilai=1',False)]:
            response=await c.get('/jasa/pelanggan/'+str(banyak['pelanggan_id'])+q)
            assert response.status_code==200
            soup=BeautifulSoup(response.text,'html.parser')
            assert bool(soup.select('script[src*="jasa-pesanan-bertahap.js"]'))==enabled
            if enabled:assert soup.select_one('#pesanan-pelanggan .jasa-pesanan-filter')
        assert await _sidik(pg)==before
    async with await _klien(pg,role='operator') as c:
        response=await c.get('/jasa/pelanggan/'+str(banyak['pelanggan_id'])+'?pesanan_halaman=2');assert response.status_code==403
        assert 'jasa-pesanan-bertahap.js' not in response.text

@pytest.mark.parametrize('raw,valid',[
 ('/jasa/pelanggan/1',True),('/jasa/pelanggan/1?tab=ringkasan&pesanan_halaman=2#pesanan-pelanggan',True),
 ('/jasa/pelanggan/1?status=berjalan&cari=asal&halaman=7&pesanan_cari=ORD&pesanan_status=selesai',True),
 ('/jasa/pelanggan/0',False),('/jasa/pelanggan/2147483648',False),
 ('/jasa/pelanggan/1?tab=stok',False),('/jasa/pelanggan/1?pesanan_id=5',False),
 ('/jasa/pelanggan/1?pesanan_halaman=1&pesanan_halaman=2',False),
 ('/jasa/pelanggan/1?buka=tutup_jasa&nilai=1',False),('/jasa/pelanggan/1#pesanan-5',False),
 ('//other.invalid/jasa/pelanggan/1',False),('/jasa/1/nota',False)])
async def test_only_order_read_location(raw,valid):
    from app.web.jasa_pesanan_bertahap import alamat
    assert alamat(raw) is valid
