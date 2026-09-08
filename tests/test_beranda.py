"""Uji Beranda: benda yang sama dengan Sedang berjalan, bentuk yang lebih padat.

Sebelum ini Beranda hanya menyebut pengeringan. Giling yang sedang berputar
dan silo yang sedang menunggu giliran tak pernah muncul — dan layar pembuka
yang tampak lengkap padahal separuh pabriknya tak disebut adalah cara paling
halus sebuah aplikasi berbohong: tak ada yang salah untuk dilaporkan, karena
tak ada yang tahu ada yang hilang.
"""
from __future__ import annotations

import inspect
import pathlib
import types

from app.services.berjalan import Baris
from app.web.tampilan import templates

AKAR = pathlib.Path(__file__).resolve().parents[1]
TPL = AKAR / "app/web/templates"


def _akun(peran: str = "operator"):
    a = types.SimpleNamespace(nama="Pras", peran=peran, sesi_pendek=False)
    a.is_admin = peran in ("admin", "superadmin")
    return a


def _beranda(**ubah):
    arg = dict(
        request=None, akun=_akun(), layar="beranda", MENUNGGU=0,
        BERJALAN=0, KEPUTUSAN=0, buka="", nilai="", VERSI="uji",
        MODE_UJI=False, LIHAT_SEBAGAI=None, kembali=None, pesan_ok=None,
        gabah_kg=42000, gabah_batch=5, pengeringan=1, silo_terisi=1,
        silo_total=2, giling=1, stok_pk=8000, stok_pk_maks=30000,
        berjalan=[], transit=[], lama=lambda t: "3 jam 10 menit",
    )
    arg.update(ubah)
    return templates.get_template("beranda.html").render(**arg)


def _giling():
    return Baris(
        kode="GLG-01", isi="digiling", judul="Giling",
        utama=("9.900", "kg"), sub="GLG-01 · bahan masuk",
        ringkas="9.900 kg bahan masuk", keadaan="catat hasil",
        aksi="hasil_giling", nilai="GLG-01", fase="giling",
        pilihan=[("hasil_giling", "Perbarui hasil giling", "PK kumulatif"),
                 ("selesai_giling", "Selesai giling", "Tutup proses")])


def _silo():
    return Baris(
        kode="Silo A", isi="gabah kering", judul="Silo A",
        utama=("21.000", "kg"), ringkas="gabah kering · menunggu giliran",
        keadaan="mulai giling bila siap", aksi="mulai_giling",
        nilai="A", fase="silo")


def test_beranda_menyebut_giling_dan_silo_bukan_pengeringan_saja():
    """Operator yang membuka aplikasi harus melihat gilingnya sendiri."""
    html = _beranda(berjalan=[_giling()], transit=[_silo()])
    assert "Giling" in html and "9.900" in html
    assert "Silo A" in html and "21.000" in html
    # Cacahnya kini elemen tersendiri supaya penyaring antrean bisa
    # menghitungnya ulang, jadi teksnya tak lagi menyatu.
    import re
    judul = re.findall(r'class="lbl">([^<]+)·\s*<span data-jumlah>(\d+)<', html)
    assert [(a.strip(), b) for a, b in judul] == [
        ("Sedang berjalan", "1"), ("Transit", "1")]


def test_kartu_beranda_bisa_dikerjakan_dari_situ():
    """Ringkas bukan berarti tak bisa dikerjakan. Kartu yang cuma bisa dilihat
    memaksa orang membuka layar lain untuk menekan tombol yang sama."""
    html = _beranda(berjalan=[_giling()], transit=[_silo()])
    # Lembarnya dibuka DI BERANDA. Menekan "Perbarui hasil giling" lalu
    # mendarat di Antrian tunggu berarti orang kehilangan tempatnya — dan
    # yang ia tekan tadi ada di layar ini, bukan di sana.
    assert "/?buka=hasil_giling&nilai=GLG-01" in html
    assert "/?buka=selesai_giling&nilai=GLG-01" in html
    assert "/?buka=mulai_giling&nilai=A" in html
    assert "/aksi?buka=" not in html
    # Dan kerangka lembarnya memang ada di halaman ini.
    assert 'id="lembar"' in html and 'id="kabar"' in html
    assert "aksi.js" in html and 'data-buka=' in html


def test_kartu_beranda_padat_bukan_kartu_penuh():
    """Gunanya Beranda adalah memuat seluruh pabrik dalam satu layar. Kartu
    penuh membatalkan itu — rinciannya sudah punya layarnya sendiri."""
    kartu = _giling()
    kartu.fakta = [("Bahan", "9.900 kg")]
    kartu.anak = [("B-01", "9.900 kg", "")]
    html = _beranda(berjalan=[kartu])
    assert "padat__nama" in html
    assert 'class="fakta"' not in html, "fakta hanya untuk kartu penuh"
    assert 'class="anak"' not in html, "rincian batch hanya untuk kartu penuh"


