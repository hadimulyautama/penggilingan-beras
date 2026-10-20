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
#: Naik ke paket pada Tahap 2 (23 September 2026) — dipakai bersama Meja.
TPL = AKAR / "hmu_tampilan/templates/stok.html"
#: Potongan bersamanya: pemisah ribuan & blok stok karung.
TPL_MAKRO = AKAR / "hmu_tampilan/templates/_stok.html"
#: Stok karung PINDAH ke halamannya sendiri 7 Oktober 2026 — lihat bagian
#: "Blok Stok karung" di bawah.
TPL_KARUNG = AKAR / "hmu_tampilan/templates/stok_karung.html"


def _sumber_stok():
    def baca(nama, terlihat):
        if nama in terlihat:
            return ""
        terlihat.add(nama)
        teks = (TPL.parent / nama).read_text()
        anak = re.findall(r'{% include "([^"]+)"', teks)
        return teks + "\n" + "\n".join(baca(n, terlihat) for n in anak)
    return baca(TPL.name, set())


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

    teks = _sumber_stok()
    for larangan in ("<form", "data-post", "<input"):
        assert larangan not in teks, f"{larangan} muncul di layar Stok"
    # Jalan tulisnya hanya MEMBUKA aksi yang sudah ada — dan hanya tiga:
    # hasil giling, mutunya, dan pemindahan tumpukan ke silo. Ketiganya
    # menulis lewat layanan yang sudah tercatat di audit, bukan lewat borang
    # milik layar ini. (`data-buka` pada tag skrip bukan jalan tulis — ia
    # yang membuka lembarnya kembali setelah halaman dimuat ulang.)
    # Didaftar SATU PER SATU, bukan dihitung: angka 2 dulu berubah jadi 3 saat
    # "Minta lot ini" lahir (24 September 2026), lalu jadi 4 saat "Masukkan ke
    # silo" lahir (5 Oktober 2026) — dan uji yang cuma menghitung akan
    # "diperbaiki" dengan menaikkan angkanya — tanpa seorang pun membaca apa
    # yang ditambahkan.
    #
    # Keempatnya membuka aksi yang SUDAH ada dan sudah tercatat. Yang ketiga
    # (`minta_pk_g1`) tak menyentuh angka stok sama sekali: ia mencatat
    # PERMINTAAN operator Gudang 2 agar lot ini dipindah, lewat
    # `permintaan_pk` yang mengunci barisnya sendiri. Yang keempat
    # (`pindah_tumpukan_silo`) jauh lebih tua dari tombolnya di sini
    # (12 September 2026) — yang baru cuma pintunya dari kartu Stok.
    #
    # `kirim_permintaan_pk` sempat ikut di sini selama satu hari (26 September
    # 2026), ketika tangan yang memuat disangka Gudang 2 dan kartu Stok-nya
    # diberi tombol "Muat & kirim". Pemilik menjawabnya 27 September: "gudang 1
    # yang mengirim", "jika sudah disetujui". Blok ini hanya tergambar untuk
    # view POLESAN, jadi tombolnya akan berdiri di layar orang yang pintunya
    # menolak dia — dan itu dicabut, bukan disembunyikan dengan syarat baru.
    dibuka = set(re.findall(r"[?&](?:amp;)?buka=([a-z_0-9]+)", teks))
    assert dibuka == {"verify_output", "qc_giling", "minta_pk_g1",
                      "pindah_tumpukan_silo", "qc_pk_luar"}, dibuka
    assert "kirim_permintaan_pk" not in teks, \
        "layar Stok menawarkan pengiriman kepada gudang yang tak mengirim"


