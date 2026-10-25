"""Tambah G2: kontrak kode/array, pembaca murni, siklus ulang dan transaksi lama."""
import asyncio
import pytest
from sqlalchemy import select,func
from app.database import now_local
from app.models import (User,Silo,Warehouse,Jasa,Pelanggan,PkPurchaseBatch,PkGudang2Intake,
 PolishingProcess,PolishingSiloUsage,PolishingOutputLog,ActivityLog,BerasKeSilo,
 BrokenKeSilo,HasilSampingKeSilo,ByproductStock)
from app.penggilingan.gudang2 import service as g2,polishing as p
from tests.pg.test_gudang2_operator_pg import gudang2
from tests.pg.test_form_mulai_penyosohan import bahan,fakta
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir
pytestmark=pytest.mark.asyncio
@pytest.fixture
async def proses(pg,bahan):
 async with pg() as db:
  u=await db.get(User,bahan['user'].id);r=await p.mulai_penyosohan(db,user=u,nama_silos=['B'])
  return dict(bahan,kode=r.proc.kode_proses,pid=r.proc.id)
async def baca(c,b,n=('A',)):
 return await c.get('/api/actions/ringkasan-tambah-silo-penyosohan',params=[('kode',b['kode'])]+[('silo',x) for x in n])
async def simpan(c,b,n=('A',)):
 return await c.post('/api/actions/tambah-silo-penyosohan',json={'kode':b['kode'],'silo':n},headers={'X-CSRF-Token':cap_formulir(c)})
async def isi(pg,b,n='Timur',kg=1000):
 async with pg() as db:
  u=await db.get(User,b['user'].id)
  await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=b['intake_tumpukan'],nama_silo=n,berat=kg)
async def test_menu_pilihan_dan_ringkasan_murni(pg,proses):
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);a=next(x for x in (await c.get('/api/actions/menu')).json() if x['id']=='tambah_silo_penyosohan')
  assert [f['name'] for f in a['fields']]==['kode','silo'];assert a['fields'][1]['type']=='remote_banyak' and a['fields'][1]['induk']=='kode';assert not a.get('konfirmasi')
  url='/api/actions/silo-bahan-g2?induk='+proses['kode'];old=(await c.get(url)).json();new=(await c.get(url+'&rincian=true')).json()
  assert [{k:v for k,v in x.items() if k!='rincian'} for x in new]==old
  assert [x['value'] for x in old]==['A']
  r=await baca(c,proses);assert r.status_code==200,r.text;assert r.headers['cache-control']=='no-store';d=r.json();assert d['tambahan']=='5.000 kg' and d['sumber_aktif']==['Silo B'];assert d['final'];assert await fakta(pg)==before
@pytest.mark.parametrize('n',[' a ',['A','A'],['A','Timur']])
async def test_kode_tunggal_daftar_duplikat_tetap_satu_proses(pg,proses,n):
 if isinstance(n,list) and 'Timur' in n:await isi(pg,proses)
 async with await _klien(pg,peran='admin') as c:
  r=await simpan(c,proses,n);assert r.status_code==200,r.text
 async with pg() as db:
  assert await db.scalar(select(func.count()).select_from(PolishingProcess))==1
  rows=(await db.scalars(select(PolishingSiloUsage).order_by(PolishingSiloUsage.id))).all();assert len(rows)==(3 if isinstance(n,list) and 'Timur' in n else 2)
  assert sum(float(x.berat_awal_kg) for x in rows)==(15800 if len(rows)==3 else 14800)
  assert all(x.berat_akhir_kg is None for x in rows);assert await db.scalar(select(func.count()).select_from(PolishingOutputLog))==0
  a=await g2.get_g2_silo(db,'A');assert await g2.hitung_stok_silo(db,a.id)==5000
