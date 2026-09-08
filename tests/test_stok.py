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
import re

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


def test_layar_memakai_kelas_pk_bukan_kondisi_gabah():
    """Pemilik memutuskan layar memakai KS / KL / MIX saja.

    "basah"/"kering" adalah keadaan gabah kemarin; yang dijual dan dibicarakan
    orang adalah kelas PK-nya. Dua kosakata untuk satu hal di kartu yang sama
    memaksa pembacanya menerjemahkan, dan yang menerjemahkan sesekali salah.
    """
    from app.services import stok

    assert stok.kelas_pk(["basah"]) == "KS"
    assert stok.kelas_pk(["kering"]) == "KL"
    assert stok.kelas_pk(["basah", "kering"]) == "MIX"
    assert stok.kelas_pk(["kering", "basah"]) == "MIX", "urutan tak boleh berpengaruh"
    assert stok.kelas_pk([]) is None, "tanpa bahan, jangan mengarang kelas"

    # Komentar templat dibuang dulu: ia MENJELASKAN mengapa kata-kata itu
    # tak dipakai, dan tes yang menghukum penjelasan yang baik akan membuat
    # orang menghapus penjelasannya, bukan memperbaiki layarnya.
    teks = TPL.read_text()
    assert "l.kelas" in teks
    tampil = re.sub(r"\{#.*?#\}", "", teks, flags=re.S).lower()
    for kata in ("basah", "kering", "campuran"):
        assert kata not in tampil, f"kata '{kata}' masih muncul di layar"


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


def test_lama_dihitung_dalam_hari_sejak_giling_ditutup():
    """Stok yang diam berbulan-bulan adalah uang yang diam, dan tanggal giling
    saja tak mengatakannya — ia menuntut pembacanya menghitung sendiri sambil
    berdiri di gudang.

    Satuannya HARI, bukan jam-menit seperti kartu antrean. Antrean bertanya
    "apakah ini tertahan sekarang", dan di sana selisih dua jam berarti sesuatu.
    Stok bertanya "sudah berapa lama uang ini diam" — pada pertanyaan itu jam
    dan menit cuma kebisingan yang berubah tiap kali halaman dibuka.

    Dihitung sejak giling DITUTUP: sebelum itu PK-nya masih keluar dari mesin,
    jadi "menumpuk" belum berarti apa-apa.
    """
    import datetime as dt

    from app.database import now_local
    from app.services import stok

    kini = now_local()
    assert stok._hari(kini) == "0 hari"
    assert stok._hari(kini - dt.timedelta(hours=23)) == "0 hari", "belum genap sehari"
    assert stok._hari(kini - dt.timedelta(days=1)) == "1 hari"
    assert stok._hari(kini - dt.timedelta(days=40)) == "40 hari"
    assert stok._hari(None) == "", "tanpa waktu, jangan mengarang umur"

    fn = kode_saja(stok.pk_gudang1)
    assert "_hari(proc.waktu_selesai or proc.waktu_mulai)" in fn
    # Umurnya menempel pada kode lot di baris judul, bukan berdiri sebagai
    # pasangan label–nilai sendiri: ia keterangan tentang bendanya, dan tiga
    # keping dalam satu baris masih terbaca sekilas.
    teks = TPL.read_text()
    assert "padat__umur" in teks and "l.lama" in teks
    assert "<dt>Lama</dt>" not in teks, "umur diulang dua kali di kartu"


def test_kelas_pk_dibaca_dari_seluruh_isi_lot():
    """Bug yang diperbaiki: `pk_jenis` membaca penunjuk TUNGGAL di
    `MillingProcess` — peninggalan masa ketika satu silo hanya boleh berisi satu
    hal. Sejak silo boleh dicampur, penunjuk itu menyebut salah satu sumber dan
    mendiamkan sisanya: lot berisi gabah basah DAN kering mengaku KS saja, dan
    PK KL di dalamnya hilang dari laporan, transfer, dan catatan QC — diam-diam,
    karena "KS" adalah jawaban yang masuk akal.
    """
    from app.penggilingan.gudang1.services import milling

    fn = kode_saja(milling._source_kondisi)
    assert "sumber_batch" in fn, "isi lot tak dibaca dari sumber bersama"
    assert "drying_lot_id" not in fn, "penunjuk tunggal kembali dipakai"
    assert "purchase_batch_id" not in fn, "penunjuk tunggal kembali dipakai"

    assert milling.kelas_pk(["basah", "kering"]) == "MIX"
    assert milling.kelas_pk(["basah"]) == "KS"
    assert milling.kelas_pk([]) is None

    # Petanya SATU tempat: layar Stok meminjamnya, tidak menyalinnya.
    from app.services import stok
    assert stok.kelas_pk is milling.kelas_pk
    assert stok.KELAS_PK is milling.KELAS_PK
