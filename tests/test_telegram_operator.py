"""Telegram sudah tidak punya peran bagi operator (3 September 2026).

Alasannya bukan sekadar merapikan: perangkat gudang dipakai bergantian,
sedangkan akun Telegram menempel pada orang. Selama kedua jalur hidup
berdampingan, catatan bisa tertulis atas nama pemilik ponsel — bukan atas nama
yang sedang bekerja.

Yang dijaga di sini adalah bahwa jalurnya benar-benar tertutup, bukan sekadar
tidak dipakai lagi.
"""
from __future__ import annotations

import inspect
import pathlib

import pytest
from fastapi import HTTPException


def test_bot_operator_tidak_ada_lagi_berkasnya():
    akar = pathlib.Path(__file__).resolve().parents[1] / "app" / "penggilingan"
    for g in ("gudang1", "gudang2"):
        assert not (akar / g / "bot.py").exists(), f"bot {g} masih ada"


def test_bot_operator_tidak_terdaftar():
    from app.bots import registry

    assert set(registry._ROUTERS) == {"admin"}


def test_token_bot_operator_tidak_dipetakan_lagi():
    """Token yang terdaftar berarti bot yang menyala — dan bot operator yang
    menyala berarti jalur masuk yang sudah ditutup terbuka lagi, meski
    variabelnya kebetulan masih tertinggal di Railway."""
    from app.config import Settings

    s = Settings()
    object.__setattr__(s, "bot_gudang1_token", "x") if hasattr(s, "bot_gudang1_token") else None
    assert "gudang1" not in s.bot_tokens
    assert "gudang2" not in s.bot_tokens


@pytest.mark.asyncio
async def test_operator_ditolak_lewat_initData():
    """Yang membuka Mini App lama tidak tahu jalurnya sudah dipensiunkan —
    jadi penolakannya menunjuk jalan, bukan sekadar menutup."""
    from types import SimpleNamespace
    from unittest.mock import patch

    from app.web import deps

    orang = SimpleNamespace(id=1, nama="Rusdi", role="operator")

    async def _palsu(_auth=None):
        return orang

    req = SimpleNamespace(cookies={}, state=SimpleNamespace())
    with patch.object(deps, "require_miniapp_user", _palsu), \
         patch("app.web.security.akun_opsional", lambda _r: _kosong()):
        with pytest.raises(HTTPException) as e:
            await deps.pengguna_aksi(req, None)
    assert e.value.status_code == 403
    assert "peramban" in str(e.value.detail).lower()


async def _kosong():
    return None


def test_konfirmasi_chat_dilewati_untuk_operator():
    """Operator tak lagi punya chat yang menerimanya, dan konfirmasinya sudah
    tampil di layar tempat ia menekan tombol."""
    from app.web import aksi_umum

    sumber = inspect.getsource(aksi_umum.kabar_chat)
    assert 'role", None) == "operator"' in sumber
    assert sumber.index("return") < sumber.index("notify_user")
