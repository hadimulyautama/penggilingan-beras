"""Tes peta jenis timbangan ↔ produksi (murni)."""
from app.penggilingan.peta_jenis import (
    intake_dari_jenis, is_gabah, is_pk, DRYER, SILO_A, SILO_B, PETA_KELUAR,
)


def test_gabah_basah_wajib_dryer():
    j = intake_dari_jenis("GABAH_BASAH")
    assert j.model == "gabah" and j.kondisi == "basah"
    assert j.tujuan_wajib == DRYER


def test_gabah_kering_pilihan():
    j = intake_dari_jenis("GABAH_KERING")
    assert j.model == "gabah" and j.kondisi == "kering"
    assert j.tujuan_wajib is None
    assert set(j.tujuan_pilihan) == {SILO_A, SILO_B, DRYER}


def test_pk():
    assert is_pk("BERAS_PK") and not is_gabah("BERAS_PK")
    assert intake_dari_jenis("BERAS_PK").model == "pk"


def test_belum_dipetakan():
    assert intake_dari_jenis("BERAS_MASUK") is None   # tunggu keputusan
    assert intake_dari_jenis("BROKEN_MASUK") is None
    assert intake_dari_jenis("MENIR") is None          # keluar, bukan intake


def test_case_insensitive():
    assert intake_dari_jenis("gabah_basah").kondisi == "basah"


def test_keluar():
    assert PETA_KELUAR["BERAS"] == "beras" and PETA_KELUAR["MENIR"] == "menir"
