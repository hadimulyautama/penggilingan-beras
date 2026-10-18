"""Kontrak Stok sesudah daftar dan detail dipisah: data, izin, dan saklar QC.

Uji sumber lama memeriksa kelas kartu yang sudah tidak dipakai. Render nyata
menjaga informasi yang sama pada komponen baru tanpa membekukan bentuk HTML.
"""
from pathlib import Path
from types import SimpleNamespace

import pytest
from jinja2 import ChoiceLoader, DictLoader, Environment, FileSystemLoader

TEMPLAT = Path(__file__).resolve().parents[1] / "hmu_tampilan/templates"


def gambar(*, detail=False, mutu_aktif=True, berjalan=False,
           boleh_ubah=False, boleh_minta=False):
    from app.services.stok import LotPk

    lot = LotPk("LOT-UJI-01", 400, 600, 200, bahan_kg=1000, rendemen=60,
                kelas="KS", tanggal="18/10/2026", lama="2 hari", berjalan=berjalan,
                bahan=[("GB-UJI-01 · Bu Sri", "700", "16/10/2026"),
                       ("GB-UJI-02 · Pak Budi", "300", "17/10/2026")],
                mutu=[("Kadar air", "13,5%"), ("Butir patah", "22%")],
                nilai_kualitas=87.2, kelas_kualitas="Baik", komponen_kualitas=6)
    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block isi %}{% endblock %}{% block kaki %}{% endblock %}"}),
        FileSystemLoader(str(TEMPLAT)),
    ]), autoescape=True)
    env.filters["jam"] = lambda nilai, fmt="": ""
    penilaian = SimpleNamespace(nilai=None, n=0, putaran=0, rows=[], lengkap=False,
                                klasifikasi=(), kelas=None, aturan_angka={}, kelas_aturan=())
    return env.get_template("stok.html").render(
        lot=[lot], tempat=[], total=400, gudang="", request=None,
        detail=detail, detail_kartu=lot, detail_gudang="g1",
        detail_href="/stok/pk/detail?gudang=g1&kode=LOT-UJI-01",
        kembali="/stok", mutu_aktif=mutu_aktif, boleh_ubah=boleh_ubah,
        boleh_minta=boleh_minta, boleh_pindah_tumpukan=False,
        JASA_SAJA=False, VIEW="admin", V_POLESAN="polesan", SARING_GUDANG=(),
        JUMLAH_KOMPONEN_QC_PK=6, VERSI="uji", buka="", nilai="",
        riwayat_qc=SimpleNamespace(penilaian=penilaian, rows=[], ada_data_lama=False))


@pytest.mark.parametrize("detail", [False, True])
@pytest.mark.parametrize("aktif", [False, True])
def test_saklar_mutu_memadamkan_angka_kolom_dan_aksi(detail, aktif):
    html = gambar(detail=detail, mutu_aktif=aktif, boleh_ubah=True)
    assert ("13,5%" in html) == aktif
    assert ("87,2" in html) == aktif
    if detail:
        assert ("buka=qc_giling" in html) == aktif
        assert ("Riwayat QC" in html) == aktif
        assert "buka=verify_output" in html
    else:
        assert ("<th>Kadar air</th>" in html) == aktif
        assert ("stok-desktop--tanpa-mutu" in html) != aktif
    assert "LOT-UJI-01" in html
    # Satuan boleh menjadi <small> di detail; angka dan satuannya tetap
    # terbaca bersebelahan, tanpa membekukan tag pembungkusnya.
    from html.parser import HTMLParser
    class Teks(HTMLParser):
        def __init__(self):
            super().__init__()
            self.bagian = []
        def handle_data(self, data):
            self.bagian.append(data)
    teks = Teks()
    teks.feed(html)
    assert "400 kg" in " ".join("".join(teks.bagian).split())


@pytest.mark.parametrize("ubah,minta,berjalan", [
    (False, False, False), (True, False, False), (False, True, False),
    (True, True, True),
])
def test_detail_menjaga_izin_dan_status_mesin(ubah, minta, berjalan):
    html = gambar(detail=True, boleh_ubah=ubah, boleh_minta=minta, berjalan=berjalan)
    assert ("buka=verify_output" in html) == (ubah and not berjalan)
    assert ("buka=minta_pk_g1" in html) == (minta and not berjalan)
    assert ("Mesin masih giling. Hasil dan rendemen belum final." in html) == berjalan
    # Bahan tetap terbaca meskipun aksi ditutup atau mesin sedang berjalan.
    for teks in ("Batch gabah <span>2</span>", "GB-UJI-01 · Bu Sri", "700 kg",
                 "GB-UJI-02 · Pak Budi", "300 kg", "2 hari", "60,0%"):
        assert teks in html
