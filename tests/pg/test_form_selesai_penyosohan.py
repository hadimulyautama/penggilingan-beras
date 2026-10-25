"""Penutupan G2: konteks baca saja, pemeriksaan server, saldo dan siklus nyata."""
import asyncio
from decimal import Decimal
import pytest
from sqlalchemy import select,func
from app.models import User,PolishingProcess,PolishingSiloUsage,PolishingOutputLog,ActivityLog,Jasa,ByproductStock,FinishedGoodsStock,Warehouse
from app.penggilingan.gudang2 import polishing as p,service as g2
from tests.pg.test_gudang2_operator_pg import gudang2
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir
from app.services.penyelesaian_proses import ringkasan_selesai
pytestmark=pytest.mark.asyncio

@pytest.fixture
async def proses(pg,gudang2):
 async with pg() as db:
  db.add(Warehouse(nama_gudang='Gudang 1 - Uji',kode_fungsi='g1'));await db.commit();u=await db.get(User,gudang2['user'].id);pr=(await p.mulai_penyosohan(db,user=u,nama_silos=['B'])).proc
 return dict(gudang2,kode=pr.kode_proses,pid=pr.id)
async def siap(pg,w,hasil=8000,sisa=500):
 async with pg() as db:
  u=await db.get(User,w['user'].id)
  await p.catat_output(db,user=u,kode=w['kode'],jenis='medium',berat_kumulatif=hasil)
  await p.selesai_penyosohan(db,user=u,kode=w['kode'],nama_silo='B',sisa_kg=sisa)
async def baca(c,k):return await c.get('/api/actions/ringkasan-selesai-penyosohan',params={'kode_proses':k})
async def preview(c,k):return await c.get('/api/actions/pratinjau-selesai-proses',params={'jenis':'sosoh','kode_proses':k})
async def kirim(c,k,d):return await c.post('/api/actions/akhiri-penyosohan',json={'kode_proses':k,'dasar':d},headers={'X-CSRF-Token':cap_formulir(c)})
async def fakta(pg):
 async with pg() as db:
  tables=[PolishingProcess,PolishingSiloUsage,PolishingOutputLog,ActivityLog,ByproductStock,FinishedGoodsStock,Jasa]
  from hmu_core.proses_db import ProsesTerpadu
  tables.append(ProsesTerpadu)
  return {m.__tablename__:[tuple(getattr(r,col.name) for col in m.__table__.columns) for r in (await db.scalars(select(m).order_by(m.id))).all()] for m in tables}
async def test_satu_field_konteks_murni_dan_semua_jenis(pg,proses):
 async with await _klien(pg,peran='admin') as c:
  old=await fakta(pg);a=next(x for x in (await c.get('/api/actions/menu')).json() if x['id']=='akhiri_penyosohan');assert [f['name'] for f in a['fields']]==['kode_proses'];assert a['pratinjau_proses']=='sosoh'
  r=await baca(c,proses['kode']);assert r.status_code==200,r.text;d=r.json();assert r.headers['cache-control']=='no-store';assert not d['sisa_lengkap'] and d['sumber'][0]['sisa'] is None
  assert d['beras'] is None and not d['ada_hasil'] and d['rendemen'] is None and all(x['kg'] is None for x in d['hasil']);assert len(d['hasil'])==9
  assert (await preview(c,proses['kode'])).status_code==409;assert await fakta(pg)==old
