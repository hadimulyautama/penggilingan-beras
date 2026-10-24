"""Permintaan operator: Sakura dan nota yang tidak perlu diketik dua kali."""
import pytest
from sqlalchemy import select, func
from app.models import Brand, PkPurchaseBatch, PkTumpukanToSilo
from app.services.seed import seed_master
from tests.pg.test_pk_karung import dunia, batch_baru
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir

pytestmark = pytest.mark.asyncio


async def test_sakura_tersedia_seed_idempoten_tanpa_mengubah_master_lama(pg):
    await seed_master()
    async with pg() as db:
        lama = (await db.scalars(select(Brand).where(Brand.nama == 'Imbiss'))).one()
        lama.aktif = False
        await db.commit()
        sakura = (await db.scalars(select(Brand).where(Brand.nama == 'Sakura'))).one()
        sid = sakura.id
        assert sakura.tipe == 'house' and sakura.aktif
    await seed_master()
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(Brand).where(Brand.nama == 'Sakura')) == 1
        assert (await db.get(Brand, sid)).tipe == 'house'
        assert not (await db.scalars(select(Brand).where(Brand.nama == 'Imbiss'))).one().aktif
    from tests.pg.test_riwayat_giling import _klien as klien_peran
    async with await klien_peran(pg, peran='superadmin') as c:
        r = await c.get('/api/actions/merk')
        assert r.status_code == 200, r.text
        assert any(x['label'] == 'Sakura' and x['value'] == 'Sakura' for x in r.json())


@pytest.mark.parametrize('n', [None, 128])
@pytest.mark.parametrize('nominal', [None, 80])
async def test_masuk_silo_tanpa_input_ulang_nominal(pg, dunia, n, nominal):
    from app.penggilingan.gudang2 import service as g2
    async with pg() as db:
        u,b,it = await batch_baru(db, dunia, n=n)
        b.ukuran_karung_kg = nominal
        await db.commit()
        uid,bid,iid = u.id,b.id,it.id
    async with await _klien(pg,uid,'nota-silo',mode='operator') as c:
        menu = (await c.get('/api/actions/menu')).json()
        aksi = next(x for x in menu if x['id'] == 'pindah_tumpukan_silo')
        assert 'ukuran_karung_kg' not in [x['name'] for x in aksi['fields']]
        params = {'tumpukan': iid, 'jumlah_karung': 20}
        isi = {'tumpukan':str(iid),'silo':'A','jumlah_karung':20,'kunci_kiriman':'nota-tanpa-input-ulang'}
        if n is None:
            params['jumlah_karung_partai'] = isi['jumlah_karung_partai'] = 128
        r = await c.get('/api/actions/pratinjau-pk-karung',params=params)
        assert r.status_code == 200, r.text
        assert '79,2 kg per karung × 20 karung = 1.584,4 kg' in r.json()['teks']
        assert ('Ukuran nominal pada surat jalan: 80,0 kg' in r.json()['teks']) == (nominal is not None)
        async with pg() as db:
            b = await db.get(PkPurchaseBatch,bid)
            assert b.jumlah_karung == n and b.ukuran_karung_kg == nominal
            assert await db.scalar(select(func.count()).select_from(PkTumpukanToSilo)) == 0
        for _ in range(2):
            r = await c.post('/api/actions/pindah-tumpukan-silo',json=isi,headers={'X-CSRF-Token':cap_formulir(c)})
            assert r.status_code == 200, r.text
        async with pg() as db:
            b = await db.get(PkPurchaseBatch,bid)
            assert b.jumlah_karung == 128 and b.ukuran_karung_kg == nominal
            assert b.berat_total_kg == 10140
            assert await db.scalar(select(func.count()).select_from(PkTumpukanToSilo)) == 1
            m = (await db.scalars(select(PkTumpukanToSilo))).one()
            assert m.jumlah_karung == 20 and m.berat_timbang_kg is None
            assert float(m.berat_kg) == pytest.approx(10140*20/128)
            assert await g2._sisa_tumpukan_intake(db,iid) == pytest.approx(10140*108/128)
            silo = await g2.get_g2_silo(db,'A')
            assert await g2.hitung_stok_silo(db,silo.id) == pytest.approx(10140*20/128)
        import os,json
        from pathlib import Path
        if os.environ.get('UJI_KARUNG_SEED'):
            Path('/tmp/karung-session.json').write_text(json.dumps({'intake':iid,'cookies':{x.name:x.value for x in c.cookies.jar}}))
