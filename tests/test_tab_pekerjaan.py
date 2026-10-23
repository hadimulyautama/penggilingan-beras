"""Angka tab katalog memakai daftar serta saringan yang sama dengan Pekerjaan."""
from types import SimpleNamespace
from urllib.parse import urlencode

import pytest
from starlette.requests import Request

from app.web.layar_pekerjaan import daftar_tab_pekerjaan


@pytest.mark.asyncio
@pytest.mark.parametrize('query', [{}, {'gudang': 'g2', 'kepemilikan': 'jasa', 'jenis': 'giling'}])
async def test_katalog_meneruskan_jumlah_tab(monkeypatch, query):
    from app import main
    from app.web import layar_pekerjaan, katalog_navigasi
    user = object()
    kelompok = SimpleNamespace(
        tindakan=[SimpleNamespace(kepemilikan='pabrik', gudang='g1', jenis='giling'),
                  SimpleNamespace(kepemilikan='jasa', gudang='g2', jenis='giling')],
        berjalan=[SimpleNamespace(kepemilikan='jasa', gudang='g2', jenis='giling')],
        informasi=[SimpleNamespace(kepemilikan='pabrik', gudang='g1', jenis='packing')])
    monkeypatch.setattr(layar_pekerjaan, 'jenis_kerja', lambda x: x.jenis)

    async def akun(_):
        return SimpleNamespace(user=user)

    async def daftar(request, siapa):
        assert siapa is user
        for key, value in query.items():
            assert request.query_params[key] == value
        return SimpleNamespace(lencana=lambda: {}), kelompok, ''

    async def duplikat(*_):
        return '', '', '', ''

    monkeypatch.setattr(main, 'akun_opsional', akun)
    monkeypatch.setattr(layar_pekerjaan, 'siapkan_daftar_pekerjaan', daftar)
    monkeypatch.setattr(katalog_navigasi, 'tujuan_duplikat', duplikat)
    monkeypatch.setattr(main, 'render', lambda request, template, **context: context)
    request = Request({'type': 'http', 'scheme': 'http', 'server': ('uji.local', 80),
                       'path': '/pekerjaan/catat-lain', 'headers': [],
                       'query_string': urlencode({'kembali': '/pekerjaan?'+urlencode(query)}).encode()})
    context = await main.halaman_aksi_lain(request)
    assert context['kembali'] == ''
    *_, tindakan, jalan = daftar_tab_pekerjaan(kelompok, query.get('kepemilikan', ''),
                                               query.get('gudang', ''), query.get('jenis', ''))
    assert (context['total_tindakan'], context['total_jalan']) == (tindakan, jalan)
    assert (tindakan, jalan) == ((1, 1) if query else (2, 2))
