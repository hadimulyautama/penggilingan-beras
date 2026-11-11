"""Sidebar retur memakai kerangka yang sama; seluruh GET tidak menulis."""
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from bs4 import BeautifulSoup
from fastapi import Depends, Request
from sqlalchemy import select

from app.models import User, Warehouse
from hmu_identitas import peran as P
from tests.pg.test_retur_supplier import asal, skema_retur_timbang, api_uji, user
from tests.pg.test_riwayat_retur_supplier import selesai, sidik_semua

pytestmark = pytest.mark.asyncio


def sidebar(html):
    nav = BeautifulSoup(html, 'html.parser').select_one('nav.laci__isi .laci__daftar')
    assert nav is not None
    return [(x.name, x.get("href"), x.get_text(" ", strip=True),
             "pintu--terkunci" in x.get("class", []))
            for x in nav.select("a.pintu, summary.pintu, a.pintu-sub__satu")]


@pytest.mark.parametrize('mode', ['super', 'admin', 'g1', 'g2'])
async def test_sidebar_sama_di_seluruh_halaman_retur_dan_hak_tetap(pg, asal, monkeypatch, mode):
    from app.web import retur_supplier as web, riwayat_retur_supplier as hist
    from app.web import retur_supplier_koreksi as koreksi, nav
    from app.web.security import butuh_akun
    from app.web.layar import view_untuk
    from app.web.tampilan import render_laci
    from app.services import retur_supplier_koreksi as svc

    for modul in (web, hist, koreksi, nav):
        monkeypatch.setattr(modul, 'SessionLocal', pg)
    async with pg() as db:
        r, _, _ = await selesai(db, asal)
        key = uuid4().hex
        check = await svc.periksa(db, user=user(asal), identitas=r.id, kunci=key,
            jenis='keterangan', keterangan='Keterangan uji', alasan='Periksa dokumen', konfirmasi=True)
        hasil = await svc.simpan(db, user=user(asal), identitas=r.id, kunci=key,
            dasar=check['dasar'], konfirmasi=True)
        await db.commit()
        role = {'super': P.SUPERADMIN, 'admin': P.ADMIN}.get(mode, P.OPERATOR)
        wh = await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi == ('g1' if mode == 'g1' else 'g2')))
        orang = await db.get(User, asal['uid'])
        orang.role, orang.default_warehouse_id = role, wh
        await db.commit()
        before = await sidik_semua(db)

    app = api_uji(pg, asal)
    app.include_router(hist.router)
    app.include_router(koreksi.router)

    async def akun(request: Request):
        # Simulasikan peran efektif setelah lihat-sebagai; hak asli super
        # tidak dibawa ke pengguna efektif operator.
        efektif = SimpleNamespace(id=asal['uid'], role=role, default_warehouse_id=wh)
        a = SimpleNamespace(user=efektif, nama='Uji Lokal', peran=role,
                            sesi_pendek=False, is_admin=P.admin_keatas(role))
        request.state.akun = a
        request.state.view = await view_untuk(efektif)
        request.state.lihat_sebagai = request.state.view if mode != 'super' else None
        return a

    app.dependency_overrides[butuh_akun] = akun

    @app.get('/uji-sidebar')
    async def acuan(request: Request, a=Depends(butuh_akun)):
        return await render_laci(request, 'riwayat_retur_supplier_gagal.html', kembali='/')

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://uji') as c:
        reference = await c.get('/uji-sidebar')
        assert reference.status_code == 200
        expected = sidebar(reference.text)
        # Acuan benar-benar berkelompok, bukan dua fallback yang sama-sama rusak.
        assert any(href == '/stok' for _, href, _, _ in expected)
        assert not any(href in ('/stok-produk', '/stok-produk-jasa', '/stok-pk-jasa',
                               '/stok-karung', '/stok-karung-jasa')
                       for _, href, _, _ in expected)
        urls = [('/riwayat-retur-supplier', 200)]
        status = 403 if mode == 'g1' else 200
        urls += [(f'/barang-masuk/{asal["tid"]}/retur-supplier', status),
                 (f'/retur-supplier/{r.id}', status),
                 (f'/retur-supplier/{r.id}/penyelesaian', status),
                 (f'/retur-supplier/{r.id}/tindakan/hasil/{hasil.peristiwa_id}', status)]
        urls += [(f'/riwayat-retur-supplier/{r.id}?tab={tab}', status)
                 for tab in ('ringkasan', 'timbang', 'stok', 'jejak')]
        urls += [(f'/retur-supplier/{r.id}/tindakan?jenis={jenis}',
                  200 if mode in ('super', 'admin') else 403)
                 for jenis in ('jumlah', 'keterangan', 'batal')]
        for url, code in urls:
            response = await c.get(url)
            assert response.status_code == code, (mode, url, response.status_code)
            if code == 200:
                assert sidebar(response.text) == expected, (mode, url)
                if url.startswith('/riwayat-retur-supplier'):
                    soup = BeautifulSoup(response.text, 'html.parser')
                    tabs = soup.select('nav[aria-label="Bagian Barang Masuk"] a')
                    assert [a.get_text(strip=True) for a in tabs] == ['Belum diterima','Diterima','Retur ke Supplier']
                    assert tabs[-1].get('aria-current') == 'page'
                    assert soup.select_one('a.pintu--kini')['href'] == '/barang-masuk'
                    assert not soup.select('nav[aria-label="Jenis halaman"]')
                assert response.headers['cache-control'] == 'private, no-store'
                if mode != 'super':
                    assert 'action="/lihat-sebagai/selesai"' in response.text

    async with pg() as db:
        assert await sidik_semua(db) == before
