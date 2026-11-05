"""Lembar kerja memakai layanan lama, tanpa mutasi saat membaca."""
import asyncio
import pytest
from sqlalchemy import select,func
from app.models import User,PolishingOutputLog,PolishingSiloUsage,PolishingProcess,ActivityLog
from app.penggilingan.gudang2 import polishing as p,service as g2
from tests.pg.test_gudang2_operator_pg import gudang2
from tests.pg.test_form_selesai_penyosohan import proses,siap,fakta
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir
pytestmark=pytest.mark.asyncio

def url(w,act=None,step=None):
 return '/api/actions/sosoh-ringkas/'+w['kode']+(f'/{act}/{step}' if act else '')
async def post(c,w,act,step,body):return await c.post(url(w,act,step),json=body,headers={'X-CSRF-Token':cap_formulir(c)})
async def preview(c,w,act,**kw):
 d=(await c.get(url(w))).json();body={'dasar':d['dasar'],**kw};r=await post(c,w,act,'periksa',body);assert r.status_code==200,r.text
 return {**body,'pemeriksaan':r.json()['pemeriksaan'],'konfirmasi':True}
async def totals(pg,w):
 async with pg() as db:return await p._output_map(db,w['pid'])

async def test_baca_tanpa_mutasi_semua_hasil_konteks_lama(pg,proses):
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);r=await c.get(url(proses));assert r.status_code==200,r.text;d=r.json()
  assert len(d['hasil'])==9 and all(h['kg'] is None for h in d['hasil']);assert not d['siap'] and d['penghalang'];assert d['sumber'][0]['id']
  assert r.headers['cache-control']=='no-store';assert await fakta(pg)==before
  for path in ['/proses-aktif/sosoh/','/proses-sosoh/']:
   r=await c.get(path+proses['kode']+'?buka=hasil_penyosohan');assert r.status_code==200,r.text
   assert 'data-sosoh-ringkas' in r.text and 'data-buka="hasil_penyosohan"' in r.text
  assert await fakta(pg)==before

async def test_kumulatif_noop_nol_semua_jenis_dan_jeda(pg,proses):
 from app.penggilingan.gudang1.services import jeda
 async with pg() as db:await jeda.hentikan(db,user=await db.get(User,proses['user'].id),jenis='penyosohan',kode=proses['kode'],sebab='Listrik padam')
 async with await _klien(pg,peran='admin') as c:
  b=await preview(c,proses,'hasil',hasil=[{'jenis':j,'total':100} for j in p._ALL_JENIS]);assert (await post(c,proses,'hasil','simpan',b)).status_code==200
  d=(await c.get(url(proses))).json();assert d['jeda'] and d['aktif'];assert all(x['kg']==100 for x in d['hasil'])
  b=await preview(c,proses,'hasil',hasil=[{'jenis':'medium','total':120},{'jenis':'premium','total':100}]);assert (await post(c,proses,'hasil','simpan',b)).status_code==200
  assert (await totals(pg,proses))['medium']==120
  async with pg() as db:assert await db.scalar(select(func.count()).select_from(PolishingOutputLog))==10
  before=await fakta(pg)
  for rows in [[{'jenis':'medium','total':120}],[{'jenis':'medium','total':110}],[{'jenis':'medium','total':-1}],[{'jenis':'medium','total':130},{'jenis':'medium','total':130}]]:
   d=(await c.get(url(proses))).json();r=await post(c,proses,'hasil','periksa',{'dasar':d['dasar'],'hasil':rows});assert r.status_code in (400,409),r.text;assert await fakta(pg)==before

async def test_nol_belum_tercatat_dan_atomic_gagal_jenis_kedua(pg,proses,monkeypatch):
 async with await _klien(pg,peran='admin') as c:
  b=await preview(c,proses,'hasil',hasil=[{'jenis':'medium','total':100},{'jenis':'premium','total':0}]);assert (await post(c,proses,'hasil','simpan',b)).status_code==200
  assert await totals(pg,proses)=={'medium':100}
  b=await preview(c,proses,'hasil',hasil=[{'jenis':'medium','total':120},{'jenis':'broken','total':20}]);before=await fakta(pg);original=p.catat_output
  async def fail(db,**kw):
   if kw['jenis']=='broken':raise p.Gudang2Error('Gagal uji pada jenis kedua')
   return await original(db,**kw)
  monkeypatch.setattr(p,'catat_output',fail)
  r=await post(c,proses,'hasil','simpan',b);assert r.status_code==409 and 'jenis kedua' in r.text;assert await fakta(pg)==before

