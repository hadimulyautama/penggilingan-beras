"""QC panjang, nama panjang, hasil belum dicatat: data lengkap dan kolom tetap sejajar."""
from pathlib import Path
from dataclasses import replace
import pytest
from tests.pg.test_riwayat_giling import pabrik,_giling_selesai,_klien
from tests.pg.test_riwayat_sosoh_desain_browser import browser
from app.penggilingan.gudang1.services import milling
pytestmark=pytest.mark.asyncio
MUTU='KA 14,1% · broken 26,7% · susut 14,0% (rata-rata 3 catatan) · Rata-rata kategori: Butir kuning Bersih · Gabah Bersih · Merang Bersih'
@pytest.mark.parametrize('width',[1440,1024,390,320])
async def test_qc_lengkap_tabel_sumber_dan_pdf(pg,pabrik,monkeypatch,width,tmp_path):
 from playwright.async_api import expect
 code=await _giling_selesai(pg,pabrik);original=milling.riwayat_giling
 async def contoh(*a,**kw):
  cards,lagi=await original(*a,**kw)
  return [replace(k,mutu=MUTU,nama_pemilik='Pelanggan jasa dengan nama yang sangat panjang',jasa=True,pemilik='Pelanggan jasa',kode_jasa='JAS-UJI') for k in cards],lagi
 monkeypatch.setattr(milling,'riwayat_giling',contoh)
 async with await _klien(pg,peran='admin') as c:
  async with browser(c,width) as page:
   await page.goto('/riwayat-giling');await page.locator('[data-rpd-ready]').wait_for()
   scope=page.locator('.rg-tabel' if width>=900 else '.rg-kartu').first
   if width>=900:
    await scope.locator('[data-rg-qc]').click();await expect(scope.locator('.rg-qc-row p')).to_have_text(MUTU)
   else:
    await scope.locator('.rg-mutu__rincian>summary').click();await expect(scope.locator('.rg-mutu__rincian>div')).to_have_text(MUTU)
   if width>=900:
    # Native table gives every header exactly the same track as its data cell.
    th=await scope.locator('thead th').evaluate_all('(xs)=>xs.map(x=>({x:x.getBoundingClientRect().x,w:x.getBoundingClientRect().width}))')
    td=await scope.locator('tbody>tr').first.locator(':scope>td').evaluate_all('(xs)=>xs.map(x=>({x:x.getBoundingClientRect().x,w:x.getBoundingClientRect().width}))')
    assert len(th)==len(td)==7
    assert all(abs(a['x']-b['x'])<1 and abs(a['w']-b['w'])<1 for a,b in zip(th,td))
    await scope.locator('[data-rg-buka]').first.click();d=page.locator('dialog[open]');await expect(d).to_contain_text('Sudah ditransfer');await expect(d).to_contain_text('Masih tersedia')
    pdf=await d.locator('a[href$="/laporan"]').get_attribute('href');await d.locator('[data-rg-tutup]').click();await expect(d).not_to_be_visible()
   else:
    pdf=await scope.locator('a[href$="/laporan"]').get_attribute('href')
    b=await scope.locator('.rg-kartu__ringkas').bounding_box();assert b['width']>230 and b['height']<1500,b
   response=await c.get(pdf);assert response.status_code==200
   response=await c.get(pdf+'.pdf');assert response.status_code==200 and response.content.startswith(b'%PDF')
   assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
   await page.screenshot(path=str(tmp_path/f'giling-{width}.png'),full_page=True)
   href=await scope.locator('a[href^="/riwayat-giling/"]:not([href$="/laporan"])').first.get_attribute('href');assert (await c.get(href)).status_code==200
   monkeypatch.setattr(milling,'riwayat_giling',original)
   await page.reload();await expect(page.locator('.rg-mutu').first).to_contain_text('Belum dinilai')
