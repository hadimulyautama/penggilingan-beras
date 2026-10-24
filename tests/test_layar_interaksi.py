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

import pytest

AKAR = pathlib.Path(__file__).resolve().parents[1]
AKSI = (AKAR / "hmu_tampilan/static/aksi.js").read_text()
PINDAH = (AKAR / "hmu_tampilan/static/pindah.js").read_text()
BASE = (AKAR / "hmu_tampilan/templates/base.html").read_text()


def test_menutup_lembar_membersihkan_alamatnya():
    """Semua jalan keluar sama: Batal, Escape, ketukan di luar, dan simpan
    yang berhasil — keempatnya lewat `tutupLembar`."""
    assert "lupakanBuka();" in AKSI
    # Diiris sampai penutup fungsinya, bukan sampai "}" PERTAMA: badan
    # fungsinya kini memuat `if (...) { ... }` di dalamnya, dan irisan yang
    # berhenti di kurung dalam melewatkan justru baris yang dicari.
    badan = AKSI.split("function tutupLembar(paksa)")[1].split("\n  }")[0]
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
    # Dua form hasil berbagi lifecycle; semantik kumulatif tetap di layanan masing-masing.
    assert 'PINDAH.segarkan(kabarHasil);' in simpan
    assert 'kabar(utama, "ok", !!formHasil)' in simpan


def test_pintu_laci_layar_yang_sedang_dibuka_bukan_jalan_buntu():
    """Menekannya tak menghasilkan apa pun — alamatnya sama dengan alamat
    sekarang — dan lacinya menggantung terbuka."""
    assert 'laci.querySelectorAll("a.pintu, .pintu-sub__satu")' in BASE
    blok = BASE.split('laci.querySelectorAll("a.pintu, .pintu-sub__satu")')[1][:200]
    assert "buka(false)" in blok


def test_pintu_bersubmenu_tak_ikut_menutup_laci():
    """⭐ Cacat lapangan 2 Oktober 2026: "ketika saya klik menu antrian
    tunggu malah yang terbuka beranda."

    Pintu bersub-menu (Antrian tunggu) adalah `<summary class="pintu">`,
    bukan `<a>`. Penjaga di atas dulu berbunyi `laci.querySelectorAll(".pintu")`
    — pola yang menjaring KEDUANYA — sehingga menekan "Antrian tunggu" untuk
    MEMBUKA sub-menunya (toggle bawaan peramban atas `<details>`) ikut memicu
    `buka(false)` dan menutup SELURUH laci sebelum sub-menunya sempat
    terlihat. Lacinya lenyap, memperlihatkan halaman di belakangnya — dan itu
    terbaca seperti "Beranda terbuka" padahal laci itu sendiri yang tertutup.

    Pemilik: "kalau di klik kemungkinannya hanya 2. expand atau diringkas
    lagi" — dan `<details>` bawaan sudah menjawab persis itu sendirian;
    pendengar penutup laci tak boleh ikut campur pada elemen yang bukan
    tautan sungguhan.
    """
    assert 'querySelectorAll("a.pintu' in BASE
    # `a.pintu` SAJA — bukan `.pintu` apa adanya — supaya `<summary
    # class="pintu">` (dropdown, tanpa `href`) tak ikut terjaring.
    assert 'querySelectorAll(".pintu")' not in BASE
    # Sub-menunya (`.pintu-sub__satu`) TETAP `<a>` sungguhan yang menuju
    # layar lain, dan tetap wajib menutup laci.
    assert "pintu-sub__satu" in BASE.split('querySelectorAll("a.pintu')[1][:60]


def test_pendengar_papan_tik_tidak_menumpuk():
    """`document` tak ikut ditukar saat halaman berpindah, jadi pendengar
    yang dipasang langsung padanya bertambah satu tiap perpindahan — dan
    yang bertambah memegang elemen lama yang sudah dibuang.

    Yang diperiksa KHUSUS `document` — elemen LAIN (kotak `kombo` yang
    dibangun ulang tiap lembar dibuka, misalnya) boleh punya pendengar
    `keydown` miliknya sendiri: ia ikut terbuang bersama elemennya begitu
    lembarnya ditutup, tak pernah menumpuk. Dulu diperiksa dengan memotong
    teks sebelum kemunculan PERTAMA `"keydown"` — asumsi yang pecah tepat
    begitu ada pendengar `keydown` lain, bukan pada `document`, lahir
    LEBIH DULU di berkasnya.
    """
    for berkas, teks in (("aksi.js", AKSI), ("base.html", BASE)):
        assert 'document.addEventListener("keydown"' not in teks, \
            f"{berkas}: pendengar keydown pada document harus lewat PINDAH.pasang"


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


def _atribut_tag(html, nama):
    from html.parser import HTMLParser

    class Pembaca(HTMLParser):
        def __init__(self):
            super().__init__()
            self.hasil = []

        def handle_starttag(self, tag, attrs):
            if tag == nama:
                self.hasil.append(dict(attrs))

    pembaca = Pembaca()
    pembaca.feed(str(html))
    return pembaca.hasil


def _gambar_benda(baris, **opsi):
    from types import SimpleNamespace
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(AKAR / "hmu_tampilan/templates")),
                      autoescape=True)
    env.filters["jam"] = lambda nilai, fmt="": ""
    env.globals.update(lama=lambda nilai: "", FASE={"baru": "Baru"},
                       request=SimpleNamespace(url=SimpleNamespace(path="/aksi"),
                           query_params={"grup": "gabah basah", "nilai": "nilai-lama"}))
    return str(env.get_template("_benda.html").module.blok("Uji", [baris], **opsi))


@pytest.mark.parametrize("opsi", [{}, {"listview": True}, {"tabel": True},
                                  {"tabel": "packing"}, {"rapat": True}])
def test_kartu_yang_membentang_membawa_seluruh_tindakannya(opsi):
    """Render cabang bersarang; memotong pada elif pertama hanya membaca
    ringkasan tabel dan melewatkan seluruh tombol yang sebenarnya ada."""
    from urllib.parse import urlsplit, parse_qs
    from app.services.berjalan import Baris

    html = _gambar_benda(Baris("GB-UJI-01", "Gabah uji", "Menunggu", nilai="GB-UJI-01",
        pilihan=[("selesai", "Selesai", "Tutup proses"),
                 ("jeda", "Jeda", "Hentikan sementara", "pengeringan:GB-UJI-01")]), **opsi)
    assert _atribut_tag(html, "details") and _atribut_tag(html, "summary")
    assert any(a.get("class") == "pilihan" for a in _atribut_tag(html, "div"))
    tautan = _atribut_tag(html, "a")
    assert len(tautan) == 2
    for a, aksi, nilai in zip(tautan, ("selesai", "jeda"),
                             ("GB-UJI-01", "pengeringan:GB-UJI-01")):
        assert "pilihan__satu" in a["class"].split()
        u = urlsplit(a["href"])
        assert u.path == "/aksi"
        assert parse_qs(u.query) == {"grup": ["gabah basah"], "buka": [aksi], "nilai": [nilai]}