def test_koreksi_stok_hanya_untuk_admin_keatas():
    """Dan admin yang sedang memakai "Lihat sebagai operator" pun tidak: peran
    efektif yang dipakai, bukan peran aslinya — samaran yang masih memegang
    wewenangnya bukan samaran."""
    from app.web import layar_stok

    sumber = inspect.getsource(layar_stok)
    assert "boleh_ubah=akun.is_admin" in sumber, "gerbang peran tak dipakai"

    teks = _sumber_stok()
    # Tombol KOREKSI-nya tetap di balik gerbang yang sama; yang berubah 26
    # September 2026 cuma lembar & skripnya, yang kini dimuat untuk siapa pun
    # yang punya tombol di halaman ini. Sebabnya cacat: sampai hari itu
    # syaratnya `boleh_ubah` saja, jadi tombol "Minta lot ini" milik operator
    # Gudang 2 tak pernah bisa membuka borangnya — menekannya hanya memuat
    # ulang /stok, dan tak ada yang menangkap `?buka=`.
    #
    # Yang dijaga sekarang: koreksi tetap milik admin, dan lembarnya tak
    # pernah termuat untuk yang tak punya tombol sama sekali (operator
    # selepan: `boleh_ubah` dan `boleh_minta` dua-duanya salah).
    assert teks.count("boleh_ubah") >= 3
    assert "{% if boleh_ubah or boleh_minta or boleh_pindah_tumpukan %}" in teks
    assert "{% if g1 and boleh_ubah and not t.berjalan %}" in teks
    # Tak ditawarkan selama mesin masih giling: angkanya belum final di sana.
    assert "boleh_ubah and not t.berjalan" in teks


def test_tiap_lot_menyebut_pemasok_bobot_dan_tanggalnya():
    """Nama pemasok di baris atas menjawab "dari siapa"; rinciannya menjawab
    "dari siapa BERAPA" — dan begitu ada keluhan mutu, pertanyaan kedua itulah
    yang menentukan tumpukan mana yang harus ditahan."""
    from app.services import stok

    # Bentuk barisnya kini di `_baris_bahan`, satu tempat yang dipakai versi
    # satuan MAUPUN versi banyak-sekaligus — dua tempat yang menyusun baris
    # yang sama akan berbeda suatu hari. Ketiganya diperiksa bersama.
    bahan = (kode_saja(stok._bahan) + kode_saja(stok._baris_bahan)
             + kode_saja(stok._bahan_banyak))
    assert "kode_batch" in bahan and "nama_supplier" in bahan
    # Bobotnya lewat `dari_batch(...).teks()`: tiga keadaan (pasti /
    # perkiraan / menunggu timbang), bukan angka mentah (QA P6).
    assert "dari_batch(b)" in bahan and "bobot.teks()" in bahan, "bobot bahan tak disebut"
    # Proses lama tanpa baris sumber tetap dijawab, lewat sumber yang sama
    # dengan HPP — dua jawaban untuk "apa isi proses ini" akan berselisih.
    assert "sumber_batch" in bahan
    assert "waktu_selesai" in kode_saja(stok.pk_gudang1), "tanggal giling tak diambil"

    teks = _sumber_stok()
    assert "l.tanggal" in teks
    assert "t.bahan" in teks and "pk-detail__batch" in teks, "rincian bobot tak dirender"
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
    # Versi banyak-sekaligus tak pernah menyentuh tabel harga sama sekali.
    assert "harga" not in kode_saja(stok._bahan_banyak).lower()
    for uang in ("harga_per_kg", "hpp", "rupiah"):
        assert uang not in _sumber_stok().lower(), f"{uang} bocor ke layar Stok"


def test_angka_stok_dipinjam_bukan_dihitung_ulang():
    """Dua penghitung untuk satu barang cepat atau lambat berselisih, dan yang
    salah selalu yang lebih jarang dibuka."""
    from app.services import stok

    fn = inspect.getsource(stok.pk_gudang1)
    assert "pk_breakdown_banyak" in fn
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

    fn = kode_saja(stok._bahan) + kode_saja(stok._baris_bahan)
    banyak = kode_saja(stok._bahan_banyak)
    assert "dari_batch(b)" in fn and "bobot.teks()" in fn, "bobot per batch tak disebut"
    assert "berat_kg" not in fn.replace("berat_total_kg", ""), \
        "berat muatan silo dipakai lagi sebagai berat batch"
    # Satu batch tak boleh terdaftar dua kali walau muncul di dua sumber —
    # aturan yang sama harus berlaku di KEDUA versi.
    assert "terlihat" in fn and "b.id in terlihat" in fn
    assert "terlihat" in banyak and "b.id in terlihat" in banyak
    # Kode pengeringannya ikut disebut — itu mata rantai ke gabahnya.
    assert "DryingLotBatch" in fn, "bahan lewat pengeringan tak ditelusuri"
    assert "DryingLotBatch" in banyak

    teks = _sumber_stok()
    assert "Batch gabah <span>{{ t.bahan|length }}" in teks, "jumlah batch tak disebut"
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
    teks = _sumber_stok()
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

    teks = _sumber_stok()
    assert "t.rendemen" in teks and "<dt>Rendemen</dt>" in teks, "rendemen tak disorot"


