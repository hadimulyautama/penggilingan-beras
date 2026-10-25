"""Pembebasan G2: token satu siklus, sisa fisik, stok dan proses independen."""
import asyncio
from decimal import Decimal
import pytest
from sqlalchemy import select,func
from app.models import (User,PolishingProcess,PolishingSiloUsage,PolishingOutputLog,ActivityLog,Silo,JedaProses,JedaCatatan,PkPurchaseBatch)
from app.penggilingan.gudang2 import polishing as p,service as g2
from tests.pg.test_form_selesai_penyosohan import proses,fakta
from tests.pg.test_gudang2_operator_pg import gudang2
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir
from app.services.penyelesaian_proses import ringkasan_bebaskan
pytestmark=pytest.mark.asyncio
async def baca(c,k,s='B',n=None):
 q=dict(kode_proses=k,silo=s)
 if n is not None:q['sisa']=n
 return await c.get('/api/actions/ringkasan-bebaskan-silo-sosoh',params=q)
async def preview(c,k,s='B',n=500):return await c.get('/api/actions/pratinjau-bebaskan-silo',params=dict(jenis='sosoh',kode_proses=k,silo=s,sisa=n))
async def simpan(c,k,s='B',n=500,dasar=''):
 return await c.post('/api/actions/selesai-penyosohan',json=dict(kode_proses=k,silo=s,sisa=n,dasar=dasar),headers={'X-CSRF-Token':cap_formulir(c)})
async def stock(pg,s='B'):
 async with pg() as db:return await g2.hitung_stok_silo(db,(await g2.get_g2_silo(db,s)).id)
async def test_tiga_field_konteks_baca_saja_dan_daftar_lama(pg,proses):
 async with await _klien(pg,peran='admin') as c:
  old=await fakta(pg);a=next(x for x in (await c.get('/api/actions/menu')).json() if x['id']=='selesai_penyosohan');assert [f['name'] for f in a['fields']]==['kode_proses','silo','sisa'];assert a['fields'][2]['label']=='Sisa fisik di silo';assert a['fields'][1]['induk']=='kode_proses';assert a['post']=='/api/actions/selesai-penyosohan'
  assert (await c.get('/api/actions/sosoh-silo')).json()==[]
  options=(await c.get('/api/actions/sosoh-silo',params={'induk':proses['kode']})).json();assert [x['value'] for x in options]==['B']
  r=await baca(c,proses['kode']);assert r.status_code==200 and r.headers['cache-control']=='no-store';d=r.json();assert d['awal']==9800 and d['tambahan']==0 and d['sisa'] is None and d['terpakai'] is None
  pr=await preview(c,proses['kode']);assert pr.status_code==200;assert set(pr.json())=={'dasar','teks','rincian'};assert await fakta(pg)==old
@pytest.mark.parametrize('n',[0,500,9800,500.25])
async def test_sisa_nol_positif_sama_seluruh_bahan_dan_desimal(pg,proses,n):
 async with await _klien(pg,peran='admin') as c:
  d=(await preview(c,proses['kode'],n=n)).json();assert d['rincian']['terpakai']==9800-n
  r=await simpan(c,proses['kode'],n=n,dasar=d['dasar']);assert r.status_code==200,r.text
  r=await simpan(c,proses['kode'],n=0,dasar=d['dasar']);assert r.status_code==400 and 'Admin' in r.text
  assert (await c.get('/api/actions/sosoh-silo',params={'induk':proses['kode']})).json()==[]
 async with pg() as db:
  pr=await db.get(PolishingProcess,proses['pid']);us=await db.scalar(select(PolishingSiloUsage));assert pr.status=='proses' and pr.waktu_selesai is None
  assert float(us.berat_akhir_kg)==n and float(us.berat_terpakai_kg)==9800-n
  assert await db.scalar(select(func.count()).select_from(PolishingOutputLog))==0
  audit=await db.scalar(select(ActivityLog).where(ActivityLog.aksi=='tutup_silo_sosoh'));assert audit.record_id==us.id and audit.changed_by and float(audit.new_value)==n
 assert await stock(pg)==n
