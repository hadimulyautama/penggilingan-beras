from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.web import api
from app.penggilingan.gudang1.services import timbang_link


@pytest.mark.parametrize('jenis,harapan', [
    ('GABAH_BASAH', {'dryer:1'}),
    ('GABAH_KERING', {'dryer:1', 'silo:2'}),
])
async def test_tujuan_mengikuti_tiket(monkeypatch, jenis, harapan):
    class Sesi:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(api, '_is_g1_operator', AsyncMock(return_value=True))
    monkeypatch.setattr(api, 'SessionLocal', Sesi)
    monkeypatch.setattr(timbang_link, 'ambil_tiket', AsyncMock(return_value={'jenis_kode': jenis}))
    monkeypatch.setattr(api, '_pilihan_tujuan_gabah', AsyncMock(return_value=[
        ['', 'Pilih'], ['dryer:1', 'Dryer 1'], ['silo:2', 'Silo 2'], ['tumpuk', 'Lantai']]))
    hasil = await api.tujuan_gabah('1', SimpleNamespace(id=1))
    assert {o['value'] for o in hasil} == harapan
