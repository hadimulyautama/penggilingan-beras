"""Harga keluar dari Pos Produksi — keputusan pemilik 28 September 2026.

Yang dibuang: verifikasi/penetapan harga (gabah, PK luar, hasil samping) dan
KEDUA HPP (PK dan beras), berikut tarif biayanya.

Yang TETAP, dan bedanya penting: pencatatan TRANSAKSI yang benar-benar terjadi
— beli karung, jual PK, barang jadi keluar, bekatul keluar. Keempatnya mencatat
uang yang berpindah, bukan menilai ulang sesuatu yang sudah tercatat.
"""
from __future__ import annotations

import pathlib
import re

import pytest

AKAR = pathlib.Path(__file__).resolve().parents[1]

#: Empat aksi TRANSAKSI yang boleh punya medan harga. Penegasan pemilik.
BOLEH_BERHARGA = {"beli_kemasan", "jual_pk", "kirim_barang_jadi", "kirim_bekatul"}


def _spesifikasi() -> dict[str, list[str]]:
    """{id aksi: nama medannya} dari seluruh katalog.

    Dibaca PER BERKAS — menggabungkan sumbernya lebih dulu membuat spesifikasi
    terakhir satu berkas menyerap medan spesifikasi pertama berkas berikutnya,
    dan pagar yang salah menuduh lebih buruk daripada tak ada pagar.

    `_bidang_pengiriman()` dibentangkan: medannya tak tertulis di tempat
    spesifikasinya, dan tanpa itu `jual_pk` terbaca seolah kehilangan harganya.
    """
    keluar: dict[str, list[str]] = {}
    for berkas in ("app/web/api.py", "app/web/aksi_inventory.py",
                   "app/web/aksi_undo.py"):
        teks = (AKAR / berkas).read_text()
        kirim: list[str] = []
        if "def _bidang_pengiriman(" in teks:
            i = teks.index("def _bidang_pengiriman(")
            kirim = re.findall(r'"name": "([a-z0-9_]+)"',
                               teks[i:teks.index("\n\n\n", i)])
        for m in re.finditer(r'\{"id": "([a-z0-9_]+)", "label": "', teks):
            i = teks.find('"fields"', m.end())
            if i < 0 or i - m.end() > 2500:
                continue
            n = teks.find('{"id": "', m.end())
            j = n if n > 0 else len(teks)
            blok = teks[i:j]
            medan = re.findall(r'"name": "([a-z0-9_]+)"', blok)
            if "_bidang_pengiriman()" in blok:
                medan += kirim
            keluar[m.group(1)] = medan
    return keluar


def test_tak_ada_borang_yang_meminta_harga_selain_transaksi():
    """Pagar utamanya: Pos Produksi tak lagi MENANYAKAN harga, kecuali pada
    empat aksi yang mencatat uang benar-benar berpindah.

    Diuji pada BENTUK BORANGNYA, bukan pada nama fungsinya: yang sampai ke
    orang adalah medan yang ia lihat di layar, dan aksi baru yang diam-diam
    membawa medan harga akan lolos dari pagar yang cuma membaca daftar nama.
    """
    salah = []
    for aksi, medan in _spesifikasi().items():
        if aksi in BOLEH_BERHARGA:
            continue
        for m in medan:
            if "harga" in m or m in ("nilai", "total_biaya", "hpp"):
                salah.append(f"{aksi}.{m}")
    assert not salah, ("borang ini meminta harga padahal bukan transaksi: "
                       + ", ".join(salah))


def test_keempat_aksi_transaksi_tetap_punya_medan_harganya():
    """Sisi lain, dan ia wajib ada: "buang harga" mudah dikerjakan dengan cara
    yang salah — menyapu SEMUA medan harga, lalu pembelian karung dan penjualan
    PK kehilangan angkanya, dan tak ada yang tahu berapa uang yang berpindah."""
    spek = _spesifikasi()
    wajib = {"beli_kemasan": "harga_per_lembar", "jual_pk": "harga_per_kg",
             "kirim_barang_jadi": "harga_per_kg", "kirim_bekatul": "harga_per_kg"}
    for aksi, medan in wajib.items():
        assert aksi in spek, f"{aksi} hilang dari katalog"
        assert medan in spek[aksi], f"{aksi} kehilangan {medan}"


def test_ketiga_aksi_harga_benar_benar_hilang():
    """Disebut satu per satu, bukan disandarkan pada pagar di atas: pagar itu
    berangkat dari katalog, dan aksi yang rutenya tertinggal tanpa spesifikasi
    tetap bisa dipanggil lewat alamatnya."""
    api = (AKAR / "app/web/api.py").read_text()
    inv = (AKAR / "app/web/aksi_inventory.py").read_text()
    for rute in ("/actions/verify-gabah", "/actions/harga-pk-luar",
                 "/actions/harga-byproduct"):
        assert f'"{rute}"' not in api + inv, f"rute {rute} masih hidup"


def test_kedua_hpp_tak_ada_lagi():
    """Keduanya mati dengan sendirinya begitu harga pergi — HPP PK butuh harga
    gabah, HPP beras butuh HPP PK dan harga hasil samping. Yang dibiarkan hidup
    akan menjawab "menunggu data lengkap" selamanya, dan blok yang selalu
    kosong mengajari orang berhenti membaca dasbornya."""
    assert not (AKAR / "app/services/costing.py").exists(), "costing.py kembali"
    from app.penggilingan.inventory import finished_goods as bj
    from app.services import analytics, transfer

    for modul, nama in ((transfer, "hpp_per_kg_pk"), (bj, "hitung_hpp_beras"),
                        (bj, "laporan_hpp_beras"), (bj, "biaya_penyosohan_proses"),
                        (bj, "set_harga_byproduct"), (bj, "harga_byproduct"),
                        (analytics, "hpp_trend"), (analytics, "biaya_produksi_detail"),
                        (analytics, "simulasi_hpp"), (analytics, "biaya_proses_ringkas")):
        assert not hasattr(modul, nama), f"{nama} kembali hidup"


def test_tarif_biaya_tak_ada_lagi_di_setelan():
    """Tarif yang dibiarkan berdiri tanpa pembaca akan dipelihara orang
    berikutnya — dinaikkan tiap tahun, dibahas di rapat — atas hitungan yang
    tak pernah dijalankan."""
    from app.config import settings

    for tarif in ("biaya_bongkar_per_kg_gabah", "biaya_operator_per_proses",
                  "biaya_pengeringan_basah_per_kg", "rubber_roll_harga_per_set",
                  "biaya_penyosohan_per_kg_pk", "biaya_marketing_per_kg_beras"):
        assert not hasattr(settings, tarif), f"{tarif} masih ada"