@pytest.mark.parametrize('n',[None,-1,'NaN','Infinity','tidak-sah',9801])
async def test_penolakan_tidak_mengubah_pemakaian(pg,proses,n):
 async with await _klien(pg,peran='admin') as c:
  old=await fakta(pg);r=await simpan(c,proses['kode'],n=n,dasar='dasar-tidak-sah');assert r.status_code in [409,422,400];assert await fakta(pg)==old
async def test_kompatibel_silo_tidak_disebut_dan_multi_tidak_acak(pg,proses):
 async with await _klien(pg,peran='admin') as c:
  d=(await preview(c,proses['kode'],s='')).json();assert d['rincian']['silo']=='Silo B';assert (await simpan(c,proses['kode'],s='',dasar=d['dasar'])).status_code==200
 async with pg() as db:
  u=await db.get(User,proses['user'].id);await p.tambah_silo_penyosohan(db,user=u,kode=proses['kode'],nama_silos=['B'])
  await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=proses['intake_tumpukan'],nama_silo='A',berat=1000)
  await p.tambah_silo_penyosohan(db,user=u,kode=proses['kode'],nama_silos=['A'])
 async with await _klien(pg,peran='admin') as c:
  old=await fakta(pg);assert (await preview(c,proses['kode'],s='')).status_code==409;assert await fakta(pg)==old
async def test_tambahan_dan_siklus_lama_tidak_terhitung_ulang(pg,proses):
 async with pg() as db:
  u=await db.get(User,proses['user'].id);await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=proses['intake_tumpukan'],nama_silo='B',berat=1000)
 async with await _klien(pg,peran='admin') as c:
  d=(await preview(c,proses['kode'],n=800)).json();assert d['rincian']['awal']==9800 and d['rincian']['tambahan']==1000 and d['rincian']['terpakai']==10000
  assert (await simpan(c,proses['kode'],n=800,dasar=d['dasar'])).status_code==200
 async with pg() as db:
  u=await db.get(User,proses['user'].id);await p.tambah_silo_penyosohan(db,user=u,kode=proses['kode'],nama_silos=['B'])
 async with await _klien(pg,peran='admin') as c:
  d=(await preview(c,proses['kode'],n=300)).json();x=d['rincian'];assert x['awal']==800 and x['tambahan']==0 and x['terpakai']==500 and len(x['sumber'])==2;assert x['pemakaian_id']==x['sumber'][1]['id']
  assert (await simpan(c,proses['kode'],n=300,dasar=d['dasar'])).status_code==200
 assert await stock(pg)==300
async def test_silo_campuran_nama_master_dan_proses_dijeda(pg,proses):
 async with pg() as db:
  pr=await db.get(PolishingProcess,proses['pid']);u=await db.get(User,proses['user'].id);si=await g2.get_g2_silo(db,'B');si.nama_silo='Tong Campuran Timur';si.jenis_isi='campuran';await db.commit()
  from app.penggilingan.gudang1.services.jeda import hentikan
  await hentikan(db,user=u,jenis='penyosohan',kode=pr.kode_proses,sebab='Listrik padam')
 async with await _klien(pg,peran='admin') as c:
  d=(await preview(c,proses['kode'],s='Tong Campuran Timur')).json();assert d['rincian']['status']=='dijeda'
  assert (await simpan(c,proses['kode'],s='Tong Campuran Timur',dasar=d['dasar'])).status_code==200
 async with pg() as db:
  assert (await db.scalar(select(JedaProses))).selesai is None
  assert (await db.scalars(select(JedaCatatan.aksi))).all()==['hentikan']
  u=await db.get(User,proses['user'].id);await p.catat_output(db,user=u,kode=proses['kode'],jenis='medium',berat_kumulatif=500)
  assert (await db.get(PolishingProcess,proses['pid'])).status=='proses'
@pytest.mark.parametrize('kind',['bobot','siklus','hasil'])
async def test_token_memakaian_berubah_ditolak_hasil_saja_tidak(pg,proses,kind):
 async with await _klien(pg,peran='admin') as c:
  d=(await preview(c,proses['kode'])).json()
  async with pg() as db:
   u=await db.get(User,proses['user'].id)
   if kind=='hasil':await p.catat_output(db,user=u,kode=proses['kode'],jenis='medium',berat_kumulatif=500)
   elif kind=='bobot':await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=proses['intake_tumpukan'],nama_silo='B',berat=1000)
   else:
    await p.selesai_penyosohan(db,user=u,kode=proses['kode'],nama_silo='B',sisa_kg=500)
    await p.tambah_silo_penyosohan(db,user=u,kode=proses['kode'],nama_silos=['B'])
  old=await fakta(pg);r=await simpan(c,proses['kode'],dasar=d['dasar']);assert r.status_code==(200 if kind=='hasil' else 400),r.text
  if kind!='hasil':assert await fakta(pg)==old
