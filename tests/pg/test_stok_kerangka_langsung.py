"""Prototype Stok hanya struktur; keputusan dan saldo tetap pembaca native."""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlsplit

import httpx
import pytest
from bs4 import BeautifulSoup
from playwright.async_api import expect

from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik, _isi
from tests.pg.test_barang_masuk_bertahap_browser import peramban, BASE

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('role,warehouse,active', [
    ('admin', None, True), ('operator', 'g1', True), ('operator', 'g2', True),
    ('operator', None, True), ('operator', 'g2', False),
])
async def test_prototype_native_izin_dan_tanpa_saldo(pg, lengkap, monkeypatch, role, warehouse, active):
    from sqlalchemy import select
    from app.models import Warehouse
    from app.web import stok_kerangka_langsung as stock
    from app.web.kerangka_langsung import LITERAL
    original = stock.susun
    async def checked(*args, **kw):
        from app.services import stok
        def denied(*a, **k):
            pytest.fail('Prototype tidak boleh menunggu saldo operasional')
        with monkeypatch.context() as m:
            for name in ('pk', 'produk', 'karung'):
                if hasattr(stok, name):
                    m.setattr(stok, name, denied)
            return await original(*args, **kw)
    monkeypatch.setattr(stock, 'susun', checked)
    if not active:
        async with pg() as db:
            row = await db.get(Warehouse, lengkap['gudang'][warehouse])
            row.aktif = False
            await db.commit()
    async with await _klien(pg, role=role, gudang_id=lengkap['gudang'].get(warehouse)) as c:
        before = await _sidik(pg)
        response = await c.get('/kabar')
        assert response.status_code == 200
        doc = BeautifulSoup(response.text, 'html.parser')
        base = json.loads(doc.select_one('#padi-kerangka-langsung').string)
        assert set(base['frames']) == set(LITERAL) | ({'/jasa'} if role == 'admin' else set())
        host = doc.select_one('#padi-stok-kerangka')
        assert host and not host.find_parent(class_='bingkai')
        descriptor = json.loads(host.string)
        kinds = {'bahan', 'produk', 'karung'} if role == 'admin' or warehouse and active else {'bahan'}
        assert set(descriptor['frames']) == kinds
        assert descriptor['konteks'] == base['konteks']
        assert descriptor['sesi'] == base['sesi']
        assert descriptor['cap'] == base['cap']
        for kind, refs in descriptor['frames'].items():
            html = ''.join(descriptor['potongan'][i] for i in refs)
            frame = BeautifulSoup(html, 'html.parser')
            root = frame.select_one('[data-kind="stok"]')
            assert root and len(root.select('thead th')) >= 6
            assert root['data-stamp'] == descriptor['konteks'] + '|/stok?tab=' + kind + '&pemilik=semua'
            assert frame.select_one('#formulir-sesi')['data-token'] == descriptor['sesi']
            assert not root.select('[data-post],[data-kirim],.antrian-item,.benda[data-cari]')
            assert 'LOT-STOK-' not in html and 'POL-STOK-' not in html
            assert root.select_one('select[name="pelanggan_id"]').has_attr('disabled')
        assert await _sidik(pg) == before


