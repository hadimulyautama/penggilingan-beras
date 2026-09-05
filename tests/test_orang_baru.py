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


def test_tangga_perannya_tiga_tingkat():
    """Superadmin / Direksi / Operator (keputusan Direksi 3 September 2026).
    "staff" tidak lagi ditawarkan."""
    assert ua._ROLES == {"superadmin", "admin", "operator"}


def test_peran_lama_staff_tetap_terbaca():
    """Baris lama di `users` mungkin masih menyebut staff, dan orangnya tidak
    boleh kehilangan akses uang gara-gara namanya berganti."""
    from types import SimpleNamespace

    from app.bots.common import can_see_financials

    for peran in ("superadmin", "admin", "staff"):
        assert can_see_financials(SimpleNamespace(role=peran)), peran
    assert not can_see_financials(SimpleNamespace(role="operator"))


def test_superadmin_termasuk_direksi():
    """Tangga yang tidak menurun ke bawah bukan tangga: superadmin ada DI ATAS
    Direksi, jadi apa pun yang terbuka bagi Direksi terbuka baginya."""
    from types import SimpleNamespace

    from app.models.akun import ProduksiAkun

    a = ProduksiAkun(username="x", password_hash="y")
    a.user = SimpleNamespace(role="superadmin", nama="Pemilik")
    assert a.is_admin and a.is_super and a.is_staff


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
            None, actor=SimpleNamespace(role="admin"), nama="Budi", role="mandor",
            gudang=None, telegram_id=None, no_hp=None, lewat_sandi=True)


def test_superadmin_tak_boleh_tertinggal_di_gerbang_mana_pun():
    """Tangga yang tidak menurun ke bawah bukan tangga.

    `superadmin` ditambahkan di puncak saat peran dikonsolidasi, tetapi
    delapan gerbang masih menyebut ("staff","admin") satu per satu — jadi
    peran TERTINGGI bisa mengerjakan LEBIH SEDIKIT daripada admin di
    bawahnya. Pengiriman PK Gudang 1 → Gudang 2 salah satunya, dan itu
    langkah yang dipakai tiap hari.
    """
    import pathlib
    akar = pathlib.Path(__file__).resolve().parent.parent / "app"
    tersangka = []
    for berkas in akar.rglob("*.py"):
        isi = berkas.read_text()
        for pola in ('("staff", "admin")', '("admin", "staff")'):
            if pola in isi:
                tersangka.append(f"{berkas.relative_to(akar)}: {pola}")
    assert not tersangka, (
        "Peran disebut satu per satu — pakai PERAN_STAF_KEATAS: " + "; ".join(tersangka)
    )


def test_can_transfer_pk_mencakup_superadmin():
    from app.bots.common import PERAN_STAF_KEATAS, can_transfer_pk

    class _U:
        def __init__(self, role): self.role = role

    assert "superadmin" in PERAN_STAF_KEATAS
    for peran in ("superadmin", "admin", "staff"):
        assert can_transfer_pk(_U(peran)), peran
    assert not can_transfer_pk(_U("operator"))
    assert not can_transfer_pk(None)
