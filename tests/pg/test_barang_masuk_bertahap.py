"""Daftar Barang Masuk memakai shell; data/izin tetap pembaca native."""
import json
import re

import httpx
import pytest
from bs4 import BeautifulSoup
from fastapi import HTTPException
from sqlalchemy.exc import SQLAlchemyError
from starlette.requests import Request

from hmu_identitas import peran as P
from tests.pg.test_konsolidasi_pekerjaan import lengkap, stok_lengkap, sosoh_jasa
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.test_halaman_bertahap import _sidik
from tests.pg.test_barang_masuk_pencarian import seed

pytestmark = pytest.mark.asyncio
PEMBACA = [(P.OPERATOR, 'g1'), (P.OPERATOR, 'g2'), (P.ADMIN, None)]


def root(html):
    node = BeautifulSoup(html, 'html.parser').select_one('[data-bm-page]')
    assert node is not None
    return node


@pytest.mark.parametrize('role,warehouse', PEMBACA)
@pytest.mark.parametrize('status,columns', [('belum', 6), ('diterima', 7)])
async def test_shell_sebelum_pembaca_dan_data_sama_native(
        pg, lengkap, monkeypatch, role, warehouse, status, columns):
    from app.services import berjalan, barang_masuk_daftar
    async with await _klien(pg, role=role, gudang_id=lengkap['gudang'].get(warehouse)) as c:
        before = await _sidik(pg)
        path = '/barang-masuk?status=' + status
        async def dilarang(*args, **kwargs):
            pytest.fail('Shell menunggu pembaca koleksi Barang Masuk')
        with monkeypatch.context() as m:
            m.setattr(berjalan, 'untuk', dilarang)
            m.setattr(barang_masuk_daftar, 'daftar', dilarang)
            shell = await c.get(path, headers={'X-Kerangka-Halaman': '1'})
        assert shell.status_code == 200
        initial = root(shell.text)
        assert initial.has_attr('data-bm-shell')
        assert re.fullmatch('[0-9a-f]{64}', initial['data-bm-stamp'])
        assert len(initial.select('[data-bm-results] th[scope=col]')) == columns
        assert len(initial.select('[data-bm-results] tbody tr')) == 1
        assert 'Memuat daftar penerimaan' in initial.get_text()
        assert 'Jumlah hasil belum tersedia' in initial.get_text() and '0 hasil' not in initial.get_text()
        assert initial.select_one('.bm-form-filter [name=pemasok]').has_attr('disabled')
        prints = BeautifulSoup(shell.text, 'html.parser').select('button[data-lk-cetak],button[data-bm-cetak]')
        assert prints and all(p.has_attr('disabled') for p in prints)
        native = await c.get(path, headers={'X-Pindah': '1'})
        raw = await c.get(path)
        legacy = await c.get(path, headers={'X-Barang-Masuk-Cari': '1', 'X-Kerangka-Halaman': '1'})
        data = await c.get('/api/halaman-bertahap/barang-masuk?status=' + status)
        assert native.status_code == raw.status_code == legacy.status_code == data.status_code == 200
        payload = data.json()
        assert payload['stamp'] == initial['data-bm-stamp']
        assert not root(native.text).has_attr('data-bm-shell')
        assert str(root(payload['html'])) == str(root(native.text)) == str(root(raw.text)) == str(root(legacy.text))
        assert await _sidik(pg) == before


async def test_shell_menjaga_pilihan_belum_diketahui_tanpa_identitas_buatan(pg, lengkap, monkeypatch):
    from app.services import berjalan, barang_masuk_daftar
    async def dilarang(*args, **kwargs):
        pytest.fail('Shell membaca koleksi atau identitas pilihan remote')
    async with await _klien(pg, role=P.ADMIN) as c:
        with monkeypatch.context() as m:
            m.setattr(berjalan, 'untuk', dilarang)
            m.setattr(barang_masuk_daftar, 'daftar', dilarang)
            r = await c.get('/barang-masuk?status=diterima&pemasok=Nama%20diterapkan&pelanggan_id=99999&cari=kode', headers={'X-Kerangka-Halaman': '1'})
        node = root(r.text)
        assert r.status_code == 200
        assert node.select_one('[data-bm-search] input[name=pelanggan_id]')['value'] == '99999'
        assert node.select_one('[data-bm-search] input[name=pemasok]')['value'] == 'Nama diterapkan'
        assert node.select_one('[data-bm-search] select[name=pemasok]').has_attr('disabled')
        assert 'Pelanggan tidak ditemukan' not in node.get_text()


async def test_data_mempertahankan_25_sort_filter_dan_detail_native(pg, lengkap):
    await seed(pg, 60)
    async with await _klien(pg, role=P.ADMIN) as c:
        before = await _sidik(pg)
        query = 'status=diterima&cari=TB-CARI&gudang=g1&jenis=gabah_kering&halaman=2'
        native = await c.get('/barang-masuk?' + query, headers={'X-Barang-Masuk-Cari': '1'})
        data = await c.get('/api/halaman-bertahap/barang-masuk?' + query)
        assert native.status_code == data.status_code == 200
        expected, actual = root(native.text), root(data.json()['html'])
        assert len(actual.select('.masuk-baris')) == 25
        assert [a['href'] for a in actual.select('.masuk-baris')] == [a['href'] for a in expected.select('.masuk-baris')]
        assert '60 hasil' in actual.get_text() and 'Halaman 2 dari 3' in actual.get_text()
        assert str(actual) == str(expected)
        empty = await c.get('/api/halaman-bertahap/barang-masuk?status=diterima&cari=TidakAdaKodeIni')
        none = root(empty.json()['html'])
        assert 'Tidak ada penerimaan yang cocok' in none.get_text()
        assert len(none.select('[data-bm-results] th')) == 7 and len(none.select('[data-bm-results] tbody tr')) == 1
        assert await _sidik(pg) == before


async def test_gagal_SQL_tetap_503_dengan_kolom_dan_bukan_nol(pg, lengkap, monkeypatch):
    from app.services import barang_masuk_daftar
    async def gagal(*args, **kwargs):
        raise SQLAlchemyError('fixture read unavailable')
    async with await _klien(pg, role=P.ADMIN) as c:
        before = await _sidik(pg)
        monkeypatch.setattr(barang_masuk_daftar, 'daftar', gagal)
        r = await c.get('/api/halaman-bertahap/barang-masuk?status=diterima&cari=kode')
        assert r.status_code == 503
        node = root(r.json()['html'])
        assert 'gagal dimuat' in node.get_text() and '0 hasil' not in node.get_text()
        assert len(node.select('[data-bm-results] th')) == 7
        assert len(node.select('[data-bm-results] tbody tr')) == 1
        assert node.select_one('[data-bm-retry]')
        assert await _sidik(pg) == before


async def test_api_baru_tidak_menambah_jalur_portal_atau_tamu(pg, monkeypatch):
    from app.main import app
    from app.web.halaman_bertahap import _isi
    from app.web.portal import scope
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://uji') as c:
        r = await c.get('/api/halaman-bertahap/barang-masuk')
    assert r.status_code == 303 and r.headers['location'].startswith('/masuk?next=')
    # An actual portal-context marker is rejected before the native portal
    # renderer; this unit boundary does not fabricate another company.
    monkeypatch.setattr(scope, 'is_customer_read', lambda request: True)
    request = Request(dict(type='http', path='/api/halaman-bertahap/barang-masuk', query_string=b'', headers=[]))
    with pytest.raises(HTTPException) as denied:
        await _isi(request, object(), 'barang-masuk')
    assert denied.value.status_code == 403