@pytest.mark.parametrize('role', ['operator', 'admin'])
@pytest.mark.parametrize('width', [390, 1280])
async def test_filter_pelanggan_gudang_dan_input_terserialisasi_saat_tab_ditahan(pg, lengkap, role, width):
    pid = str(lengkap['lain'])
    query = 'tab=bahan&pemilik=jasa&gudang=g2&pelanggan_id=' + pid
    async with await _klien(pg, role=role, gudang_id=lengkap['gudang']['g2'] if role=='operator' else None) as c:
        before = await _sidik(pg)
        async with peramban(c, width) as (page, transport):
            await page.goto(BASE + '/stok?' + query)
            await expect(page.locator('[data-stok-controls]')).to_be_visible()
            await expect(page.locator('[data-halaman-bertahap][data-kind="stok"]')).to_have_count(0)
            search = page.locator('[data-stok-controls] input[type="search"][name="cari"]')
            await search.fill('Baru & nilai')
            await search.press('Enter', no_wait_after=True)
            await page.wait_for_function("()=>new URL(location.href).searchParams.get('cari')==='Baru & nilai'")
            entered, release = asyncio.Event(), asyncio.Event()
            transport['gates']['/api/halaman-bertahap/stok'] = (entered, release)
            try:
                await page.locator('nav[aria-label="Jenis stok"] a').filter(has_text='Produk').click()
                await asyncio.wait_for(entered.wait(), 20)
                root=page.locator('[data-halaman-bertahap][data-kind="stok"]')
                await expect(root.locator('input[type="search"][name="cari"]')).to_have_value('Baru & nilai')
                await expect(root.locator('select[name="pemilik"]')).to_have_value('jasa')
                await expect(root.locator('select[name="gudang"]')).to_have_value('g2')
                await expect(root.locator('select[name="pelanggan_id"]')).to_have_value(pid)
                await expect(root.locator('select[name="pelanggan_id"]')).to_be_disabled()
                forms=await root.locator('form').evaluate_all('(forms)=>forms.map(f=>Object.fromEntries(new FormData(f)))')
                assert len(forms)==2
                for values in forms:
                    assert values==dict(tab='produk',pemilik='jasa',gudang='g2',pelanggan_id=pid,cari='Baru & nilai')
                await root.locator('[data-sk-buka="sk-filter"]').first.click()
                owner=root.locator('.sk-form-filter select[name="pemilik"]')
                customer=root.locator('.sk-form-filter select[name="pelanggan_id"]')
                await owner.select_option('pabrik')
                await expect(root.locator('[data-stok-pelanggan]')).to_be_hidden()
                await owner.select_option('jasa')
                await expect(root.locator('[data-stok-pelanggan]')).to_be_visible()
                await expect(customer).to_be_enabled()
                await customer.select_option(str(lengkap['pelanggan_id']))
                actual=await root.locator('.sk-form-filter').evaluate("f=>new FormData(f).getAll('pelanggan_id')")
                assert actual==[str(lengkap['pelanggan_id'])], 'PID lama tidak boleh dikirim bersama pilihan baru'
                # Restore the original draft before accepting its pending read.
                await customer.select_option(pid)
                await page.keyboard.press('Escape')
                await expect(root.locator('[data-sk-buka="sk-filter"]').first).to_be_focused()
                await expect(customer).to_be_enabled()
                assert not transport['posts'] and not transport['errors']
                release.set()
                await expect(page.locator('[data-stok-controls]')).to_be_visible()
                await expect(page.locator('[data-halaman-bertahap][data-kind="stok"]')).to_have_count(0)
            finally:
                release.set()
        assert await _sidik(pg)==before


@pytest.mark.parametrize('status', [503, 403])
async def test_descriptor_opsional_gagal_tidak_menyamarkan_izin(pg, lengkap, monkeypatch, status):
    from fastapi import HTTPException
    from app.web import stok_kerangka_langsung as stock
    async def unavailable(*a, **kw):
        raise HTTPException(status, 'Private fixture unavailable')
    monkeypatch.setattr(stock, 'susun', unavailable)
    async with await _klien(pg, role='admin') as c:
        before = await _sidik(pg)
        response = await c.get('/kabar')
        doc = BeautifulSoup(response.text, 'html.parser')
        assert doc.select_one('#padi-stok-kerangka') is None
        assert bool(doc.select_one('#padi-kerangka-langsung')) == (status == 503)
        assert await _sidik(pg) == before


@pytest.mark.parametrize('role,warehouse', [('operator', 'g1'), ('operator', 'g2'), ('admin', None)])
async def test_isi_stok_filter_sama_native_dan_stamp_tepat(pg, lengkap, role, warehouse):
    async with await _klien(pg, role=role, gudang_id=lengkap['gudang'].get(warehouse)) as c:
        before = await _sidik(pg)
        for tab in ('bahan', 'produk', 'karung'):
            for owner in ('semua', 'pabrik', 'jasa'):
                query = 'tab=' + tab + '&pemilik=' + owner + '&cari=Nama+baru+%26+uji'
                if owner == 'jasa':
                    query += '&pelanggan_id=' + str(lengkap['lain'])
                shell = await c.get('/stok?' + query, headers={'X-Kerangka-Halaman': '1'})
                data = await c.get('/api/halaman-bertahap/stok?' + query)
                native = await c.get('/stok?' + query, headers={'X-Pindah': '1'})
                assert shell.status_code == data.status_code == native.status_code == 200
                root = BeautifulSoup(shell.text, 'html.parser').select_one('[data-halaman-bertahap]')
                assert root['data-stamp'] == data.json()['stamp']
                assert _isi(data.json()['html']) == _isi(native.text)
                different = await c.get('/api/halaman-bertahap/stok?' + query + '&cari=Nama+lain')
                assert different.status_code == 200 and different.json()['stamp'] != data.json()['stamp']
        assert await _sidik(pg) == before


