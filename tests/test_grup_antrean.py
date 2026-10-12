"""Grup antrean — sub-menu "Antrian tunggu", dan jaring yang menangkap sisanya.

Keputusan pemilik 2 Oktober 2026: *"antrian tunggu bisa banyak sekali"* →
*"bisa tidak antrian tunggu jika di klik muncul dropdown sub menu?"* →
*"sub menu pertama bahan baku, kedua tunggu packing. tunggu dipindah."*

⚠ YANG DIJAGA PALING KERAS: tak satu kartu pun boleh jatuh ke luar seluruh
grup. Kartu yang tak masuk grup mana pun akan HILANG dari layar yang justru
menagihnya — pelajaran 1 Oktober 2026, ketika saringan "milik pabrik" membuang
tujuh ton PK pelanggan dari setiap angka tanpa satu pun galat. Menyaring tanpa
menyebutkan sama buruknya dengan menjumlahkan.
"""
from __future__ import annotations

import pytest

from app.services.berjalan import (GRUP_ANTREAN, Baris, Berjalan, _GRUP_AKSI,
                                   _GRUP_KELOMPOK, grup_baris)

KUNCI = {k for k, _ in GRUP_ANTREAN}


def _kartu(aksi=None, kelompok=None, kode="X-1", jasa_id=None):
    return Baris(kode=kode, isi="", keadaan="", aksi=aksi, kelompok=kelompok,
                jasa_id=jasa_id)


def test_grup_terakhir_adalah_komplemen_bukan_daftar():
    """⭐ JARINGNYA. Apa pun yang tak terpetakan jatuh ke grup terakhir.

    Termasuk kartu jenis baru yang lahir besok — dan itu disengaja: daftar yang
    harus lengkap adalah daftar yang suatu hari tidak lengkap, dan kartu yang
    tak masuk grup mana pun akan hilang dari layar yang menagihnya.
    """
    for aneh in (_kartu(aksi="aksi_yang_belum_ada"),
                 _kartu(kelompok="kelompok_yang_belum_ada"),
                 _kartu(),
                 _kartu(aksi="", kelompok="")):
        assert grup_baris(aneh) == GRUP_ANTREAN[-1][0]
    # Dan ia memang grup yang digambar, bukan nilai buangan: namanya ada.
    assert dict(GRUP_ANTREAN)[GRUP_ANTREAN[-1][0]]


def test_setiap_kartu_selalu_dapat_grup_yang_sah():
    """`grup_baris` tak pernah melempar dan tak pernah menjawab di luar daftar."""
    for aksi in (*_GRUP_AKSI, None, "", "entah"):
        for kelompok in (*_GRUP_KELOMPOK, None, "", "entah", "tumpukan"):
            g = grup_baris(_kartu(aksi=aksi, kelompok=kelompok))
            assert g in KUNCI, (aksi, kelompok, g)


def test_jumlah_grup_menjumlah_tepat_seluruh_antrean():
    """⭐ INVARIAN YANG MENJAGA SELURUHNYA: Σ grup == panjang antrean.

    Kalau ada kartu yang tak terhitung, angka sub-menunya akan menyebut lebih
    sedikit daripada isinya — dan orang berhenti mencari sisanya.
    """
    b = Berjalan(menunggu=[
        _kartu(aksi="gabah_masuk"), _kartu(kelompok="tiket"),
        _kartu(aksi="pindah_tumpukan"), _kartu(aksi="pindah_tumpukan_silo"),
        _kartu(aksi="kirim_permintaan_pk"), _kartu(aksi="catat_packing"),
        _kartu(aksi="muat_semua", kelompok="keluar"),
        _kartu(kelompok="selesai"), _kartu(aksi="belum_dikenal"),
    ])
    n = b.jumlah_grup()
    assert sum(n.values()) == len(b.menunggu) == 9
    assert set(n) == KUNCI, "ada grup yang tak pernah dihitung"


def test_tumpukan_gudang_satu_dan_dua_masuk_grup_BERBEDA():
    """⭐ `kelompok="tumpukan"` RANCU, dan itu sebabnya `aksi` dibaca lebih dulu.

    Di Gudang 1 ia gabah yang menunggu giliran giling — BAHAN BAKU. Di Gudang 2
    ia PK yang menunggu dipindah ke silo — TUNGGU DIPINDAH. Satu nilai
    `kelompok`, dua grup; yang memetakan lewat `kelompok` akan menjawab salah
    satunya dengan salah.
    """
    g1 = _kartu(aksi="pindah_tumpukan", kelompok="tumpukan")
    g2 = _kartu(aksi="pindah_tumpukan_silo", kelompok="tumpukan")
    assert grup_baris(g1) == "bahan"
    assert grup_baris(g2) == "pindah"
    assert grup_baris(g1) != grup_baris(g2)
    # Dan `tumpukan` memang TIDAK dipetakan di kaki kedua — kalau ia dipetakan,
    # kartu tumpukan yang kelak kehilangan `aksi`-nya akan ikut salah grup.
    assert "tumpukan" not in _GRUP_KELOMPOK


