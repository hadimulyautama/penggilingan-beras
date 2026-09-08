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

from tests.bantu import kode_saja

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

    bahan = kode_saja(stok._bahan)
    assert "kode_batch" in bahan and "nama_supplier" in bahan
    assert "berat_kg" in bahan, "bobot bahan tak disebut"
    # Proses lama tanpa baris sumber tetap dijawab, lewat sumber yang sama
    # dengan HPP — dua jawaban untuk "apa isi proses ini" akan berselisih.
    assert "sumber_batch" in bahan
    assert "waktu_selesai" in kode_saja(stok.pk_gudang1), "tanggal giling tak diambil"

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

    assert "_harga" in kode_saja(stok._bahan), "harga tak dibuang secara eksplisit"
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


def test_bobot_bahan_adalah_yang_masuk_mesin_bukan_berat_kiriman():
    """Baris bahan harus bisa DIJUMLAHKAN menjadi "Dari gabah" di atasnya.

    Pernah tidak: barisnya memakai `purchase_batches.berat_total_kg` — berat
    seluruh kiriman truk — sehingga satu batch berbunyi 8.250 kg di sebelah
    "Dari gabah 8.000 kg", padahal hanya 4.000 dari batch itu yang masuk lot
    ini; sisanya tertinggal di silo atau ikut giling lain. Angka yang tak bisa
    dijumlahkan menjadi angka di atasnya akan dicurigai sebagai salah hitung,
    dan orang berhenti percaya pada seluruh kartunya.
    """
    from app.services import stok

    fn = kode_saja(stok._bahan)
    assert "MillingProcessSource" in fn, "berat tak diambil dari sumber giling"
    assert "_kg(s.berat_kg)" in fn, "berat baris bukan berat yang masuk mesin"
    # `berat_total_kg` hanya boleh muncul di jalur proses LAMA yang memang tak
    # punya baris sumber — dan di sana ia WAJIB diberi kata "dibeli".
    assert fn.count("berat_total_kg") == 1
    assert "dibeli" in fn, "berat pembelian tak diberi nama"

    # Dan penyebut di atasnya memang berasal dari tempat yang sama.
    assert "berat_gabah_masuk_kg" in kode_saja(stok.pk_gudang1)


def test_kondisi_gabah_tak_diringkas_jadi_satu_kata():
    """"Gabah campuran" terbaca seperti nama varietas. Yang dimaksud adalah dua
    asal-usul dalam satu lot: yang datang basah lalu dikeringkan sendiri (PK
    KS) bercampur yang datang sudah kering (PK KL)."""
    from app.services import stok

    assert "campuran" not in kode_saja(stok._bahan)
    teks = TPL.read_text()
    assert 'join(" + ")' in teks, "kondisi tak disebut apa adanya"
    assert "l.kondisi" in teks


def test_rendemen_memakai_penyebut_yang_sama_dengan_seluruh_aplikasi():
    """Dua layar yang memakai penyebut berbeda akan menyebut rendemen berbeda
    untuk lot yang sama — dan yang melihatnya akan mencari sebabnya di mesin,
    bukan di catatan."""
    from app.penggilingan.gudang1.services import milling
    from app.services import stok

    assert "hitung_rendemen" in kode_saja(stok.pk_gudang1)
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


def test_batch_asal_dilipat_dan_kartunya_tertutup_rapi():
    """Rincian batch hanya muncul saat kartu dibuka — tetapi PERINGATAN tidak
    ikut dilipat: yang harus dibuka dulu untuk terbaca bukan peringatan, ia
    catatan kaki.

    Tag penutupnya ikut diperiksa karena pernah hilang: `</details>` tak
    tercetak, jadi kartu kedua bersarang di dalam kartu pertama dan seluruh
    rinciannya lenyap dari halaman tanpa satu pun galat.
    """
    teks = TPL.read_text()
    assert teks.count("details") >= 2 and "summary" in teks

    # Yang dilipat: rincian batch. Yang tidak: peringatan mesin berjalan.
    ring = teks.split('</{{ "summary"')[0]
    assert "nota--hati" in ring, "peringatan ikut terlipat"
    assert "anak__baris" not in ring, "rincian batch tidak terlipat"

    # Buka dan tutup harus berpasangan — keduanya ditulis dengan ekspresi yang
    # sama, jadi yang dijaga adalah jumlahnya.
    assert teks.count('<{{ "details"') == teks.count('</{{ "details"') == 1
    assert teks.count('<{{ "summary"') == teks.count('</{{ "summary"') == 1
