"""Label neraca sosoh tetap terbaca ketika nilai berupa status panjang."""
from pathlib import Path

import pytest
from playwright.sync_api import sync_playwright


@pytest.mark.parametrize('width', [320, 390, 430, 1440])
@pytest.mark.parametrize('value', ['Belum dapat dipastikan · periksa sisa silo', '23.678 kg'])
def test_label_neraca_tidak_terjepit_status_panjang(width, value, tmp_path):
    root = Path(__file__).resolve().parents[1]
    css = '\n'.join((root / p).read_text() for p in (
        'hmu_tampilan/static/app.css',
        'app/web/static/sosoh-desain.css',
        'app/web/static/sosoh-ringkas.css',
    ))
    html = '''<body class="padiflow-ui terik"><main class="sr sr-redesign">
    <section class="sr-card sr-design-overview">
    <div class="sr-design-overview-title"><h2>Neraca sementara</h2><span class="sr-status">Belum final</span></div>
    <div class="sr-design-mass"><div><span>Bahan proses · sementara</span><strong>''' + value + '''</strong><small>Sisa seluruh siklus belum lengkap</small></div>
    <div><span>Seluruh hasil tercatat</span><strong>Belum tersedia</strong><small>Total hasil produksi proses ini</small></div>
    <div><span>Selisih sementara</span><strong>Belum tersedia</strong><small>Belum berarti susut final</small></div></div>
    </section></main></body>'''
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        page = browser.new_page(viewport={'width': width, 'height': 900})
        page.set_content('<meta name="viewport" content="width=device-width,initial-scale=1"><style>' + css + '</style>' + html)
        cell = page.locator('.sr-design-mass>div').first
        label = cell.locator(':scope>span')
        number = cell.locator(':scope>strong')
        boxes = [el.bounding_box() for el in (cell, label, number)]
        line = label.evaluate('e => parseFloat(getComputedStyle(e).lineHeight)')
        # Neraca ponsel kini tiga kolom; label harus mengisi sel dan terbaca.
        assert boxes[0]['width'] >= 70
        assert boxes[1]['width'] >= boxes[0]['width'] * .8
        assert boxes[1]['height'] <= line * 2 + 1
        if width <= 650:
            assert boxes[2]['y'] >= boxes[1]['y'] + boxes[1]['height']
            assert boxes[1]['width'] >= boxes[0]['width'] * .8
        assert page.evaluate('document.documentElement.scrollWidth <= innerWidth')
        assert number.inner_text() == value
        page.screenshot(path=str(tmp_path / f'neraca-{width}.png'), full_page=True)
        browser.close()
