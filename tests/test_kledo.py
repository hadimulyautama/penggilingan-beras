"""Tes Kledo (murni, tanpa API)."""
from app.kantor import kledo
from app.kantor.rbac import _domain_mode


def test_belum_konfig(monkeypatch):
    monkeypatch.delenv("KLEDO_API_KEY", raising=False)
    assert kledo.terkonfigurasi() is False


def test_tools_cocok_nama():
    assert {t["name"] for t in kledo.TOOLS} == set(kledo.NAMA_TOOL)


def test_format_rupiah():
    assert kledo._rp(5590401) == "Rp 5.590.401"


def test_items_bentuk_umum():
    assert kledo._items({"data": [{"a": 1}]}) == [{"a": 1}]
    assert kledo._items({"data": {"data": [{"b": 2}]}}) == [{"b": 2}]
    assert kledo._items([{"c": 3}]) == [{"c": 3}]
    assert kledo._items({}) == []


def test_kledo_domain_keuangan_read():
    assert _domain_mode("tagihan_kledo", {}) == ("keuangan", "read")
    assert _domain_mode("akun_kledo", {}) == ("keuangan", "read")
