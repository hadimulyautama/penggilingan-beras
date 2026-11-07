"""Pemilik dipilih secara eksplisit; pencarian tidak mengubah transaksi atau membuang draf."""
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from contextlib import contextmanager
import pytest
from playwright.sync_api import sync_playwright,expect
from tests.test_pk_kepemilikan_tampilan import document,R

PRAS=dict(value=7,label='Pak Pras · JAS/007')
SRI=dict(value=42,label='Ibu Sri dengan nama pelanggan panjang · JAS/042')

@contextmanager
def screen(width):
 with sync_playwright() as p:
  b=p.chromium.launch();page=b.new_page(viewport=dict(width=width,height=1000));calls=[];errors=[];pending=[];failed=set()
  page.on('pageerror',lambda e:errors.append(str(e)))
  options=dict(gudang=[dict(id=1,nama='Gudang Selepan')],pemilik=[PRAS],sumber=[dict(sumber='tumpukan:13',warehouse_id=1,gudang='Gudang Selepan',label='PK/0013',owner=None,pemilik='Pabrik',tersedia='1000'),dict(sumber='tumpukan:14',warehouse_id=1,gudang='Gudang Selepan',label='PK/0014',owner=7,pemilik=PRAS['label'],tersedia='500')])
  def route(r):
   u=urlsplit(r.request.url);path=u.path;q=parse_qs(u.query)
   if path.startswith('/static/'):
    f=path.rsplit('/',1)[1];target=R/('hmu_tampilan/static' if f=='stok-seragam.css' else 'app/web/static')/f;r.fulfill(path=target);return
   if path.startswith('/api/'):
    body=r.request.post_data_json if r.request.method=='POST' else None;calls.append((path,q,body))
    if path.endswith(('/pilihan','/detail-sumber')):r.fulfill(json=options);return
    if path.endswith('/cari-tujuan'):
     query=q.get('q',[''])[0]
     if query=='lambat':pending.append(r);return
     if query=='gagal' and query not in failed:failed.add(query);r.abort('failed');return
     items=[SRI] if query in ('Sri','gagal') or q.get('page')==['2'] or q.get('pilihan_id')==['42'] else [] if query=='kosong' else [PRAS]
     if q.get('dari')==['7']:items=[x for x in items if x['value']!=7]
     r.fulfill(json=dict(items=items,total=2 if not query else len(items),page=int(q.get('page',['1'])[0]),pages=2 if not query else 1));return
    if path.endswith('/periksa'):
     r.fulfill(json=dict(baseline='base',review='proof',plan=dict(gudang='Gudang Selepan',sumber='PK/0013',physical_before='1000',physical_after='1000',balances_before={'None':{'kg':'1000'},'42':{'kg':'0'}},balances_after={'None':{'kg':'750'},'42':{'kg':'250'}})));return
    raise AssertionError(path)
   r.fulfill(body=document(),content_type='text/html')
  page.route('**/*',route);page.goto('https://uji.local/kepemilikan/pk/baru');page.locator('[data-pk-form]').wait_for(state='visible')
  try:yield page,calls,pending
  finally:
   assert not errors,errors
   b.close()

