"""Penyelesaian asli: bacaan mesin, fase, kegagalan parsial dan izin efektif."""
from datetime import timedelta
from decimal import Decimal,ROUND_HALF_UP
import os,json
from pathlib import Path
import pytest
from sqlalchemy import select,func
from tests.pg.test_proses_aktif_detail import pengeringan,dryer_pabrik
from tests.pg.test_form_kadar_air import fakta as fakta_ukur,post
from tests.pg.test_riwayat_giling import _klien

pytestmark=pytest.mark.asyncio

async def fakta(pg,p):
 from app.models import DryingLot,DryingCoolingLog
 from app.penggilingan.gudang1.services import drying as dr
 from hmu_core.proses_db import ProsesTerpadu
 f=await fakta_ukur(pg,p)
 async with pg() as db:
  lot=await db.get(DryingLot,p['id'])
  f.update(akhir=lot.waktu_selesai_pengeringan,mulai=lot.waktu_mulai_pengeringan,dingin=lot.waktu_selesai_pendinginan,
   dryer=lot.dryer_id,jasa=lot.jasa_id,beban=await dr.dryer_load_kg(db),
   cooling=[(x.waktu,x.catatan,x.input_by) for x in (await db.scalars(select(DryingCoolingLog).where(DryingCoolingLog.drying_lot_id==lot.id).order_by(DryingCoolingLog.id))).all()],
   bersama=[(x.tabel_sumber,x.status,x.waktu_selesai,x.metadata_domain) for x in (await db.scalars(select(ProsesTerpadu).where(ProsesTerpadu.id_sumber==str(lot.id)).order_by(ProsesTerpadu.id))).all()])
 return f

@pytest.mark.parametrize('nilai',[None,0,-1,100.1,'NaN','Infinity','abc'])
async def test_penolakan_sebelum_penulisan(pg,pengeringan,nilai):
 before=await fakta(pg,pengeringan)
 async with await _klien(pg,peran='admin') as c:
  r=await post(c,'selesai-pengeringan',{'kode_lot':pengeringan['kode'],'kadar_air':nilai});assert r.status_code in (400,422),r.text
 assert await fakta(pg,pengeringan)==before

@pytest.mark.parametrize('kode',['','PGR-TIDAK-ADA'])
async def test_lot_tidak_sah(pg,pengeringan,kode):
 before=await fakta(pg,pengeringan)
 async with await _klien(pg,peran='admin') as c:
  assert (await post(c,'selesai-pengeringan',{'kode_lot':kode,'kadar_air':14})).status_code==400
  assert (await c.get('/api/actions/ringkasan-selesai-pengeringan',params={'kode_lot':kode})).status_code==400
 assert await fakta(pg,pengeringan)==before

@pytest.mark.parametrize('nilai,target',[(15,13),(12.2,13),(13.4567,13),(100,13),(16,None)])
async def test_selesai_mesin_saja_idempoten_tidak_memindah_stok(pg,pengeringan,nilai,target):
 from app.models import DryingLot,User
 from app.penggilingan.gudang1.services import drying as dr
 async with pg() as db:
  lot=await db.get(DryingLot,pengeringan['id']);lot.target_kadar_air=target;await db.commit()
 before=await fakta(pg,pengeringan)
 async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
  r=await post(c,'selesai-pengeringan',{'kode_lot':pengeringan['kode'],'kadar_air':nilai});assert r.status_code==200,r.text
  after=await fakta(pg,pengeringan)
  assert after['status']=='selesai' and after['target']==target and after['akhir'] is not None
  assert len(after['logs'])==len(before['logs'])+1 and after['logs'][-1][:6]==(None,float(Decimal(str(nilai)).quantize(Decimal('.01'),rounding=ROUND_HALF_UP)),None,None,None,None)
  assert after['logs'][:-1]==before['logs'] and len(after['cooling'])==1 and after['dingin'] is None
  assert after['pendinginan']==str(after['akhir']) and after['cooling'][0][0]==after['akhir']
  for k in ['dryer','jasa','stok_silo','beban']:assert after[k]==before[k]
  assert after['beban']==8000
  assert any(x[0]=='drying_lots' and x[1]=='selesai' and x[3].get('kadar_air_akhir')==nilai for x in after['bersama'])
  assert any(x[0]=='drying_cooling' and x[1]=='berjalan' for x in after['bersama'])
  d=(await c.get('/api/actions/ringkasan-selesai-pengeringan',params={'kode_lot':pengeringan['kode']})).json()
  assert not d['dapat_diselesaikan'] and d['status']=='selesai' and d['tes_terakhir']=='18,0%'
  assert d['durasi']==f"{dr._hours(after['akhir'],after['mulai']):.1f} jam".replace('.',',')
  assert d['mesin_terakhir']==f'{nilai:.1f}%'.replace('.',',')
  # Pengulangan lewat endpoint dan pemanggil service lama tidak mengoreksi bacaan.
  assert (await post(c,'selesai-pengeringan',{'kode_lot':pengeringan['kode'],'kadar_air':19})).status_code==200
  assert (await post(c,'selesai-pengeringan',{'kode_lot':pengeringan['kode']})).status_code==200
  async with pg() as db:await dr.finish_drying(db,user=await db.get(User,pengeringan['user']),kode_lot=pengeringan['kode'])
  assert await fakta(pg,pengeringan)==after
  h=await c.get('/proses-aktif/pengeringan/'+pengeringan['kode']);assert h.url.path.endswith('/pendinginan/'+pengeringan['kode'])
  assert 'buka=selesai_pengeringan' not in h.text