def test_ketiga_grup_yang_pemilik_sebut_ada_dan_bernama_begitu():
    """Namanya yang dibaca orang, bukan kuncinya."""
    nama = dict(GRUP_ANTREAN)
    assert nama["bahan"] == "Bahan baku"
    assert nama["pindah"] == "Tunggu dipindah"
    assert nama["packing"] == "Packing"
    # Urutannya urutan aliran barang, bukan abjad.
    assert [k for k, _ in GRUP_ANTREAN][:3] == ["bahan", "pindah", "packing"]


def test_packing_titipan_dan_pabrik_masuk_grup_BERBEDA():
    """⭐ `aksi` SAMA ("catat_packing"), pemiliknya BEDA — `aksi` sendirian tak
    bisa menjawab ini (beda dari `kelompok="tumpukan"` di atas, yang
    terjawab lewat `aksi` yang berbeda). Keluhan pemilik 6 Oktober 2026: "di
    halaman tunggu packing tidak bisa dibedakan mana jasa mana yang tidak."
    """
    pabrik = _kartu(aksi="catat_packing", kelompok="produk")
    titipan = _kartu(aksi="catat_packing", kelompok="produk", jasa_id=7)
    assert grup_baris(pabrik) == "packing"
    assert grup_baris(titipan) == "packing_jasa"
    assert "packing_jasa" in KUNCI
    assert dict(GRUP_ANTREAN)["packing_jasa"] == "Packing jasa"


def test_aksi_yang_dipetakan_memang_ada_di_kode():
    """Nama `aksi` yang salah tulis jatuh DIAM-DIAM ke grup komplemen.

    Tiga nama sempat salah tulis saat peta ini ditulis (`pk_luar_masuk`,
    `minta_pk_g1`, `setujui_permintaan_pk`) dan tak satu pun melempar galat —
    kartunya cuma pindah ke "Lainnya" tanpa ada yang tahu.
    """
    import pathlib
    import re

    sumber = pathlib.Path("app/services/berjalan.py").read_text()
    # Menerima kedua bentuk: `aksi="x"` dan `aksi=None if … else "x"`.
    ada = set(re.findall(r'aksi=(?:[^,\n]*?)"([a-z_]+)"', sumber))
    hilang = sorted(set(_GRUP_AKSI) - ada)
    assert not hilang, f"dipetakan tapi tak ada kartu yang memakainya: {hilang}"


# ── Sub-menu laci ──

def test_submenu_butuh_dua_grup_berisi():
    """Dropdown yang tak punya pilihan MERAMPAS satu ketukan.

    Dengan satu grup berisi, membuka pintu antrean cuma menawarkan "Semua" dan
    satu nama yang isinya sama persis. Di hari seperti itu pintunya wajib
    kembali jadi pintu biasa — dan syaratnya sama dengan syarat pil di dalam
    halaman, supaya laci berdropdown tak pernah muncul di atas halaman tanpa
    pil.

    ⚠ Diperiksa pada kunci "aksi" SAJA, bukan `submenu() == {}`: sejak 5
    Oktober 2026 "stok" punya sub-menunya sendiri, independen dari isi
    antrean (`pintu_produk` bawaannya True) — lihat
    `test_stok_bersub_menu_saat_stok_produk_ditawarkan`.
    """
    satu = Berjalan(menunggu=[_kartu(aksi="catat_packing") for _ in range(6)])
    assert "aksi" not in satu.submenu()
    assert "aksi" not in satu.lencana()["SUBMENU"]

    dua = Berjalan(menunggu=[_kartu(aksi="catat_packing"),
                             _kartu(aksi="gabah_masuk")])
    assert "aksi" in dua.submenu()

    assert "aksi" not in Berjalan().submenu(), "antrean kosong tak punya sub-menu"


