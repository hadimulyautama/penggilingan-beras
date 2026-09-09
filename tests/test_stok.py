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

AKAR = pathlib.Path(__file__).resolve().parents[1]
TPL = AKAR / "app/web/templates/stok.html"


def test_stok_tak_pernah_menerima_angka_stok_langsung():
    """Yang boleh dikoreksi HASIL GILINGNYA, bukan angka stoknya.

    Stok = hasil − dikirim − dijual. Membolehkan orang mengetik stok berarti
    membolehkan salah satu dari ketiganya dibengkokkan tanpa jejak, dan selisih
    yang ditutupi berhenti jadi pertanyaan. Jadi layar ini tak punya rute POST
    dan tak punya medan isian sendiri; ia hanya MEMBUKA aksi yang sudah ada dan
    sudah tercatat — verifikasi output — sehingga rendemen dan stok terhitung
    ulang sendiri dari satu angka, dan koreksinya bisa dibatalkan lewat List
    audit.
    """
    from app.web import layar_stok

    sumber = inspect.getsource(layar_stok)
    assert "@router.post" not in sumber, "Stok tidak boleh menerima kiriman"

    teks = TPL.read_text()
    for larangan in ("<form", "data-post", "<input"):
        assert larangan not in teks, f"{larangan} muncul di layar Stok"
    # Satu-satunya jalan tulis: membuka aksi verifikasi output. (`data-buka`
    # pada tag skrip bukan jalan tulis — ia yang MEMBUKA lembarnya kembali
    # setelah halaman dimuat ulang.)
    assert "buka=verify_output" in teks
    assert teks.count("?buka=") == 1, "ada jalan tulis kedua"


def test_koreksi_stok_hanya_untuk_admin_keatas():
    """Dan admin yang sedang memakai "Lihat sebagai operator" pun tidak: peran
    efektif yang dipakai, bukan peran aslinya — samaran yang masih memegang
    wewenangnya bukan samaran."""
    from app.web import layar_stok

    sumber = inspect.getsource(layar_stok)
    assert "boleh_ubah=akun.is_admin" in sumber, "gerbang peran tak dipakai"

    teks = TPL.read_text()
    # Tombolnya, lembarnya, DAN skripnya semua di balik gerbang yang sama —
    # tombol tersembunyi yang lembarnya tetap termuat masih bisa dibuka lewat
    # alamat.
    assert teks.count("boleh_ubah") >= 3
    assert "{% if boleh_ubah %}" in teks
    # Tak ditawarkan selama mesin masih giling: angkanya belum final di sana.
    assert "boleh_ubah and not l.berjalan" in teks


def test_tiap_lot_menyebut_pemasok_bobot_dan_tanggalnya():
    """Nama pemasok di baris atas menjawab "dari siapa"; rinciannya menjawab
    "dari siapa BERAPA" — dan begitu ada keluhan mutu, pertanyaan kedua itulah
    yang menentukan tumpukan mana yang harus ditahan."""
    from app.services import stok

    bahan = kode_saja(stok._bahan)
    assert "kode_batch" in bahan and "nama_supplier" in bahan
    assert "berat_total_kg" in bahan, "bobot bahan tak disebut"
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


def test_bahan_didaftar_satu_baris_per_batch():
    """Pemilik: "saya ingin benar-benar list" — berapa batch asalnya, dan tiap
    batch berapa bobotnya.

    Sebelumnya bahan dari satu pengeringan digabung jadi SATU baris bernama dua
    pemasok sekaligus. Hasilnya di layar: kepala berbunyi "BATCH ASAL · 1"
    sementara barisnya berbunyi "2 batch", nama pemasoknya berdempet sampai
    membungkus baris, dan bobot per batch — yang justru diminta — tak muncul.

    Beratnya berat PEMBELIAN, dan itu bukan kelalaian: `drying_lot_batches`
    tak punya kolom berat, jadi berapa kilo TIAP batch yang masuk silo setelah
    dikeringkan memang tak pernah tercatat. Karena itu jumlahnya tidak akan
    sama persis dengan "Bahan" — selisihnya susut pengeringan.
    """
    from app.services import stok

    fn = kode_saja(stok._bahan)
    assert "_kg(b.berat_total_kg)" in fn, "bobot per batch tak disebut"
    assert "berat_kg" not in fn.replace("berat_total_kg", ""), \
        "berat muatan silo dipakai lagi sebagai berat batch"
    # Satu batch tak boleh terdaftar dua kali walau muncul di dua sumber.
    assert "terlihat" in fn and "b.id in terlihat" in fn
    # Kode pengeringannya ikut disebut — itu mata rantai ke gabahnya.
    assert "DryingLotBatch" in fn, "bahan lewat pengeringan tak ditelusuri"

    teks = TPL.read_text()
    assert "Batch asal · {{ l.bahan|length }}" in teks, "jumlah batch tak disebut"
    assert "2 batch" not in teks, "baris gabungan kembali"


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


