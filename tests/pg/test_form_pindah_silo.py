"""Dua field lama: pratinjau tanpa tulisan, saldo, kepemilikan dan balapan nyata."""
import asyncio
from datetime import date
import pytest
import pytest_asyncio
from sqlalchemy import select,func
from tests.pg.test_proses_aktif_detail import pengeringan,dryer_pabrik
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_form_kadar_air import post

pytestmark=pytest.mark.asyncio

@pytest_asyncio.fixture
async def siap(pg,pengeringan):
 from app.models import Silo,User
 from app.penggilingan.gudang1.services import drying as dr
 async with pg() as db:
  u=await db.get(User,pengeringan['user'])
  for nama in ['Silo A','Silo B','Tong Selatan']:
   s=await db.scalar(select(Silo).where(Silo.nama_silo==nama,Silo.warehouse_id==u.default_warehouse_id))
   if s is None:db.add(Silo(nama_silo=nama,warehouse_id=u.default_warehouse_id,status='kosong',kapasitas_ton=1))
   else:s.kapasitas_ton=1
  await db.commit()
  await dr.finish_drying(db,user=u,kode_lot=pengeringan['kode'],kadar_air_akhir=14)
  await dr.finish_cooling(db,user=u,kode_lot=pengeringan['kode'])
 return pengeringan

async def fakta(pg):
 from app.models import DryingLot,PurchaseBatch,Silo,SiloStorage,MillingProcess,MillingProcessSource,Jasa,ActivityLog,DryingCoolingLog
 async with pg() as db:
  return {m.__tablename__:[tuple(row) for row in (await db.execute(select(*m.__table__.c).order_by(m.__table__.c.id))).all()] for m in [DryingLot,PurchaseBatch,Silo,SiloStorage,MillingProcess,MillingProcessSource,Jasa,ActivityLog,DryingCoolingLog]}

async def ringkas(c,p,silo=''):
 r=await c.get('/api/actions/ringkasan-pindah-silo',params={'kode_lot':p['kode'],'silo':silo});assert r.status_code==200,r.text
 assert r.headers['cache-control']=='no-store';return r.json()

async def isi(pg,p,*,jasa=None,kg=3000,huruf='A',kode='GB-SILO-UJI'):
 from app.database import now_local
 from app.models import PurchaseBatch,SiloStorage,Silo
 async with pg() as db:
  from app.models import Supplier
  batch=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch==p['batch']))
  b=PurchaseBatch(kode_batch=kode,supplier_id=(batch.supplier_id or (await db.scalar(select(Supplier.id).limit(1)))) if jasa is None else None,jasa_id=jasa,berat_total_kg=kg,kondisi_gabah='kering',tanggal_pembelian=date.today(),waktu_pembelian=now_local(),input_by=p['user'],sumber_berat='manual',flag_unverified=False,status_batch='di_silo')
  from app.penggilingan.gudang1.services.silo import get_g1_silo
  db.add(b);await db.flush();s=await get_g1_silo(db,huruf)
  row=SiloStorage(silo_id=s.id,purchase_batch_id=b.id,tipe_masuk='langsung_kering',tanggal_masuk=now_local(),input_by=p['user'],status='terisi',jasa_id=jasa);db.add(row);await db.commit();return row.id

