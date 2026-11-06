"""Rilis berbeda dengan nomor sama tidak boleh memakai alamat cache sama."""
import hmu_tampilan as ui
import pytest
from app.web.tampilan import templates


def test_commit_berbeda_memiliki_cap_cache_berbeda():
    a = ui.cap_aset('commit-pertama')
    b = ui.cap_aset('commit-kedua')
    assert a != b
    assert a == ui.cap_aset('commit-pertama')
    assert a.startswith(ui.VERSI + '-')


def test_template_memakai_cap_unik_dan_versi_produk_tetap_tersedia():
    assert templates.env.globals['VERSI'] == ui.CAP_ASET
    assert templates.env.globals['VERSI_APLIKASI'] == ui.VERSI


@pytest.mark.asyncio
async def test_denyut_sse_mengingatkan_pembaruan_setelah_formulir_ditutup(monkeypatch):
    import asyncio
    from app.web import api
    async def baca():
        return {'n':'tetap','versi':ui.CAP_ASET}
    async def tanpa_tunggu(*args):
        pass
    monkeypatch.setattr(api, '_penanda', baca)
    monkeypatch.setattr(asyncio, 'sleep', tanpa_tunggu)
    g = api.aliran_penanda(jeda=15)
    try:
        pertama = await anext(g)
        assert pertama.startswith('data: ')
        assert await anext(g) == ': hidup\n\n'
        assert await anext(g) == pertama
    finally:
        await g.aclose()
