"""QC asli tetap utuh di tab desktop/ponsel, termasuk draf dan transaksi beras."""
import os
from pathlib import Path
import pytest
from sqlalchemy import select,func
from hmu_identitas.peran import SUPERADMIN,ADMIN,OPERATOR
from app.models import SampelQcSosoh,ActivityLog
from app.services import qc_sosoh as svc
from tests.pg.test_riwayat_qc_detail import qc
from tests.pg.test_qc_sosoh import dunia,ambil
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_riwayat_sosoh_desain_browser import browser

pytestmark=[pytest.mark.asyncio,pytest.mark.skipif(os.getenv('UJI_BROWSER_RIWAYAT_QC_DESAIN')!='1',reason='Browser lokal opsional')]
OUT=Path(__file__).resolve().parents[3]/'bukti'

async def guide(page,width):
 from playwright.async_api import expect
 if width<=700:await page.locator('.rhs-menu>summary').click()
 await page.locator('[data-rqd-guide]:visible').first.click()
 await expect(page.locator('#rqd-panduan')).to_be_visible()
 await page.locator('[data-rqd-guide-close]').click()
 await page.locator('.rhs-menu>summary').click()
 await page.locator('[data-rqd-nav-open]').click()
 await expect(page.locator('#rqd-navigation')).to_be_visible()
 assert await page.locator('#rqd-navigation .laporan-nav__tabs a').count()>=3
 await page.locator('[data-rqd-nav-close]').click()

@pytest.mark.parametrize('width',[1440,390,320])
async def test_semua_jenis_putaran_rumus_asal_dan_navigasi(pg,qc,width):
 from playwright.async_api import expect
 OUT.mkdir(exist_ok=True)
 async with await _klien(pg,peran=SUPERADMIN) as c:
  async with browser(c,width) as page:
   async with pg() as db:before=await db.scalar(select(func.count()).select_from(ActivityLog))
   for jenis,ref,n in [('gabah-basah','GB-QC-BASAH',5),('gabah-kering','GB-QC-KERING',5),('pk-hasil-giling','LOT-QC-DETAIL',3),('pk-luar','PKB-QC-DETAIL',1)]:
    path=f'/riwayat-qc/{jenis}/{ref}'
    await page.goto('/riwayat-qc/'+jenis)
    await page.locator('[data-rqd-ready]').wait_for()
    assert await page.locator('[data-rqd-category-slot] a').count()==5
    await page.locator('.tabel-standar__baris').first.click()
    await expect(page.locator('[data-rqd-panel=ringkasan]')).to_be_visible()
    assert await page.locator('.qc-history-round').count()==n
    await page.locator('#qc-tab-ringkasan').focus();await page.keyboard.press('ArrowRight')
    await expect(page.locator('#qc-tab-putaran')).to_have_attribute('aria-selected','true')
    await page.select_option('#qc-putaran','1');await page.locator('.qc-picker button').click()
    await expect(page.locator('.qc-history-round:visible')).to_have_attribute('data-posisi','1')
    if n>1:
     await page.locator('.qc-pager a').last.click()
     await expect(page.locator('.qc-history-round:visible')).to_have_attribute('data-posisi','2')
    await page.locator('#qc-tab-ringkasan').click();await page.locator('#qc-tab-putaran').click()
    await expect(page.locator('.qc-history-round:visible')).to_have_attribute('data-posisi','2' if n>1 else '1')
    await page.locator('#qc-tab-perhitungan').click()
    await expect(page.locator('#qc-panel-perhitungan')).to_contain_text('kadar air' if jenis.startswith('gabah') else 'Perhitungan nilai gabungan')
    await page.locator('#qc-tab-asal').click()
    await expect(page.locator('#qc-panel-asal')).to_contain_text(ref)
    if jenis=='pk-luar':await expect(page.locator('#qc-panel-asal')).to_contain_text('Contoh catatan laboratorium <b>tetap teks</b>')
    await page.reload();await expect(page.locator('#qc-panel-asal')).to_be_visible()
    await page.locator('#qc-tab-ringkasan').click()
    assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
    await page.screenshot(path=str(OUT/f'{jenis}-{width}.png'),full_page=True)
   await guide(page,width)
   async with pg() as db:assert await db.scalar(select(func.count()).select_from(ActivityLog))==before

