"""Uji pendaftaran orang baru dari webapp (Fase B3, lubang keenam).

Sebelum ini, orang hanya bisa didaftarkan lewat bot — dan bot menuntut
Telegram ID atau nomor HP, karena ia tak punya cara lain mengenali penuturnya.
Webapp punya: kredensialnya sendiri. Yang diuji di sini adalah bahwa pelonggaran
itu tidak sekalian melonggarkan hal lain.
"""
from __future__ import annotations

import inspect

import pytest

from app.services import user_admin as ua
from app.web import pengguna as web


def test_syarat_kontak_hanya_gugur_untuk_yang_masuk_lewat_sandi():
    """Jalur bot HARUS tetap menuntut kontak. Kalau ikut longgar, orang bisa
    terdaftar lewat chat tanpa satu pun cara mengenalinya."""
    sumber = inspect.getsource(ua.register_user)
    assert "not telegram_id and not phone and not lewat_sandi" in sumber


def test_yang_masuk_lewat_sandi_langsung_aktif():
    """"pending" berarti menunggu orangnya membuktikan diri lewat Telegram.
    Yang masuk lewat sandi tak punya penantian itu — dan bila ditandai pending,
    ia tidak muncul di daftar orang yang belum punya akun, sehingga akunnya
    tak pernah bisa dibuat sama sekali."""
    sumber = inspect.getsource(ua.register_user)
    assert 'status = "aktif" if (telegram_id or lewat_sandi) else "pending"' in sumber


def test_peran_di_layar_sama_dengan_peran_yang_dikenal_master():
    """Peran yang hanya ada di layar akan membuat orang terdaftar dengan
    tingkat yang tak dikenali pemeriksa hak akses mana pun."""
    assert {k for k, _, _ in web.PERAN} == ua._ROLES


def test_tiap_peran_dijelaskan_akibatnya_bukan_hanya_dinamai():
    """Direksi memilih peran untuk orang lain. Nama peran saja tidak cukup
    untuk tahu apa yang sedang diserahkan."""
    for kode, nama, arti in web.PERAN:
        assert nama and arti.endswith("."), kode
        assert len(arti) > 25, f"{kode}: keterangannya terlalu pendek untuk menolong"


@pytest.mark.asyncio
async def test_hanya_admin_yang_boleh_mendaftarkan_orang():
    from types import SimpleNamespace
    with pytest.raises(ua.UserAdminError):
        await ua.register_user(
            None, actor=SimpleNamespace(role="staff"), nama="Budi", role="operator",
            gudang=1, telegram_id=None, no_hp=None, lewat_sandi=True)


@pytest.mark.asyncio
async def test_peran_karangan_ditolak_walau_pendaftarnya_admin():
    from types import SimpleNamespace
    with pytest.raises(ua.UserAdminError):
        await ua.register_user(
            None, actor=SimpleNamespace(role="admin"), nama="Budi", role="superadmin",
            gudang=None, telegram_id=None, no_hp=None, lewat_sandi=True)