async def test_agregat_beras_b_rendemen_stok_dan_packing_tetap(pg,proses):
 await siap(pg,proses)
 async with pg() as db:
  u=await db.get(User,proses['user'].id)
  for j,n in [('medium',8100),('beras_b',200),('bekatul',100)]:await p.catat_output(db,user=u,kode=proses['kode'],jenis=j,berat_kumulatif=n)
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);r=await preview(c,proses['kode']);assert r.status_code==200,r.text;d=r.json();assert set(d)>={'dasar','teks','rincian'};assert await fakta(pg)==before
  x=d['rincian'];assert x['beras']==8300 and x['samping']==100 and x['total']==8400 and x['selisih']==900
  assert x['rendemen']==pytest.approx(8300/9300*100)
  async with pg() as db:
   assert x['rendemen']==await p.rendemen_proses(db,proses['pid'])
   from app.services.stok import output_sosoh
   assert await output_sosoh(db,proses['pid'])=={'medium':8100,'beras_b':200,'bekatul':100}
  assert (await kirim(c,proses['kode'],d['dasar'])).status_code==200
  assert (await kirim(c,proses['kode'],d['dasar'])).status_code==409
 async with pg() as db:
  pr=await db.get(PolishingProcess,proses['pid']);assert pr.status=='selesai' and pr.waktu_selesai
  assert await g2.hitung_stok_silo(db,(await g2.get_g2_silo(db,'B')).id)==500
  assert await db.scalar(select(func.count()).select_from(PolishingOutputLog))==4
  assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='akhiri_penyosohan'))==1
  from app.services.stok import output_sosoh
  assert await output_sosoh(db,pr.id)=={'medium':8100,'beras_b':200,'bekatul':100}
@pytest.mark.parametrize('kind',['hasil','siklus','bobot'])
async def test_perubahan_dasar_tidak_menutup_atau_mengubah_sebagian(pg,proses,kind):
 await siap(pg,proses)
 async with await _klien(pg,peran='admin') as c:
  d=(await preview(c,proses['kode'])).json()
  async with pg() as db:
   u=await db.get(User,proses['user'].id)
   if kind=='hasil':await p.catat_output(db,user=u,kode=proses['kode'],jenis='medium',berat_kumulatif=8100)
   elif kind=='bobot':r=await db.scalar(select(PolishingSiloUsage));r.berat_masuk_kg=100;await db.commit()
   else:
    r=await db.scalar(select(PolishingSiloUsage));db.add(PolishingSiloUsage(polishing_process_id=proses['pid'],silo_id=r.silo_id,berat_awal_kg=100,berat_masuk_kg=0,berat_akhir_kg=0,berat_terpakai_kg=100));await db.commit()
  before=await fakta(pg);r=await kirim(c,proses['kode'],d['dasar']);assert r.status_code==409 and 'berubah' in r.text;assert await fakta(pg)==before
@pytest.mark.parametrize('delta,ok',[(0,True),(.001,True),(.002,False)])
async def test_toleransi_lama_sama_bahan_dan_hasil_samping_saja(pg,proses,delta,ok):
 async with pg() as db:
  u=await db.get(User,proses['user'].id);await p.catat_output(db,user=u,kode=proses['kode'],jenis='bekatul',berat_kumulatif=9300);await p.selesai_penyosohan(db,user=u,kode=proses['kode'],nama_silo='B',sisa_kg=500)
  row=await db.scalar(select(PolishingSiloUsage));row.berat_awal_kg=Decimal('9800')-Decimal(str(delta));row.berat_terpakai_kg=Decimal('9300')-Decimal(str(delta));await db.commit()
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);r=await preview(c,proses['kode']);assert r.status_code==(200 if ok else 409),r.text
  if ok:assert (await kirim(c,proses['kode'],r.json()['dasar'])).status_code==200
  else:assert await fakta(pg)==before
