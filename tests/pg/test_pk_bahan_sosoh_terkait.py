"""Siklus silo baru mengabaikan log lama; lengkapi koreksi yang sudah tersimpan."""
from datetime import timedelta
from decimal import Decimal as D
import pytest
from sqlalchemy import select
from app.database import now_local
from app.models import (User,ActivityLog,PolishingProcess,PolishingSiloUsage,InternalTransfer,PkGudang2Intake)
from app.services import kepemilikan as umum,pk_persediaan as ledger
from tests.pg.test_pk_koreksi_rantai import rantai,world,save,req,total
from tests.pg.test_masuk_detail_timbang import sidik
pytestmark=pytest.mark.asyncio

async def test_log_tutup_lama_dan_silo_ditambahkan_setelah_proses_mulai(pg,rantai):
 w=rantai
 async with pg() as db:
  p=await db.get(PolishingProcess,w['pol']);p.waktu_mulai=now_local()-timedelta(hours=2)
  u=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==p.id,PolishingSiloUsage.silo_id==w['silo']))
  db.add(ActivityLog(table_name='polishing_silo_usage',record_id=u.id,action='UPDATE',aksi='tutup_silo_sosoh',changed_by=w['user'],waktu_perubahan=now_local()-timedelta(days=3)))
  await db.commit()
  result,_=await save(db,w,10000)
  assert result['plan']['pk_chain']['processes']
  await db.refresh(u)
  assert u.awal_tetap_kg==10000 and u.masuk_tetap_kg==0
  assert await total(db,w['pol'])==D('19977.5')

async def legacy_edit(db,w,monkeypatch):
 import app.services.pk_koreksi_rantai as chain
 original=chain.rancang
 async def skip_silo(*args,**kwargs):return None
 async def legacy_plan(*args,**kwargs):
  p=await original(*args,**kwargs);p.pop('linkage_version',None);return p
 with monkeypatch.context() as m:
  m.setattr(chain.Rancangan,'silo',skip_silo)
  m.setattr(chain,'rancang',legacy_plan)
  result,_=await save(db,w,10000)
 return result

async def test_lengkapi_bahan_tanpa_mengulang_pengembalian_stok_atau_transfer(pg,rantai,monkeypatch):
 w=rantai
 async with pg() as db:
  legacy=await legacy_edit(db,w,monkeypatch)
  assert (await db.get(InternalTransfer,w['transfer'])).berat_kg==10000
  assert await total(db,w['pol'])==D('22477.5')
  u=await db.get(User,w['user']);ctx=await umum.context(db,user=u,ident=w['root'])
  assert ctx['pending_chain_repair']
  before=await sidik(db);body=await req(db,w,10000)
  review=await umum.inspect(db,user=u,ident=w['root'],req=body)
  assert await sidik(db)==before
  chain=review['plan']['pk_chain']
  assert chain['repair_of']==[legacy['event_id']] and chain['flows']==[]
  assert chain['transfers']==chain['intakes']==[]
  assert review['plan']['balances_before']==review['plan']['balances_after']
  result,body=await save(db,w,10000)
  assert await total(db,w['pol'])==D('19977.5')
  assert (await db.get(InternalTransfer,w['transfer'])).berat_kg==10000
  assert (await db.get(PkGudang2Intake,w['intake'])).berat_kg==10000
  source=(await ledger.baca(db))[w['sources'][0]]
  assert not source.masalah and source.stok.saldo(w['jasa'])==2500
  assert not (await umum.context(db,user=u,ident=w['root']))['pending_chain_repair']
  again=await umum.save(db,user=u,ident=w['root'],req=body)
  assert again['event_id']==result['event_id']
  assert await total(db,w['pol'])==D('19977.5')

async def test_perbaikan_tertinggal_harus_diselesaikan_sebelum_jumlah_diubah_lagi(pg,rantai,monkeypatch):
 w=rantai
 async with pg() as db:
  await legacy_edit(db,w,monkeypatch)
  body=await req(db,w,9000)
  with pytest.raises(umum.InventoryError,match='jumlah kepemilikan tetap'):
   await umum.inspect(db,user=await db.get(User,w['user']),ident=w['root'],req=body)

async def test_penyesuaian_melalui_endpoint_app_dari_26177_5_ke_23677_5(pg,rantai,monkeypatch):
 from app.models import Silo
 from app.penggilingan.gudang2.service import _add_intake
 from tests.pg.test_riwayat_giling import _klien
 from tests.pg.formulir import cap_formulir
 import uuid
 w=rantai
 async with pg() as db:
  await legacy_edit(db,w,monkeypatch)
  u=await db.get(User,w['user'])
  await _add_intake(db,user=u,sumber_tipe='beli_luar',tujuan='A',berat_kg=2500,hpp_per_kg=0,tanggal=now_local().date(),jam=None)
  extra=Silo(nama_silo='Silo Tambahan Uji',warehouse_id=w['warehouses'][1],jenis_isi='pk',status='dipakai')
  db.add(extra);await db.flush()
  await _add_intake(db,user=u,sumber_tipe='beli_luar',tujuan=extra.nama_silo,berat_kg=1200,hpp_per_kg=0,tanggal=now_local().date(),jam=None)
  db.add(PolishingSiloUsage(polishing_process_id=w['pol'],silo_id=extra.id,awal_tetap_kg=1200))
  await db.commit();assert await total(db,w['pol'])==D('26177.5')
 async with await _klien(pg,peran='admin') as c:
  context=(await c.get('/api/kepemilikan/'+str(w['root']))).json();assert context['pending_chain_repair']
  body=dict(mode='ubah',quantity=10000,customer=None,source_ids=[],reason='Lengkapi bahan tanpa mengulang stok',baseline=context['baseline'],key=uuid.uuid4().hex)
  r=await c.post('/api/kepemilikan/'+str(w['root'])+'/periksa',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
  assert r.status_code==200,r.text
  plan=r.json()['plan'];assert plan['pk_moves']==[] and plan['pk_chain']['flows']==[]
  assert D(plan['pk_chain']['processes'][0]['bahan_after'])==D('23677.5')
  body.update(review=r.json()['review'],confirm=True)
  r=await c.post('/api/kepemilikan/'+str(w['root'])+'/simpan',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
  assert r.status_code==200,r.text
 async with pg() as db:
  assert await total(db,w['pol'])==D('23677.5')
  assert (await ledger.baca(db))[w['sources'][0]].stok.saldo(w['jasa'])==2500
