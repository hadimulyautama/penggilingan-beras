"""Mulai G2: pembaca murni, saldo/komposisi dan kontrak lama pada PG uji."""
import asyncio
import pytest
from sqlalchemy import select, func
from app.database import now_local
from app.models import (User, Warehouse, Silo, Jasa, Pelanggan, PkPurchaseBatch,
 PkGudang2Intake, PkTumpukanToSilo, PolishingProcess, PolishingSiloUsage,
 PolishingOutputLog, ActivityLog, BerasKeSilo, BrokenKeSilo, HasilSampingKeSilo)
from app.penggilingan.gudang2 import service as g2, polishing as p
from tests.pg.test_gudang2_operator_pg import gudang2
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir
pytestmark=pytest.mark.asyncio

@pytest.fixture
async def bahan(pg,gudang2):
 async with pg() as db:
  u=await db.get(User,gudang2['user'].id)
  await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=gudang2['intake_tumpukan'],nama_silo='A',berat=5000)
  wh=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g2'))
  db.add(Silo(nama_silo='Silo Timur',warehouse_id=wh,jenis_isi='beras'))
  db.add(Warehouse(nama_gudang='Gudang 1 - Uji',kode_fungsi='g1'))
  await db.commit()
 return gudang2
async def baca(c,n=('A','B')):return await c.get('/api/actions/ringkasan-mulai-penyosohan',params=[('silo',x) for x in n])
async def simpan(c,n=('A','B')):return await c.post('/api/actions/mulai-penyosohan',json={'silo':n},headers={'X-CSRF-Token':cap_formulir(c)})
async def fakta(pg):
 async with pg() as db:
  return {m.__tablename__:[tuple(getattr(r,col.name) for col in m.__table__.columns) for r in (await db.scalars(select(m).order_by(m.id))).all()] for m in [PolishingProcess,PolishingSiloUsage,PolishingOutputLog,PkTumpukanToSilo,PkGudang2Intake,Jasa,ActivityLog]}
async def test_katalog_reader_tidak_menulis_dan_kontrak_lama(pg,bahan):
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg)
  a=next(x for x in (await c.get('/api/actions/menu')).json() if x['id']=='mulai_penyosohan')
  assert [f['name'] for f in a['fields']]==['silo'];assert a['fields'][0]['type']=='remote_banyak';assert not a.get('konfirmasi')
  old=(await c.get('/api/actions/silo-bahan-g2')).json();new=(await c.get('/api/actions/silo-bahan-g2?rincian=true')).json()
  assert [{k:v for k,v in x.items() if k!='rincian'} for x in new]==old
  r=await baca(c);assert r.status_code==200,r.text;assert r.headers['cache-control']=='no-store'
  d=r.json();assert d['bobot']=='14.800 kg' and d['final'] and d['siap'];assert len(d['silos'])==2
  assert await fakta(pg)==before
@pytest.mark.parametrize('n',['B',['A','B','A']])
async def test_satu_beberapa_duplikat_satu_proses_stok_tetap(pg,bahan,n):
 async with await _klien(pg,peran='admin') as c:
  before=(await baca(c,['B'] if n=='B' else ['A','B'])).json()
  r=await simpan(c,n);assert r.status_code==200,r.text;assert r.json()['kode_proses'].startswith('POL-')
 async with pg() as db:
  assert await db.scalar(select(func.count()).select_from(PolishingProcess))==1
  rows=(await db.scalars(select(PolishingSiloUsage))).all();assert len(rows)==(1 if n=='B' else 2)
  assert sum(float(x.berat_awal_kg) for x in rows)==(9800 if n=='B' else 14800)
  assert all(x.berat_akhir_kg is None for x in rows)
  assert await db.scalar(select(func.count()).select_from(PolishingOutputLog))==0
  for d in before['silos']:
   s=await g2.get_g2_silo(db,d['nama']);assert await g2.hitung_stok_silo(db,s.id)==(5000 if d['nama']=='Silo A' else 9800)