async def test_pratinjau_saldo_dikurangi_dan_pindah_satu_kali(pg,siap):
 from app.models import SiloStorage,DryingLot,PurchaseBatch,ActivityLog
 from app.penggilingan.gudang1.services import silo as si,drying as dr
 rid=await isi(pg,siap)
 async with pg() as db:
  row=await db.get(SiloStorage,rid);row.dikemas_kg=700;await db.commit()
 before=await fakta(pg)
 async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
  for _ in range(3):
   d=await ringkas(c,siap,'A');assert d['bobot']=='8.000 kg' and d['tujuan']['isi']=='2.300 kg' and d['tujuan']['sesudah']=='10.300 kg'
   assert len(d['peringatan'])==2 and d['siap'] and d['tujuan']['kapasitas']=='1.000 kg'
  assert await fakta(pg)==before
  r=await post(c,'pindah-silo',{'kode_lot':siap['kode'],'silo':'A'});assert r.status_code==200,r.text
  after=await fakta(pg)
  assert (await post(c,'pindah-silo',{'kode_lot':siap['kode'],'silo':'B'})).status_code==400
  assert await fakta(pg)==after
  assert siap['kode'] not in {x['value'] for x in (await c.get('/api/actions/drying-done')).json()}
  d=await ringkas(c,siap,'A');assert not d['siap'] and d['tujuan']['sesudah']=='Pemindahan tidak tersedia'
 async with pg() as db:
  rows=(await db.scalars(select(SiloStorage).where(SiloStorage.drying_lot_id==siap['id']))).all();assert len(rows)==1
  assert await si._silo_content_kg(db,rows[0].silo_id)==10300
  lot=await db.get(DryingLot,siap['id']);assert lot.waktu_selesai_pendinginan==before['drying_lots'][0][list(DryingLot.__table__.c.keys()).index('waktu_selesai_pendinginan')]
  assert await dr.dryer_load_kg(db)==0
  assert (await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch==siap['batch']))).status_batch=='di_silo'
  audit=await db.scalar(select(ActivityLog).where(ActivityLog.table_name=='silo_storage').order_by(ActivityLog.id.desc()).limit(1));assert audit.record_id==rows[0].id and audit.aksi=='silo_gabung'

@pytest.mark.parametrize('berat,sumber,teks',[(None,'menunggu','menunggu timbang'),(7600,'perkiraan','± 7.600 kg'),(8000,'manual','8.000 kg')])
async def test_bobot_tidak_final_bukan_larangan_baru(pg,siap,berat,sumber,teks):
 from app.models import PurchaseBatch
 async with pg() as db:
  b=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch==siap['batch']));b.berat_total_kg=berat;b.sumber_berat=sumber;b.berat_perkiraan_kg=berat if sumber=='perkiraan' else None;await db.commit()
 async with await _klien(pg,peran='admin') as c:
  d=await ringkas(c,siap,'Tong Selatan');assert teks in d['bobot'] and teks.split(' kg')[0] in d['tujuan']['sesudah']
  assert (await post(c,'pindah-silo',{'kode_lot':siap['kode'],'silo':'Tong Selatan'})).status_code==200
  label=next(x['label'] for x in (await c.get('/api/actions/silo-g1')).json() if x['value']=='Tong Selatan');assert teks in label and 'kosong' not in label

@pytest.mark.parametrize('keadaan',['proses','belum_dingin','ulang'])
async def test_pendinginan_tidak_dilewati(pg,siap,keadaan):
 from app.models import DryingLot,User
 from app.penggilingan.gudang1.services import drying as dr
 async with pg() as db:
  lot=await db.get(DryingLot,siap['id'])
  if keadaan=='ulang':await dr.mulai_pendinginan_ulang(db,user=await db.get(User,siap['user']),kode_lot=siap['kode'])
  else:
   lot.status='proses' if keadaan=='proses' else 'selesai';lot.waktu_selesai_pendinginan=None;await db.commit()
 before=await fakta(pg)
 async with await _klien(pg,peran='admin') as c:
  assert not (await ringkas(c,siap,'A'))['siap']
  assert (await post(c,'pindah-silo',{'kode_lot':siap['kode'],'silo':'A'})).status_code==400
 assert await fakta(pg)==before

@pytest.mark.parametrize('kode,silo',[('','A'),('TIDAK-ADA','A'),(None,''),(None,'TIDAK-ADA')])
async def test_tujuan_lot_tidak_sah_tanpa_tulisan(pg,siap,kode,silo):
 before=await fakta(pg)
 async with await _klien(pg,peran='admin') as c:
  assert (await post(c,'pindah-silo',{'kode_lot':siap['kode'] if kode is None else kode,'silo':silo})).status_code==400
 assert await fakta(pg)==before

