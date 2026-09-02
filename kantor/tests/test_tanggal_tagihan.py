"""Tes parse tanggal Indonesia (radar jatuh tempo) & validasi tanggal tagihan."""
from datetime import date

from app.kantor import billing
from app.kantor.proaktif import deadline as dp


def test_parse_tgl_indonesia():
    assert dp._parse_tgl_id("11 Agu 2026") == date(2026, 8, 11)
    assert dp._parse_tgl_id("2 Sep 2026 (estimasi)") == date(2026, 9, 2)
    assert dp._parse_tgl_id("1 Januari 2027") == date(2027, 1, 1)
    assert dp._parse_tgl_id("15 Des 2026, auto-renew") == date(2026, 12, 15)


def test_parse_tgl_kosong_atau_bukan():
    assert dp._parse_tgl_id("-") is None
    assert dp._parse_tgl_id("Bulanan") is None
    assert dp._parse_tgl_id("(menyusul)") is None
    assert dp._parse_tgl_id("") is None
    assert dp._parse_tgl_id("32 Xyz 2026") is None  # bulan tak dikenal


def test_tgl_valid_tagihan():
    assert billing._tgl_valid("2026-08-13") == date(2026, 8, 13)
    assert billing._tgl_valid("2026-08-13T09:00:00") == date(2026, 8, 13)
    assert billing._tgl_valid("") is None
    assert billing._tgl_valid("bukan-tanggal") is None
    assert billing._tgl_valid("1999-01-01") is None  # sebelum 2020 → ditolak
