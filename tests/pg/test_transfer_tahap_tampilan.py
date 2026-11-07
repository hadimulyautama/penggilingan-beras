"""Tahap operasional jelas tanpa mengubah peran, bobot, atau endpoint tindakan."""
from pathlib import Path
from types import SimpleNamespace as N
import pytest
from app.models import User, PermintaanPk
from app.services import detail_transfer, permintaan_pk
from tests.pg.test_permintaan_empat_langkah import pabrik, _minta, _acc, _kirim
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_riwayat_sosoh_desain_browser import browser

@pytest.mark.asyncio
@pytest.mark.parametrize('width',[1440,390])
async def test_empat_tahap_pada_url_yang_sama_dan_detail_transfer(pg,pabrik,width):
 from playwright.async_api import expect
 pid=await _minta(pg,pabrik,berat=1000)
 url=f'/permintaan-pk/{pid}'
 async with await _klien(pg,peran='admin') as c:
  async with browser(c,width) as page:
   async def lihat(judul,status,actor,aksi):
    await page.goto(url);await page.locator('[data-rht-ready]').wait_for()
    await expect(page.locator('.rhs-header h1')).to_have_text(judul)
    await expect(page.locator('[data-rht-state]')).to_have_text(status)
    await expect(page.locator('#tindakan-proses')).to_contain_text(actor)
    assert await page.locator(f'[data-aksi-permintaan={aksi}]').count()==1 if aksi else await page.locator('[data-aksi-permintaan]').count()==0
    assert await page.locator('#tindakan-proses').evaluate('e=>e.compareDocumentPosition(document.querySelector("#ringkasan-proses"))&Node.DOCUMENT_POSITION_FOLLOWING')
    step=page.locator('.transfer-tahap [aria-current=step]')
    if aksi:
     await expect(step).to_contain_text({'acc_permintaan_pk':'Setujui','kirim_permintaan_pk':'Kirim','tutup_permintaan_pk':'Tutup'}[aksi])
    else:assert await step.count()==0
    assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
    await page.screenshot(path=str(Path('..')/f'transfer-{width}-{status.split()[0]}.png'),full_page=True)
   await lihat('Permintaan transfer PK','Menunggu persetujuan Admin','Admin menetapkan','acc_permintaan_pk')
   await expect(page.locator('#tindakan-proses')).to_contain_text('belum memindahkan stok')
   await _acc(pg,pabrik,pid,berat=1000)
   await lihat('Transfer PK aktif','Menunggu muat','Gudang 1','kirim_permintaan_pk')
   p=await _kirim(pg,pabrik,pid,berat=900)
   await lihat('Transfer PK aktif','Menunggu penutupan Admin','PK sudah berpindah','tutup_permintaan_pk')
   await page.goto(f'/riwayat-transfer/{p.internal_transfer_id}');await expect(page.locator('[data-rht-state]')).to_have_text('Menunggu penutupan Admin')
   async with pg() as db:
    await permintaan_pk.tutup_admin(db,user=await db.get(User,pabrik['admin']),permintaan_id=pid,berat_final=900)
   await lihat('Riwayat transfer PK','Transfer selesai','Admin sudah menutup',None)
   await page.locator('#tab-permintaan').click()
   for text in ['1.000 kg','900 kg','Selesai']:await expect(page.locator('#panel-permintaan')).to_contain_text(text)
   await page.locator('#tab-riwayat').click();await expect(page.locator('#panel-riwayat')).to_contain_text('Terkirim')
   async with pg() as db:
    p=await db.get(PermintaanPk,pid);assert p.status=='selesai' and p.berat_kirim_kg==900 and p.berat_final_kg==900

@pytest.mark.parametrize('state,expected',[('ditolak','Permintaan ditolak'),('gugur','Permintaan gugur')])
def test_permohonan_berakhir_tidak_meminta_tindakan_lagi(state,expected):
 d=detail_transfer.keadaan_transfer(None,N(status=state,sebab='Tujuan belum siap'),'Asal','Tujuan')
 assert d['status']==expected and not d['aktif'] and d['judul']=='Riwayat permintaan transfer PK'
 assert 'Tujuan belum siap' in d['keterangan']

def test_catatan_dibatalkan_tidak_dianggap_aktif_meski_permintaan_masih_terbuka():
 d=detail_transfer.keadaan_transfer(N(status='dibatalkan'),N(status='dikirim'),'Asal','Tujuan')
 assert not d['aktif'] and d['status']=='Dibatalkan' and d['judul']=='Riwayat transfer PK'
