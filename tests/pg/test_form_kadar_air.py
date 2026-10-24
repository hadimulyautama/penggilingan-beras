"""Kontrak pengukuran/target asli dan pratinjau baca saja, pada PG terisolasi."""
import os,json
from pathlib import Path
import pytest
from sqlalchemy import select,func
from tests.pg.test_proses_aktif_detail import pengeringan,dryer_pabrik
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir
pytestmark=pytest.mark.asyncio

async def post(c,path,isi):
 return await c.post('/api/actions/'+path,json=isi,headers={'X-CSRF-Token':cap_formulir(c)})

async def fakta(pg,p):
 from app.models import DryingLot,DryingMoistureLog,ActivityLog,SiloStorage
 async with pg() as db:
  lot=await db.get(DryingLot,p['id'])
  logs=(await db.scalars(select(DryingMoistureLog).where(DryingMoistureLog.drying_lot_id==lot.id).order_by(DryingMoistureLog.id))).all()
  audit=(await db.scalars(select(ActivityLog).where(ActivityLog.record_id==lot.id,ActivityLog.table_name.in_(['drying_moisture_logs','drying_lots'])).order_by(ActivityLog.id))).all()
  return {'target':float(lot.target_kadar_air) if lot.target_kadar_air is not None else None,'status':lot.status,'pendinginan':str(lot.waktu_mulai_pendinginan),'stok_silo':await db.scalar(select(func.count()).select_from(SiloStorage)),
   'logs':[(float(x.kadar_air_tes_manual) if x.kadar_air_tes_manual is not None else None,float(x.kadar_air_indikator) if x.kadar_air_indikator is not None else None,*[float(getattr(x,'kadar_air_tes_'+str(i))) if getattr(x,'kadar_air_tes_'+str(i)) is not None else None for i in range(1,5)],x.input_by,str(x.waktu_update)) for x in logs],
   'audit':[(x.action,x.field_name,x.old_value,x.new_value,x.changed_by) for x in audit]}

@pytest.mark.parametrize('tes,avg', [([18.2],18.2),([18.2,18.8],18.5),([18,19,20],19),([18,19,20,21],19.5)])
async def test_pengukuran_resmi_berulang_tanpa_efek_samping(pg,pengeringan,tes,avg):
 before=await fakta(pg,pengeringan)
 async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
  for _ in range(2):
   r=await post(c,'kadar-air',{'kode_lot':pengeringan['kode'],'tes':tes,'indikator':19})
   assert r.status_code==200,r.text
 after=await fakta(pg,pengeringan)
 assert len(after['logs'])==len(before['logs'])+2
 assert after['logs'][-1][0:2]==(avg,19)
 assert after['logs'][-1][2:6]==tuple(tes+[None]*(4-len(tes)))
 assert after['logs'][-1][6] and after['logs'][-1][7]
 for k in ['target','status','pendinginan','stok_silo']:assert after[k]==before[k]
 assert len(after['audit'])==len(before['audit'])+2

@pytest.mark.parametrize('isi,avg,mesin,sampel',[
 ({'tes':[18.2,18.8],'tes_1':99,'tes_2':100},18.5,None,(18.2,18.8,None,None)),
 ({'tes_1':18,'tes_3':20},19,None,(18,None,20,None)),
 ({'kadar_air':19},None,19,(None,None,None,None)),
 ({'indikator':18,'kadar_air':99},None,18,(None,None,None,None)),
 ({'tes':[100]},100,None,(100,None,None,None)),
 ({'tes':[18],'target_baru':14},18,None,(18,None,None,None))])
async def test_kompatibilitas_backend_lama(pg,pengeringan,isi,avg,mesin,sampel):
 async with await _klien(pg,peran='admin') as c:
  r=await post(c,'kadar-air',{'kode_lot':pengeringan['kode'],**isi});assert r.status_code==200,r.text
 f=await fakta(pg,pengeringan);assert f['logs'][-1][0:6]==(avg,mesin,*sampel)
 assert f['target']==isi.get('target_baru',13)

@pytest.mark.parametrize('tes,indikator', [([],None),([0],None),([-1],None),([101],None),(['NaN'],None),(['Infinity'],None),([18],0),([18],101)])
async def test_validasi_lama_tanpa_menulis(pg,pengeringan,tes,indikator):
 before=await fakta(pg,pengeringan)
 async with await _klien(pg,peran='admin') as c:
  r=await post(c,'kadar-air',{'kode_lot':pengeringan['kode'],'tes':tes,'indikator':indikator});assert r.status_code in (400,422)
 assert await fakta(pg,pengeringan)==before

