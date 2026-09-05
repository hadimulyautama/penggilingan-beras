"""Penjaga mode uji.

Fitur ini menghapus data di basis yang DIPAKAI BERSAMA dua aplikasi lain.
Versi pertamanya memakai `TRUNCATE ... CASCADE` dan menyapu seluruh tiket
timbang — 2 menjadi 0 — karena CASCADE merambat keluar lewat foreign key yang
MASUK, ke tabel yang produksi bahkan tak mengenalnya. Uji di sinilah yang
menangkapnya sebelum terkirim.
"""
from __future__ import annotations

import inspect

import pytest

from app.database import Base
from app.web import mode_uji


def test_tak_satu_pun_tabel_timbangan_dalam_jangkauan():
    """Sasaran penghapusan hanya tabel yang didefinisikan produksi sendiri."""
    assert not [t for t in Base.metadata.tables if t.startswith("timbangan")]
    assert not [t for t in mode_uji._tabel_dihapus() if t.startswith("timbangan")]


def test_tabel_milik_bersama_dipertahankan():
    """Tiga tabel yang tampak "milik produksi" padahal dipakai aplikasi lain.

    `suppliers` ditunjuk Timbangan dengan kolom WAJIB ISI; `kantor_config` &
    `kantor_llm_usage` memuat kill-switch dan BATAS BIAYA LLM yang dipakai
    bersama layanan Kantor. Tak satu pun terlihat asing dari namanya saja.
    """
    for nama in ("suppliers", "kantor_config", "kantor_llm_usage"):
        assert nama in mode_uji.DIPERTAHANKAN, nama
        assert nama not in mode_uji._tabel_dihapus(), nama


def test_akun_dan_alat_dipertahankan():
    """Menghapus akun berarti mengunci diri sendiri di luar aplikasi."""
    for nama in ("users", "produksi_akun", "warehouses", "silos", "dryers"):
        assert nama in mode_uji.DIPERTAHANKAN, nama


def _kode(fn) -> str:
    """Sumber fungsi TANPA komentar & docstring.

    Komentar di berkas ini justru menyebut CASCADE untuk menerangkan mengapa
    ia dibuang — memeriksa seluruh sumber berarti menghukum penjelasan yang
    baik. `ast.unparse` membuang komentar; docstring dibuang tersendiri.
    """
    import ast
    import textwrap

    pohon = ast.parse(textwrap.dedent(inspect.getsource(fn)))
    fungsi = pohon.body[0]
    if (fungsi.body and isinstance(fungsi.body[0], ast.Expr)
            and isinstance(fungsi.body[0].value, ast.Constant)
            and isinstance(fungsi.body[0].value.value, str)):
        fungsi.body = fungsi.body[1:]
    return ast.unparse(fungsi)


def test_tak_memakai_cascade():
    """CASCADE-lah yang dulu menyapu tiket. Ia tak boleh kembali."""
    kode = _kode(mode_uji.hapus)
    assert "CASCADE" not in kode.upper()
    assert "DELETE FROM" in kode


def test_urutan_hapus_dari_metadata_bukan_daftar_tangan():
    """Daftar yang ditulis tangan akan basi pada tabel berikutnya."""
    assert "Base.metadata.sorted_tables" in _kode(mode_uji.hapus)


@pytest.mark.asyncio
async def test_mati_total_saat_mode_uji_padam():
    """Mematikannya bukan menyembunyikan tombol — endpointnya ikut menolak."""
    from fastapi import HTTPException

    from app.config import settings

    asli = settings.mode_uji
    try:
        settings.mode_uji = False
        with pytest.raises(HTTPException) as e:
            mode_uji._wajib_mode_uji()
        assert e.value.status_code == 404
        settings.mode_uji = True
        mode_uji._wajib_mode_uji()      # tidak melempar
    finally:
        settings.mode_uji = asli
