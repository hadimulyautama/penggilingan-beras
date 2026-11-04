from pathlib import Path
from jinja2 import Environment,FileSystemLoader
from playwright.sync_api import sync_playwright
import pytest
R=Path(__file__).resolve().parents[1]
@pytest.mark.parametrize('width',[390,1440])
@pytest.mark.parametrize('tema',['terik',''])
def test_kontrol_tidak_mengubah_gaya_isi_daftar(width,tema):
 env=Environment(loader=FileSystemLoader(R/'app/web/templates'));env.filters['jam']=lambda *_:'04/11/2026'
 row=dict(id=1,nama='Pihak Uji',kode='TM-UJI',nomor_polisi='AD 1234 BC',kepemilikan='pabrik',jenis_nama='Gabah',berat_diterima=None,keterangan_berat='',status_tiket='SELESAI',catatan=[dict(waktu='',status='diterima')])
 html=env.get_template('_daftar_penerimaan_pencarian.html').render(riwayat=[row],detail_tiket=lambda _:'/detail')
 base=''.join((R/'hmu_tampilan/static'/f).read_text() for f in ['app.css','komponen-portal.css','tabel-standar.css'])
 baru=(R/'hmu_tampilan/static/barang-masuk.css').read_text()
 with sync_playwright() as p:
  b=p.chromium.launch();page=b.new_page(viewport=dict(width=width,height=844));hasil=[]
  for css in [base,base+baru]:
   page.set_content('<meta charset="utf-8"><style>'+css+'</style><body class="padiflow-ui '+tema+'"><header class="bm-kepala"></header>'+html+'</body>')
   hasil.append(page.locator('.masuk-daftar,.masuk-daftar *').evaluate_all('els=>els.map(e=>{let c=getComputedStyle(e);return Object.fromEntries(["display","padding","margin","border","borderRadius","backgroundColor","color","fontSize","fontWeight","gridTemplateColumns","gap","width","height"].map(k=>[k,c[k]]))})'))
  assert hasil[0]==hasil[1]
  b.close()