@pytest.mark.parametrize('peran,view,izin',[('operator',None,True),('admin',None,True),('superadmin',None,True),('admin','operator:g1',True),('operator','operator:g2',False),('admin','operator:g2',False),('superadmin','operator:g2',False),('staff',None,False)])
async def test_gerbang_akses_semua_sumber_dan_post(pg,siap,peran,view,izin):
 from app.web.lihat_sebagai import NAMA_KUKI
 async with await _klien(pg,peran=peran,gudang='Gudang 1') as c:
  if view:c.cookies.set(NAMA_KUKI,view)
  for url in ['/api/actions/drying-done','/api/actions/silo-g1','/api/actions/ringkasan-pindah-silo?kode_lot='+siap['kode']]:
   r=await c.get(url);assert r.status_code==(200 if izin else 403),r.text
  assert any(x['id']=='pindah_silo' for x in (await c.get('/api/actions/menu')).json())==izin
  assert (await post(c,'pindah-silo',{'kode_lot':siap['kode'],'silo':'A'})).status_code==(200 if izin else 403)

@pytest.mark.parametrize('pemilik',['sama','berbeda','pabrik'])
async def test_pemilik_penggabungan_hanya_saat_simpan(pg,siap,pemilik):
 from app.models import Jasa,Pelanggan,DryingLot,PurchaseBatch
 async with pg() as db:
  a=Pelanggan(nama_pelanggan='Catur');b=Pelanggan(nama_pelanggan='Catur');db.add_all([a,b]);await db.flush()
  j1=Jasa(kode='JAS-UJI-1',pelanggan_id=a.id,status='berjalan');j2=Jasa(kode='JAS-UJI-2',pelanggan_id=a.id if pemilik=='sama' else b.id,status='berjalan');db.add_all([j1,j2]);await db.flush()
  lot=await db.get(DryingLot,siap['id']);lot.jasa_id=j1.id;batch=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch==siap['batch']));batch.jasa_id=j1.id;batch.supplier_id=None;await db.commit();jid=j2.id
 await isi(pg,siap,jasa=None if pemilik=='pabrik' else jid)
 before=await fakta(pg)
 async with await _klien(pg,peran='admin') as c:
  d=await ringkas(c,siap,'A');assert d['tujuan']['cocok']==(pemilik=='sama')
  assert await fakta(pg)==before
  assert not any('dibeli kering' in t for t in d['peringatan'])
  r=await post(c,'pindah-silo',{'kode_lot':siap['kode'],'silo':'A'});assert r.status_code==(200 if pemilik=='sama' else 400),r.text
 if pemilik!='sama':assert await fakta(pg)==before
 else:
  async with pg() as db:assert (await db.get(Jasa,jid)).status=='digabung'

async def test_dua_sesi_lot_sama_tidak_masuk_dua_silo(pg,siap):
 from app.models import User,SiloStorage
 from app.penggilingan.gudang1.services.silo import masuk_silo,SiloError
 async def pindah(nama):
  async with pg() as db:
   try:
    await masuk_silo(db,user=await db.get(User,siap['user']),nama_silo=nama,kode_lot=siap['kode'],kode_batch=None);return True
   except SiloError:return False
 assert sorted(await asyncio.gather(pindah('A'),pindah('B')))==[False,True]
 async with pg() as db:assert await db.scalar(select(func.count()).select_from(SiloStorage).where(SiloStorage.drying_lot_id==siap['id']))==1

async def test_silo_sumber_kedua_giling_tambahan_sekali(pg,siap):
 from app.models import User,MillingProcess,MillingProcessSource,Silo
 from app.penggilingan.gudang1.services.milling import start_milling
 from app.penggilingan.gudang1.services.silo import masuk_silo
 await isi(pg,siap,huruf='A',kode='GB-SUMBER-A')
 await isi(pg,siap,huruf='B',kode='GB-SUMBER-B')
 async with pg() as db:
  u=await db.get(User,siap['user']);r=await start_milling(db,user=u,nama_silo=['A','B']);proc_id=r.proc.id;awal=float(r.proc.berat_gabah_masuk_kg)
  from app.penggilingan.gudang1.services.silo import get_g1_silo
  assert r.proc.silo_id != (await get_g1_silo(db,'B')).id
 async with await _klien(pg,peran='admin') as c:
  d=await ringkas(c,siap,'B');assert 'Digiling' in d['tujuan']['kegiatan']
  assert (await post(c,'pindah-silo',{'kode_lot':siap['kode'],'silo':'B'})).status_code==200
 async with pg() as db:
  proc=await db.get(MillingProcess,proc_id);assert proc.status=='proses' and float(proc.berat_gabah_masuk_kg)==awal+8000
  assert await db.scalar(select(func.count()).select_from(MillingProcessSource).where(MillingProcessSource.drying_lot_id==siap['id']))==1

