"""UI asli dengan API terisolasi: data lengkap, kontrol, koreksi dan pembatalan."""
import copy,json
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import pytest
from playwright.sync_api import sync_playwright,expect

R=Path(__file__).resolve().parents[1]

def detail(kind='karung'):
 state=dict(kind=kind,quantity=120,kg=None if kind=='karung' else 6000,customer=None if kind=='pk' else 7,
            owners=[7],status='terkoreksi',version=1,parties={'7':'Pak Pras','None':'Pabrik'})
 line=dict(source_id=41,target_id=42,source_owner=7,quantity=120,kg=state['kg'],
           free=100,used=20,source_before=dict(source_type='pembelian',source_id=11),
           consistent=True,blocker='20 lembar sudah terikat pada penggunaan berikutnya.')
 state['lines']=[line]
 original=copy.deepcopy(state);original.update(quantity=150,version=0,status='aktif')
 return dict(id=128,code='PKM/00128',state=state,original=original,
             description=dict(unit='kg' if kind=='pk' else 'lembar' if kind=='karung' else 'karung',
                              label='Karung laminasi · Hadi Mulya · 25 kg',warehouses=['Gudang 2'],
                              capacity_note='Ukuran tercatat 25 kg per lembar.'),
             names={'7':'Pak Pras','None':'Pabrik'},time='2026-11-04T13:14:00Z',actor='Admin A',
             baseline='baseline-uji',lines=[line],balances={'7':{'lembar':120},'None':{'lembar':240}},
             history=[dict(before=original,after=state,reason='Jumlah awal salah catat',
                           time='2026-11-04T14:00:00Z',actor='Admin B')])

def document(data,theme):
 css=''.join((R/'hmu_tampilan/static'/f).read_text() for f in
             ['app.css','komponen-portal.css','panduan.css','padiflow-brand.css','stok-seragam.css'])
 css+=(R/'app/web/static/kepemilikan.css').read_text()
 return '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+'</style><body class="padiflow-ui '+theme+'"><style>body{padding-left:0!important}</style><main class="isi"><section data-kepemilikan data-actor="uji"><div data-ko-controls></div><div data-ko-message role="status"></div><div data-ko-error role="alert"></div><div data-ko-recovery hidden><button data-ko-latest>Baca status terbaru</button></div><div data-ko-body></div></section></main><script type="application/json" id="kepemilikan-awal">'+json.dumps(data)+'</script><script src="/static/kepemilikan.js"></script></body>'

def route_for(page,data,theme,requests):
 def handler(route):
  u=urlsplit(route.request.url);path=u.path
  if path=='/static/kepemilikan.js':route.fulfill(path=R/'app/web/static/kepemilikan.js');return
  if path.startswith('/api/'):
   requests.append((path,route.request.method,parse_qs(u.query),route.request.post_data_json if route.request.method=='POST' else None))
   if path in ['/api/actions/pelanggan-kledo','/api/pk-kepemilikan/pemilik']:value=[dict(label='Pak Pras',value=7),dict(label='Genta PK',value=8)]
   elif path.endswith('/sumber'):value=dict(items=[dict(id=41,label='Pak Pras · JAS/007 · Sumber #41',available=120)],total=1,page=1,pages=1)
   elif path.endswith('/periksa'):
    before=data['state'];after={**before,'quantity':100};value=dict(review='bukti-uji',plan=dict(before=before,after=after,balances_before={'7':{'lembar':120}},balances_after={'7':{'lembar':100}}))
   elif path.endswith('/simpan'):value=dict(event_id=22)
   elif path=='/api/kepemilikan/128':value=data
   elif path=='/api/kepemilikan':value=dict(total=2,page=1,pages=2,items=[dict(id=128,code='PKM/00128',summary='Pabrik → Pak Pras · Karung laminasi · Hadi Mulya · 25 kg',status='terkoreksi',quantity=120,kind='karung',time='2026-11-04T13:14:00Z'),dict(id=129,code='PKM/00129',summary='Pak Pras → Pabrik · Premium',status='aktif',quantity=30,kg=1500,kind='barang',time='2026-11-03T13:14:00Z')])
   else:raise AssertionError(path)
   route.fulfill(json=value);return
  route.fulfill(body=document(data,theme),content_type='text/html')
 page.route('**/*',handler)

def no_overflow(page):
 assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
 assert page.locator('[data-kepemilikan]').evaluate('(e)=>e.scrollWidth <= e.clientWidth')

