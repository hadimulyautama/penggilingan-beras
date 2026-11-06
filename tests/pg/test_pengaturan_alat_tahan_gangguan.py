"""Tanda terima dan writer lama memakai transaksi PostgreSQL yang sama."""
import asyncio
from uuid import uuid4
import pytest
from sqlalchemy import select,event,text
from sqlalchemy.orm import Session
from app.models import Dryer,Silo,Warehouse,LiniProduksi,AuditFasilitas
from app.web.pengaturan_alat_simpan import kunci,OBJEK
from hmu_identitas import peran as P
from tests.pg.test_pengaturan_usulan import master,klien,cap,kirim
from tests.pg.test_pengaturan_simpan_terpisah import snapshot
from tests.pg.test_pengaturan_terpadu import fisik
from tests.pg.test_qc_berjalan import giling

pytestmark=pytest.mark.asyncio
HEADERS={'X-Pengaturan-Alat':'1'}

async def context(pg, action):
    async with pg() as db:
        did=await db.scalar(select(Dryer.id).order_by(Dryer.id))
        sid=await db.scalar(select(Silo.id).where(Silo.jenis_isi=='gabah').order_by(Silo.id))
        wid=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g1'))
        lid=await db.scalar(select(LiniProduksi.id).where(LiniProduksi.dryer_id==did))
    data={'_operasi_alat':str(uuid4()),'nama':'Isian tersimpan uji'}
    if action=='dryer-add':path='dryer';data.update(kapasitas_kg='23456',warehouse_id=str(wid),kembali_pengaturan='/pengaturan/mesin')
    elif action=='dryer-edit':path='dryer/edit';data.update(dryer_id=str(did),kapasitas_kg='23456',target_kadar_air='14.3',kembali_pengaturan=f'/pengaturan/mesin/{lid}')
    elif action=='silo-add':path='silo';data.update(warehouse_id=str(wid),jenis_isi='gabah',kembali_pengaturan='/pengaturan/silo')
    else:path='silo/edit';data.update(silo_id=str(sid),komoditas='gabah_kering',kembali_pengaturan='/pengaturan/silo')
    return '/pengaturan/alat/'+path,data

async def post(c,path,data):
    return await c.post(path,data={'_csrf':await cap(c),**data},headers=HEADERS)

@pytest.mark.parametrize('action',['dryer-add','dryer-edit','silo-add','silo-edit'])
async def test_receipt_replay_payload_dan_status(pg,master,giling,action):
    c,_,_=await klien(pg,P.SUPERADMIN)
    path,data=await context(pg,action);stock=await fisik(pg)
    async with c:
        status='/pengaturan/alat/status-simpan/'+data['_operasi_alat']
        assert (await c.get(status)).json()['status']=='belum_tersimpan'
        first=await post(c,path,data)
        assert first.status_code==200 and first.json()['status']=='tersimpan',first.text
        before=await snapshot(pg)
        again=await post(c,path,data)
        assert again.json()==first.json()
        assert await snapshot(pg)==before  # termasuk updated_at dan audit.
        got=await c.get(status)
        assert got.headers['cache-control']=='no-store'
        assert got.json()['status']=='tersimpan' and got.json()['url']==first.json()['url']
        assert (await c.get(got.json()['url'])).status_code==200
        bad=await post(c,path,dict(data,nama='Payload berbeda'))
        assert bad.status_code==409 and bad.json()['status']=='konflik'
        assert await snapshot(pg)==before
    assert await fisik(pg)==stock

@pytest.mark.parametrize('action',['dryer-add','dryer-edit','silo-add','silo-edit'])
async def test_db_gagal_receipt_rollback_lalu_retry(pg,master,action):
    c,_,_=await klien(pg,P.SUPERADMIN);path,data=await context(pg,action)
    before=await snapshot(pg)
    def mark(session,*_):
        if any(isinstance(x,AuditFasilitas) and x.objek==OBJEK and x.sesudah.get('operasi_id')==data['_operasi_alat'] for x in session.new):session.info['gagal_alat']=True
    def fail(session):
        if session.info.get('gagal_alat'):session.execute(text('SELECT 1 / 0'))
    event.listen(Session,'before_flush',mark);event.listen(Session,'before_commit',fail)
    async with c:
        try:r=await post(c,path,data)
        finally:event.remove(Session,'before_flush',mark);event.remove(Session,'before_commit',fail)
        assert r.status_code==503 and r.json()['status']=='belum_pasti'
        assert await snapshot(pg)==before
        assert (await c.get('/pengaturan/alat/status-simpan/'+data['_operasi_alat'])).json()['status']=='belum_tersimpan'
        assert (await post(c,path,data)).json()['status']=='tersimpan'
        after=await snapshot(pg)
        assert (await post(c,path,data)).json()['status']=='tersimpan'
        assert await snapshot(pg)==after

@pytest.mark.parametrize('action',['dryer-add','dryer-edit','silo-add','silo-edit'])
async def test_serentak_token_sama(pg,master,action):
    c,_,_=await klien(pg,P.SUPERADMIN);path,data=await context(pg,action)
    async with c:
        payload={'_csrf':await cap(c),**data}
        a,b=await asyncio.gather(*[c.post(path,data=payload,headers=HEADERS) for _ in range(2)])
        assert a.status_code==b.status_code==200 and a.json()==b.json()
    async with pg() as db:
        receipts=list((await db.scalars(select(AuditFasilitas).where(AuditFasilitas.objek==OBJEK))).all())
        assert len(receipts)==1

