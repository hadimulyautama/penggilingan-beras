"""Tes peta jenis timbangan ↔ produksi (murni)."""
from app.penggilingan.peta_jenis import (
    TUMPUK,
    intake_dari_jenis, is_gabah, is_pk, DRYER, SILO_A, SILO_B, PETA_KELUAR,
)


def test_gabah_basah_boleh_dryer_atau_tumpukan():
    """Dulu dipaksa ke dryer. Direksi meluruskannya 2 September 2026: dryer
    hanya menerima satu lot pada satu waktu, dan gabah yang datang saat dryer
    terisi harus mendarat di suatu tempat. Memaksanya ke dryer tidak membuat
    gabahnya hilang — hanya membuat pencatatannya gagal."""
    j = intake_dari_jenis("GABAH_BASAH")
    assert j.model == "gabah" and j.kondisi == "basah"
    assert j.tujuan_wajib is None
    assert set(j.tujuan_pilihan) == {DRYER, TUMPUK}


def test_gabah_basah_tetap_tak_boleh_langsung_ke_silo():
    """Pagar yang TIDAK ikut longgar saat tumpukan ditambahkan: silo Gudang 1
    menampung gabah kering."""
    j = intake_dari_jenis("GABAH_BASAH")
    assert SILO_A not in j.tujuan_pilihan and SILO_B not in j.tujuan_pilihan


def test_gabah_kering_pilihan():
    j = intake_dari_jenis("GABAH_KERING")
    assert j.model == "gabah" and j.kondisi == "kering"
    assert j.tujuan_wajib is None
    assert set(j.tujuan_pilihan) == {SILO_A, SILO_B, DRYER, TUMPUK}


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
