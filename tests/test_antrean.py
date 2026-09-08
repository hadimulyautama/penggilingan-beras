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


def _render(menunggu, meja=()):
    """Layar ANTREAN. `meja` sengaja tak diterimanya lagi — parameternya
    tinggal supaya tesnya membaca seperti dulu."""
    return templates.get_template("aksi.html").render(
        request=None, akun=_akun("admin"), layar="aksi",
        MENUNGGU=len(menunggu), KEPUTUSAN=len(meja), MODE_UJI=False,
        LIHAT_SEBAGAI=None, kembali=None, menunggu=menunggu, berjalan=[],
        buka="", nilai="", lama=lambda t: "")


def _render_keputusan(meja):
    return templates.get_template("keputusan.html").render(
        request=None, akun=_akun("admin"), layar="keputusan",
        MENUNGGU=0, KEPUTUSAN=len(meja), MODE_UJI=False, LIHAT_SEBAGAI=None,
        kembali=None, meja=meja, buka="", nilai="", lama=lambda t: "")


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


def test_lencana_antrean_tidak_menagih_kerja_meja():
    """Satu angka untuk dua daftar yang berbeda isi akan menagih pekerjaan di
    layar yang tak memuatnya — lalu orang berhenti mempercayai lencana."""
    b = Berjalan(menunggu=[_tiket()], meja=[_meja(), _meja()])
    assert b.jumlah_menunggu == 1
    assert b.jumlah_keputusan == 2


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


def test_kerja_meja_keluar_dari_antrean():
    """Dicampur, baris kerja meja terbaca seperti tiket yang tertinggal — lalu
    orang mencari gabah yang sebenarnya sudah lama ditempatkan."""
    def label(h):
        import re
        return [x.strip() for x in re.findall(r'class="lbl">([^<]+)·', h)]

    # Aturan pemilik: begitu gabah punya tempat, ia keluar dari ANTREAN.
    # Gabah di baris kerja meja sudah lama punya tempat — sudah di mesin,
    # sudah di silo, bahkan sudah digiling. Jadi ia tak boleh ada di sana
    # sama sekali; blok tersendiri pun masih menyalahi aturannya.
    assert label(_render([_tiket()])) == ["Bisa dikerjakan sekarang"]
    assert "keputusan" not in (TPL / "aksi.html").read_text().lower()

    # Tempatnya layar sendiri, dan lembar aksinya dibuka DI SITU — menekan
    # "Verifikasi harga" lalu mendarat di layar lain berarti orang kehilangan
    # tempatnya setiap kali ia menyelesaikan satu baris.
    h = _render_keputusan([_meja()])
    # Judul layar sudah berkata "Menunggu keputusan"; bloknya menyebut
    # keputusan APA — dan yang kosong tak muncul.
    assert label(h) == ["Harga belum diverifikasi"]
    assert "/keputusan?buka=verify_gabah" in h
    assert "/aksi?buka=" not in h


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


def test_layar_keputusan_hanya_admin():
    """Sejak awal pekerjaan admin. Yang menjaga sungguhan adalah rutenya,
    bukan pintu yang disembunyikan dari laci — alamatnya tetap bisa diketik."""
    import inspect

    from app.web import layar_keputusan
    from app.web.nav import TAB

    assert "Depends(butuh_admin)" in inspect.getsource(
        layar_keputusan.halaman_keputusan)
    kunci = {k: peran for k, _, _, _, peran in TAB}
    assert kunci["keputusan"] == "admin"


def test_tiap_layar_berlaci_membawa_ketiga_lencana():
    """Lencana yang hilang di sebagian layar lebih membingungkan daripada
    lencana yang tak pernah ada: orang menyimpulkan pekerjaannya habis
    padahal ia cuma sedang berdiri di layar yang lupa menghitung.

    Yang ditagih adalah SETIAP layar yang lacinya muncul — yaitu setiap
    templat yang namanya ada di TAB. Versi lama tes ini hanya memeriksa
    blok yang sudah menyebut salah satu lencana, jadi layar yang tak
    membawa satu pun justru lolos tanpa diperiksa; begitulah List audit
    tayang berminggu-minggu dengan laci kosong.
    """
    import re

    from app.web.nav import TAB

    berlaci = {f"{kunci}.html" for kunci, *_ in TAB}
    akar = pathlib.Path(__file__).resolve().parents[1] / "app"
    terlihat, kurang = set(), []
    for berkas in akar.rglob("*.py"):
        teks = berkas.read_text()
        for m in re.finditer(r'\brender(_laci)?\(\s*request,\s*"([^"]+)"', teks):
            nama = m.group(2)
            if nama not in berlaci:
                continue
            terlihat.add(nama)
            if m.group(1):                     # render_laci → ketiganya sekaligus
                continue
            potongan = _panggilan(teks, m.end())
            if "lencana(" in potongan:
                continue
            hilang = [l for l in ("MENUNGGU", "BERJALAN", "KEPUTUSAN")
                      if l not in potongan]
            if hilang:
                baris = teks[:m.start()].count("\n") + 1
                kurang.append(f"{berkas.name}:{baris} {nama} — kurang "
                              + ", ".join(hilang))
    assert not kurang, "layar ini lupa lencananya:\n  " + "\n  ".join(kurang)
    # Setiap pintu laci harus benar-benar punya layar yang dirender; kalau
    # tidak, tes di atas menjaga daftar kosong tanpa ada yang tahu.
    assert terlihat == berlaci, f"tak ketemu rendernya: {berlaci - terlihat}"