def test_semua_selalu_baris_pertama_submenu():
    """⚠ TANPA INI DAFTAR UTUHNYA TAK TERJANGKAU.

    Pintunya berubah jadi `<summary>` saat ia bersub-menu, jadi mengkliknya tak
    lagi menuju `/aksi`. Baris "Semua" satu-satunya jalan ke daftar penuh dari
    dalam laci.
    """
    b = Berjalan(menunggu=[_kartu(aksi="catat_packing"),
                           _kartu(aksi="gabah_masuk"),
                           _kartu(aksi="pindah_tumpukan_silo")])
    sub = b.submenu()["aksi"]
    alamat, nama, jml = sub[0]
    assert alamat == "/aksi", "baris pertama bukan jalan ke daftar utuh"
    assert nama == "Semua"
    assert jml == len(b.menunggu)
    # Sisanya menuju alamat bergrup, dan angkanya sepadan dengan isinya.
    assert all(a.startswith("/aksi?grup=") for a, _, _ in sub[1:])
    assert sum(j for _, _, j in sub[1:]) == len(b.menunggu)


def test_grup_kosong_tak_pernah_ditawarkan_di_submenu():
    """Lencana yang tak pernah bisa dinolkan mengajari orang mengabaikannya —
    dan baris sub-menu bertuliskan 0 jenis yang sama."""
    b = Berjalan(menunggu=[_kartu(aksi="catat_packing"),
                           _kartu(aksi="gabah_masuk")])
    sub = b.submenu()["aksi"]
    assert all(j > 0 for _, _, j in sub)
    nama = [n for _, n, _ in sub]
    assert "Tunggu dipindah" not in nama and "Lainnya" not in nama


def test_angka_submenu_datang_dari_daftar_yang_akan_digambar():
    """SATU sumber untuk angka dan isi.

    Sub-menu yang menyebut 3 pada pintu yang begitu dibuka memperlihatkan 2
    akan dipercaya satu kali saja. Jadi angkanya dihitung dari `menunggu` yang
    sama — dibuktikan dengan menyaring sendiri dan membandingkan.
    """
    b = Berjalan(menunggu=[
        _kartu(aksi="gabah_masuk"), _kartu(aksi="gabah_masuk"),
        _kartu(aksi="catat_packing"), _kartu(aksi="pindah_tumpukan_silo"),
        _kartu(kelompok="keluar", aksi="muat_semua"),
    ])
    n = b.jumlah_grup()
    for kunci, _ in GRUP_ANTREAN:
        saring = [x for x in b.menunggu if grup_baris(x) == kunci]
        assert len(saring) == n[kunci], kunci


# ══════════════ Sub-menu "Stok" — gabung PK & Produk, bukan filter ══════════════
#
# Keputusan pemilik 5 Oktober 2026: *"ringkas menu. buat stock menjadi main
# menu memiliki sub menu. yaitu stock PK dan stock produk."* BEDA bentuknya
# dari "aksi"/"keputusan" di atas: dua tujuannya sudah lengkap sendiri-sendiri
# (dua HALAMAN berbeda, bukan dua filter atas satu halaman yang sama), jadi
# tak ada baris "Semua" — tak ada daftar utuh yang lebih besar dari keduanya
# untuk dituju.

def test_stok_bersub_menu_saat_stok_produk_ditawarkan():
    b = Berjalan(pintu_produk=True)
    assert b.submenu()["stok"] == [("/stok", "Stok PK", 0),
                                   ("/stok-pk-jasa", "Stok PK Jasa", 0),
                                   ("/stok-produk", "Stok Produk", 0),
                                   ("/stok-produk-jasa", "Produk Jasa", 0),
                                   ("/stok-karung", "Stok Karung", 0),
                                   ("/stok-karung-jasa", "Karung Jasa", 0)]


def test_stok_sub_menu_tak_ada_satu_pun_angka_walau_jumlah_produk_terisi():
    """Stok PK (dan Stok PK Jasa) tak pernah punya lencana — tak seperti
    Antrian tunggu/Keputusan, "Stok" tak menagih pekerjaan. "Stok Produk"
    pun sejak 7 Oktober 2026 (permintaan pemilik: "tidak perlu ada
    angkanya") — sebelumnya satu-satunya baris yang memakai `jumlah_produk`
    sebagai lencananya, sekarang sama seperti baris lain: murni informasi,
    tanpa badge, berapa pun `jumlah_produk`-nya."""
    b = Berjalan(pintu_produk=True, jumlah_produk=3)
    assert b.submenu()["stok"] == [("/stok", "Stok PK", 0),
                                   ("/stok-pk-jasa", "Stok PK Jasa", 0),
                                   ("/stok-produk", "Stok Produk", 0),
                                   ("/stok-produk-jasa", "Produk Jasa", 0),
                                   ("/stok-karung", "Stok Karung", 0),
                                   ("/stok-karung-jasa", "Karung Jasa", 0)]