@pytest.mark.parametrize("opsi", [{}, {"listview": True}, {"tabel": True},
                                  {"tabel": "packing"}, {"rapat": True}])
def test_antrean_dikerjakan_tanpa_lembar_melayang(opsi):
    """Tujuan langsung harus tetap lengkap pada semua bentuk kartu. JSON
    dibaca dari atribut HTML agar kutip yang putus benar-benar terdeteksi."""
    import json
    from app.services.berjalan import Baris, Tombol

    muatan = {"kode": "GB-UJI-01", "nama": "Bu Sri & O'Reilly \"uji\" <beras>"}
    html = _gambar_benda(Baris("GB-UJI-01", "Gabah uji", "Menunggu", tombol=[
        Tombol("Pengering 1", "Tersedia", "/api/actions/masuk", muatan, utama=True),
        Tombol("Pengering 2", "", "/api/actions/masuk", {"kode": "GB-UJI-02"},
               mati="Pengering penuh"),
    ]), **opsi)
    assert _atribut_tag(html, "details") and _atribut_tag(html, "summary")
    tombol = _atribut_tag(html, "button")
    assert len(tombol) == 2 and not _atribut_tag(html, "a")
    assert tombol[0]["data-post"] == "/api/actions/masuk"
    assert json.loads(tombol[0]["data-kirim"]) == muatan
    assert "disabled" not in tombol[0]
    assert "disabled" in tombol[1] and tombol[1]["aria-disabled"] == "true"
    assert json.loads(tombol[1]["data-kirim"]) == {"kode": "GB-UJI-02"}
    assert "Pengering penuh" in html

    assert 'PINDAH.pasang(document, "click"' in AKSI
    kirim = AKSI.split('[data-kirim]')[1].split("\n  });")[0]
    assert "t.disabled = false" in kirim
    assert "PINDAH.segarkan(" in kirim


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
    blok = AKSI.split("if (kunciMedan(f)) {")[1].split("\n      }")[0]
    # Teks biasa, bukan kotak isian — dan TANPA label, karena label adalah
    # pertanyaan dan pertanyaannya sudah dijawab saat kartunya ditekan.
    assert '<p class="terkunci"' in blok
    assert '<span class="lbl">' not in blok and "<label" not in blok
    # Nilainya tetap ikut terkirim.
    assert 'input type="hidden"' in blok and 'data-name="' in blok

    # Yang dikunci hanya isian PENUNJUK — yang pertama bertipe pilihan.
    pilih = AKSI.split("var namaKunci = \"\";")[1].split("var isi =")[0]
    assert 'f0.type !== "select" && f0.type !== "remote"' in pilih


def test_daftar_yang_bergantung_menunggu_induknya():
    """Medan `remote` ber-`induk` tak dimuat sebelum induknya dipilih.

    Daftar yang dimuat tanpa induk akan menawarkan SELURUH pilihan yang
    mungkin — persis kesalahan yang medan ini menggantikan: borang "Selesai
    penyosohan" menawarkan Silo A kepada orang yang menyosoh di Silo B
    (keluhan pemilik 24 September 2026 07:14).
    """
    blok = AKSI.split("function muatPilihan(")[1].split("ambil(sumber)")[0]
    assert "if (f.induk)" in blok and "nilaiMedan(f.induk)" in blok
    assert "if (!nilaiInduk) { return; }" in blok, "dimuat walau induknya kosong"
    assert "induk=" in blok, "nilai induk tak ikut ke sumbernya"

    # Nilai induk dibaca juga dari isian TERKUNCI (kolom tersembunyi) — itulah
    # jalan yang paling sering dipakai: menekan kartunya.
    nm = AKSI.split("function nilaiMedan(")[1].split("\n    }")[0]
    assert "lembar.querySelector" in nm and "data-name=" in nm

    # Induk berubah → daftar anaknya dimuat ulang. Tanpa ini medan bergantung
    # cuma benar untuk proses yang dipilih PERTAMA.
    assert 'pi.addEventListener("change"' in AKSI
    # Satu-satunya kemungkinan tak perlu dipilih orang — `f.auto_satu`
    # (11 Oktober 2026) memberi medan TANPA induk jalan yang sama, untuk
    # borang yang daftarnya memang bisa berhenti di satu pilihan sendiri.
    assert "daftar.length === 1)" in AKSI and "f.induk || f.auto_satu" in AKSI


def test_penampung_sementara_pilihan_punya_value_kosong():
    """`<option>` tanpa `value` memakai TULISANNYA sebagai nilai.

    Ditemukan di peramban sungguhan, bukan oleh uji: medan silo yang bergantung
    pada medan proses membaca "memuat…" sebagai pilihan yang sah, memuat
    daftarnya dengan induk itu, dan menerima daftar kosong — layarnya berkata
    "(belum ada)" lalu mematikan tombol Simpan, padahal orangnya belum memilih
    apa pun. Uji kontrak dan uji pg tak bisa melihatnya: keduanya tak pernah
    menanyakan `select.value` kepada peramban.
    """
    for penampung in ('"><option value="">', '<option value="">memuat…</option>'):
        assert penampung in AKSI, penampung
    # Dan tak ada penampung yang tertinggal tanpa value.
    assert "<option>memuat…" not in AKSI


def test_kunci_dilepas_kalau_barisnya_sudah_basi():
    """Kalau nilai dari barisnya tak ada lagi di daftar server, mengirimnya
    hanya akan ditolak. Kuncinya dilepas supaya orang bisa memilih sendiri."""
    blok = AKSI.split("if (kunciMedan(f)) {", 2)[2].split("return;\n        }")[0]
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
    """Formulir membuka dan kembali pada konteks daftar baru yang sama."""
    from pathlib import Path
    from app.web import layar_pekerjaan
    import inspect
    paket=Path(__file__).resolve().parents[1]/'hmu_tampilan/templates'
    for nama in ('barang_masuk.html','pekerjaan.html','barang_masuk_detail.html'):
        t=(paket/nama).read_text()
        assert 'alamat=request.url.path' in t and 'id="lembar"' in t and 'id="kabar"' in t
        assert 'nav.kaki(buka,nilai)' in t
    helper=(paket/'_kerja_navigasi.html').read_text()
    assert 'aksi.js' in helper and 'data-buka=' in helper and 'data-nilai=' in helper
    for fn in (layar_pekerjaan.halaman_pekerjaan,layar_pekerjaan.halaman_barang_masuk):
        src=inspect.getsource(fn)
        assert "query_params.get('buka'" in src and "query_params.get('nilai'" in src


