"""Gagal satu sumber tidak boleh menyimpan pemindahan sebagian."""
import pytest
from sqlalchemy import select,func
from app.database import now_local
from app.models import User,PolishingProcess,PolishingOutputLog,PolishingSiloUsage,ByproductStock,BrokenKeSilo
from app.penggilingan.gudang2 import service as g2
from tests.pg.test_form_broken_silo import sosoh,hasil
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir

@pytest.mark.parametrize('penerimaan',[False,True])
async def test_sumber_kedua_tidak_sah_membatalkan_seluruh_pemindahan_http(pg,sosoh,penerimaan):
    await hasil(pg,sosoh,0 if penerimaan else 100)
    async with pg() as db:
        p=PolishingProcess(kode_proses='POL-SUMBER-AKTIF',status='proses',waktu_mulai=now_local(),created_by=sosoh['user'])
        db.add(p);await db.flush()
        db.add(PolishingOutputLog(polishing_process_id=p.id,jenis='broken',berat_kg=100,waktu_update=now_local(),input_by=sosoh['user']))
        db.add(PolishingSiloUsage(polishing_process_id=p.id,silo_id=sosoh['silo']['C'],berat_awal_kg=500))
        if penerimaan:
            db.add(ByproductStock(jenis_produk='broken',source_type='timbangan',source_id=123,berat_kg=100,tanggal=now_local().date(),waktu=now_local(),input_by=sosoh['user']))
        await db.commit()
    async with await _klien(pg,sosoh['user'],'broken-atomik',mode='admin') as c:
        r=await c.post('/api/actions/masukkan-broken-silo',json=dict(proses='pemilik|pabrik',berat_kg=150,silo='C'),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==400 and 'SEDANG' in r.text,r.text
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(BrokenKeSilo))==0
        u=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.silo_id==sosoh['silo']['C']))
        assert float(u.berat_masuk_kg or 0)==0
        assert await db.scalar(select(func.count()).select_from(ByproductStock))==int(penerimaan)

async def test_broken_setelah_retur_hanya_sisa_fisik_bisa_masuk_silo(pg,asal):
    from uuid import uuid4
    from sqlalchemy import text
    from tests.pg.test_retur_supplier import buat_sumber,tiket,user
    from app.models.retur_supplier import ReturSupplierItem
    from app.services import retur_supplier as s,retur_supplier_selesai as f
    async with pg() as db:
        tid,row,key=await buat_sumber(db,asal,'broken',kg='998')
        payload=[dict(kunci=key,jumlah='125.25')]
        check=await s.periksa(db,tid,user(asal),payload,'Mutu tidak sesuai','')
        rec=await s.simpan(db,user=user(asal),tid=tid,jumlah=payload,alasan='Mutu tidak sesuai',catatan='',kunci=uuid4().hex,dasar=check['dasar'])
        t=await tiket(db,asal['sid'],'RETUR_SUPPLIER','RETUR_KELUAR');await db.flush()
        await s.hubungkan(db,user=user(asal),identitas=rec.id,tiket_id=t)
        await db.execute(text("UPDATE timbangan_transaksi SET timbang2_kg=5125.25,berat_barang_kg=125.25,status_tiket='SELESAI' WHERE id=:id"),dict(id=t));await db.commit()
        it=await db.scalar(select(ReturSupplierItem).where(ReturSupplierItem.retur_supplier_id==rec.id))
        snap=await f.periksa(db,identitas=rec.id,user=user(asal),jumlah=[dict(item_id=it.id,jumlah='125.25')]);await db.commit()
        await f.catat_keluar(db,identitas=rec.id,user=user(asal),dasar=snap['dasar'],konfirmasi=True);await db.commit()
        u=await db.get(User,asal['uid'])
        rid=row.id
        assert await g2._sisa_broken_row(db,rid)==872.75
        with pytest.raises(g2.Gudang2Error,match='sisa broken'):
            await g2.pindah_broken_ke_silo(db,user=u,byproduct_stock_id=rid,nama_silo='A',berat=998)
        await db.rollback()
        r=await g2.pindah_broken_ke_silo(db,user=await db.get(User,asal['uid']),byproduct_stock_id=rid,nama_silo='A')
        assert r.berat_kg==872.75 and r.sisa_broken==0
        assert await g2._sisa_broken_row(db,rid)==0

from tests.pg.test_retur_supplier import asal,skema_retur_timbang

@pytest.mark.parametrize('penerimaan',[False,True])
async def test_dua_operator_ke_silo_berbeda_tidak_memakai_saldo_yang_sama(pg,sosoh,penerimaan):
    import asyncio
    await hasil(pg,sosoh,0 if penerimaan else 100)
    if penerimaan:
        async with pg() as db:
            db.add(ByproductStock(jenis_produk='broken',source_type='timbangan',source_id=123,berat_kg=100,tanggal=now_local().date(),waktu=now_local(),input_by=sosoh['user']));await db.commit()
    async def pindah(silo):
        async with pg() as db:
            try:
                await g2.masukkan_stok_broken_pemilik_ke_silo(db,user=await db.get(User,sosoh['user']),jasa_id=None,nama_silo=silo,berat_kg=75)
                return True
            except g2.Gudang2Error:
                await db.rollback();return False
    assert sum(await asyncio.gather(pindah('C'),pindah('D')))==1
    async with pg() as db:
        assert await db.scalar(select(func.sum(BrokenKeSilo.berat_kg)))==75
        direct,procs,_=await g2.rencana_broken_pemilik(db,jasa_id=None,berat_kg=None)
        assert sum(w for _,w in direct+procs)==25
