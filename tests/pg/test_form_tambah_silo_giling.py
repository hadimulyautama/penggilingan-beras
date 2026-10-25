"""Mix G1: pembaca tanpa mutasi dan kontrak simpan lama pada PG terisolasi."""
import asyncio
import pytest
from sqlalchemy import select, func
from tests.pg.test_form_hasil_penggilingan import hasil, g1, _isi_silo_g1, fakta
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir
from app.models import Silo, SiloStorage, MillingProcess, MillingProcessSource, PurchaseBatch, User, Jasa, Pelanggan, ActivityLog, Warehouse
from app.penggilingan.gudang1.services import milling as m
pytestmark=pytest.mark.asyncio

@pytest.fixture
async def mix(pg,hasil,g1):
 async with pg() as db:
  silo=Silo(nama_silo='Silo Tong Selatan',warehouse_id=g1['wh'],status='kosong');db.add(silo);await db.flush();g1['silo']['TONG SELATAN']=silo.id;await db.commit()
 await _isi_silo_g1(pg,g1,huruf='TONG SELATAN',kode='GB-MIX-1',kg=1500)
 await _isi_silo_g1(pg,g1,huruf='TONG SELATAN',kode='GB-MIX-2',kg=1000)
 return hasil
async def baca(c,p,silo='TONG SELATAN'):
 return await c.get('/api/actions/ringkasan-tambah-silo-giling',params=dict(kode_proses=p.kode_proses,silo=silo))
async def simpan(c,p,silo='TONG SELATAN'):
 return await c.post('/api/actions/tambah-silo-giling',json=dict(kode_proses=p.kode_proses,silo=silo),headers={'X-CSRF-Token':cap_formulir(c)})
async def snapshot(pg):
 async with pg() as db:
  return {c.__tablename__:[tuple(getattr(r,col.name) for col in c.__table__.columns) for r in (await db.scalars(select(c).order_by(c.id))).all()] for c in [MillingProcess,MillingProcessSource,SiloStorage,PurchaseBatch,Jasa,ActivityLog]}
async def test_kontrak_pilihan_reader_tanpa_mutasi(pg,mix):
 u,p,j=mix
 async with await _klien(pg,peran='admin') as c:
  before=await snapshot(pg)
  a=next(x for x in (await c.get('/api/actions/menu')).json() if x['id']=='tambah_silo_giling')
  assert [f['name'] for f in a['fields']]==['kode_proses','silo'];assert a['post']=='/api/actions/tambah-silo-giling';assert not a.get('konfirmasi') and not a.get('pratinjau_silo')
  assert (await c.get('/api/actions/silo-g1-tambah')).json()==[]
  options=(await c.get('/api/actions/silo-g1-tambah',params=dict(induk=p.kode_proses))).json();assert [x['value'].upper() for x in options]==['TONG SELATAN']
  r=await baca(c,p);assert r.status_code==200,r.text;assert r.headers['cache-control']=='no-store'
  d=r.json();assert d['bahan']=='10.000 kg' and d['tambahan']=='2.500 kg' and d['setelah']=='12.500 kg';assert len(d['sumber'])==2 and d['cocok'] and d['final']
  assert (await c.get('/api/actions/ringkasan-tambah-silo-giling',params=dict(kode_proses='hilang'))).status_code==400
  assert await snapshot(pg)==before