def test_kabar_cukup_berhasil_atau_gagal():
    """Pemilik: "feedbacknya cukup berhasil atau gagal saja."

    Sebelumnya seluruh kalimat server ditumpahkan ke sini — hasil berikut
    peringatannya — dan hasilnya sebuah paragraf yang menutupi layar setiap
    kali orang menekan satu tombol. Yang membuatnya cukup: sejak lembar
    aksinya menutup, LAYARNYA digambar ulang, jadi apa yang terjadi sudah
    terbaca di tempat aslinya.
    """
    fn = AKSI.split("function kabar(pesan, jenis, rinci)")[1].split("\n  }")[0]
    assert '"Tersimpan"' in fn, "umpan balik umum tetap singkat"
    assert "rinci ?" in fn, "form kumulatif dapat menunjukkan jawaban total/tambahan server"
    assert "kabar__nota" not in fn, "peringatan tak lagi ditumpahkan ke sini"
    # Gagal TETAP membawa sebabnya — "Gagal" tanpa sebab tak bisa
    # ditindaklanjuti; orangnya hanya tahu harus mencoba lagi, tanpa tahu
    # apa yang harus diubah.
    assert 'jenis === "err"' in fn
    assert 'split("\\n")[0]' in fn
    assert "esc(teks)" in fn, "sebab dari server memuat nama & kode dari orang"


def test_galat_tidak_hilang_lebih_cepat_dari_yang_lain():
    """Urutannya pernah terbalik: galat — satu-satunya kabar yang
    MENGHENTIKAN pekerjaan dan menuntut tindakan — justru yang paling cepat
    hilang, 4,2 detik, sementara peringatan bertahan 11 detik."""
    fn = AKSI.split("function kabar(pesan, jenis, rinci)")[1].split("\n  }")[0]
    assert 'if (jenis !== "err")' in fn, "galat tak berumur; ia menunggu ditekan"
    # Dan bisa ditutup dengan menekannya — yang sudah membaca tak perlu menunggu.
    assert "t.onclick" in fn

    # Bentuknya pun dibedakan: pil untuk berhasil, kotak untuk gagal. Dua
    # kabar berbentuk sama tertukar di sudut mata.
    css = (AKAR / "hmu_tampilan/static/app.css").read_text()
    assert "border-radius: 999px" in css.split(".kabar {")[1].split("}")[0]
    assert "border-radius: 12px" in css.split(".kabar--err {")[1].split("}")[0]


def test_peringatan_kadar_air_menetap_di_kartu():
    """Sebaran antar titik dan selisih mesin dulu hanya muncul di kabar
    sekejap sesudah menyimpan, lalu hilang bersamanya — padahal justru
    inilah yang menerangkan mengapa kadar airnya tak kunjung turun."""
    import inspect
    import types

    from app.penggilingan.gudang1.services import drying
    from app.services.berjalan import Baris

    assert "catatan" in Baris.__dataclass_fields__
    assert "peringatan_kadar_air(log)" in inspect.getsource(
        __import__("app.services.berjalan", fromlist=["untuk_gudang1"]).untuk_gudang1)

    log = types.SimpleNamespace(
        kadar_air_tes_1=12.4, kadar_air_tes_2=22.9, kadar_air_tes_3=17.1,
        kadar_air_tes_4=18.0, kadar_air_tes_manual=17.6, kadar_air_indikator=20)
    pesan = drying.peringatan_kadar_air(log)
    assert len(pesan) == 2
    assert "Sebaran 10.5%" in pesan[0] and "belum kering merata" in pesan[0]
    assert "+2.4%" in pesan[1] and "sensor dryer" in pesan[1]

    # Yang merata & sensornya sepakat tak berkata apa-apa: angka tambahan
    # yang selalu muncul cepat jadi latar yang tak dibaca siapa pun.
    rapi = types.SimpleNamespace(
        kadar_air_tes_1=15.1, kadar_air_tes_2=15.3, kadar_air_tes_3=15.0,
        kadar_air_tes_4=15.2, kadar_air_tes_manual=15.15, kadar_air_indikator=15.2)
    assert drying.peringatan_kadar_air(rapi) == []
    assert drying.peringatan_kadar_air(None) == []


def test_ambang_peringatan_tidak_disalin():
    """Ambang yang disalin akan berselisih, dan yang berselisih membuat kartu
    berkata "merata" sementara catatannya berkata tidak."""
    import pathlib

    from app.penggilingan.gudang1.services.drying import (
        AMBANG_SEBAR, AMBANG_SELISIH_MESIN)

    assert (AMBANG_SEBAR, AMBANG_SELISIH_MESIN) == (1.5, 2.0)
    mini = (pathlib.Path(__file__).resolve().parents[1]
            / "app/web/api.py").read_text()
    assert "r.sebar >= AMBANG_SEBAR" in mini
    assert "abs(r.selisih_mesin) >= AMBANG_SELISIH_MESIN" in mini


def test_tiap_tindakan_membawa_penunjuknya_sendiri():
    """Pemilik: "ketika hentikan sementara kenapa harus masih memilih
    prosesnya? kan satu kartu satu proses."

    Memang satu kartu satu proses — tetapi tiap aksi MENAMAI proses itu
    dengan bentuknya sendiri: kadar air memakai kode lot, hentikan/lanjutkan
    memakai "pengeringan:<kode>". Satu nilai untuk semua pilihan berarti
    salah satunya tak pernah cocok dengan daftar server, kuncinya terlepas,
    dan lembarnya bertanya lagi proses mana yang dimaksud.
    """
    import inspect

    from app.services import berjalan as svc

    sumber = inspect.getsource(svc.untuk_gudang1)
    assert 'f"pengeringan:{lot.kode_lot}"' in sumber
    assert 'f"giling:{p.kode_proses}"' in sumber
    # Dan yang BUKAN hentikan/lanjutkan tetap memakai kodenya polos.
    rapat = " ".join(sumber.split())
    assert '"Perbarui kadar air", "Catat hasil ukur terbaru", lot.kode_lot' in rapat
    assert '"Periksa sisa setiap silo sebelum menutup proses", p.kode_proses' in rapat

    makro = (AKAR / "hmu_tampilan/templates/_benda.html").read_text()
    assert "{% set nl = p[3] if p|length > 3 else b.nilai %}" in makro
    assert "{% if nl %}&nilai={{ nl|urlencode }}{% endif %}" in makro


def test_kartu_tidak_menyusut_di_bawah_isinya():
    """Panel "Catatan terakhir" di List audit pecah: judulnya melayang di atas
    garis tepi dan tombolnya menimpa kartu di bawahnya.

    `.isi` kotak flex kolom, jadi tiap kartu adalah anak flex — dan
    `min-height` yang dipasang pada kartu MEMBATALKAN perlindungan bawaan
    (`min-height: auto`) yang biasanya mencegah anak menyusut di bawah tinggi
    isinya. Di halaman yang penuh, kartunya menyusut ke 56px dan
    `align-items: center` melempar isinya ke luar, atas dan bawah.
    """
    css = (AKAR / "hmu_tampilan/static/app.css").read_text()
    for kelas in ("benda", "padat"):
        blok = css.split(f".{kelas} {{")[1].split("}")[0]
        assert "flex-shrink: 0" in blok, kelas
        assert "min-height" in blok, f"{kelas}: min-height-nya yang membuat ini perlu"


