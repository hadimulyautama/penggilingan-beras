"""Regresi navigasi instan dan satu kiriman borang, seluruh respons lokal."""
import json
import mimetypes
import re
from pathlib import Path
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

akar=Path(__file__).resolve().parents[2]
html=akar/'output/pengaturan404/html'
utama=(html/'super-1-utama.html').read_text()
token=re.search(r'name="formulir-sesi" content="([^"]+)"',utama)[1]
nonce=re.search(r'id="formulir-sesi"[^>]*data-nonce="([^"]*)"',utama)[1]
posts=[]


def respons(route):
    path=urlparse(route.request.url).path
    if route.request.method=='POST':
        assert path=='/pengaturan/nama'
        posts.append(path)
        route.fulfill(status=303,headers={'Location':'/pengaturan/akun?pesan=nama-diganti'})
        return
    if path=='/api/sesi-formulir':
        route.fulfill(content_type='application/json',body=json.dumps({'aktif':True,'token':token}));return
    if path=='/api/kabar/jumlah':
        route.fulfill(content_type='application/json',body='{"belum":0,"merah":false,"terakhir":0}');return
    if path.startswith('/static/'):
        files=[akar/'hmu_tampilan/static'/path.removeprefix('/static/'),akar/'app/web/static'/path.removeprefix('/static/')]
    else:
        bagian=path.removeprefix('/pengaturan').strip('/') or 'utama'
        files=[html/f'super-1-{bagian}.html']
    for p in files:
        if p.is_file():
            route.fulfill(body=p.read_bytes(),content_type=mimetypes.guess_type(p)[0] or 'application/octet-stream');return
    route.fulfill(status=404,body='Tidak tersedia pada fixture.')


with sync_playwright() as p:
    browser=p.chromium.launch()
    context=browser.new_context(service_workers='block',viewport={'width':1440,'height':960})
    context.add_cookies([{'name':'produksi_csrf','value':nonce,'url':'http://bukti.local'}])
    context.route('**/*',respons)
    page=context.new_page()
    page.goto('http://bukti.local/pengaturan',wait_until='networkidle')
    for _ in range(6):
        page.locator('.pg-pintu[href="/pengaturan/akun"]').click()
        page.locator('input[name="nama"]').wait_for(state='visible')
        page.locator('.pg-kembali').click()
        page.locator('.pg-pintu[href="/pengaturan/akun"]').wait_for(state='visible')
    page.locator('.pg-pintu[href="/pengaturan/akun"]').click()
    page.locator('input[name="nama"]').fill('Nama fixture pemeriksaan')
    page.get_by_role('button',name='Simpan nama',exact=True).click()
    page.wait_for_load_state('networkidle')
    assert posts==['/pengaturan/nama'],posts
    assert page.locator('#sesi-berubah').count()==0
    browser.close()
print('6 siklus navigasi instan dan satu kiriman borang lulus; semua respons lokal.')