async def test_jeda_ditutup_durasi_tetap_waktu_berlalu(pg,pengeringan):
 from app.models import User,DryingLot,JedaProses
 from app.database import now_local
 from app.penggilingan.gudang1.services import drying as dr,jeda
 async with pg() as db:
  u=await db.get(User,pengeringan['user']);lot=await db.get(DryingLot,pengeringan['id']);lot.waktu_mulai_pengeringan=now_local()-timedelta(hours=3);await db.commit()
  await jeda.hentikan(db,user=u,jenis='pengeringan',kode=lot.kode_lot,sebab='Listrik padam')
 async with await _klien(pg,peran='admin') as c:
  d=(await c.get('/api/actions/ringkasan-selesai-pengeringan',params={'kode_lot':pengeringan['kode']})).json();assert d['status']=='dijeda' and d['durasi']=='3,0 jam'
  assert (await post(c,'selesai-pengeringan',{'kode_lot':pengeringan['kode'],'kadar_air':15})).status_code==200
 async with pg() as db:
  assert await jeda.jeda_terbuka(db,'pengeringan',pengeringan['id']) is None
  assert (await db.scalar(select(JedaProses).where(JedaProses.drying_lot_id==pengeringan['id']))).selesai is not None

async def test_belum_mulai_dan_urutan_waktu_lama(pg,pengeringan):
 from app.models import User,DryingLot
 from app.penggilingan.gudang1.services import drying as dr
 before=await fakta(pg,pengeringan)
 async with pg() as db:
  lot=await db.get(DryingLot,pengeringan['id']);w=lot.waktu_mulai_pengeringan-timedelta(days=1)
  with pytest.raises(dr.DryingError,match='lebih awal'):
   await dr.finish_drying(db,user=await db.get(User,pengeringan['user']),kode_lot=lot.kode_lot,kadar_air_akhir=15,tanggal=w.date(),jam=w.timetz())
 assert await fakta(pg,pengeringan)==before
 async with pg() as db:
  lot=await db.get(DryingLot,pengeringan['id']);lot.status='di_dryer';await db.commit()
 before=await fakta(pg,pengeringan)
 async with await _klien(pg,peran='admin') as c:
  assert (await post(c,'selesai-pengeringan',{'kode_lot':pengeringan['kode'],'kadar_air':15})).status_code==400
  assert not (await c.get('/api/actions/ringkasan-selesai-pengeringan',params={'kode_lot':pengeringan['kode']})).json()['dapat_diselesaikan']
 assert await fakta(pg,pengeringan)==before