def test_layar_menyegarkan_diri_saat_kembali_ke_depan():
    """Keluhan pemilik, 10 September 2026: operator mencatat sesuatu dari
    HP-nya, dan di layar pemilik tak terjadi apa-apa — ia harus MEMATIKAN
    aplikasinya dulu, baru perubahannya terlihat.

    Sebabnya bukan cache yang basi; `pindah` sudah memeriksa ulang tiap kali
    orang berpindah layar. Sebabnya lebih sederhana dan lebih buruk: tak ada
    SATU PUN pemicu penyegaran. Halaman digambar sekali saat dibuka lalu diam
    selamanya, dan aplikasi terpasang tak pernah dimuat ulang saat dibuka
    kembali dari latar belakang — ia melanjutkan DOM yang sama.

    Layar pabrik yang menunjukkan keadaan setengah jam lalu tanpa memberi tahu
    bahwa ia basi lebih buruk daripada layar kosong: yang kosong membuat orang
    bertanya, yang basi membuat orang yakin.
    """
    import pathlib

    js = (pathlib.Path(__file__).resolve().parents[1]
          / "hmu_tampilan/static/pindah.js").read_text()

    # Kembali ke depan — inilah yang menjawab keluhannya.
    assert 'addEventListener("visibilitychange"' in js
    # Dan simpanan maju-mundur peramban, yang tak memicu visibilitychange.
    assert 'addEventListener("pageshow"' in js
    # Denyut untuk telepon yang tergeletak menyala; hanya saat TERLIHAT, supaya
    # yang di latar belakang tak menghabiskan baterai maupun kuota.
    assert "setInterval" in js and 'visibilityState === "visible"' in js


def test_penyegaran_diam_tak_membuang_ketikan_orang():
    """Ia berjalan TANPA diminta, jadi ia harus tahu kapan tidak boleh
    mengganggu. Menukar isi di bawah borang yang sedang diisi berarti membuang
    ketikan orang — dan sekali itu terjadi, orang berhenti memakai borangnya.
    """
    import pathlib

    js = (pathlib.Path(__file__).resolve().parents[1]
          / "hmu_tampilan/static/pindah.js").read_text()
    diam = js[js.index("diam: function ()"):js.index("  function cabutSemua")]

    js_semua = (pathlib.Path(__file__).resolve().parents[1]
                / "hmu_tampilan/static/pindah.js").read_text()
    jaga = js_semua[js_semua.index("function bolehDiam"):
                    js_semua.index("function lembarTerbuka")]
    assert "lembarTerbuka()" in jaga, "lembar terbuka tak dijaga"
    assert "INPUT|SELECT|TEXTAREA" in jaga, "kotak isian yang dipegang tak dijaga"
    assert "disentuh" in jaga, "halaman yang sudah diketik tak dijaga"
    # Tahap C: denyut TIDAK PERNAH menukar isi — ia hanya bertanya. Satu-
    # satunya penukaran tanpa ketukan adalah layar `data-segar-sendiri`
    # (papan pantau), dan itu pun dijaga `bolehDiam()`.
    assert "ambil(" not in diam and "pasang(" not in diam
    terima = js[js.index("function terimaPenanda(j)"):js.index("function tawarkanPerubahan()")]
    assert 'data-segar-sendiri' in terima and "if (bolehDiam()) { muatPerubahan(); }" in terima
    # Posisi gulung dikembalikan saat pil diketuk — yang sedang membaca baris
    # ke-20 tak boleh dilempar ke atas.
    muat = js[js.index("function muatPerubahan()"):js.index("Kanal dorong (SSE)")]
    assert "scrollTop" in muat


def test_halaman_yang_sudah_diketik_tak_digambar_ulang():
    """Memeriksa "ada kotak yang sedang dipegang" saja TIDAK CUKUP.

    Pemilik menanyakannya pada 11 September 2026, lalu diuji di peramban:
    ketikan di borang Pengaturan HILANG, diganti nilai dari server. Urutannya
    biasa saja — orang mengetik namanya, lalu menggulir sebentar melihat
    setelan lain sehingga kotaknya kehilangan fokus; di detik itu orang lain
    mengubah sesuatu di halaman yang sama.

    Lembar aksi memang sudah aman sejak awal, dan di sanalah hampir semua
    pencatatan terjadi. Yang bocor borang BIASA: Pengaturan, ganti sandi,
    kelola pengguna. Jarang dipakai — tetapi yang hilang di sana adalah
    ketikan orang yang tak pernah diberi tahu kenapa.
    """
    import pathlib

    js = (pathlib.Path(__file__).resolve().parents[1]
          / "hmu_tampilan/static/pindah.js").read_text()

    # Penandanya dipasang dari SATU tempat, menangkap seluruh halaman.
    assert 'addEventListener("input"' in js and 'addEventListener("change"' in js
    assert "disentuh = true" in js
    # Dan direset saat halamannya memang berganti — kalau tidak, satu ketikan
    # mematikan penyegaran untuk selamanya sampai aplikasi dimatikan.
    pasang = js[js.index("function pasang"):js.index("function angkatLembar")]
    assert "disentuh = false" in pasang


# ────────── Penanda keadaan: bertanya dulu, mengunduh belakangan ──────────

def test_denyut_bertanya_dulu():
    """Denyut yang mengunduh seluruh halaman (14–26 KB) hanya untuk
    menyimpulkan "tak ada yang berubah" membakar sekitar 17 MB kuota per
    perangkat per sif — dan operator memakai kuotanya sendiri."""
    import pathlib

    js = (pathlib.Path(__file__).resolve().parents[1]
          / "hmu_tampilan/static/pindah.js").read_text()
    diam = js[js.index("diam: function ()"):js.index("  function cabutSemua")]
    assert "tanyaPenanda()" in diam
    # Denyut HANYA bertanya; halamannya tak pernah diambil olehnya (Tahap C:
    # yang mengambil adalah ketukan pil, `muatPerubahan`).
    assert "ambil(alamat)" not in diam
    muat = js[js.index("function muatPerubahan()"):js.index("Kanal dorong (SSE)")]
    assert "ambil(alamat)" in muat


def test_belum_tahu_bukan_berarti_tak_berubah():
    """`null` terjadi tepat sesudah aplikasi dibuka — dan di situlah justru
    yang paling mungkin basi, karena telepon bisa saja sejam di kantong.
    Menganggapnya "tak berubah" berarti mengulang keluhan yang sedang
    diperbaiki."""
    import pathlib

    js = (pathlib.Path(__file__).resolve().parents[1]
          / "hmu_tampilan/static/pindah.js").read_text()
    terima = js[js.index("function terimaPenanda(j)"):js.index("function tawarkanPerubahan()")]
    # `null` = belum tahu: bukan perubahan, bukan pula "tak berubah".
    assert "if (!j) { return; }" in terima
    assert "penanda !== null && n !== penanda" in terima


def test_sesi_habis_tak_memicu_muat_ulang_tanpa_henti():
    """Sesi habis menjawab halaman masuk, bukan JSON."""
    import pathlib

    js = (pathlib.Path(__file__).resolve().parents[1]
          / "hmu_tampilan/static/pindah.js").read_text()
    blok = js[js.index("function tanyaPenanda"):js.index("function bolehDiam")]
    assert "r.ok ? r.json() : null" in blok
    assert ".catch(" in blok


