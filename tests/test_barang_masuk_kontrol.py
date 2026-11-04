"""Kontrol halaman asli tetap bekerja saat filter dipindah ke dialog."""
from pathlib import Path
from types import SimpleNamespace as NS
from urllib.parse import urlencode, urlsplit

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader
from playwright.sync_api import sync_playwright, expect
from starlette.requests import Request

ROOT = Path(__file__).resolve().parents[1] / 'hmu_tampilan'


@pytest.mark.parametrize('width', [390, 1440])
@pytest.mark.parametrize('status', ['belum', 'diterima'])
def test_filter_cari_tab_menu_dan_cetak(width, status):
    env = Environment(loader=ChoiceLoader([
        DictLoader({'base.html': '<div class="bingkai"><main class="isi">{% block isi %}{% endblock %}</main></div>'}),
        FileSystemLoader(ROOT / 'templates'),
    ]), autoescape=True)
    env.filters['jam'] = lambda *_: '04/11/2026 · 14:30'
    request = Request({'type': 'http', 'path': '/barang-masuk', 'query_string': b'',
                       'headers': [], 'scheme': 'http', 'server': ('uji.local', 80)})
    row = dict(id=1, nama='Pak Suroto', kode='TM/02614', nomor_polisi='AD 8241 BC',
               kepemilikan='pabrik', jenis_nama='Gabah', jenis_kode='gabah',
               berat_diterima=8420, keterangan_berat='', status_tiket='SELESAI',
               catatan=[dict(waktu='', status='diterima')])
    html = env.get_template('barang_masuk.html').render(
        request=request, VERSI='uji', TAMPILAN_INDUK=True, VIEW='super', V_MEJA=['super'],
        status=status, total_belum=0, total_diterima=1, jenis='', gudang='',
        jenis_barang=[('gabah', 'Gabah'), ('pk', 'PK')], pelanggan_saring='',
        nama_saring=['Pak Suroto'], menunggu=[], riwayat=[row], halaman_akhir=1,
        href=lambda **p: '/barang-masuk?' + urlencode(p), detail_tiket=lambda _: '/barang-masuk/1',
    )
    prefix = '<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
    css = ''.join((ROOT / 'static' / f).read_text() for f in ('app.css', 'komponen-portal.css'))
    html = prefix + '<style>' + css + '</style><body class="padiflow-ui terik">' + html + '</body>'
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={'width': width, 'height': 844})
        errors = []
        page.on('pageerror', lambda e: errors.append(str(e)))
        def route(r):
            path = urlsplit(r.request.url).path
            if path == '/barang-masuk':
                r.fulfill(body=html, content_type='text/html')
            elif path.startswith('/static/') and (ROOT / path.lstrip('/')).is_file():
                r.fulfill(path=ROOT / path.lstrip('/'))
            else:
                r.fulfill(body='', status=200)
        page.route('**/*', route)
        page.goto('http://uji.local/barang-masuk')
        search = page.get_by_role('searchbox')
        search.fill('Suroto')
        expect(page.locator('[data-hasil-cari]')).to_contain_text('cocok')
        assert 'cari=Suroto' in page.locator('.bm-tab a').first.get_attribute('href')
        if status == 'diterima':
            expect(page.locator('.masuk-baris')).to_be_visible()
            search.fill('Tidak ada')
            expect(page.locator('.masuk-baris')).to_be_hidden()
            search.fill('Suroto')
        filter_button = page.locator('.bm-tindakan-ponsel [data-bm-buka="bm-filter"]' if width == 390 else '.bm-filter-desktop')
        expect(page.locator('#bm-filter')).not_to_be_visible()
        filter_button.click()
        expect(page.locator('#bm-filter')).to_be_visible()
        page.locator('#bm-filter [name=jenis]').select_option('pk')
        assert page.locator('#bm-filter [name=cari]').input_value() == 'Suroto'
        page.locator('#bm-filter [name=pemasok]').select_option('Pak Suroto')
        page.keyboard.press('Escape')
        expect(page.locator('#bm-filter')).not_to_be_visible()
        expect(filter_button).to_be_focused()
        if width == 390:
            page.get_by_role('button', name='Panduan dan print', exact=True).click()
            page.get_by_role('button', name='Panduan penerimaan', exact=True).click()
        else:
            page.locator('.bm-tindakan-desktop [data-bm-buka]').click()
        expect(page.locator('#bm-panduan')).to_be_visible()
        page.get_by_role('button', name='Tutup panduan').click()
        page.evaluate('() => { window.jumlahCetak=0; window.print=()=>{window.jumlahCetak++}; }')
        if width == 390:
            page.get_by_role('button', name='Panduan dan print', exact=True).click()
            page.get_by_role('button', name='Print daftar halaman ini').click()
        else:
            page.locator('.bm-tindakan-desktop [data-bm-cetak]').click()
        assert page.evaluate('window.jumlahCetak') == 1
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        filter_button.click()
        page.get_by_role('button', name='Terapkan filter').click()
        page.wait_for_url('**/barang-masuk?**')
        assert 'jenis=pk' in page.url and 'cari=Suroto' in page.url
        assert 'pemasok=Pak+Suroto' in page.url
        out = ROOT.parent / 'output/barang-masuk-rilis'
        out.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out / f'{status}-{width}.png'), full_page=True)
        assert not errors
        browser.close()