def test_stok_tetap_bersub_menu_bila_stok_produk_padam():
    """Operator selepan: 'Stok Produk' & 'Produk Jasa' tak ditawarkan sama
    sekali (lihat `Berjalan.lencana`) — tapi 'Stok' TETAP dropdown berisi
    DUA tujuan ('Stok PK', 'Stok PK Jasa'), bukan pintu biasa: beda dari
    sebelum "Stok PK Jasa" ada (dulu 'Stok' sendirian berarti SATU tujuan).
    PK titipan berdiri di Gudang 1 juga, jadi operator selepan tetap berhak
    melihatnya — "Stok PK Jasa" TIDAK digerbangi `pintu_produk` (lihat
    `submenu()`)."""
    assert Berjalan(pintu_produk=False).submenu()["stok"] == [
        ("/stok", "Stok PK", 0), ("/stok-pk-jasa", "Stok PK Jasa", 0)]


def test_pintu_stok_produk_sendiri_selalu_padam_di_laci():
    """Pintunya DIPENSIUNKAN untuk SEMUA orang sejak diserap 'Stok' —
    bukan cuma operator selepan seperti sebelum 5 Oktober 2026."""
    for pintu_produk in (True, False):
        mati = Berjalan(pintu_produk=pintu_produk).lencana()["PINTU_MATI"]
        assert "stok_produk" in mati


def test_pintu_stok_karung_sendiri_selalu_padam_di_laci():
    """Pola yang sama dengan 'stok_produk' — 'Stok Karung'/'Karung Jasa'
    hanya terjangkau lewat dropdown 'Stok', tak pernah pintu berdiri
    sendiri, untuk siapa pun."""
    for pintu_produk in (True, False):
        mati = Berjalan(pintu_produk=pintu_produk).lencana()["PINTU_MATI"]
        assert "stok_karung" in mati and "stok_karung_jasa" in mati


def test_audit_jasa_kabar_padam_di_laci_permintaan_pemilik_7_oktober():
    """Tiga pintu dipadamkan permintaan pemilik 7 Oktober 2026 — tanpa
    syarat, untuk semua orang:

      · "audit" — digantikan tombol di Pengaturan (lihat `test_setelan.py::
        test_tombol_list_audit_hanya_untuk_admin_ke_atas`), halamannya
        sendiri tak berubah;
      · "jasa" & "kabar" — disembunyikan sementara TANPA jalan pengganti,
        sampai pemilik memutuskan kelak. Alamatnya (`/jasa`, `/kabar`)
        tetap bisa diketik — menyembunyikan pintu bukan penjagaan."""
    mati = Berjalan().lencana()["PINTU_MATI"]
    for kunci in ("audit", "jasa", "kabar"):
        assert kunci in mati, kunci


# ═══════ Sub-menu "Riwayat Proses" — Penyosohan vs Penggilingan/Pengeringan/
#         Transfer, per GUDANG yang SEDANG dikerjakan (7 Oktober 2026) ═══════
#
# Pola sama "Stok" di atas (empat HALAMAN utuh, bukan filter, tanpa baris
# "Semua") — bedanya isinya terbagi per gudang, bukan per fitur: operator
# Gudang 2 cuma berhak atas "Penyosohan", operator Gudang 1 cuma berhak atas
# ketiga sisanya, dan Admin/Superadmin (kedua bendera `True`) melihat
# keempatnya. Kunci dict-nya `riwayat_sosoh` — kunci TAB yang sudah ada,
# bukan kunci baru "riwayat_proses" (tak ada TAB bernama itu; "Riwayat
# Proses" cuma label laci pintu `riwayat_sosoh`, persis "Stok" cuma label
# pintu `stok`).

def test_riwayat_bersub_menu_untuk_admin_superadmin():
    """Urutan ALUR PRODUKSI (koreksi pemilik 7 Oktober 2026): Pengeringan
    (basah→kering) → Penggilingan (kering→PK) → Penyosohan (PK→beras) →
    Transfer — bukan urutan "Gudang 2 dulu" yang kebetulan lebih mudah
    ditulis kodenya."""
    b = Berjalan(boleh_riwayat_sosoh=True, boleh_riwayat_g1=True)
    assert b.submenu()["riwayat_sosoh"] == [
        ("/riwayat-pengeringan", "Pengeringan", 0),
        ("/riwayat-giling", "Penggilingan", 0),
        ("/riwayat-sosoh", "Penyosohan", 0),
        ("/riwayat-transfer", "Transfer", 0)]


