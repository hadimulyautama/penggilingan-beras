"""Potret Pengaturan hasil uji HTTP; semua permintaan peramban dipenuhi secara lokal.

Jalankan dengan Python lingkungan tampilan (Playwright), setelah mengekspor
BUKTI_RETUR_DIR melalui test_layar_menunggu_koreksi_manual_dan_diterima.
Tidak membuka sesi/data operasional dan tidak mengirim formulir.
"""
import argparse
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse, unquote

from playwright.sync_api import sync_playwright

parser = argparse.ArgumentParser()
parser.add_argument('masukan', type=Path)
parser.add_argument('keluaran', type=Path)
args = parser.parse_args()
akar = Path(__file__).resolve().parents[2]
args.keluaran.mkdir(parents=True, exist_ok=True)


def berkas(route):
    path = unquote(urlparse(route.request.url).path)
    if route.request.method != 'GET':
        route.abort()
        return
    if path == '/api/sesi-formulir':
        route.fulfill(content_type='application/json', body=json.dumps({'aktif': True, 'token': token_sesi}))
        return
    if path == '/api/kabar/jumlah':
        route.fulfill(content_type='application/json', body=json.dumps({'belum': 0, 'merah': False, 'terakhir': 0}))
        return
    if path.startswith('/static/'):
        kandidat = [akar / 'hmu_tampilan/static' / path.removeprefix('/static/'),
                    akar / 'app/web/static' / path.removeprefix('/static/')]
    else:
        kandidat = [args.masukan / Path(path).name]
    for p in kandidat:
        if p.is_file() and (p.resolve().is_relative_to(akar.resolve())
                           or p.resolve().is_relative_to(args.masukan.resolve())):
            route.fulfill(body=p.read_bytes(), content_type=mimetypes.guess_type(p)[0] or 'application/octet-stream')
            return
    route.fulfill(status=404, body='Tidak tersedia pada potret uji.')


hasil = []
with sync_playwright() as p:
    browser = p.chromium.launch()
    for html in sorted(args.masukan.glob('*.html')):
        token_sesi = re.search(r'name="formulir-sesi" content="([^"]+)"', html.read_text()).group(1)
        nonce = re.search(r'id="formulir-sesi"[^>]*data-nonce="([^"]*)"', html.read_text()).group(1)
        for lebar in (390, 1440):
            for terang in ('-1-' in html.stem,):
                context = browser.new_context(viewport={'width': lebar, 'height': 960},
                    color_scheme='light' if terang else 'dark', service_workers='block')
                context.add_cookies([{'name': 'produksi_csrf', 'value': nonce, 'url': 'http://bukti.local'}])
                context.route('**/*', berkas)
                page = context.new_page()
                page.goto(f'http://bukti.local/{html.name}', wait_until='networkidle')
                assert page.locator('#sesi-berubah').count() == 0
                page.evaluate('(terang) => document.body.classList.toggle("terik", terang)', terang)
                nama = f'{html.stem}-{lebar}-{"terang" if terang else "gelap"}.png'
                page.screenshot(path=str(args.keluaran / nama), full_page=True)
                assert page.evaluate('document.documentElement.scrollWidth <= innerWidth'), nama
                assert page.get_by_role('heading', level=1).count() >= 1, nama
                if page.locator('.pg').count():
                    for e in page.locator('.pg button:visible, .pg .pg-pintu:visible, .pg summary:visible').all():
                        assert e.bounding_box()['height'] >= 43, nama
                lipat = page.locator('.pg details').first.locator('summary')
                if lipat.count():
                    lipat.focus()
                    lipat.press('Enter')
                    assert lipat.evaluate('(e) => e.parentElement.open'), nama
                kontrol = page.locator('.pg input:not([type=hidden]):enabled:visible').first
                if kontrol.count():
                    kontrol.focus()
                    assert kontrol.evaluate('(e) => document.activeElement === e'), nama
                page.evaluate('''() => {
                    for (const el of document.querySelectorAll('main,.isi,.bingkai')) {
                        if (el.scrollHeight > el.clientHeight && ['auto','scroll'].includes(getComputedStyle(el).overflowY))
                            el.scrollTop = el.scrollHeight;
                    }
                }''')
                page.screenshot(path=str(args.keluaran / ('bawah-' + nama)), full_page=True)
                hasil.append({'gambar': nama, 'lebar': lebar, 'tema': 'terang' if terang else 'gelap'})
                context.close()
    browser.close()
(args.keluaran / 'hasil.json').write_text(json.dumps(hasil, indent=2))
print(f'{len(hasil)} potret lulus pemeriksaan overflow, target sentuh, dan fokus input.')