async def test_target_terpisah_dan_jeda(pg,pengeringan):
 from app.models import User
 from app.penggilingan.gudang1.services import jeda
 from app.services.setelan import target_kadar_air
 async with pg() as db:
  await jeda.hentikan(db,user=await db.get(User,pengeringan['user']),jenis='pengeringan',kode=pengeringan['kode'],sebab='Listrik padam')
 before=await fakta(pg,pengeringan)
 async with pg() as db:globaltarget=await target_kadar_air(db)
 async with await _klien(pg,peran='admin') as c:
  for v in [None,0,-1,101,13]:
   assert (await post(c,'ubah-target',{'kode_lot':pengeringan['kode'],'target':v})).status_code==400
  assert (await post(c,'ubah-target',{'kode_lot':pengeringan['kode'],'target':14})).status_code==200
  target=await fakta(pg,pengeringan)
  assert target['target']==14 and target['logs']==before['logs']
  assert target['audit'][-1][1:4]==('target_kadar_air','13.0','14.0')
  assert (await post(c,'kadar-air',{'kode_lot':pengeringan['kode'],'tes':[12]})).status_code==200
 after=await fakta(pg,pengeringan);assert after['target']==14 and after['status']=='proses'
 async with pg() as db:assert await target_kadar_air(db)==globaltarget
 async with pg() as db:assert await jeda.jeda_terbuka(db,'pengeringan',pengeringan['id'])

@pytest.mark.parametrize('peran,view,izin',[('operator',None,True),('admin',None,True),('superadmin',None,True),('admin','operator:g1',True),('operator','operator:g2',False),('admin','operator:g2',False),('superadmin','operator:g2',False),('staff',None,False)])
async def test_hak_asli_pengukuran_dan_target(pg,pengeringan,peran,view,izin):
 from app.services.seed import seed_master
 from app.web.lihat_sebagai import NAMA_KUKI
 await seed_master()
 async with await _klien(pg,peran=peran,gudang='Gudang 1') as c:
  if view:c.cookies.set(NAMA_KUKI,view)
  for path,isi in [('kadar-air',{'tes':[18]}),('ubah-target',{'target':14})]:
   r=await post(c,path,{'kode_lot':pengeringan['kode'],**isi});assert r.status_code==(200 if izin else 403),r.text

@pytest.mark.parametrize('tes,mesin,sebar,delta,warning', [([18.2],None,None,None,0),([18.2,18.8],19,0.6,0.5,0),([18,19.4999],None,1.4999,None,0),([18,19.5],None,1.5,None,1),([18.2,18.8],20.4999,0.6,1.9999,0),([18.2,18.8],20.5,0.6,2,1),([18.2,18.8],16.5,0.6,-2,1),([18,19,20,21],22,3,2.5,2)])
async def test_pratinjau_resmi_ambang_dan_tanpa_mutasi(pg,pengeringan,tes,mesin,sebar,delta,warning):
 before=await fakta(pg,pengeringan)
 async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
  params=[('kode_lot',pengeringan['kode'])]+[('tes',x) for x in tes]+([] if mesin is None else [('indikator',mesin)])
  r=await c.get('/api/actions/ringkasan-kadar-air',params=params);assert r.status_code==200,r.text
  d=r.json();assert d['rata']==sum(tes)/len(tes)
  assert d['sebar']==(pytest.approx(sebar) if sebar is not None else None)
  assert d['selisih']==(pytest.approx(delta) if delta is not None else None)
  assert len(d['peringatan'])==warning and d['target']==13 and d['pemilik']=='Pabrik'
  assert r.headers['cache-control']=='no-store' and d['bahan']=='8.000 kg'
  if os.environ.get('UJI_KADAR_SEED'):
   Path('/tmp/kadar-session.json').write_text(json.dumps({'kode':pengeringan['kode'],'id':pengeringan['id'],'cookies':{x.name:x.value for x in c.cookies.jar}}))
 assert await fakta(pg,pengeringan)==before

