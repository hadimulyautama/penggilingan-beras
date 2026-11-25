"""Owner regression: native Giling structure, same-URL GET and pending keys.

The intercepted transport holds HTML/data independently. Ordinary HTTP and
PWA upgrade/rollback are verified separately; Sec-Fetch is not fabricated here.
"""
import asyncio
import json

import pytest
from bs4 import BeautifulSoup
from playwright.async_api import expect

from tests.pg.test_barang_masuk_bertahap_browser import peramban, BASE
from tests.pg.test_form_hasil_penggilingan import hasil, g1, fakta
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_halaman_bertahap import _sidik

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('role', ['admin', 'operator'])
@pytest.mark.parametrize('width', [390, 1280])
async def test_work_detail_structure_latest_tab_and_no_post(pg, hasil, role, width):
    _, process, _ = hasil
    path = '/proses-aktif/giling/' + process.kode_proses
    async with await _klien(pg, peran=role, gudang='Gudang 1') as client:
        before, stock = await _sidik(pg), await fakta(pg, process)
        async with peramban(client, width) as (page, transport):
            entered, release = asyncio.Event(), asyncio.Event()
            try:
                await page.goto(BASE + '/pekerjaan?tab=berjalan')
                await page.wait_for_function("()=>window.PadiKerangkaUI&&document.querySelector('[data-giling-native-catalog]')")
                link = page.locator('.proses-aktif-list__row[data-proses=giling] a.proses-aktif-list__detail').filter(has=page.locator('strong', has_text=process.kode_proses)).first
                address = await link.get_attribute('href')
                assert address.split('?')[0] == path
                transport['gates'][path] = entered, release
                await link.click()
                await asyncio.wait_for(entered.wait(), 20)
                shell = page.locator('[data-giling-native-html]')
                await expect(shell).to_be_visible()
                await expect(page.locator('.halaman-memuat')).to_have_count(0)
                await expect(shell.locator('h1')).to_have_text('Penggilingan aktif')
                await expect(shell.locator('[role=tab]')).to_have_count(5)
                await expect(shell.get_by_role('spinbutton', name='Total PK kumulatif')).to_be_disabled()
                await shell.locator('[data-gk-tab-pilih=qc]').focus()
                await page.keyboard.press('Enter')
                await expect(shell.locator('[data-gk-qc-grid] .gr-qc-value')).to_have_count(6)
                await expect(shell.locator('[data-gk-panel=qc]')).to_be_visible()
                # Focus elsewhere while the chosen VIEW tab must survive the read.
                await shell.locator('h1').click()
                assert transport['gets'].count(path) == 1  # data GET only; no destination HTML first
                if width<650:await shell.locator('[data-gk-menu]').click()
                guide=shell.get_by_role('button',name='ⓘ Panduan',exact=True).filter(visible=True)
                await guide.click()
                await expect(shell.locator('#gk-panduan')).to_be_visible()
                release.set()
                await expect(shell).to_have_attribute('data-padi-baca-native-state','waiting-interaction')
                await expect(shell.locator('#gk-panduan')).to_be_visible()
                await page.keyboard.press('Escape')
                native = page.locator('[data-giling-ringkas]')
                await expect(native.locator('[data-sr-tab=qc]')).to_have_attribute('aria-selected', 'true')
                await expect(native.locator('#qc .gr-qc-value')).to_have_count(6)
                await expect(native.locator('h1')).to_have_text('Penggilingan aktif')
                assert not transport['posts'] and not transport['errors']
                assert not await page.evaluate('document.documentElement.scrollWidth>innerWidth')
            finally:
                release.set()
        assert await _sidik(pg) == before and await fakta(pg, process) == stock


async def test_pending_key_survives_read_and_native_recovery_stays_visible(pg, hasil):
    _, process, _ = hasil
    path = '/proses-aktif/giling/' + process.kode_proses
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as client:
        response = await client.get(path, headers={'X-Pindah': '1'})
        assert response.status_code == 200
        document = BeautifulSoup(response.text, 'html.parser')
        actor = document.select_one('[data-giling-ringkas]')['data-actor']
        token = document.select_one('#formulir-sesi')['data-token']
        data = json.loads(document.select_one('#giling-awal').string)
        key = 'giling-ringkas:' + actor + ':' + process.kode_proses + ':' + token
        saved = dict(drafts={'pk': '5900'}, forms={}, action=None, uncertain=True,
                     last=None, baseline=data['dasar'])
        before, stock = await _sidik(pg), await fakta(pg, process)
        async with peramban(client, 390) as (page, transport):
            entered, release = asyncio.Event(), asyncio.Event()
            try:
                await page.goto(BASE + '/pekerjaan?tab=berjalan')
                await page.wait_for_function("()=>document.querySelector('[data-giling-native-catalog]')")
                await page.evaluate('([key,value])=>sessionStorage.setItem(key,JSON.stringify(value))', [key, saved])
                transport['gates'][path] = entered, release
                await page.locator('.proses-aktif-list__row[data-proses=giling] a.proses-aktif-list__detail').filter(has=page.locator('strong', has_text=process.kode_proses)).first.click()
                await asyncio.wait_for(entered.wait(), 20)
                await expect(page.locator('[data-gk-recovery-unknown]')).to_be_visible()
                assert await page.evaluate('key=>JSON.parse(sessionStorage.getItem(key))', key) == saved
                release.set()
                native = page.locator('[data-giling-ringkas]')
                await expect(native.locator('[data-pemulihan]')).to_be_visible()
                await expect(native.get_by_role('spinbutton', name='Total PK kumulatif')).to_have_value('5900')
                await expect(native.get_by_role('spinbutton', name='Total PK kumulatif')).to_be_disabled()
                assert await page.evaluate('key=>JSON.parse(sessionStorage.getItem(key))', key) == saved
                assert not transport['posts'] and not transport['errors']
            finally:
                release.set()
        assert await _sidik(pg) == before and await fakta(pg, process) == stock


async def test_document_authorization_and_native_data_path_remain_separate(pg, hasil, monkeypatch):
    from app.web import giling_ringkas
    _, process, _ = hasil
    path = '/proses-aktif/giling/' + process.kode_proses
    headers = {'Sec-Fetch-Mode': 'navigate', 'Sec-Fetch-Dest': 'document'}
    async def heavy(*args, **kwargs):
        pytest.fail('Structure must not wait for the heavy Giling reader')
    for role, warehouse, allowed in [('admin', None, True), ('operator', 'Gudang 1', True), ('operator', 'Gudang 2', False)]:
        async with await _klien(pg, peran=role, gudang=warehouse) as client:
            before = await _sidik(pg)
            with monkeypatch.context() as patch:
                patch.setattr(giling_ringkas, 'baca', heavy)
                response = await client.get(path, headers=headers)
            assert response.status_code == (200 if allowed else 403)
            if allowed:
                assert BeautifulSoup(response.text, 'html.parser').select_one('[data-giling-native-html]')
                native = await client.get(path, headers={**headers, 'X-Pindah': '1', 'X-Kerangka-Halaman': '1'})
                assert native.status_code == 200
                assert BeautifulSoup(native.text, 'html.parser').select_one('#giling-awal')
                assert not BeautifulSoup(native.text, 'html.parser').select_one('[data-giling-native-html]')
            assert await _sidik(pg) == before