async def test_sebagian_bobot_diketahui_dan_master_filter(pg,siap):
 from app.models import PurchaseBatch,DryingLotBatch,Silo
 from app.database import now_local
 async with pg() as db:
  asal=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch==siap['batch']))
  b=PurchaseBatch(kode_batch='GB-BELUM-TIMBANG',supplier_id=asal.supplier_id,berat_total_kg=None,kondisi_gabah='basah',tanggal_pembelian=date.today(),waktu_pembelian=now_local(),input_by=siap['user'],sumber_berat='menunggu',flag_unverified=True,status_batch='di_dryer');db.add(b);await db.flush();db.add(DryingLotBatch(drying_lot_id=siap['id'],purchase_batch_id=b.id));await db.commit()
 async with await _klien(pg,peran='admin') as c:
  d=await ringkas(c,siap,'Tong Selatan');assert d['bobot']==d['tujuan']['sesudah']=='≥ 8.000 kg · 1 truk belum ditimbang' and d['jumlah_batch']==2
  assert 'Tong Selatan' in {x['value'] for x in (await c.get('/api/actions/silo-g1')).json()}
  async with pg() as db:
   s=await db.scalar(select(Silo).where(Silo.nama_silo=='Tong Selatan'));s.komoditas_diizinkan=['pk'];await db.commit()
  assert not (await ringkas(c,siap,'Tong Selatan'))['tujuan']['cocok']
  before=await fakta(pg)
  assert (await post(c,'pindah-silo',{'kode_lot':siap['kode'],'silo':'Tong Selatan'})).status_code==400
  assert await fakta(pg)==before
  async with pg() as db:
   s=await db.scalar(select(Silo).where(Silo.nama_silo=='Tong Selatan'));s.aktif=False;await db.commit()
  assert 'Tong Selatan' not in {x['value'] for x in (await c.get('/api/actions/silo-g1')).json()}
  assert (await post(c,'pindah-silo',{'kode_lot':siap['kode'],'silo':'Tong Selatan'})).status_code==400

async def test_isi_berubah_setelah_pratinjau_diperiksa_server(pg,siap):
 from app.models import Jasa,Pelanggan
 async with await _klien(pg,peran='admin') as c:
  assert (await ringkas(c,siap,'A'))['tujuan']['cocok']
  async with pg() as db:
   p=Pelanggan(nama_pelanggan='Pemilik lain');db.add(p);await db.flush();j=Jasa(kode='JAS-ISI-BARU',pelanggan_id=p.id);db.add(j);await db.commit();jid=j.id
  await isi(pg,siap,jasa=jid)
  before=await fakta(pg)
  r=await post(c,'pindah-silo',{'kode_lot':siap['kode'],'silo':'A'});assert r.status_code==400 and 'pemilik berbeda' in r.text.lower()
  assert await fakta(pg)==before

async def test_anonim_portal_csrf_dan_audit_pelaku(pg,siap):
 import httpx
 from app.main import app
 from app.models import Pelanggan,User,ActivityLog,SiloStorage
 from app.models.portal import PortalAccount
 from app.web.portal.security import COOKIE,issue
 from app.web import csrf,security
 before=await fakta(pg)
 async with await _klien(pg,peran='admin') as c:
  assert (await c.post('/api/actions/pindah-silo',json={'kode_lot':siap['kode'],'silo':'A'})).status_code==403
 async with pg() as db:
  p=Pelanggan(nama_pelanggan='Portal uji pindah');db.add(p);await db.flush();a=PortalAccount(username='uji-pindah-portal',pelanggan_id=p.id,password_hash=security.hash_sandi('uji-aman-123'),active=True,token_version=1);db.add(a);await db.commit()
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
  for portal in [False,True]:
   if portal:c.cookies.set(COOKIE,issue(a));c.cookies.set(csrf.NAMA_COOKIE,csrf.terbitkan_baru())
   for url in ['/api/actions/ringkasan-pindah-silo?kode_lot='+siap['kode'],'/api/actions/silo-g1','/api/actions/drying-done']:
    r=await c.get(url);assert r.status_code in (401,403) and siap['kode'] not in r.text
   assert (await post(c,'pindah-silo',{'kode_lot':siap['kode'],'silo':'A'})).status_code in (401,403)
 assert await fakta(pg)==before
 async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
  async with pg() as db:pelaku=await db.scalar(select(User.id).where(User.nama=='Uji operator').order_by(User.id.desc()).limit(1))
  assert (await post(c,'pindah-silo',{'kode_lot':siap['kode'],'silo':'A'})).status_code==200
 async with pg() as db:
  row=await db.scalar(select(SiloStorage).where(SiloStorage.drying_lot_id==siap['id']))
  audit=await db.scalar(select(ActivityLog).where(ActivityLog.table_name=='silo_storage',ActivityLog.record_id==row.id).order_by(ActivityLog.id.desc()).limit(1))
  assert audit.changed_by==row.input_by==pelaku and audit.aksi=='silo_masuk'

