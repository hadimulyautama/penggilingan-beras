"""Kontrak kelas dan normalisasi Armada lintas aplikasi."""
from app.models import Armada, PkPurchaseBatch, PurchaseBatch
from hmu_core import Armada as ArmadaBersama, normalisasi_nomor_polisi


def test_armada_adalah_model_bersama_yang_dipakai_batch():
    assert Armada is ArmadaBersama
    assert PurchaseBatch.armada_id.property.columns[0].foreign_keys
    assert PkPurchaseBatch.armada_id.property.columns[0].foreign_keys
    assert normalisasi_nomor_polisi(" ad   1234 xy ") == "AD 1234 XY"
    assert normalisasi_nomor_polisi(None) is None


def test_format_nomor_tanpa_spasi_dan_penolakan_nomor_tidak_lengkap():
    import pytest
    from hmu_core.armada import validasi_nomor_polisi
    assert validasi_nomor_polisi('h9313ic') == 'H 9313 IC'
    assert validasi_nomor_polisi('AD0001AB') == 'AD 0001 AB'
    for bad in ['3840','HURUF','-','A12B3','AD-1234-XY']:
        with pytest.raises(ValueError,match='Format nomor polisi'):
            validasi_nomor_polisi(bad)
