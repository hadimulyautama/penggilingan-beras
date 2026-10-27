"""Tampilan induk tidak boleh menaikkan izin pengguna yang membacanya."""
from types import SimpleNamespace as NS
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException
from hmu_identitas import peran as P

from app.web import api
from app.web.akses import hak_view, PERAN_KOLOM


@pytest.fixture
def katalog(monkeypatch):
    from app.services import setelan

    class Sesi:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass

    monkeypatch.setattr(api, "SessionLocal", Sesi)
    monkeypatch.setattr(api, "_pilihan_tujuan_gabah", AsyncMock(return_value=[]))
    monkeypatch.setattr(setelan, "sebab_jeda", AsyncMock(return_value={
        "pengeringan": [], "giling": [], "penyosohan": []}))
    monkeypatch.setattr(setelan, "target_kadar_air", AsyncMock(return_value=14))
    monkeypatch.setattr(setelan, "fitur_mutu", AsyncMock(return_value=True))

    async def ambil(role, g1, g2):
        monkeypatch.setattr(api, "_is_g1_operator", AsyncMock(return_value=g1))
        monkeypatch.setattr(api, "_is_g2_operator", AsyncMock(return_value=g2))
        return await api.actions_menu(NS(role=role))
    return ambil


@pytest.mark.asyncio
async def test_katalog_sama_dan_matriks_mengikuti_izin_sebenarnya(katalog):
    daftar = [await katalog(*args) for args in (
        (P.SUPERADMIN, True, True), (P.ADMIN, True, True),
        (P.OPERATOR, True, False), (P.OPERATOR, False, True))]
    master = daftar[0]
    assert all(a["boleh"] for a in master)
    for kolom, menu in enumerate(daftar):
        assert [a["id"] for a in menu] == [a["id"] for a in master]
        for a, induk in zip(menu, master):
            assert a["fields"] == induk["fields"]
            assert a["boleh"] == a["izin_peran"][kolom]
            assert a["boleh"] == hak_view(PERAN_KOLOM[kolom][0])[a["akses"]]
    for menu, minta in zip(daftar, (True, False, False, True)):
        assert next(a["boleh"] for a in menu if a["id"] == "minta_pk_g1") == minta
        assert next(a["boleh"] for a in menu if a["id"] == "undo")


@pytest.mark.asyncio
async def test_katalog_tidak_memberi_hak_pada_peran_tidak_sah(katalog):
    assert not any(a["boleh"] for a in await katalog("tidak_dikenal", False, False))


@pytest.mark.asyncio
@pytest.mark.parametrize("role,g2", [(P.ADMIN, True), (P.OPERATOR, False)])
async def test_tombol_terkunci_tetap_ditolak_endpoint_minta(monkeypatch, role, g2):
    monkeypatch.setattr(api, "_is_g2_operator", AsyncMock(return_value=g2))
    with pytest.raises(HTTPException) as e:
        await api.act_minta_pk_g1(api.MintaPkReq(kode_proses="LOT-UJI", berat=1), NS(role=role))
    assert e.value.status_code == 403


@pytest.mark.asyncio
async def test_superadmin_membaca_semua_penerima_kabar():
    from app.services.kabar import _cakupan
    assert await _cakupan(NS(role=P.SUPERADMIN)) == []


@pytest.mark.asyncio
@pytest.mark.parametrize("role,g2,boleh", [
    (P.SUPERADMIN, True, True), (P.ADMIN, True, False),
    (P.OPERATOR, False, False), (P.OPERATOR, True, True),
])
async def test_pratinjau_minta_lot_mengikuti_izin_aksinya(monkeypatch, role, g2, boleh):
    monkeypatch.setattr(api, "_is_g2_operator", AsyncMock(return_value=g2))
    if boleh:
        hasil = await api.pratinjau_unit_transfer_pk('minta', user=NS(role=role))
        assert hasil['teks'] == 'Pilih lot PK.'
    else:
        with pytest.raises(HTTPException) as exc:
            await api.pratinjau_unit_transfer_pk('minta', user=NS(role=role))
        assert exc.value.status_code == 403


def test_izin_baca_pengiriman_sesuai_endpoint():
    from app.web.akses import matriks, PINTU_HAK
    assert matriks(PINTU_HAK['barang_keluar']) == [True, True, False, True]