@pytest.mark.parametrize('n',[[],[''],['hilang'],['B'],['Timur'],['A','hilang']])
async def test_tidak_sah_tidak_menambah_sebagian(pg,proses,n):
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);r=await simpan(c,proses,n);assert r.status_code==400,r.text;assert await fakta(pg)==before
@pytest.mark.parametrize('sisa,refill',[(0,False),(200,False),(0,True)])
async def test_pakai_ulang_siklus_asli_tidak_ditimpa(pg,proses,sisa,refill):
 async with pg() as db:
  u=await db.get(User,proses['user'].id);await p.tambah_silo_penyosohan(db,user=u,kode=proses['kode'],nama_silos=['A']);await p.selesai_penyosohan(db,user=u,kode=proses['kode'],nama_silo='A',sisa_kg=sisa)
 if refill:await isi(pg,proses,'A',1000)
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);d=(await baca(c,proses)).json();assert d['silos'][0]['pakai_kembali'];assert d['silos'][0]['kosong']==(sisa==0 and not refill);assert d['tambahan']==('1.000 kg' if refill else str(sisa)+' kg');assert await fakta(pg)==before
  opts=(await c.get('/api/actions/silo-bahan-g2',params={'induk':proses['kode'],'rincian':'true'})).json();assert next(x for x in opts if x['value']=='A')['rincian']['pakai_kembali'];assert (await simpan(c,proses)).status_code==200
 async with pg() as db:
  a=await g2.get_g2_silo(db,'A');rs=(await db.scalars(select(PolishingSiloUsage).where(PolishingSiloUsage.silo_id==a.id).order_by(PolishingSiloUsage.id))).all()
  assert len(rs)==2 and float(rs[0].berat_akhir_kg)==sisa and float(rs[0].berat_terpakai_kg)==5000-sisa;assert float(rs[1].berat_awal_kg)==(1000 if refill else sisa)
 if not sisa and not refill:
  await isi(pg,proses,'A',1000)
  async with pg() as db:
   rs=(await db.scalars(select(PolishingSiloUsage).where(PolishingSiloUsage.silo_id==a.id).order_by(PolishingSiloUsage.id))).all();assert float(rs[0].berat_akhir_kg)==0 and float(rs[1].berat_masuk_kg)==1000
@pytest.mark.parametrize('kind',['beda','pabrik_jasa','sama'])
async def test_pemilik_dan_penggabungan_hanya_saat_simpan(pg,proses,kind):
 async with pg() as db:
  a=Pelanggan(nama_pelanggan='Nama Sama');b=Pelanggan(nama_pelanggan='Nama Sama');db.add_all([a,b]);await db.flush();j1=Jasa(kode='JAS-UJI-01',pelanggan_id=a.id);j2=Jasa(kode='JAS-UJI-02',pelanggan_id=a.id if kind=='sama' else b.id);db.add_all([j1,j2]);await db.flush()
  its=(await db.scalars(select(PkGudang2Intake).order_by(PkGudang2Intake.id))).all()
  for it,jid in [(its[0],None if kind=='pabrik_jasa' else j1.id),(its[1],j2.id)]:
   it.jasa_id=jid;batch=await db.get(PkPurchaseBatch,it.pk_purchase_batch_id);batch.jasa_id=jid
   if jid:batch.supplier_id=None
  pr=await db.get(PolishingProcess,proses['pid']);pr.jasa_id=j2.id;await db.commit()
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);d=(await baca(c,proses)).json();assert await fakta(pg)==before
  assert any('pemilik bahan berbeda' in x for x in d['peringatan'])==(kind!='sama')
  r=await simpan(c,proses);assert r.status_code==(200 if kind=='sama' else 400),r.text
  if kind!='sama':assert await fakta(pg)==before
  else:
   async with pg() as db:assert await db.scalar(select(func.count()).select_from(Jasa).where(Jasa.status=='digabung'))==1
async def test_karung_dinamis_ringkasan_tidak_mengikat_dan_bobot_terbaru(pg,proses):
 async with pg() as db:
  u=await db.get(User,proses['user'].id);supplier=await db.scalar(select(PkPurchaseBatch.supplier_id).limit(1));now=now_local();b=PkPurchaseBatch(kode_batch='PKB-KARUNG-UJI',supplier_id=supplier,jumlah_karung=100,ukuran_karung_kg=50,berat_total_kg=4800,sumber_berat='perkiraan',berat_perkiraan_kg=4800,tanggal_pembelian=now.date(),waktu_pembelian=now,input_by=u.id);db.add(b);await db.commit();it=(await g2.masukkan_pk_luar(db,user=u,kode=b.kode_batch)).intake;await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo='Timur',jumlah_karung=50)
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);d=(await baca(c,proses,['Timur'])).json();assert not d['final'] and '± 2.400' in d['tambahan'];assert await fakta(pg)==before
  async with pg() as db:b=await db.scalar(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch=='PKB-KARUNG-UJI'));b.berat_total_kg=5000;b.sumber_berat='timbangan';await db.commit()
  assert (await simpan(c,proses,['Timur'])).status_code==200
 async with pg() as db:
  s=await g2.get_g2_silo(db,'Timur');u=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.silo_id==s.id));assert u.bobot_karung_dinamis and float(u.berat_awal_kg)==2500 and len(u.pemindahan_karung)==1