async def test_konkuren_satu_catatan_saja(pg,proses):
 async with pg() as db:d=await ringkasan_bebaskan(db,jenis='sosoh',kode=proses['kode'],silo='B',sisa=500)
 async def run():
  async with pg() as db:
   try:await p.selesai_penyosohan(db,user=await db.get(User,proses['user'].id),kode=proses['kode'],nama_silo='B',sisa_kg=500,dasar=d['dasar']);return 'ok'
   except p.Gudang2Error:await db.rollback();return 'ditolak'
 assert sorted(await asyncio.gather(run(),run()))==['ditolak','ok'];assert await stock(pg)==500
 async with pg() as db:assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='tutup_silo_sosoh'))==1
async def test_rollback_status_silo_audit_dan_sisa(pg,proses,monkeypatch):
 async def gagal(*a,**kw):raise RuntimeError('kegagalan uji')
 before=await fakta(pg);stok=await stock(pg);monkeypatch.setattr(g2,'segarkan_status_silo',gagal)
 async with pg() as db:
  with pytest.raises(RuntimeError):await p.selesai_penyosohan(db,user=await db.get(User,proses['user'].id),kode=proses['kode'],nama_silo='B',sisa_kg=500)
  await db.rollback()
 assert await fakta(pg)==before and await stock(pg)==stok
async def test_pemakaian_kosong_sah_dan_isian_baru_tetap_utuh(pg,proses):
 async with pg() as db:
  u=await db.get(User,proses['user'].id);await p.selesai_penyosohan(db,user=u,kode=proses['kode'],nama_silo='B',sisa_kg=0)
  # Pembukaan ulang kosong memang didukung layanan lama, tanpa bahan baru.
  await p.tambah_silo_penyosohan(db,user=u,kode=proses['kode'],nama_silos=['B'])
 async with await _klien(pg,peran='admin') as c:
  d=(await preview(c,proses['kode'],n=0)).json();assert d['rincian']['bahan']==0;assert (await simpan(c,proses['kode'],n=0,dasar=d['dasar'])).status_code==200
 async with pg() as db:
  u=await db.get(User,proses['user'].id);await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=proses['intake_tumpukan'],nama_silo='B',berat=1000)
  assert all(x.berat_akhir_kg==0 for x in (await db.scalars(select(PolishingSiloUsage))).all())
 assert await stock(pg)==1000
@pytest.mark.parametrize('role,view,gudang,izin',[('operator',None,'Gudang 2',True),('admin',None,'Gudang 2',True),('superadmin',None,'Gudang 2',True),('admin','operator:g2','Gudang 2',True),('operator',None,'Gudang 1',False),('admin','operator:g1','Gudang 1',False),('staff',None,'Gudang 2',False)])
async def test_akses_efektif_sumber_reader_preview_simpan(pg,proses,role,view,gudang,izin):
 from app.web.lihat_sebagai import NAMA_KUKI
 async with await _klien(pg,peran=role,gudang=gudang) as c:
  if view:c.cookies.set(NAMA_KUKI,view)
  before=await fakta(pg);assert (await baca(c,proses['kode'])).status_code==(200 if izin else 403)
  assert (await c.get('/api/actions/sosoh-silo',params={'induk':proses['kode']})).status_code==(200 if izin else 403)
  r=await preview(c,proses['kode']);assert r.status_code==(200 if izin else 403)
  assert (await simpan(c,proses['kode'],dasar=r.json()['dasar'] if izin else 'x')).status_code==(200 if izin else 403)
  if not izin:assert await fakta(pg)==before