@pytest.mark.parametrize('change',['hasil','sisa','bobot'])
async def test_snapshot_lama_ditolak_tanpa_perubahan_sebagian(pg,proses,change):
 async with await _klien(pg,peran='admin') as c:
  b=await preview(c,proses,'hasil',hasil=[{'jenis':'medium','total':100}])
  async with pg() as db:
   u=await db.get(User,proses['user'].id)
   if change=='hasil':await p.catat_output(db,user=u,kode=proses['kode'],jenis='medium',berat_kumulatif=10)
   elif change=='sisa':await p.selesai_penyosohan(db,user=u,kode=proses['kode'],nama_silo='B',sisa_kg=200)
   else:
    usage=await db.scalar(select(PolishingSiloUsage));usage.berat_masuk_kg=50;await db.commit()
  before=await fakta(pg);r=await post(c,proses,'hasil','simpan',b);assert r.status_code==409 and 'berubah' in r.text;assert await fakta(pg)==before

async def test_dua_kiriman_satu_pertambahan_dan_audit(pg,proses):
 async with await _klien(pg,peran='admin') as c:
  b=await preview(c,proses,'hasil',hasil=[{'jenis':'medium','total':100}])
  rs=await asyncio.gather(post(c,proses,'hasil','simpan',b),post(c,proses,'hasil','simpan',b));assert sorted(r.status_code for r in rs)==[200,409]
  assert await totals(pg,proses)=={'medium':100}
  async with pg() as db:assert await db.scalar(select(func.count()).select_from(PolishingOutputLog))==1

@pytest.mark.parametrize('sisa',[0,500])
async def test_bebaskan_terpisah_siklus_tepat_tetap_stok(pg,proses,sisa):
 async with await _klien(pg,peran='admin') as c:
  d=(await c.get(url(proses))).json();uid=d['sumber'][0]['id'];b=await preview(c,proses,'bebaskan',pemakaian_id=uid,sisa=sisa)
  assert (await post(c,proses,'bebaskan','simpan',b)).status_code==200
  d=(await c.get(url(proses))).json();assert d['aktif'] and d['sumber'][0]['sisa']==sisa and not d['ada_hasil']
  async with pg() as db:assert await g2.hitung_stok_silo(db,(await g2.get_g2_silo(db,'B')).id)==sisa
  before=await fakta(pg);assert (await post(c,proses,'bebaskan','simpan',b)).status_code==409;assert await fakta(pg)==before

async def test_mix_pemakaian_ulang_saldo_baru_dan_selesai(pg,proses):
 async with await _klien(pg,peran='admin') as c:
  d=(await c.get(url(proses))).json();b=await preview(c,proses,'bebaskan',pemakaian_id=d['sumber'][0]['id'],sisa=0);assert (await post(c,proses,'bebaskan','simpan',b)).status_code==200
  async with pg() as db:await g2.pindah_tumpukan_ke_silo(db,user=await db.get(User,proses['user'].id),intake_id=proses['intake_tumpukan'],nama_silo='B',berat=1000)
  b=await preview(c,proses,'mix',silos=['B']);assert (await post(c,proses,'mix','simpan',b)).status_code==200
  d=(await c.get(url(proses))).json();assert len(d['sumber'])==2 and d['sumber'][0]['sisa']==0 and d['sumber'][1]['awal']==1000
  b=await preview(c,proses,'hasil',hasil=[{'jenis':'medium','total':8000}]);assert (await post(c,proses,'hasil','simpan',b)).status_code==200
  b=await preview(c,proses,'bebaskan',pemakaian_id=d['sumber'][1]['id'],sisa=200);assert (await post(c,proses,'bebaskan','simpan',b)).status_code==200
  b=await preview(c,proses,'selesai');before=await totals(pg,proses);assert (await post(c,proses,'selesai','simpan',b)).status_code==200
  d=(await c.get(url(proses))).json();assert not d['aktif'] and d['petugas_selesai'];assert await totals(pg,proses)==before
  assert (await c.get('/proses-aktif/sosoh/'+proses['kode'])).status_code==200
  before=await fakta(pg);assert (await post(c,proses,'selesai','simpan',b)).status_code==409;assert await fakta(pg)==before

