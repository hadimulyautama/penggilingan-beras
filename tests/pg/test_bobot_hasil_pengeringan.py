"""Bobot basah/estimasi/terukur, stage silo, audit, dan stok terpisah."""
import asyncio
from decimal import Decimal
from uuid import uuid4
from io import BytesIO
from pathlib import Path
import pytest
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy import select,delete,func
from app.models import DryingLot,SiloStorage,PurchaseBatch,ActivityLog,User
from app.services import bobot_pengeringan as svc
from app.services.estimasi_pengeringan import untuk_silo_banyak
from tests.pg.test_estimasi_pengeringan import buat,sidik
from tests.pg.test_gabung_jasa import dunia
from tests.pg.test_riwayat_pengeringan import _klien
from tests.pg.test_form_kadar_air import post
from tests.pg.test_portal_transit import _akun
from tests.pg.test_portal_pelanggan import client

pytestmark=pytest.mark.asyncio

async def baca(c,lid):
 r=await c.get('/api/actions/bobot-pengeringan',params={'lot_id':lid});assert r.status_code==200,r.text
 return r.json()

def isian(data,**kw):
 return dict(lot_id=data['lot_id'],kg=26000.25,referensi='FLOW-UJI-001',alasan='',konfirmasi=True,dasar=data['dasar'],kunci=str(uuid4()),**kw)

async def jumlah_audit(pg):
 async with pg() as db:return await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='catat_bobot_kering_terukur'))