@pytest.mark.parametrize('kind',['broken','medium','menir','reject'])
async def test_asal_hasil_sendiri_ditolak_utuh(pg,proses,kind):
 await isi(pg,proses)
 async with pg() as db:
  s=await g2.get_g2_silo(db,'A');now=now_local();kw=dict(silo_id=s.id,berat_kg=100,tanggal=now.date(),waktu=now,input_by=proses['user'].id)
  if kind=='broken':
   bp=ByproductStock(jenis_produk='broken',source_type='polishing',source_id=proses['pid'],berat_kg=100,tanggal=now.date(),waktu=now,input_by=proses['user'].id);db.add(bp);await db.flush();db.add(BrokenKeSilo(kode_pindah='BKS-UJI',byproduct_stock_id=bp.id,**kw))
  else:db.add((BerasKeSilo if kind=='medium' else HasilSampingKeSilo)(kode_pindah='HAS-UJI',polishing_process_id=proses['pid'],jenis=kind,**kw))
  await db.commit()
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);d=(await baca(c,proses)).json();assert d['silos'][0]['hasil_sendiri'];assert await fakta(pg)==before
  r=await simpan(c,proses,['Timur','A']);assert r.status_code==400 and 'sendiri' in r.text;assert await fakta(pg)==before
async def test_dijeda_hasil_dan_silo_tidak_diubah(pg,proses):
 from app.penggilingan.gudang1.services.jeda import hentikan,jeda_terbuka
 async with pg() as db:
  u=await db.get(User,proses['user'].id);await p.catat_output(db,user=u,kode=proses['kode'],jenis='medium',berat_kumulatif=1000);await hentikan(db,user=u,jenis='penyosohan',kode=proses['kode'],sebab='Listrik padam')
 async with await _klien(pg,peran='admin') as c:
  d=(await baca(c,proses)).json();assert d['status']=='dijeda';assert (await simpan(c,proses)).status_code==200
 async with pg() as db:
  pr=await db.get(PolishingProcess,proses['pid']);assert pr.status=='proses' and pr.waktu_selesai is None;assert await jeda_terbuka(db,'penyosohan',pr.id)
  logs=(await db.scalars(select(PolishingOutputLog))).all();assert len(logs)==1 and float(logs[0].berat_kg)==1000
async def test_konkurensi_satu_sumber_satu_pemakaian(pg,proses):
 async def tambah():
  async with pg() as db:
   u=await db.get(User,proses['user'].id)
   try:await p.tambah_silo_penyosohan(db,user=u,kode=proses['kode'],nama_silos=['A']);return 'ok'
   except p.Gudang2Error:await db.rollback();return 'ditolak'
 assert sorted(await asyncio.gather(tambah(),tambah()))==['ditolak','ok']
 async with pg() as db:assert await db.scalar(select(func.count()).select_from(PolishingSiloUsage))==2
async def test_gagal_tengah_transaksi_rollback(pg,proses,monkeypatch):
 await isi(pg,proses);before=await fakta(pg);asli=p._ikat_sumber_karung;calls=0
 async def gagal(*args,**kw):
  nonlocal calls
  calls+=1
  if calls==2:raise RuntimeError('kegagalan uji terisolasi')
  return await asli(*args,**kw)
 monkeypatch.setattr(p,'_ikat_sumber_karung',gagal)
 async with pg() as db:
  u=await db.get(User,proses['user'].id)
  with pytest.raises(RuntimeError):await p.tambah_silo_penyosohan(db,user=u,kode=proses['kode'],nama_silos=['A','Timur'])
  await db.rollback()
 assert await fakta(pg)==before