@pytest.mark.parametrize('keadaan',['pasti','perkiraan','belum','sebagian'])
async def test_saldo_pengurangan_kepastian_dan_sinkron(pg,mix,keadaan):
 u,p,_=mix
 async with pg() as db:
  b=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch=='GB-MIX-1'));st=await db.scalar(select(SiloStorage).where(SiloStorage.purchase_batch_id==b.id));st.dikemas_kg=300
  if keadaan=='perkiraan':b.sumber_berat='perkiraan';b.berat_perkiraan_kg=1500
  if keadaan in ('belum','sebagian'):b.berat_total_kg=None;b.sumber_berat='menunggu'
  if keadaan=='belum':b2=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch=='GB-MIX-2'));b2.berat_total_kg=None;b2.sumber_berat='menunggu'
  await db.commit()
 async with await _klien(pg,peran='admin') as c:
  d=(await baca(c,p)).json();assert d['final']==(keadaan=='pasti');assert len(d['sumber'])==2
  if keadaan=='pasti':assert d['tambahan']=='2.200 kg' and d['setelah']=='12.200 kg'
  elif keadaan=='perkiraan':assert d['tambahan'].startswith('± 2.200')
  elif keadaan=='belum':assert 'menunggu timbang' in d['tambahan'] and '≥ 10.000' in d['setelah']
  else:assert d['tambahan'].startswith('≥ 1.000') and d['setelah'].startswith('≥ 11.000')
  before=await fakta(pg,p);r=await simpan(c,p);assert r.status_code==200,r.text
  if keadaan=='belum':assert '0 kg' not in r.json()['pesan'] and 'menunggu timbang' in r.json()['pesan']
 after=await fakta(pg,p);assert before['stok']==after['stok'] and before['logs']==after['logs'];assert len(after['sumber'])==4 and after['status']=='proses'
 async with pg() as db:
  pr=await db.get(MillingProcess,p.id);assert pr.kode_proses==p.kode_proses and pr.bobot_masuk_final==(keadaan=='pasti')
  if keadaan in ('belum','sebagian'):
   rows=(await db.scalars(select(PurchaseBatch).where(PurchaseBatch.kode_batch.in_(['GB-MIX-1','GB-MIX-2'])))).all()
   for b in rows:b.berat_total_kg=1500 if b.kode_batch.endswith('1') else 1000;b.sumber_berat='timbangan'
   await db.commit();await m.resinkron_bahan_berjalan(db)
   await db.refresh(pr);assert float(pr.berat_gabah_masuk_kg)==12200 and pr.bobot_masuk_final
@pytest.mark.parametrize('jenis',['pabrik_jasa','beda_pelanggan','sepemilik'])
async def test_pemilik_dan_penggabungan_baca_tidak_menulis(pg,mix,jenis):
 u,p,j=mix
 async with pg() as db:
  a=await db.get(Jasa,j)
  owner=Pelanggan(nama_pelanggan='Nama sama');db.add(owner);await db.flush()
  other=Jasa(kode='JAS-MIX-LAIN',pelanggan_id=a.pelanggan_id if jenis=='sepemilik' else owner.id);db.add(other);await db.flush()
  if jenis!='pabrik_jasa':pr=await db.get(MillingProcess,p.id);pr.jasa_id=j
  rows=(await db.scalars(select(SiloStorage).join(PurchaseBatch,PurchaseBatch.id==SiloStorage.purchase_batch_id).where(PurchaseBatch.kode_batch.like('GB-MIX-%')))).all()
  for st in rows:st.jasa_id=other.id;b=await db.get(PurchaseBatch,st.purchase_batch_id);b.supplier_id=None;b.jasa_id=other.id
  await db.commit()
 async with await _klien(pg,peran='admin') as c:
  before=await snapshot(pg);d=(await baca(c,p)).json();assert d['cocok']==(jenis=='sepemilik');assert await snapshot(pg)==before
  if jenis=='sepemilik':assert d['pemilik']=='Pelanggan Uji Penggilingan' and d['sumber'][0]['pemilik']=='Pelanggan Uji Penggilingan'
  assert any(x['value'].upper()=='TONG SELATAN' for x in (await c.get('/api/actions/silo-g1-tambah',params=dict(induk=p.kode_proses))).json())
  r=await simpan(c,p);assert r.status_code==(200 if jenis=='sepemilik' else 400),r.text
  if jenis!='sepemilik':assert await snapshot(pg)==before
  else:
   async with pg() as db:
    pr=await db.get(MillingProcess,p.id);assert pr.jasa_id in (j,other.id)
    orders=(await db.scalars(select(Jasa).where(Jasa.id.in_([j,other.id])))).all();assert sum(x.status=='digabung' for x in orders)==1