def test_lot_yang_mesinnya_masih_menyala_ditandai():
    """PK-nya sudah ada tetapi angkanya belum final — dan angka belum final
    yang terbaca final akan dipakai merencanakan kiriman."""
    from app.services import stok

    assert 'proc.status == "proses"' in inspect.getsource(stok.pk_gudang1)
    assert "Mesin masih giling. Hasil dan rendemen belum final." in _sumber_stok()


def test_batch_asal_dilipat_dan_kartunya_tertutup_rapi():
    """Rincian batch hanya muncul saat kartu dibuka — tetapi PERINGATAN tidak
    ikut dilipat: yang harus dibuka dulu untuk terbaca bukan peringatan, ia
    catatan kaki.

    Tag penutupnya ikut diperiksa karena pernah hilang: `</details>` tak
    tercetak, jadi kartu kedua bersarang di dalam kartu pertama dan seluruh
    rinciannya lenyap dari halaman tanpa satu pun galat.

    ⚠ Sampai 5 Oktober 2026 DUA kartu berlipat di sini: lot giling Gudang 1
    DAN tempat Gudang 2 (laci "Pernah masuk"). Keputusan pemilik hari itu
    membuang laci Gudang 2: kartunya kini satu per kode bahan, dan satu
    pemasukan sudah tahu asalnya sendiri — tak ada lagi yang perlu dilipat
    di sana. Jadi yang berlipat tinggal SATU, lot Gudang 1.
    """
    # Daftar sekarang menuju detail; bahan tidak lagi disembunyikan di
    # details bersarang. Batas halaman, bukan lipatan, menjaga daftar padat.
    induk = (TPL.parent / "_stok_pk_daftar.html").read_text()
    detail = (TPL.parent / "_stok_pk_detail.html").read_text()
    assert "/stok/pk/detail?gudang=g1" in induk
    batch = detail.split('class="pk-detail__panel pk-detail__batches"')[1].split("</section>")[0]
    assert "t.bahan|length" in batch and "for nama, berat, kapan in t.bahan" in batch
    assert "<details" not in batch and "<summary" not in batch
    assert "Mesin masih giling. Hasil dan rendemen belum final." in detail


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
    teks = _sumber_stok()
    assert "t.lama" in teks and "t.tanggal" in teks
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
    css = (AKAR / "hmu_tampilan/static/app.css").read_text()
    assert "anak--kecil" not in css, "rincian batch dikecilkan lagi"
    assert "anak--kecil" not in _sumber_stok()
    # Kepalanya tetap LEBIH KECIL daripada isinya — ia label, dan label yang
    # sebesar isinya membuat keduanya berebut mata.
    #
    # Angkanya bukan lagi 9,5px: sejak UI-04 tak ada teks di bawah 13px sama
    # sekali. QA menghitung 24–41 potong teks di bawah 13px per layar, dan
    # layar ini dibaca sambil berdiri, kadang di bawah matahari. Yang dijaga
    # uji ini tetap sama — hierarkinya — bukan angka yang kebetulan dipakai
    # saat ia ditulis.
    import re

    def ukuran(blok: str) -> float:
        m = re.search(r"font-size: *([\d.]+)px", blok)
        return float(m.group(1)) if m else 0.0

    # Split pada awal baris, bukan substring polos — sejak blok ".anak__kelompok
    # .anak__kepala {" (kartu penyosohan bergrup, 11 Oktober 2026) selektor itu
    # juga MENGANDUNG teks ".anak__kepala {" di tengah barisnya, dan ia datang
    # lebih dulu dalam berkas. Tanpa penjagaan ini uji membaca blok yang salah.
    kepala = css.split("\n.anak__kepala {")[1].split("}")[0]
    isi = css.split(".anak__kg {")[1].split("}")[0] if ".anak__kg {" in css else ""
    assert "uppercase" in kepala
    assert ukuran(kepala) >= 13, "label turun di bawah 13px lagi"
    if isi:
        assert ukuran(kepala) <= ukuran(isi), "label sebesar isinya"


