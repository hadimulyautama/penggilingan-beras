"""Input karung/curah memakai rantai kg lama, bukan perpindahan baru."""
import asyncio
from decimal import Decimal
import pytest
from sqlalchemy import select, func
from app.models import User, PermintaanPk, InternalTransfer, PkGudang2Intake, Peristiwa
from app.services.transfer import saldo_pk
from app.services.permintaan_pk import tutup_admin
from tests.pg.test_permintaan_empat_langkah import pabrik, _minta, _acc
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir
from hmu_identitas import peran as P

pytestmark = pytest.mark.asyncio

async def post(c, aksi, **isi):
    return await c.post('/api/actions/'+aksi, json=isi, headers={'X-CSRF-Token':cap_formulir(c)})

async def test_empat_tahap_unit_dan_saldo(pg,pabrik):
    async with await _klien(pg,pabrik['op2'],'minta-karung',mode='operator') as c:
        for _ in range(2):
            r=await c.get('/api/actions/pratinjau-unit-transfer-pk/minta',params=dict(kode_proses=pabrik['lot'],cara='karung',jumlah_karung=10,berat_curah_kg=20))
            assert r.status_code==200 and r.json()['rincian']['total_kg']==520,r.text
        async with pg() as db:
            assert await saldo_pk(db,pabrik['proses_id'])==6000
            assert await db.scalar(select(func.count()).select_from(PermintaanPk))==0
            assert await db.scalar(select(func.count()).select_from(Peristiwa))==0
        r=await post(c,'minta-pk-g1',kode_proses=pabrik['lot'],cara='karung',jumlah_karung=10,berat_curah_kg=20)
        assert r.status_code==200,r.text
    async with pg() as db:
        b=(await db.scalars(select(PermintaanPk))).one();pid=b.id
        assert b.berat_minta_kg==520 and b.status=='diminta'
        assert await saldo_pk(db,pabrik['proses_id'])==6000
    await _acc(pg,pabrik,pid,tujuan='ditumpuk',berat=510)
    async with pg() as db: assert await saldo_pk(db,pabrik['proses_id'])==6000
    async with await _klien(pg,pabrik['op1'],'kirim-karung',mode='operator') as c:
        r=await c.get('/api/actions/pratinjau-unit-transfer-pk/kirim',params=dict(permintaan=pid,cara='karung',jumlah_karung=11))
        assert r.status_code==200 and 'Melebihi persetujuan' in r.json()['teks']
        r=await post(c,'kirim-permintaan-pk',permintaan=str(pid),cara='karung',jumlah_karung=11)
        assert r.status_code==400,r.text
        r=await post(c,'kirim-permintaan-pk',permintaan=str(pid),cara='karung',jumlah_karung=10,berat_curah_kg=5)
        assert r.status_code==200,r.text
        r=await post(c,'kirim-permintaan-pk',permintaan=str(pid),cara='karung',jumlah_karung=10,berat_curah_kg=5)
        assert r.status_code==400
    async with pg() as db:
        b=await db.get(PermintaanPk,pid)
        assert (b.berat_minta_kg,b.berat_setuju_kg,b.berat_kirim_kg,b.berat_final_kg)==(520,510,505,None)
        tr=(await db.scalars(select(InternalTransfer))).one()
        assert (tr.berat_kg,tr.jumlah_karung,tr.berat_curah_kg)==(505,10,5)
        it=(await db.scalars(select(PkGudang2Intake))).one();assert it.berat_kg==505
        assert await saldo_pk(db,pabrik['proses_id'])==5495
        assert await db.scalar(select(func.count()).select_from(Peristiwa))==2
        await tutup_admin(db,user=await db.get(User,pabrik['admin']),permintaan_id=pid,berat_final=505)
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(InternalTransfer))==1
        assert (await db.get(PermintaanPk,pid)).berat_final_kg==505
        assert await saldo_pk(db,pabrik['proses_id'])==5495

@pytest.mark.parametrize('isi', [dict(berat=75.125),dict(cara='kg',berat=75.125),dict(cara='karung',berat_curah_kg=20),dict(cara='karung',jumlah_karung=0,berat_curah_kg=.125)])
async def test_kontrak_kg_dan_curah_saja(pg,pabrik,isi):
    async with await _klien(pg,pabrik['op2'],'kontrak-kg',mode='operator') as c:
        r=await post(c,'minta-pk-g1',kode_proses=pabrik['lot'],**isi);assert r.status_code==200,r.text
    async with pg() as db:
        b=(await db.scalars(select(PermintaanPk))).one();pid=b.id
    await _acc(pg,pabrik,pid,tujuan='ditumpuk',berat=100)
    async with await _klien(pg,pabrik['op1'],'kontrak-kg-kirim',mode='operator') as c:
        r=await post(c,'kirim-permintaan-pk',permintaan=str(pid),**isi);assert r.status_code==200,r.text
    async with pg() as db:
        tr=(await db.scalars(select(InternalTransfer))).one()
        assert tr.berat_kg in [Decimal('75.13'),Decimal('20'),Decimal('.13')]

@pytest.mark.parametrize('isi', [dict(cara='karung'),dict(cara='karung',jumlah_karung=0),dict(jumlah_karung=1.5),dict(jumlah_karung=-1),dict(jumlah_karung=True),dict(berat_curah_kg=-1),dict(berat_curah_kg='NaN'),dict(berat_curah_kg='Infinity'),dict(berat=50,jumlah_karung=1),dict(cara='kg',jumlah_karung=1),dict(cara='karung',berat=50),dict(jumlah_karung=121)])
async def test_input_tidak_sah_tanpa_stok_atau_niat(pg,pabrik,isi):
    async with await _klien(pg,pabrik['op2'],'invalid-unit',mode='operator') as c:
        r=await post(c,'minta-pk-g1',kode_proses=pabrik['lot'],**isi);assert r.status_code in [400,422],r.text
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(PermintaanPk))==0
        assert await saldo_pk(db,pabrik['proses_id'])==6000

