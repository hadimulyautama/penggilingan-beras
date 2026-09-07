"""Uji setelan pabrik & tempat katalog aksi.

Dua hal yang ditemukan pemilik saat memakai beta: daftar aksi lengkap masih
menggantung di bawah antrean, dan setelan yang ada di rancangan tak ada di
aplikasi.
"""
from __future__ import annotations

import inspect
import pathlib
import types

from app.services import setelan
from app.web.tampilan import templates
from tests.bantu import kode_saja

AKAR = pathlib.Path(__file__).resolve().parents[1]


def _akun(peran: str):
    a = types.SimpleNamespace(nama="Pras", peran=peran, sesi_pendek=False)
    a.is_admin = peran in ("admin", "superadmin")
    return a


def test_katalog_aksi_keluar_dari_antrean():
    """Antrean adalah daftar BENDA. Daftar kata kerja di bawahnya cuma
    menawarkan pintu kedua untuk pekerjaan yang sudah punya pintu — dan
    membuat antrean berhenti berarti apa yang ia namai."""
    html = (AKAR / "app/web/templates/aksi.html").read_text()
    assert "semua-aksi" not in html
    assert "Catat pekerjaan lain" not in html.split("{% block isi %}")[1] \
        or "/aksi-lain" in html


def test_katalog_punya_alamatnya_sendiri():
    """Tak ada yang boleh jadi tak terjangkau: aksi yang tak berwujud benda —
    harga, QC, barang keluar, pembatalan — tetap perlu pintu."""
    from app import main
    from app.web.nav import TAB

    assert any(k == "aksi_lain" for k, *_ in TAB)
    assert hasattr(main, "halaman_aksi_lain")
    # Dan halamannya benar-benar memuat kerangka yang diisi aksi.js.
    html = (AKAR / "app/web/templates/aksi_lain.html").read_text()
    assert 'id="layar"' in html and "aksi.js" in html


def test_antrean_kosong_menunjuk_ke_mana_lagi():
    """Layar kosong tanpa kalimat adalah tempat aplikasi terlihat rusak,
    padahal justru sedang benar."""
    html = templates.get_template("aksi.html").render(
        request=None, akun=_akun("operator"), layar="aksi", MENUNGGU=0,
        MODE_UJI=False, LIHAT_SEBAGAI=None, kembali=None,
        menunggu=[], berjalan=[], buka="", nilai="", lama=lambda t: "", FASE={})
    assert "Tidak ada yang menunggu Anda" in html
    assert "/berjalan" in html and "/aksi-lain" in html


def test_setelan_kerja_hanya_untuk_admin():
    """Operator mengurus data dirinya sendiri dan sandinya sendiri, tak lebih.
    Sebab berhenti dan target bawaan menyentuh pekerjaan semua orang."""
    kosong = templates.get_template("pengaturan.html").render(
        request=None, akun=_akun("operator"), layar="pengaturan", MENUNGGU=0,
        MODE_UJI=True, LIHAT_SEBAGAI=None, kembali=None, pesan_ok=None, err="",
        tuan=False, target_bawaan=None, sebab_jeda={}, JAM_BATAS=48)
    for blok in ("Sebab berhenti", "Target kadar air bawaan", "Batas ubah catatan"):
        assert blok not in kosong, blok

    penuh = templates.get_template("pengaturan.html").render(
        request=None, akun=_akun("admin"), layar="pengaturan", MENUNGGU=0,
        MODE_UJI=True, LIHAT_SEBAGAI=None, kembali=None, pesan_ok=None, err="",
        tuan=True, target_bawaan=14.0,
        sebab_jeda={"pengeringan": ["Listrik padam", "Bahan bakar habis"],
                    "giling": ["Mesin giling rusak", "Limbah produksi penuh"]},
        JAM_BATAS=48)
    for blok in ("Sebab berhenti · pengeringan", "Sebab berhenti · giling",
                 "Target kadar air bawaan", "Batas ubah catatan"):
        assert blok in penuh, blok


def test_batas_48_jam_ditampilkan_tapi_tak_bisa_diubah():
    """Batas yang bisa dilonggarkan oleh orang yang ingin melonggarkannya
    bukan batas. Tetapi menyembunyikannya juga salah — setelan yang diam tanpa
    keterangan akan dicari orang di menu lain sampai lelah."""
    html = (AKAR / "app/web/templates/pengaturan.html").read_text()
    blok = html[html.index("Batas ubah catatan"):]
    blok = blok[:blok.index("</div>\n</div>") + 12] if "</div>\n</div>" in blok else blok
    assert "<form" not in blok, "batas tak boleh punya borang"
    assert "keputusan Direksi" in blok


def test_sebab_berhenti_tak_boleh_dikosongkan():
    """Berhenti tanpa sebab tak bisa dipakai memperbaiki apa pun."""
    assert "tak boleh kosong" in inspect.getsource(setelan.set_sebab_jeda)


def test_setelan_rusak_sebagian_tak_mengosongkan_borang():
    """Setelan yang gagal dibaca tak boleh membuat borang jeda tak punya
    pilihan sama sekali — operator lalu tak bisa mencatat berhentinya."""
    sumber = kode_saja(setelan.sebab_jeda)
    assert "JSONDecodeError" in sumber
    assert "simpan.get(k) or v" in sumber


def test_borang_jeda_membaca_setelan_bukan_konstanta():
    """Yang ditambahkan admin harus langsung muncul tanpa menunggu kode
    berubah."""
    from app.web import miniapp

    sumber = inspect.getsource(miniapp.actions_menu)
    assert "SEBAB_AKTIF" in sumber
    assert "await sebab_jeda(db)" in sumber


def test_satu_tombol_satu_perubahan():
    """Borang yang mengirim seluruh daftar sekaligus akan menimpa perubahan
    orang lain yang membuka layar yang sama semenit lebih dulu."""
    from app.web import pengaturan

    sumber = kode_saja(pengaturan.ubah_sebab_jeda)
    assert "tambah" in sumber and "buang" in sumber