@pytest.mark.parametrize('width',[320,390,1440])
def test_pilih_keyboard_draf_remote_dan_periksa_tetap_utuh(width):
 with screen(width) as (page,calls,pending):
  field=page.get_by_role('combobox',name='Pemilik tujuan',exact=True)
  expect(field).to_have_value('')
  field.fill('Sri');expect(page.get_by_role('option',name=SRI['label'],exact=True)).to_be_visible()
  field.press('ArrowDown');field.press('Enter');expect(field).to_have_value(SRI['label'])
  assert page.locator('[name=ke]').input_value()=='42'
  page.get_by_label('Bobot yang dialihkan (kg)').fill('250');page.get_by_label('Alasan pengalihan',exact=True).fill('Kesepakatan pelanggan')
  page.reload();expect(field).to_have_value(SRI['label'])
  assert any(q.get('pilihan_id')==['42'] for _,q,_ in calls)
  expect(page.get_by_label('Bobot yang dialihkan (kg)')).to_have_value('250');expect(page.get_by_label('Alasan pengalihan',exact=True)).to_have_value('Kesepakatan pelanggan')
  field.click();expect(page.get_by_role('option',name=PRAS['label'],exact=True)).to_be_visible();page.keyboard.press('Escape');expect(page.locator('[data-pk-target-panel]')).to_be_hidden();expect(field).to_have_value(SRI['label'])
  page.get_by_role('button',name='Periksa dampak',exact=True).click();expect(page.locator('[data-pk-review]')).to_contain_text(SRI['label'])
  request=next(body for path,_,body in calls if path.endswith('/periksa'))
  assert request['ke']==42 and request['dari'] is None and request['quantity']==250
  assert not any(path.endswith('/simpan') for path,_,_ in calls)
  page.get_by_role('button',name='Ubah isian',exact=True).click();expect(field).to_have_value(SRI['label'])
  assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
  field.fill('Sri');expect(page.get_by_role('option',name=SRI['label'],exact=True)).to_be_visible()
  page.screenshot(path=str(Path('..')/f'pemilik-pk-{width}.png'),full_page=True)

@pytest.mark.parametrize('width',[390,1440])
def test_paginasi_kosong_gagal_ulang_dan_tutup(width):
 with screen(width) as (page,calls,pending):
  field=page.get_by_role('combobox',name='Pemilik tujuan',exact=True);field.click()
  expect(page.get_by_role('option',name=PRAS['label'],exact=True)).to_be_visible()
  assert page.get_by_role('option',name='Pabrik',exact=True).count()==0
  page.get_by_role('button',name='Berikutnya',exact=True).click();page.get_by_role('option',name=SRI['label'],exact=True).click();expect(field).to_have_value(SRI['label'])
  field.click();expect(page.locator('[data-pk-target-panel]')).to_be_visible();page.get_by_label('Bobot yang dialihkan (kg)').click();expect(page.locator('[data-pk-target-panel]')).to_be_hidden();expect(field).to_have_value(SRI['label'])
  field.fill('kosong');expect(page.locator('[data-pk-target-status]')).to_contain_text('Tidak ada pilihan')
  field.fill('gagal');expect(page.get_by_role('button',name='Coba lagi',exact=True)).to_be_visible();page.get_by_role('button',name='Coba lagi',exact=True).click();page.get_by_role('option',name=SRI['label'],exact=True).click()
  expect(field).to_have_value(SRI['label']);assert not any(body for _,_,body in calls)

@pytest.mark.parametrize('width',[390,1440])
def test_isian_bebas_bukan_pilihan_dan_balasan_lama_tidak_mengganti_sumber(width):
 with screen(width) as (page,calls,pending):
  field=page.get_by_role('combobox',name='Pemilik tujuan',exact=True)
  field.fill('lambat');page.wait_for_function('document.querySelector("[data-pk-target-status]").textContent.includes("Mencari")');page.wait_for_timeout(350)
  assert pending
  page.get_by_role('combobox',name='Sumber PK dan pemilik asal',exact=True).select_option('tumpukan:14|7')
  expect(field).to_have_value('Pabrik');pending.pop().fulfill(json=dict(items=[SRI],total=1,page=1,pages=1))
  page.wait_for_timeout(50);expect(field).to_have_value('Pabrik');assert page.locator('[name=ke]').input_value()==''
  field.fill('Sri');page.get_by_label('Bobot yang dialihkan (kg)').fill('100');page.get_by_label('Alasan pengalihan',exact=True).fill('Uji')
  page.get_by_role('button',name='Periksa dampak',exact=True).click()
  assert not any(body for _,_,body in calls)
  expect(page.locator('[data-pk-form]')).to_be_visible()