async def test_anonim_csrf_proses_selesai_dan_referensi_salah(pg,proses):
 import httpx
 from app.main import app
 async with await _klien(pg,peran='admin') as c:
  assert (await c.post('/api/actions/selesai-penyosohan',json=dict(kode_proses=proses['kode'],silo='B',sisa=0,dasar='x'))).status_code==403
  before=await fakta(pg);assert (await baca(c,'tidak-ada')).status_code==409;assert (await preview(c,proses['kode'],s='silo-lain')).status_code==409;assert await fakta(pg)==before
 async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:assert (await baca(c,proses['kode'])).status_code==401
async def test_sumber_karung_dinamis_berubah_setelah_pembebasan(pg,proses):
 from app.database import now_local
 async with pg() as db:
  u=await db.get(User,proses['user'].id);supplier=await db.scalar(select(PkPurchaseBatch.supplier_id).limit(1));now=now_local()
  b=PkPurchaseBatch(kode_batch='PKB-BSP-DINAMIS',supplier_id=supplier,jumlah_karung=100,ukuran_karung_kg=50,berat_total_kg=None,sumber_berat='menunggu',tanggal_pembelian=now.date(),waktu_pembelian=now,input_by=u.id)
  db.add(b);db.add(Silo(nama_silo='Silo Timur',warehouse_id=u.default_warehouse_id,jenis_isi='campuran'));await db.commit()
  it=(await g2.masukkan_pk_luar(db,user=u,kode=b.kode_batch)).intake
  await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=proses['intake_tumpukan'],nama_silo='Timur',berat=100)
  await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo='Timur',jumlah_karung=50)
  pr=(await p.mulai_penyosohan(db,user=u,nama_silos=['Timur'])).proc;kode=pr.kode_proses;pid=pr.id
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);d=(await baca(c,kode,'Timur')).json();assert d['awal'] is None and d['bahan'] is None and not d['bobot_final'];assert await fakta(pg)==before
 async with pg() as db:
  b=await db.scalar(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch=='PKB-BSP-DINAMIS'));b.berat_total_kg=4800;b.sumber_berat='perkiraan';await db.commit()
 async with await _klien(pg,peran='admin') as c:
  d=(await preview(c,kode,'Timur',300)).json();assert d['rincian']['bahan']==2500 and not d['rincian']['bobot_final'];assert (await simpan(c,kode,'Timur',300,d['dasar'])).status_code==200
 async with pg() as db:
  b=await db.scalar(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch=='PKB-BSP-DINAMIS'));b.berat_total_kg=5000;b.sumber_berat='timbangan';await db.commit()
 async with pg() as db:
  us=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==pid));assert us.bobot_karung_dinamis and float(us.berat_awal_kg)==2600 and float(us.berat_terpakai_kg)==2300 and us.berat_akhir_kg==300
  assert await g2.hitung_stok_silo(db,us.silo_id)==300
async def test_pemakaian_lain_dan_hasil_tidak_berubah(pg,proses):
 async with pg() as db:
  u=await db.get(User,proses['user'].id);await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=proses['intake_tumpukan'],nama_silo='A',berat=1000);await p.tambah_silo_penyosohan(db,user=u,kode=proses['kode'],nama_silos=['A']);await p.catat_output(db,user=u,kode=proses['kode'],jenis='medium',berat_kumulatif=200)
 async with await _klien(pg,peran='admin') as c:
  d=(await preview(c,proses['kode'])).json();assert len(d['rincian']['sumber'])==2;assert (await simpan(c,proses['kode'],dasar=d['dasar'])).status_code==200
 async with pg() as db:
  a=await g2.get_g2_silo(db,'A');us=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.silo_id==a.id));assert us.berat_akhir_kg is None and us.berat_terpakai_kg is None;assert await g2.hitung_stok_silo(db,a.id)==1000
  out=(await db.scalars(select(PolishingOutputLog))).all();assert len(out)==1 and out[0].berat_kg==200
async def test_proses_selesai_tetap_ditolak(pg,proses):
 async with pg() as db:
  u=await db.get(User,proses['user'].id);await p.selesai_penyosohan(db,user=u,kode=proses['kode'],nama_silo='B',sisa_kg=0);await p.catat_output(db,user=u,kode=proses['kode'],jenis='medium',berat_kumulatif=1000);await p.akhiri_penyosohan(db,user=u,kode=proses['kode'])
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);assert (await preview(c,proses['kode'])).status_code==409;assert (await simpan(c,proses['kode'],dasar='x')).status_code==400;assert await fakta(pg)==before