async def test_pratinjau_izin_target_tidak_diketahui_selesai_portal(pg,pengeringan):
 from app.services.seed import seed_master
 from app.models import DryingLot,User
 from app.penggilingan.gudang1.services import drying as dr
 from app.web.lihat_sebagai import NAMA_KUKI
 await seed_master()
 async with pg() as db:
  p=await db.get(DryingLot,pengeringan['id']);p.target_kadar_air=None;await db.commit()
 async with await _klien(pg,peran='admin') as c:
  d=(await c.get('/api/actions/ringkasan-kadar-air',params={'kode_lot':pengeringan['kode']})).json();assert d['target'] is None and d['target_teks']=='Belum tercatat'
  async with pg() as db:await dr.finish_drying(db,user=await db.get(User,pengeringan['user']),kode_lot=pengeringan['kode'],kadar_air_akhir=18)
  before=await fakta(pg,pengeringan)
  assert (await post(c,'kadar-air',{'kode_lot':pengeringan['kode'],'tes':[18]})).status_code==400
  assert (await post(c,'ubah-target',{'kode_lot':pengeringan['kode'],'target':14})).status_code==400
  assert await fakta(pg,pengeringan)==before
 for peran,view in [('operator','operator:g2'),('admin','operator:g2'),('superadmin','operator:g2'),('staff',None)]:
  async with await _klien(pg,peran=peran,gudang='Gudang 1') as c:
   if view:c.cookies.set(NAMA_KUKI,view)
   r=await c.get('/api/actions/ringkasan-kadar-air',params={'kode_lot':pengeringan['kode']});assert r.status_code==403 and pengeringan['kode'] not in r.text

async def test_peringatan_tersimpan_jeda_ukur_dan_notifikasi(pg,pengeringan):
 from app.models import User
 from app.penggilingan.gudang1.services import drying as dr
 async with pg() as db:
  r=await dr.log_moisture(db,user=await db.get(User,pengeringan['user']),kode_lot=pengeringan['kode'],sampel=[18,20],indikator=22)
  assert r.jam_sejak_mulai>=0 and r.jam_sejak_log_sebelumnya>=0
 async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
  h=await c.get('/proses-aktif/pengeringan/'+pengeringan['kode']+'?tab_detail=pengukuran')
  assert 'Sebaran 2.0%' in h.text and 'Mesin membaca +3.0%' in h.text

async def test_csrf_dan_portal_tidak_boleh_mengukur_atau_membaca_konteks(pg,pengeringan):
 import httpx
 from app.main import app
 from app.models import Pelanggan
 from app.models.portal import PortalAccount
 from app.web.portal.security import COOKIE,issue
 from app.web import csrf,security
 before=await fakta(pg,pengeringan)
 async with await _klien(pg,peran='admin') as c:
  for path,isi in [('kadar-air',{'tes':[18]}),('ubah-target',{'target':14})]:
   r=await c.post('/api/actions/'+path,json={'kode_lot':pengeringan['kode'],**isi})
   assert r.status_code==403
 async with pg() as db:
  owner=Pelanggan(nama_pelanggan='Pemilik uji kadar air');db.add(owner);await db.flush()
  akun=PortalAccount(username='uji-kadar-portal',pelanggan_id=owner.id,password_hash=security.hash_sandi('uji-aman-123'),active=True,token_version=1)
  db.add(akun);await db.commit()
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
  c.cookies.set(COOKIE,issue(akun));c.cookies.set(csrf.NAMA_COOKIE,csrf.terbitkan_baru())
  r=await c.get('/api/actions/ringkasan-kadar-air',params={'kode_lot':pengeringan['kode']});assert r.status_code in (401,403) and pengeringan['kode'] not in r.text
  for path,isi in [('kadar-air',{'tes':[18]}),('ubah-target',{'target':14})]:
   assert (await post(c,path,{'kode_lot':pengeringan['kode'],**isi})).status_code in (401,403)
 assert await fakta(pg,pengeringan)==before

async def test_konteks_pemilik_mengikuti_relasi_lot_asli(pg,pengeringan):
 from app.models import Pelanggan,Jasa,DryingLot
 async with pg() as db:
  owner=Pelanggan(nama_pelanggan='Pelanggan uji kadar air dengan nama panjang');db.add(owner);await db.flush()
  jasa=Jasa(kode='JAS-UJI-KADAR',pelanggan_id=owner.id);db.add(jasa);await db.flush()
  lot=await db.get(DryingLot,pengeringan['id']);lot.jasa_id=jasa.id;await db.commit()
 async with await _klien(pg,peran='admin') as c:
  d=(await c.get('/api/actions/ringkasan-kadar-air',params={'kode_lot':pengeringan['kode']})).json()
  assert d['kepemilikan']=='Titipan jasa' and 'Pelanggan uji kadar air' in d['pemilik']
  assert d['kode_lot']==pengeringan['kode'] and d['bahan']=='8.000 kg' and d['target']==13