async def test_dijeda_duplikat_audit_dan_sumber_tepat_sekali(pg,mix):
 from app.penggilingan.gudang1.services import jeda as j
 u,p,_=mix
 async with pg() as db:await j.hentikan(db,user=u,jenis='giling',kode=p.kode_proses,sebab='Listrik padam')
 before=await fakta(pg,p)
 async with await _klien(pg,peran='admin') as c:
  assert (await baca(c,p)).json()['status']=='dijeda';assert (await simpan(c,p)).status_code==200;after=await snapshot(pg)
  assert (await simpan(c,p)).status_code==400;assert await snapshot(pg)==after
 async with pg() as db:
  assert await j.jeda_terbuka(db,'giling',p.id);pr=await db.get(MillingProcess,p.id);assert pr.status=='proses' and not pr.waktu_selesai
  audit=await db.scalar(select(ActivityLog).where(ActivityLog.table_name=='milling_process',ActivityLog.record_id==p.id,ActivityLog.new_value.like('%TONG SELATAN%')));assert audit and audit.changed_by and audit.waktu_perubahan
 after=await fakta(pg,p);assert after['logs']==before['logs'] and after['stok']==before['stok']
async def test_konflik_dua_sesi_rollback_dan_daftar_sudah_terpakai(pg,mix,g1):
 u,p,_=mix
 async def tambah():
  async with pg() as db:
   try:await m.tambah_silo_giling(db,user=u,kode_proses=p.kode_proses,nama_silo=['TONG SELATAN']);return 'ok'
   except m.MillingError:await db.rollback();return 'ditolak'
 assert sorted(await asyncio.gather(tambah(),tambah()))==['ditolak','ok']
 async with pg() as db:
  pr=await db.get(MillingProcess,p.id);assert float(pr.berat_gabah_masuk_kg)==12500
  assert await db.scalar(select(func.count()).select_from(MillingProcessSource).where(MillingProcessSource.milling_process_id==p.id))==4
 async with await _klien(pg,peran='admin') as c:assert (await c.get('/api/actions/silo-g1-tambah',params=dict(induk=p.kode_proses))).json()==[]
async def test_tidak_sah_dan_service_list_legacy_atomik(pg,mix):
 u,p,_=mix
 async with await _klien(pg,peran='admin') as c:
  before=await snapshot(pg)
  for silo in ['','A','HILANG']:
   assert (await simpan(c,p,silo)).status_code==400
  assert await snapshot(pg)==before
 async with pg() as db:
  with pytest.raises(m.MillingError):await m.tambah_silo_giling(db,user=u,kode_proses=p.kode_proses,nama_silo=['TONG SELATAN','HILANG'])
  await db.rollback()
 assert await snapshot(pg)==before
 async with pg() as db:await m.tambah_silo_giling(db,user=u,kode_proses=p.kode_proses,nama_silo=['TONG SELATAN','TONG SELATAN'])
 async with pg() as db:
  pr=await db.get(MillingProcess,p.id);assert float(pr.berat_gabah_masuk_kg)==12500
async def test_proses_selesai_dan_silo_diklaim_setelah_dibuka(pg,mix):
 u,p,_=mix
 async with pg() as db:other=(await m.start_milling(db,user=u,nama_silo='TONG SELATAN')).proc
 async with await _klien(pg,peran='admin') as c:
  before=await snapshot(pg);assert (await simpan(c,p)).status_code==400;assert await snapshot(pg)==before
 async with pg() as db:pr=await db.get(MillingProcess,p.id);pr.status='selesai';await db.commit()
 async with await _klien(pg,peran='admin') as c:assert (await simpan(c,p)).status_code==400
