"""Detail ringkas memakai izin, field dan penulis penerimaan yang lama."""
import asyncio,json,re
import pytest
from sqlalchemy import select,text,func
from app.models import PurchaseBatch,PkPurchaseBatch,FinishedGoodsStock,ByproductStock,ActivityLog
from tests.pg.test_konsolidasi_pekerjaan import lengkap,JENIS,stok_lengkap,sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.formulir import cap_formulir
from tests.pg.test_portal_pelanggan import portal
from tests.pg.test_riwayat_qc_detail import qc
pytestmark=pytest.mark.asyncio

def awal(r):return json.loads(re.search(r'<script id="penerimaan-awal" type="application/json">(.*?)</script>',r.text,re.S)[1])
async def read(c,tid):
 r=await c.get(f'/api/actions/penerimaan-ringkas/{tid}');assert r.status_code==200,r.text;assert r.headers['cache-control']=='no-store';return r.json()
async def snapshot(pg):
 async with pg() as db:
  return {m.__tablename__:[tuple(getattr(r,col.name) for col in m.__table__.columns) for r in (await db.scalars(select(m).order_by(m.id))).all()] for m in [PurchaseBatch,PkPurchaseBatch,FinishedGoodsStock,ByproductStock,ActivityLog]}

@pytest.mark.parametrize('kind',JENIS)
@pytest.mark.parametrize('jasa',[False,True])
async def test_lima_jenis_konteks_field_izin_bobot_dan_penulis_lama(pg,lengkap,kind,jasa):
 tid=lengkap['tiket'][kind]
 if jasa:
  async with pg() as db:
   await db.execute(text('UPDATE timbangan_transaksi SET jasa=true,pelanggan_id=:p,jasa_id=:j WHERE id=:i'),dict(p=lengkap['pelanggan_id'],j=lengkap['jasa_id'],i=tid));await db.commit()
 async with await _klien(pg,role='superadmin') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c);before=await snapshot(pg)
  page=await c.get(f'/barang-masuk/{tid}?kembali_kerja=%2Fbarang-masuk%3Fstatus%3Dbelum%26halaman%3D2')
  assert page.status_code==200,page.text
  assert 'data-penerimaan-ringkas' in page.text and 'data-buka=""' in page.text
  d=awal(page);assert d['tiket']['id']==tid and d['status_penerimaan']=='Belum diterima' and not d['catatan']
  assert d==await read(c,tid) and await snapshot(pg)==before
  assert ('Pelanggan / pemilik:' if jasa else 'Supplier:') in page.text
  assert 'data-tiket="'+str(tid)+'"' in page.text
  a=d['formulir'][0];assert a['boleh']
  old=next(x for x in (await c.get('/api/actions/menu')).json() if x['id']==a['id'])
  assert a['fields']==old['fields'] and a['post']==old['post']
  assert not any(k in d['tiket'] for k in ['harga','harga_hpp','hpp','harga_per_kg','total_harga'])
  payload={'timbangan_transaksi_id':tid}
  if kind.startswith('GABAH'):
   targets={x['value'] for x in d['tujuan']}
   if jasa and kind=='GABAH_BASAH':assert 'tumpuk' not in targets
   else:assert 'tumpuk' in targets
   payload['tujuan']=next(x['value'] for x in d['tujuan'] if not x['alasan'] and (x['value']=='tumpuk' or jasa and kind=='GABAH_BASAH'))
  elif kind=='BERAS_PK':payload.update(jenis_pk='semi_ks',jumlah_karung=196,ukuran_karung_kg=50)
  r=await c.post(a['post'],json=payload);assert r.status_code==200,r.text
  after=await read(c,tid);assert after['status_penerimaan']=='Penerimaan tercatat' and len(after['catatan'])==1
  assert after['berat_diterima']==9800 and after['catatan'][0]['jasa_id']==(lengkap['jasa_id'] if jasa else None)
  if jasa:assert 'Bu Sri' in after['catatan'][0]['pemilik'] and after['catatan'][0]['pesanan']
  if not jasa:assert after['catatan'][0]['pemilik']=='Milik pabrik'
  saved=await snapshot(pg);duplicate=await c.post(a['post'],json=payload);assert duplicate.status_code in [200,400,409]
  assert await snapshot(pg)==saved
  page=await c.get(f'/barang-masuk/{tid}');assert 'Catatan penerimaan' in page.text and 'laporan.pdf' in page.text
  assert not any(f['boleh'] for f in awal(page)['formulir'])

