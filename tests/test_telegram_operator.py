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


def test_aksi_di_app_tidak_dikabarkan_ke_telegram():
    """Pemilik: "apa yang dilakukan di app, tidak perlu ada feedback ke
    telegram."

    Dulu tiap aksi lewat layar ikut dikirim ke chat sebagai "Aksi cepat".
    Operator sudah lama dilewati; yang tersisa admin ke atas — dan bagi
    mereka pesan itu cuma menggandakan apa yang baru saja mereka lihat
    sendiri di layar tempat mereka menekannya. Pemberitahuan yang cuma
    mengulang mengajari orang mengabaikan pemberitahuan.
    """
    import pathlib

    from app.web import aksi_umum

    assert not hasattr(aksi_umum, "kabar_chat")
    akar = pathlib.Path(__file__).resolve().parents[1] / "app/web"
    for berkas in ("miniapp.py", "aksi_inventory.py", "aksi_undo.py",
                   "aksi_umum.py"):
        teks = (akar / berkas).read_text()
        assert "kabar_chat" not in teks, berkas
        assert "notify_user" not in teks, f"{berkas}: aksi layar tak mengabari chat"