def test_rincian_menyebut_jumlah_batch_dan_bobot_masing_masing():
    """Susunan yang diminta pemilik: berapa batch asalnya, dan tiap batch
    berapa bobotnya — bukan satu angka gabungan."""
    teks = _sumber_stok()
    assert "Batch gabah <span>{{ t.bahan|length }}" in teks, "jumlah batch tak disebut"
    assert "pk-detail__batch" in teks and "for nama, berat, kapan in t.bahan" in teks


def test_selesai_giling_menunggu_sisa_dan_tidak_mengosongkan_silo():
    from app.penggilingan.gudang1.services import milling
    fn = kode_saja(milling.finish_milling)
    assert "MillingProcessSource.milling_process_id == proc.id" in fn
    assert "berat_akhir_kg is None" in fn
    assert 'st.status = "kosong"' not in fn
    assert 'silo.status = "kosong"' not in fn


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

    teks = _sumber_stok()
    assert "l.belum_dicatat" in teks
    assert "Belum ditimbang final" in teks and "<strong>—</strong>" in teks
    assert "hasil belum dicatat" in teks and "Berat tersedia belum masuk hitungan stok" in teks


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
    # Nol dan yang mustahil ikut ditolak: rendemen 100% ATAU LEBIH salah
    # ketik — `>=`, bukan `>` (keputusan pemilik 5 Oktober 2026: sekam
    # selalu terbuang, jadi tepat 100% sama mustahilnya dengan di atasnya).
    assert "berat_akhir <= 0" in fn
    assert "berat_akhir >= masuk" in fn
    # Angkanya masuk sebagai progres kumulatif, bukan kolom baru.
    assert "MillingProgressLog" in fn

    # Dan formulirnya memang meminta angkanya.
    teks = (AKAR / "app/web/api.py").read_text()
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
    teks = (AKAR / "app/web/api.py").read_text()
    fn = teks.split("async def milling_unverified")[1].split("\n@router")[0]
    assert "MillingProcess.status == \"selesai\"" in fn
    assert "~sudah" not in fn, "yang sudah diverifikasi kembali disaring keluar"
    # Yang belum diverifikasi tetap di atas.
    assert "case((sudah, 1)" in fn
    # Labelnya polos: `aksi.js` memakainya juga sebagai teks TERKUNCI.
    assert '"label": k}' in fn, "label diberi penanda; ia akan bocor ke teks terkunci"

    # Dan `aksi.js` memang melepas kunci bila tak ada padanannya — sifat yang
    # membuat sumber di atas harus lengkap.
    js = (AKAR / "hmu_tampilan/static/aksi.js").read_text()
    assert "kuncinya" in js and "kotak.outerHTML" in js