@pytest.mark.parametrize('role,wh,view,g1,g2,write_pk',[('superadmin',None,None,True,True,True),('admin',None,None,True,True,True),('operator','g1',None,True,False,False),('operator','g2',None,False,True,False),('superadmin',None,'operator:g1',True,False,False),('superadmin',None,'operator:g2',False,True,False)])
async def test_hak_baca_tulis_efektif_dan_endpoint_lama(pg,lengkap,role,wh,view,g1,g2,write_pk):
 async with await _klien(pg,role=role,gudang_id=lengkap['gudang'].get(wh)) as c:
  c.headers['X-CSRF-Token']=cap_formulir(c)
  if view:assert (await c.post('/lihat-sebagai',data={'peran':view,'_csrf':cap_formulir(c)})).status_code==303
  for kind,allowed in [('GABAH_KERING',g1),('BERAS_PK',g2)]:
   tid=lengkap['tiket'][kind]
   for path in [f'/barang-masuk/{tid}',f'/api/actions/penerimaan-ringkas/{tid}']:
    r=await c.get(path);assert r.status_code==(200 if allowed else 403),(role,view,path,r.text[-500:])
   if allowed:
    d=await read(c,tid);assert d['formulir'][0]['boleh']==(g1 if kind.startswith('GABAH') else write_pk)
  if not write_pk:
   before=await snapshot(pg);r=await c.post('/api/actions/catat-pk-luar',json={'timbangan_transaksi_id':lengkap['tiket']['BERAS_PK'],'jenis_pk':'ks'});assert r.status_code==403;assert await snapshot(pg)==before

@pytest.mark.parametrize('terbuka',[False,True])
async def test_penolakan_historis_dan_alasan_tetap_tanpa_stok(pg,lengkap,terbuka):
 tid=lengkap['tiket']['BERAS_PK']
 if terbuka:
  async with pg() as db:
   await db.execute(text("UPDATE timbangan_transaksi SET status_tiket='TERBUKA',netto_timbangan_kg=NULL WHERE id=:i"),dict(i=tid));await db.commit()
 async with await _klien(pg,role='superadmin') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c);before=await snapshot(pg)
  r=await c.post('/api/actions/tolak-pk-luar',json={'timbangan_transaksi_id':tid,'alasan':'   '});assert r.status_code==400;assert await snapshot(pg)==before
  r=await c.post('/api/actions/tolak-pk-luar',json={'timbangan_transaksi_id':tid,'alasan':'Mutu tidak sesuai pemeriksaan fisik'});assert r.status_code==200,r.text
  d=await read(c,tid);assert d['status_penerimaan']=='Ditolak' and d['berat_diterima'] is None
  assert d['catatan'][0]['penolakan']['alasan']=='Mutu tidak sesuai pemeriksaan fisik'
  page=await c.get(f'/barang-masuk/{tid}');assert 'Mutu tidak sesuai pemeriksaan fisik' in page.text and ('Ditutup paksa' in page.text if terbuka else d['tiket']['status_tiket']=='SELESAI')
  assert not any(f['boleh'] for f in d['formulir'])
  async with pg() as db:
   from app.models import PkGudang2Intake
   assert not await db.scalar(select(PkGudang2Intake.id).where(PkGudang2Intake.pk_purchase_batch_id==d['catatan'][0]['id']))

async def test_produk_dua_permintaan_bersamaan_tetap_satu_stok(pg,lengkap):
 tid=lengkap['tiket']['BERAS_MASUK']
 async with await _klien(pg,role='superadmin') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c)
  rs=await asyncio.gather(*[c.post('/api/actions/catat-produk-timbang-masuk',json={'timbangan_transaksi_id':tid}) for _ in range(2)])
  assert sorted(r.status_code for r in rs)==[200,409]
  d=await read(c,tid);assert len(d['catatan'])==1 and d['berat_diterima']==9800

@pytest.mark.parametrize('field,value',[('jenis_pk',''),('jumlah_karung',0),('jumlah_karung',-1),('jumlah_karung',1.5),('ukuran_karung_kg',0)])
async def test_validasi_pk_lama_dan_isian_tidak_dibuang_di_server(pg,lengkap,field,value):
 tid=lengkap['tiket']['BERAS_PK']
 async with await _klien(pg,role='superadmin') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c);before=await snapshot(pg)
  body={'timbangan_transaksi_id':tid,'jenis_pk':'ks',field:value};r=await c.post('/api/actions/catat-pk-luar',json=body);assert r.status_code in [400,422]
  assert await snapshot(pg)==before and not (await read(c,tid))['catatan']