def test_penanda_memuat_tiket_timbang():
    """Tiket timbang dibuat aplikasi TIMBANGAN, yang menulis ke basis data
    yang sama tanpa lewat `activity_logs` milik aplikasi ini — padahal tiket
    gabah yang belum ditaut berdiri sebagai kartu di Antrian tunggu.

    Tanpa bagian kedua ini, truk yang baru masuk tak akan pernah muncul
    sendiri di layar operator; ia harus berpindah layar dulu.
    """
    import inspect

    from app.web import api

    src = inspect.getsource(api._penanda)      # satu rumus untuk /keadaan dan /aliran
    assert "ActivityLog" in src, "perubahan di aplikasi ini tak terpantau"
    assert "timbangan_transaksi" in src, "tiket timbang tak terpantau"
    # `updated_at` ikut: tiket DIUBAH saat timbang kedua, nomornya tak
    # bergerak di situ.
    assert "max(updated_at)" in src
    # Nomor yang selalu naik, bukan jam perangkat.
    assert "extract(epoch" in src


def test_tiket_gabah_baru_muncul_sendiri_di_antrean():
    """Pemilik: "jika ada tiket timbang baru, di antrian tunggu app
    operasional harus ada, jika itu gabah."

    Dua hal harus benar bersamaan, dan keduanya mudah luput satu-satu.
    Penandanya harus ikut bergerak saat aplikasi TIMBANGAN menulis tiket —
    ia tak lewat `activity_logs` milik aplikasi ini. Dan penyaringnya harus
    membuang yang BUKAN gabah: PK dan komoditas lain punya alurnya sendiri,
    dan kartu yang salah alur menuntun operator memasukkan barang ke tempat
    yang salah.

    Dibuktikan di peramban pada 11 September 2026: tiket gabah basah baru
    dimasukkan ke basis data dari luar, satu denyut dijalankan tanpa memuat
    ulang halaman, dan kartunya muncul.
    """
    import inspect

    from app.services import berjalan
    from app.web import api

    assert "timbangan_transaksi" in inspect.getsource(api._penanda)

    saring = inspect.getsource(berjalan._tiket_belum_ditaut)
    assert 'info.model != "gabah"' in saring, "yang bukan gabah tak disaring"
    # Jenisnya dibaca dari PETA JENIS, bukan ditebak dari awalan kodenya —
    # komoditas baru diam-diam dianggap gabah kering kalau ditebak.
    assert "intake_dari_jenis" in saring


# ──────── Beberapa pilihan sekaligus: giling dari beberapa silo ────────

def test_borang_mulai_giling_menerima_beberapa_silo():
    """Keputusan pemilik 24 September 2026: menggiling dari beberapa silo
    "sering", dan "hasilnya 1 lot".

    Daftarnya dari MASTER, bukan tupel huruf yang diketik di kode: silo Gudang 1
    lebih dari dua dan bisa bertambah lewat Pengaturan → Alat. Pintu yang
    memeriksa `not in ("A", "B")` menolak silo ketiga yang baru dibeli dengan
    kalimat "Pilih silo yang digiling dulu" — padahal orangnya sudah memilih.
    """
    import inspect

    from app.web import api
    from tests.bantu import kode_saja

    sumber = inspect.getsource(api)
    i = sumber.index('"id": "mulai_giling"')
    blok = sumber[i:i + 900]
    assert '"type": "remote_banyak"' in blok, "borangnya masih satu silo saja"
    assert '"source": "/api/actions/silo-siap-giling"' in blok, "daftarnya bukan dari master"

    # `kode_saja`: komentar di pintunya MENYEBUT daftar huruf yang dicabut,
    # justru supaya orang berikutnya tahu kenapa ia tak boleh kembali. Pagar
    # yang membaca komentar akan menagih kalimat itu dihapus.
    pintu = kode_saja(api.act_mulai_giling)
    assert "('A', 'B')" not in pintu and '("A", "B")' not in pintu, \
        "daftar huruf tertulis-tangan berdiri lagi"
    assert "isinstance(req.silo, str)" in pintu, "bentuk tunggal tak lagi diterima"


def test_daftar_centang_mengirim_daftar_dan_tak_mengunci_kartu():
    """Tiga sifat yang masing-masing pernah jadi jalan buntu tersendiri.

    · Nilainya dikirim sebagai DAFTAR, bahkan bila cuma satu tercentang —
      server yang menerima kadang daftar kadang teks harus menebak;
    · kartu yang membuka lembar ini MENCENTANG silonya, bukan menguncinya:
      mengunci berarti orang yang menekan kartu Silo A tak bisa menambah Silo B
      tanpa menutup borangnya dulu, dan kartu berubah jadi kandang;
    · kalimat konfirmasi memakai TULISANNYA ("Silo A · Silo B"), bukan kodenya
      ("A,B") — orang yang sedang diminta memastikan tak boleh disuruh
      menerjemahkan sendiri.
    """
    assert 'f.type === "remote_banyak"' in AKSI
    # Kunci kini juga dapat berasal dari baris kemasan (kunciMedan).
    # Urutan yang berarti adalah cabang RENDER, bukan deklarasi helpernya.
    render = AKSI.split("var isi = (a.fields || []).map")[1]
    i = render.index('f.type === "remote_banyak"')
    # Cabangnya berdiri SEBELUM cabang terkunci — itulah yang membuat kartu
    # mencentang, bukan mengunci.
    assert i < render.index("if (kunciMedan(f))"), "medan banyak ikut terkunci kartu"
    assert 'data-banyak="1"' in AKSI
    assert "String(v || \"\").split(\",\").filter(Boolean)" in AKSI, \
        "nilainya tak dikirim sebagai daftar"
    assert "el.dataset.teks || el.value" in AKSI, "konfirmasi menyebut kode, bukan tulisan"
    # Yang hilang dari daftar tak boleh tetap terkirim: silonya bisa saja baru
    # diambil proses lain sementara lembarnya terbuka.
    assert "sinkron();" in AKSI


def test_centang_dipulihkan_lewat_kode_bukan_tulisannya():
    """Ditemukan di PERAMBAN, bukan di uji — dan itulah sebabnya ia dijaga.

    Pemulihan sesudah "Kembali" dari layar konfirmasi dulu mencocokkan TULISAN
    pilihannya. Tulisan itu sendiri memuat "·" ("Silo A · 10.000 kg"), yaitu
    pemisah yang sama dengan yang menggabungkan beberapa pilihan jadi satu
    baris — jadi pemecahannya menghasilkan potongan yang tak cocok dengan apa
    pun, dan pilihan kedua dan seterusnya LENYAP tanpa kabar. Orang yang cuma
    ingin memeriksa sekali lagi kehilangan separuh jawabannya, dan tak ada
    satu pun tanda bahwa itu terjadi.
    """
    assert 'v["kode:" + el.dataset.name] = el.value' in AKSI, \
        "kode pilihan tak dititipkan; pemulihan kembali menebak dari tulisan"
    assert 'semula["kode:" + el.dataset.name]' in AKSI
    assert '(simpanan.dataset.pulih || "").split(",")' in AKSI, \
        "pemulihan memecah dengan pemisah yang bisa muncul di dalam tulisannya"
    # Kunci bertanda titik dua supaya tak pernah cocok dengan lubang {nama} di
    # kalimat konfirmasi, yang hanya menerima \w.
    assert "replace(/\\{(\\w+)\\}/g" in AKSI