def test_mutu_kartu_stok_memakai_rata_rata_yang_sama():
    """Kartu Stok menggambar RATA-RATA, dan rata-rata yang SAMA.

    Pagar ini semula menjaga hal lain: "ambil nilai terbaru per kolom, jangan
    baris terakhir apa adanya", sebab koreksi yang cuma menyebut butir patah
    menulis baris baru dengan kadar air kosong. Niat itu betul untuk dunia di
    mana catatan QC kedua MEMBETULKAN yang pertama.

    Dunianya berubah 24 September 2026: pemilik memutuskan mutu dicatat berulang
    selama giling berjalan dan "nanti hasilnya di rata-rata" — catatan kedua
    adalah TUSUKAN kedua, bukan koreksi. Sejak itu tombolnya dan kalimat
    balasannya menyebut rata-rata sementara kartu Stok masih menggambar nilai
    terbaru: satu lot, dua angka mutu, dua layar (temuan QA T-2). Yang dijaga
    sekarang karena itu bukan lagi "terbaru per kolom" melainkan:

      · angkanya rata-rata, dan
      · hitungannya SATU — dipinjam dari `milling.qc_rata_banyak`, tempat
        rata-rata PER KOLOM atas baris yang mengisi kolom itu sudah diuji.

    Dua tempat yang menghitung rata-rata sendiri-sendiri akan berselisih, dan
    yang salah adalah yang lebih jarang dibaca.
    """
    from app.services import stok

    fn = kode_saja(stok._mutu_banyak) + kode_saja(stok._mutu)
    assert "qc_rata_banyak" in fn, "kartu Stok menghitung rata-ratanya sendiri"
    # Tak boleh ada lagi kueri log sendiri di sini: kueri sendiri adalah cara
    # rata-rata kedua lahir tanpa ada yang menyadarinya.
    assert "MillingQcLog" not in fn, "masih membaca log sendiri, bukan lewat qc_rata_banyak"
    # Labelnya dibaca dari `QcRata`, bukan dari kolom tabelnya — medan di sana
    # bernama `broken`/`susut`, bukan `broken_persen`/`susut_persen`.
    kolom = dict(stok._KOLOM_MUTU)
    assert set(kolom.values()) == {"kadar_air", "broken", "susut"}
    # Kolom yang belum pernah diisi dilewati, bukan digambar sebagai 0%.
    assert "if v is not None" in kode_saja(stok._mutu_dari)

    # Mutu ada di KARTU UTAMA, bukan di dalam laci: ia yang menentukan PK ini
    # masuk kelas apa dan laku berapa, dan yang harus dibuka dulu untuk terbaca
    # akan dianggap tak ada.
    teks = _sumber_stok()
    ring = teks.split('</{{ "summary"')[0]
    assert "l.mutu" in ring, "mutu terlipat ke dalam laci"
    assert "belum dinilai" in ring, "layar diam soal mutu terbaca seolah mutunya baik"


def test_daftar_qc_memuat_yang_sudah_dinilai():
    """Jebakan yang sama dengan daftar verifikasi output: sumber yang menyaring
    keluar lot yang sudah punya QC menutup koreksi, DAN melepas penguncian
    penunjuk saat kartu Stok membukanya untuk kedua kalinya."""
    teks = (AKAR / "app/web/api.py").read_text()
    fn = teks.split("async def milling_noqc")[1].split("\n@router")[0]
    assert "not_in" not in fn, "yang sudah punya QC kembali disaring keluar"
    # Urutannya: yang SEDANG BERJALAN di atas (di situlah orangnya berdiri saat
    # mencatat — keputusan pemilik 24 September 2026), lalu yang selesai tetapi
    # belum dinilai, lalu sisanya. Dulu cuma dua golongan, sebab daftar ini
    # cuma memuat yang sudah selesai.
    assert 'MillingProcess.status.in_(("proses", "selesai"))' in fn, \
        "giling yang sedang berjalan tak lagi bisa dinilai mutunya"
    assert "case((jalan, 0), (ada_qc, 2), else_=1)" in fn, "urutannya berubah"
    # Labelnya kini menyebut keadaan & jumlah catatan. Itu AMAN untuk penguncian
    # penunjuk dari kartu: `aksi.js` mencocokkan `value`, bukan `label` — dan
    # nilainya tetap kode prosesnya apa adanya.
    assert '"value": k,' in fn, "nilai bukan lagi kode proses apa adanya"


def test_hasil_dan_mutu_punya_tombolnya_masing_masing():
    """Berat hasil dan kadar air datang dari dua penimbangan yang berbeda,
    sering pada waktu yang berbeda pula. Satu borang berisi keduanya memaksa
    orang mengisi yang belum ia punya."""
    teks = _sumber_stok()
    assert "buka=verify_output" in teks and "buka=qc_giling" in teks
    # Namanya ikut keadaan: mencatat pertama kali bukan mengoreksi.
    assert '"Catat QC berikutnya" if t.mutu else "Catat QC"' in teks
    assert '"Catat hasil giling" if t.belum_dicatat else "Perbaiki hasil giling"' in teks