async def test_riwayat_ringkasan_pdf_dan_bobot_pasti_audit_tanpa_stok(pg,dunia,tmp_path):
 lid,storage,bid=await buat(pg,dunia)
 await buat(pg,dunia,huruf='B',jasa=dunia['jasa3'],kode='PGR-RAHASIA-B',kg=5000)
 account=await _akun(pg,dunia)
 async with await _klien(pg,peran='admin') as c:
  for url in ['/riwayat-pengeringan',f'/riwayat-pengeringan/{lid}']:
   r=await c.get(url);assert r.status_code==200,r.text
   assert '26.456,76 kg' in r.text
   (tmp_path/('riwayat.html' if url=='/riwayat-pengeringan' else 'detail.html')).write_text(r.text)
  r=await c.get(f'/riwayat-pengeringan/{lid}/bobot');assert r.status_code==200
  (tmp_path/'form.html').write_text(r.text)
  soup=BeautifulSoup(r.text,'html.parser')
  assert any('data-bobot-pengeringan' in style.get_text() for style in soup.select('body style'))
  r=await c.get(f'/riwayat-pengeringan/{lid}/bobot',headers={'X-Pindah':'1'})
  assert r.status_code==200 and '[data-bobot-pengeringan] [hidden]' in r.text
  r=await c.get(f'/riwayat-pengeringan/{lid}/laporan.pdf');assert r.status_code==200
  (tmp_path/'pengeringan-estimasi.pdf').write_bytes(r.content)
  txt=' '.join(page.extract_text() for page in PdfReader(BytesIO(r.content)).pages)
  assert '26.456,76 kg' in txt and 'Bobot kering terukur' not in txt
  data=await baca(c,lid);before=await sidik(pg)
  payload=isian(data)
  response=await post(c,'bobot-pengeringan',payload);assert response.status_code==200,response.text
  saved=response.json()['data'];assert saved['bobot']['terukur']=='26.000,25 kg'
  assert await jumlah_audit(pg)==1
  assert (await post(c,'bobot-pengeringan',payload)).status_code==200
  assert await jumlah_audit(pg)==1
  assert (await post(c,'bobot-pengeringan',dict(payload,kunci=str(uuid4())))).status_code==200
  assert await jumlah_audit(pg)==1
  after=await sidik(pg)
  for name in before:
   if name not in ('activity_logs','proses_terpadu'):assert before[name]==after[name]
  async with pg() as db:
   batch=await db.get(PurchaseBatch,bid);assert batch.berat_total_kg==Decimal('30251.50')
   row=await db.scalar(select(ActivityLog).where(ActivityLog.aksi=='catat_bobot_kering_terukur'))
   assert row.old_value is None and '26000.25' in row.new_value
   from app.services.undo import _undo_one,UndoError
   with pytest.raises(UndoError,match='flowing scale'):await _undo_one(db,row,actor_id=row.changed_by)
  r=await c.get(f'/riwayat-pengeringan/{lid}/laporan.pdf');assert r.status_code==200
  (tmp_path/'pengeringan-terukur.pdf').write_bytes(r.content)
  text='\n'.join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages)
  assert '26.456,76 kg' in text and '26.000,25 kg' in text and '30.251,50 kg' in text
  # A stale correction cannot overwrite the first result.
  p=dict(payload,kunci=str(uuid4()),kg=25990,alasan='Periksa ulang alat')
  assert (await post(c,'bobot-pengeringan',p)).status_code==400
  new=await baca(c,lid);p.update(dasar=new['dasar'],alasan='   ')
  assert (await post(c,'bobot-pengeringan',p)).status_code==400
  p['alasan']='Koreksi pencatatan hasil timbangan'
  r=await post(c,'bobot-pengeringan',p);assert r.status_code==200,r.text
  assert r.json()['data']['terukur']['versi']==2 and await jumlah_audit(pg)==2
 async with client(account) as c:
  for url,name in [('/pelanggan/','beranda'),('/pelanggan/barang-saya','barang'),('/pelanggan/riwayat-proses','portal-riwayat')]:
   r=await c.get(url);assert r.status_code==200
   assert 'PGR-RAHASIA-B' not in r.text
   assert 'Bobot gabah kering terukur' in r.text and '25.990,00 kg' in r.text
   assert '/bobot' not in r.text and 'data-simpan' not in r.text
   s=BeautifulSoup(r.text,'html.parser')
   assert not s.select('.pelanggan-batch .pelanggan-stok-bobot')
   (tmp_path/(name+'.html')).write_text(r.text)
  r=await c.get(f'/pelanggan/riwayat-pengeringan/{lid}/laporan.pdf');assert r.status_code==200
  assert '25.990,00 kg' in ' '.join(p.extract_text() for p in PdfReader(BytesIO(r.content)).pages)
  assert (await c.get('/api/actions/bobot-pengeringan',params={'lot_id':lid})).status_code==401
  assert (await c.get('/pelanggan/riwayat-pengeringan/'+str(lid)+'/bobot')).status_code in (403,404)

@pytest.mark.parametrize('stage',['drying','pendinginan','dingin-belum-silo'])
async def test_tidak_ada_entry_pasti_sebelum_selesai_dipindah_silo(pg,dunia,stage):
 lid,storage,_=await buat(pg,dunia)
 async with pg() as db:
  await db.execute(delete(SiloStorage).where(SiloStorage.id==storage))
  lot=await db.get(DryingLot,lid)
  if stage!='dingin-belum-silo':lot.waktu_selesai_pendinginan=None
  if stage=='drying':lot.status='proses';lot.waktu_selesai_pengeringan=None
  await db.commit()
 async with await _klien(pg,peran='admin') as c:
  assert (await c.get('/api/actions/bobot-pengeringan',params={'lot_id':lid})).status_code==400
  assert (await c.get(f'/riwayat-pengeringan/{lid}/bobot')).status_code==400
  page=await c.get(f'/riwayat-pengeringan/{lid}');assert page.status_code in (200,303,307)
  assert 'Catat hasil timbang flowing scale' not in page.text
  before=await sidik(pg)
  p=dict(lot_id=lid,kg=26000,referensi='FLOW',alasan='',konfirmasi=True,dasar='palsu',kunci=str(uuid4()))
  assert (await post(c,'bobot-pengeringan',p)).status_code==400
  assert await sidik(pg)==before