@pytest.mark.parametrize('action',['dryer-add','silo-add'])
async def test_dua_token_nama_sama_tidak_membuat_ganda(pg,master,action):
    c,_,_=await klien(pg,P.SUPERADMIN);path,data=await context(pg,action)
    async with c:
        csrf=await cap(c)
        a,b=await asyncio.gather(c.post(path,data={'_csrf':csrf,**data},headers=HEADERS),
            c.post(path,data={'_csrf':csrf,**data,'_operasi_alat':str(uuid4())},headers=HEADERS))
        assert sorted([a.status_code,b.status_code])==[200,422]
        assert [a.json()['status'],b.json()['status']].count('tersimpan')==1

async def test_status_diproses_dan_batas_aktor(pg,master):
    c,_,uid=await klien(pg,P.SUPERADMIN);token=str(uuid4());path='/pengaturan/alat/status-simpan/'+token
    async with c,pg() as db:
        await db.execute(text('SELECT pg_advisory_xact_lock(:k)'),{'k':kunci(uid,token)})
        assert (await c.get(path)).json()['status']=='diproses'
        await db.rollback()
        assert (await c.get(path)).json()['status']=='belum_tersimpan'
        assert (await c.get('/pengaturan/alat/status-simpan/salah')).status_code==422
        path,data=await context(pg,'dryer-add');assert (await post(c,path,data)).status_code==200
    other,_,_=await klien(pg,P.SUPERADMIN,username='super_lain')
    async with other:assert (await other.get('/pengaturan/alat/status-simpan/'+data['_operasi_alat'])).json()['status']=='belum_tersimpan'

@pytest.mark.parametrize('role,view,gd',[(P.ADMIN,None,None),(P.OPERATOR,None,'Gudang 1'),(P.OPERATOR,None,'Gudang 2'),(P.SUPERADMIN,P.ADMIN,None),(P.SUPERADMIN,'operator:g1',None),(P.SUPERADMIN,'operator:g2',None)])
async def test_status_dan_simpan_tetap_mengikuti_lihat_sebagai(pg,master,role,view,gd):
    guard,_,_=await klien(pg,P.SUPERADMIN,username='penjaga_super');await guard.aclose()
    c,_,_=await klien(pg,role,gd)
    path,data=await context(pg,'silo-add')
    async with c:
        if view:assert (await kirim(c,'/lihat-sebagai',{'peran':view})).status_code==303
        before=await snapshot(pg)
        assert (await c.get('/pengaturan/alat/status-simpan/'+data['_operasi_alat'])).status_code==403
        assert (await post(c,path,data)).status_code==403
        assert await snapshot(pg)==before

async def test_status_db_tidak_terbaca_tidak_menyatakan_gagal_pasti(pg,master,monkeypatch):
    from app.web import pengaturan_alat_simpan as svc
    c,_,_=await klien(pg,P.SUPERADMIN)
    async def gagal(db,*args):
        await db.execute(text('SELECT 1 / 0'))
    monkeypatch.setattr(svc,'_receipt',gagal)
    before=await snapshot(pg)
    async with c:
        r=await c.get('/pengaturan/alat/status-simpan/'+str(uuid4()))
        assert r.status_code==200 and r.json()['status']=='belum_pasti'
        assert 'Jangan kirim ulang' in r.json()['pesan']
    assert await snapshot(pg)==before

@pytest.mark.parametrize('action',['dryer-add','dryer-edit','silo-add','silo-edit'])
async def test_json_validasi_tidak_menerbitkan_receipt(pg,master,action):
    c,_,_=await klien(pg,P.SUPERADMIN);path,data=await context(pg,action)
    if action=='dryer-add':data['kapasitas_kg']='0'
    elif action=='dryer-edit':data['target_kadar_air']='31'
    elif action=='silo-add':
        async with pg() as db:
            s=await db.scalar(select(Silo).where(Silo.jenis_isi=='gabah').order_by(Silo.id))
            data.update(nama=s.nama_silo,warehouse_id=str(s.warehouse_id))
    else:data['komoditas']='bekatul'
    before=await snapshot(pg)
    async with c:
        response=await post(c,path,data)
        assert response.status_code==422 and response.json()['status']=='ditolak'
        assert (await c.get('/pengaturan/alat/status-simpan/'+data['_operasi_alat'])).json()['status']=='belum_tersimpan'
    assert await snapshot(pg)==before

@pytest.mark.parametrize('token',[None,'bukan-uuid'])
async def test_json_wajib_identitas_dan_csrf(pg,master,token):
    c,_,_=await klien(pg,P.SUPERADMIN);path,data=await context(pg,'dryer-add')
    async with c:
        before=await snapshot(pg)
        assert (await c.post(path,data=data,headers=HEADERS)).status_code==403
        if token is None:data.pop('_operasi_alat')
        else:data['_operasi_alat']=token
        r=await post(c,path,data)
        assert r.status_code==409 and r.json()['status']=='konflik'
        assert await snapshot(pg)==before
