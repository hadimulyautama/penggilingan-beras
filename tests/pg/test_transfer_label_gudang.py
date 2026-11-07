"""Nama master dan rujukan lokasi dibaca tanpa mutasi transaksi transfer."""
from pathlib import Path
import pytest
from sqlalchemy import select
from app.models import User, Warehouse, MillingProcess, PkGudang2Intake
from app.services import transfer, detail_transfer
from tests.pg.test_permintaan_empat_langkah import pabrik
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_riwayat_sosoh_desain_browser import browser

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('width',[1440,390])
async def test_nama_master_di_semua_tab_dan_panduan(pg,pabrik,width):
 async with pg() as db:
  result=await transfer.create_internal_transfer(db,user=await db.get(User,pabrik['admin']),kode_proses=pabrik['lot'],lokasi_tujuan='ditumpuk',berat=1000)
  tid=result.transfer.id
  for code,nama in [('g1','Selepan Utara'),('g2','Penyosohan Selatan')]:
   w=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi==code));w.nama_gudang=nama
  await db.commit()
 async with await _klien(pg,peran='admin') as c:
  async with browser(c,width) as page:
   await page.goto(f'/riwayat-transfer/{tid}')
   await page.locator('[data-rht-ready]').wait_for()
   for tab in ['ringkasan','bahan','permintaan','riwayat']:
    await page.locator('#tab-'+tab).click()
    text=await page.locator('[data-riwayat-transfer]').inner_text()
    assert 'Selepan Utara' in text and 'Penyosohan Selatan' in text
    assert 'Gudang 1' not in text and 'Gudang 2' not in text
    assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   await page.locator('#tab-ringkasan').click()
   await page.screenshot(path=str(Path('../')/f'transfer-gudang-{width}.png'),full_page=True)
 async with pg() as db:
  from app.models import InternalTransfer
  t=await db.get(InternalTransfer,tid)
  assert t.berat_kg==1000 and t.status=='terkirim'

async def test_identitas_eksplisit_diutamakan_dan_tidak_ditebak(pg,pabrik):
 async with pg() as db:
  result=await transfer.create_internal_transfer(db,user=await db.get(User,pabrik['admin']),kode_proses=pabrik['lot'],lokasi_tujuan='ditumpuk',berat=1000)
  t=result.transfer
  proc=await db.get(MillingProcess,pabrik['proses_id'])
  a=Warehouse(nama_gudang='Cabang A',aktif=False);b=Warehouse(nama_gudang='Cabang B')
  db.add_all([a,b]);await db.flush()
  proc.warehouse_id=a.id
  intake=await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.internal_transfer_id==t.id))
  intake.warehouse_id=b.id
  assert await detail_transfer.gudang_transfer(db,proc,t)==('Cabang A','Cabang B')
  from types import SimpleNamespace
  missing=SimpleNamespace(warehouse_id=999999,silo_id=None)
  assert (await detail_transfer.gudang_transfer(db,missing,t))[0]=='Gudang asal belum tercatat'
  await db.rollback()
