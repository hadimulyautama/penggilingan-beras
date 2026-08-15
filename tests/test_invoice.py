"""Tes otak invoice (murni, tanpa LLM/jaringan)."""
from app.kantor import invoice

_SVC = [
    ["S1", "Railway", "Hosting"],
    ["S9", "Kledo", "Finance / Akuntansi"],
    ["S2", "GajiHub", "HR / Payroll"],
]

_EKS_KLEDO = {
    "jenis": "invoice", "langganan": True, "vendor": "PT Kledo Berhati Nyaman",
    "layanan": "Kledo Elite", "no_invoice": "INV/VIII/70584", "tanggal": "2026-08-14",
    "total": "Rp 4.659.333", "lunas": True, "siklus": "tahunan", "keyakinan": "tinggi",
}


def test_cocok_layanan():
    assert invoice.cocok_layanan("PT Kledo Berhati Nyaman", "Kledo Elite", _SVC)[0] == "Kledo"
    assert invoice.cocok_layanan("GajiHub Indonesia", "GajiHub", _SVC)[0] == "GajiHub"
    assert invoice.cocok_layanan("Vendor Asing", "Produk X", _SVC) is None


def test_susun_usulan_langganan():
    u = invoice.susun_usulan(_EKS_KLEDO, "invoice-kledo.pdf", _SVC)
    assert u["langganan"] and u["layanan_cocok"] == "Kledo"
    assert u["folder_id"] == invoice.LANGGANAN_FOLDER_ID
    assert u["nama_file"] == "Kledo - Invoice INV-VIII-70584 - 14 Agu 2026 - LUNAS.pdf"
    d = dict(u["it_updates"])
    assert d["biaya"] == "Rp 4.659.333/thn"
    assert d["siklus"] == "tahunan"
    assert d["renewal"] == "14 Agu 2027"  # tanggal + 1 tahun
    assert "INV/VIII/70584" in d["catatan_tambah"] and "LUNAS" in d["catatan_tambah"]


def test_susun_usulan_belum_lunas():
    e = dict(_EKS_KLEDO, lunas=False)
    u = invoice.susun_usulan(e, "x.pdf", _SVC)
    assert "BELUM LUNAS" in u["nama_file"]


def test_bukan_invoice():
    e = {"jenis": "lainnya", "vendor": "", "keyakinan": "rendah"}
    u = invoice.susun_usulan(e, "x.pdf", _SVC)
    assert not u["invoice"] and not u["langganan"]
    assert "Tak ada usulan" in invoice.ringkas_usulan(u)


def test_tak_cocok_layanan_tetap_arsip():
    e = dict(_EKS_KLEDO, vendor="Adobe", layanan="Photoshop")
    u = invoice.susun_usulan(e, "x.pdf", _SVC)
    assert u["langganan"] and u["layanan_cocok"] == ""  # tak ada di DB
    assert u["it_updates"] == []  # tak usul update IT
    assert "dilewati" in invoice.ringkas_usulan(u)
