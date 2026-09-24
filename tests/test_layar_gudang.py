"""Halaman "Satu gudang" di Pos Produksi — celah ke-3 dari lima menjelang app
meja & gudang2 dihapus.

Yang dijaga di sini bukan "halamannya tampil" melainkan dua hal yang kalau
salah tak akan kelihatan: gerbangnya menanya VIEW (bukan peran tersimpan), dan
templatnya tidak menumbuhkan salinan keempat markup petak.
"""
from __future__ import annotations

import inspect
import pathlib

import hmu_tampilan
from app.web.layar import (ADMIN, GUDANG, NAMA_GUDANG, POLESAN, SELEPAN, SUPER,
                           TAMU, boleh_lihat_gudang)

AKAR = pathlib.Path(__file__).resolve().parents[1]
TPL = AKAR / "hmu_tampilan/templates/gudang.html"


def test_gerbang_bertanya_view_bukan_peran_tersimpan():
    """Admin yang memakai "Lihat sebagai operator Gudang 2" harus kehilangan
    Gudang 1 di sini juga.

    Kalau gerbangnya `butuh_admin`, samarannya bocor: peran tersimpannya masih
    admin, jadi halaman gudang sebelah tetap terbuka — dan pemilik yang memakai
    samaran itu pulang mengira operatornya melihat hal yang tak pernah ia lihat.
    """
    from app.web import layar_gudang

    sumber = inspect.getsource(layar_gudang)
    assert "boleh_lihat_gudang" in sumber
    # Yang diperiksa PEMAKAIANNYA, bukan penyebutannya: docstring rutenya
    # memang menyebut `butuh_admin` untuk menjelaskan kenapa ia TIDAK dipakai,
    # dan uji yang menolak kata itu menghukum penjelasannya.
    assert "Depends(butuh_admin)" not in sumber, "gerbang peran tersimpan membocorkan samaran"
    assert "request.state" in sumber and "view" in sumber
    # Membaca saja. Ringkasan yang menerima kiriman jadi tempat kedua untuk
    # mengubah hal yang sama.
    assert "@router.post" not in sumber


def test_operator_melihat_gudangnya_bukan_gudang_sebelah():
    """Yang dilarang gudang SEBELAH, bukan halamannya.

    Melarang operator membuka gudangnya sendiri cuma membuat tautan yang tak
    boleh ditekan: petaknya sama dengan yang sudah ada di Beranda-nya.
    """
    assert boleh_lihat_gudang(SELEPAN, "g1") and not boleh_lihat_gudang(SELEPAN, "g2")
    assert boleh_lihat_gudang(POLESAN, "g2") and not boleh_lihat_gudang(POLESAN, "g1")
    # Peran meja memegang keduanya — itu definisinya.
    for v in (SUPER, ADMIN):
        assert boleh_lihat_gudang(v, "g1") and boleh_lihat_gudang(v, "g2")
    # Operator yang belum diberi gudang tak punya satu pun.
    assert not boleh_lihat_gudang(TAMU, "g1") and not boleh_lihat_gudang(TAMU, "g2")
    # Gudang karangan ditolak sebelum menyentuh basis data.
    assert not boleh_lihat_gudang(SUPER, "g9")


def test_daftar_gudang_tinggal_satu_salinan():
    """`GUDANG` lahir di `meja_api` dan dipindah ke `app.web.layar` saat Pos
    Produksi memakainya juga — dua salinan daftar gudang berarti gudang ketiga
    yang muncul di satu layar dan tidak di layar sebelahnya.

    `meja_api` dihapus 24 September 2026 bersama app Meja; yang dijaga kini
    seluruh `app/web/`: tak boleh ada berkas layar yang menuliskan daftarnya
    sendiri, apa pun namanya.
    """
    import pathlib

    from app.web import layar

    assert [g for g, _, _ in GUDANG] == ["g1", "g2"]
    assert set(NAMA_GUDANG) == {"g1", "g2"}
    web = pathlib.Path(inspect.getsourcefile(layar)).resolve().parent
    for berkas in web.glob("*.py"):
        if berkas.name == "layar.py":
            continue
        assert '("g1", "Gudang 1"' not in berkas.read_text(), \
            f"daftar gudang disalin lagi di {berkas.name}"


def test_templat_gudang_di_paket_dan_tanpa_salinan_petak():
    """Markup sel petak sempat hidup di TIGA berkas. Halaman ini memanggil
    makronya; sel yang disalin adalah sel yang cepat atau lambat beda tinggi
    barisnya."""
    assert "gudang.html" in hmu_tampilan.BERKAS_PAKET
    s = TPL.read_text()
    assert "br.petak_rata(" in s
    assert "petak__sel" not in s, "markup sel petak disalin ke layar"
    assert "_beranda.html" in s and "with context" in s
    # Tombol bisu: `aksi.js` hanya di app yang punya rute aksinya.
    assert "{% if blok_aksi %}" in s and "aksi.js" in s


def test_tombol_kembali_bukan_tab():
    """Halaman ini punya INDUK (Beranda) dan bukan tab. `render` menurunkan
    `layar` dari nama templat, jadi tanpa `kembali` orang mendarat di layar
    tanpa jalan pulang — dan `layar="gudang"` bukan kunci tab mana pun,
    sehingga laci pun tak menyalakan apa-apa."""
    from app.web import layar_gudang
    from app.web.nav import TAB

    sumber = inspect.getsource(layar_gudang)
    assert 'kembali="/"' in sumber
    assert "gudang" not in {k for k, _, _, _, _ in TAB}
