"""Koreksi AM-PK mengikuti bobot fisik hingga bahan sosoh, lewat app/service."""
import copy,uuid
from decimal import Decimal as D
import pytest
from sqlalchemy import select,func
from app.database import now_local
from app.models import (User,Silo,MillingProcess,MillingProcessVerification,
    InternalTransfer,PkGudang2Intake,PolishingProcess,PolishingSiloUsage,PolishingOutputLog,Peristiwa)
from app.models.peristiwa import ProyeksiTransferPk,ProyeksiPkMasukG2
from app.services import kepemilikan as umum,pk_persediaan as ledger,pk_kepemilikan as pk
from app.services.transfer import create_internal_transfer
from app.penggilingan.gudang2.service import _add_intake,hitung_stok_silo
from app.penggilingan.gudang2.polishing import mulai_penyosohan
from tests.pg.test_pk_kepemilikan import world,initial
from tests.pg.test_masuk_detail_timbang import sidik
pytestmark=pytest.mark.asyncio

@pytest.fixture
async def rantai(pg,world):
 w=world
 async with pg() as db:
  u=await db.get(User,w['user']);p=await db.get(MillingProcess,1)
  p.jasa_id=w['jasa'];p.berat_gabah_masuk_kg=20000
  v=await db.scalar(select(MillingProcessVerification).where(MillingProcessVerification.milling_process_id==p.id));v.berat_output_final_kg=12500
  await db.commit()
  result,_=await initial(db,w,amount=12500,dari=w['jasa'],ke=None)
  a=await create_internal_transfer(db,user=u,kode_proses=p.kode_proses+'|pemilik=pabrik',lokasi_tujuan='A',berat=12500)
  await _add_intake(db,user=u,sumber_tipe='beli_luar',tujuan='B',berat_kg=9977.5,hpp_per_kg=0,tanggal=now_local().date(),jam=None)
  r=await mulai_penyosohan(db,user=u,nama_silos=['A','B'])
  for jenis,n in [('sayur',13550),('premium',2150)]:
   db.add(PolishingOutputLog(polishing_process_id=r.proc.id,jenis=jenis,berat_kg=n,waktu_update=now_local(),input_by=u.id))
  await db.commit()
  it=await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.internal_transfer_id==a.transfer.id))
  return dict(**w,root=result['id'],transfer=a.transfer.id,intake=it.id,pol=r.proc.id,silo=a.transfer.silo_id)

async def req(db,w,amount,mode='ubah'):
 u=await db.get(User,w['user']);ctx=await umum.context(db,user=u,ident=w['root'])
 return dict(mode=mode,quantity=amount,customer=None,source_ids=[],reason='Betulkan kelebihan catat melalui aplikasi',baseline=ctx['baseline'],key=uuid.uuid4().hex)

async def save(db,w,amount,mode='ubah'):
 u=await db.get(User,w['user']);body=await req(db,w,amount,mode)
 review=await umum.inspect(db,user=u,ident=w['root'],req=body)
 body.update(review=review['review'],confirm=True)
 result=await umum.save(db,user=u,ident=w['root'],req=body);await db.commit()
 return result,body

async def total(db,pid):
 rows=(await db.scalars(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==pid))).all()
 return sum((x.berat_terpakai_kg if x.berat_akhir_kg is not None else x.berat_awal_kg+x.berat_masuk_kg) for x in rows)

async def test_pratinjau_koreksi_12500_ke_10000_tidak_menulis_dan_menunjukkan_bahan_sosoh(pg,rantai):
 w=rantai
 async with pg() as db:
  u=await db.get(User,w['user']);body=await req(db,w,10000);before=await sidik(db)
  review=await umum.inspect(db,user=u,ident=w['root'],req=body)
  assert await sidik(db)==before
  p=review['plan'];chain=p['pk_chain']
  assert p['before']['quantity']=='12500' and D(p['after']['quantity'])==10000
  assert D(chain['transfers'][0]['after']['berat_kg'])==10000
  assert D(chain['intakes'][0]['after']['berat_kg'])==10000
  assert D(chain['processes'][0]['bahan_before'])==D('22477.5')
  assert D(chain['processes'][0]['bahan_after'])==D('19977.5')
  assert D(chain['processes'][0]['hasil_tercatat'])==15700
  assert not chain['warnings']

async def test_simpan_idempoten_audit_bahan_dan_replay_proyeksi(pg,rantai):
 from app.services import peristiwa as buku
 w=rantai
 async with pg() as db:
  old=copy.deepcopy((await db.get(Peristiwa,w['root'])).muatan)
  result,body=await save(db,w,10000)
  n=await db.scalar(select(func.count()).select_from(Peristiwa))
  repeat=await umum.save(db,user=await db.get(User,w['user']),ident=w['root'],req=body)
  assert repeat['event_id']==result['event_id']
  assert await db.scalar(select(func.count()).select_from(Peristiwa))==n
  t=await db.get(InternalTransfer,w['transfer']);it=await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.id==w['intake']).execution_options(termasuk_dibatalkan=True))
  assert t.berat_kg==it.berat_kg==10000
  assert await total(db,w['pol'])==D('19977.5')
  source=(await ledger.baca(db))[w['sources'][0]]
  assert not source.masalah and source.stok.saldo(w['jasa'])==2500 and source.stok.saldo(None)==0
  assert (await db.get(Peristiwa,w['root'])).muatan==old
  await buku.bangun_ulang(db)
  assert (await db.get(ProyeksiTransferPk,t.peristiwa_id)).berat_kg==10000
  assert (await db.get(ProyeksiPkMasukG2,it.peristiwa_id)).berat_kg==10000

