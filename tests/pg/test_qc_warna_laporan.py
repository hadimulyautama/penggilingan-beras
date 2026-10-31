"""Perbandingan geometri, isi, dan sumber snapshot sebelum/sesudah pewarnaan."""
from io import BytesIO
import pytest
from pypdf import PdfReader
from sqlalchemy import select
from app.web import qc_warna
from app.models import PkPurchaseBatch,PkPurchaseVerification
from app.web.laporan_sosoh import ambil_data,buat_pdf
from tests.pg.test_gudang2_operator_pg import gudang2
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_pdf_penerimaan import penerimaan
from tests.pg.test_masuk_detail_timbang import contoh
from tests.pg.test_pdf_giling_desain import sidik,bukti
from app.database import now_local
pytestmark=pytest.mark.asyncio


def signature(data):
 r=PdfReader(BytesIO(data))
 return [(tuple(p.mediabox),' '.join((p.extract_text() or '').split())) for p in r.pages]

async def test_penerimaan_angka_geometri_sama_dan_warna_rata(pg,penerimaan,monkeypatch):
 async with await _klien(pg,peran='admin') as c:
  colored=await c.get(f'/barang-masuk/{penerimaan["tid"]}/laporan.pdf')
  assert colored.status_code==200
  monkeypatch.setattr(qc_warna,'warna',lambda *_:None)
  plain=await c.get(f'/barang-masuk/{penerimaan["tid"]}/laporan.pdf')
  assert signature(colored.content)==signature(plain.content)
  assert b'.835294 .921569 .819608 rg' in PdfReader(BytesIO(colored.content)).pages[0].get_contents().get_data()

async def test_sosoh_warna_tiga_parameter_dalam_sel_lama_tanpa_perubahan_data(pg,gudang2,monkeypatch):
 from app.penggilingan.gudang2.polishing import mulai_penyosohan,catat_output,selesai_penyosohan,akhiri_penyosohan
 u=gudang2['user']
 async with pg() as db:
  b=await db.scalar(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch=='PKB-20260912-02'))
  db.add(PkPurchaseVerification(pk_purchase_batch_id=b.id,kadar_air=14,broken_persen=20,penyusutan_persen=10,butir_kuning='sedikit',gabah='bersih',merang='parah',keputusan='terima',waktu_verifikasi=now_local(),verified_by=u.id))
  await db.commit()
  proc=(await mulai_penyosohan(db,user=u,nama_silos=['B'])).proc
  await catat_output(db,user=u,kode=proc.kode_proses,jenis='medium',berat_kumulatif=6500)
  await selesai_penyosohan(db,user=u,kode=proc.kode_proses,nama_silo='B',sisa_kg=0)
  await akhiri_penyosohan(db,user=u,kode=proc.kode_proses)
 d=await ambil_data(proc.id);before=repr(d)
 async with pg() as db:database_before=await sidik(db)
 colored=buat_pdf(d)
 bukti('penyosohan-data-uji.pdf',colored)
 monkeypatch.setattr(qc_warna,'warna',lambda *_:None)
 plain=buat_pdf(d)
 assert signature(colored)==signature(plain)
 assert repr(d)==before
 async with pg() as db:assert await sidik(db)==database_before
 text=' '.join(' '.join(p.extract_text() for p in PdfReader(BytesIO(colored)).pages).split())
 assert 'sedikit / bersih / parah' in text