def test_riwayat_operator_gudang1_hanya_tiga_tanpa_penyosohan():
    b = Berjalan(boleh_riwayat_sosoh=False, boleh_riwayat_g1=True)
    assert b.submenu()["riwayat_sosoh"] == [
        ("/riwayat-pengeringan", "Pengeringan", 0),
        ("/riwayat-giling", "Penggilingan", 0),
        ("/riwayat-transfer", "Transfer", 0)]


def test_riwayat_operator_gudang2_tanpa_dropdown_cuma_satu_pilihan():
    """Operator Gudang 2 cuma berhak atas SATU tujuan ('Penyosohan') —
    aturan ≥2 yang sama dipakai "Antrian tunggu"/"Keputusan"/"Stok": pintu
    ini kembali jadi tautan biasa ke `/riwayat-sosoh`, bukan dropdown tanpa
    pilihan yang merampas satu ketukan."""
    b = Berjalan(boleh_riwayat_sosoh=True, boleh_riwayat_g1=False)
    assert "riwayat_sosoh" not in b.submenu()


def test_riwayat_giling_pengeringan_transfer_selalu_padam_di_laci():
    """Ketiganya hanya terjangkau lewat dropdown "Riwayat Proses" —
    `riwayat_sosoh` sendiri TETAP (ia pintu induk sekaligus anak pertama,
    persis "stok")."""
    for sosoh, g1 in ((True, True), (True, False), (False, True)):
        mati = Berjalan(boleh_riwayat_sosoh=sosoh, boleh_riwayat_g1=g1).lencana()["PINTU_MATI"]
        for kunci in ("riwayat_giling", "riwayat_pengeringan", "riwayat_transfer"):
            assert kunci in mati
        assert "riwayat_sosoh" not in mati


def test_riwayat_qc_memuat_kategori_sesuai_gudang():
    admin = Berjalan(boleh_riwayat_sosoh=True, boleh_riwayat_g1=True)
    assert admin.submenu()["riwayat_qc"] == [
        ("/riwayat-qc/gabah-basah", "Gabah basah", 0),
        ("/riwayat-qc/gabah-kering", "Gabah kering", 0),
        ("/riwayat-qc/pk-hasil-giling", "PK Hasil Giling", 0),
        ("/riwayat-qc/pk-luar", "PK Luar", 0),
        ("/riwayat-qc/beras-hasil-sosoh", "Beras Hasil Sosoh", 0),
    ]
    g1 = Berjalan(boleh_riwayat_sosoh=False, boleh_riwayat_g1=True)
    assert [label for _, label, _ in g1.submenu()["riwayat_qc"]] == [
        "Gabah basah", "Gabah kering", "PK Hasil Giling"]
    g2 = Berjalan(boleh_riwayat_sosoh=True, boleh_riwayat_g1=False)
    assert [label for _, label, _ in g2.submenu()["riwayat_qc"]] == [
        "PK Luar", "Beras Hasil Sosoh"]


# ══════════════ Yang TERGAMBAR: pil halaman & sub-menu laci ══════════════
#
# Dirender sungguhan, bukan diperiksa sebagai teks di berkas templatnya.
# Penjaga versi hitung-teks pernah LULUS saat markup dimatikan dengan
# `{% if false %}` — tulisannya tetap ada di berkasnya, cuma tak pernah
# tergambar (pelajaran kartu pemilik, 2 Oktober 2026).

import types

from app.web.tampilan import templates


def _akun(peran="operator"):
    a = types.SimpleNamespace(nama="Pras", peran=peran, sesi_pendek=False)
    a.is_admin = peran in ("admin", "superadmin")
    return a


def _layar_aksi(menunggu, *, grup="", pil=None, total=None):
    """Layar antrean, dengan nilai yang DIKIRIM RUTENYA — bukan diketik ulang:
    `halaman_aksi` menyusunnya dari `GRUP_ANTREAN` dan `jumlah_grup()`."""
    b = Berjalan(menunggu=menunggu)
    n = b.jumlah_grup()
    tampil = ([x for x in menunggu if grup_baris(x) == grup] if grup else menunggu)
    return templates.get_template("aksi.html").render(
        request=None, akun=_akun("admin"), layar="aksi",
        MENUNGGU=len(menunggu), KEPUTUSAN=0, MODE_UJI=False,
        LIHAT_SEBAGAI=None, kembali=None, menunggu=tampil, berjalan=[],
        buka="", nilai="", lama=lambda t: "",
        KELOMPOK_ATAS="tumpukan", judul_atas="Menumpuk di lantai",
        judul_bawah="Bisa dikerjakan sekarang", PINTASAN=(),
        GRUP_PIL=(pil if pil is not None
                  else [(k, nm, n[k]) for k, nm in GRUP_ANTREAN
                        if n[k] or k == grup]),
        GRUP_KINI=grup,
        GRUP_TOTAL=(total if total is not None else sum(n.values())))