@pytest.mark.parametrize('role,view,gudang,izin',[('operator',None,'Gudang 1',True),('admin',None,'Gudang 1',True),('superadmin',None,'Gudang 1',True),('admin','operator:g1','Gudang 1',True),('operator',None,'Gudang 2',False),('admin','operator:g2','Gudang 2',False),('superadmin','operator:g2','Gudang 2',False),('staff',None,'Gudang 1',False)])
async def test_izin_efektif_pilihan_baca_simpan(pg,mix,role,view,gudang,izin):
 from app.web.lihat_sebagai import NAMA_KUKI
 u,p,_=mix
 async with pg() as db:
  if not await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g2')):db.add(Warehouse(nama_gudang='Gudang 2 - Polesan',kode_fungsi='g2'))
  await db.commit()
 async with await _klien(pg,peran=role,gudang=gudang) as c:
  if view:c.cookies.set(NAMA_KUKI,view)
  before=await snapshot(pg)
  for url in ['/api/actions/milling-active','/api/actions/silo-g1-tambah?induk='+p.kode_proses]:assert (await c.get(url)).status_code==(200 if izin else 403)
  assert (await baca(c,p)).status_code==(200 if izin else 403)
  assert (await simpan(c,p)).status_code==(200 if izin else 403)
  if not izin:assert await snapshot(pg)==before
async def test_csrf_anonim(pg,mix):
 import httpx
 from app.main import app
 _,p,_=mix
 async with await _klien(pg,peran='admin') as c:assert (await c.post('/api/actions/tambah-silo-giling',json=dict(kode_proses=p.kode_proses,silo='TONG SELATAN'))).status_code==403
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
  assert (await baca(c,p)).status_code==401
  assert (await simpan(c,p)).status_code in (401,403)

async def test_bahan_awal_semua_belum_diketahui_bukan_nol(pg,mix):
 u,p,_=mix
 async with pg() as db:
  for r in (await db.scalars(select(MillingProcessSource).where(MillingProcessSource.milling_process_id==p.id))).all():r.berat_kg=None
  pr=await db.get(MillingProcess,p.id);pr.berat_gabah_masuk_kg=0;pr.bobot_masuk_final=False;await db.commit()
 async with await _klien(pg,peran='admin') as c:
  d=(await baca(c,p)).json();assert d['bahan'].startswith('menunggu timbang') and d['setelah'].startswith('≥ 2.500') and not d['final']

async def test_dua_proses_berebut_sumber_hanya_satu_yang_berhasil(pg,mix,g1):
 u,p,_=mix
 async with pg() as db:
  silo=Silo(nama_silo='Silo Utara',warehouse_id=g1['wh'],status='kosong');db.add(silo);await db.flush();g1['silo']['UTARA']=silo.id;await db.commit()
 await _isi_silo_g1(pg,g1,huruf='UTARA',kode='GB-MIX-UTARA',kg=800)
 async with pg() as db:q=(await m.start_milling(db,user=u,nama_silo='UTARA')).proc
 async def tambah(kode):
  async with pg() as db:
   try:await m.tambah_silo_giling(db,user=u,kode_proses=kode,nama_silo='TONG SELATAN');return True
   except m.MillingError:await db.rollback();return False
 assert sum(await asyncio.gather(tambah(p.kode_proses),tambah(q.kode_proses)))==1
 async with pg() as db:
  rows=(await db.scalars(select(MillingProcessSource).join(SiloStorage,SiloStorage.id==MillingProcessSource.silo_storage_id).where(SiloStorage.silo_id==g1['silo']['TONG SELATAN']))).all()
  assert len(rows)==2 and len({r.milling_process_id for r in rows})==1
  ps=(await db.scalars(select(MillingProcess).where(MillingProcess.id.in_([p.id,q.id])))).all();assert sum(float(x.berat_gabah_masuk_kg) for x in ps)==13300

async def test_gagal_setelah_klaim_rollback_seluruh_sumber(pg,mix,monkeypatch):
 from sqlalchemy.exc import IntegrityError
 from app.services import proses_bersama
 u,p,_=mix;before=await snapshot(pg)
 async def gagal(*a,**kw):raise IntegrityError('uji rahasia internal',{},Exception('rincian tidak boleh tampil'))
 monkeypatch.setattr(proses_bersama,'perbarui_bahan_proses_bersama',gagal)
 async with pg() as db:
  with pytest.raises(m.MillingError) as err:await m.tambah_silo_giling(db,user=u,kode_proses=p.kode_proses,nama_silo='TONG SELATAN')
  assert 'rahasia' not in str(err.value) and 'rincian tidak' not in str(err.value)
 assert await snapshot(pg)==before
