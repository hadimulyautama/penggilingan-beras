"""Negosiasi kerangka Jasa terpisah dari legacy; memakai dunia sintetis native."""
import hashlib,json
import pytest
from sqlalchemy import text
from hmu_identitas import peran as P
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien

pytestmark=pytest.mark.asyncio

async def _sidik(pg):
    async with pg() as db:
        names=(await db.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))).all()
        result={}
        for name in names:
            rows=(await db.scalars(text('SELECT row_to_json(x)::text FROM "'+name+'" x ORDER BY row_to_json(x)::text'))).all()
            result[name]=hashlib.sha256(json.dumps(rows).encode()).hexdigest()
        return result

@pytest.mark.parametrize('role,gudang,code',[(P.ADMIN,None,200),(P.SUPERADMIN,None,200),(P.OPERATOR,'g1',403),(P.OPERATOR,'g2',403)])
async def test_renderer_eksplisit_dan_API_mempertahankan_legacy(pg,stok_lengkap,role,gudang,code):
    async with await _klien(pg,role=role,gudang_id=stok_lengkap['gudang'].get(gudang)) as c:
        before=await _sidik(pg)
        full=await c.get('/jasa?status=berjalan')
        background=await c.get('/jasa?status=berjalan',headers={'X-Pindah':'1'})
        shell=await c.get('/jasa?status=berjalan',headers={'X-Pindah':'1','X-Kerangka-Halaman':'1'})
        data=await c.get('/api/halaman-bertahap/jasa?status=berjalan')
        assert full.status_code==background.status_code==shell.status_code==data.status_code==code
        if code==200:
            assert full.text==background.text==data.json()['html']
            assert full.text.count('class="kartu jasa-pelanggan"')==2
            assert 'data-jasa-bertahap' not in full.text
            assert 'data-jasa-bertahap' in shell.text
            assert '5.000' not in shell.text and 'Jumlah pelanggan belum dibaca.' in shell.text
            assert 'disabled aria-describedby="jasa-detail-alasan"' in shell.text
            assert 'no-store' in shell.headers['cache-control']
        else:
            assert 'Bu Sri' not in data.text and 'data-jasa-bertahap' not in shell.text
        assert await _sidik(pg)==before