@pytest.mark.parametrize('width',[1440,390,320])
async def test_beras_editor_asli_draf_desimal_sampel_dan_pembatalan(pg,dunia,width):
 from playwright.async_api import expect
 from tests.pg.test_riwayat_sosoh import _klien as klien
 q=await ambil(pg,dunia)
 other=await ambil(pg,dunia,'premium',5)
 async with pg() as db:
  await svc.isi_hasil(db,user=dunia['user'],sampel_id=other.id,kadar_air=14,catatan_lab='<b>Catatan asli</b>')
  await svc.batalkan_sampel(db,user=dunia['user'],sampel_id=other.id,alasan='Jenis salah dipilih')
 async with await klien(pg,peran=ADMIN) as c:
  async with browser(c,width) as page:
   path='/riwayat-qc/beras-hasil-sosoh/'+dunia['proc'].kode_proses
   await page.goto(path)
   await expect(page.locator('#qc-panel-ringkasan')).to_be_visible()
   await page.locator('#qc-tab-sampel').click()
   await expect(page.locator('#qc-panel-sampel')).to_contain_text('Dikeluarkan dari pemetaan')
   await page.locator('[data-qc-lengkapi]').click()
   form=page.locator('[data-qc-editor]');await expect(form).to_be_visible()
   assert await form.locator('input[inputmode=decimal]').count()==5
   field=form.locator('[name=kadar_air]');await field.fill('13,455');await field.evaluate("e=>e.dataset.nodeUji='asli'")
   await page.locator('#qc-tab-sesi').click();await page.locator('#qc-tab-sampel').click()
   assert await field.input_value()=='13,455' and await field.get_attribute('data-node-uji')=='asli'
   for name,value in [('broken_persen','9,995'),('md','123,456'),('transparant','1,005'),('whiteness','45,678')]:await form.locator('[name='+name+']').fill(value)
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   OUT.mkdir(exist_ok=True);await page.screenshot(path=str(OUT/f'beras-editor-{width}.png'),full_page=True)
   await form.locator('[data-qc-simpan]').click()
   await expect(page.locator('#qc-panel-sampel')).to_contain_text('Kadar air 13,46%')
   await expect(page.locator('#qc-panel-sampel')).to_contain_text('MD 123,46')
   async with pg() as db:
    saved=await db.get(SampelQcSosoh,q.id);assert float(saved.kadar_air)==13.46 and float(saved.md)==123.46
   await page.locator('#qc-tab-ringkasan').click();await page.locator('[data-qc-baru]').click()
   await expect(form).to_be_visible();await form.locator('[data-qc-jenis=medium]').click()
   await expect(form.locator('[data-qc-kabar]')).to_contain_text('Sampel tersimpan')
   await expect(form.locator('[data-qc-hasil]')).to_be_enabled()
   async with pg() as db:assert await db.scalar(select(func.count()).select_from(SampelQcSosoh))==3
   await form.locator('[data-qc-nanti]').click()
   await expect(page.locator('[data-qc-editor]')).to_be_hidden()
   await page.locator('#qc-tab-sampel').click()
   await page.locator('a[href*="buka=batalkan_sampel_qc_sosoh"]').first.click()
   await expect(page.locator('#lembar')).to_be_visible()
   await page.locator('#lembar [data-name=alasan]').fill('Uji pembatalan dari riwayat QC')
   await page.locator('#lembar #simpan').click()
   await expect(page.locator('#lembar')).to_be_hidden()
   await expect(page.locator('#qc-panel-sampel')).to_contain_text('Uji pembatalan dari riwayat QC')
   async with pg() as db:
    saved=await db.get(SampelQcSosoh,q.id);assert saved.dibatalkan_pada and float(saved.md)==123.46

   await guide(page,width)