@pytest.mark.parametrize('value',[-1,0,'NaN','Infinity',1.234])
async def test_angka_tidak_sah_tidak_menulis(pg,dunia,value):
 lid,_,_=await buat(pg,dunia)
 async with await _klien(pg,peran='admin') as c:
  p=isian(await baca(c,lid));p['kg']=value
  before=await sidik(pg)
  assert (await post(c,'bobot-pengeringan',p)).status_code in (400,422)
  assert await sidik(pg)==before

async def test_balapan_dua_catatan_hanya_satu_dan_retry_aman(pg,dunia):
 lid,_,_=await buat(pg,dunia)
 async with await _klien(pg,peran='admin') as c:
  p=isian(await baca(c,lid))
  results=await asyncio.gather(post(c,'bobot-pengeringan',p),post(c,'bobot-pengeringan',p))
  assert [r.status_code for r in results]==[200,200] and await jumlah_audit(pg)==1
  latest=await baca(c,lid)
  a=isian(latest);a['alasan']='Koreksi A';a['kg']=25900
  b=isian(latest);b['alasan']='Koreksi B';b['kg']=25800
  results=await asyncio.gather(post(c,'bobot-pengeringan',a),post(c,'bobot-pengeringan',b))
  assert sorted(r.status_code for r in results)==[200,400] and await jumlah_audit(pg)==2

@pytest.mark.parametrize('role,warehouse,view,allowed',[
 ('admin',None,None,True),('superadmin',None,None,True),('operator','Gudang 1',None,True),
 ('operator','Gudang 2',None,False),('superadmin',None,'operator:g2',False),('staff',None,None,False)])
async def test_izin_efektif_dan_csrf(pg,dunia,role,warehouse,view,allowed):
 lid,_,_=await buat(pg,dunia)
 async with await _klien(pg,peran=role,gudang=warehouse) as c:
  if view:c.cookies.set('produksi_lihat',view)
  r=await c.get('/api/actions/bobot-pengeringan',params={'lot_id':lid})
  assert r.status_code==(200 if allowed else 403)
  p=isian(r.json()) if allowed else dict(lot_id=lid,kg=26000,referensi='X',alasan='',konfirmasi=True,dasar='palsu',kunci=str(uuid4()))
  before=await sidik(pg)
  assert (await c.post('/api/actions/bobot-pengeringan',json=p)).status_code==403
  if not allowed:assert (await post(c,'bobot-pengeringan',p)).status_code==403
  assert await sidik(pg)==before


async def test_catatan_pasti_tidak_dianggap_aktif_bila_pemindahan_dibatalkan(pg,dunia):
 lid,storage,_=await buat(pg,dunia)
 async with await _klien(pg,peran='admin') as c:
  p=isian(await baca(c,lid));assert (await post(c,'bobot-pengeringan',p)).status_code==200
 async with pg() as db:
  await db.execute(delete(SiloStorage).where(SiloStorage.id==storage));await db.commit()
  from app.services.estimasi_pengeringan import untuk_lot_banyak
  lot=await db.get(DryingLot,lid);info=(await untuk_lot_banyak(db,[lot]))[lid]
  assert info['terukur'] is None and info['kering']=='26.456,76 kg'
  assert await jumlah_audit(pg)==1  # Measurement audit is not erased.


async def test_catatan_timbang_rusak_ditahan_tanpa_menulis(pg,dunia):
 from hmu_core.proses_db import ProsesTerpadu
 lid,_,_=await buat(pg,dunia)
 async with pg() as db:
  row=await db.scalar(select(ProsesTerpadu).where(ProsesTerpadu.id_sumber==str(lid)))
  row.metadata_domain={**row.metadata_domain,'bobot_kering_terukur':'data lama tidak sah'};await db.commit()
 before=await sidik(pg)
 async with await _klien(pg,peran='admin') as c:
  r=await c.get('/api/actions/bobot-pengeringan',params={'lot_id':lid})
  assert r.status_code==400 and 'audit' in r.text
 assert await sidik(pg)==before
