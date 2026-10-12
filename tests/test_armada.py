"""Kontrak kelas dan normalisasi Armada lintas aplikasi."""
from app.models import Armada, PkPurchaseBatch, PurchaseBatch
from hmu_core import Armada as ArmadaBersama, normalisasi_nomor_polisi


def test_armada_adalah_model_bersama_yang_dipakai_batch():
    assert Armada is ArmadaBersama
    assert PurchaseBatch.armada_id.property.columns[0].foreign_keys
    assert PkPurchaseBatch.armada_id.property.columns[0].foreign_keys
    assert normalisasi_nomor_polisi(" ad   1234 xy ") == "AD 1234 XY"
    assert normalisasi_nomor_polisi(None) is None
