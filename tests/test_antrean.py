"""Uji antrean tunggu: kerja gudang, kerja meja, dan penyaringnya.

Pemilik menemukan tiket yang seolah tertinggal di antrean padahal gabahnya
sudah masuk dryer atau silo. Ternyata bukan tiket: itu baris verifikasi harga
— pekerjaan lain yang memakai baju tiket, dengan kepingan fase yang berbohong
("Belum ada tindakan" untuk gabah yang sudah dua hari di dalam mesin).
"""
from __future__ import annotations

import inspect
import pathlib
import types

from app.services.berjalan import Baris, Berjalan, untuk_staff
from app.web.tampilan import templates

AKAR = pathlib.Path(__file__).resolve().parents[1]
TPL = AKAR / "app/web/templates"


def _akun(peran: str = "operator"):
    a = types.SimpleNamespace(nama="Pras", peran=peran, sesi_pendek=False)
    a.is_admin = peran in ("admin", "superadmin")
    return a


def _tiket(judul="H. Karyo", kode="TRX-1"):
    return Baris(kode=kode, isi="gabah basah", judul=judul,
                 utama=("9.200", "kg"), sub=f"{kode} · Gabah Basah · AD 1 XY",
                 keadaan="", aksi="gabah_masuk", nilai="1", fase="baru")


def _meja(judul="Bu Sri", kode="GB-01", fase="silo"):
    return Baris(kode=kode, isi=f"{judul} · 6.100 kg", judul=judul,
                 utama=("6.100", "kg"), sub=f"{kode} · gabah kering",
                 fakta=[("Gabahnya", "sudah di silo")],
                 keadaan="harga belum diverifikasi", aksi="verify_gabah",
                 nilai=kode, fase=fase)


def _render(menunggu, meja):
    return templates.get_template("aksi.html").render(
        request=None, akun=_akun("admin"), layar="aksi",
        MENUNGGU=len(menunggu) + len(meja), MODE_UJI=False, LIHAT_SEBAGAI=None,
        kembali=None, menunggu=menunggu, berjalan=[], meja=meja,
        buka="", nilai="", lama=lambda t: "")


def test_kerja_meja_hanya_untuk_yang_boleh_melihat_uang():
    """Verifikasi harga sejak awal fitur admin. Operator — dan admin yang
    sedang memakai Mode operator — tak boleh melihatnya sama sekali."""
    sumber = inspect.getsource(
        __import__("app.services.berjalan", fromlist=["untuk"]).untuk)
    # Satu-satunya jalan `meja` terisi adalah lewat gerbang uang.
    assert "b.meja += s.meja" in sumber
    baris = sumber.split("b.meja += s.meja")[0]
    assert baris.rstrip().endswith("s = await untuk_staff(db)")
    assert "if can_see_financials(user):" in baris
    # Dan tak ada jalan lain: `untuk_gudang1` tak pernah menyentuh `meja`.
    g1 = inspect.getsource(
        __import__("app.services.berjalan", fromlist=["untuk_gudang1"]).untuk_gudang1)
    assert ".meja" not in g1


def test_lencana_tetap_menghitung_kerja_meja():
    """Ia memang menunggu ORANG — dipisah tempatnya, bukan diabaikan."""
    b = Berjalan(menunggu=[_tiket()], meja=[_meja(), _meja()])
    assert b.jumlah_menunggu == 3


def test_kepingan_fase_baris_meja_tidak_berbohong():
    """"Belum ada tindakan" untuk gabah yang sudah di dalam mesin adalah
    kepingan yang dipercaya justru karena ia salah."""
    sumber = inspect.getsource(untuk_staff)
    assert "_FASE_BATCH" in sumber and "fase=_FASE_BATCH" in sumber
    from app.services.berjalan import _DI_MANA, _FASE_BATCH

    assert _FASE_BATCH["di_dryer"] == "dryer"
    assert _FASE_BATCH["di_silo"] == "silo"
    assert _FASE_BATCH["digiling"] == "giling"
    assert _FASE_BATCH["ditumpuk"] == "baru"
    # Dan barisnya menyebut di mana gabahnya, supaya tak perlu buka layar lain.
    assert set(_DI_MANA) == set(_FASE_BATCH)
    assert "fakta=[(\"Gabahnya\"" in sumber


def test_dua_blok_terpisah_di_layar():
    """Dicampur, baris kerja meja terbaca seperti tiket yang tertinggal — lalu
    orang mencari gabah yang sebenarnya sudah lama ditempatkan."""
    def label(h):
        import re
        return [x.strip() for x in re.findall(r'class="lbl">([^<]+)·', h)]

    assert label(_render([_tiket()], [_meja()])) == [
        "Bisa dikerjakan sekarang", "Menunggu keputusan Anda"]
    # Blok yang kosong tidak muncul sama sekali.
    assert label(_render([_tiket()], [])) == ["Bisa dikerjakan sekarang"]


def test_penyaring_muncul_hanya_saat_antreannya_panjang():
    """Di bawah lima baris seluruh daftarnya sudah terbaca sekaligus; kotak
    cari di atasnya cuma menyita ruang untuk mencari yang sudah kelihatan."""
    pendek = _render([_tiket(kode=f"TRX-{i}") for i in range(4)], [])
    assert 'id="cari-antri"' not in pendek

    panjang = _render([_tiket(judul=n, kode=f"TRX-{i}") for i, n in
                       enumerate(("H. Karyo", "Bu Sri", "Pak Tarno",
                                  "H. Sulaiman", "Bu Sri"))], [])
    assert 'id="cari-antri"' in panjang
    assert 'id="saring-pemasok"' in panjang
    # Pemasoknya unik dan urut — bukan satu baris per tiket.
    opsi = panjang.split('id="saring-pemasok"')[1].split("</select>")[0]
    assert opsi.count("<option") == 5           # 4 pemasok + "Semua pemasok"
    assert opsi.index("Bu Sri") < opsi.index("H. Karyo")


def test_kartu_membawa_teks_yang_bisa_dicari():
    """Menyaring dengan membaca innerText berarti ikut membaca label dan
    satuan — lalu mengetik "kg" menampilkan semuanya."""
    html = _render([_tiket(judul=n, kode=f"TRX-{i}") for i, n in
                    enumerate(("A", "B", "C", "D", "E"))], [])
    assert 'data-cari="' in html and 'data-sup="' in html
    assert "data-blok" in html and "data-jumlah" in html


def test_tak_ada_dua_kalimat_bermakna_sama():
    """"Belum ada tindakan" (kepingan) dan "catat & tentukan tempatnya"
    (keadaan) mengatakan hal yang sama, dan dua kalimat bermakna sama membuat
    orang mencari bedanya lalu menemukan tak ada."""
    from app.services import berjalan as svc

    sumber = inspect.getsource(svc._tiket_belum_ditaut)
    assert "catat & tentukan tempatnya" not in sumber
    assert "susulan" in sumber, "yang susulan tetap bicara — itu menambah sesuatu"
    # Waktunya tetap terbaca meski keadaannya kosong.
    makro = (TPL / "_benda.html").read_text()
    assert "{% if b.keadaan or lama(b.sejak) %}" in makro
