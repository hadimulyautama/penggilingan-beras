"""Pemeriksaan baca dan penyimpanan terkonfirmasi memakai asal otomatis dari stok."""
from pathlib import Path
import pytest
from sqlalchemy import select,func
from app.models import User,Peristiwa,FinishedGoodsStock
from app.services import kepemilikan as s,kepemilikan_pratinjau as pre
from tests.pg.test_kepemilikan_koreksi import world
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_riwayat_sosoh_desain_browser import browser
from tests.pg.formulir import cap_formulir
pytestmark=pytest.mark.asyncio

def data(w,kind):
 if kind=='karung':return dict(aksi='pindah_kepemilikan_karung',karung='biasa|50|',pelanggan=str(w['customers'][1]),jumlah=10)
 return dict(aksi='pindah_kepemilikan_produk',item=f"bj:{w['sku']}||{w['owners'][0]}" if kind=='barang' else f"cr:{kind}|{w['owners'][0]}",jumlah=10)

@pytest.mark.parametrize('kind',['barang','broken','bekatul','karung'])
async def test_pratinjau_tidak_menulis_dan_angka_sesuai_mutasi_asli(pg,world,kind):
 body=data(world,kind);pool='barang' if kind=='barang' else 'karung' if kind=='karung' else 'curah'
 identity=dict(sku=world['sku'],std=None) if pool=='barang' else dict(material=world['material'],size=world['size'],brand=None) if pool=='karung' else dict(jenis=kind)
 async with await _klien(pg,peran='admin') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c)
  async with pg() as db:before=await s.physical(db,pool,identity);count=await db.scalar(select(func.count()).select_from(Peristiwa))
  r=await c.post('/api/actions/pratinjau-kepemilikan',json=body);assert r.status_code==200,r.text
  d=r.json();assert d['plan']['owners']==(['Pabrik'] if pool=='karung' else ['Pelanggan A · JAS-KOREKSI-0'])
  assert d['plan']['destination']==('Pelanggan B' if pool=='karung' else 'Pabrik')
  async with pg() as db:
   assert await s.physical(db,pool,identity)==before
   assert await db.scalar(select(func.count()).select_from(Peristiwa))==count
  payload={k:v for k,v in body.items() if k!='aksi'};payload.update(review=d['review'],confirm=True)
  path='/api/actions/'+body['aksi'].replace('_','-')
  r=await c.post(path,json=payload);assert r.status_code==200,r.text
  async with pg() as db:
   assert await s.physical(db,pool,identity)==before
   e=await db.scalar(select(Peristiwa).where(Peristiwa.jenis==s.AWAL).order_by(Peristiwa.id.desc()))
   for owner,expected in d['plan']['balances_after'].items():
    actual=await s.balance(db,pool,identity,None if owner=='None' else int(owner))
    assert {k:pre.angka(v) for k,v in actual.items()}==expected
  # A retry of the same reviewed request cannot perform a second transfer.
  r=await c.post(path,json=payload);assert r.status_code==400

async def test_stok_berubah_dan_konfirmasi_kosong_ditolak_tanpa_mutasi(pg,world):
 body=data(world,'barang')
 async with await _klien(pg,peran='admin') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c)
  d=(await c.post('/api/actions/pratinjau-kepemilikan',json=body)).json()
  payload=dict(item=body['item'],jumlah=10,review=d['review'],confirm=False)
  assert (await c.post('/api/actions/pindah-kepemilikan-produk',json=payload)).status_code==400
  async with pg() as db:
   row=await db.get(FinishedGoodsStock,world['source']);row.jumlah_karung-=1;row.berat_total_kg-=50;await db.commit()
  payload['confirm']=True
  r=await c.post('/api/actions/pindah-kepemilikan-produk',json=payload)
  assert r.status_code==400 and 'berubah' in r.text
  async with pg() as db:assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis==s.AWAL))==0
 async with await _klien(pg,peran='operator') as c:
  c.headers['X-CSRF-Token']=cap_formulir(c)
  assert (await c.post('/api/actions/pratinjau-kepemilikan',json=body)).status_code==403