async def test_pembatalan_baris_tepat_dan_log_pemindahan_lama(pg,siap):
 from app.models import User,SiloStorage,SiloMovingLog,DryingLot
 from app.penggilingan.gudang1.services import silo as si
 from app.services.undo import _undo_masuk_silo_baris
 async with pg() as db:
  u=await db.get(User,siap['user']);lot=await db.get(DryingLot,siap['id']);dingin=lot.waktu_selesai_pendinginan
  await si.moving_started(db,user=u,nama_silo='A',kode_lot=siap['kode'])
  assert await db.scalar(select(func.count()).select_from(SiloStorage).where(SiloStorage.drying_lot_id==lot.id))==0
  r=await si.moving_finished(db,user=u,nama_silo=None,kode_lot=siap['kode']);assert r.kondisi=='intake'
  row=await db.scalar(select(SiloStorage).where(SiloStorage.drying_lot_id==lot.id));rid=row.id
  again=await si.moving_finished(db,user=u,nama_silo=None,kode_lot=siap['kode']);assert again.kondisi=='already'
  assert lot.waktu_selesai_pendinginan==dingin and await db.scalar(select(func.count()).select_from(SiloStorage).where(SiloStorage.drying_lot_id==lot.id))==1
  assert [x.tipe for x in (await db.scalars(select(SiloMovingLog).order_by(SiloMovingLog.id))).all()]==['mulai','selesai','selesai']
 lain=await isi(pg,siap,kode='GB-SESUDAH',kg=4000)
 async with pg() as db:
  await _undo_masuk_silo_baris(db,rid);await db.commit()
  assert await db.get(SiloStorage,rid) is None and await db.get(SiloStorage,lain) is not None
  assert await si._silo_content_kg(db,(await si.get_g1_silo(db,'A')).id)==4000

async def test_isi_berubah_tetap_cocok_tidak_ditolak(pg,siap):
 async with await _klien(pg,peran='admin') as c:
  assert (await ringkas(c,siap,'A'))['tujuan']['isi']=='0 kg'
  await isi(pg,siap)
  r=await post(c,'pindah-silo',{'kode_lot':siap['kode'],'silo':'A'});assert r.status_code==200,r.text
  assert (await ringkas(c,siap,'A'))['tujuan']['isi']=='11.000 kg'


async def test_tautan_lama_lot_yang_silonya_sudah_dikosongkan_tetap_bukan_siap_pindah(pg,siap):
 from app.models import SiloStorage
 async with await _klien(pg,peran='admin') as c:
  assert (await post(c,'pindah-silo',{'kode_lot':siap['kode'],'silo':'A'})).status_code==200
  async with pg() as db:
   row=await db.scalar(select(SiloStorage).where(SiloStorage.drying_lot_id==siap['id']));row.status='kosong';await db.commit()
  before=await fakta(pg)
  d=await ringkas(c,siap,'A');assert not d['siap'] and d['status']=='Sudah dipindah dari dryer' and d['tujuan']['sesudah']=='Pemindahan tidak tersedia'
  assert siap['kode'] not in {x['value'] for x in (await c.get('/api/actions/drying-done')).json()}
  assert await fakta(pg)==before
