"""Halaman baca baru mempertahankan rincian dan pintu tindakan aslinya."""
import os
from pathlib import Path
from uuid import uuid4
import pytest
from sqlalchemy import select,text
from app.services import retur_supplier_koreksi as k
from app.models.retur_supplier import ReturSupplierKeluar
from tests.pg.test_retur_supplier import asal,skema_retur_timbang,user
from tests.pg.test_retur_supplier_koreksi import keluar_dua
from tests.pg.test_riwayat_retur_supplier import sidik_semua
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_riwayat_sosoh_desain_browser import browser

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_RETUR_SUPPLIER_DESAIN')!='1',reason='Browser lokal opsional')]

@pytest.mark.parametrize('width',[1440,390,320])
async def test_empat_tab_rincian_panduan_konteks_dan_form_asli(pg,keluar_dua,width):
 from playwright.async_api import expect
 x=keluar_dua;url=f'/riwayat-retur-supplier/{x["rid"]}?q=Uji&halaman=2&penerimaan={x["tid"]}'
 out=Path('../bukti');out.mkdir(exist_ok=True)
 async with pg() as db:before=await sidik_semua(db)
 async with await _klien(pg,peran='admin',gudang='Gudang 2') as c:
  async with browser(c,width) as page:
   await page.goto(url);await page.locator('[data-rsd-ready]').wait_for()
   await expect(page.locator('.rhs-header h1')).to_have_text('Riwayat retur ke supplier')
   assert await page.locator('.rsh-tabs [role=tab]').count()==4
   assert await page.locator('#rsd-tab-ringkasan').evaluate('e=>getComputedStyle(e).backgroundColor')=='rgba(0, 0, 0, 0)'
   assert await page.locator('.rsp-stack>.rsp-kartu').filter(has_text='Barang pada retur').locator('.rsp-item').count()==2
   for label in ['Diajukan','Aktual dimuat','Keluar awal tercatat','Keluar efektif saat ini','Total aktual dimuat','Penerimaan & sumber','Alasan retur']:await expect(page.locator('#rsd-panel')).to_contain_text(label)
   assert not await page.locator('[data-riwayat-retur-supplier]').evaluate('e=>e.scrollWidth>e.clientWidth')
   await page.screenshot(path=str(out/f'ringkasan-{width}.png'),full_page=True)
   if width<=700:await page.locator('.rhs-menu>summary').click()
   await page.locator('[data-rsd-guide]:visible').click();await expect(page.locator('#rsd-panduan')).to_contain_text('tidak menambah stok');await page.locator('[data-rsd-guide-close]').click()
   await page.locator('#rsd-tab-timbang').click();await page.locator('[data-rsd-ready]').wait_for()
   for label in ['Tiket retur terkini','Rekaman timbang saat pemeriksaan','Verifikasi PadiFlow','Riwayat hasil pemeriksaan','Koreksi tiket yang relevan','Revisi tiket saat pemeriksaan']:await expect(page.locator('#rsd-panel')).to_contain_text(label)
   assert 'tab=timbang' in page.url and 'halaman=2' in page.url and 'q=Uji' in page.url
   await page.get_by_text('Rincian tara kemasan',exact=True).click();await expect(page.locator('#rsd-panel')).to_contain_text('Tara adalah toleransi')
   await page.locator('#rsd-tab-stok').click();await page.locator('[data-rsd-ready]').wait_for()
   for label in ['Stok fisik sebelum','Karung sebelum','Karung sesudah','Alokasi sendiri dilepas','Alokasi lain saat transaksi tetap berlaku','Sisa alokasi yang tidak ikut keluar','Tambahan dari stok bebas','Stok tersedia sesudah transaksi','Catatan barang keluar']:await expect(page.locator('#rsd-panel')).to_contain_text(label)
   assert await page.locator('#rsd-panel a').filter(has_text='Buka Stok terkini').count()==2
   await page.screenshot(path=str(out/f'stok-{width}.png'),full_page=True)
   await page.locator('#rsd-tab-jejak').click();await page.locator('[data-rsd-ready]').wait_for();await expect(page.locator('#rsd-panel')).to_contain_text('Jejak pengajuan & penyelesaian');await expect(page.locator('#rsd-panel')).to_contain_text('Dokumen & tautan')
   await page.get_by_text('Nilai sebelum / sesudah dan versi data',exact=True).first.click();assert await page.locator('#rsd-panel pre:visible').count()>=2
   await page.locator('#rsd-tab-ringkasan').click();await page.locator('[data-rsd-ready]').wait_for();await page.locator('#rsd-tab-ringkasan').focus();await page.keyboard.press('ArrowRight');await expect(page.locator('#rsd-tab-timbang')).to_have_attribute('aria-selected','true')
   await page.locator('.rsd-actions a').filter(has_text='Koreksi pencatatan').click();await page.locator('[data-rsk-form]').wait_for()
   # Formulir asli tetap mempunyai seluruh baris dengan satuan sumbernya.
   assert await page.locator('[data-rsk-item]').count()==2
   await page.locator('select[name=jenis]').select_option('keterangan');await page.locator('[name=keterangan]').fill('Pemeriksaan dokumen uji')
   assert await page.locator('[name=keterangan]').input_value()=='Pemeriksaan dokumen uji'
   # Tidak simpan pada uji baca ini; kembali melalui jalur asli.
   await page.goto(url);await page.locator('.rsd-actions a').filter(has_text='Pembatalan setelah keluar').click();await page.locator('[data-rsk-form]').wait_for()
   assert await page.locator('[name=keberadaan]').count()==2
   await page.goto(url);await page.locator('[data-rsd-ready]').wait_for();await page.locator('.rhs-menu>summary').click();await page.locator('.rhs-menu-body a').filter(has_text='Lihat mutasi stok').click();await page.locator('[data-rsd-ready]').wait_for();await expect(page.locator('#catatan-keluar')).to_be_in_viewport()
   assert 'tab=stok' in page.url and 'q=Uji' in page.url
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
 async with pg() as db:assert await sidik_semua(db)==before