async def test_beras_operator_tanpa_editor_dan_tautan_langsung(pg,dunia):
 from playwright.async_api import expect
 from tests.pg.test_riwayat_sosoh import _klien as klien
 await ambil(pg,dunia)
 async with await klien(pg,peran=OPERATOR,gudang='Gudang 2',lihat='operator:g2') as c:
  async with browser(c,390) as page:
   await page.goto('/riwayat-qc/beras-hasil-sosoh/'+dunia['proc'].kode_proses+'?tab_qc=sampel')
   await expect(page.locator('#qc-panel-sampel')).to_be_visible()
   assert await page.locator('[data-qc-editor],[data-qc-baru],[data-qc-lengkapi],a[href*="buka=batalkan_sampel_qc_sosoh"]').count()==0
   await expect(page.locator('#qc-panel-sampel')).to_contain_text('Menunggu hasil timbang')

@pytest.mark.parametrize('width',[1440,390])
async def test_beras_selesai_total_aktual_sesi_estimasi_dan_lab_tertunda(pg,dunia,width):
 from playwright.async_api import expect
 from datetime import timedelta
 from app.models import PolishingOutputLog,PolishingProcess
 from tests.pg.test_riwayat_sosoh import _klien as klien
 qs=[await ambil(pg,dunia,'medium',0),await ambil(pg,dunia,'premium',5),await ambil(pg,dunia,'medium',7)]
 async with pg() as db:
  for jenis,kg in [('medium',8000),('premium',2000)]:
   db.add(PolishingOutputLog(polishing_process_id=dunia['proc'].id,jenis=jenis,berat_kg=kg,cara_input='kumulatif',waktu_update=dunia['awal']+timedelta(minutes=10),input_by=dunia['user'].id))
  p=await db.get(PolishingProcess,dunia['proc'].id);p.status='selesai';p.waktu_selesai=dunia['awal']+timedelta(minutes=10);await db.commit()
 async with await klien(pg,peran=ADMIN) as c:
  async with browser(c,width) as page:
   await page.goto('/riwayat-qc/beras-hasil-sosoh/'+dunia['proc'].kode_proses)
   assert await page.locator('[data-qc-baru]').count()==0
   await expect(page.locator('#qc-panel-ringkasan')).to_contain_text('8000,00 kg')
   await expect(page.locator('#qc-panel-ringkasan')).to_contain_text('2000,00 kg')
   await page.locator('#qc-tab-sesi').click()
   await expect(page.locator('#qc-panel-sesi')).to_contain_text('≈ 5000,00 kg · estimasi')
   await expect(page.locator('#qc-panel-sesi')).to_contain_text('≈ 3000,00 kg · estimasi')
   await expect(page.locator('#qc-panel-sesi')).to_contain_text('Pergantian di antara')
   await expect(page.locator('#qc-panel-sesi')).to_contain_text('Sampel teramati')
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   OUT.mkdir(exist_ok=True);await page.screenshot(path=str(OUT/f'beras-sesi-{width}.png'),full_page=True)
   await page.locator('#qc-tab-sampel').click()
   await page.locator('[data-qc-lengkapi]').first.click()
   await expect(page.locator('[data-qc-editor]')).to_be_visible()
   await page.locator('[name=md]').fill('120,1')
   await page.locator('#qc-tab-asal').click();await page.locator('#qc-tab-sampel').click()
   assert await page.locator('[name=md]').input_value()=='120,1'
   await page.locator('[data-qc-simpan]').click()
   await expect(page.locator('#qc-panel-sampel')).to_contain_text('MD 120,10')
   async with pg() as db:assert float((await db.get(SampelQcSosoh,qs[0].id)).md)==120.1