@pytest.mark.parametrize('kind',['beda','pabrik_jasa','sama'])
async def test_pemilik_penggabungan_hanya_saat_simpan(pg,bahan,kind):
 async with pg() as db:
  a=Pelanggan(nama_pelanggan='Nama Sama');b=Pelanggan(nama_pelanggan='Nama Sama');db.add_all([a,b]);await db.flush()
  j1=Jasa(kode='JAS-UJI-01',pelanggan_id=a.id);j2=Jasa(kode='JAS-UJI-02',pelanggan_id=a.id if kind=='sama' else b.id);db.add_all([j1,j2]);await db.flush()
  its=(await db.scalars(select(PkGudang2Intake).order_by(PkGudang2Intake.id))).all()
  for it,jid in [(its[0],None if kind=='pabrik_jasa' else j1.id),(its[1],j2.id)]:
   it.jasa_id=jid;batch=await db.get(PkPurchaseBatch,it.pk_purchase_batch_id);batch.jasa_id=jid
   if jid:batch.supplier_id=None
  await db.commit()
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);d=(await baca(c)).json();assert d['cocok']==(kind=='sama');assert await fakta(pg)==before
  r=await simpan(c);assert r.status_code==(200 if kind=='sama' else 400),r.text
  if kind!='sama':assert await fakta(pg)==before
  else:
   async with pg() as db:assert await db.scalar(select(func.count()).select_from(Jasa).where(Jasa.status=='digabung'))==1
async def test_komposisi_sisa_dan_seluruh_jenis_tidak_dihitung_ganda(pg,bahan):
 async with pg() as db:
  u=await db.get(User,bahan['user'].id);r=await p.mulai_penyosohan(db,user=u,nama_silos=['A'])
  await p.selesai_penyosohan(db,user=u,kode=r.proc.kode_proses,nama_silo='A',sisa_kg=500)
  s=await g2.get_g2_silo(db,'A');now=now_local()
  db.add(BerasKeSilo(kode_pindah='BRS-UJI-01',polishing_process_id=r.proc.id,jenis='medium',silo_id=s.id,berat_kg=100,tanggal=now.date(),waktu=now,input_by=u.id))
  # Bentuk sumber nyata memakai model lama; validasi stok pergerakan ditutup
  # suite service terkait, bukan digantikan pembaca formulir.
  for j,k in [('menir',50),('reject',25)]:db.add(HasilSampingKeSilo(kode_pindah='HSS-UJI-'+j,polishing_process_id=r.proc.id,jenis=j,silo_id=s.id,berat_kg=k,tanggal=now.date(),waktu=now,input_by=u.id))
  await db.commit()
 async with await _klien(pg,peran='admin') as c:
  d=(await baca(c,['A'])).json();assert d['bobot']=='675 kg';assert set(x['jenis'] for x in d['silos'][0]['komposisi'])=={'PK','Beras olah ulang','Menir','Reject'}
  assert (await simpan(c,['A'])).status_code==200
async def test_bobot_karung_dinamis_terbaru_dan_reader_tidak_mengikat(pg,bahan):
 async with pg() as db:
  u=await db.get(User,bahan['user'].id);supplier=await db.scalar(select(PkPurchaseBatch.supplier_id).limit(1));now=now_local()
  b=PkPurchaseBatch(kode_batch='PKB-KARUNG-UJI',supplier_id=supplier,jumlah_karung=100,ukuran_karung_kg=50,berat_total_kg=4800,sumber_berat='perkiraan',berat_perkiraan_kg=4800,tanggal_pembelian=now.date(),waktu_pembelian=now,input_by=u.id)
  db.add(b);await db.commit();it=(await g2.masukkan_pk_luar(db,user=u,kode=b.kode_batch)).intake
  await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo='Timur',jumlah_karung=50)
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);d=(await baca(c,['Timur'])).json();assert not d['final'] and '± 2.400' in d['bobot'];assert await fakta(pg)==before
  async with pg() as db:b=await db.scalar(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch=='PKB-KARUNG-UJI'));b.berat_total_kg=5000;b.sumber_berat='timbangan';await db.commit()
  assert (await simpan(c,['Timur'])).status_code==200
 async with pg() as db:
  usage=await db.scalar(select(PolishingSiloUsage));assert usage.bobot_karung_dinamis and float(usage.berat_awal_kg)==2500
  assert len(usage.pemindahan_karung)==1
