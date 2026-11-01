"""Beban data uji Ringkasan: saldo penuh tidak mengikuti batas tampilan pesanan."""
import json,time,os
from urllib.parse import parse_qs,urlsplit
from pathlib import Path
import pytest,pytest_asyncio
from sqlalchemy import select,event
from bs4 import BeautifulSoup
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien
pytestmark=pytest.mark.asyncio

@pytest_asyncio.fixture
async def banyak(pg,stok_lengkap):
 from app.models import Jasa,PurchaseBatch,MillingProcess,MillingProgressLog
 from app.database import now_local
 async with pg() as db:
  now=now_local();silo=await db.scalar(select(MillingProcess.silo_id).limit(1));orders=[]
  for i in range(100):
   j=Jasa(kode=f'JAS-BANYAK-{i:03}',pelanggan_id=stok_lengkap['pelanggan_id'],status='berjalan' if i%3==0 else 'selesai',catatan=f'Catatan pesanan data uji panjang ke-{i}; seluruh saldo pelanggan harus tetap dihitung.');db.add(j);orders.append(j)
  await db.flush()
  for i in range(120):
   db.add(PurchaseBatch(kode_batch=f'GB-BANYAK-{i:03}',jasa_id=orders[i%100].id,kondisi_gabah='kering',berat_total_kg=1000,sumber_berat='manual',status_batch='digiling',tanggal_pembelian=now.date(),waktu_pembelian=now,input_by=stok_lengkap['user']))
  for i in range(24):
   m=MillingProcess(kode_proses=f'LOT-BANYAK-{i:03}',silo_id=silo,jasa_id=orders[i].id,status='selesai',berat_gabah_masuk_kg=1000,waktu_mulai=now,waktu_selesai=now,created_by=stok_lengkap['user']);db.add(m);await db.flush()
   db.add(MillingProgressLog(milling_process_id=m.id,berat_kumulatif_kg=750,waktu_update=now,input_by=stok_lengkap['user']))
  await db.commit()
 return {**stok_lengkap,'order_ids':[j.id for j in orders]}

async def test_beban_ringkasan_banyak(pg,banyak):
 from app.services import jasa_pelanggan as svc
 async with pg() as db:
  old=await svc.pelanggan(db,banyak['pelanggan_id'])
  assert len(old['pesanan'])==101 and len(old['penerimaan'])==120
  assert old['pk_kg']==21500 and old['beras_kg']==5000
 async with await _klien(pg,role='admin') as c:
  engine=pg.kw['bind'];queries=[]
  def record(conn,cursor,statement,params,ctx,many):queries.append(statement.split(None,1)[0])
  event.listen(engine.sync_engine,'before_cursor_execute',record)
  start=time.perf_counter()
  try:r=await c.get(f'/jasa/pelanggan/{banyak["pelanggan_id"]}?tab=ringkasan')
  finally:event.remove(engine.sync_engine,'before_cursor_execute',record)
  elapsed=time.perf_counter()-start
  assert r.status_code==200,r.text[:1000]
  s=BeautifulSoup(r.text,'html.parser');count=len(s.select('.jasa-catatan'))
  out=Path(os.environ.get('BUKTI_RINGKASAN_DIR','output/uji-ringkasan-banyak'));out.mkdir(exist_ok=True,parents=True)
  (out/'banyak-paginasi.json').write_text(json.dumps({'orders':len(old['pesanan']),'receipts':len(old['penerimaan']),'processes':len(old['proses']),'pk_kg':old['pk_kg'],'beras_kg':old['beras_kg'],'rendered_orders':count,'queries':len(queries),'seconds':elapsed,'html_bytes':len(r.content)},indent=2))
  (out/'banyak-paginasi.html').write_text(r.text)
  assert count==20
  assert len(s.select('.jasa-detail-tab a'))==5
  assert len(queries)<600
  for q in ({'pesanan_halaman':6},{'pesanan_cari':'JAS-BANYAK-000'},{'pesanan_status':'dibatalkan'}):
   rr=await c.get(f"/jasa/pelanggan/{banyak['pelanggan_id']}",params=q)
   assert rr.status_code==200
   page=BeautifulSoup(rr.text,'html.parser')
   assert page.select_one('.jasa-detail-angka').get_text()==s.select_one('.jasa-detail-angka').get_text()
   assert len(page.select('.jasa-catatan'))<=20
   if q.get('pesanan_status')=='dibatalkan':assert 'Tidak ada pesanan yang cocok' in page.text
  target=banyak['jasa_id']
  rr=await c.get(f"/jasa/pelanggan/{banyak['pelanggan_id']}",params={'pesanan_id':target,'pesanan_status':'dibatalkan','cari':'asal','status':'berjalan','halaman':7})
  page=BeautifulSoup(rr.text,'html.parser')
  assert page.select_one(f'#pesanan-{target}') and 'penyaring pesanan dikosongkan' in page.text
  back=parse_qs(urlsplit(page.select_one('.jasa-terkait a')['href']).query)['kembali_jasa'][0]
  assert parse_qs(urlsplit(back).query)['pesanan_halaman']==['6']
  alias=await c.get(f'/jasa/{target}');assert alias.status_code==303 and f'pesanan_id={target}' in alias.headers['location']
  for row in page.select('.jasa-catatan a[href]'):
   if 'buka=' in row['href']:assert 'pesanan_halaman=6' in row['href']
