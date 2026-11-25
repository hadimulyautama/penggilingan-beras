"""Owner acceptance of actual shipping READ navigation; run serial by integrator.

Uses only the existing gudang/_perintah/muat_semua/verifikasi recipes. Setup
is complete before fingerprints. Browser traffic thereafter must be GET only.
The existing peramban transport blocks service workers: this is deterministic
native/ASGI acceptance, not a cold/warm PWA or hosted-runtime proof.
"""
import asyncio
import json
import os
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import httpx
import pytest
from bs4 import BeautifulSoup

from tests.pg.test_barang_keluar import gudang, _perintah
from tests.pg.test_halaman_bertahap import _sidik

pytestmark = pytest.mark.asyncio
DOCUMENT = {"Sec-Fetch-Mode": "navigate", "Sec-Fetch-Dest": "document"}
NATIVE = {"X-Pindah": "1", "X-Kerangka-Halaman": "0"}
SHELL = "[data-pengiriman-detail-kerangka]"
TABS = {"ringkasan": "Ringkasan", "barang": "Barang",
        "tiket": "Tiket & bobot", "riwayat": "Retur & riwayat"}


def address(href):
    """Keep the actual native query, remove only its panel fragment."""
    u = urlsplit(href)
    from tests.pg.test_barang_masuk_bertahap_browser import BASE
    assert not u.netloc or (u.scheme, u.netloc) == (urlsplit(BASE).scheme, urlsplit(BASE).netloc)
    return u.path + ("?" + u.query if u.query else "")


def chrome(html):
    """Compare native semantic chrome, retaining labels, hierarchy and hrefs."""
    doc = BeautifulSoup(html, "html.parser")
    main = doc.select_one("#isi-halaman")
    assert main
    row = main.select_one(".desktop-chrome__crumbrow")
    header = main.select_one("header.bar")
    assert row and header
    items = []
    for li in row.select("nav.desktop-breadcrumb ol > li"):
        item = li.select_one("a[href], [aria-current=page]")
        assert item
        items.append(dict(tag=item.name, text=item.get_text(" ", strip=True),
                          href=item.get("href"), current=item.get("aria-current")))
    back = row.select_one("a.desktop-back")
    control = header.select_one(".bar__menu, .bar__balik")
    brand = header.select_one(".bar__merek")
    body_back = main.select_one("a.detail-kirim-kembali")
    assert back and control and brand and body_back
    return dict(items=items, back=dict(href=back.get("href"), label=back.get("aria-label")),
                control=dict(tag=control.name, id=control.get("id"),
                             classes=control.get("class"), href=control.get("href"),
                             label=control.get("aria-label"), title=control.get("title")),
                title=brand.get_text(" ", strip=True),
                content_back=body_back.get("href"))


async def assert_chrome(page, client, target, code):
    native = await client.get(target, headers=NATIVE)
    assert native.status_code == 200
    expected = chrome(native.text)
    actual = chrome(await page.content())
    assert actual == expected, dict(target=target, actual=actual, expected=expected)
    assert [item["text"] for item in actual["items"]] == ["Beranda", "Barang Keluar", code]
    assert actual["items"][-1] == dict(tag="span", text=code, href=None, current="page")
    assert actual["back"]["label"] == "Kembali ke Barang Keluar"
    return native


async def setup_shipments(pg, stock):
    """Existing native fixture recipes only; no return/correction/PACK setup."""
    from app.models import User
    from app.services import barang_keluar as bk
    values = {}
    for state, bags in [("perintah", 12), ("dimuat", 13), ("selesai", 4)]:
        record = await _perintah(pg, stock, karung=bags)
        oid, code = record.rec.id, record.rec.kode
        if state != "perintah":
            async with pg() as db:
                await bk.muat_semua(db, user=await db.get(User, stock["op"]), rec_id=oid)
        if state == "selesai":
            # Existing under-200kg quick-order rule; no invented weighing ticket.
            async with pg() as db:
                await bk.verifikasi(db, user=await db.get(User, stock["adm"]), rec_id=oid)
        values[state] = dict(id=oid, code=code, path=f"/barang-keluar/{oid}")
    return values


