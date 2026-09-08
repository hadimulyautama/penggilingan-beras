"""Layar Stok — PK Gudang 1, per lot giling.

Dua sifat yang dijaga, keduanya keputusan bukan selera:

· Membaca saja. Stok berubah lewat pencatatan pekerjaan. Halaman yang
  membolehkan orang mengetik angka stoknya akan dipakai menutupi selisih,
  dan selisih yang ditutupi berhenti jadi pertanyaan.
· Tiap baris menyebut asal-usulnya — aturan pemilik untuk SETIAP kartu.
  Kode lot saja tak memberi tahu gabah siapa yang ada di tumpukan itu.
"""
import inspect
import pathlib

TPL = pathlib.Path(__file__).resolve().parents[1] / "app/web/templates/stok.html"


def test_stok_hanya_membaca():
    from app.web import layar_stok

    sumber = inspect.getsource(layar_stok)
    assert "@router.post" not in sumber, "Stok tidak boleh menerima kiriman"
    teks = TPL.read_text()
    for larangan in ("<form", "data-post", "<input", "<button"):
        assert larangan not in teks, f"{larangan} muncul di layar yang membaca saja"


def test_tiap_lot_menyebut_pemasok_bobot_dan_tanggalnya():
    """Nama pemasok di baris atas menjawab "dari siapa"; rinciannya menjawab
    "dari siapa BERAPA" — dan begitu ada keluhan mutu, pertanyaan kedua itulah
    yang menentukan tumpukan mana yang harus ditahan."""
    from app.services import stok

    fn = inspect.getsource(stok.pk_gudang1)
    # Isi lot dibaca dari SATU sumber yang sama dengan HPP; dua jawaban untuk
    # "apa isi proses ini" akan berselisih, dan pada HPP selisihnya jadi uang.
    assert "sumber_batch" in fn, "isi lot tak diambil dari sumber bersama"
    assert "berat_total_kg" in fn, "bobot bahan tak disebut"
    assert "kode_batch" in fn and "nama_supplier" in fn
    assert "waktu_selesai" in fn, "tanggal giling tak diambil"

    teks = TPL.read_text()
    assert "l.tanggal" in teks
    assert "l.bahan" in teks and "anak__kg" in teks, "rincian bobot tak dirender"
    # Nama pemasok muncul SEKALI, di rinciannya. Ringkasan di baris atas
    # dibuang begitu rinciannya ada: dua kali nama yang sama membuat orang
    # mengira keduanya menyebut hal berbeda.
    assert "l.pemasok" not in teks, "nama pemasok masih diringkas di baris atas"


def test_harga_tak_ikut_terbawa_ke_layar_stok():
    """`sumber_batch` mengembalikan harga per kg juga. Layar Stok dilihat
    operator, dan operator tak berhak atas angka uang — jadi harga itu harus
    dibuang di tempat ia diterima, bukan disaring di templat."""
    from app.services import stok

    fn = inspect.getsource(stok.pk_gudang1)
    assert "_harga" in fn, "harga tak dibuang secara eksplisit"
    for uang in ("harga_per_kg", "hpp", "rupiah"):
        assert uang not in TPL.read_text().lower(), f"{uang} bocor ke layar Stok"


def test_angka_stok_dipinjam_bukan_dihitung_ulang():
    """Dua penghitung untuk satu barang cepat atau lambat berselisih, dan yang
    salah selalu yang lebih jarang dibuka."""
    from app.services import stok

    fn = inspect.getsource(stok.pk_gudang1)
    assert "_pk_breakdown" in fn
    assert "func.sum" not in fn, "stok dihitung ulang di sini"


def test_yang_habis_tak_ikut_terdaftar():
    """Daftar yang memuat baris nol mengajari orang melewatkan barisnya."""
    from app.services import stok

    assert "if bd.tersedia <= 0" in inspect.getsource(stok.pk_gudang1)


def test_rendemen_memakai_penyebut_yang_sama_dengan_seluruh_aplikasi():
    """Dua layar yang memakai penyebut berbeda akan menyebut rendemen berbeda
    untuk lot yang sama — dan yang melihatnya akan mencari sebabnya di mesin,
    bukan di catatan."""
    from app.penggilingan.gudang1.services import milling
    from app.services import stok

    assert "hitung_rendemen" in inspect.getsource(stok.pk_gudang1)
    # Tak ada lagi yang menghitung rendemen sendiri di luar helper itu.
    sumber = inspect.getsource(milling)
    assert "def hitung_rendemen(" in sumber
    # Tak ada lagi yang mengalikan 100 sendiri di luar helper itu.
    assert sumber.count("* 100") == 1, "rendemen masih dihitung sendiri di suatu tempat"

    teks = TPL.read_text()
    assert "l.rendemen" in teks and "sorot" in teks, "rendemen tak disorot"


def test_lot_yang_mesinnya_masih_menyala_ditandai():
    """PK-nya sudah ada tetapi angkanya belum final — dan angka belum final
    yang terbaca final akan dipakai merencanakan kiriman."""
    from app.services import stok

    assert 'proc.status == "proses"' in inspect.getsource(stok.pk_gudang1)
    assert "nota--hati" in TPL.read_text()
