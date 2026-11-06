"""Desain baru menjalankan tab, draf dan POST asli pada Postgres lokal."""
import os
from pathlib import Path
import pytest
from sqlalchemy import select,func
from app.models import User,InternalTransfer,PermintaanPk
from app.services import transfer
from tests.pg.test_permintaan_empat_langkah import pabrik,_minta,_acc,_kirim
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_riwayat_sosoh_desain_browser import browser
from tests.pg.test_detail_transfer_pk import _saldo

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_TRANSFER_DESAIN')!='1',reason='Browser lokal opsional')]

@pytest.fixture
async def langsung(pg,pabrik):
 async with pg() as db:
  r=await transfer.create_internal_transfer(db,user=await db.get(User,pabrik['admin']),kode_proses=pabrik['lot'],lokasi_tujuan='ditumpuk',berat=1000)
  return dict(**pabrik,tid=r.transfer.id,kode=r.transfer.kode_transfer)

@pytest.mark.parametrize('width',[1440,390,320])
async def test_tab_draf_koreksi_ditolak_dan_nol_asli(pg,langsung,width):
 from playwright.async_api import expect
 d=langsung;url=f'/riwayat-transfer/{d["tid"]}?kembali_kerja=%2Fpekerjaan%3Ftab%3Dberjalan';out=Path('../bukti');out.mkdir(exist_ok=True)
 async with await _klien(pg,peran='admin') as c:
  before=await _saldo(pg,d['proses_id'])
  async with browser(c,width) as page:
   await page.goto(url);await page.locator('[data-rht-ready]').wait_for();assert await page.locator('.transfer-tabs [role=tab]').count()==4
   await expect(page.locator('.rhs-header h1')).to_have_text('Riwayat transfer PK')
   for text in ['1.000 kg','5.000 kg','Transfer aktif seluruh lot']:await expect(page.locator('#panel-ringkasan')).to_contain_text(text)
   assert await page.locator('#tab-ringkasan').evaluate('e=>getComputedStyle(e).backgroundColor')=='rgba(0, 0, 0, 0)'
   await page.screenshot(path=str(out/f'ringkasan-{width}.png'),full_page=True)
   await page.locator('#tab-bahan').click()
   for text in ['6.000 kg','Hasil PK lot','Retur PK langsung','Barang keluar langsung','PK tersisa di Gudang 1']:await expect(page.locator('#panel-bahan')).to_contain_text(text)
   assert '/riwayat-giling/' in await page.locator('#panel-bahan a').last.get_attribute('href')
   await page.locator('#tab-permintaan').click();await expect(page.locator('#panel-permintaan')).to_contain_text('Tidak ada permintaan operator')
   await page.locator('#tab-riwayat').click();await expect(page.locator('#panel-riwayat')).to_contain_text('20 karung × 50 kg')
   await page.locator('#tab-ringkasan').focus();await page.keyboard.press('ArrowRight');await expect(page.locator('#panel-bahan')).to_be_visible()
   if width<=700:await page.locator('.rhs-menu>summary').click()
   await page.locator('[data-rht-guide]:visible').click();await expect(page.locator('#rht-panduan')).to_contain_text('Bobot 0 membatalkan tanpa pengganti');await page.keyboard.press('Escape')
   await page.locator('[data-rht-edit]').click();editor=page.locator('.rht-correction');await expect(editor).to_be_visible()
   field=page.locator('[name=hasil_transfer]');await field.fill('900');await page.locator('[name=alasan]').fill('Hasil pemeriksaan <uji>');await field.evaluate('e=>e.dataset.nodeUji="asli"')
   await page.keyboard.press('Escape');await page.locator('#tab-bahan').click();await page.locator('[data-rht-edit]').click();assert await field.input_value()=='900' and await field.get_attribute('data-node-uji')=='asli'
   await page.locator('[name=dasar_transfer]').evaluate('e=>e.value="999"')
   await editor.get_by_role('button',name='Periksa koreksi',exact=True).click();await expect(page.locator('[data-rht-review]')).to_contain_text('999 kg · akan dibatalkan')
   assert await _saldo(pg,d['proses_id'])==before
   await page.screenshot(path=str(out/f'koreksi-{width}.png'),full_page=True)
   await page.locator('[data-rht-confirm]').click();await page.locator('[name=periksa_ulang]').wait_for();await expect(page.locator('.rht-correction')).to_be_visible()
   assert await field.input_value()=='900';assert await page.locator('[name=alasan]').input_value()=='Hasil pemeriksaan <uji>'
   assert await page.locator('[name=dasar_transfer]').input_value()=='1000.00';assert await _saldo(pg,d['proses_id'])==before
   assert await page.locator('[data-rht-ready]').count()==1
   await page.keyboard.press('Escape');await page.locator('#tab-ringkasan').click();await page.locator('[data-rht-edit]').click()
   await page.locator('[name=periksa_ulang]').check();await field.fill('0');await page.locator('.rht-correction').get_by_role('button',name='Periksa koreksi',exact=True).click()
   await expect(page.locator('[data-rht-review]')).to_contain_text('Tidak dibuat · berat akhir 0 kg')
   await page.locator('[data-rht-confirm]').click();await expect(page.locator('.rhs-identity')).to_contain_text('Dibatalkan')
   await expect(page.locator('#panel-riwayat')).to_contain_text('berat akhir transfer 0 kg');await expect(page.locator('#panel-riwayat')).to_contain_text('1.000 kg')
   assert 'kembali_kerja=' in page.url
   await page.locator('#tab-ringkasan').click();await expect(page.locator('#panel-ringkasan')).to_contain_text('6.000 kg')
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   assert await page.locator('[data-riwayat-transfer] a[href$="/laporan.pdf"]').count()==0
   async with pg() as db:
    t=await db.get(InternalTransfer,d['tid']);assert t.berat_kg==1000 and t.status=='dibatalkan'
    assert await db.scalar(select(func.count()).select_from(InternalTransfer))==1

