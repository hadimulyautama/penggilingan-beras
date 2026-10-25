"""Formulir mulai: pembaca tidak menulis, kontrak lama dan sumber tetap utuh."""
from datetime import date
import pytest
from sqlalchemy import select,func
from tests.pg.test_giling_beberapa_silo import silos
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_form_kadar_air import post
from tests.pg.test_form_pindah_silo import fakta

pytestmark=pytest.mark.asyncio

async def ringkas(c,nama):
 r=await c.get('/api/actions/ringkasan-mulai-giling',params=[('silo',x) for x in nama]);assert r.status_code==200,r.text
 assert r.headers['cache-control']=='no-store';return r.json()

async def test_saldo_semua_baris_pratinjau_tanpa_tulisan_dan_satu_lot(pg,silos):
 from app.models import SiloStorage,PurchaseBatch,User,MillingProcess,MillingProcessSource,MillingProgressLog
 from app.database import now_local
 async with pg() as db:
  a=await db.get(SiloStorage,silos['isi']['A']['storage']);a.dikemas_kg=700
  b=await db.get(PurchaseBatch,silos['isi']['A']['batch'])
  extra=PurchaseBatch(kode_batch='GB-EKSTRA',supplier_id=b.supplier_id,berat_total_kg=2000,kondisi_gabah='kering',tanggal_pembelian=date.today(),waktu_pembelian=now_local(),input_by=silos['user'],sumber_berat='manual',flag_unverified=False,status_batch='di_silo');db.add(extra);await db.flush()
  db.add(SiloStorage(silo_id=a.silo_id,purchase_batch_id=extra.id,tipe_masuk='langsung_kering',tanggal_masuk=now_local(),input_by=silos['user'],status='terisi'));await db.commit()
 before=await fakta(pg)
 async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
  menu=next(x for x in (await c.get('/api/actions/menu')).json() if x['id']=='mulai_giling');assert len(menu['fields'])==1 and menu['fields'][0]['name']=='silo'
  for _ in range(2):
   p=(await c.get('/api/actions/silo-siap-giling')).json();assert [x['value'] for x in p]==['A','B'];assert p[0]['rincian']['jumlah_sumber']==2
   d=await ringkas(c,['A','B']);assert d['bobot']=='17.300 kg' and d['jumlah_sumber']==3 and d['final'] and d['pemilik']=='Pabrik'
  assert await fakta(pg)==before
  r=await post(c,'mulai-giling',{'silo':[' B ','A','B']});assert r.status_code==200,r.text
  assert r.json()['bobot']=='17.300 kg' and r.json()['silos']=='B + A'
  assert not (await c.get('/api/actions/silo-siap-giling')).json()
  latest=await ringkas(c,['A','B']);assert not latest['siap'] and all(x['proses']==r.json()['kode_proses'] for x in latest['silos'])
 async with pg() as db:
  proc=await db.scalar(select(MillingProcess));assert proc.silo_id==silos['silo']['B'] and float(proc.berat_gabah_masuk_kg)==17300
  assert await db.scalar(select(func.count()).select_from(MillingProcessSource))==3
  assert await db.scalar(select(func.count()).select_from(MillingProgressLog))==0
  rows=(await db.scalars(select(SiloStorage))).all();assert all(x.status=='terisi' for x in rows)

@pytest.mark.parametrize('keadaan,teks,final',[("pasti","16.000 kg",True),("perkiraan","± 15.600 kg",False),("sebagian","≥ 10.000 kg",False),("semua","menunggu timbang",False)])
async def test_keadaan_bobot_sama_sebelum_sesudah(pg,silos,keadaan,teks,final):
 from app.models import PurchaseBatch,MillingProcessSource
 async with pg() as db:
  b=await db.get(PurchaseBatch,silos['isi']['B']['batch'])
  if keadaan=='perkiraan':b.berat_total_kg=5600;b.berat_perkiraan_kg=5600;b.sumber_berat='perkiraan';b.flag_unverified=True
  elif keadaan in ['sebagian','semua']:b.berat_total_kg=None;b.sumber_berat='menunggu';b.flag_unverified=True
  if keadaan=='semua':
   a=await db.get(PurchaseBatch,silos['isi']['A']['batch']);a.berat_total_kg=None;a.sumber_berat='menunggu';a.flag_unverified=True
  await db.commit()
 async with await _klien(pg,peran='admin') as c:
  d=await ringkas(c,['A','B']);assert teks in d['bobot'] and d['final']==final
  r=await post(c,'mulai-giling',{'silo':['A','B']});assert r.status_code==200,r.text
  assert r.json()['bobot']==d['bobot'] and r.json()['bobot_final']==final
 async with pg() as db:
  vals=(await db.scalars(select(MillingProcessSource.berat_kg))).all()
  assert sum(x is None for x in vals)==(2 if keadaan=='semua' else 1 if keadaan=='sebagian' else 0)