async def test_seluruh_siklus_tambahan_refill_tidak_hilang(pg,proses):
 async with pg() as db:
  u=await db.get(User,proses['user'].id);await p.selesai_penyosohan(db,user=u,kode=proses['kode'],nama_silo='B',sisa_kg=0)
  await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=proses['intake_tumpukan'],nama_silo='B',berat=1000)
  await p.tambah_silo_penyosohan(db,user=u,kode=proses['kode'],nama_silos=['B']);await p.catat_output(db,user=u,kode=proses['kode'],jenis='medium',berat_kumulatif=8000)
 async with await _klien(pg,peran='admin') as c:
  d=(await baca(c,proses['kode'])).json();assert len(d['sumber'])==2 and d['sumber'][0]['sisa']==0 and d['sumber'][1]['sisa'] is None
  assert (await preview(c,proses['kode'])).status_code==409
  async with pg() as db:
   u=await db.get(User,proses['user'].id);await p.selesai_penyosohan(db,user=u,kode=proses['kode'],nama_silo='B',sisa_kg=200)
   await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=proses['intake_tumpukan'],nama_silo='B',berat=300)
  d=(await preview(c,proses['kode'])).json();assert d['rincian']['bahan']=='10.600 kg';assert (await kirim(c,proses['kode'],d['dasar'])).status_code==200
 async with pg() as db:assert await g2.hitung_stok_silo(db,(await g2.get_g2_silo(db,'B')).id)==500
async def test_konkuren_satu_tutup_rollback_dan_audit(pg,proses):
 await siap(pg,proses)
 async with pg() as db:d=await ringkasan_selesai(db,jenis='sosoh',kode=proses['kode'])
 async def tutup():
  async with pg() as db:
   try:await p.akhiri_penyosohan(db,user=await db.get(User,proses['user'].id),kode=proses['kode'],dasar=d['dasar']);return 'ok'
   except p.Gudang2Error:await db.rollback();return 'ditolak'
 assert sorted(await asyncio.gather(tutup(),tutup()))==['ditolak','ok']
 async with pg() as db:assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='akhiri_penyosohan'))==1
@pytest.mark.parametrize('role,view,gudang,izin',[('operator',None,'Gudang 2',True),('admin',None,'Gudang 2',True),('superadmin',None,'Gudang 2',True),('admin','operator:g2','Gudang 2',True),('operator',None,'Gudang 1',False),('admin','operator:g1','Gudang 1',False),('staff',None,'Gudang 2',False)])
async def test_akses_efektif_reader_preview_dan_endpoint(pg,proses,role,view,gudang,izin):
 from app.web.lihat_sebagai import NAMA_KUKI
 await siap(pg,proses)
 async with await _klien(pg,peran=role,gudang=gudang) as c:
  if view:c.cookies.set(NAMA_KUKI,view)
  before=await fakta(pg);assert (await baca(c,proses['kode'])).status_code==(200 if izin else 403)
  r=await preview(c,proses['kode']);assert r.status_code==(200 if izin else 403)
  assert (await kirim(c,proses['kode'],r.json()['dasar'] if izin else 'palsu')).status_code==(200 if izin else 403)
  if not izin:assert await fakta(pg)==before
async def test_anonim_csrf_dan_tanpa_hasil(pg,proses):
 import httpx
 from app.main import app
 async with pg() as db:
  u=await db.get(User,proses['user'].id);await p.selesai_penyosohan(db,user=u,kode=proses['kode'],nama_silo='B',sisa_kg=0)
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);assert (await preview(c,proses['kode'])).status_code==409
  assert (await c.post('/api/actions/akhiri-penyosohan',json={'kode_proses':proses['kode'],'dasar':'x'})).status_code==403
  assert (await baca(c,'tidak-ada')).status_code==409;assert await fakta(pg)==before
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
  assert (await baca(c,proses['kode'])).status_code==401

async def test_gagal_di_tengah_rollback_status_jeda_dan_proyeksi(pg,proses,monkeypatch):
 await siap(pg,proses)
 from app.services import proses_bersama
 async def gagal(*a,**kw):raise RuntimeError('kegagalan uji terisolasi')
 before=await fakta(pg)
 monkeypatch.setattr(proses_bersama,'tutup_proses_bersama',gagal)
 async with pg() as db:
  with pytest.raises(RuntimeError):await p.akhiri_penyosohan(db,user=await db.get(User,proses['user'].id),kode=proses['kode'])
  await db.rollback()
 assert await fakta(pg)==before