@pytest.mark.parametrize('width',[1440,390])
async def test_permintaan_aksi_asli_paginasi_hash_dan_panduan(pg,pabrik,width):
 from playwright.async_api import expect
 pid=await _minta(pg,pabrik,berat=1000);await _acc(pg,pabrik,pid,berat=1200);p=await _kirim(pg,pabrik,pid,berat=1100)
 async with pg() as db:
  for _ in range(20):await transfer.create_internal_transfer(db,user=await db.get(User,pabrik['admin']),kode_proses=pabrik['lot'],lokasi_tujuan='ditumpuk',berat=10)
 before=await _saldo(pg,pabrik['proses_id'])
 async with await _klien(pg,peran='admin') as c:
  async with browser(c,width) as page:
   await page.goto(f'/riwayat-transfer/{p.internal_transfer_id}#bahan-proses');await expect(page.locator('#panel-bahan')).to_be_visible()
   await page.locator('#tab-permintaan').click()
   for text in ['1.000 kg','1.200 kg','1.100 kg','Belum tercatat']:await expect(page.locator('#panel-permintaan')).to_contain_text(text)
   action=page.locator('[data-aksi-permintaan=tutup_permintaan_pk]');await action.click();await page.locator('#lembar[open]').wait_for()
   await expect(page.locator('#lembar')).to_contain_text('Tutup');await page.keyboard.press('Escape');await expect(page.locator('#panel-permintaan')).to_be_visible()
   await page.locator('#tab-riwayat').click();await page.locator('.transfer-paginasi a').filter(has_text='Lebih lama').click();await expect(page.locator('#panel-riwayat')).to_be_visible();assert 'halaman_transfer=2' in page.url and 'buka=' not in page.url;await expect(page.locator('#lembar')).not_to_be_visible()
   if width<=700:await page.locator('.rhs-menu>summary').click()
   await page.locator('[data-rht-guide]:visible').click();await expect(page.locator('#rht-panduan')).to_be_visible();await page.locator('[data-rht-guide-close]').click()
   await page.reload();await expect(page.locator('#panel-riwayat')).to_be_visible();assert await _saldo(pg,pabrik['proses_id'])==before
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')

async def test_koreksi_positif_tautan_pengganti_asli(pg,langsung):
 from playwright.async_api import expect
 async with await _klien(pg,peran='admin') as c:
  async with browser(c,390) as page:
   await page.goto(f'/riwayat-transfer/{langsung["tid"]}?buka_koreksi=1');await page.locator('.rht-correction[open]').wait_for()
   await page.locator('[name=hasil_transfer]').fill('950');await page.locator('[name=alasan]').fill('Hasil timbang terbaru')
   await page.locator('.rht-correction').get_by_role('button',name='Periksa koreksi',exact=True).click();await page.locator('[data-rht-confirm]').click()
   await expect(page.locator('.rhs-identity')).to_contain_text('Dibatalkan');await expect(page.locator('#panel-riwayat')).to_contain_text('1.000 kg')
   assert await page.locator('#koreksi-transfer a').is_visible();await page.locator('#koreksi-transfer a').click();await expect(page.locator('.rhs-identity')).to_contain_text('Terkirim')
   await expect(page.locator('#panel-ringkasan')).to_contain_text('950 kg')