def _laci(submenu, layar="beranda"):
    from app.web.nav import TAB

    return templates.get_template("base.html").render(
        request=None, akun=_akun("admin"), layar=layar, MENUNGGU=7,
        MODE_UJI=False, LIHAT_SEBAGAI=None, kembali=None, TAB=TAB,
        SUBMENU=submenu, VIEW="admin", CSRF="x")


def test_pil_grup_tergambar_dan_angkanya_ikut():
    dua = [_kartu(aksi="gabah_masuk"), _kartu(aksi="catat_packing"),
           _kartu(aksi="catat_packing")]
    h = _layar_aksi(dua)
    assert "Bahan baku" in h and "Packing" in h
    assert "pil--on" in h, "pil 'Semua' tak bertanda aktif"
    # Angkanya, dan kelasnya yang memang ada di app.css.
    assert 'class="pil__jml"' in h
    assert ">3<" in h.replace(" ", "").replace("\n", "")


def test_pil_tak_digambar_bila_grupnya_cuma_satu():
    """Satu pil di atas daftar yang seluruhnya satu grup tak membedakan apa pun,
    dan ia memakan baris yang di ponsel berharga."""
    h = _layar_aksi([_kartu(aksi="catat_packing") for _ in range(5)])
    # `<a class="pil` — PENANDA PILNYA SENDIRI, bukan `.saring` (dipakai
    # DUA fitur berbeda: kotak cari muncul begitu kartunya >4, pil muncul
    # begitu grupnya >1 — keduanya bisa hidup berdampingan atau sendiri-
    # sendiri) dan bukan `class="pil` polos (kartu sungguhan juga membawa
    # `class="pilihan"`, tombol aksinya).
    assert '<a class="pil' not in h


def test_grup_kosong_tak_berkata_pekerjaan_anda_habis():
    """⚠ Bedanya menentukan apakah orang pulang.

    "Tidak ada yang menunggu Anda" pada grup yang kosong sementara tiga grup
    lain berisi adalah kalimat yang menyuruh orang berhenti bekerja.
    """
    kartu = [_kartu(aksi="gabah_masuk"), _kartu(aksi="catat_packing")]
    h = _layar_aksi(kartu, grup="pindah")
    assert "Grup ini kosong" in h
    assert "Tidak ada yang menunggu Anda" not in h
    # Dan ia menunjuk jalan keluarnya, berikut berapa yang ada di grup lain.
    assert "Lihat semua" in h and "2 kartu" in h


def test_antrean_benar_benar_kosong_tetap_memakai_kalimat_lamanya():
    h = _layar_aksi([])
    assert "Tidak ada yang menunggu Anda" in h
    assert "Grup ini kosong" not in h


def test_pintu_antrean_jadi_summary_saat_bersub_menu():
    """⭐ Pintunya BERUBAH: `<a href>` → `<summary>`.

    Itu yang membuat kliknya membuka sub-menu alih-alih menuju halamannya —
    dan itu pula sebabnya baris "Semua" wajib ada di dalamnya.
    """
    sub = {"aksi": [("/aksi", "Semua", 7), ("/aksi?grup=bahan", "Bahan baku", 1),
                    ("/aksi?grup=packing", "Packing", 6)]}
    h = _laci(sub)
    assert "pintu-lipat" in h
    assert "<summary" in h
    assert 'class="pintu-sub"' in h
    for nama in ("Semua", "Bahan baku", "Packing"):
        assert nama in h
    # Jalan ke daftar utuh tetap ada.
    assert 'href="/aksi"' in h
    assert 'href="/aksi?grup=bahan"' in h


def test_pintu_tetap_tautan_biasa_tanpa_sub_menu():
    """Dan pintu LAIN tak pernah ikut berubah — sub-menunya per kunci."""
    h = _laci({})
    assert "pintu-lipat" not in h
    assert 'href="/aksi"' in h
    # Pintu lain tetap tautan walau antrean bersub-menu.
    h2 = _laci({"aksi": [("/aksi", "Semua", 2),
                         ("/aksi?grup=bahan", "Bahan baku", 1),
                         ("/aksi?grup=packing", "Packing", 1)]})
    assert 'href="/stok"' in h2 and 'href="/berjalan"' in h2


