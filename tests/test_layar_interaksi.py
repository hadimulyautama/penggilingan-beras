"""Uji jalan buntu di layar — kotak yang mati sesudah sekali ditekan.

Pemilik menemukannya: kartu di Antrian tunggu dan Menunggu keputusan ditekan,
lembarnya terbuka, lalu ia keluar dengan menekan area di luar — dan sesudah
itu kartu yang sama tak bisa ditekan lagi.

Sebabnya alamat yang berbohong. Kartu menaut ke `?buka=…&nilai=…`, dan
perpindahan halaman instan menolak tautan yang alamatnya sama persis dengan
alamat sekarang (kalau tidak, tiap ketukan pada layar yang sedang dibuka akan
memuat ulang halaman). Menutup lembar tidak membersihkan alamat itu, jadi
ketukan kedua ditolak — dan satu-satunya jalan keluar adalah memuat ulang
halaman, yang tak terpikir siapa pun.
"""
from __future__ import annotations

import pathlib

AKAR = pathlib.Path(__file__).resolve().parents[1]
AKSI = (AKAR / "app/web/static/aksi.js").read_text()
PINDAH = (AKAR / "app/web/static/pindah.js").read_text()
BASE = (AKAR / "app/web/templates/base.html").read_text()


def test_menutup_lembar_membersihkan_alamatnya():
    """Semua jalan keluar sama: Batal, Escape, ketukan di luar, dan simpan
    yang berhasil — keempatnya lewat `tutupLembar`."""
    assert "lupakanBuka();" in AKSI
    badan = AKSI.split("function tutupLembar()")[1].split("}")[0]
    assert "lupakanBuka()" in badan, "jalan keluar yang tak membersihkan alamat"

    fn = AKSI.split("function lupakanBuka()")[1].split("\n  }")[0]
    assert 'searchParams.delete("buka")' in fn
    assert 'searchParams.delete("nilai")' in fn
    # `replaceState`, BUKAN `pushState`: menutup lembar bukan langkah baru
    # dalam riwayat, dan tombol Kembali harus membawa orang ke layar
    # sebelumnya — bukan membuka lagi lembar yang baru saja ia tutup.
    assert "history.replaceState" in fn and "pushState" not in fn


def test_yang_sudah_dikerjakan_hilang_seketika():
    """Kartunya digambar server, jadi memuat ulang daftar aksi saja tak
    menyentuhnya. Layar yang masih menagih pekerjaan yang baru saja
    diselesaikan orangnya sendiri adalah cara tercepat membuatnya berhenti
    dipercaya."""
    assert "segarkan: function" in PINDAH
    simpan = AKSI.split("async function simpan(")[1].split("catch")[0]
    assert "PINDAH.segarkan(" in simpan
    # Kabarnya ditampilkan SESUDAH isinya ditukar — ia ikut tersapu bersama
    # isi lama kalau ditampilkan lebih dulu.
    assert 'PINDAH.segarkan(function () { kabar(pesan, "ok"); });' in simpan


def test_pintu_laci_layar_yang_sedang_dibuka_bukan_jalan_buntu():
    """Menekannya tak menghasilkan apa pun — alamatnya sama dengan alamat
    sekarang — dan lacinya menggantung terbuka."""
    assert 'laci.querySelectorAll(".pintu")' in BASE
    blok = BASE.split('laci.querySelectorAll(".pintu")')[1][:200]
    assert "buka(false)" in blok


def test_pendengar_papan_tik_tidak_menumpuk():
    """`document` tak ikut ditukar saat halaman berpindah, jadi pendengar
    yang dipasang langsung padanya bertambah satu tiap perpindahan — dan
    yang bertambah memegang elemen lama yang sudah dibuang."""
    for berkas, teks in (("aksi.js", AKSI), ("base.html", BASE)):
        keydown = teks.split('"keydown"')[0]
        assert keydown.rstrip().endswith("pasang(document,"), \
            f"{berkas}: pendengar keydown harus lewat PINDAH.pasang"


def test_setiap_kartu_membentang_di_tempat():
    """Pemilik: kotak yang ditekan harus membentang seperti laci, bukan
    melemparkan lembar melayang ke depan layar.

    Ketukan pertama yang artinya berbeda-beda di tiap kartu memaksa orang
    menebak apa yang akan terjadi sebelum menekan — dan yang menebak akan
    berhenti menekan. Jadi tiap baris yang punya tindakan wajib membawa
    `pilihan`, sekalipun isinya cuma satu.
    """
    import ast

    sumber = (AKAR / "app/services/berjalan.py").read_text()
    telanjang = []
    for simpul in ast.walk(ast.parse(sumber)):
        if not (isinstance(simpul, ast.Call)
                and getattr(simpul.func, "id", None) == "Baris"):
            continue
        kunci = {k.arg for k in simpul.keywords}
        if "aksi" in kunci and not (kunci & {"pilihan", "tombol"}):
            telanjang.append(f"baris {simpul.lineno}")
    assert not telanjang, (
        "baris ini masih melempar langsung ke lembar, bukan membentang:\n  "
        + "\n  ".join(telanjang))