async def test_kosong_terpakai_konflik_dan_rollback(pg,bahan):
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg)
  for x in [[],['Timur'],['AB'],['A','hilang']]:assert (await simpan(c,x)).status_code==400
  assert await fakta(pg)==before
 async def mulai():
  async with pg() as db:
   u=await db.get(User,bahan['user'].id)
   try:await p.mulai_penyosohan(db,user=u,nama_silos=['A']);return 'ok'
   except p.Gudang2Error:await db.rollback();return 'ditolak'
 assert sorted(await asyncio.gather(mulai(),mulai()))==['ditolak','ok']
 async with await _klien(pg,peran='admin') as c:
  assert 'A' not in [x['value'] for x in (await c.get('/api/actions/silo-bahan-g2')).json()]
  assert (await simpan(c,['B'])).status_code==200 # Tidak ada larangan global.
@pytest.mark.parametrize('role,view,gudang,izin', [('operator',None,'Gudang 2',True),('admin',None,'Gudang 2',True),('superadmin',None,'Gudang 2',True),('admin','operator:g2','Gudang 2',True),('operator',None,'Gudang 1',False),('admin','operator:g1','Gudang 1',False),('staff',None,'Gudang 2',False)])
async def test_akses_efektif_pilihan_reader_simpan(pg,bahan,role,view,gudang,izin):
 from app.web.lihat_sebagai import NAMA_KUKI
 async with await _klien(pg,peran=role,gudang=gudang) as c:
  if view:c.cookies.set(NAMA_KUKI,view)
  before=await fakta(pg)
  assert (await c.get('/api/actions/silo-bahan-g2?rincian=true')).status_code==(200 if izin else 403)
  assert (await baca(c)).status_code==(200 if izin else 403)
  assert (await simpan(c)).status_code==(200 if izin else 403)
  if not izin:assert await fakta(pg)==before
async def test_csrf_anonim(pg,bahan):
 import httpx
 from app.main import app
 async with await _klien(pg,peran='admin') as c:assert (await c.post('/api/actions/mulai-penyosohan',json={'silo':['A']})).status_code==403
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:assert (await baca(c)).status_code==401

async def test_karung_belum_diketahui_dan_sisa_ukur_bukan_nol_pasti(pg,bahan):
 async with pg() as db:
  u=await db.get(User,bahan['user'].id);supplier=await db.scalar(select(PkPurchaseBatch.supplier_id).limit(1));now=now_local()
  b=PkPurchaseBatch(kode_batch='PKB-BELUM-UJI',supplier_id=supplier,jumlah_karung=100,ukuran_karung_kg=50,berat_total_kg=None,sumber_berat='perkiraan',tanggal_pembelian=now.date(),waktu_pembelian=now,input_by=u.id)
  db.add(b);await db.commit();it=(await g2.masukkan_pk_luar(db,user=u,kode=b.kode_batch)).intake
  await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo='B',jumlah_karung=50)
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);d=(await baca(c,['B'])).json();assert d['bobot'].startswith('≥ 9.800') and not d['final'];assert 'menunggu timbang' in d['silos'][0]['sumber'][-1]['bobot'];assert await fakta(pg)==before

async def test_audit_dan_keadaan_dijeda_silo_tetap_terikat(pg,bahan):
 from app.penggilingan.gudang1.services.jeda import hentikan
 async with pg() as db:
  u=await db.get(User,bahan['user'].id);r=await p.mulai_penyosohan(db,user=u,nama_silos=['B'])
  await hentikan(db,user=u,jenis='penyosohan',kode=r.proc.kode_proses,sebab='Listrik padam')
  audit=await db.scalar(select(ActivityLog).where(ActivityLog.table_name=='polishing_process',ActivityLog.record_id==r.proc.id))
  assert audit and audit.changed_by==u.id and audit.waktu_perubahan
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);d=(await baca(c,['B'])).json();assert not d['siap']
  assert 'B' not in [x['value'] for x in (await c.get('/api/actions/silo-bahan-g2')).json()]
  assert (await simpan(c,['A','B'])).status_code==400;assert await fakta(pg)==before