async def test_jeda_ditutup_tanpa_lanjut_fiktif(pg,proses):
 from app.penggilingan.gudang1.services.jeda import jeda_terbuka
 from app.models import JedaProses,JedaCatatan
 async with pg() as db:
  pr=await db.get(PolishingProcess,proses['pid']);u=await db.get(User,proses['user'].id)
  from datetime import timedelta
  from app.database import now_local
  j=JedaProses(jenis='penyosohan',polishing_process_id=pr.id,mulai=now_local()-timedelta(minutes=1),sebab='Listrik padam',dicatat_oleh=u.id)
  db.add(j);await db.commit()
 await siap(pg,proses)
 async with await _klien(pg,peran='admin') as c:
  d=(await preview(c,proses['kode'])).json();assert d['rincian']['status']=='dijeda';assert (await kirim(c,proses['kode'],d['dasar'])).status_code==200
 async with pg() as db:
  assert await jeda_terbuka(db,'penyosohan',proses['pid']) is None
  assert (await db.scalars(select(JedaCatatan.aksi))).all()==['akhir_proses']

async def test_sumber_karung_belum_pasti_tetap_dinamis_dan_bukan_nol(pg,proses):
 from app.models import PkPurchaseBatch,Silo
 from app.database import now_local
 async with pg() as db:
  u=await db.get(User,proses['user'].id);supplier=await db.scalar(select(PkPurchaseBatch.supplier_id).limit(1));now=now_local()
  b=PkPurchaseBatch(kode_batch='PKB-DINAMIS-AKHIR',supplier_id=supplier,jumlah_karung=100,ukuran_karung_kg=50,berat_total_kg=None,sumber_berat='menunggu',tanggal_pembelian=now.date(),waktu_pembelian=now,input_by=u.id)
  db.add(b);db.add(Silo(nama_silo='Silo Timur',warehouse_id=u.default_warehouse_id,jenis_isi='pk'));await db.commit()
  it=(await g2.masukkan_pk_luar(db,user=u,kode=b.kode_batch)).intake
  await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=proses['intake_tumpukan'],nama_silo='Timur',berat=100)
  await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo='Timur',jumlah_karung=50)
  pr=(await p.mulai_penyosohan(db,user=u,nama_silos=['Timur'])).proc;kode=pr.kode_proses
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);d=(await baca(c,kode)).json();assert d['sumber'][0]['awal'] is None;assert d['sumber'][0]['terpakai'] is None;assert d['rendemen'] is None;assert not d['bobot_final'];assert await fakta(pg)==before
 async with pg() as db:
  u=await db.get(User,proses['user'].id);b=await db.scalar(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch=='PKB-DINAMIS-AKHIR'));b.berat_total_kg=4800;b.sumber_berat='perkiraan';await db.commit()
  await p.selesai_penyosohan(db,user=u,kode=kode,nama_silo='Timur',sisa_kg=0)
  await p.catat_output(db,user=u,kode=kode,jenis='medium',berat_kumulatif=2000)
 async with await _klien(pg,peran='admin') as c:
  r=await preview(c,kode);assert r.status_code==200,r.text;d=r.json();assert d['rincian']['bahan']=='± 2.500 kg';assert d['rincian']['rendemen'] is None
  assert (await kirim(c,kode,d['dasar'])).status_code==200
 async with pg() as db:
  b=await db.scalar(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch=='PKB-DINAMIS-AKHIR'));b.berat_total_kg=5000;b.sumber_berat='timbangan';await db.commit()
 async with await _klien(pg,peran='admin') as c:
  d=(await baca(c,kode)).json();assert d['bahan']=='2.600 kg' and d['rendemen']==pytest.approx(2000/2600*100) and d['bobot_final'] and d['status']=='selesai'
