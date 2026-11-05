"""Baca dan minta bagian pabrik di G1 tanpa membuka hak gudang lain."""
from urllib.parse import parse_qs,urlsplit
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select,func
from app.models import User,MillingProcess,PkGudang2Intake,PermintaanPk,InternalTransfer
from app.services import stok,pk_persediaan
from tests.pg.test_pk_kepemilikan import world,initial
from tests.pg.test_stok_pk_g1_polesan import _klien
from tests.pg.test_masuk_detail_timbang import sidik
from tests.pg.formulir import cap_formulir

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('aktif',[False,True])
async def test_bagian_asal_jasa_yang_sudah_pabrik_terlihat_dan_bisa_diminta(pg,world,aktif):
 w=world
 async with pg() as db:
  proc=await db.get(MillingProcess,int(w['sources'][0].split(':')[1]));proc.jasa_id=w['jasa']
  if aktif:proc.status='proses';proc.waktu_selesai=None
  intake=await db.get(PkGudang2Intake,int(w['sources'][1].split(':')[1]));intake.jasa_id=w['jasa']
  await db.commit()
  await initial(db,w,amount=400,dari=w['jasa'],ke=None)
 async with await _klien(pg,gudang_id=w['warehouses'][1]) as c:
  async with pg() as db:before=await sidik(db)
  r=await c.get('/stok');assert r.status_code==200
  s=BeautifulSoup(r.text,'html.parser')
  href=next(a['href'] for a in s.select('a[href]') if '/stok/pk/detail?' in a['href'] and 'LOT-PK-001' in a['href'])
  assert parse_qs(urlsplit(href).query)['jasa']==['0']
  assert 'Pemilik jasa PK' in r.text  # titipan di gudang G2 sendiri tetap terbaca
  d=await c.get(href);assert d.status_code==200
  ds=BeautifulSoup(d.text,'html.parser');button=ds.find('a',string='Minta lot ini')
  assert button and '400' in ds.select_one('.pk-detail__weight').get_text()
  assert 'pemilik%3Dpabrik' in button['href']
  assert 'LOT-PK-001' not in (await c.get('/stok?pemilik=jasa')).text
  forbidden=await c.get('/stok/pk/detail',params={'gudang':'g1','kode':'LOT-PK-001','jasa':'1','pemilik_id':w['jasa']})
  assert forbidden.status_code==404
  assert forbidden.headers['content-type'].startswith('text/html')
  options=await c.get('/api/actions/pk-g1-tersedia');assert options.status_code==200
  item=next(x for x in options.json() if 'LOT-PK-001' in x['value'])
  assert item['value']=='LOT-PK-001|pemilik=pabrik'
  good=await c.get('/api/actions/pratinjau-unit-transfer-pk/minta',params={'kode_proses':item['value'],'cara':'kg','berat':'350'})
  assert good.status_code==200,good.text
  assert good.json()['rincian']['tersedia_kg']==400
  for code in ['LOT-PK-001','LOT-PK-001|pemilik='+str(w['jasa'])]:
   bad=await c.get('/api/actions/pratinjau-unit-transfer-pk/minta',params={'kode_proses':code})
   assert bad.status_code==403,bad.text
   bad=await c.post('/api/actions/minta-pk-g1',json={'kode_proses':code,'berat':100},headers={'X-CSRF-Token':cap_formulir(c)})
   assert bad.status_code==400 and 'milik pabrik' in bad.text,bad.text
  over=await c.post('/api/actions/minta-pk-g1',json={'kode_proses':item['value'],'berat':401},headers={'X-CSRF-Token':cap_formulir(c)})
  assert over.status_code==400 and '400' in over.text,over.text
  async with pg() as db:assert await sidik(db)==before
  r=await c.post('/api/actions/minta-pk-g1',json={'kode_proses':item['value'],'berat':350},headers={'X-CSRF-Token':cap_formulir(c)})
  assert r.status_code==200,r.text
 async with pg() as db:
  req=(await db.scalars(select(PermintaanPk))).one()
  assert req.jasa_id is None and req.berat_minta_kg==350 and req.status=='diminta'
  assert await db.scalar(select(func.count()).select_from(InternalTransfer))==0
  source=(await pk_persediaan.baca(db))[w['sources'][0]]
  assert source.stok.saldo(None)==400 and source.stok.saldo(w['jasa'])==600
  assert source.stok.fisik_kg==1000

async def test_lot_jasa_murni_tertutup_g2_tetapi_pemilik_dan_g1_masih_bisa_membaca(pg,world):
 w=world
 async with pg() as db:
  p=await db.get(MillingProcess,int(w['sources'][0].split(':')[1]));p.jasa_id=w['jasa'];await db.commit()
 async with await _klien(pg,gudang_id=w['warehouses'][1]) as c:
  for url in ['/stok','/stok?pemilik=pabrik','/stok?pemilik=jasa','/stok-pk-jasa','/stok?gudang=g1']:
   r=await c.get(url);assert r.status_code==200 and 'LOT-PK-001' not in r.text
  assert (await c.get('/api/actions/pk-g1-tersedia')).json()==[]
  assert (await c.get('/gudang/g1')).status_code==403
 for role,wid in [('admin',None),('superadmin',None),('operator',w['warehouses'][0])]:
  async with await _klien(pg,role=role,gudang_id=wid) as c:
   assert 'LOT-PK-001' in (await c.get('/stok')).text
