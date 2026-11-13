"""Unit transfer dikonversi server; stok, batas persetujuan dan idempotensi tetap satu."""
import uuid
from decimal import Decimal
import pytest
from fastapi import FastAPI
from httpx import ASGITransport,AsyncClient
from sqlalchemy import select,func
from app.models import User,InternalTransfer,PermintaanPk
from app.services import pengiriman_pk as s,transfer
from app.web.deps import pengguna_aksi
from app.web.pengiriman_pk import router
from tests.pg.test_pengiriman_pk_bertahap import siap,lot_lain
from tests.pg.test_permintaan_empat_langkah import pabrik
pytestmark=pytest.mark.asyncio

@pytest.fixture
async def api(pg,siap):
 app=FastAPI();app.include_router(router)
 async with pg() as db:u=await db.get(User,siap['op1'])
 app.dependency_overrides[pengguna_aksi]=lambda:u
 async with AsyncClient(transport=ASGITransport(app=app),base_url='http://uji') as client:yield client

def body(w,**fields):return dict(items=[dict(permintaan_id=w['rid'],**fields)],kunci=uuid.uuid4().hex)

async def test_karung_curah_dan_kg_dengan_kunci_sama_tidak_menggandakan_stok(pg,siap,api):
 payload=body(siap,cara='karung',jumlah_karung=23,berat_curah_kg='2')
 result=await api.post('/api/transfer-bertahap/pengiriman',json=payload);assert result.status_code==200,result.text
 payload['items']=[dict(permintaan_id=siap['rid'],cara='kg',berat_kg='1152')]
 ulang=await api.post('/api/transfer-bertahap/pengiriman',json=payload);assert ulang.status_code==200 and ulang.json()['ulang']
 assert result.json()['id']==ulang.json()['id']
 async with pg() as db:
  assert await db.scalar(select(func.count()).select_from(InternalTransfer))==1
  assert await db.scalar(select(func.sum(InternalTransfer.berat_kg)))==1152
  assert await transfer.saldo_pk(db,siap['proses_id'])==4848
  assert await s.sisa(db,await db.get(PermintaanPk,siap['rid']))==4848

@pytest.mark.parametrize('fields,status',[
 ({'cara':'karung','jumlah_karung':121,'berat_curah_kg':'0'},409),
 ({'cara':'karung','jumlah_karung':120,'berat_curah_kg':'0.01'},409),
 ({'cara':'karung','jumlah_karung':0,'berat_curah_kg':'0'},409),
 ({'cara':'karung','jumlah_karung':-1,'berat_curah_kg':'50'},422),
 ({'cara':'karung','jumlah_karung':1.5,'berat_curah_kg':'0'},422),
 ({'cara':'karung','jumlah_karung':True,'berat_curah_kg':'0'},422),
 ({'cara':'karung','jumlah_karung':1,'berat_curah_kg':'NaN'},409),
 ({'cara':'karung','jumlah_karung':1,'berat_curah_kg':'-1'},409),
 ({'cara':'karung','jumlah_karung':1,'berat_curah_kg':'0.001'},409),
 ({'cara':'kg','berat_kg':'50','jumlah_karung':1},409),
 ({'cara':'karung','berat_kg':'50','jumlah_karung':1},409),
 ({'cara':'karung','jumlah_karung':1,'berat_curah_kg':'0','berat_kg':'50'},409),
])
async def test_isian_tidak_sah_tidak_mengubah_stok(pg,siap,api,fields,status):
 result=await api.post('/api/transfer-bertahap/pengiriman',json=body(siap,**fields));assert result.status_code==status,result.text
 async with pg() as db:
  assert await db.scalar(select(func.count()).select_from(InternalTransfer))==0
  assert await transfer.saldo_pk(db,siap['proses_id'])==6000

async def test_curah_saja_boleh_dan_batas_tepat_selesai_otomatis(pg,siap,api):
 for fields in [dict(cara='karung',jumlah_karung=0,berat_curah_kg='31.25'),dict(cara='karung',jumlah_karung=119,berat_curah_kg='18.75')]:
  r=await api.post('/api/transfer-bertahap/pengiriman',json=body(siap,**fields));assert r.status_code==200,r.text
 async with pg() as db:
  request=await db.get(PermintaanPk,siap['rid']);assert request.status=='selesai' and request.berat_final_kg==6000
  assert await transfer.saldo_pk(db,siap['proses_id'])==0

async def test_beberapa_lot_boleh_memakai_unit_berbeda(pg,siap,api):
 rid=await lot_lain(pg,siap)
 async with pg() as db:await s.setujui_banyak(db,user=await db.get(User,siap['admin']),items=[dict(permintaan_id=rid,berat_kg='3000',tujuan='ditumpuk')])
 payload=dict(items=[dict(permintaan_id=siap['rid'],cara='karung',jumlah_karung=1,berat_curah_kg='2'),dict(permintaan_id=rid,cara='kg',berat_kg='100.75')],kunci=uuid.uuid4().hex)
 r=await api.post('/api/transfer-bertahap/pengiriman',json=payload);assert r.status_code==200,r.text
 async with pg() as db:
  amounts=list((await db.scalars(select(InternalTransfer.berat_kg).order_by(InternalTransfer.id))).all())
  assert amounts==[Decimal('52'),Decimal('100.75')]
