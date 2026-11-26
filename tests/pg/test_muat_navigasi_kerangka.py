"""Kerangka Muatan tidak membaca stok atau memberikan hak sebelum data native."""
import json
from types import SimpleNamespace
from bs4 import BeautifulSoup
from fastapi import Request
import pytest
from sqlalchemy import select
from app.models import User
from tests.pg.test_barang_keluar import gudang, _perintah, _klien, _stok
from tests.pg.test_ruang_perusahaan import siapkan, aktifkan, konfigurasi
from tests.pg.test_halaman_bertahap import _sidik
from hmu_identitas.ruang_data import pasang_pagar

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('role', ['operator', 'admin'])
async def test_kerangka_nol_data_dan_hasil_native_tetap(pg, gudang, monkeypatch, role):
    from app.web import muatan
    record = await _perintah(pg, gudang, karung=40)
    uid = gudang['op' if role == 'operator' else 'adm']
    client = await _klien(pg, uid, 'kerangka-muat-'+role, mode=role)
    space = await siapkan(pg)
    await aktifkan(pg, space)
    konfigurasi(monkeypatch, space)
    pasang_pagar(pg.kw['bind'], wajib=True)
    async with client:
        before = await _sidik(pg)
        stock = await _stok(pg, gudang)
        async def forbidden(*a, **kw):
            raise AssertionError('Penyusunan prototype tidak boleh membaca/mengunci saldo')
        old = muatan.papan
        monkeypatch.setattr(muatan, 'papan', forbidden)
        # Katalog sudah memiliki kerangka; tambahan Muatan tidak perlu membaca
        # isi perintah atau menambahkan dependency terhadap stock reader.
        response = await client.get('/pekerjaan/catat-lain', headers={'Sec-Fetch-Mode':'navigate','Sec-Fetch-Dest':'document'})
        assert response.status_code == 200
        host = BeautifulSoup(response.text, 'html.parser').select_one('#padi-muatan-kerangka')
        assert host
        data = json.loads(host.string)
        assert set(data['frames']) == {'/muatan', '/muatan?perintah=2147483647'}
        for key in data['frames']:
            doc = BeautifulSoup(''.join(data['potongan'][i] for i in data['frames'][key]), 'html.parser')
            root = doc.select_one('[data-muatan-shell]')
            assert root and not root.has_attr('data-editor-perintah')
            assert not root.has_attr('data-lembar-muatan') and root['data-boleh'] == '0'
            assert root['data-perintah'] == ''
            assert len(root.select('.mr-table th')) == 4
            assert all(n.has_attr('disabled') for n in root.select('[data-lembar-isi] input,[data-lembar-isi] button'))
            assert all(n.text == '—' for n in root.select('.mr-summary dd'))
            assert not doc.select('#lembar-awal') and not root.select('form[method=post]')
        monkeypatch.setattr(muatan, 'papan', old)
        native = await client.get('/muatan?perintah='+str(record.rec.id), headers={'X-Pindah':'1'})
        assert native.status_code == 200
        soup = BeautifulSoup(native.text, 'html.parser')
        root = soup.select_one('[data-lembar-muatan]')
        assert root and root['data-perintah'] == str(record.rec.id)
        async with pg() as db:
            user = await db.get(User, uid)
        assert root['data-boleh'] == ('1' if await muatan.boleh_catat(user) else '0')
        actual = json.loads(soup.select_one('#lembar-awal').string)
        assert actual['kiriman'][0]['total_perintah_kg'] == 1000
        missing = await client.get('/muatan?perintah=2147483647', headers={'X-Pindah':'1'})
        assert missing.status_code == 404
        assert await _stok(pg, gudang) == stock and await _sidik(pg) == before


async def test_portal_tidak_memperoleh_kerangka_internal(monkeypatch):
    from hmu_identitas import peran as P
    from app.web import muatan_kerangka
    request = Request({'type':'http','method':'GET','path':'/','headers':[],
                       'query_string':b'','state':{'portal_scope':object()}})
    assert await muatan_kerangka.susun(request, SimpleNamespace(user=SimpleNamespace(role=P.ADMIN)), navigasi={}) is None


@pytest.mark.parametrize('url,expected', [
    ('/muatan', True), ('/muatan?perintah=12', True),
    ('/barang-keluar/12/muatan?item=9', True),
    ('/muatan?perintah=12&semua=1', True),
    ('//example.invalid/muatan', False), ('/selesai-muat', False),
    ('/muatan?perintah=12&perintah=13', False),
    ('/barang-keluar/12/muatan?perintah=13', False),
    ('/muatan?buka=muat_semua', False), ('/muatan#lama', False),
])
async def test_opt_in_hanya_tujuan_baca_tidak_ambigu(url, expected):
    from app.web.muatan_kerangka import alamat_kerangka
    assert alamat_kerangka(url) is expected