@pytest.mark.parametrize('role,view,gudang,izin',[('operator',None,'Gudang 2',True),('admin',None,'Gudang 2',True),('superadmin',None,'Gudang 2',True),('admin','operator:g2','Gudang 2',True),('operator',None,'Gudang 1',False),('admin','operator:g1','Gudang 1',False),('staff',None,'Gudang 2',False)])
async def test_akses_efektif_daftar_ringkasan_endpoint(pg,proses,role,view,gudang,izin):
 from app.web.lihat_sebagai import NAMA_KUKI
 async with await _klien(pg,peran=role,gudang=gudang) as c:
  if view:c.cookies.set(NAMA_KUKI,view)
  before=await fakta(pg);assert (await c.get('/api/actions/silo-bahan-g2',params={'induk':proses['kode'],'rincian':'true'})).status_code==(200 if izin else 403);assert (await baca(c,proses)).status_code==(200 if izin else 403);assert (await simpan(c,proses)).status_code==(200 if izin else 403)
  if not izin:assert await fakta(pg)==before
async def test_anonim_csrf_dan_proses_hilang(pg,proses):
 import httpx
 from app.main import app
 async with await _klien(pg,peran='admin') as c:
  assert (await c.post('/api/actions/tambah-silo-penyosohan',json={'kode':proses['kode'],'silo':['A']})).status_code==403
  assert (await baca(c,dict(kode='tidak-ada'))).status_code==409
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:assert (await baca(c,proses)).status_code==401
async def test_konflik_proses_lain_tidak_menambah_pilihan_lain(pg,proses):
 await isi(pg,proses)
 async with pg() as db:
  u=await db.get(User,proses['user'].id);await p.mulai_penyosohan(db,user=u,nama_silos=['A'])
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);assert (await simpan(c,proses,['Timur','A'])).status_code==400;assert await fakta(pg)==before
  assert 'A' not in [x['value'] for x in (await c.get('/api/actions/silo-bahan-g2',params={'induk':proses['kode']})).json()]
async def test_proses_selesai_tetap_ditolak(pg,proses):
 async with pg() as db:
  u=await db.get(User,proses['user'].id);await p.catat_output(db,user=u,kode=proses['kode'],jenis='medium',berat_kumulatif=1000);await p.selesai_penyosohan(db,user=u,kode=proses['kode'],nama_silo='B',sisa_kg=0);await p.akhiri_penyosohan(db,user=u,kode=proses['kode'])
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);r=await simpan(c,proses);assert r.status_code==400 and 'selesai' in r.text;assert await fakta(pg)==before
async def test_komposisi_campuran_dari_proses_lain_tetap_sah(pg,proses):
 async with pg() as db:
  now=now_local();old=PolishingProcess(kode_proses='POL-ASAL-LAMA',status='selesai',waktu_mulai=now,waktu_selesai=now,created_by=proses['user'].id);db.add(old);await db.flush();s=await g2.get_g2_silo(db,'A');kw=dict(silo_id=s.id,berat_kg=100,tanggal=now.date(),waktu=now,input_by=proses['user'].id)
  bp=ByproductStock(jenis_produk='broken',source_type='polishing',source_id=old.id,berat_kg=100,tanggal=now.date(),waktu=now,input_by=proses['user'].id);db.add(bp);await db.flush();db.add(BrokenKeSilo(kode_pindah='BKS-ASAL',byproduct_stock_id=bp.id,**kw));db.add(BerasKeSilo(kode_pindah='BRS-ASAL',polishing_process_id=old.id,jenis='medium',**kw))
  for j in ['menir','reject']:db.add(HasilSampingKeSilo(kode_pindah='HSS-'+j,polishing_process_id=old.id,jenis=j,**kw))
  await db.commit()
 async with await _klien(pg,peran='admin') as c:
  d=(await baca(c,proses)).json();assert d['tambahan']=='5.400 kg';assert set(x['jenis'] for x in d['silos'][0]['komposisi'])=={'PK','Beras olah ulang','Broken','Menir','Reject'};assert (await simpan(c,proses)).status_code==200
 async with pg() as db:
  a=await g2.get_g2_silo(db,'A');u=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.silo_id==a.id));assert float(u.berat_awal_kg)==5400