def test_rincian_batch_tak_dikecilkan_dari_ukuran_bawaan():
    """Pernah dikecilkan jadi 10,5px dan diredupkan demi "ringkas", dan yang
    didapat adalah daftar yang harus didekatkan ke mata.

    Justru rincian inilah yang dibaca saat ada keluhan mutu: nama pemasok dan
    kode batch dieja huruf per huruf, lalu dicocokkan ke karung di gudang. Yang
    boleh mengecil adalah LABELNYA, bukan isinya.
    """
    css = (AKAR / "app/web/static/app.css").read_text()
    assert "anak--kecil" not in css, "rincian batch dikecilkan lagi"
    assert "anak--kecil" not in TPL.read_text()
    # Kepalanya tetap kecil — ia label, dan label yang sebesar isinya membuat
    # keduanya berebut mata.
    kepala = css.split(".anak__kepala {")[1].split("}")[0]
    assert "9.5px" in kepala and "uppercase" in kepala


def test_rincian_menyebut_jumlah_batch_dan_bobot_masing_masing():
    """Susunan yang diminta pemilik: berapa batch asalnya, dan tiap batch
    berapa bobotnya — bukan satu angka gabungan."""
    teks = TPL.read_text()
    assert "Batch asal · {{ l.bahan|length }}" in teks, "jumlah batch tak disebut"
    assert "anak__kg" in teks and "for nama, berat, kapan in l.bahan" in teks


def test_selesai_giling_mengosongkan_SELURUH_sumber_silonya():
    """Bug yang dilihat pemilik: "kenapa kembali menjadi transit di silo kering
    setelah selesai giling?"

    `start_milling` mengisi penunjuk tunggal `proc.silo_storage_id` dengan SALAH
    SATU baris silo saja — "baris lot bila ada" — padahal satu giling boleh
    memakan beberapa baris sejak silo boleh dicampur. `finish_milling` dulu
    mengosongkan penunjuk itu saja, jadi baris lain tetap "terisi" dan silonya
    muncul kembali sebagai "Transit di silo kering": gabah yang sama ditawarkan
    untuk digiling dua kali.
    """
    from app.penggilingan.gudang1.services import milling

    fn = kode_saja(milling.finish_milling)
    assert "MillingProcessSource.silo_storage_id" in fn, "sumber tak dibaca"
    # Penunjuk tunggal hanya boleh jadi CADANGAN untuk proses lama.
    assert "if not ids and proc.silo_storage_id" in fn


def test_output_terverifikasi_menang_atas_progres_operator():
    """Giling yang ditutup tanpa operator mencatat hasilnya, lalu outputnya
    diverifikasi admin, dulu tetap berstok NOL — hilang dari layar Stok DAN tak
    bisa dikirim ke Gudang 2. Angka yang sudah diverifikasi tetapi tak dipakai
    adalah pekerjaan verifikasi yang dibuang."""
    from app.penggilingan.gudang1.services import milling

    fn = kode_saja(milling._produced_pk)
    assert "berat_output_final_kg" in fn, "angka final tak dibaca"
    # Progres tetap jadi cadangan selama proses masih jalan.
    assert "_latest_progress" in fn
    assert fn.index("berat_output_final_kg") < fn.index("_latest_progress"), \
        "progres operator masih menang atas angka final"


def test_hanya_satu_tempat_menghitung_pk_dihasilkan():
    """Dua jawaban untuk satu pertanyaan akan berselisih, dan yang salah adalah
    yang lebih jarang dibaca."""
    from app.services import transfer

    assert transfer._produced_pk is not None
    teks = (AKAR / "app/services/transfer.py").read_text()
    assert "async def _produced_pk" not in teks, "salinan kedua kembali"
    assert "import _produced_pk" in teks