@pytest.mark.parametrize('pemilik',['sama','berbeda','pabrik'])
async def test_pelanggan_bukan_nama_pesanan_preview_tidak_gabung(pg,silos,pemilik):
 from app.models import Pelanggan,Jasa,PurchaseBatch,SiloStorage
 async with pg() as db:
  a=Pelanggan(nama_pelanggan='Catur');b=Pelanggan(nama_pelanggan='Catur');db.add_all([a,b]);await db.flush()
  j1=Jasa(kode='JAS-FORM-1',pelanggan_id=a.id,status='berjalan');j2=Jasa(kode='JAS-FORM-2',pelanggan_id=a.id if pemilik=='sama' else b.id,status='berjalan');db.add_all([j1,j2]);await db.flush();ids=[j1.id,None if pemilik=='pabrik' else j2.id]
  for huruf,jid in zip(['A','B'],ids):
   st=await db.get(SiloStorage,silos['isi'][huruf]['storage']);st.jasa_id=jid
   if jid:
    batch=await db.get(PurchaseBatch,st.purchase_batch_id);batch.jasa_id=jid;batch.supplier_id=None
  await db.commit();kedua=j2.id
 before=await fakta(pg)
 async with await _klien(pg,peran='admin') as c:
  d=await ringkas(c,['A','B']);assert d['cocok']==(pemilik=='sama');assert d['peringatan'];assert await fakta(pg)==before
  r=await post(c,'mulai-giling',{'silo':['A','B']});assert r.status_code==(200 if pemilik=='sama' else 400),r.text
 if pemilik!='sama':assert await fakta(pg)==before
 else:
  async with pg() as db:assert (await db.get(Jasa,kedua)).status=='digabung'

@pytest.mark.parametrize('peran,view,izin',[('operator',None,True),('admin',None,True),('superadmin',None,True),('admin','operator:g1',True),('operator','operator:g2',False),('admin','operator:g2',False),('superadmin','operator:g2',False),('staff',None,False)])
async def test_semua_gerbang_efektif(pg,silos,peran,view,izin):
 from app.web.lihat_sebagai import NAMA_KUKI
 from app.services.seed import seed_master
 await seed_master()
 async with await _klien(pg,peran=peran,gudang='Gudang 1',lihat=view) as c:
  if view:c.cookies.set(NAMA_KUKI,view)
  for url in ['/api/actions/silo-siap-giling','/api/actions/ringkasan-mulai-giling?silo=A']:
   assert (await c.get(url)).status_code==(200 if izin else 403)
  assert any(x['id']=='mulai_giling' for x in (await c.get('/api/actions/menu')).json())==izin
  assert (await post(c,'mulai-giling',{'silo':'A'})).status_code==(200 if izin else 403)

@pytest.mark.parametrize('nama',[[],['C'],['TIDAK ADA'],['A','C']])
async def test_tidak_sah_tidak_mulai_sebagian(pg,silos,nama):
 before=await fakta(pg)
 async with await _klien(pg,peran='admin') as c:
  d=await ringkas(c,nama);assert not d['siap']
  assert (await post(c,'mulai-giling',{'silo':nama})).status_code==400
 assert await fakta(pg)==before

async def test_master_lain_aktif_dan_csrf(pg,silos):
 from app.models import Silo
 async with pg() as db:
  s=await db.get(Silo,silos['silo']['B']);s.nama_silo='Tong Selatan';await db.commit()
 async with await _klien(pg,peran='admin') as c:
  assert 'Tong Selatan' in [x['value'] for x in (await c.get('/api/actions/silo-siap-giling')).json()]
  assert (await c.post('/api/actions/mulai-giling',json={'silo':'Tong Selatan'})).status_code==403
  assert (await post(c,'mulai-giling',{'silo':'Tong Selatan'})).status_code==200

async def test_silo_kedua_dijeda_tetap_terikat(pg,silos):
 from app.models import User
 from app.penggilingan.gudang1.services import milling,jeda
 async with pg() as db:
  u=await db.get(User,silos['user']);r=await milling.start_milling(db,user=u,nama_silo=['A','B'])
  await jeda.hentikan(db,user=u,jenis='giling',kode=r.proc.kode_proses,sebab='Listrik padam')
 async with await _klien(pg,peran='admin') as c:
  assert not (await c.get('/api/actions/silo-siap-giling')).json()
  d=await ringkas(c,['B']);assert not d['siap'] and d['silos'][0]['proses']==r.proc.kode_proses
  before=await fakta(pg)
  assert (await post(c,'mulai-giling',{'silo':'B'})).status_code==400
  assert await fakta(pg)==before

async def test_sumber_berubah_setelah_pratinjau_diperiksa_lagi(pg,silos):
 from app.models import User,MillingProcess
 from app.penggilingan.gudang1.services.milling import start_milling
 async with await _klien(pg,peran='admin') as c:
  assert (await ringkas(c,['A','B']))['siap']
  async with pg() as db:await start_milling(db,user=await db.get(User,silos['user']),nama_silo='B')
  before=await fakta(pg)
  r=await post(c,'mulai-giling',{'silo':['A','B']});assert r.status_code==400 and 'sedang digiling' in r.text
  assert await fakta(pg)==before
  async with pg() as db:assert await db.scalar(select(func.count()).select_from(MillingProcess))==1
