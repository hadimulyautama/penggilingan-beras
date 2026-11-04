from pathlib import Path
from urllib.parse import urlsplit,parse_qs
import html,re
import pytest
from playwright.sync_api import sync_playwright,expect
from tests._stok_seragam_fixture import views
R=Path(__file__).resolve().parents[1]
@pytest.mark.parametrize('width',[390,1440])
@pytest.mark.parametrize('tab',['bahan','produk','karung'])
@pytest.mark.parametrize('owner',['pabrik','jasa'])
def test_informasi_saldo_detail_dan_kontrol(width,tab,owner):
 css=''.join((R/'hmu_tampilan/static'/f).read_text() for f in ['app.css','tabel-standar.css','komponen-portal.css','padiflow-brand.css','stok-seragam.css'])
 def render(url):
  q={k:v[0] for k,v in parse_qs(urlsplit(url).query,keep_blank_values=True).items()}
  v=views['|'.join([q.get('tab',tab),q.get('pemilik',owner),q.get('gudang','')])]
  header=re.sub(r'(name="cari"[^>]*value=")[^"]*(")',lambda m:m[1]+html.escape(q.get('cari',''),quote=True)+m[2],v['after'])
  return '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+'</style><body class="padiflow-ui terik"><style>body{padding-left:0!important}</style><div class="bingkai"><main class="isi">'+header+'<div class="stok-isi stok-seragam">'+v['body']+'</div></main></div><script src="/static/stok-seragam.js"></script></body>'
 with sync_playwright() as p:
  b=p.chromium.launch();page=b.new_page(viewport=dict(width=width,height=900));errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
  def route(r):
   path=urlsplit(r.request.url).path
   if path=='/stok':r.fulfill(body=render(r.request.url),content_type='text/html')
   elif path=='/static/stok-seragam.js':r.fulfill(path=R/'hmu_tampilan/static/stok-seragam.js')
   else:r.fulfill(body='')
  page.route('**/*',route);page.goto('http://uji.local/stok?tab='+tab+'&pemilik='+owner)
  body=page.locator('.stok-seragam');saldo=body.locator('.jumlah__angka').all_text_contents();links=body.locator('a[href]').evaluate_all('els=>els.map(e=>e.getAttribute("href"))')
  assert page.locator('.sk-tab [aria-current=page]').count()==1
  fields={'bahan':['PK/00821','PK/00819','13,8%','12,4%','0,6%','85 karung','6.800','4.250','4/6 komponen'],'produk':['Premium','Bekatul','10.000','3.000','6.000','1.000','7.000','2.250'],'karung':['Hadi Mulya','Tanpa merek','Karung laminasi','Karung biasa','25','50','240','18','Menipis']}
  for value in fields[tab]:assert value in body.text_content()
  if tab=='bahan':assert len([x for x in links if '/stok/pk/detail?' in x])==4
  if tab=='produk':assert len([x for x in links if '/detail?' in x])==2;assert page.locator('.produk-grup').count()==2
  if tab=='karung':
   assert page.locator('.karung-bagian').count()==2 and page.locator('.karung-jenis').count()==0
   assert page.locator('.karung-tabel tbody tr').count()==2
   assert len([x for x in links if 'pindah_kepemilikan_karung' in x])==(2 if owner=='pabrik' else 0)
  page.get_by_role('searchbox').fill('Tidak ada');page.get_by_role('button',name='Cari',exact=True).click();expect(page.locator('[data-stok-hasil]')).to_contain_text('0 baris cocok')
  assert body.locator('.jumlah__angka').all_text_contents()==saldo
  page.get_by_role('searchbox').press('Escape');expect(page.locator('[data-stok-hasil]')).to_be_hidden();assert body.locator('a[href]').count()==len(links)
  if owner=='jasa':
   page.get_by_role('searchbox').fill('Pras');page.get_by_role('button',name='Cari',exact=True).click();assert '0 baris' not in page.locator('[data-stok-hasil]').inner_text();page.get_by_role('searchbox').press('Escape')
  if width==1440:
   boxes=[page.locator(s).bounding_box() for s in ['.sk-filter-desktop','.sk-cari','.sk-pencarian>button']];assert max(x['y'] for x in boxes)-min(x['y'] for x in boxes)<2
  trigger=page.locator('.sk-filter-desktop' if width==1440 else '.sk-tindakan-ponsel [data-sk-buka="sk-filter"]');trigger.click();expect(page.locator('#sk-filter')).to_be_visible()
  if owner=='pabrik':
   page.locator('#sk-filter [name=pemilik]').select_option('jasa');expect(page.locator('#sk-filter [name=pelanggan_id]')).to_be_enabled();expect(page.locator('#sk-filter [name=pelanggan_id] option')).to_have_count(2)
  page.keyboard.press('Escape');expect(trigger).to_be_focused()
  if width==390:page.get_by_role('button',name='Panduan dan print',exact=True).click();page.locator('#sk-tindakan [data-sk-buka]').click()
  else:page.locator('.sk-tindakan-desktop [data-sk-buka]').click()
  expect(page.locator('#sk-panduan')).to_be_visible();page.get_by_role('button',name='Tutup panduan').click()
  page.evaluate('() => { window.totalPrint=0;window.print=()=>{window.totalPrint++}; }')
  if width==390:
   page.get_by_role('button',name='Panduan dan print',exact=True).click();page.locator('#sk-tindakan [data-sk-cetak]').click()
  else:page.locator('.sk-tindakan-desktop [data-sk-cetak]').click()
  assert page.evaluate('window.totalPrint')==1
  if tab=='karung' and owner=='pabrik':
   action=page.locator('.karung-aksi').first;action.locator('summary').click();expect(action.get_by_role('link',name='Alihkan ke pelanggan')).to_be_visible();action.locator('summary').click()
  assert page.evaluate('document.documentElement.scrollWidth<=innerWidth')
  out=R/'output/stok-seragam';out.mkdir(parents=True,exist_ok=True);page.screenshot(path=str(out/f'{tab}-{owner}-{width}.png'),full_page=True)
  assert not errors,errors;b.close()

def test_kembali_pencarian_tetap_aman():
 from app.web.stok_navigasi import alamat,kembali_aman
 url=alamat('karung','jasa',pelanggan_id=7,gudang='g2',cari='Hadi 25')
 assert parse_qs(urlsplit(kembali_aman(url)).query)['cari']==['Hadi 25']
 assert kembali_aman('https://asing.invalid/stok?cari=apa')==''
 assert 'pelanggan_id' not in alamat('produk','pabrik',pelanggan_id=7)


@pytest.mark.asyncio
@pytest.mark.parametrize('source', ['stok_produk.html', 'stok_produk_jasa.html',
                                   'stok_karung.html', 'stok_karung_jasa.html'])
async def test_kontrol_stok_pada_pembungkus_kepemilikan(source):
 from starlette.requests import Request
 from app.web.stok_navigasi import siapkan, HALAMAN
 request = Request(dict(type='http', method='GET', path='/stok',
                        query_string=b'', headers=[], state={'view': 'super'}))
 context = dict(template_kepemilikan_asal=source, daftar=[], karung=[])
 await siapkan(request, 'stok_kepemilikan.html', context)
 kind, owner = HALAMAN[source]
 assert context['STOK_NAV']['jenis'] == kind
 assert context['STOK_NAV']['pemilik'] == owner
 assert context['daftar'] == [] and context['karung'] == []
