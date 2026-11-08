"""Aturan final: pengemasan awal hasil samping otomatis, seluruh pintu manual ditolak."""
import pytest
from sqlalchemy import select,func
from app.models import User,FinishedGoodsStock,ActivityLog
from app.penggilingan.inventory import finished_goods as fg
from tests.pg.test_grup_packing_jasa import empat_jenis,_klien
from tests.pg.formulir import cap_formulir

JENIS=[('broken','putih',50),('menir','putih',50),('reject','bekas',50),('bekatul','bekas',40)]

@pytest.mark.parametrize('jenis,bahan,ukuran',JENIS)
@pytest.mark.parametrize('lama',[False,True])
async def test_endpoint_baru_dan_payload_lama_menolak_tanpa_menulis(pg,empat_jenis,jenis,bahan,ukuran,lama):
    async with await _klien(pg,peran='superadmin') as c:
        payload=dict(jumlah_karung=1)
        payload.update(dict(kode_pol=empat_jenis['kode'],produk=f'{jenis}|{bahan}|{ukuran}') if lama else dict(sumber=f"{empat_jenis['kode']}|{jenis}",kemasan=f'{bahan}|{ukuran}'))
        r=await c.post('/api/actions/catat-packing',json=payload,headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==400 and 'otomatis' in r.text.lower(),r.text
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock))==0

@pytest.mark.parametrize('jenis,bahan,ukuran',JENIS)
async def test_layanan_langsung_menolak_packing_awal_hasil_samping(pg,empat_jenis,pemakai,jenis,bahan,ukuran):
    async with pg() as db:
        with pytest.raises(fg.InventoryError,match='otomatis'):
            await fg.catat_packing(db,user=await db.get(User,pemakai.id),kode_pol=empat_jenis['kode'],kategori=jenis,material_kode=bahan,ukuran=ukuran,jumlah_karung=1)
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock))==0

async def test_daftar_sumber_dan_kemasan_packing_hanya_beras(pg,empat_jenis):
    async with await _klien(pg,peran='superadmin') as c:
        for params in ({},{'hanya_beras':'false'},{'hanya_beras':'true'}):
            r=await c.get('/api/actions/beras-belum-dikemas',params=params)
            assert r.status_code==200 and [x['value'] for x in r.json()]==[empat_jenis['kode']+'|medium']
        for jenis,_,_ in JENIS:
            assert (await c.get('/api/actions/kemasan-untuk',params={'induk':empat_jenis['kode']+'|'+jenis})).json()==[]

async def test_katalog_borang_lama_hanya_beras(pg,empat_jenis):
    async with await _klien(pg,peran='superadmin') as c:
        rows=(await c.get('/api/actions/produk-kemasan')).json()
        assert rows and all(r['value'].split('|')[0] in {'beras_putih','beras_b'} for r in rows)
        for jenis,_,_ in JENIS:
            r=await c.get('/api/actions/rincian-packing-beras',params={'sumber':empat_jenis['kode']+'|'+jenis})
            assert r.status_code==400 and 'otomatis' in r.text,r.text
