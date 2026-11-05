import pytest
import os
from pathlib import Path
from sqlalchemy import select,text
from tests.pg.test_konsolidasi_stok import stok_lengkap
from tests.pg.test_stok_produk_jasa import sosoh_jasa
from tests.pg.test_stok_pk_g1_polesan import _klien

pytestmark=pytest.mark.asyncio

async def test_semua_tahap_bobot_tidak_diketahui_dan_gudang_baru(pg,stok_lengkap):
 from app.models import Warehouse,Silo,PurchaseBatch,SiloStorage,PkPurchaseBatch
 from app.database import now_local
 from app.services import jasa_pelanggan as svc
 x=stok_lengkap;now=now_local()
 async with pg() as db:
  wh=Warehouse(nama_gudang='Gudang titipan baru',aktif=True);db.add(wh);await db.flush()
  for i,(status,kg) in enumerate([('baru',None),('ditumpuk',2000),('di_dryer',10839),('dikeringkan',10498),('di_silo',32843.5)]):
   b=PurchaseBatch(kode_batch=f'GABAH-TAHAP-{i}',jasa_id=x['jasa_id'],warehouse_id=wh.id,
    kondisi_gabah='basah' if status in ('di_dryer','dikeringkan') else 'kering',berat_total_kg=kg,sumber_berat='manual',
    status_batch=status,tanggal_pembelian=now.date(),waktu_pembelian=now,input_by=x['user'])
   db.add(b);await db.flush()
   if status=='di_silo':
    si=Silo(nama_silo='Silo gudang baru',warehouse_id=wh.id,jenis_isi='gabah',status='terisi');db.add(si);await db.flush()
    db.add(SiloStorage(silo_id=si.id,purchase_batch_id=b.id,tipe_masuk='langsung',tanggal_masuk=now,status='terisi',jasa_id=x['jasa_id'],input_by=x['user']))
  db.add(PkPurchaseBatch(kode_batch='PK-BELUM-DITEMPATKAN',jasa_id=x['jasa_id'],warehouse_id=wh.id,
   berat_total_kg=None,sumber_berat='manual',status_batch='diterima',tanggal_pembelian=now.date(),waktu_pembelian=now,input_by=x['user']))
  await db.commit()
  await db.execute(text('SET TRANSACTION READ ONLY'))
  d=await svc.pelanggan(db,x['pelanggan_id'])
  g={(r['jenis'],r['tahap']):r for r in d['bahan_titipan']}
  assert g['Gabah','pengering']['kg']==21337
  assert g['Gabah','silo_giling']['kg']==32843.5
  assert g['Gabah','tumpukan']['kg']==2000
  assert g['Gabah','penempatan']['belum_diketahui']==1
  assert g['PK','penempatan']['belum_diketahui']==1
  assert 'Gudang titipan baru' in ' '.join(g['Gabah','silo_giling']['lokasi'])
  assert d['pk_kg']==3500 and d['beras_kg']==5000
 async with await _klien(pg,role='admin') as c:
  for url in ['/jasa',f'/jasa/pelanggan/{x["pelanggan_id"]}']:
   r=await c.get(url);assert r.status_code==200,r.text[:1000]
   assert '21.337 kg' in r.text and '32.843,5 kg' in r.text and 'Belum diketahui' in r.text
   assert 'data-jasa-kontrol' in r.text
   if os.environ.get('BUKTI_JASA_KONTROL'):
    out=Path(os.environ['BUKTI_JASA_KONTROL']);out.mkdir(parents=True,exist_ok=True);(out/('jasa.html' if url=='/jasa' else 'ringkasan.html')).write_text(r.text)
  for tab in ['penerimaan','proses','stok','pengambilan']:
   r=await c.get(f'/jasa/pelanggan/{x["pelanggan_id"]}?tab='+tab);assert r.status_code==200,r.text[:500]
   if os.environ.get('BUKTI_JASA_KONTROL'):(Path(os.environ['BUKTI_JASA_KONTROL'])/(tab+'.html')).write_text(r.text)


async def test_pk_dalam_silo_terpisah_dari_pk_bebas_dan_berkurang_setelah_sosoh(pg,pemakai):
 from tests.pg.skenario_jasa_pelanggan import buat
 from app.services import jasa_pelanggan as svc
 from app.models import User
 from app.penggilingan.gudang2 import service as g2
 x=await buat(pg,pemakai)
 async with pg() as db:
  d=await svc.pelanggan(db,x['pelanggan_id'])
  # Semua silo skenario sudah dikonsumsi, sehingga bahan lama tidak hidup lagi.
  assert not any(r['tahap']=='silo_sosoh' and r['kg'] for r in d['bahan_titipan'])
  pile=next(r for r in d['stok'] if r['nama']=='PK' and r['kg']==1000)
  from app.models import PkGudang2Intake,PkPurchaseBatch
  batch=await db.scalar(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch=='PKB-392-01'))
  intake=await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.pk_purchase_batch_id==batch.id))
  await g2.pindah_tumpukan_ke_silo(db,user=await db.get(User,x['user']),intake_id=intake.id,nama_silo='C',berat=500)
  d=await svc.pelanggan(db,x['pelanggan_id'])
  assert any(r['jenis']=='PK' and r['tahap']=='silo_sosoh' and abs(float(r['kg'])-500)<.01 for r in d['bahan_titipan'])
  assert d['pk_kg']==1500