@pytest.mark.parametrize('width',[1440,390])
@pytest.mark.parametrize('kind',['barang','broken','bekatul','karung'])
async def test_ui_asal_otomatis_kembali_isian_dan_simpan(pg,world,width,kind):
 from playwright.async_api import expect
 body=data(world,kind);value=body.get('item',body.get('karung'))
 if kind=='karung':
  from app.models import Pelanggan
  async with pg() as db:
   customer=await db.get(Pelanggan,world['customers'][1]);customer.kledo_contact_id=909;await db.commit()
 async with await _klien(pg,peran='admin') as c:
  if kind=='karung':
   r=await c.get('/api/actions/pelanggan-kledo');assert r.status_code==200 and any(str(x['value'])==str(world['customers'][1]) for x in r.json()),r.text
  async with browser(c,width) as page:
   await page.goto('/stok?tab='+('karung' if kind=='karung' else 'produk')+'&buka='+body['aksi']+'&nilai='+__import__('urllib.parse',fromlist=['quote']).quote(value,safe=''))
   await page.locator('#lembar[open]').wait_for()
   await page.locator('#f_jumlah').fill('10')
   if kind=='karung':
    await page.wait_for_function("document.querySelector('#x_pelanggan')._daftarKombo?.length",timeout=5000)
    await page.locator('#x_pelanggan').fill('Pelanggan B')
    await page.locator('.kombo__opsi').filter(has_text='Pelanggan B').click()
   before=await page.locator('#f_jumlah').input_value()
   await page.locator('#simpan').click();await expect(page.locator('.milik-review')).to_be_visible()
   await expect(page.locator('.milik-review')).to_contain_text('Pemilik asal · otomatis dari stok')
   await expect(page.locator('.milik-review')).to_contain_text('Pabrik')
   await expect(page.locator('#ya')).to_be_disabled()
   async with pg() as db:assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis==s.AWAL))==0
   await page.locator('#kembali').click();assert await page.locator('#f_jumlah').input_value()==before
   await page.locator('#simpan').click();await page.locator('[data-milik-confirm]').check()
   assert not await page.locator('#lembar').evaluate('e=>e.scrollWidth>e.clientWidth')
   await page.screenshot(path=str(Path('..')/f'pengalihan-{kind}-{width}.png'),full_page=True)
   await page.locator('#ya').click();await expect(page.locator('#lembar')).not_to_be_visible()
   async with pg() as db:assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis==s.AWAL))==1

async def test_ui_gagal_periksa_dan_stok_berubah_mempertahankan_isian(pg,world):
 from playwright.async_api import expect
 body=data(world,'barang')
 async with await _klien(pg,peran='admin') as c:
  async with browser(c,390) as page:
   from urllib.parse import quote
   await page.goto('/stok?tab=produk&buka='+body['aksi']+'&nilai='+quote(body['item'],safe=''))
   await page.locator('#lembar[open]').wait_for();await page.locator('#f_jumlah').fill('10')
   await page.route('**/api/actions/pratinjau-kepemilikan',lambda r:r.abort())
   await page.locator('#simpan').click()
   await expect(page.locator('#lembar')).to_contain_text('Failed to fetch')
   assert await page.locator('#f_jumlah').input_value()=='10'
   await page.unroute('**/api/actions/pratinjau-kepemilikan')
   await page.locator('#simpan').click();await expect(page.locator('.milik-review')).to_be_visible()
   async with pg() as db:
    row=await db.get(FinishedGoodsStock,world['source']);row.jumlah_karung-=1;row.berat_total_kg-=50;await db.commit()
   await page.locator('[data-milik-confirm]').check();await page.locator('#ya').click()
   await expect(page.locator('#lembar')).to_contain_text('Stok atau pemilik berubah')
   await expect(page.locator('#f_jumlah')).to_be_visible()
   assert await page.locator('#f_jumlah').input_value()=='10'
   async with pg() as db:assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis==s.AWAL))==0