def test_pintu_stok_jadi_summary_tanpa_semua_dan_tanpa_lencana_nol():
    """⭐ "Stok" BEDA bentuk dari "Antrian tunggu": dua tujuan yang sudah
    lengkap sendiri-sendiri, bukan dua filter satu daftar — jadi tak ada
    baris "Semua" di dalamnya. Dan "Stok PK" tak boleh menggambar lencana
    "0": `sub_jml=0` harus dibuang `{% if sub_jml %}` di templat, bukan
    "kebetulan" ikut kosong seperti grup antrean yang memang disaring
    sebelum masuk daftar.
    """
    sub = {"stok": [("/stok", "Stok PK", 0), ("/stok-produk", "Stok Produk", 3)]}
    h = _laci(sub)
    assert "pintu-lipat" in h and "<summary" in h
    for nama in ("Stok PK", "Stok Produk"):
        assert nama in h
    assert 'href="/stok"' in h and 'href="/stok-produk"' in h
    assert "Semua" not in h
    # Lencana "0" tak tergambar (Stok PK); "3" harus (Stok Produk) — dan
    # itu satu-satunya badge berkelas ini di laci selama BERJALAN/KABAR tak
    # dikirim ke `_laci`.
    assert h.count('class="pintu__jml pintu__jml--kabar"') == 1
    assert ">3<" in h.replace(" ", "").replace("\n", "")


def test_sub_menu_terbuka_sendiri_di_halamannya_sendiri():
    """Yang sudah berada di antrean hampir pasti ingin berpindah grup, dan satu
    ketukan tambahan untuk itu adalah ketukan yang diulang sepanjang hari."""
    sub = {"aksi": [("/aksi", "Semua", 2), ("/aksi?grup=bahan", "Bahan baku", 1),
                    ("/aksi?grup=packing", "Packing", 1)]}
    assert "<details class=\"pintu-lipat\" open>" in _laci(sub, layar="aksi")
    assert " open>" not in _laci(sub, layar="beranda")


def test_kelas_css_sub_menu_memang_ada():
    """⚠ Kelas yang tak dikenal TIDAK melempar galat — ia cuma tak menggambar.

    `pil--aktif` dan `btn--halus` pernah dipakai layar Jasa selama sehari dan
    dua-duanya tak pernah ada di `app.css`: pil saringan yang aktif tak
    bertanda sama sekali, dan tak ada satu pun uji yang bisa menangkapnya.
    """
    import pathlib

    css = pathlib.Path("hmu_tampilan/static/app.css").read_text()
    for kelas in (".pintu-lipat", ".pintu-sub", ".pintu-sub__satu",
                  ".pintu-sub__nama", ".pil__jml"):
        assert kelas in css, f"{kelas} dipakai templat tapi tak ada di app.css"


# ══════════════════ PENJAGA UMUM: kelas CSS karangan ══════════════════

def test_tak_ada_kelas_css_karangan_di_templat_app_ini():
    """⭐ Kelas yang tak dikenal TIDAK melempar galat — ia cuma tak menggambar.

    Dalam dua hari, LIMA kelas karangan lolos ke layar Jasa dan nota-nya:

        pil--aktif      → yang ada `pil--on`   (pil saringan aktif tak bertanda)
        btn--halus      → yang ada `btn--kecil`
        kartu__judul    → tak ada; `.kartu` memang panel tanpa kelas judul
        lencana--netral → `.lencana` tanpa pengubah MEMANG yang netral
        redup           → yang ada `bantu`
        blok            → tak ada

    Tak satu pun melempar apa pun, tak satu pun uji bisa menangkapnya, dan
    semuanya cuma terlihat oleh orang yang membandingkan layarnya dengan layar
    sebelah. Penjaga inilah yang menangkapnya — dan ia BERSIH saat ditulis:
    nol gangguan dari templat yang sudah lama berdiri.

    Lingkupnya templat milik repo ini saja (`app/web/templates/`). Templat paket
    dijaga `test_tampilan_paket.py` di repo `tampilan`, tempat CSS-nya tinggal.

    ⚠ Komentar Jinja DIBUANG dulu: komentar repo ini sering mengutip markup
    yang salah berikut sebabnya, dan penjaga yang memerah karena kutipan akan
    dilonggarkan oleh orang yang sedang tergesa.
    """
    import pathlib
    import re

    akar = pathlib.Path(__file__).resolve().parents[1]
    css = (akar / "hmu_tampilan/static/app.css").read_text()
    ada = set(re.findall(r"\.([a-zA-Z][\w-]*)", css))

    karangan: dict[str, set[str]] = {}
    for berkas in sorted((akar / "app/web/templates").glob("*.html")):
        markup = re.sub(r"\{#.*?#\}", "", berkas.read_text(), flags=re.S)
        # Hanya `class="…"` yang MURNI huruf — yang memuat `{{ }}` atau `{% %}`
        # dirakit saat render dan tak bisa dibaca dari sini.
        for daftar in re.findall(r'class="([^"{}]*)"', markup):
            for kelas in daftar.split():
                if kelas and kelas not in ada:
                    karangan.setdefault(kelas, set()).add(berkas.name)

    assert not karangan, "kelas dipakai templat tapi tak ada di app.css: " + ", ".join(
        f"{k} ({', '.join(sorted(v))})" for k, v in sorted(karangan.items()))