async def test_koreksi_ulang_dan_pembatalan_memulihkan_seluruh_pk_tanpa_menimpa_hasil(pg,rantai):
 w=rantai
 async with pg() as db:
  await save(db,w,10000)
  await save(db,w,9000)
  source=(await ledger.baca(db))[w['sources'][0]]
  assert source.stok.saldo(w['jasa'])==3500 and not source.masalah
  result,_=await save(db,w,None,'batal')
  t=await db.get(InternalTransfer,w['transfer']);it=await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.id==w['intake']).execution_options(termasuk_dibatalkan=True))
  assert t.status=='dibatalkan' and it.dibatalkan_pada is not None
  assert await total(db,w['pol'])==D('9977.5')
  assert result['plan']['pk_chain']['warnings']
  source=(await ledger.baca(db))[w['sources'][0]]
  assert not source.masalah and source.stok.saldo(w['jasa'])==12500 and source.stok.saldo(None)==0
  assert await db.scalar(select(func.sum(PolishingOutputLog.berat_kg)).where(PolishingOutputLog.polishing_process_id==w['pol']))==15700

async def test_perubahan_bahan_atau_hasil_setelah_pratinjau_menolak_simpan_tanpa_mutasi(pg,rantai):
 w=rantai
 async with pg() as db:
  u=await db.get(User,w['user']);body=await req(db,w,10000)
  review=await umum.inspect(db,user=u,ident=w['root'],req=body)
  body.update(review=review['review'],confirm=True)
  db.add(PolishingOutputLog(polishing_process_id=w['pol'],jenis='sayur',berat_kg=1,waktu_update=now_local(),input_by=u.id));await db.commit()
  before=await sidik(db)
  with pytest.raises(umum.InventoryError,match='Rancangan berubah'):
   await umum.save(db,user=u,ident=w['root'],req=body)
  assert await sidik(db)==before