async def role_client(pg, stock, role):
    from sqlalchemy import select
    from app.models import User, Warehouse
    from hmu_identitas import peran as P
    from tests.pg.test_stok_pk_g1_polesan import _klien
    async with pg() as db:
        op = await db.get(User, stock["op"])
        if role == "operator-g2":
            warehouse = op.default_warehouse_id
        elif role == "operator-g1":
            warehouse = await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi == "g1"))
            assert warehouse, "Existing seed recipe lacks G1; do not invent another warehouse."
        else:
            warehouse = None
    client = await _klien(pg, role=P.ADMIN if role == "admin" else P.OPERATOR,
                          gudang_id=warehouse)
    # Native tab macros use request.url; pin the same owned browser origin
    # before obtaining goldens instead of rewriting native hrefs or HTML.
    from tests.pg.test_barang_masuk_bertahap_browser import BASE
    client.base_url = BASE
    return client


def native_read_gate(transport, path):
    entered, release = asyncio.Event(), asyncio.Event()
    transport["gate_headers"][path] = {"x-pindah": "1", "x-kerangka-halaman": "0"}
    transport["gates"][path] = entered, release
    return entered, release


async def two_frames(page):
    await page.evaluate("()=>new Promise(r=>requestAnimationFrame(()=>requestAnimationFrame(r)))")


def artifacts(role, width):
    folder = os.environ.get("DETAIL_OUT")
    if not folder:
        return None
    path = Path(folder) / ("shipping-detail-" + role + "-" + str(width))
    path.mkdir(parents=True, exist_ok=True)
    return path