async def test_gagal_setelah_pengukuran_commit(pg,pengeringan,monkeypatch):
 from app.services import proses_bersama
 from app.penggilingan.gudang1.services import drying as dr
 async def gagal(*a,**kw):raise dr.DryingError('Uji kegagalan penutupan setelah bacaan tersimpan')
 before=await fakta(pg,pengeringan)
 monkeypatch.setattr(proses_bersama,'tutup_proses_bersama',gagal)
 async with await _klien(pg,peran='admin') as c:
  r=await post(c,'selesai-pengeringan',{'kode_lot':pengeringan['kode'],'kadar_air':15});assert r.status_code==400
  d=(await c.get('/api/actions/ringkasan-selesai-pengeringan',params={'kode_lot':pengeringan['kode']})).json()
 after=await fakta(pg,pengeringan)
 assert len(after['logs'])==len(before['logs'])+1 and after['logs'][-1][1]==15
 assert after['status']=='proses' and after['akhir'] is None and not after['cooling']
 assert d['jumlah_log']==len(after['logs']) and d['mesin_terakhir']=='15,0%' and d['dapat_diselesaikan']

@pytest.mark.parametrize('peran,view,izin',[('operator',None,True),('admin',None,True),('superadmin',None,True),('admin','operator:g1',True),('operator','operator:g2',False),('admin','operator:g2',False),('superadmin','operator:g2',False),('staff',None,False)])
async def test_akses_menu_konteks_sumber_dan_aksi(pg,pengeringan,peran,view,izin):
 from app.web.lihat_sebagai import NAMA_KUKI
 async with await _klien(pg,peran=peran,gudang='Gudang 1') as c:
  if view:c.cookies.set(NAMA_KUKI,view)
  for url,params in [('/api/actions/drying-active',{}),('/api/actions/ringkasan-selesai-pengeringan',{'kode_lot':pengeringan['kode']})]:
   r=await c.get(url,params=params);assert r.status_code==(200 if izin else 403),r.text
  menu=(await c.get('/api/actions/menu')).json();assert any(x['id']=='selesai_pengeringan' for x in menu)==izin
  r=await post(c,'selesai-pengeringan',{'kode_lot':pengeringan['kode'],'kadar_air':15});assert r.status_code==(200 if izin else 403),r.text

async def test_konteks_tidak_menulis_titipan_ref_mesin_tidak_hapus_tes(pg,pengeringan):
 from app.models import DryingLot,Pelanggan,Jasa,User
 from app.penggilingan.gudang1.services import drying as dr
 async with pg() as db:
  p=Pelanggan(nama_pelanggan='Pelanggan pengeringan uji');db.add(p);await db.flush();j=Jasa(kode='JAS-UJI-SELESAI',pelanggan_id=p.id);db.add(j);await db.flush()
  lot=await db.get(DryingLot,pengeringan['id']);lot.jasa_id=j.id;lot.target_kadar_air=None;await db.commit()
  await dr.log_moisture(db,user=await db.get(User,pengeringan['user']),kode_lot=lot.kode_lot,indikator=14.2)
 before=await fakta(pg,pengeringan)
 async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
  r=await c.get('/api/actions/ringkasan-selesai-pengeringan',params={'kode_lot':pengeringan['kode']});d=r.json()
  assert r.headers['cache-control']=='no-store' and d['pemilik']=='JAS-UJI-SELESAI Pelanggan pengeringan uji' and d['kepemilikan']=='Titipan jasa'
  assert d['target'] is None and d['target_teks']=='Belum tercatat'
  assert d['mesin_terakhir']=='14,2%' and d['tes_terakhir']=='18,0%' and d['mesin_waktu'] and d['tes_waktu']
  if os.environ.get('UJI_SELESAI_SEED'):Path('/tmp/selesai-session.json').write_text(json.dumps({'kode':pengeringan['kode'],'id':pengeringan['id'],'cookies':{x.name:x.value for x in c.cookies.jar}}))
 assert await fakta(pg,pengeringan)==before

async def test_csrf_portal_dan_anonim_tetap_ditolak(pg,pengeringan):
 import httpx
 from app.main import app
 from app.models import Pelanggan
 from app.models.portal import PortalAccount
 from app.web.portal.security import COOKIE,issue
 from app.web import csrf,security
 before=await fakta(pg,pengeringan)
 async with await _klien(pg,peran='admin') as c:
  assert (await c.post('/api/actions/selesai-pengeringan',json={'kode_lot':pengeringan['kode'],'kadar_air':15})).status_code==403
 async with pg() as db:
  p=Pelanggan(nama_pelanggan='Portal uji selesai');db.add(p);await db.flush()
  akun=PortalAccount(username='uji-selesai-portal',pelanggan_id=p.id,password_hash=security.hash_sandi('uji-aman-123'),active=True,token_version=1);db.add(akun);await db.commit()
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
  for portal in [False,True]:
   if portal:c.cookies.set(COOKIE,issue(akun));c.cookies.set(csrf.NAMA_COOKIE,csrf.terbitkan_baru())
   r=await c.get('/api/actions/ringkasan-selesai-pengeringan',params={'kode_lot':pengeringan['kode']})
   assert r.status_code in (401,403) and pengeringan['kode'] not in r.text
   assert (await post(c,'selesai-pengeringan',{'kode_lot':pengeringan['kode'],'kadar_air':15})).status_code in (401,403)
 assert await fakta(pg,pengeringan)==before

