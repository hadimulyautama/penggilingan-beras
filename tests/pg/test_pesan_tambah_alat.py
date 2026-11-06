"""Pesan tindakan diuji melalui POST dan redirect asli pada PostgreSQL uji."""
import pytest
from sqlalchemy import select
from app.models import Warehouse, Dryer, Silo
from hmu_identitas import peran as P
from tests.pg.test_pengaturan_usulan import master, klien, kirim
from tests.pg.test_pengaturan_terpadu import fisik

pytestmark = pytest.mark.asyncio

@pytest.mark.parametrize('jenis', ['dryer', 'silo'])
@pytest.mark.parametrize('jalur', ['lama', 'gudang', 'baru'])
async def test_pesan_tambah_sesuai_tindakan(pg, master, jenis, jalur):
    c, _, _ = await klien(pg, P.SUPERADMIN)
    before = await fisik(pg)
    data = {'nama': 'Uji pesan sukses'}
    if jenis == 'dryer':
        data['kapasitas_kg'] = '20000'
    else:
        data['gudang'] = 'g1'
        data['jenis_isi'] = 'gabah'
    if jalur != 'lama':
        async with pg() as db:
            data['warehouse_id'] = await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi == 'g1'))
    if jalur == 'baru':
        data['kembali_pengaturan'] = '/pengaturan/mesin' if jenis == 'dryer' else '/pengaturan/silo'
    async with c:
        r = await kirim(c, '/pengaturan/alat/' + jenis, data)
        assert r.status_code == 303
        assert 'pesan=' + jenis + '-ditambah' in r.headers['location']
        for _ in range(3):
            r = await c.get(r.headers['location'])
            if r.status_code == 200:
                break
            assert r.status_code == 303
        assert r.status_code == 200
        assert ('Dryer' if jenis == 'dryer' else 'Silo') + ' baru ditambahkan.' in r.text
        assert 'Alat diperbarui.' not in r.text
    async with pg() as db:
        model = Dryer if jenis == 'dryer' else Silo
        name = model.nama if jenis == 'dryer' else model.nama_silo
        assert await db.scalar(select(model.id).where(name == ('Uji pesan sukses' if jenis == 'dryer' else 'Silo Uji pesan sukses')))
    assert await fisik(pg) == before
