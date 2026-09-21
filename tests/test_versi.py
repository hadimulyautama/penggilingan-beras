"""Versi kode yang sedang berjalan terlihat di Pengaturan.

21 September 2026: pemilik melaporkan galat yang sudah diperbaiki, dan butuh
satu putaran QA penuh hanya untuk tahu bahwa ponselnya masih menjalankan
kode lama. Sejak itu Pengaturan menyebut tiga angka — versi aset, commit,
revisi migrasi — dan memperingatkan admin bila basis datanya tertinggal.
"""
from __future__ import annotations

import importlib.util
import pathlib
import types

import pytest

from app.web import skema, versi
from app.web.tampilan import templates
from tests.bantu import kode_saja

AKAR = pathlib.Path(__file__).resolve().parents[1]


def _akun(peran: str):
    a = types.SimpleNamespace(nama="Pras", peran=peran, sesi_pendek=False,
                              harus_ganti_sandi=False)
    a.is_admin = peran in ("admin", "superadmin")
    return a


def _render(peran: str, versi_info: dict) -> str:
    return templates.get_template("pengaturan.html").render(
        request=None, akun=_akun(peran), layar="pengaturan", MENUNGGU=0,
        MODE_UJI=False, LIHAT_SEBAGAI=None, kembali=None, pesan_ok=None, err="",
        tuan=peran != "operator", target_bawaan=14.0, sebab_jeda={},
        mutu_aktif=False, ada_super=True, JAM_BATAS=48, versi=versi_info)


def _turun_satu(head: str) -> str:
    """`down_revision` dari berkas migrasi head — revisi tepat satu di bawahnya."""
    berkas = AKAR / "migrations" / "versions" / f"{head}.py"
    spec = importlib.util.spec_from_file_location(head, berkas)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.down_revision


class _SesiVersi:
    """Basis data tiruan yang hanya punya satu baris `alembic_version`."""

    def __init__(self, revisi: str | None):
        self.revisi = revisi

    def __call__(self):
        return self

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, *_a, **_k):
        revisi = self.revisi

        class _Hasil:
            def scalars(self_inner):
                return self_inner

            def first(self_inner):
                return revisi

        return _Hasil()


def test_baris_versi_muncul_di_pengaturan():
    """Untuk semua peran — operator pun boleh membacakan angkanya ke QA."""
    info = {"versi": "130", "komit": "abc1234", "revisi": "0054_x",
            "head": "0054_x", "keadaan": versi.SELARAS}
    for peran in ("operator", "admin", "superadmin"):
        html = _render(peran, info)
        assert "Versi 130 · abc1234 · migrasi 0054_x" in " ".join(html.split()), peran
        assert 'data-uji="baris-versi"' in html
        assert 'data-uji="skema-tertinggal"' not in html

    # Rutenya benar-benar mengirimnya — templat yang siap tanpa bahan diam.
    from app.web import pengaturan

    assert "_versi.info()" in kode_saja(pengaturan.halaman_pengaturan)


async def test_peringatan_migrasi_bila_basis_data_turun_satu_revisi(monkeypatch):
    """`alembic_version` satu revisi di bawah head → admin melihat peringatan
    mencolok, operator tidak."""
    head = skema._head_dari_berkas()
    turun = _turun_satu(head)
    assert turun and turun != head

    monkeypatch.setattr(skema, "SessionLocal", _SesiVersi(turun))
    monkeypatch.setenv("RAILWAY_GIT_COMMIT_SHA", "deadbeefcafe")
    versi.komit.cache_clear()
    try:
        info = await versi.info()
    finally:
        versi.komit.cache_clear()

    assert info["keadaan"] == versi.TERTINGGAL
    assert info["revisi"] == turun and info["head"] == head
    assert info["komit"] == "deadbee"                  # dipendekkan ke 7

    html = _render("admin", info)
    assert 'data-uji="skema-tertinggal"' in html
    assert "alembic upgrade head" in html
    assert turun in html and head in html
    assert "deadbee" in html

    assert 'data-uji="skema-tertinggal"' not in _render("operator", info)


async def test_selaras_tak_memperingatkan(monkeypatch):
    head = skema._head_dari_berkas()
    monkeypatch.setattr(skema, "SessionLocal", _SesiVersi(head))
    info = await versi.info()
    assert info["keadaan"] == versi.SELARAS
    html = _render("superadmin", info)
    assert "role=\"alert\"" not in html


def test_revisi_tak_dikenal_berarti_kode_lama():
    """Basis data di DEPAN kode — persis keadaan 21 September: yang berjalan
    bukan deploy terbaru. Obatnya deploy ulang, bukan migrasi."""
    head = skema._head_dari_berkas()
    assert versi.banding("9999_masa_depan", head) == versi.KODE_LAMA
    assert versi.banding(None, head) == versi.TAK_TERBACA
    assert versi.banding(head, None) == versi.TAK_TERBACA
    html = _render("admin", {"versi": "130", "komit": None, "revisi": "9999_masa_depan",
                             "head": head, "keadaan": versi.KODE_LAMA})
    assert 'data-uji="kode-lama"' in html and "commit ?" in html


def test_hanya_hash_commit_yang_dibaca_dari_lingkungan():
    """Layar bukan tempat nilai variabel apa pun selain hash commit. Satu-
    satunya akses ke lingkungan di modul ini adalah satu kunci itu."""
    import re

    sumber = (AKAR / "app/web/versi.py").read_text()
    akses = re.findall(r"os\.environ[^\n]*", sumber)
    assert akses == ['os.environ.get("RAILWAY_GIT_COMMIT_SHA"))'], akses
    assert "--kv" not in sumber and "railway variables" not in sumber


def test_commit_dari_berkas_bila_lingkungan_kosong(monkeypatch, tmp_path):
    monkeypatch.delenv("RAILWAY_GIT_COMMIT_SHA", raising=False)
    berkas = tmp_path / "KOMIT"
    berkas.write_text("0123456789abcdef\n")
    monkeypatch.setattr(versi, "BERKAS_KOMIT", berkas)
    versi.komit.cache_clear()
    try:
        assert versi.komit() == "0123456"
    finally:
        versi.komit.cache_clear()


def test_dockerfile_menulis_commit_saat_build():
    """Variabel build Railway hanya terlihat bila dideklarasikan ARG."""
    docker = (AKAR / "Dockerfile").read_text()
    assert "ARG RAILWAY_GIT_COMMIT_SHA" in docker
    assert "> /app/KOMIT" in docker