def test_kartu_mencentang_medan_banyak_bukan_melewatinya():
    """Penguncian dari kartu memeriksa TIPE medannya. Medan baru yang tak
    disebut di situ akan dilewati diam-diam: kartu Silo A membuka borang yang
    tak mencentang apa pun, dan orang harus memilih ulang benda yang baru saja
    ia tekan — kesempatan kedua untuk salah pilih yang penguncian ini justru
    ada untuk menutupnya."""
    assert 'f0.type !== "remote_banyak"' in AKSI


def test_borang_penyosohan_juga_menerima_beberapa_silo():
    """Permintaan pemilik 24 September 2026: penyosohan pun boleh lebih dari
    satu silo, lewat borangnya.

    Layanannya (`mulai_penyosohan`) sudah menerima berapa pun silo sejak 12
    September. Yang mengurungnya jadi tiga kemungkinan adalah daftar pilihan
    "A / B / A+B" di borang dan petanya di pintu — dua tempat yang menyebut
    nama silo yang diketik seseorang bertahun lalu, dan takkan pernah menyebut
    silo yang ditambahkan lewat Pengaturan → Alat.
    """
    import inspect

    from app.web import api
    from tests.bantu import kode_saja

    sumber = inspect.getsource(api)
    i = sumber.index('"id": "mulai_penyosohan"')
    blok = sumber[i:i + 900]
    assert '"type": "remote_banyak"' in blok, "borangnya masih satu pilihan"
    assert '"source": "/api/actions/silo-bahan-g2"' in blok, "daftarnya bukan dari master"
    assert "SILO_BAHAN" not in sumber, "tupel huruf lamanya masih berdiri"

    pintu = kode_saja(api.act_mulai_penyosohan)
    assert '"AB"' not in pintu, "peta A/B/AB berdiri lagi di pintu"
    assert "isinstance(req.silo, str)" in pintu, "bentuk tunggal dari kartu tak diterima"

    # Daftarnya menyaring persis seperti pagar layanannya: ada isinya, dan tak
    # sedang dipakai proses yang berjalan.
    daftar = kode_saja(api.silo_bahan_g2)
    assert "hitung_stok_silo" in daftar and "PolishingProcess.status" in daftar


def test_laci_bisa_digulir_sampai_pintu_terakhir():
    """Laporan pemilik 28 September 2026, dengan fotonya: laci tak bisa digulir,
    dan "Kabar" terpotong di tepi bawah layar — berikut List audit, Pengaturan,
    dan tombol Keluar di bawahnya.

    Sebabnya bukan tab Kabar yang lahir 26 September; ia cuma yang membuat
    daftarnya melewati tinggi layar pada telepon 6 inci. Cacatnya sudah ada
    sejak lacinya lahir: `.laci__isi` berjangkar `inset: 0 auto 0 0` — tingginya
    persis setinggi layar — dan tak satu pun anaknya boleh menggulir.

    Pagar ini menagih KEDUANYA, dan yang kedua yang paling mudah ketinggalan:
    anak sebuah kotak flex bawaannya `min-height: auto`, yang menolak menyusut
    di bawah tinggi isinya. Tanpa `min-height: 0`, `overflow-y: auto`
    sendirian tak pernah punya kesempatan bekerja — kotaknya keburu melar, dan
    laci tetap terpotong seperti di foto itu.
    """
    css = (AKAR / "hmu_tampilan/static/app.css").read_text()
    i = css.index(".laci__daftar")
    blok = css[i:css.index("}", i)]
    assert "overflow-y: auto" in blok, "daftar pintu tak bisa digulir"
    assert "min-height: 0" in blok, \
        "overflow-y tanpa min-height:0 — kotak flex menolak menyusut"

    # Dan yang di luar daftar TIDAK ikut menggulir: nama pemakai dan tombol
    # Keluar harus selalu terlihat — yang satu supaya ia tahu sedang masuk
    # sebagai siapa, yang satu supaya ia bisa keluar tanpa menggulir.
    for bagian in (".laci__kepala", ".laci__kaki"):
        j = css.index(bagian + " {")
        assert "flex-shrink: 0" in css[j:css.index("}", j)], \
            f"{bagian} ikut menyusut saat daftarnya panjang"


def test_jumlah_pintu_laci_melewati_satu_layar():
    """Pagar di atas menjaga aturannya; yang ini menjaga ALASANNYA tetap nyata.

    Kalau kelak pintunya tinggal empat, `overflow-y` jadi tak terbukti apa pun
    dan pagar di atas lulus tanpa menguji apa-apa. Dua belas pintu pada telepon
    6 inci sudah melewati satu layar — itu yang membuat foto pemilik mungkin.
    """
    from app.web.nav import TAB

    assert len(TAB) >= 10, (
        f"tinggal {len(TAB)} pintu — periksa apakah laci masih bisa melebihi "
        "satu layar; kalau tidak, pagar penggulirnya tak lagi menguji apa pun")


def test_laci_menggambar_nama_pintu_saja():
    """Permintaan pemilik 28 September 2026: "sidebar cukup nama halamannya
    saja", "deskripsi tambahan tidak perlu" — dan, pada pesan yang sama,
    "angka disampingnya tetap dipertahankan".

    Dua tuntutan sekaligus, jadi dijaga dua-duanya: keterangan hilang, lencana
    tinggal. Pagar yang cuma menagih yang pertama akan meluluskan laci yang
    ikut kehilangan angkanya.
    """
    tpl = (AKAR / "hmu_tampilan/templates/base.html").read_text()
    css = (AKAR / "hmu_tampilan/static/app.css").read_text()

    assert "pintu__nama" in tpl
    assert "pintu__ket" not in tpl, "keterangan pintu masih digambar"
    assert "pintu__ket" not in css, "aturan gaya keterangan tertinggal"
    # Angkanya tetap — keempat lencananya, masing-masing pada pintunya.
    for lencana in ("MENUNGGU", "BERJALAN", "KEPUTUSAN", "MUTU", "PRODUK", "KABAR"):
        assert f"and {lencana} %}}" in tpl, f"lencana {lencana} hilang dari laci"


def test_baris_laci_tak_saling_menimpa_saat_isinya_panjang():
    """Baris laci memakai tinggi ISINYA, bukan bagian dari tinggi kotaknya.

    Kotak grid yang tingginya ditentukan induknya (di sini `flex: 1 1 auto`)
    boleh membagi tingginya ke baris-barisnya; baris yang tertekan di bawah
    tinggi isinya melimpahkan isinya ke baris berikutnya. `align-content:
    start` menutup kemungkinan itu.

    ⚠ JUJUR TENTANG APA YANG TERBUKTI, sebab pagar yang mengaku lebih daripada
    yang ia ketahui menyesatkan pembaca berikutnya: pemilik memfoto baris yang
    saling menimpa pada VERSI 157, dan yang MENYEMBUHKANNYA adalah keterangan
    dua baris yang dicabut atas permintaannya. Tumpang-tindihnya tak berhasil
    ditirukan di harness, dengan maupun tanpa `align-content`. Pagar ini
    menjaga bentuk yang benar untuk daftar yang menggulir — bukan memberi
    kesaksian bahwa ia obat foto itu.
    """
    css = (AKAR / "hmu_tampilan/static/app.css").read_text()
    i = css.index(".laci__daftar")
    blok = css[i:css.index("}", i)]
    assert "align-content: start" in blok, \
        "baris laci bisa ditekan di bawah tinggi isinya, lalu saling menimpa"


