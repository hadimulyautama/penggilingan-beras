"""Penjaga pintu Meja: token service + akun yang diwakili.

Meja Administrasi (repo meja/) memakai akun yang sama dengan Pos Produksi,
lewat header — bukan cookie. Yang dijaga di sini: tanpa token yang benar,
header akun apa pun diabaikan; dengan token, versi yang dibawa ikut
diperiksa lewat aturan yang sama dengan cookie; dan pagar CSRF mengenali
permintaan Meja sebagai mesin, bukan peramban.
"""
from __future__ import annotations

import types

from app.config import settings
from app.web import csrf, security as sec


def _req(headers: dict) -> types.SimpleNamespace:
    return types.SimpleNamespace(headers={k.lower(): v for k, v in headers.items()},
                                 cookies={}, state=types.SimpleNamespace())


def test_tanpa_token_diset_pintu_mati(monkeypatch):
    monkeypatch.setattr(settings, "meja_api_token", "", raising=False)
    assert not csrf.dari_meja({"x-internal-token": ""})
    assert not csrf.dari_meja({"x-internal-token": "apa-pun"})
    assert sec.akun_dari_meja(_req({"X-Internal-Token": "apa-pun", "X-Meja-Akun": "7"})) is None


def test_token_salah_mengabaikan_header_akun(monkeypatch):
    monkeypatch.setattr(settings, "meja_api_token", "rahasia", raising=False)
    assert sec.akun_dari_meja(_req({"X-Internal-Token": "salah", "X-Meja-Akun": "7"})) is None
    assert not csrf.dari_meja({"x-internal-token": "salah"})


def test_token_benar_membaca_akun_dan_versi(monkeypatch):
    monkeypatch.setattr(settings, "meja_api_token", "rahasia", raising=False)
    assert sec.akun_dari_meja(_req({"X-Internal-Token": "rahasia", "X-Meja-Akun": "7",
                                    "X-Meja-Versi": "3"})) == (7, 3)
    # Tanpa versi → dianggap versi 1, sama seperti token cookie lama.
    assert sec.akun_dari_meja(_req({"X-Internal-Token": "rahasia", "X-Meja-Akun": "7"})) == (7, 1)
    # Nomor akun yang bukan angka bukan akun.
    assert sec.akun_dari_meja(_req({"X-Internal-Token": "rahasia", "X-Meja-Akun": "x"})) is None
    assert csrf.dari_meja({"x-internal-token": "rahasia"})


def test_versi_lama_dari_meja_ditolak_seperti_cookie(monkeypatch):
    """Keluar-semua / ganti sandi menaikkan versi akun; sesi Meja yang
    membawa versi lama harus putus persis seperti cookie lama."""
    monkeypatch.setattr(settings, "meja_api_token", "rahasia", raising=False)
    dibaca = sec.akun_dari_meja(_req({"X-Internal-Token": "rahasia", "X-Meja-Akun": "7",
                                      "X-Meja-Versi": "1"}))
    assert not sec.token_masih_berlaku(dibaca, versi_akun=2)
    assert sec.token_masih_berlaku(dibaca, versi_akun=1)


def test_csrf_tetap_memagari_jalur_miniapp_tanpa_token():
    assert csrf.perlu_periksa("POST", "/api/actions/verify-gabah")
    assert not csrf.perlu_periksa("POST", "/internal/meja/masuk")
