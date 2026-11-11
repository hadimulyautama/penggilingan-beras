"""Label dan nilai panjang tetap terbaca pada kartu dan detail portal asli."""
from pathlib import Path
import os
import pytest
from playwright.sync_api import sync_playwright
from app.web.tampilan import templates
from app.web.portal.proses_ringkas import siapkan
from tests.profil_browser import mesin, konteks

ROOT = Path(__file__).resolve().parents[1]


def halaman(theme):
    css = ''.join((ROOT/'hmu_tampilan/static'/name).read_text() for name in
                  ('app.css', 'tabel-standar.css', 'komponen-portal.css', 'padiflow-brand.css'))
    css += (ROOT/'app/web/static/portal-pelanggan.css').read_text()
    rows = [siapkan(dict(jenis=jenis,judul=judul,kode=jenis+'-uji',lokasi='Gudang 1',
        status='Sedang berjalan',angka=('Jumlah bahan','31.365 kg'),
        fakta=[('Bahan masuk','31.365 kg · belum final, menunggu timbang'),
               ('Hasil sementara','15.000 kg')],maju=None,catatan=None,
        diperbarui=None,href='/pelanggan/proses-uji')) for jenis,judul in
        [('giling','Penggilingan gabah'),('sosoh','Penyosohan bahan campuran')]]
    cards = templates.env.get_template('portal/_progres.html').module.proses_berjalan(rows, str)
    # Detail memakai komponen angka yang sama; kasus bobot panjang harus ikut aman.
    detail = templates.env.get_template('portal/_inti_proses_ringkas.html').render(
        r={**rows[0], 'angka':('Bahan masuk',rows[0]['fakta_ringkas'][0][1])})
    return ('<!doctype html><html class="portal-document"><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1">'
        '<style>'+css+'</style><body class="padiflow-ui portal-customer '+theme+'">'
        '<div class="portal-workspace"><main class="isi portal-content">'
        '<div class="pelanggan-halaman">'+str(cards)+detail+'</div></main></div></body></html>')


@pytest.mark.parametrize('width', [320,390,430,768,1440])
@pytest.mark.parametrize('theme', ['', 'terik'])
def test_label_dan_bobot_sementara_tidak_terjepit(width, theme):
    with sync_playwright() as pw:
        browser = mesin(pw).launch()
        page = browser.new_page(**konteks(pw,width))
        # Semua dokumen, CSS, dan angka berasal dari fixture; tanpa jaringan/DB produksi.
        page.route('**/*',lambda route: route.abort())
        page.set_content(halaman(theme))
        labels = page.locator('.pelanggan-proses-angka dt')
        assert labels.count() >= 7
        assert labels.filter(has_text='Bahan masuk').first.bounding_box()['width'] >= 80
        for label in labels.all():
            rect = label.bounding_box()
            value = label.locator('xpath=following-sibling::dd')
            assert rect['width'] >= 80, label.inner_text()
            # Deteksi pemenggalan satu huruf per baris, bukan hanya overflow halaman.
            assert label.evaluate('e=>{const r=document.createRange();r.selectNodeContents(e);return r.getClientRects().length}') <= 2
            if width <= 600:
                assert value.bounding_box()['y'] >= rect['y']+rect['height']-1
        assert page.locator('dd').filter(has_text='31.365 kg · belum final, menunggu timbang').count() == 3
        assert not page.evaluate('document.documentElement.scrollWidth>innerWidth')
        assert page.locator('[data-post], [data-aksi], form').count() == 0
        if os.getenv('BUKTI_PORTAL_ANGKA'):
            folder=Path(os.environ['BUKTI_PORTAL_ANGKA']);folder.mkdir(parents=True,exist_ok=True)
            page.screenshot(path=str(folder/f'portal-{width}-{theme or "gelap"}.png'),full_page=True)
        browser.close()