async def test_tiket_berubah_snapshot_lama_dan_saldo_historis(pg,keluar_dua):
 from playwright.async_api import expect
 x=keluar_dua
 async with pg() as db:
  await db.execute(text('UPDATE timbangan_transaksi SET jumlah_revisi=jumlah_revisi+1,berat_barang_kg=999 WHERE id=:id'),{'id':x['tid_out']})
  ledger=await db.scalar(select(ReturSupplierKeluar).where(ReturSupplierKeluar.retur_supplier_id==x['rid']));ledger.snapshot=dict(ledger.snapshot,items=[]);await db.commit();before=await sidik_semua(db)
 async with await _klien(pg,peran='admin',gudang='Gudang 2') as c:
  async with browser(c,390) as page:
   await page.goto(f'/riwayat-retur-supplier/{x["rid"]}?tab=timbang');await expect(page.locator('#rsd-panel')).to_contain_text('Data tiket terkini berbeda');await expect(page.locator('#rsd-panel')).to_contain_text('999 kg');await expect(page.locator('#rsd-panel')).to_contain_text('249,5 kg')
   await page.locator('#rsd-tab-stok').click();await expect(page.locator('#rsd-panel')).to_contain_text('Snapshot mutasi barang ini belum lengkap');await expect(page.locator('#rsd-panel')).not_to_contain_text('Stok fisik sesudah')
 async with pg() as db:assert await sidik_semua(db)==before

async def test_perubahan_pasca_keluar_dan_batal_tanpa_stok_masuk(pg,keluar_dua):
 from playwright.async_api import expect
 x=keluar_dua
 async with pg() as db:
  for jenis,extra in [('keterangan',{'keterangan':'Keterangan diperbaiki'}),('batal',{'keberadaan':'kembali'})]:
   key=uuid4().hex;c=await k.periksa(db,user=user(x),identitas=x['rid'],kunci=key,jenis=jenis,alasan='Pemeriksaan dokumen dan barang',konfirmasi=True,**extra)
   await k.simpan(db,user=user(x),identitas=x['rid'],kunci=key,dasar=c['dasar'],konfirmasi=True);await db.commit()
  before=await sidik_semua(db)
 async with await _klien(pg,peran='admin',gudang='Gudang 2') as c:
  async with browser(c,320) as page:
   await page.goto(f'/riwayat-retur-supplier/{x["rid"]}?tab=jejak');await expect(page.locator('[data-riwayat-retur-supplier]')).to_contain_text('Pembatalan administratif')
   for label in ['Koreksi keterangan','Dampak stok 0 kg','Menunggu penerimaan kembali','Buka hasil dan audit tindakan']:await expect(page.locator('#rsd-panel')).to_contain_text(label)
   assert await page.locator('.rsd-actions a').count()==0
   await page.locator('#rsd-panel a').filter(has_text='Buka hasil dan audit tindakan').first.click();await page.locator('[data-rsk]').wait_for()
 async with pg() as db:assert await sidik_semua(db)==before
