"""Tes fungsi pemilahan email berbasis ATURAN (deterministik) — regresi #1."""
from types import SimpleNamespace

from app.kantor import aturan


def _r(jenis, cocok, verdikt):
    return SimpleNamespace(jenis=jenis, cocok=cocok, verdikt=verdikt)


def test_normal_verdikt():
    assert aturan._normal_verdikt("rutin") == "rutin"
    assert aturan._normal_verdikt("tidak penting") == "rutin"
    assert aturan._normal_verdikt("arsip saja") == "rutin"
    assert aturan._normal_verdikt("penting") == "penting"
    assert aturan._normal_verdikt("") == "penting"


def test_cocok_from():
    rules = [_r("from", "klikbca", "rutin")]
    assert aturan.cocok_dari_list(
        {"from": "klikbcabisnis@klikbca.com", "subject": "x"}, rules) == "rutin"
    assert aturan.cocok_dari_list(
        {"from": "budi@lain.com", "subject": "x"}, rules) is None


def test_cocok_domain():
    rules = [_r("domain", "bri.co.id", "rutin")]
    assert aturan.cocok_dari_list(
        {"from": "noreply@bri.co.id", "subject": "x"}, rules) == "rutin"
    assert aturan.cocok_dari_list(
        {"from": "noreply@bca.co.id", "subject": "x"}, rules) is None


def test_cocok_subjek():
    rules = [_r("subjek", "newsletter", "rutin")]
    assert aturan.cocok_dari_list(
        {"from": "a@b.com", "subject": "Weekly NEWSLETTER"}, rules) == "rutin"


def test_prioritas_urutan():
    # aturan pertama yang cocok menang
    rules = [_r("from", "notaris", "penting"), _r("domain", "gmail.com", "rutin")]
    assert aturan.cocok_dari_list(
        {"from": "notaris@gmail.com", "subject": "x"}, rules) == "penting"


def test_tanpa_aturan():
    assert aturan.cocok_dari_list({"from": "a@b.com", "subject": "x"}, []) is None