def test_fitur_mutu_bisa_dimatikan_seluruhnya():
    """Keputusan pemilik: mutu jadi fitur yang bisa dinyalakan/dimatikan —
    "dari input QC sampai menunjukkan mutu".

    Setengah mati adalah yang terburuk: layar yang masih menagih QC sementara
    borangnya tak ada mengajari orang mengabaikan tagihan. Jadi yang dijaga di
    sini adalah KELENGKAPANNYA — katalog aksi, rutenya, sumber daftarnya, kartu
    kerja meja, dan baris mutu di kartu Stok.
    """
    from app.services import setelan

    # Bawaannya MENYALA: pabrik yang sudah memakai QC tak boleh kehilangan
    # layarnya hanya karena setelan baru ditambahkan.
    fn = kode_saja(setelan.fitur_mutu)
    assert "n != '0'" in fn, "bawaannya tidak menyala"

    mini = (AKAR / "app/web/api.py").read_text()
    assert 'AKSI_MUTU = {"qc_giling", "qc_pk_luar", "qc_gabah_basah", "qc_gabah_kering"}' in mini
    assert 'a["id"] not in (*AKSI_MUTU, "qc_gabah_tutup")' in mini, "katalog tak disaring"
    # Disembunyikan SAJA tidak cukup: alamatnya bisa diketik, dan lembar yang
    # masih terbuka di layar orang lain masih bisa mengirim.
    # Pratinjau penutupan QC juga membaca mutu, sehingga memakai pagar yang sama.
    assert mini.count("await _wajib_mutu()") == 9, "ada rute mutu tanpa penjaga"

    jalan = (AKAR / "app/services/berjalan.py").read_text()
    assert "if mutu_aktif else 1" in jalan, "kartu QC giling tak ikut padam"
    assert "if await fitur_mutu(db) else []" in jalan, "kartu QC PK luar tak ikut padam"
    # Impornya ada di FUNGSI yang memakainya — pernah tidak, dan /keputusan
    # menjawab 500 sementara seluruh tes tetap hijau. Tiga sejak 24 September
    # 2026: `untuk_gudang1` ikut membacanya, karena kartu giling yang sedang
    # berjalan kini menawarkan "Catat mutu sekarang" dan menyebut rata-ratanya —
    # keduanya harus ikut padam saat pencatatan mutu dimatikan.
    assert jalan.count("from app.services.setelan import fitur_mutu") == 3
    assert "if (boleh_qc and qc_aktif) else []" in jalan, \
        "tombol QC di kartu giling tak ikut padam / tak bergerbang peran"

    teks = _sumber_stok()
    assert "{% if mutu_aktif %}" in teks, "baris mutu di kartu Stok tak ikut padam"


# ══════════════════════════════════════════════════════════════════════
# Blok Stok karung — pindah ke halaman sendiri (`/stok-karung`) 7 Oktober
# 2026, keputusan pemilik: karung butuh stok terpisah per pemilik, dan itu
# tak muat sebagai blok tanpa pemilik di halaman ini. Lihat
# `layar_produk.halaman_stok_karung`/`tests/test_gudang2_operator.py` untuk
# siapa-melihat-apa (sekarang gerbang RUTE, bukan helper `_karung` yang
# sudah dihapus) dan `tests/pg/test_stok_karung_http.py` untuk gerbangnya
# lewat HTTP sungguhan.
# ══════════════════════════════════════════════════════════════════════

_KARUNG = [
    {"gudang": "Gudang 2", "kode": "laminasi", "nama": "Karung Laminasi",
     "merk": "Cap Padi Emas", "ukuran": 5, "lembar": 1840, "menipis": False},
    {"gudang": "Gudang 1", "kode": "karung_pk", "nama": "Karung PK",
     "merk": None, "ukuran": 50, "lembar": 90, "menipis": True},
]


def test_stok_karung_filter_gudang1_tetap_ada_di_rute():
    """Operator Gudang 2 SAJA (bukan admin ke atas) tak melihat baris
    "Gudang 1" (karung PK) — pola `_karung()` lama, dipertahankan persis
    sesudah pindah ke `halaman_stok_karung`."""
    from app.web import layar_produk

    kode = inspect.getsource(layar_produk.halaman_stok_karung)
    assert 'b["gudang"] != "Gudang 1" or gudang1(view)' in kode


