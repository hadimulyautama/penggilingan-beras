"""Batas proyeksi halaman tidak memotong rekap atau cakupan yang diizinkan."""
from decimal import Decimal as D
import pytest
from sqlalchemy import select,event
from sqlalchemy.orm import Session
from hmu_identitas import peran as P
from app.models import Warehouse,User
from app.models.retur_supplier import ReturSupplier as R,ReturSupplierKeluar as K
from app.services import riwayat_retur_supplier as h
from tests.pg.test_retur_supplier import asal,skema_retur_timbang,user
from tests.pg.test_riwayat_retur_supplier import sidik_semua,selesai
from tests.pg.histori_retur_fixture import arsip


@pytest.mark.parametrize('role',[P.OPERATOR,P.ADMIN,P.SUPERADMIN])
async def test_halaman_stabil_batas_dua_puluh_dan_cakupan(pg,asal,role):
    async with pg() as db:
        await arsip(db,asal)
        actor=await db.get(User,asal['uid']);actor.role=role;actor.default_warehouse_id=asal['wh'];await db.commit()
        expected=(await db.scalars(select(R.id).order_by(R.waktu.desc(),R.id.desc()))).all()
        before=await sidik_semua(db)
    for page in (1,2,3,999):
        seen=[]
        def load(session,instance):
            if isinstance(instance,R):seen.append(instance.id)
        event.listen(Session,'loaded_as_persistent',load)
        try:
            async with pg() as db:
                d=await h.daftar(db,user(asal,role),halaman=page,supplier=asal['sid'],gudang=asal['wh'],penerimaan=asal['tid'])
                actual=min(page,3)
                assert [x['rec'].id for x in d['rows']]==expected[(actual-1)*20:actual*20]
                assert d['halaman']==actual and d['pages']==3 and d['total']==45
                assert d['total_keluar']==0 and d['jumlah_keluar']==0
                assert len(seen)<=20
        finally:event.remove(Session,'loaded_as_persistent',load)
    async with pg() as db:
        assert await sidik_semua(db)==before
        g1=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g1'))
        limited=await h.daftar(db,user(asal,P.OPERATOR,g1))
        assert limited['total']==0 and limited['rows']==[] and limited['suppliers']=={}


async def test_json_rekap_historis_dan_halaman_tidak_mengubah_tipe_angka(pg,asal,monkeypatch):
    async with pg() as db:
        ids=[]
        for i in range(4):
            r,_,_=await selesai(db,asal);ids.append(r.id)
        amounts=[dict(total_kg='1.10'),dict(total_kg=0.1),dict(total_kg=None),{}]
        for rid,value in zip(ids,amounts):
            ledger=await db.scalar(select(K).where(K.retur_supplier_id==rid));ledger.snapshot={**ledger.snapshot,**value}
            if not value:ledger.snapshot={k:v for k,v in ledger.snapshot.items() if k!='total_kg'}
        await db.commit();before=await sidik_semua(db)
        monkeypatch.setattr(h,'UKURAN_HALAMAN',1)
        d=await h.daftar(db,user(asal),halaman=4)
        assert len(d['rows'])==1 and d['total']==4 and d['jumlah_keluar']==4
        assert d['keluar_tidak_lengkap']==2
        assert d['total_keluar']==D(0.1)+D('1.10')
        assert await sidik_semua(db)==before


async def test_filter_dinamis_mempertahankan_casefold_dan_status(pg,asal):
    async with pg() as db:
        ids=await arsip(db,asal)
        r=await db.get(R,ids[0]);r.sumber={**r.sumber,'supplier':'STRAẞE Sintetis'}
        await db.commit();before=await sidik_semua(db)
        d=await h.daftar(db,user(asal),q='strasse')
        assert d['total']==1 and d['rows'][0]['rec'].id==ids[0]
        d=await h.daftar(db,user(asal),status='cancel')
        assert d['total']==44 and len(d['rows'])==20
        assert all(r['status']=='cancel' for r in d['rows'])
        assert await sidik_semua(db)==before
