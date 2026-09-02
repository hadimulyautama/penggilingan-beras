"""Uji aksi batalkan-input-terakhir (Fase B3).

Undo adalah satu-satunya aksi di aplikasi ini yang MENGHAPUS pekerjaan orang.
Karena itu yang dijaga bukan cuma "berhasil membatalkan", melainkan pagarnya:

  · operator tidak boleh menjangkau pekerjaan orang lain — dan larangan itu
    ditegakkan di POST, bukan dengan menyembunyikan pilihannya;
  · tindakan yang belum didukung tidak boleh dicoba lalu gagal separuh jalan;
  · yang tertulis di layar harus tindakan yang sama dengan yang dibatalkan.
"""
from __future__ import annotations

import inspect
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.services import undo as svc
from app.web import aksi_undo as au
from app.web import miniapp


def _orang(role: str):
    return SimpleNamespace(id=7, nama="Rusdi", role=role)


# ─────────────────────── Lingkup yang boleh dijangkau ───────────────────────

def test_operator_hanya_menjangkau_dirinya_sendiri():
    assert au._lingkup_untuk(_orang("operator")) == ("saya",)


def test_staff_dan_admin_menjangkau_lingkup_yang_lebih_luas():
    for role in ("staff", "admin"):
        lingkup = au._lingkup_untuk(_orang(role))
        assert "semua" in lingkup
        assert lingkup[0] == "saya", "membatalkan pekerjaan sendiri harus yang pertama"


def test_tiap_lingkup_punya_namanya_di_layar():
    """Lingkup tanpa label akan muncul sebagai kode mentah seperti
    'operator_gudang1' di tengah kalimat berbahasa Indonesia."""
    for lingkup in au.LINGKUP_LUAS:
        assert lingkup in au.LINGKUP_LABEL


# ─────────────────────── Pagar di POST ───────────────────────

async def _tolak(lingkup: str, role: str) -> HTTPException:
    with pytest.raises(HTTPException) as e:
        await au.act_undo(au.UndoReq(lingkup=lingkup), user=_orang(role))
    return e.value


@pytest.mark.asyncio
async def test_operator_ditolak_saat_meminta_lingkup_orang_lain():
    """Daftar pilihan memang sudah disaring — tetapi penyaringan itu
    kenyamanan, dan kenyamanan bukan pengamanan."""
    for lingkup in ("semua", "staff", "operator_gudang2"):
        e = await _tolak(lingkup, "operator")
        assert e.status_code == 403


@pytest.mark.asyncio
async def test_lingkup_karangan_ditolak():
    e = await _tolak("operator_gudang9", "admin")
    assert e.status_code == 403


@pytest.mark.asyncio
async def test_tindakan_yang_belum_didukung_ditolak_sebelum_menyentuh_apa_pun():
    """Bertanda `x:` — ditolak di gerbang, bukan dicoba lalu gagal di tengah."""
    e = await _tolak("x:saya", "admin")
    assert e.status_code == 400
    assert "belum bisa dibatalkan" in str(e.detail).lower()


# ─────────────────────── Pratinjau & pembatalan sejalan ───────────────────────

def test_pratinjau_dan_pembatalan_memakai_kueri_yang_sama():
    """Bila keduanya menyusun kueri sendiri-sendiri, suatu saat salah satunya
    diubah dan orang menekan tombol untuk membatalkan sesuatu yang lain dari
    yang tertulis di layar."""
    for fungsi in (svc.pratinjau_terakhir, svc.undo_last):
        assert "_log_terakhir" in inspect.getsource(fungsi)


def test_tiap_tabel_yang_bisa_dibatalkan_punya_label_manusia():
    """Tanpa label, pratinjau berbunyi 'pk_purchase_verifications' — dan orang
    yang membacanya tidak tahu apa yang akan hilang."""
    for tabel in svc._UNDOABLE:
        assert svc.label_tabel(tabel) != tabel, f"{tabel} belum punya label"


def test_kalimat_pratinjau_menyebut_apa_kapan_dan_siapa():
    from datetime import datetime
    p = svc.Pratinjau(tabel="purchase_batches", label="gabah masuk",
                      ringkas="PB-20260902-01", oleh="Rusdi",
                      waktu=datetime(2026, 9, 2, 14, 32), didukung=True)
    kalimat = au._kalimat(p)
    assert "gabah masuk" in kalimat
    assert "PB-20260902-01" in kalimat
    assert "02/09 14:32" in kalimat
    assert "Rusdi" in kalimat


# ─────────────────────── Bentuk spesifikasi ───────────────────────

def test_yang_tak_boleh_mencatat_apa_pun_tak_mendapat_tombol_batal():
    assert au.spesifikasi(boleh=False) == []


def test_aksi_undo_terdaftar_di_router_dan_dipetakan_ke_gudang():
    (a,) = au.spesifikasi(boleh=True)
    terdaftar = {r.path for r in au.router.routes}
    assert a["post"] in terdaftar
    assert a["fields"][0]["source"] in terdaftar
    assert a["id"] in miniapp._ACTION_WH


def test_setiap_tabel_yang_menulis_jejak_punya_label_manusia():
    """Pratinjau menampilkan tindakan terakhir APA PUN tabelnya — termasuk yang
    belum bisa dibatalkan, supaya orang tahu kenapa tombolnya tidak menolong.

    Karena itu label tidak cukup hanya untuk tabel yang didukung. Tanpa ini,
    layar pernah berbunyi "purchase_batch_verifications · total=8400000" —
    kalimat yang tidak menolong siapa pun yang membacanya.
    """
    import pathlib
    import re

    akar = pathlib.Path(__file__).resolve().parents[1] / "app"
    menulis = set()
    for berkas in akar.rglob("*.py"):
        menulis |= set(re.findall(r'table_name="([a-z_]+)"', berkas.read_text()))
    menulis.discard("undo")   # jejak undo sendiri tak pernah jadi sasaran undo

    tanpa = sorted(t for t in menulis if svc.label_tabel(t) == t)
    assert not tanpa, f"tabel tanpa label manusia: {tanpa}"