@pytest.mark.parametrize('role,warehouse', [('operator', 'g1'), ('operator', 'g2'), ('admin', None)])
@pytest.mark.parametrize('width', [390, 1280])
async def test_klik_stok_sebelum_html_dan_data_filter_baru_retry_keluar(pg, lengkap, role, warehouse, width):
    api = '/api/halaman-bertahap/stok'
    async with await _klien(pg, role=role, gudang_id=lengkap['gudang'].get(warehouse)) as c:
        before = await _sidik(pg)
        native = c.request
        fail = {'next': False}
        async def request(method, url, **kwargs):
            if method == 'GET' and urlsplit(str(url)).path == api and fail['next']:
                fail['next'] = False
                return httpx.Response(503, json={'detail': 'Fixture read unavailable'})
            response = await native(method, url, **kwargs)
            if method=='GET' and urlsplit(str(url)).path==api and fail.get('stamp'):
                fail['stamp']=False
                payload=response.json();payload['stamp']='fixture-wrong-context'
                return httpx.Response(200,json=payload)
            return response
        c.request = request
        async with peramban(c, width) as (page, transport):
            await page.goto(BASE + '/kabar')
            await expect(page.locator('#padi-stok-kerangka')).to_have_count(1)
            entered, release = asyncio.Event(), asyncio.Event()
            html_entered, html_release = asyncio.Event(), asyncio.Event()
            transport['gates']['/stok'] = (html_entered, html_release)
            transport['gates'][api] = (entered, release)
            try:
                link = page.locator('a[href="/stok"]:visible').first
                if not await link.count():
                    await page.locator('#buka-laci').click()
                    link = page.locator('#laci a[href="/stok"]').first
                await link.click()
                await asyncio.wait_for(entered.wait(), 20)
                root = page.locator('[data-halaman-bertahap][data-kind="stok"]')
                await expect(root).to_be_visible()
                await expect(root.locator('h1,.halaman-bertahap__kepala')).to_have_count(0)
                controls=['nav[aria-label="Jenis stok"]','[data-stok-controls] input[type="search"]','[data-stok-controls] .kontrol-pencarian>[data-sk-buka="sk-filter"]','[data-stok-controls] .kontrol-aksi>[data-sk-buka="sk-panduan"]','[data-stok-controls] .kontrol-aksi>[data-sk-cetak]']
                before_controls={s:await page.locator(s).bounding_box() for s in controls}
                await expect(root.locator('thead th').first).to_contain_text('Lot')
                await expect(root.locator('input[type="search"][name="cari"]')).to_be_visible()
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                assert not html_entered.is_set(), 'Kerangka masih menunggu HTML tujuan'
                await root.locator('input[type="search"][name="cari"]').fill('Filter baru & uji')
                release.set()
                await expect(root.locator('[data-shell-status]')).to_contain_text('pilihan tetap dipertahankan')
                await expect(root.locator('input[type="search"][name="cari"]')).to_be_focused()
                # Filter baru tidak ada di katalog alamat awal. Tautan tab
                # harus membawa filter ini tanpa menunggu HTML tujuan.
                await root.locator('input[type="search"][name="cari"]').fill('')
                await root.locator('input[type="search"][name="cari"]').press('Tab')
                await expect(page.locator('[data-stok-controls]')).to_be_visible()
                await expect(page.locator('[data-halaman-bertahap][data-kind="stok"]')).to_have_count(0)
                for selector,box in before_controls.items():
                    current_box=await page.locator(selector).bounding_box()
                    assert box and current_box
                    assert all(abs(box[key]-current_box[key])<=2 for key in ('x','y','width','height')),(selector,box,current_box)
                assert await page.evaluate("()=>document.activeElement.matches('[data-stok-controls] .kontrol-pencarian__submit,[data-sk-buka=sk-filter],[data-daftar-kosong],[aria-label=\"Daftar Stok\"]')")
                search = page.locator('[data-stok-controls] input[type="search"][name="cari"]')
                await search.fill('Nama baru & uji')
                await search.press('Enter', no_wait_after=True)
                await page.wait_for_function("()=>new URL(location.href).searchParams.get('cari')==='Nama baru & uji'")
                entered2, release2 = asyncio.Event(), asyncio.Event()
                transport['gates'][api] = (entered2, release2)
                fail['next'] = True
                try:
                    await page.locator('nav[aria-label="Jenis stok"] a').filter(has_text='Produk').click()
                    await asyncio.wait_for(entered2.wait(), 20)
                    await expect(root.locator('thead th').first).to_have_text('Produk')
                    assert urlsplit(await root.get_attribute('data-url')).query
                    await expect(root.locator('input[type="search"][name="cari"]')).to_have_value('Nama baru & uji')
                    await expect(page.locator('.halaman-memuat')).to_have_count(0)
                    assert not html_entered.is_set()
                    if os.environ.get('DETAIL_OUT'):
                        await page.screenshot(path=str(Path(os.environ['DETAIL_OUT']) / (role + '-' + str(width) + '-before-data.png')))
                    release2.set()
                    await expect(root.locator('[data-shell-retry]')).to_be_visible()
                    fail['stamp']=True
                    await root.locator('[data-shell-retry]').focus()
                    await page.keyboard.press('Enter')
                    await expect(root.locator('[data-shell-status]')).to_contain_text('Konteks sesi atau gudang berubah')
                    await expect(root.locator('[data-shell-retry]')).to_be_visible()
                    await root.locator('[data-shell-retry]').click()
                    await expect(page.locator('[data-stok-controls]')).to_be_visible()
                    await expect(page.locator('[data-halaman-bertahap][data-kind="stok"]')).to_have_count(0)
                    await expect(page.locator('[data-shell-retry]')).to_have_count(0)
                    assert not transport['posts'] and not transport['errors'], transport
                finally:
                    release2.set()
                transport['gates'].pop('/stok',None)
                html_release.set()
                old_entered,old_release,old_done=asyncio.Event(),asyncio.Event(),asyncio.Event()
                transport['gates'][api]=(old_entered,old_release)
                transport['completed'][api]=old_done
                try:
                    await page.locator('nav[aria-label="Jenis stok"] a').filter(has_text='Karung').click()
                    await asyncio.wait_for(old_entered.wait(),20)
                    await expect(root.locator('thead th').first).to_have_text('No.')
                    await root.locator('input[type="search"][name="cari"]').fill('Belum diterapkan')
                    link=page.locator('a[href="/pekerjaan"]:visible').first
                    if not await link.count():
                        await page.locator('#buka-laci').click()
                        link=page.locator('#laci a[href="/pekerjaan"]').first
                    await link.click()
                    await expect(page).to_have_url(BASE+'/pekerjaan')
                    await expect(page.locator('[data-halaman-bertahap]')).to_have_count(0)
                    current=await page.locator('.bingkai').element_handle()
                    old_release.set();await asyncio.wait_for(old_done.wait(),20)
                    await page.evaluate('()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))')
                    assert await current.evaluate('node=>node.isConnected')
                    await page.go_back()
                    await expect(page.locator('[data-stok-controls]')).to_be_visible()
                    await expect(page.locator('[data-stok-controls] input[type="search"][name="cari"]')).to_have_value('Nama baru & uji')
                    await page.reload()
                    await expect(page.locator('[data-stok-controls]')).to_be_visible()
                    await expect(page.locator('[data-stok-controls] input[type="search"][name="cari"]')).to_have_value('Nama baru & uji')
                finally:
                    old_release.set()
                if os.environ.get('DETAIL_OUT'):
                    await page.screenshot(path=str(Path(os.environ['DETAIL_OUT']) / (role + '-' + str(width) + '-stock.png')))
            finally:
                release.set(); html_release.set()
        assert await _sidik(pg) == before