def test_nota_hati_selalu_punya_dua_anak():
    """`.nota--hati` adalah grid DUA KOLOM — `15px 1fr`, kolom pertama untuk
    ikon. Teks polos yang ditaruh sebagai anak tunggal jatuh ke kolom selebar
    15px itu, lalu patah SATU KATA PER BARIS.

    Difoto pemilik 28 September 2026 di layar Kabar: "informasi di kartu
    pertama jelek sekali". Dua templat kena sekaligus, dan yang kedua
    (`stok_produk.html`) belum pernah terlihat siapa pun — ia cuma muncul
    ketika ada mesin sosoh yang sedang menyala.

    Itu sebabnya pagar ini menyapu SELURUH templat paket, bukan cuma yang
    difoto: kelas dua-kolom yang dipakai seperti kelas biasa tidak melahirkan
    galat apa pun — ia cuma jelek, di layar yang jarang dibuka.
    """
    import re

    akar = AKAR / "hmu_tampilan/templates"
    salah = []
    for berkas in sorted(akar.glob("*.html")):
        teks = berkas.read_text()
        for m in re.finditer(r'<div class="nota nota--hati">', teks):
            # Isi blok sampai penutupnya — cukup, sebab blok ini tak pernah
            # memuat <div> lain di dalamnya.
            akhir = teks.index("</div>", m.end())
            isi = teks[m.end():akhir]
            if isi.count("<span") < 2:
                baris = teks[:m.start()].count("\n") + 1
                salah.append(f"{berkas.name}:{baris}")
    assert not salah, (
        "`.nota--hati` dipakai tanpa dua anak — teksnya akan patah satu kata "
        "per baris di kolom ikon selebar 15px: " + ", ".join(salah))


def test_tiap_fase_punya_kata_dan_warnanya():
    """Kunci fase memikul DUA tugas: KATA kepingannya dan WARNA kartunya.
    Yang punya satu tanpa yang lain gagal diam-diam.

    Ini ketiga kalinya cacat yang sama difoto pemilik:

      24 Sep · kartu "Penyosohan" berkeping "Proses giling" — Gudang 2
               meminjam fase Gudang 1 demi warnanya, ikut membawa katanya;
      28 Sep · kartu "Kirim PK ke Gudang 2" berkeping "PROSES GILING" —
               kelima kartu rantai permintaan meminjam "giling", alasan sama.

    Dua-duanya lahir dari peminjaman yang masuk akal (warnanya memang harus
    sama) dan berakhir pada kepingan yang membantah judul kartunya sendiri.
    Kepingan yang berbohong lebih buruk daripada kepingan yang tak ada, sebab
    ia dipercaya.

    Maka yang dijaga ATURANNYA, bukan kelima kartu itu: setiap fase yang
    dipakai `berjalan.py` wajib punya katanya di `FASE` DAN kelas warnanya di
    `app.css` — untuk `.benda` maupun `.padat`, sebab satu kartu digambar
    dengan kerangka yang berbeda di layar yang berbeda.
    """
    import re

    from app.web.tampilan import templates

    kata = templates.env.globals["FASE"]
    css = (AKAR / "hmu_tampilan/static/app.css").read_text()
    sumber = (AKAR / "app/services/berjalan.py").read_text()

    dipakai = set(re.findall(r'fase="([a-z0-9_]+)"', sumber))
    # `_FASE_BATCH` memetakan status batch → fase; nilainya ikut dipakai.
    blok = sumber[sumber.index("_FASE_BATCH = {"):]
    dipakai |= set(re.findall(r':\s*"([a-z0-9_]+)"', blok[:blok.index("}")]))

    tanpa_kata = sorted(f for f in dipakai if f not in kata)
    assert not tanpa_kata, (
        "fase tanpa kata di FASE — kepingannya tampil kosong: " + ", ".join(tanpa_kata))

    tanpa_warna = sorted(
        f for f in dipakai
        if f".benda--{f} " not in css or f".padat--{f} " not in css)
    assert not tanpa_warna, (
        "fase tanpa kelas warna — kartunya tampil polos: " + ", ".join(tanpa_warna))


def test_tiap_pintu_laci_punya_ikonnya_sendiri():
    """Ikon yang dipakai beberapa pintu berhenti menjadi ikon.

    Sampai 29 September 2026 ikon laci adalah rantai `if/elif` di `base.html`
    yang berakhir `{% else %}⚙`. Akibatnya LIMA pintu memakai gerigi yang sama —
    Catat pekerjaan lain, Stok Produk, Barang Keluar, List audit, Pengaturan.
    Pemilik mengeluhkannya sebagai "ikonnya salah"; yang salah bukan bentuknya
    melainkan bahwa mata tak bisa membedakan apa pun dengannya.

    Dua arah yang dijaga, dan yang kedua yang akan patah lebih dulu: pintu BARU
    yang lupa membawa ikonnya jatuh ke cadangan `⚙` di templat — tanpa galat,
    tanpa kotak kosong, cuma diam-diam berbagi gerigi dengan Pengaturan lagi.
    """
    from app.web.nav import TAB

    kurang = [t[0] for t in TAB if len(t) < 6 or not (t[5] or "").strip()]
    assert not kurang, f"pintu tanpa ikon — akan memakai ⚙ bersama: {kurang}"

    ikon = {}
    for t in TAB:
        ikon.setdefault(t[5], []).append(t[0])
    kembar = {i: p for i, p in ikon.items() if len(p) > 1}
    assert not kembar, f"ikon dipakai lebih dari satu pintu: {kembar}"


def test_ikon_laci_bukan_emoji_dan_bukan_huruf_biasa():
    """Emoji tampil BERWARNA dan bentuknya berbeda di tiap merek HP.

    Dua belas ikon monokrom ditambah satu emoji terbaca seperti kesalahan, dan
    yang menambahkannya tak akan melihatnya di peramban komputernya sendiri —
    di sana emoji ikut monokrom pada sebagian sistem.

    Yang diizinkan blok yang sudah TERBUKTI tampil di app ini: Geometric Shapes
    (U+25xx), Arrows (U+21xx), Misc Technical (U+23xx), Misc Symbols (U+26xx),
    Dingbats (U+27xx), dan beberapa tanda rumah/gerigi di U+2302/U+2699.
    """
    from app.web.nav import TAB

    salah = []
    for t in TAB:
        if t[5] in ("chart-no-axes-combined", "truck"):
            # Simbol baru dirender sebagai SVG monokrom, bukan teks nama ikon.
            assert t[0] == {"chart-no-axes-combined": "laporan_riwayat", "truck": "barang_keluar"}[t[5]]
            base = (AKAR / "hmu_tampilan/templates/base.html").read_text()
            assert 'ikon_portal(ikon)' in base
            from jinja2 import Environment, FileSystemLoader
            env = Environment(loader=FileSystemLoader(str(AKAR / "hmu_tampilan/templates")), autoescape=True)
            ikon = str(env.get_template("_ikon_portal.html").module.ikon_portal(t[5]))
            assert '<svg ' in ikon and 'stroke="currentColor"' in ikon
            assert '<path ' in ikon and '</svg>' in ikon
            continue
        for ch in (t[5] or ""):
            k = ord(ch)
            if k < 0x2000:
                salah.append(f"{t[0]}: '{ch}' huruf biasa")
            elif k >= 0x1F000:
                salah.append(f"{t[0]}: '{ch}' emoji (U+{k:04X})")
    assert not salah, "; ".join(salah)