def test_tombol_kirim_di_templat_app_ini_memakai_data_kirim():
    """⭐ `aksi.js` mengikat `[data-kirim]` — `data-post` SENDIRI tak cukup.

    Tombol "Tutup pesanan" di layar Jasa sempat berbunyi `data-post=…` dan
    `data-jasa=…` tanpa `data-kirim`, dan akibatnya ia TIDAK BERBUAT APA-APA
    saat ditekan: tak ada galat, tak ada kabar, cuma tombol yang diam. Yang
    menekannya akan menekan berulang lalu menyimpulkan aplikasinya rusak.
    """
    import pathlib
    import re

    akar = pathlib.Path(__file__).resolve().parents[1]
    js = (akar / "hmu_tampilan/static/aksi.js").read_text()
    # Kontraknya dibaca dari JS-nya sendiri, bukan diketik ulang di sini.
    assert 'closest("[data-kirim]")' in js, \
        "kontrak aksi.js berubah — penjaga ini ikut harus berubah"

    cacat = []
    for berkas in sorted((akar / "app/web/templates").glob("*.html")):
        markup = re.sub(r"\{#.*?#\}", "", berkas.read_text(), flags=re.S)
        for tombol in re.findall(r"<button[^>]*>", markup):
            if "data-post" in tombol and "data-kirim" not in tombol:
                cacat.append(f"{berkas.name}: {tombol[:70]}")
    assert not cacat, "tombol ber-data-post tanpa data-kirim (diam saat ditekan): " \
                      + "; ".join(cacat)


def test_tombol_tutup_jasa_sungguh_tergambar_dan_muatannya_sah():
    """⚠ Cabang `boleh_tutup` DIRENDER, bukan cuma dibaca sebagai teks.

    Pesanan yang baru lahir tak pernah boleh ditutup (aturannya benar), jadi
    cabang ini tak pernah dilewati oleh percobaan lewat basis data — dan galat
    Jinja di dalamnya baru akan muncul di gudang, pada pesanan pertama yang
    memang sudah selesai.

    Muatannya diperiksa sebagai JSON SUNGGUHAN dan dibandingkan dengan bentuk
    yang rutenya terima (`JasaReq`): atribut yang kutipnya salah akan putus di
    karakter pertama muatannya, dan yang terkirim jadi JSON tak lengkap.
    """
    import json
    import re
    import types

    from app.web.aksi_inventory import JasaReq
    from app.web.tampilan import templates

    kartu = types.SimpleNamespace(
        id=7, kode="JAS-2610-077", pelanggan="Pak Budi", fase="barang_jadi",
        sisa=types.SimpleNamespace(gabah_kg=0, dryer_kg=0, silo_kg=0, pk_g1_kg=0,
                                   pk_g2_kg=0, barang_jadi_kg=0, ada=False),
        umur_hari=3, status="berjalan", boleh_tutup=True, sebab="")
    h = templates.get_template("jasa.html").render(
        request=None, akun=_akun("admin"), layar="jasa", MENUNGGU=0,
        MODE_UJI=False, LIHAT_SEBAGAI=None, kembali=None, CSRF="x",
        kartu=[kartu], FASE_JASA={}, tapis="berjalan", ton=0,
        STATUS_PILIHAN=(("berjalan", "Berjalan"),))

    assert "Tutup pesanan" in h
    m = re.search(r"data-kirim='([^']*)'", h)
    assert m, "tombol tutup tanpa data-kirim — ia akan diam saat ditekan"
    muatan = json.loads(m.group(1))
    # Bentuknya memang yang rutenya terima: `JasaReq(jasa=…)`.
    assert JasaReq(**muatan).jasa == "7"