@pytest.mark.parametrize('role,view,gudang,allowed',[('admin',None,'Gudang 2',True),('superadmin',None,'Gudang 2',True),('operator',None,'Gudang 2',True),('admin','operator:g2','Gudang 2',True),('operator',None,'Gudang 1',False),('admin','operator:g1','Gudang 1',False),('staff',None,'Gudang 2',False)])
async def test_izin_efektif_semua_endpoint(pg,proses,role,view,gudang,allowed):
 from app.web.lihat_sebagai import NAMA_KUKI
 async with await _klien(pg,peran=role,gudang=gudang) as c:
  if view:c.cookies.set(NAMA_KUKI,view)
  before=await fakta(pg);r=await c.get(url(proses));assert r.status_code==(200 if allowed else 403),r.text
  assert (await c.get('/proses-aktif/sosoh/'+proses['kode'])).status_code==(200 if allowed else 403)
  body={'dasar':r.json()['dasar'] if allowed else 'palsu','hasil':[{'jenis':'medium','total':10}]}
  r=await post(c,proses,'hasil','periksa',body);assert r.status_code==(200 if allowed else 403),r.text
  assert await fakta(pg)==before

async def test_csrf_cap_konfirmasi_dan_jenis_palsu(pg,proses):
 async with await _klien(pg,peran='admin') as c:
  d=(await c.get(url(proses))).json();body={'dasar':d['dasar'],'hasil':[{'jenis':'medium','total':10}]};before=await fakta(pg)
  assert (await c.post(url(proses,'hasil','simpan'),json=body)).status_code==403
  assert (await post(c,proses,'hasil','simpan',body)).status_code==409
  body['hasil'][0]['jenis']='palsu';assert (await post(c,proses,'hasil','periksa',body)).status_code==400
  b=await preview(c,proses,'hasil',hasil=[{'jenis':'medium','total':10}]);b['hasil'][0]['total']=20;assert (await post(c,proses,'hasil','simpan',b)).status_code==409
  assert await fakta(pg)==before

async def test_mix_saldo_berubah_memerlukan_konfirmasi_baru_dan_tetap_jeda(pg,proses):
 from app.penggilingan.gudang1.services import jeda
 async with pg() as db:
  u=await db.get(User,proses['user'].id);await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=proses['intake_tumpukan'],nama_silo='A',berat=1000)
  await jeda.hentikan(db,user=u,jenis='penyosohan',kode=proses['kode'],sebab='Listrik padam')
 async with await _klien(pg,peran='admin') as c:
  b=await preview(c,proses,'mix',silos=['A'])
  async with pg() as db:await g2.pindah_tumpukan_ke_silo(db,user=await db.get(User,proses['user'].id),intake_id=proses['intake_tumpukan'],nama_silo='A',berat=200)
  before=await fakta(pg);assert (await post(c,proses,'mix','simpan',b)).status_code==409;assert await fakta(pg)==before
  b=await preview(c,proses,'mix',silos=['A']);assert (await post(c,proses,'mix','simpan',b)).status_code==200
  d=(await c.get(url(proses))).json();assert d['jeda'] and d['aktif'] and not d['ada_hasil'];assert d['sumber'][1]['awal']==1200

async def test_siklus_salah_dan_sisa_tidak_sah(pg,proses):
 async with await _klien(pg,peran='admin') as c:
  d=(await c.get(url(proses))).json();before=await fakta(pg)
  for uid,sisa in [(99999,0),(d['sumber'][0]['id'],-1),(d['sumber'][0]['id'],9801)]:
   r=await post(c,proses,'bebaskan','periksa',{'dasar':d['dasar'],'pemakaian_id':uid,'sisa':sisa});assert r.status_code==409;assert await fakta(pg)==before

