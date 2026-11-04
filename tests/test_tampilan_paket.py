"""Penjaga paket tampilan (temuan QA X-22, Tahap 1 rancang ulang).

Sumber tunggal CSS/JS/templat dasar adalah repo `tampilan/` (paket
`hmu_tampilan`), di-vendor ke `hmu_tampilan/` di sini. Dua hal yang dijaga:
tak ada berkas paket yang disalin lagi ke tempat lain di repo ini, dan
salinan vendored tidak disunting tangan atau basi.
"""
from __future__ import annotations

import pathlib

from hmu_tampilan import penjaga

AKAR = pathlib.Path(__file__).resolve().parents[1]


def test_tak_ada_salinan_berkas_paket_di_repo_ini():
    assert penjaga.salinan_terlarang(AKAR) == []


def test_penjaga_membedakan_namespace_dan_salinan_asli(tmp_path):
    sumber = AKAR / 'hmu_tampilan/templates/masuk.html'
    portal = tmp_path / 'app/web/templates/portal/masuk.html'
    portal.parent.mkdir(parents=True)
    portal.write_text('<h1>Masuk pelanggan</h1>')
    ekspor = tmp_path / 'output/pratinjau/masuk.html'
    ekspor.parent.mkdir(parents=True)
    ekspor.write_bytes(sumber.read_bytes())
    assert penjaga.salinan_terlarang(tmp_path) == []
    portal.write_bytes(sumber.read_bytes())
    assert penjaga.salinan_terlarang(tmp_path) == [portal.relative_to(tmp_path)]
    portal.unlink()
    timpa = portal.parent.parent / 'masuk.html'
    timpa.write_text('<h1>Menimpa layar paket</h1>')
    assert penjaga.salinan_terlarang(tmp_path) == [timpa.relative_to(tmp_path)]


def test_vendored_selaras_dengan_manifest_dan_sumbernya():
    assert penjaga.vendor_selaras(AKAR) == []


def test_versi_aset_satu_nomor_dari_paket():
    import hmu_tampilan
    from app.web import tampilan
    assert tampilan.VERSI == hmu_tampilan.VERSI


def test_tak_ada_strftime_telanjang_di_templat():
    """Jam di templat WAJIB lewat saringan `jam`, bukan `.strftime(...)`.

    Laporan operator 30 September 2026: "jam pada kabar belum sesuai" — dan
    melesetnya tujuh jam. Kolom waktu di basis data `timestamptz`; asyncpg
    mengembalikannya ber-UTC, dan `.strftime()` di templat mencetaknya apa
    adanya. Empat templat lain mengidap hal yang sama tanpa ada yang tahu.

    Yang membuat kelas kesalahan ini bertahan: `.strftime()` BEKERJA. Ia tak
    pernah gagal, tak pernah berkabar, dan cacatnya hanya terlihat oleh orang
    yang membandingkan layarnya dengan jam tangannya. Jadi yang menjaganya
    tidak bisa "ingat memakai berzona" — harus pagar.

    Kalau suatu hari ada kolom yang memang naif dan perlu dicetak apa adanya:
    saringan `jam` sudah melewatkan yang naif tanpa menggesernya. Pakai
    saringannya; jangan longgarkan pagar ini.
    """
    salah = []
    for akar in (AKAR / "hmu_tampilan/templates", AKAR / "app/web/templates"):
        if not akar.is_dir():
            continue
        for berkas in sorted(akar.rglob("*.html")):
            for n, baris in enumerate(berkas.read_text().splitlines(), 1):
                if ".strftime(" in baris:
                    salah.append(f"{berkas.relative_to(AKAR)}:{n}")
    assert salah == [], (
        "templat mencetak waktu tanpa saringan `jam` — jamnya akan meleset "
        f"sebanyak beda zona: {salah}")