def test_giling_tanpa_hasil_tercatat_tidak_disembunyikan():
    """Nol karena HABIS berbeda dari nol karena TAK DICATAT.

    "Selesai giling" tidak meminta berat PK — ia hanya menutup prosesnya. Jadi
    giling bisa ditutup tanpa satu pun angka hasil, dan lot itu dulu hilang dari
    layar Stok karena tersedianya nol. Yang hilang dari layar tidak hilang dari
    lantai gudang.
    """
    from app.services import stok

    fn = kode_saja(stok.pk_gudang1)
    assert "bd.tersedia <= 0 and (not belum)" in fn, "yang tak dicatat masih disembunyikan"
    # Rendemen TIDAK dihitung untuk yang tak dicatat: rumusnya akan menjawab
    # 0,0% dengan patuh, dan itu terbaca sebagai giling yang gagal total.
    assert "None if belum" in fn

    teks = TPL.read_text()
    assert "l.belum_dicatat" in teks
    assert "padat__nilai--kosong" in teks, "angka tak diketahui digambar sebagai nol"
    assert "belum dicatat, belum terhitung" in teks, "total tak mengaku ada yang tak terhitung"


def test_selesai_giling_menolak_tanpa_hasil_dan_tak_menyentuh_prosesnya():
    """Keputusan pemilik: "selesai giling wajib minta hasil akhir. jika tidak
    ada maka kartu kembali statusnya menjadi proses giling yang sedang
    berjalan."

    Yang membuat kartunya kembali sendiri adalah URUTAN: seluruh pemeriksaan
    terjadi SEBELUM satu pun kolom diubah. Kalau `proc.status = "selesai"`
    dipasang lebih dulu lalu ditolak, prosesnya sudah setengah tertutup di
    dalam sesi — dan yang menyelamatkannya cuma kebetulan bahwa rollback
    kebetulan terjadi.
    """
    from app.penggilingan.gudang1.services import milling

    fn = kode_saja(milling.finish_milling)
    assert "berat_akhir" in fn
    # Pemeriksaan mendahului perubahan.
    assert fn.index("Sebutkan hasil akhir") < fn.index("proc.status = 'selesai'"), \
        "status diubah sebelum hasilnya diperiksa"
    # Nol dan yang mustahil ikut ditolak: rendemen di atas 100% salah ketik.
    assert "berat_akhir <= 0" in fn
    assert "berat_akhir > masuk" in fn
    # Angkanya masuk sebagai progres kumulatif, bukan kolom baru.
    assert "MillingProgressLog" in fn

    # Dan formulirnya memang meminta angkanya.
    teks = (AKAR / "app/web/miniapp.py").read_text()
    blok = teks.split('"id": "selesai_giling"')[1].split('{"id": "hentikan_proses"')[0]
    assert '"berat_akhir"' in blok, "formulir tak meminta hasil akhir"
    assert '"Hasil akhir PK (kg)"' in blok


def test_daftar_verifikasi_memuat_yang_sudah_diverifikasi():
    """Kalau tidak, penguncian penunjuk terlepas pada koreksi KEDUA.

    Pemilik melaporkannya begini: "mengapa harus memilih lagi? harusnya
    otomatis sesuai dengan kartu yang dipilih kan" — dan menambahkan bahwa yang
    pertama sudah otomatis, yang kedua tidak.

    Rantainya: kartu Stok membuka `verify_output` dengan penunjuk terkunci;
    `aksi.js` MELEPAS kunci itu bila nilainya tak ada di daftar jarak-jauhnya
    ("barisnya sudah basi") — perlindungan yang benar untuk baris antrean yang
    kedaluwarsa. Tetapi sumbernya dulu hanya memuat yang BELUM diverifikasi,
    jadi begitu satu lot diverifikasi sekali ia lenyap dari daftar dan koreksi
    berikutnya disuguhi tarik-turun.

    Itu juga bertentangan dengan aksinya sendiri: `verify_milling_output`
    memang mendukung verifikasi ulang.
    """
    teks = (AKAR / "app/web/miniapp.py").read_text()
    fn = teks.split("async def milling_unverified")[1].split("\n@router")[0]
    assert "MillingProcess.status == \"selesai\"" in fn
    assert "~sudah" not in fn, "yang sudah diverifikasi kembali disaring keluar"
    # Yang belum diverifikasi tetap di atas.
    assert "case((sudah, 1)" in fn
    # Labelnya polos: `aksi.js` memakainya juga sebagai teks TERKUNCI.
    assert '"label": k}' in fn, "label diberi penanda; ia akan bocor ke teks terkunci"

    # Dan `aksi.js` memang melepas kunci bila tak ada padanannya — sifat yang
    # membuat sumber di atas harus lengkap.
    js = (AKAR / "app/web/static/aksi.js").read_text()
    assert "kuncinya" in js and "kotak.outerHTML" in js