def test_batang_kemajuan_hanya_untuk_yang_punya_ukurannya():
    """Giling tak punya garis selesai. Memberinya batang kemajuan berarti
    menjawab pertanyaan yang tak bisa dijawab — lebih buruk daripada diam."""
    assert "maju__bar" not in _beranda(berjalan=[_giling()])

    pgr = Baris(kode="PGR-01", isi="dikeringkan", judul="Pengeringan",
                utama=("30.000", "kg"), keadaan="menunggu kadar air turun",
                aksi="kadar_air", nilai="PGR-01", fase="dryer", maju=0.42,
                ringkas="alat tes 18,0% → target 14%")
    html = _beranda(berjalan=[pgr])
    assert "maju__bar" in html and "42.0%" in html


def test_beranda_tak_mengulang_pintu_yang_sudah_ada_di_laci():
    """Dua pintu ke tempat yang sama adalah dua tempat di kepala orang."""
    # Dibaca dari berkasnya, bukan dari halaman jadi: laci memang memuat
    # ketiganya, dan itu justru inti soalnya — tempatnya di laci, bukan di
    # badan halaman.
    isi = (TPL / "beranda.html").read_text()
    assert 'href="/laporan"' not in isi
    assert 'href="/pengaturan"' not in isi
    # Yang tersisa satu, dan ia tinggal karena membawa jumlah — pintu laci tak
    # memberi tahu berapa yang menunggu tanpa dibuka dulu.
    assert 'href="/aksi"' in isi
    assert "Antrian tunggu" in isi and "Catat pekerjaan" not in isi


def test_beranda_kosong_tetap_berkata_sesuatu():
    html = _beranda()
    assert "Tidak ada mesin yang menyala" in html


def test_beranda_memakai_daftar_yang_sama_bukan_hitungan_sendiri():
    """Beranda yang menghitung sendiri apa yang berjalan cepat atau lambat
    menyebut angka yang berbeda dari layar sebelahnya."""
    from app import main

    sumber = inspect.getsource(main.beranda)
    assert "svc.untuk(db, akun.user)" in sumber
    assert "berjalan=jalan.berjalan" in sumber and "transit=jalan.transit" in sumber
    # Dan kartunya makro yang sama, bukan salinan.
    assert '"_benda.html"' in (TPL / "beranda.html").read_text()


def test_transit_sampai_ke_layarnya():
    """Gabah di dryer dan silo sengaja dikeluarkan dari antrean. Kalau
    transitnya tak ikut dibawa, ia hilang dari KEDUA layar sekaligus — dan
    yang hilang dari semua layar tak akan pernah ada yang mencarinya."""
    from app.services import berjalan as svc

    sumber = inspect.getsource(svc.untuk)
    # Gudang 1 (operator), Gudang 1 (staff yang bukan operator), dan Gudang 2.
    assert sumber.count("b.transit += ") == 3, "tiap gudang & tiap peran perlu"


def test_tiap_kartu_menyebut_asal_usul_barangnya():
    """Pemilik: tiap kartu harus menyebut asal-usul barangnya — minimal nama
    pemasok dan tanggal masuk.

    Kode batch saja tak memberi tahu apa pun tentang gabah SIAPA yang sedang
    di dalam mesin, dan begitu ada keluhan mutu, pemasok dan tanggal masuk
    itulah dua hal pertama yang dicari. Menuntut orang membuka laporan untuk
    mengetahuinya berarti pertanyaan itu tak pernah terjawab di lapangan.
    """
    import inspect

    from app.services import berjalan as svc

    sumber = inspect.getsource(svc)
    assert "async def _asal(" in sumber
    fn = inspect.getsource(svc._asal)
    assert "Supplier.nama_supplier" in fn and "tanggal_pembelian" in fn
    assert 'f"masuk {_tgl(tgl)}"' in fn

    # Dipakai oleh SETIAP jenis kartu yang membawa barang: mesin pengering,
    # pengeringan, pendinginan, lot dingin, silo, giling, dan kerja meja.
    g1 = inspect.getsource(svc.untuk_gudang1)
    assert g1.count("await _asal(") >= 5, "ada kartu yang belum menyebut asalnya"
    assert "_pemasok_ringkas(" in g1
    assert "await _asal(" in inspect.getsource(svc.untuk_staff)


def test_beranda_tidak_ikut_berubah():
    """Pemilik: "yang di beranda sudah sempurna, jangan disentuh lagi."

    Asal-usul ditaruh di `anak` dan `sub` — keduanya TIDAK dirender kartu
    padat, jadi Beranda tetap seperti sebelumnya. Yang dirender di sana
    `judul`, `utama`, dan `ringkas`.
    """
    makro = (TPL / "_benda.html").read_text()
    padat = makro.split("{% macro padat(b) -%}")[1].split("{%- endmacro %}")[0]
    assert "b.anak" not in padat and "b.fakta" not in padat
    assert "b.ringkas or b.sub or b.isi" in padat
