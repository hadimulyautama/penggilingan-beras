"""Laporan dari layanan dan basis data uji, termasuk akses URL dan baca-saja."""
from datetime import timedelta
from io import BytesIO
from pathlib import Path
import os
import pytest
from sqlalchemy import select,text
from pypdf import PdfReader
from app.models import PurchaseBatch,PurchaseBatchQc,PurchaseBatchQcSample,MillingProcess,MillingQcLog,User
from app.database import now_local
from app.services.mutu_pk import penilaian_dari_log
from app.web.layar_riwayat import _ambil_data_laporan_giling
from tests.pg.test_riwayat_giling import pabrik,_giling_selesai,_klien
from tests.pg.test_masuk_detail_timbang import contoh
pytestmark=pytest.mark.asyncio


def bukti(nama,data):
 folder=os.environ.get('BUKTI_LAPORAN_QC')
 if folder:
  target=Path(folder);target.mkdir(parents=True,exist_ok=True)
  (target/nama).write_bytes(data if isinstance(data,bytes) else data.encode())

async def sidik(db):
 names=(await db.execute(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))).scalars().all()
 return {n:await db.scalar(text('SELECT md5(COALESCE(string_agg(row_to_json(t)::text,\'\' ORDER BY row_to_json(t)::text),\'\')) FROM "'+n+'" t')) for n in names}

async def test_laporan_lengkap_lamur_tersimpan_dan_rata_sama_layanan(pg,pabrik):
 kode=await _giling_selesai(pg,pabrik)
 async with pg() as db:
  proc=await db.scalar(select(MillingProcess).where(MillingProcess.kode_proses==kode));pid=proc.id
  batch=await db.scalar(select(PurchaseBatch));bid=batch.id
  # Histori kering dengan lamur tercatat tetap ditampilkan; tidak mengubah aturan input QC.
  batch.kadar_air_awal_persen=14.1
  q=PurchaseBatchQc(purchase_batch_id=bid,lamur=True,jumlah_sak_lamur=2,biji_hijau='sedikit',densiti='padat',input_by=pabrik['user']);db.add(q);await db.flush()
  for i in range(5):
   db.add(PurchaseBatchQcSample(purchase_batch_qc_id=q.id,nomor_sampel=i+1,kadar_air_1=14,kadar_air_2=14.2,lamur=True if i==0 else False if i<4 else None,jumlah_sak_lamur=2 if i==0 else 0 if i<4 else None,biji_hijau='sedikit',densiti='sedang',input_by=pabrik['user']))
  for i in range(3):
   db.add(MillingQcLog(milling_process_id=pid,kadar_air=13+i,broken_persen=20+i,susut_persen=10+i,butir_kuning=['bersih','sedikit','banyak'][i],gabah='bersih',merang='sedang',catatan_lab='Catatan utuh '+str(i),waktu=now_local()+timedelta(minutes=i),input_by=pabrik['user']))
  await db.commit()
  logs=(await db.scalars(select(MillingQcLog).where(MillingQcLog.milling_process_id==pid))).all()
  expected=penilaian_dari_log(logs)
 data=await _ambil_data_laporan_giling(pid)
 assert data['qc_rating']==expected and len(data['qc'])==3
 assert len(data['raw_qc'])==5 and data['raw_summary'][batch.kode_batch]['n']==10
 assert [r['lamur'] for r in data['raw_qc']]==['Ya · 2 sak','Tidak · 0 sak','Tidak · 0 sak','Tidak · 0 sak','Tidak tercatat']
 async with await _klien(pg,peran='admin') as c:
  async with pg() as db:before=await sidik(db)
  for suffix in ['/laporan','/laporan.pdf','/laporan.pdf?unduh=1']:
   response=await c.get(f'/riwayat-giling/{pid}'+suffix);assert response.status_code==200
   if suffix=='/laporan':
    bukti('giling-preview.html',response.text)
   else:
    pdf=PdfReader(BytesIO(response.content));content='\n'.join(p.extract_text() for p in pdf.pages)
    assert len(pdf.pages)==1
    for v in ['Laporan Penggilingan','Ya · 2 sak','Tidak · 0 sak','Tidak tercatat','Rata-rata','Catatan utuh 0','Catatan utuh 2','Nilai mutu:','10 pembacaan','Sisa PK tersedia']:
     assert v in content,v
    assert 'Tidak berlaku untuk gabah kering' not in content and 'tanda tangan' not in content.lower()
    assert pdf.metadata.title=='Laporan Penggilingan'
    bukti('penggilingan-data-uji.pdf',response.content)
  async with pg() as db:assert await sidik(db)==before

@pytest.mark.parametrize('role,warehouse,view,allowed',[
 ('superadmin',None,None,True),('admin',None,None,True),('operator','Gudang 1',None,True),
 ('operator','Gudang 2',None,False),('superadmin',None,'operator:g2',False),
 ('superadmin',None,'operator:g1',True)])
async def test_akses_pdf_efektif(pg,pabrik,role,warehouse,view,allowed):
 kode=await _giling_selesai(pg,pabrik)
 async with pg() as db:pid=await db.scalar(select(MillingProcess.id).where(MillingProcess.kode_proses==kode))
 async with await _klien(pg,peran=role,gudang=warehouse) as c:
  if view:
   from app.models import Warehouse
   async with pg() as db:
    if not await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g2')):
     db.add(Warehouse(nama_gudang='Gudang 2 - Penyosohan',kode_fungsi='g2'));await db.commit()
   from tests.pg.formulir import cap_formulir
   assert (await c.post('/lihat-sebagai',data={'peran':view,'_csrf':cap_formulir(c)},follow_redirects=False)).status_code==303
  r=await c.get(f'/riwayat-giling/{pid}/laporan.pdf')
  assert r.status_code==(200 if allowed else 403)

async def test_sopir_dari_tiket_tertaut_dan_qc_header_lama(pg,pabrik,contoh):
 # Tiket uji eksplisit, tanpa pencocokan plat atau nama supplier.
 from app.web.pdf_giling import buat_pdf
 kode=await _giling_selesai(pg,pabrik)
 async with pg() as db:
  proc=await db.scalar(select(MillingProcess).where(MillingProcess.kode_proses==kode))
  batch=await db.scalar(select(PurchaseBatch));batch.timbangan_transaksi_id=contoh['tid'];batch.no_polisi_truk='B 17 UJI';batch.kadar_air_awal_persen=14
  await db.execute(text('UPDATE timbangan_transaksi SET supplier_id=:s,nama_sopir=:n WHERE id=:id'),dict(s=batch.supplier_id,n='Sopir tiket uji',id=contoh['tid']))
  db.add(PurchaseBatchQc(purchase_batch_id=batch.id,lamur=False,jumlah_sak_lamur=0,biji_hijau='sedikit',densiti='padat',input_by=pabrik['user']))
  await db.commit();pid=proc.id
 data=await _ambil_data_laporan_giling(pid)
 assert data['batches'][0]['driver']=='Sopir tiket uji'
 assert data['raw_qc'][0]['number'] is None
 assert data['raw_qc'][0]['lamur']=='Tidak · 0 sak'
 content=' '.join(p.extract_text() for p in PdfReader(BytesIO(buat_pdf(data))).pages)
 assert 'Sopir tiket uji' in content and 'Rincian bacaan tidak tersedia' in content
 assert 'QC historis' in content and '10 pembacaan' not in content