async def test_akhir_penghalang_dan_tidak_mengurangi_stok_kedua(pg,proses):
 async with await _klien(pg,peran='admin') as c:
  d=(await c.get(url(proses))).json();assert not d['siap']
  assert (await post(c,proses,'selesai','periksa',{'dasar':d['dasar']})).status_code==409
  await siap(pg,proses,hasil=9500,sisa=500)
  d=(await c.get(url(proses))).json();assert not d['siap'] and 'melebihi' in d['penghalang']
  before=await fakta(pg);assert (await post(c,proses,'selesai','periksa',{'dasar':d['dasar']})).status_code==409;assert await fakta(pg)==before

async def test_bobot_dinamis_belum_final_bukan_nol_dan_snapshot_angka_asli(pg,proses):
 from app.models import PkPurchaseBatch,Silo
 from app.database import now_local
 async with pg() as db:
  u=await db.get(User,proses['user'].id);supplier=await db.scalar(select(PkPurchaseBatch.supplier_id).limit(1));now=now_local()
  batch=PkPurchaseBatch(kode_batch='PK-DINAMIS-LEMBAR',supplier_id=supplier,jumlah_karung=100,ukuran_karung_kg=50,berat_total_kg=None,sumber_berat='menunggu',tanggal_pembelian=now.date(),waktu_pembelian=now,input_by=u.id)
  db.add(batch);db.add(Silo(nama_silo='Silo Timur',warehouse_id=u.default_warehouse_id,jenis_isi='pk'));await db.commit()
  it=(await g2.masukkan_pk_luar(db,user=u,kode=batch.kode_batch)).intake
  await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=proses['intake_tumpukan'],nama_silo='Timur',berat=100)
  await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo='Timur',jumlah_karung=50)
  # Skenario ini menjalankan dua proses bersamaan: fasilitas kedua hanya data uji.
  from app.models import LiniProduksi,JenisProsesProduksi
  jid=await db.scalar(select(JenisProsesProduksi.id).where(JenisProsesProduksi.kode=='penyosohan'))
  line=LiniProduksi(kode='uji-timur',nama='Line uji Timur',warehouse_id=u.default_warehouse_id,jenis_proses_id=jid,aktif=True,versi=1);db.add(line);await db.commit()
  proc=(await p.mulai_penyosohan(db,user=u,nama_silos=['Timur'],lini_id=line.id)).proc;w={'kode':proc.kode_proses,'pid':proc.id}
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);r=await c.get(url(w));assert r.status_code==200,r.text;d=r.json()
  assert not d['sumber_final'] and not d['bobot_final'] and d['sumber'][0]['awal'] is None and d['rendemen'] is None
  assert await fakta(pg)==before
  b=await preview(c,w,'hasil',hasil=[{'jenis':'medium','total':50}])
  async with pg() as db:
   batch=await db.scalar(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch=='PK-DINAMIS-LEMBAR'));batch.berat_total_kg=5000;batch.sumber_berat='timbangan';await db.commit()
  before=await fakta(pg);r=await post(c,w,'hasil','simpan',b);assert r.status_code==409 and 'berubah' in r.text;assert await fakta(pg)==before
  assert (await c.get(url(w))).json()['sumber_final']

async def test_waktu_selesai_historis_hilang_tidak_direka_sebagai_sekarang(pg,proses):
 await siap(pg,proses)
 async with pg() as db:
  await p.akhiri_penyosohan(db,user=await db.get(User,proses['user'].id),kode=proses['kode'])
  row=await db.get(PolishingProcess,proses['pid']);row.waktu_selesai=None;await db.commit()
 async with await _klien(pg,peran='admin') as c:
  before=await fakta(pg);r=await c.get(url(proses));assert r.status_code==200,r.text;d=r.json()
  assert not d['aktif'] and d['waktu']['selesai'] is None
  assert all(d['waktu'][k]=='Belum tersedia' for k in ['durasi','jeda','aktif']);assert await fakta(pg)==before
