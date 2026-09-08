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


def test_tiap_lot_menyebut_pemasok_dan_tanggalnya():
    from app.services import stok

    fn = inspect.getsource(stok.pk_gudang1)
    assert "_milling_supplier_names" in fn, "pemasok tak diambil"
    assert "waktu_selesai" in fn, "tanggal giling tak diambil"
    teks = TPL.read_text()
    assert "ringkas(l.pemasok)" in teks and "l.tanggal" in teks


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


def test_lot_yang_mesinnya_masih_menyala_ditandai():
    """PK-nya sudah ada tetapi angkanya belum final — dan angka belum final
    yang terbaca final akan dipakai merencanakan kiriman."""
    from app.services import stok

    assert 'proc.status == "proses"' in inspect.getsource(stok.pk_gudang1)
    assert "nota--hati" in TPL.read_text()