@pytest.mark.parametrize("ikon_uji", ["◈", "⇥"])
def test_templat_bersama_tak_lagi_memilih_ikon_per_layar(ikon_uji):
    """Tempatnya `nav.TAB`, bukan `base.html`.

    Berkas itu milik BERSAMA beberapa aplikasi, sedangkan "pintu apa saja yang
    ada" milik masing-masing. Templat itu sendiri sudah menuliskan prinsipnya
    beberapa baris di atas, untuk `peran_min`; ikon satu-satunya fakta
    per-pintu yang tercecer di sana — dan menambah layar berarti menyunting
    berkas milik bersama demi satu huruf.
    """
    from types import SimpleNamespace
    from jinja2 import Environment, FileSystemLoader

    env = Environment(loader=FileSystemLoader(str(AKAR / "hmu_tampilan/templates")),
                      autoescape=True)
    env.globals.update(VERSI="uji", APP_NAMA="Uji", PWA_NAMA="Uji",
        MODE_UJI=False, MOCKUP=False, TAB_KUNCI=set(), JUDUL={}, NAMA_VIEW={},
        SUBMENU={}, PINTU_MATI=(),
        TAB=(("stok", "/uji", "Pintu uji", "Uji ikon", None, ikon_uji),))
    html = env.get_template("base.html").render(
        akun=SimpleNamespace(nama="Operator Uji"), layar="uji", VIEW="uji",
        LIHAT_SEBAGAI=None, CSRF="uji", TERIK=True)
    ikon = [s for s in _atribut_tag(html, "span")
            if "pintu__ikon" in s.get("class", "").split()]
    assert len(ikon) == 1 and ikon[0]["aria-hidden"] == "true"
    assert ">" + ikon_uji + "</span>" in html
    assert 'href="/uji"' in html


# ─────── Bekatul curah: obatnya di sebelah keluhannya (30 Sep 2026) ───────

def _kartu_produk_uji(jenis="bekatul", curah=80):
    from app.services.stok import KartuProduk

    return KartuProduk(jenis=jenis, nama=jenis.title(), hasil_kg=300, hasil=[],
        belum_final_kg=0, dikemas_kg=300-curah, curah_kg=curah, keluar_kg=0,
        keluar=[], sisa_kg=300, curah_saja=jenis == "bekatul",
        ukuran_kemasan_otomatis=50, jumlah_karung_otomatis=6,
        dikemas_otomatis_kg=300)


def _env_stok_uji():
    from jinja2 import Environment, ChoiceLoader, DictLoader, FileSystemLoader

    env = Environment(loader=ChoiceLoader([
        DictLoader({"base.html": "{% block isi %}{% endblock %}{% block kaki %}{% endblock %}"}),
        FileSystemLoader(str(AKAR / "hmu_tampilan/templates")),
    ]), autoescape=True)
    env.filters["jam"] = lambda nilai, fmt="": ""
    return env


def _gambar_detail_produk(boleh_catat, jenis="bekatul", curah=80):
    return _env_stok_uji().get_template("stok_produk_detail.html").render(
        k=_kartu_produk_uji(jenis, curah), kembali="/stok-produk", pelanggan_id=None,
        beras=False, pemilik="Pabrik", kemasan={}, BOLEH_CATAT=boleh_catat,
        BOLEH_PINDAH=False, BOLEH_MASUKKAN_SILO=False, halaman_aksi="/stok-produk",
        detail_href="/stok-produk/detail?jenis="+jenis, baris_kemasan=[],
        curah_titipan=None, jasa_ids=(), VERSI="uji", buka="", nilai="", sumber_stok="")


def test_bekatul_curah_punya_tombol_di_kartunya():
    """Daftar kini membuka detail; obat tetap di samping stok yang perlu
    dicatat, dan dialog serta skrip wajib berada di detail yang sama."""
    from urllib.parse import urlsplit, parse_qs

    env = _env_stok_uji()
    daftar = str(env.get_template("_stok.html").module.blok("Hasil samping",
        [_kartu_produk_uji()], 300, 80, "curah", "samping", {}, desktop=True))
    assert any(a["href"] == "/stok-produk/detail?jenis=bekatul"
               for a in _atribut_tag(daftar, "a"))
    html = _gambar_detail_produk(True)
    tautan = [a for a in _atribut_tag(html, "a") if "buka=catat_bekatul" in a.get("href", "")]
    assert len(tautan) == 1
    alamat = urlsplit(tautan[0]["href"])
    assert alamat.path == "/stok-produk/detail"
    assert parse_qs(alamat.query) == {"jenis": ["bekatul"], "buka": ["catat_bekatul"]}
    assert any(d.get("id") == "lembar" for d in _atribut_tag(html, "dialog"))
    assert any(s.get("src", "").startswith("/static/aksi.js?")
               for s in _atribut_tag(html, "script"))
    # Rincian otomatis yang sudah ada tidak boleh hilang saat tombol kembali.
    assert "Dikemas otomatis" in html and "6 karung × 50 kg" in html


@pytest.mark.parametrize("izin,jenis,curah,tampil", [
    (True, "bekatul", 80, True), (False, "bekatul", 80, False),
    (True, "bekatul", 0, False), (True, "broken", 80, False),
])
def test_tombol_bekatul_dioper_ke_makronya(izin, jenis, curah, tampil):
    """Periksa HASIL render, termasuk izin palsu dan stok kosong. Sekadar
    mencari ejaan parameter tak menangkap makro yang membaca konteks salah."""
    html = _gambar_detail_produk(izin, jenis, curah)
    assert ("buka=catat_bekatul" in html) == tampil
    assert bool(_atribut_tag(html, "dialog")) == izin
    if not izin:
        assert not _atribut_tag(html, "script")

    # Makro yang dipanggil sendiri juga harus memakai parameter eksplisit,
    # bukan BOLEH_CATAT dari konteks yang mungkin milik pelanggan lain.
    env = _env_stok_uji()
    env.globals["BOLEH_CATAT"] = not izin
    st = env.get_template("_stok.html").module
    blok = str(st.blok("Uji", [_kartu_produk_uji(jenis, curah)], 300, curah,
                       "curah", "samping", {}, boleh_catat=izin))
    assert ("buka=catat_bekatul" in blok) == tampil
