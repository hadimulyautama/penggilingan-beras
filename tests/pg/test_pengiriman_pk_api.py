"""Endpoint UI memakai izin yang sama dengan writer stok."""
import pytest
from fastapi import FastAPI
from httpx import ASGITransport,AsyncClient
from app.models import User
from app.web.deps import pengguna_aksi
from tests.pg.test_pengiriman_pk_bertahap import siap,buat
from tests.pg.test_permintaan_empat_langkah import pabrik
pytestmark=pytest.mark.asyncio

async def test_daftar_dan_aksi_mengikuti_peran_efektif(pg,siap):
 from app.web.pengiriman_pk import router
 app=FastAPI();app.include_router(router)
 w=siap
 async with AsyncClient(transport=ASGITransport(app=app),base_url='http://uji') as client:
  for role,isadmin,send in [('op1',False,True),('op2',False,False),('admin',True,True)]:
   async with pg() as db:u=await db.get(User,w[role])
   app.dependency_overrides[pengguna_aksi]=lambda:u
   r=await client.get('/api/transfer-bertahap');assert r.status_code==200,r.text
   data=r.json();assert data['admin']==isadmin and data['boleh_kirim']==send
   assert data['permintaan'][0]['id']==w['rid']
   if not isadmin:
    r=await client.post('/api/transfer-bertahap/setujui',json={'items':[dict(permintaan_id=w['rid'],berat_kg='1',tujuan='ditumpuk')]});assert r.status_code==403
   if not send:
    r=await client.post('/api/transfer-bertahap/pengiriman',json=dict(items=[dict(permintaan_id=w['rid'],berat_kg='1')],nomor_polisi='K 9773 J',nama_sopir='Kasidi',kunci='a'*32));assert r.status_code==403
   assert r.headers.get('cache-control')=='private, no-store' if r.status_code==200 else True

async def test_permohonan_dari_stok_hingga_antrean_baru_dengan_csrf(pg,pabrik):
 from sqlalchemy import select
 from app.models import PermintaanPk
 from tests.pg.test_riwayat_giling import _klien
 from tests.pg.formulir import cap_formulir
 from app.web import csrf
 async with await _klien(pg,peran='operator',gudang='Gudang 2') as tujuan,await _klien(pg,peran='operator',gudang='Gudang 1') as asal,await _klien(pg,peran='admin') as admin:
  for c in (tujuan,asal,admin):c.headers[csrf.NAMA_HEADER]=cap_formulir(c)
  r=await tujuan.post('/api/actions/minta-pk-g1',json=dict(kode_proses=pabrik['lot'],berat=4000));assert r.status_code==200,r.text
  async with pg() as db:
   request=await db.scalar(select(PermintaanPk));rid=request.id;assert request.bertahap
  r=await admin.get('/pekerjaan?tab=tindakan');assert r.status_code==200 and '/transfer-bertahap' in r.text
  r=await admin.get('/transfer-bertahap');assert r.status_code==200 and 'id="transfer-pk"' in r.text
  r=await admin.post('/api/transfer-bertahap/setujui',json=dict(items=[dict(permintaan_id=rid,berat_kg='4000',tujuan='ditumpuk')]));assert r.status_code==200,r.text
  r=await asal.get('/pekerjaan?tab=tindakan');assert r.status_code==200 and 'Buka transfer per perjalanan' in r.text
  r=await asal.post('/api/transfer-bertahap/pengiriman',json=dict(items=[dict(permintaan_id=rid,berat_kg='1000')],nomor_polisi='K 9773 J',nama_sopir='Kasidi',kunci='b'*32));assert r.status_code==200,r.text
  data=(await tujuan.get('/api/transfer-bertahap')).json();assert data['permintaan'][0]['sisa']=='3000' and len(data['pengiriman'])==1
  result=await admin.post(f'/api/transfer-bertahap/permintaan/{rid}/tutup-sisa',json={'alasan':'Kebutuhan berubah'});assert result.status_code==409
  jid=data['pengiriman'][0]['id']
  result=await admin.post(f'/api/transfer-bertahap/{jid}/batal',json={'alasan':'Belum berangkat; kendaraan batal'});assert result.status_code==200,result.text
  result=await admin.post(f'/api/transfer-bertahap/permintaan/{rid}/tutup-sisa',json={'alasan':'Kebutuhan ditunda'});assert result.status_code==200,result.text
  async with pg() as db:
   request=await db.get(PermintaanPk,rid);assert request.status=='gugur' and request.berat_setuju_kg==4000 and request.berat_final_kg==0