def test_kartu_yang_membentang_membawa_seluruh_tindakannya():
    """Yang dibentangkan harus benar-benar bisa dikerjakan dari situ —
    membentang lalu menyuruh orang mencari tombolnya di tempat lain lebih
    buruk daripada tidak membentang sama sekali."""
    makro = (AKAR / "app/web/templates/_benda.html").read_text()
    blok = makro.split("{% elif b.pilihan %}")[1].split("{% elif")[0]
    assert "<details" in blok and "<summary>" in blok
    assert 'class="pilihan"' in blok
    assert "{{ alamat }}?buka={{ id }}" in blok


def test_antrean_dikerjakan_tanpa_lembar_melayang():
    """Pemilik: kartu antrean tak perlu mengeluarkan layar melayang lagi —
    langsung bentang dengan tombol opsinya.

    Ini pekerjaan yang paling sering dilakukan, tiap truk yang datang. Tiga
    ketukan dan satu layar yang menutupi barisnya sendiri, untuk satu
    keputusan yang cuma punya beberapa jawaban.
    """
    makro = (AKAR / "app/web/templates/_benda.html").read_text()
    blok = makro.split("{% if b.tombol %}")[1].split("{% elif")[0]
    assert "<button" in blok and "data-post=" in blok
    # Kutip TUNGGAL, wajib: `tojson` tak melolosikan kutip ganda untuk
    # atribut, jadi di dalam kutip ganda atributnya putus di karakter pertama
    # isi muatannya — dan halaman tetap tampil, cuma tombolnya tak berfungsi.
    assert "data-kirim='{{ t.data|tojson }}'" in blok
    assert "?buka=" not in blok, "tombol tujuan tak boleh menyeberang ke lembar"
    # Yang tak boleh tetap tampil berikut alasannya.
    assert "{{ t.mati or t.ket }}" in blok
    assert "disabled" in blok

    aksi = (AKAR / "app/web/static/aksi.js").read_text()
    assert 'PINDAH.pasang(document, "click"' in aksi, \
        "didelegasikan lewat PINDAH supaya tak menumpuk tiap perpindahan"
    kirim = aksi.split('[data-kirim]')[1].split("\n  });")[0]
    assert "t.disabled = false" in kirim, \
        "yang ditolak harus bisa dicoba lagi tanpa memuat ulang halaman"
    assert "PINDAH.segarkan(" in kirim, \
        "kartu yang selesai harus hilang seketika, bukan menunggu orang pergi"


def test_alasan_tujuan_dimatikan_ikut_aturan_server():
    """Kalau alasannya disusun ulang di layar, cepat atau lambat layar
    melarang yang sebenarnya boleh — atau lebih buruk, mempersilakan yang
    akan ditolak."""
    import inspect

    from app.services.berjalan import _tujuan_gabah
    from app.penggilingan.gudang1.services import drying

    sumber = inspect.getsource(_tujuan_gabah)
    # Ketiganya persis penolakan `masuk_dryer`.
    for potongan in ('d.status != "aktif"', "lot is not None",
                     'isi and isi[0] != kondisi'):
        assert potongan in sumber, potongan
    penolakan = inspect.getsource(drying.masuk_dryer)
    assert "Tidak boleh mencampur gabah basah & kering" in penolakan
    assert "kosongkan ke silo dulu" in penolakan
    # Kapasitas sengaja diserahkan ke server — pesannya sudah menyebut sisanya
    # dengan tepat, dan menebaknya di layar hanya menambah tempat yang salah.
    kode = "\n".join(b for b in sumber.split('"""')[2:])
    assert "kapasitas" not in kode.lower()


def test_penunjuk_buka_tutup_sebaris_dengan_judulnya():
    """Dulu diapungkan ke kanan, dan apungan mengikuti BARIS TERAKHIR isi
    kartu — jadi pada kartu tinggi ia melorot ke bawah, jauh dari judul yang
    sebenarnya ia jelaskan. Penanda yang meleset terbaca sebagai cacat meski
    tak ada yang bisa menyebut apa yang salah."""
    css = (AKAR / "app/web/static/app.css").read_text()
    for kelas in ("benda", "padat"):
        blok = css.split(f"details.{kelas} > summary::after {{")[1].split("}")[0]
        assert "position: absolute" in blok, kelas
        assert "float" not in blok, f"{kelas}: apungan mengikuti baris terakhir"
        assert "width: 7px" in blok, f"{kelas}: ukurannya harus sama di kedua kartu"
    # Ruang kanannya disisakan supaya bobot yang panjang tak menabraknya.
    ringkas = css.split("details.benda > summary {")[1].split("}")[0]
    assert "padding: 13px 32px 13px 14px" in ringkas


