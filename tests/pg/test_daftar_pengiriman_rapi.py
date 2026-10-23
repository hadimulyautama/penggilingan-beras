"""Penataan daftar tidak memberi tindakan baru atau mengubah stok."""
import json
import os
from pathlib import Path
from uuid import uuid4

import pytest

from app.web.draf_keluar import SimpanDraf, simpan
from tests.pg.test_barang_keluar import gudang, _klien, _perintah, _stok
from tests.pg.test_draf_keluar import _isi, _user

pytestmark = pytest.mark.asyncio


async def test_daftar_kosong_panduan_dan_filter_tetap_berizin(pg, gudang):
    stok = await _stok(pg, gudang)
    for uid, nama, boleh in [(gudang['adm'], 'rapi-admin', True), (gudang['op'], 'rapi-operator', False)]:
        async with await _klien(pg, uid, nama) as c:
            r = await c.get('/barang-keluar')
            assert r.status_code == 200
            assert 'data-daftar-draf' not in r.text
            assert 'data-bantuan-kirim' in r.text
            assert r.text.count('role="tabpanel"') == 3
            assert 'id="panduan-tahap-3"' in r.text
            assert ('href="/barang-keluar/baru"' in r.text) is boleh
            assert 'name="q"' in r.text and 'name="sejak"' in r.text
            assert 'Belum ada pengiriman berjalan' in r.text
            if os.environ.get('BUKTI_DAFTAR_KELUAR'):
                folder = Path(os.environ['BUKTI_DAFTAR_KELUAR']); folder.mkdir(parents=True, exist_ok=True)
                (folder / f'{nama}-kosong.html').write_text(r.text)
    assert await _stok(pg, gudang) == stok


async def test_draf_terisi_dan_filter_tidak_mengubah_transaksi(pg, gudang):
    stok = await _stok(pg, gudang)
    ident = uuid4()
    await simpan(ident, SimpanDraf(revisi=0, kiriman=uuid4(), isi=await _isi(pg, gudang)), await _user(pg, gudang))
    hasil = await _perintah(pg, gudang, karung=12)
    oid = hasil.rec.id
    async with await _klien(pg, gudang['adm'], 'rapi-daftar') as c:
        r = await c.get('/barang-keluar')
        assert r.status_code == 200
        assert 'data-daftar-draf' in r.text
        assert f'data-hapus-draf="{ident}"' in r.text
        assert f'href="/barang-keluar/draf/{ident}"' in r.text
        assert f'/barang-keluar/{oid}' in r.text
        kosong = await c.get('/barang-keluar?q=tidak-ada&status=perintah&sejak=2020-01-01')
        assert kosong.status_code == 200
        assert 'value="tidak-ada"' in kosong.text
        assert 'value="perintah" selected' in kosong.text
        assert 'value="2020-01-01"' in kosong.text
        assert 'Belum ada pengiriman berjalan' in kosong.text
        assert f'/barang-keluar/{oid}"' not in kosong.text
        if os.environ.get('BUKTI_DAFTAR_KELUAR'):
            folder = Path(os.environ['BUKTI_DAFTAR_KELUAR']); folder.mkdir(parents=True, exist_ok=True)
            (folder / 'admin-terisi.html').write_text(r.text)
            (folder / 'admin-filter.html').write_text(kosong.text)
            (Path('/tmp/daftar-keluar-session.json')).write_text(json.dumps({'cookies': {x.name: x.value for x in c.cookies.jar}, 'draf': str(ident), 'perintah': oid}))
    assert await _stok(pg, gudang) == stok
