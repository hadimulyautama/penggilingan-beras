"""Tes helper biaya penyosohan (murni, tanpa DB)."""
from app.config import settings
from app.penggilingan.inventory.finished_goods import biaya_penyosohan_proses


def test_rate_dan_operator_flat():
    # default: (100+50+50)/kg PK × 10.000 + 300.000 flat = 2.300.000
    assert biaya_penyosohan_proses(10_000) == 200 * 10_000 + 300_000


def test_pk_nol_hanya_operator_flat():
    # tanpa PK disosoh, operator flat tetap dibebankan
    assert biaya_penyosohan_proses(0) == settings.biaya_operator_penyosohan


def test_none_aman():
    assert biaya_penyosohan_proses(None) == settings.biaya_operator_penyosohan