def _panggilan(teks: str, mulai: int) -> str:
    """Potongan sumber dari `render(` sampai kurung penutupnya yang seimbang."""
    dalam = 1
    for i in range(mulai, len(teks)):
        if teks[i] == "(":
            dalam += 1
        elif teks[i] == ")":
            dalam -= 1
            if not dalam:
                return teks[mulai:i]
    return teks[mulai:]


def test_lencana_menagih_dan_lencana_mengabari_dibedakan():
    """"Antrian tunggu" dan "Menunggu keputusan" berarti ada yang harus
    dikerjakan; "Sedang berjalan" cuma menyebut berapa yang sedang jalan — ia
    bisa berisi seharian tanpa ada yang salah. Kalau keduanya tampil sama,
    yang menagih kehilangan artinya."""
    base = (TPL / "base.html").read_text()
    assert "BERJALAN" in base and "pintu__jml--kabar" in base
    blok = base.split("kunci == 'berjalan' and BERJALAN")[1].split("{% elif")[0]
    assert "pintu__jml--kabar" in blok
    for kunci in ("aksi", "keputusan"):
        b = base.split(f"kunci == '{kunci}' and ")[1].split("{% elif")[0]
        assert "--kabar" not in b, kunci

    # Dibedakan WARNANYA, bukan ketebalannya: biru berarti ada yang harus
    # Anda kerjakan, oranye berarti ada mesin yang sedang menyala — warna
    # yang sama dengan mesin pengering di kartu, jadi lencana dan bendanya
    # berkata hal yang sama.
    css = (AKAR / "app/web/static/app.css").read_text()
    kabar = css.split(".pintu__jml--kabar {")[1].split("}")[0]
    assert "var(--fase-dryer)" in kabar
    tagih = css.split(".pintu__jml {")[1].split("}")[0]
    assert "var(--aksi)" in tagih


def test_jumlah_berjalan_menghitung_mesin_dan_transit():
    """Yang tampil di layar Sedang berjalan ada dua blok, jadi lencananya
    harus menghitung keduanya — bukan hanya yang mesinnya menyala."""
    b = Berjalan(berjalan=[_tiket()], transit=[_tiket(), _tiket()])
    assert b.jumlah_berjalan == 3


def test_gudang2_punya_kartunya_sendiri():
    """Pemilik bertanya apa guna halaman "Catat pekerjaan lain". Sebabnya: 17
    dari 32 aksi tak punya kartu sama sekali — termasuk SELURUH alur Gudang 2
    dan PK dari luar. Operator Gudang 2 harus membaca daftar kata kerja untuk
    menemukan satu, persis keadaan yang sudah dibuang dari Gudang 1."""
    import inspect

    from app.services import berjalan as svc

    assert hasattr(svc, "untuk_gudang2")
    fn = inspect.getsource(svc.untuk_gudang2)
    for aksi in ("masukkan_pk", "harga_pk_luar", "qc_pk_luar",
                 "mulai_penyosohan", "hasil_penyosohan", "selesai_penyosohan"):
        assert aksi in fn, aksi
    # Golongannya mengikuti aturan yang sama dengan Gudang 1.
    assert "b.menunggu.append" in fn and "b.berjalan.append" in fn
    assert "b.transit.append" in fn and "b.meja.append" in fn
    # Patokan "belum bertempat" DIAMBIL dari yang sama dengan daftar pilihan
    # aksinya sendiri — kalau disusun ulang, kartu dan lembarnya berbeda isi.
    assert "PkGudang2Intake.pk_purchase_batch_id == PkPurchaseBatch.id" in fn

    untuk = inspect.getsource(svc.untuk)
    assert "untuk_gudang2(db)" in untuk
    assert "Gudang 2 menyusul" not in untuk, "Gudang 2 tak lagi ditunda"
    assert "pass    #" not in untuk, "cabang Gudang 2 tak lagi kosong"


def test_katalog_dikelompokkan_dan_undo_dikeluarkan():
    """Tiga puluh kata kerja berjajar sama besar menuntut orang membaca
    semuanya untuk menemukan satu. Dan `undo` punya rumahnya sendiri di List
    audit — dua pintu untuk satu pekerjaan berarti yang satu tak pernah ikut
    diperbarui."""
    import inspect

    from app.web import miniapp

    assert hasattr(miniapp, "_GRUP_AKSI") and hasattr(miniapp, "URUT_GRUP")
    assert miniapp._GRUP_AKSI["mulai_penyosohan"] == "Gudang 2 · penyosohan"
    assert miniapp._GRUP_AKSI["catat_pk_luar"] == "PK dari luar"
    assert miniapp._GRUP_AKSI["gabah_masuk"] == miniapp.GRUP_KARTU

    menu = inspect.getsource(miniapp.actions_menu)
    assert 'a["grup"] = _GRUP_AKSI.get' in menu
    # `undo` dibuang HANYA bagi yang punya List audit. Operator tak punya
    # layar itu, jadi katalog inilah satu-satunya jalannya membatalkan —
    # membuangnya untuk semua orang berarti yang paling sering salah ketik
    # justru kehilangan cara memperbaikinya.
    assert 'if fin:\n        actions = [a for a in actions if a["id"] != "undo"]' in menu

    aksi_js = (AKAR / "app/web/static/aksi.js").read_text()
    assert "DATA.urutGrup" in aksi_js
    assert 'a.grup || "Lain-lain"' in aksi_js