def test_stok_karung_tak_menyebut_uang():
    """Bloknya dibaca operator, dan operator tak melihat angka uang. Satuan
    yang ditanyakan orang saat melihat tumpukan karung memang lembar.

    Yang dibaca hanya bagian yang DIGAMBAR — mulai dari `{% if karung %}` —
    bukan komentar di atasnya. Catatan "tanpa HARGA" memang menyebut harga,
    dan uji yang menghitung kata di dalam komentar melarang orang menjelaskan
    keputusannya.
    """
    # Bloknya makro bersama sejak Tahap 2; halamannya sendiri memanggilnya.
    assert "st.karung_blok(karung" in TPL_KARUNG.read_text()
    isi = TPL_MAKRO.read_text()
    assert "{% if karung %}" in isi, "blok Stok karung hilang"
    blok = isi.split("{% if karung %}", 1)[1]
    tampak = re.sub(r"\{#.*?#\}", "", blok, flags=re.S)
    assert "lembar" in tampak
    # Sebagai KATA, bukan sebagai potongan huruf: "terpakai" mengandung "rp",
    # dan uji yang tak tahu batas kata akan melarang kata yang tak bersalah.
    for uang in ("Rp", "harga", "hpp", "rupiah"):
        assert not re.search(rf"\b{uang}\b", tampak, re.I), uang


def test_layar_stok_karung_menggambar_kosong_dan_isi():
    """LAYARNYA, bukan cuma datanya: `stok_karung.html` dirender langsung
    (gerbang peran sudah pindah ke rute, diuji lewat HTTP di
    `tests/pg/test_stok_karung_http.py` — di sini murni markup)."""
    from app.web.tampilan import templates

    def gambar(karung: list[dict], *, boleh_pindah: bool) -> str:
        return templates.get_template("stok_karung.html").render(
            request=None, akun=None, layar="stok_karung", VIEW="admin",
            LIHAT_SEBAGAI=None, PERAN_ASLI="admin", CSRF="c", TERIK=False,
            MENUNGGU=0, BERJALAN=0, KEPUTUSAN=0, MODE_UJI=False, kembali=None,
            lama=lambda s: "", FASE={}, buka="", nilai="",
            karung=karung, BOLEH_PINDAH=boleh_pindah)

    kosong = gambar([], boleh_pindah=False)
    assert "Belum ada stok kemasan" in kosong
    assert "Karung Laminasi" not in kosong

    isi = gambar(_KARUNG, boleh_pindah=True)
    assert "Karung Laminasi" in isi and "Karung PK" in isi
    assert "Pindah kepemilikan" in isi, "boleh_pindah=True harus menggambar tombolnya"

    tanpa_tombol = gambar(_KARUNG, boleh_pindah=False)
    assert "Pindah kepemilikan" not in tanpa_tombol
    assert "menipis" in isi, "yang menipis tak terbaca menipis"


def test_stok_karung_satu_pemformat_bukan_dua():
    """Berkas ini pernah membawa dua makro berisi persis sama (`kg` dan
    `ribuan`) — penggandaan kecil di layar yang justru sedang disatukan."""
    # Sejak Tahap 2 pemformatnya SATU untuk ketiga app, di `_stok.html`.
    assert TPL_MAKRO.read_text().count('macro kg(n)') == 1
    from app.web.tampilan import templates
    tampil = templates.env.from_string("{% import '_stok.html' as st %}{{ st.kg(n) }}")
    assert tampil.render(n=125.25).strip() == '125,25'
    assert tampil.render(n=6500).strip() == '6.500'
    assert tampil.render(n=0).strip() == '0'
    # Yang dilarang MAKRO keduanya, bukan katanya: komentar yang menjelaskan
    # "pemisah ribuan" tak bersalah, dan uji yang menghitung kata di dalam
    # komentar melarang orang menjelaskan keputusannya.
    for berkas in (TPL, TPL_MAKRO):
        assert "macro ribuan(" not in berkas.read_text(), berkas.name
    # Dan layarnya meminjamnya, bukan menulis ulang.
    assert "{% set kg = st.kg %}" in _sumber_stok()