async def test_notifikasi_dan_pelaku_audit(pg,pengeringan):
 from app.models import Notification,ActivityLog,User
 async with pg() as db:
  n=Notification(tipe='pengeringan_telat',record_id=pengeringan['id'],status='baru',pesan='Uji keterlambatan');db.add(n);await db.commit();nid=n.id
 async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
  async with pg() as db:pelaku=await db.scalar(select(User.id).where(User.nama=='Uji operator').order_by(User.id.desc()).limit(1))
  assert (await post(c,'selesai-pengeringan',{'kode_lot':pengeringan['kode'],'kadar_air':15})).status_code==200
 async with pg() as db:
  assert (await db.get(Notification,nid)).status=='selesai'
  audit=(await db.scalars(select(ActivityLog).where(ActivityLog.table_name=='drying_lots',ActivityLog.record_id==pengeringan['id'],ActivityLog.field_name=='status',ActivityLog.new_value=='selesai'))).all()
  assert audit and all(x.changed_by==pelaku for x in audit)
  from app.models import DryingMoistureLog
  akhir=await db.scalar(select(DryingMoistureLog).where(DryingMoistureLog.drying_lot_id==pengeringan['id']).order_by(DryingMoistureLog.id.desc()).limit(1))
  assert akhir.input_by==pelaku

async def test_titipan_sejak_awal_tetap_pemilik_saat_pendinginan(pg,dryer_pabrik):
 from tests.pg.test_riwayat_pengeringan import _batch_basah
 from app.models import Pelanggan,Jasa,PurchaseBatch,DryingLot,User,SiloStorage
 from app.penggilingan.gudang1.services import drying as dr
 from hmu_core.proses_db import ProsesTerpadu
 kode_batch=await _batch_basah(pg,dryer_pabrik,8000)
 async with pg() as db:
  pemilik=Pelanggan(nama_pelanggan='Pemilik titipan pengeringan');db.add(pemilik);await db.flush()
  jasa=Jasa(kode='JAS-UJI-TITIPAN',pelanggan_id=pemilik.id);db.add(jasa);await db.flush();jid=jasa.id
  batch=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch==kode_batch));batch.supplier_id=None;batch.jasa_id=jid;await db.commit()
  u=await db.get(User,dryer_pabrik['user']);await dr.masuk_dryer(db,user=u,kode_batch_list=[kode_batch]);r=await dr.start_drying(db,user=u,target_kadar_air=13);kode=r.lot.kode_lot;lid=r.lot.id
 async with await _klien(pg,peran='admin') as c:
  sebelum=(await c.get('/api/actions/ringkasan-selesai-pengeringan',params={'kode_lot':kode})).json()
  assert sebelum['kepemilikan']=='Titipan jasa' and 'Pemilik titipan' in sebelum['pemilik']
  assert (await post(c,'selesai-pengeringan',{'kode_lot':kode,'kadar_air':15})).status_code==200
  sesudah=(await c.get('/api/actions/ringkasan-selesai-pengeringan',params={'kode_lot':kode})).json()
  assert sesudah['pemilik']==sebelum['pemilik'] and sesudah['bahan']==sebelum['bahan']
 async with pg() as db:
  lot=await db.get(DryingLot,lid);assert lot.jasa_id==jid and lot.waktu_selesai_pendinginan is None
  batch=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch==kode_batch));assert batch.jasa_id==jid and batch.supplier_id is None
  bersama=(await db.scalars(select(ProsesTerpadu).where(ProsesTerpadu.id_sumber==str(lid)))).all()
  assert bersama and all(x.jenis_pemilik=='jasa' and str(x.id_pemilik)==str(jid) for x in bersama)
  assert await dr.dryer_load_kg(db)==8000 and await db.scalar(select(func.count()).select_from(SiloStorage))==0