def test_sorotan_hanya_kalau_memang_ada_rekomendasi():
    """Dua tombol tersorot sekaligus bukan rekomendasi melainkan hiasan, dan
    sorotan yang muncul di mana-mana berhenti menandakan apa pun."""
    import inspect

    from app.services.berjalan import _tujuan_gabah

    sumber = inspect.getsource(_tujuan_gabah)
    assert 'utama=(kondisi == "kering" and len(silo) == 1)' in sumber
    # Gabah basah cuma punya satu tujuan sungguhan: mesin pengering.
    assert 'utama=(kondisi == "basah" and not mati)' in sumber


def test_yang_sudah_ditunjuk_kartunya_tak_ditanyakan_lagi():
    """Pemilik: "saya kan sudah klik kartu yang saya maksud, untuk apa lagi
    field pilih batch?"

    Menyuruh orang memilih hal yang sama dua kali bukan cuma satu ketukan
    terbuang — kesempatan kedua itulah tempat ia salah pilih.
    """
    assert "function nilaiBaris()" in AKSI
    blok = AKSI.split("if (f.name === namaKunci) {")[1].split("\n      }")[0]
    # Teks biasa, bukan kotak isian — dan TANPA label, karena label adalah
    # pertanyaan dan pertanyaannya sudah dijawab saat kartunya ditekan.
    assert '<p class="terkunci"' in blok
    assert '<span class="lbl">' not in blok and "<label" not in blok
    # Nilainya tetap ikut terkirim.
    assert 'input type="hidden"' in blok and 'data-name="' in blok

    # Yang dikunci hanya isian PENUNJUK — yang pertama bertipe pilihan.
    pilih = AKSI.split("var namaKunci = \"\";")[1].split("var isi =")[0]
    assert 'f0.type !== "select" && f0.type !== "remote"' in pilih


def test_kunci_dilepas_kalau_barisnya_sudah_basi():
    """Kalau nilai dari barisnya tak ada lagi di daftar server, mengirimnya
    hanya akan ditolak. Kuncinya dilepas supaya orang bisa memilih sendiri."""
    blok = AKSI.split("if (f.name === namaKunci) {", 2)[2].split("return;\n        }")[0]
    assert "kotak.outerHTML" in blok and "<select" in blok
    assert "sembunyi.remove()" in blok, "kolom tersembunyi ikut dibuang"


def test_konfirmasi_membaca_nama_bukan_kodenya():
    """Kalimat konfirmasi yang menyebut "silo:2" alih-alih "Silo B" menuntut
    orangnya menerjemahkan sendiri — persis saat ia sedang diminta
    memastikan."""
    blok = AKSI.split("function terbaca()")[1].split("\n    }")[0]
    assert 'el.type === "hidden" ? $("t_" + el.dataset.name)' in blok


def test_halaman_tidak_boleh_disimpan_peramban():
    """Aset bercap versi disimpan setahun dan ditandai `immutable`. Yang
    menentukan alamat mana yang diminta adalah HALAMANNYA — jadi halaman yang
    ikut tersimpan membuat aplikasi membeku pada versi lama, dan menutup
    aplikasi pun tak menolong."""
    import inspect

    from app import main

    sumber = inspect.getsource(main.halaman_jangan_disimpan)
    assert 'jenis.startswith("text/html")' in sumber
    assert '"no-store' in sumber
    # Asetnya TIDAK ikut dimatikan — di situlah kecepatannya berasal.
    statis = inspect.getsource(main.StatisTerCache)
    assert "immutable" in statis and "no-store" not in statis


def test_lembar_terbuka_di_layar_tempat_tombolnya_ditekan():
    """Pemilik: aksi dari Beranda tak perlu memindahkan orang ke Sedang
    berjalan — lembarnya muncul di Beranda saja.

    Menekan tombol lalu mendarat di layar lain berarti orang kehilangan
    tempatnya, dan yang baru saja ia lihat ada di layar yang ia tinggalkan.
    """
    tpl = AKAR / "app/web/templates"
    for berkas, alamat in (("beranda.html", '"/"'),
                           ("berjalan.html", '"/berjalan"'),
                           ("keputusan.html", '"/keputusan"'),
                           ("aksi.html", None)):
        teks = (tpl / berkas).read_text()
        if alamat:
            assert f"alamat={alamat}" in teks, berkas
            # Kerangka lembarnya harus ada, kalau tidak tautannya menganga.
            assert 'id="lembar"' in teks and 'id="kabar"' in teks, berkas
            assert "aksi.js" in teks and "data-buka=" in teks, berkas
        # Tak satu pun lagi melempar ke antrean.
        assert '"/aksi?buka=' not in teks, berkas

    # Dan rutenya benar-benar meneruskan `buka`/`nilai`; tanpa itu lembarnya
    # tak pernah terbuka meski tautannya benar.
    import inspect

    from app import main
    from app.web import layar_berjalan, layar_keputusan

    for fn in (main.beranda, main.halaman_aksi,
               layar_berjalan.halaman_berjalan, layar_keputusan.halaman_keputusan):
        sumber = inspect.getsource(fn)
        assert 'query_params.get("buka")' in sumber, fn.__name__
        assert 'query_params.get("nilai")' in sumber, fn.__name__
