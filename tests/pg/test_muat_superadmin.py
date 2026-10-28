"""Super Admin melihat tugas muat dan memakai alur pencatatan yang sama."""
import pytest
from sqlalchemy import select
from app.models import User, OutgoingRecord, ActivityLog
from app.services import berjalan, barang_keluar as bk
from tests.pg.test_barang_keluar import gudang, _perintah, _klien, _stok
from tests.pg.formulir import cap_formulir
from hmu_identitas import peran as P

pytestmark=pytest.mark.asyncio


@pytest.mark.parametrize('role',[P.SUPERADMIN,P.ADMIN])
@pytest.mark.parametrize('karung',[1,40])
async def test_tugas_dan_tombol_muat_mengikuti_peran_efektif(pg,gudang,role,karung):
    r=await _perintah(pg,gudang,karung=karung)
    async with pg() as db:
        u=await db.get(User,gudang['adm']);u.role=role;await db.commit()
        daftar=await berjalan.untuk(db,u)
        kartu=[b for b in daftar.menunggu if b.kode==r.rec.kode and b.aksi=='muat_semua']
        assert len(kartu)==int(role==P.SUPERADMIN)
        awal=(await db.scalars(select(ActivityLog.id).order_by(ActivityLog.id))).all()
    async with await _klien(pg,gudang['adm'],'muat-peran') as c:
        page=await c.get('/pekerjaan')
        assert page.status_code==200
        if role==P.SUPERADMIN:assert r.rec.kode in page.text and 'Muat barang keluar' in page.text
        detail=await c.get(f'/barang-keluar/{r.rec.id}')
        assert detail.status_code==200
        assert ('buka=muat_semua' in detail.text)==(role==P.SUPERADMIN)
        assert ('buka=selesai_muat' in detail.text)==(role==P.SUPERADMIN)
        assert 'buka=batal_perintah_keluar' in detail.text
    async with pg() as db:
        assert (await db.get(User,gudang['adm'])).role==role
        assert (await db.scalars(select(ActivityLog.id).order_by(ActivityLog.id))).all()==awal
    assert await _stok(pg,gudang)==10000


@pytest.mark.parametrize('mode,status,muat',[
    ('admin',200,False),('operator:g1',403,False),('operator:g2',200,True),
])
async def test_super_admin_lihat_sebagai_tetap_mengikuti_mode(pg,gudang,mode,status,muat):
    r=await _perintah(pg,gudang,karung=40)
    async with pg() as db:
        u=await db.get(User,gudang['adm']);u.role=P.SUPERADMIN;await db.commit()
    async with await _klien(pg,gudang['adm'],'muat-mode') as c:
        c.cookies.set('produksi_lihat',mode)
        response=await c.get(f'/barang-keluar/{r.rec.id}')
        assert response.status_code==status
        if status==200:assert ('buka=muat_semua' in response.text)==muat
    assert await _stok(pg,gudang)==10000
    async with pg() as db:assert (await db.get(User,gudang['adm'])).role==P.SUPERADMIN


async def test_super_admin_mencatat_muatan_tanpa_pengurangan_ganda(pg,gudang):
    r=await _perintah(pg,gudang,karung=40)
    async with pg() as db:
        u=await db.get(User,gudang['adm']);u.role=P.SUPERADMIN;await db.commit()
        rec=await db.get(OutgoingRecord,r.rec.id)
        dasar=(await bk.ringkasan_muat(db,rec))['dasar']
    async with await _klien(pg,gudang['adm'],'muat-super') as c:
        page=await c.get(f'/muatan?perintah={r.rec.id}')
        assert page.status_code==200 and 'data-boleh="1"' in page.text
        body=dict(perintah=str(r.rec.id),baris=str(r.baris[0].id),jumlah=20,dasar=dasar)
        headers={'X-CSRF-Token':cap_formulir(c)}
        preview=await c.post('/api/actions/periksa-catat-muatan',json=body,headers=headers)
        assert preview.status_code==200,preview.text
        assert await _stok(pg,gudang)==10000
        simpan=await c.post('/api/actions/muat-barang',json=body,headers=headers)
        assert simpan.status_code==200,simpan.text
        ulang=await c.post('/api/actions/muat-barang',json=body,headers=headers)
        assert ulang.status_code==409,ulang.text
    assert await _stok(pg,gudang)==9500
    async with pg() as db:assert (await db.get(User,gudang['adm'])).role==P.SUPERADMIN