@pytest.mark.parametrize("role", ["admin", "operator-g2"])
@pytest.mark.parametrize("width", [390, 1280])
async def test_actual_links_four_tabs_native_chrome_race_retry_and_leave(
        pg, gudang, monkeypatch, role, width):
    from playwright.async_api import expect
    from tests.pg.test_barang_masuk_bertahap_browser import peramban, BASE
    shipments = await setup_shipments(pg, gudang)
    async with await role_client(pg, gudang, role) as client:
        # One explicitly labelled read-transport fault, AFTER real native auth
        # and read. No synthetic success identity/DTO or changed server policy.
        faults = {"next": False, "count": 0, "path": None}
        request = client.request
        async def with_read_fault(method, url, **kwargs):
            response = await request(method, url, **kwargs)
            headers = {k.lower(): v for k, v in kwargs.get("headers", {}).items()}
            if faults["next"] and urlsplit(str(url)).path == faults["path"] and method.upper() == "GET" and headers.get("x-pindah") == "1" and headers.get("x-kerangka-halaman") == "0":
                assert response.status_code == 200
                faults["next"] = False
                faults["count"] += 1
                return httpx.Response(503, text="Owner fixture read unavailable", headers={"content-type": "text/html"}, request=response.request)
            return response
        monkeypatch.setattr(client, "request", with_read_fault)
        before = await _sidik(pg)
        releases = []
        results = []
        out = artifacts(role, width)
        async with peramban(client, width) as (page, transport):
            try:
                for state in ("perintah", "dimuat"):
                    item = shipments[state]
                    source = "/barang-keluar" if state == "perintah" else "/barang-keluar?" + urlencode(dict(q=item["code"], status=state))
                    await page.goto(BASE + source, wait_until="load")
                    await page.wait_for_function("()=>window.PadiKerangkaPengirimanDetailUI&&document.getElementById('padi-pengiriman-detail-catalog')")
                    link = page.locator('.keluar-daftar tr.keluar-baris td:first-child>a').filter(has=page.locator("small", has_text=item["code"]))
                    await expect(link).to_have_count(1)
                    target = address(await link.get_attribute("href"))
                    assert urlsplit(target).path == item["path"]
                    entered, release = native_read_gate(transport, item["path"])
                    releases.append(release)
                    await link.click()
                    await asyncio.wait_for(entered.wait(), 20)
                    shell = page.locator(SHELL)
                    await expect(shell).to_be_visible()
                    await expect(page.locator('.halaman-memuat')).to_have_count(0)
                    await expect(shell.locator(".detail-kirim-tabs>a")).to_have_text(list(TABS.values()))
                    await expect(shell.locator("table thead th")).to_have_text(["Barang", "Perintah", "Dimuat aktual", "Sisa perintah"])
                    assert not await shell.locator("form,input[name=_csrf]").count()
                    assert await shell.locator("button:not(:disabled):not([data-pd-retry])").count() == 0
                    await assert_chrome(page, client, target, item["code"])
                    if out:
                        await page.screenshot(path=str(out / (state + "-before-data.png")), full_page=True)
                    # First response remains held; a real keyboard tab target
                    # starts a second native GET. Old completion must not win.
                    entered2, release2 = native_read_gate(transport, item["path"])
                    faults['next'] = True
                    faults['path'] = item['path']
                    releases.append(release2)
                    tab = shell.locator('#tab-barang')
                    target2 = address(await tab.get_attribute("href"))
                    await tab.press("Enter")
                    await asyncio.wait_for(entered2.wait(), 20)
                    await expect(shell.locator('#tab-barang')).to_have_attribute("aria-selected", "true")
                    release.set()
                    await two_frames(page)
                    await expect(shell).to_be_visible()
                    await expect(shell.locator('#tab-barang')).to_have_attribute("aria-selected", "true")
                    await assert_chrome(page, client, target2, item["code"])
                    release2.set()
                    retry = shell.locator('[data-pd-retry]')
                    await expect(retry).to_be_visible()
                    await expect(shell.locator('[data-pd-status]')).to_contain_text('Detail belum dapat dibaca')
                    await retry.press('Enter')
                    await expect(shell).to_have_count(0, timeout=20000)
                    await expect(page.locator('[data-detail-tab] #tab-barang')).to_have_attribute("aria-selected", "true")
                    native = await assert_chrome(page, client, target2, item["code"])
                    expected_headers = [n.get_text(" ", strip=True) for n in BeautifulSoup(native.text, "html.parser").select('[data-detail-tab] table thead th')]
                    await expect(page.locator('[data-detail-tab] table thead th')).to_have_text(expected_headers)
                    if out:
                        await page.screenshot(path=str(out / (state + "-after-data.png")), full_page=True)
                    # Native detail_kirim_retur.js switches already authorized
                    # panels locally (preventDefault + replaceState), with no
                    # additional GET. Preserve that existing efficient contract.
                    for key in ("tiket", "riwayat", "ringkasan"):
                        count = len(transport['gets'])
                        tab = page.locator('[data-detail-tab] #tab-' + key)
                        target3 = address(await tab.get_attribute("href"))
                        await tab.press("Enter")
                        await expect(page.locator('[data-detail-tab] #tab-' + key)).to_have_attribute("aria-selected", "true")
                        await expect(page.locator('#panel-' + key)).to_be_visible()
                        await two_frames(page)
                        assert len(transport['gets']) == count
                        await expect(shell).to_have_count(0)
                        await assert_chrome(page, client, target3, item["code"])
                    results.append(dict(state=state, native_link=target, four_tabs=True, race=True, retry=True))

                # A legitimate native document deep link supplies its own Back
                # context. Tab navigation must preserve it, not invent one.
                item = shipments["perintah"]
                back_target = item["path"] + "?" + urlencode(dict(q=item["code"], status="perintah", kembali_kerja="/pekerjaan?tab=berjalan"))
                await page.goto(BASE + back_target, wait_until="load")
                await expect(page.locator('[data-detail-tab]')).to_be_visible(timeout=20000)
                await page.wait_for_function("()=>!!document.getElementById('padi-pengiriman-detail-catalog')")
                tab = page.locator('[data-detail-tab] #tab-barang')
                target = address(await tab.get_attribute("href"))
                await tab.press("Enter")
                await expect(page.locator('[data-detail-tab] #tab-barang')).to_have_attribute("aria-selected", "true")
                await assert_chrome(page, client, target, item["code"])
                await expect(page.locator('header.bar .bar__balik')).to_have_attribute("href", "/pekerjaan?tab=berjalan")
                # A direct complete document switches tabs locally. Exercise
                # pending-leave through an actual list link, where a native
                # GET really is still required, rather than fabricate a GET.
                await page.goto(BASE + '/barang-keluar', wait_until='load')
                await page.wait_for_function("()=>!!document.getElementById('padi-pengiriman-detail-catalog')")
                link = page.locator('.keluar-daftar tr.keluar-baris td:first-child>a').filter(has=page.locator('small', has_text=item['code']))
                entered, release = native_read_gate(transport, item["path"])
                releases.append(release)
                await link.click()
                await asyncio.wait_for(entered.wait(), 20)
                await expect(page.locator(SHELL)).to_be_visible()
                leave = page.locator(SHELL + ' a.detail-kirim-kembali')
                destination = address(await leave.get_attribute('href'))
                assert urlsplit(destination).path == '/barang-keluar'
                await leave.press('Enter')
                await expect(page).to_have_url(BASE + destination)
                release.set()
                await two_frames(page)
                await expect(page.locator(SHELL + ',[data-detail-tab]')).to_have_count(0)
                await expect(page).to_have_url(BASE + destination)

                # Final records deliberately keep their original journey DTO.
                final = shipments["selesai"]
                for headers in (DOCUMENT, NATIVE):
                    response = await client.get(final["path"], headers=headers)
                    assert response.status_code == 200
                    doc = BeautifulSoup(response.text, "html.parser")
                    assert doc.select_one('[data-riwayat-kiriman]')
                    assert not doc.select(SHELL + ',#padi-pengiriman-detail-catalog')
                await page.goto(BASE + final["path"], wait_until="load")
                await expect(page.locator('[data-riwayat-kiriman]')).to_be_visible()
                await expect(page.locator(SHELL)).to_have_count(0)
                assert faults["count"] == 2
                assert not transport["posts"] and not transport["errors"], dict(posts=transport["posts"], errors=transport["errors"])
                if out:
                    await page.screenshot(path=str(out / "final-native-fallback.png"), full_page=True)
                    (out / "observations.json").write_text(json.dumps(dict(role=role, width=width, engine=os.getenv("OWNER_BROWSER", os.getenv("UJI_BROWSER", "chromium")), cases=results, posts=transport["posts"], pageerrors=transport["errors"], get_paths=transport["gets"], final_native=True), ensure_ascii=False, indent=2))
            finally:
                for release in releases:
                    release.set()
        assert await _sidik(pg) == before, "A read/cancel/navigation changed fixture tables."