async def test_alur_http_app_periksa_tidak_menulis_simpan_koreksi_dan_hak_akses(pg,rantai):
 from tests.pg.test_riwayat_giling import _klien
 from tests.pg.formulir import cap_formulir
 w=rantai
 async with await _klien(pg,peran='admin') as c:
  async with pg() as db:before=await sidik(db)
  page=await c.get('/kepemilikan/'+str(w['root']));assert page.status_code==200
  context=(await c.get('/api/kepemilikan/'+str(w['root']))).json()
  body=dict(mode='ubah',quantity=10000,customer=None,source_ids=[],reason='Koreksi melalui app',baseline=context['baseline'],key=uuid.uuid4().hex)
  review=await c.post('/api/kepemilikan/'+str(w['root'])+'/periksa',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
  assert review.status_code==200,review.text
  assert D(review.json()['plan']['pk_chain']['processes'][0]['bahan_after'])==D('19977.5')
  async with pg() as db:assert await sidik(db)==before
  body.update(review=review.json()['review'],confirm=True)
  r=await c.post('/api/kepemilikan/'+str(w['root'])+'/simpan',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
  assert r.status_code==200,r.text
 async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
  assert (await c.get('/api/kepemilikan/'+str(w['root']))).status_code==403
 async with pg() as db:
  from app.services.jasa import sisa_jasa
  from app.services.stok import pk_gudang1
  cards=await pk_gudang1(db)
  assert any(x.jasa_id==w['jasa'] and x.tersedia==2500 for x in cards)
  assert (await sisa_jasa(db,w['jasa'])).pk_g1_kg==2500

async def test_kegagalan_sinkron_membatalkan_seluruh_perubahan_dan_audit(pg,rantai,monkeypatch):
 import app.services.pk_koreksi_rantai as chain
 w=rantai
 async with pg() as db:
  u=await db.get(User,w['user']);body=await req(db,w,10000)
  review=await umum.inspect(db,user=u,ident=w['root'],req=body)
  body.update(review=review['review'],confirm=True)
  before=await sidik(db)
  async def fail(*args,**kwargs):raise RuntimeError('Simulasi gagal sinkron')
  monkeypatch.setattr(chain,'sinkron_bahan',fail)
  with pytest.raises(RuntimeError,match='gagal sinkron'):
   await umum.save(db,user=u,ident=w['root'],req=body)
  await db.rollback()
  assert await sidik(db)==before

async def test_tumpukan_yang_sudah_masuk_silo_bisa_dikoreksi_dan_dibatalkan(pg,world):
 from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo
 w=world
 async with pg() as db:
  initial_result,_=await initial(db,w,1,400)
  w={**w,'root':initial_result['id']}
  u=await db.get(User,w['user'])
  silo=await db.scalar(select(Silo).where(Silo.warehouse_id==w['warehouses'][1],Silo.nama_silo.in_(['A','Silo A'])))
  await pindah_tumpukan_ke_silo(db,user=u,intake_id=int(w['sources'][1].split(':')[1]),nama_silo=silo.nama_silo,berat=300,hasil_timbang=True,pemilik_id=w['jasa'])
  await save(db,w,200)
  source=(await ledger.baca(db))[w['sources'][1]]
  assert not source.masalah and source.stok.saldo(None)==800 and source.stok.saldo(w['jasa'])==0
  await save(db,w,None,'batal')
  source=(await ledger.baca(db))[w['sources'][1]]
  assert not source.masalah and source.stok.saldo(None)==1000 and source.stok.saldo(w['jasa'])==0

async def test_tambahan_koreksi_setelah_penurunan_tidak_merusak_jejak_fifo(pg,rantai):
 w=rantai
 async with pg() as db:
  await save(db,w,10000)
  await save(db,w,11000)
  source=(await ledger.baca(db))[w['sources'][0]]
  assert not source.masalah and source.stok.saldo(None)==1000 and source.stok.saldo(w['jasa'])==1500
  await save(db,w,None,'batal')
  source=(await ledger.baca(db))[w['sources'][0]]
  assert not source.masalah and source.stok.saldo(w['jasa'])==12500

async def test_transfer_setelah_koreksi_rantai_tidak_bisa_dibatalkan_terpisah(pg,rantai):
 from app.services.undo import _undo_transfer,UndoError
 from app.services.transfer import alasan_koreksi_transfer
 w=rantai
 async with pg() as db:
  await save(db,w,10000);before=await sidik(db)
  assert 'AM-PK-'+str(w['root']) in await alasan_koreksi_transfer(db,w['transfer'])
  with pytest.raises(UndoError,match='Gunakan koreksi'):
   await _undo_transfer(db,w['transfer'])
  assert await sidik(db)==before

async def test_bahan_proses_selesai_dan_sisa_silo_dihitung_ulang(pg,rantai):
 w=rantai
 async with pg() as db:
  p=await db.get(PolishingProcess,w['pol']);p.status='selesai';p.waktu_selesai=now_local()
  for u in (await db.scalars(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==p.id))).all():
   u.berat_akhir_kg=0;u.terpakai_lama_kg=u.berat_awal_kg+u.berat_masuk_kg
  await db.commit()
  await save(db,w,10000)
  assert await total(db,w['pol'])==D('19977.5')
  assert (await db.get(PolishingProcess,w['pol'])).status=='selesai'

@pytest.mark.parametrize('selama',[False,True])
async def test_transfer_lewat_tumpukan_dan_bahan_sebelum_atau_selama_sosoh(pg,world,selama):
 from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo
 w=world
 async with pg() as db:
  u=await db.get(User,w['user']);proc=await db.get(MillingProcess,1);proc.jasa_id=w['jasa'];proc.berat_gabah_masuk_kg=20000
  v=await db.scalar(select(MillingProcessVerification).where(MillingProcessVerification.milling_process_id==1));v.berat_output_final_kg=12500;await db.commit()
  original,_=await initial(db,w,amount=12500,dari=w['jasa'],ke=None);w={**w,'root':original['id']}
  tr=await create_internal_transfer(db,user=u,kode_proses=proc.kode_proses+'|pemilik=pabrik',lokasi_tujuan='ditumpuk',berat=12500)
  it=await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.internal_transfer_id==tr.transfer.id))
  await _add_intake(db,user=u,sumber_tipe='beli_luar',tujuan='B',berat_kg=9977.5,hpp_per_kg=0,tanggal=now_local().date(),jam=None)
  if selama:
   await _add_intake(db,user=u,sumber_tipe='beli_luar',tujuan='A',berat_kg=500,hpp_per_kg=0,tanggal=now_local().date(),jam=None)
   process=await mulai_penyosohan(db,user=u,nama_silos=['A','B'])
  move=await pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo='A',berat=12500,hasil_timbang=True,pemilik_id=None)
  if not selama:process=await mulai_penyosohan(db,user=u,nama_silos=['A','B'])
  await db.commit()
  await save(db,w,10000)
  assert await total(db,process.proc.id)==D('19977.5')+(500 if selama else 0)
  source=(await ledger.baca(db))[w['sources'][0]]
  assert not source.masalah and source.stok.saldo(w['jasa'])==2500
  assert not (await ledger.baca(db))['tumpukan:'+str(it.id)].masalah
  await save(db,w,None,'batal')
  assert await total(db,process.proc.id)==D('9977.5')+(500 if selama else 0)
  source=(await ledger.baca(db))[w['sources'][0]]
  assert not source.masalah and source.stok.saldo(w['jasa'])==12500