@pytest.mark.parametrize('width',[320,390,760,1440])
@pytest.mark.parametrize('theme',['','terik'])
def test_daftar_kontrol_isi_tema_dan_ukuran(width,theme):
 with sync_playwright() as p:
  b=p.chromium.launch();page=b.new_page(viewport=dict(width=width,height=1000));requests=[];errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)));route_for(page,None,theme,requests)
  page.goto('https://uji.local/kepemilikan?kind=karung&kembali_stok=%2Fstok%3Ftab%3Dkarung')
  expect(page.get_by_role('heading',name='Riwayat kepemilikan',exact=True)).to_be_visible()
  for text in ['PKM/00128','Pak Pras','Karung laminasi','Hadi Mulya','25 kg','120 lembar','30 karung · 1.500 kg','Terkoreksi','Halaman 1 / 2']:
   assert text in page.locator('[data-ko-body]').inner_text()
  assert page.locator('.sk-tab [aria-current=page]').inner_text()=='Karung'
  assert 'kembali_stok=' in page.get_by_role('link',name='Produk',exact=True).get_attribute('href')
  filt=page.get_by_role('button',name='Buka filter riwayat') if width<=650 else page.get_by_role('button',name='Filter',exact=True)
  search=page.get_by_role('searchbox');search.fill('Pras');page.get_by_role('button',name='Cari',exact=True).click()
  expect(page.get_by_role('searchbox')).to_have_value('Pras')
  assert requests[-1][2]['q']==['Pras']
  filt.click();expect(page.get_by_role('dialog',name='Filter riwayat')).to_be_visible()
  page.locator('select[name=status]').select_option('terkoreksi');page.get_by_role('button',name='Terapkan filter').click()
  expect(page.get_by_role('searchbox')).to_have_value('Pras');assert requests[-1][2]['status']==['terkoreksi']
  assert requests[-1][2]['kembali_stok']==['/stok?tab=karung']
  if width<=650:page.get_by_role('button',name='Panduan dan print').click()
  page.locator('.sk-menu > button' if width<=650 else '.sk-tindakan-desktop button').first.click()
  expect(page.get_by_role('dialog',name='ⓘ Panduan kepemilikan')).to_be_visible();page.keyboard.press('Escape')
  assert page.get_by_role('link',name='Catatan lama').count()==1
  assert page.get_by_role('link',name='Berikutnya').count()==1
  no_overflow(page);assert not errors
  root=page.locator('[data-kepemilikan]');assert root.evaluate('(e)=>getComputedStyle(e).maxWidth')=='none'
  b.close()

@pytest.mark.parametrize('width',[390,1440])
@pytest.mark.parametrize('kind',['karung','barang','pk'])
def test_detail_koreksi_pemeriksaan_konfirmasi_dan_batal(width,kind):
 with sync_playwright() as p:
  b=p.chromium.launch();page=b.new_page(viewport=dict(width=width,height=1000));requests=[];errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)));data=detail(kind);route_for(page,data,'terik',requests)
  page.goto('https://uji.local/kepemilikan/128?kembali=%2Fkepemilikan%3Fkind%3Dkarung%26status%3Daktif')
  expect(page.get_by_role('heading',name='PKM/00128')).to_be_visible()
  for text in ['Gudang 2','Admin A','Awal tercatat','Sumber #41 → baris #42','Masih bebas','Terpakai / terikat','pembelian #11',('Saldo sumber PK ini' if kind=='pk' else 'Saldo tersedia saat ini'),'Ukuran tercatat']:
   assert text in page.locator('[data-ko-body]').inner_text()
  assert page.get_by_role('link',name='← Riwayat kepemilikan').get_attribute('href')=='/kepemilikan?kind=karung&status=aktif'
  page.get_by_text('Riwayat perubahan · 2',exact=True).click();assert 'Jumlah awal salah catat' in page.locator('[data-ko-body]').inner_text()
  assert page.get_by_role('link',name='Audit terkait').count()==1
  no_overflow(page)
  page.get_by_role('button',name='Koreksi transaksi',exact=True).click()
  page.get_by_role('spinbutton').fill('100');page.get_by_role('textbox',name='Alasan koreksi (wajib)').fill('Jumlah dicatat terlalu banyak')
  if kind=='karung':expect(page.get_by_role('combobox')).to_have_value('7')
  elif kind=='barang':
   page.get_by_text('Perbaiki pemilik / baris sumber (jika salah)',exact=True).click();page.get_by_role('button',name='Cari sumber').click();page.get_by_role('checkbox').check()
  page.get_by_role('button',name='Periksa dampak').click()
  expect(page.get_by_role('heading',name='Dampak sebelum disimpan')).to_be_visible()
  expect(page.get_by_role('button',name='Simpan koreksi')).to_be_disabled()
  assert not any(path.endswith('/simpan') for path,*_ in requests)
  no_overflow(page)
  page.get_by_role('checkbox',name='Saya sudah memeriksa pemilik, jumlah, dan dampak stok.').check()
  page.get_by_role('button',name='Simpan koreksi').click()
  expect(page.locator('[data-ko-message]')).to_contain_text('audit #22')
  saved=next(q for path,method,_,q in requests if path.endswith('/simpan'));assert saved['confirm'] and saved['review']=='bukti-uji' and saved['quantity']==100 and saved['baseline']=='baseline-uji'
  assert saved['source_ids']==([41] if kind=='barang' else [])
  page.get_by_role('button',name='Batalkan perpindahan',exact=True).click()
  page.get_by_role('textbox',name='Alasan pembatalan (wajib)').fill('Transaksi salah tujuan');page.get_by_role('button',name='Periksa dampak').click()
  expect(page.get_by_role('button',name='Konfirmasi pembatalan')).to_be_disabled();no_overflow(page)
  assert not errors
  b.close()