@pytest.mark.parametrize("width", [390, 1280])
async def test_g1_denied_by_same_native_guard_for_active_and_final(pg, gudang, width):
    from playwright.async_api import expect
    from tests.pg.test_barang_masuk_bertahap_browser import peramban, BASE
    shipments = await setup_shipments(pg, gudang)
    async with await role_client(pg, gudang, "operator-g1") as client:
        before = await _sidik(pg)
        async with peramban(client, width) as (page, transport):
            for item in shipments.values():
                for headers in (DOCUMENT, NATIVE):
                    response = await client.get(item["path"], headers=headers)
                    assert response.status_code == 403
                    doc = BeautifulSoup(response.text, "html.parser")
                    assert not doc.select(SHELL + ',#padi-pengiriman-detail-catalog,[data-detail-tab],[data-riwayat-kiriman]')
                response = await page.goto(BASE + item["path"], wait_until="load")
                assert response.status == 403
                await expect(page.locator(SHELL + ',#padi-pengiriman-detail-catalog,[data-detail-tab],[data-riwayat-kiriman]')).to_have_count(0)
                await expect(page.locator('#isi-halaman')).to_contain_text("Pengiriman tersedia untuk Admin dan Operator Gudang 2")
            assert not transport["posts"] and not transport["errors"], dict(posts=transport["posts"], errors=transport["errors"])
        assert await _sidik(pg) == before
