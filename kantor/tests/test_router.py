"""Tes router domain (murni, 0 LLM)."""
from app.kantor import router


def test_pilih_domain_produksi():
    assert "produksi" in router.pilih_domain("simulasi hpp gabah kering")
    assert "produksi" in router.pilih_domain("berapa stok beras di silo")


def test_pilih_domain_email():
    assert "email" in router.pilih_domain("cek email finance masuk apa")


def test_pilih_domain_keuangan():
    assert "keuangan" in router.pilih_domain("berapa tagihan yang harus dibayar")
    assert "keuangan" in router.pilih_domain("lihat faktur piutang di kledo")


def test_pilih_domain_umum_fallback():
    assert router.pilih_domain("halo selamat pagi apa kabar") == {"umum"}


def test_bundel_produksi_ramping():
    tools = [{"name": n} for n in
             ["simulasi_hpp", "tanya_produksi", "baca_email", "cari_pengetahuan", "status_biaya"]]
    names = {t["name"] for t in router.bundel({"produksi"}, tools)}
    assert {"simulasi_hpp", "tanya_produksi"} <= names          # domain produksi
    assert {"cari_pengetahuan", "status_biaya"} <= names        # shared selalu ada
    assert "baca_email" not in names                            # domain lain dibuang


def test_bundel_umum_penuh():
    tools = [{"name": "baca_email"}, {"name": "simulasi_hpp"}]
    assert router.bundel({"umum"}, tools) == tools


def test_bundel_tak_pernah_kosong():
    tools = [{"name": "baca_email"}]  # tak ada tool produksi
    assert router.bundel({"produksi"}, tools) == tools  # fallback penuh, bukan []