@pytest.mark.parametrize('kind',['GABAH_KERING','BERAS_PK'])
@pytest.mark.parametrize('tara',[False,True])
async def test_bobot_belum_final_memakai_pembaca_lama_dan_bukan_nol(pg,lengkap,kind,tara):
 from tests.pg.test_bobot_belum_final import _tiket
 async with pg() as db:
  if tara:await _tiket(db,'TB-TARA-HISTORIS',nopol='AD 5511 UJI',t1=18000,netto=11500,kosong=6500,hari_lalu=1)
  tid=await _tiket(db,'TB-MENUNGGU-UI',nopol='AD 5511 UJI',t1=16300,jenis=kind);await db.commit()
 async with await _klien(pg,role='superadmin') as c:
  before=await snapshot(pg);r=await c.get(f'/barang-masuk/{tid}');d=awal(r)
  assert d['bobot_masuk']==dict(kg=9800 if tara else None,sumber='perkiraan' if tara else 'menunggu')
  from bs4 import BeautifulSoup
  main=BeautifulSoup(r.text,'html.parser').select_one('.bm-bobot>strong').get_text(strip=True)
  assert 'Berat belum final' in r.text and main==('9.800 kg' if tara else 'Belum tercatat')
  assert await read(c,tid)==d and await snapshot(pg)==before

async def test_tujuan_diubah_setelah_dibaca_memakai_validasi_lama(pg,lengkap):
 from app.models import Dryer
 tid=lengkap['tiket']['GABAH_KERING']
 async with await _klien(pg,role='superadmin') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c);d=await read(c,tid)
  assert any(t['value']=='tumpuk' for t in d['tujuan'])
  async with pg() as db:
   dryer=await db.scalar(select(Dryer).order_by(Dryer.id));did=dryer.id
   dryer.warehouse_id=lengkap['gudang']['g2'];await db.commit()
  before=await snapshot(pg)
  r=await c.post('/api/actions/gabah-masuk',json=dict(timbangan_transaksi_id=tid,tujuan='dryer:'+str(did)))
  # Layanan lama dapat menyimpan penerimaan, lalu penempatan tertunda.
  # Jangan mengklaim seluruh tindakan gagal dan mengirim ulang penerimaan.
  assert r.status_code==200 and 'Belum ditempatkan' in r.json()['pesan'],r.text
  latest=await read(c,tid);assert not latest['pending'] and len(latest['catatan'])==1
  assert latest['catatan'][0]['status']=='baru'
  async with pg() as db:
   b=await db.get(PurchaseBatch,latest['catatan'][0]['id']);assert b.dryer_id is None
  saved=await snapshot(pg);r=await c.post('/api/actions/gabah-masuk',json=dict(timbangan_transaksi_id=tid,tujuan='tumpuk'))
  assert r.status_code in (400,409) and await snapshot(pg)==saved

@pytest.mark.parametrize('path',['/barang-masuk','/pekerjaan'])
async def test_pintasan_bertiket_lama_membuka_konteks_tanpa_memilih_ulang(pg,lengkap,path):
 from urllib.parse import parse_qs,urlsplit
 async with await _klien(pg,role='superadmin') as c:
  tid=lengkap['tiket']['BERAS_PK'];r=await c.get(path,params=dict(buka='catat_pk_luar',nilai=str(tid),jenis='pk',cari='TRX-391',halaman='2'))
  assert r.status_code==303
  u=urlsplit(r.headers['location']);assert u.path==f'/barang-masuk/{tid}'
  q=parse_qs(u.query);assert q['buka']==['catat_pk_luar'] and 'halaman=2' in q['kembali_kerja'][0]
  page=await c.get(r.headers['location']);assert page.status_code==200 and awal(page)['tiket']['id']==tid

async def test_status_internal_tidak_dibuka_dengan_sesi_portal(pg,portal):
 from tests.pg.test_portal_pelanggan import client
 async with client(portal.accounts[0]) as c:
  r=await c.get('/api/actions/penerimaan-ringkas/1')
  assert r.status_code==401 and 'catatan' not in r.json()