async def test_kirim_kosong_klien_lama_dan_koreksi_admin(pg,pabrik):
    pid=await _minta(pg,pabrik,berat=520);await _acc(pg,pabrik,pid,tujuan='ditumpuk',berat=510)
    async with await _klien(pg,pabrik['op1'],'kosong-lama',mode='operator') as c:
        r=await post(c,'kirim-permintaan-pk',permintaan=str(pid));assert r.status_code==200,r.text
    async with pg() as db:
        b=await db.get(PermintaanPk,pid);assert b.berat_kirim_kg==510
        await tutup_admin(db,user=await db.get(User,pabrik['admin']),permintaan_id=pid,berat_final=500)
    async with pg() as db:
        b=await db.get(PermintaanPk,pid)
        assert (b.berat_minta_kg,b.berat_setuju_kg,b.berat_kirim_kg,b.berat_final_kg)==(520,510,510,500)
        rows=(await db.scalars(select(InternalTransfer).order_by(InternalTransfer.id))).all()
        assert [(r.status,r.berat_kg) for r in rows]==[('dibatalkan',510),('terkirim',500)]
        assert await saldo_pk(db,pabrik['proses_id'])==5500

@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN,P.SUPERADMIN,P.PERAN_PENSIUN[0]])
async def test_izin_efektif_dan_pratinjau(pg,pabrik,role):
    async with pg() as db:
        u=await db.get(User,pabrik['op1']);u.role=role;await db.commit()
    async with await _klien(pg,pabrik['op1'],'peran-unit',mode='operator' if role==P.OPERATOR else 'admin') as c:
        # Identitas staf lama bukan izin admin. Peran efektif tetap diproses sesi.
        kirim=await c.get('/api/actions/pratinjau-unit-transfer-pk/kirim')
        minta=await c.get('/api/actions/pratinjau-unit-transfer-pk/minta')
        assert minta.status_code in [403,401]
        assert kirim.status_code == 200 if role in [P.OPERATOR,P.ADMIN,P.SUPERADMIN] else kirim.status_code in [401,403]

async def test_permohonan_dan_pengiriman_bersamaan(pg,pabrik):
    async with await _klien(pg,pabrik['op2'],'ganda-minta',mode='operator') as c:
        rs=await asyncio.gather(*(post(c,'minta-pk-g1',kode_proses=pabrik['lot'],cara='karung',jumlah_karung=10) for _ in range(2)))
        assert sorted(r.status_code for r in rs)==[200,400]
    async with pg() as db: pid=(await db.scalars(select(PermintaanPk))).one().id
    await _acc(pg,pabrik,pid,tujuan='ditumpuk',berat=500)
    async with await _klien(pg,pabrik['op1'],'ganda-kirim',mode='operator') as c:
        rs=await asyncio.gather(*(post(c,'kirim-permintaan-pk',permintaan=str(pid),cara='karung',jumlah_karung=10) for _ in range(2)))
        assert sorted(r.status_code for r in rs)==[200,400]
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(InternalTransfer))==1
        assert await saldo_pk(db,pabrik['proses_id'])==5500


@pytest.mark.parametrize('view',['operator:g1','operator:g2'])
async def test_admin_lihat_sebagai_dan_akses_langsung(pg,pabrik,view):
    pid=await _minta(pg,pabrik,berat=500)
    await _acc(pg,pabrik,pid,tujuan='ditumpuk',berat=500)
    async with await _klien(pg,pabrik['admin'],'lihat-unit',mode='admin') as c:
        r=await c.post('/lihat-sebagai',data={'peran':view,'_csrf':cap_formulir(c)})
        assert r.status_code==303,r.text
        r=await c.get('/api/actions/pratinjau-unit-transfer-pk/kirim',params={'permintaan':pid,'jumlah_karung':10})
        assert r.status_code==(200 if view=='operator:g1' else 403),r.text
        r=await c.get('/api/actions/pratinjau-unit-transfer-pk/minta',params={'kode_proses':pabrik['lot'],'jumlah_karung':10})
        assert r.status_code==(200 if view=='operator:g2' else 403),r.text
        if view=='operator:g2':
            r=await post(c,'kirim-permintaan-pk',permintaan=str(pid),cara='karung',jumlah_karung=10)
            assert r.status_code==403,r.text
        else:
            r=await post(c,'minta-pk-g1',kode_proses=pabrik['lot'],cara='karung',jumlah_karung=10)
            assert r.status_code==403,r.text


async def test_bentuk_menu_unit_dan_persetujuan_lama(pg,pabrik):
    for key,mode,aksi in [('op2','operator','minta_pk_g1'),('op1','operator','kirim_permintaan_pk'),('admin','admin','acc_permintaan_pk')]:
        async with await _klien(pg,pabrik[key],'menu-'+key,mode=mode) as c:
            r=await c.get('/api/actions/menu');assert r.status_code==200,r.text
            a=next(a for a in r.json() if a['id']==aksi)
            fields={f['name']:f for f in a['fields']}
            if key=='admin':
                assert set(fields)=={'permintaan','tujuan','berat'} and fields['berat']['wajib']
            else:
                assert {'cara','jumlah_karung','berat_curah_kg','berat','unit_pk'}<=fields.keys()
                assert fields['cara']['bawaan']=='karung' and not fields['berat'].get('wajib')
                assert fields['unit_pk']['type']=='pratinjau'