@pytest.mark.parametrize('width',[390,1440])
@pytest.mark.parametrize('mode',['ubah','batal'])
def test_pratinjau_pk_berantai_menampilkan_bobot_transfer_silo_dan_bahan_sosoh(width,mode):
 data=detail('pk');data['state'].update(quantity=12500,kg=12500,status='aktif',version=0)
 data['code']='AM-PK-10';data['description']['warehouses']=['Gudang 1']
 plan=dict(before=data['state'],after={**data['state'],'quantity':10000 if mode=='ubah' else 0},
  balances_before={'None':{'kg':0},'7':{'kg':0}},balances_after={'None':{'kg':0},'7':{'kg':2500 if mode=='ubah' else 12500}},
  pk_chain=dict(transfers=[dict(id=1,kode='TRF-UJI-01',effective_before='12500',effective_after='10000' if mode=='ubah' else '0')],
   intakes=[dict(id=2,effective_before='12500',effective_after='10000' if mode=='ubah' else '0')],moves=[],
   processes=[dict(id=1,kode='POL-UJI-01',bahan_before='22477.5',bahan_after='19977.5' if mode=='ubah' else '9977.5')],
   warnings=['Hasil tercatat perlu diperiksa setelah pembatalan.'] if mode=='batal' else []))
 with sync_playwright() as p:
  b=p.chromium.launch();page=b.new_page(viewport=dict(width=width,height=1100));calls=[];errors=[]
  page.on('pageerror',lambda e:errors.append(str(e)));route_for(page,data,'terik',calls)
  def review(route):
   calls.append(('periksa',route.request.post_data_json));route.fulfill(json=dict(plan=plan,review='review-rantai'))
  def save(route):
   calls.append(('simpan',route.request.post_data_json));route.fulfill(json=dict(event_id=99,plan=plan))
  page.route('**/api/kepemilikan/128/periksa',review);page.route('**/api/kepemilikan/128/simpan',save)
  page.goto('https://uji.local/kepemilikan/128')
  page.get_by_role('button',name='Koreksi transaksi' if mode=='ubah' else 'Batalkan perpindahan',exact=True).click()
  if mode=='ubah':page.get_by_role('spinbutton').fill('10000')
  page.get_by_role('textbox',name='Alasan '+('koreksi' if mode=='ubah' else 'pembatalan')+' (wajib)').fill('Betulkan angka berantai melalui aplikasi')
  page.get_by_role('button',name='Periksa dampak',exact=True).click()
  expect(page.locator('[data-ko-chain]')).to_be_visible()
  text=page.locator('[data-ko-chain]').inner_text()
  assert 'TRF-UJI-01' in text and 'POL-UJI-01' in text and '22.477,5 kg' in text
  assert ('19.977,5 kg' if mode=='ubah' else '9.977,5 kg') in text
  if mode=='batal':assert page.locator('[data-ko-chain] [role=alert]').is_visible()
  assert 'Lokasi tetap' not in page.locator('[data-ko-body]').inner_text()
  button=page.get_by_role('button',name='Simpan koreksi' if mode=='ubah' else 'Konfirmasi pembatalan',exact=True)
  expect(button).to_be_disabled();assert not any(c[0]=='simpan' for c in calls)
  no_overflow(page)
  out=Path('/private/tmp/pk-koreksi-rantai-visual');out.mkdir(exist_ok=True)
  page.screenshot(path=str(out/f'{mode}-{width}.png'),full_page=True)
  page.get_by_role('checkbox',name='Saya sudah memeriksa pemilik, bobot transfer, bahan proses lanjutan, dan seluruh peringatan.').check()
  button.click();expect(page.locator('[data-ko-message]')).to_contain_text('bahan proses terkait sudah disesuaikan')
  assert next(c[1] for c in calls if c[0]=='simpan')['review']=='review-rantai'
  assert not errors;b.close()
