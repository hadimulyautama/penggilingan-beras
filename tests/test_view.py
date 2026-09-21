"""Empat view, dan yang dijaga adalah bahwa keempatnya memang BERBEDA.

Sebelum ini aplikasi punya dua tampilan yang menyamar sebagai empat: "admin
ke atas" dan "selebihnya". Dua pasang orang karenanya melihat layar yang bukan
miliknya — Super Admin dan Admin persis sama, operator polesan mendapat layar
yang dibentuk untuk selepan.

Uji di berkas ini menolak kemunduran ke sana. Yang paling penting bukan
"Beranda menampilkan angka yang benar" melainkan "Beranda operator polesan
TIDAK menampilkan angka Gudang 1" — kesalahan pertama kelihatan, kesalahan
kedua tidak, dan yang tidak kelihatan itulah yang bertahan berbulan-bulan.
"""
from __future__ import annotations

import inspect
import pathlib

import pytest

from app.web.layar import (ADMIN, MEJA, POLESAN, SELEPAN, SUPER, TAMU,
                           gudang1, gudang2, petak_beranda, view_untuk)

AKAR = pathlib.Path(__file__).resolve().parents[1]


class _Orang:
    def __init__(self, role, wid=None):
        self.role = role
        self.default_warehouse_id = wid


# ─────────────────────────── Siapa dapat view apa ───────────────────────────

async def test_peran_meja_tak_perlu_bertanya_ke_gudang():
    """Super Admin dan Admin dijawab dari perannya saja.

    Bukan sekadar cepat: `_is_g*_operator` menjawab True untuk admin ke atas
    (mereka memang boleh mengerjakan aksi kedua gudang), jadi menanyakannya
    di sini akan menjatuhkan Super Admin ke view operator — gudang mana pun
    yang kebetulan diperiksa lebih dulu.
    """
    assert await view_untuk(_Orang("superadmin")) == SUPER
    assert await view_untuk(_Orang("admin")) == ADMIN
    # `staff` DIPENSIUNKAN (15 Sep 2026): bukan admin, bukan operator — tamu.
    assert await view_untuk(_Orang("staff")) == TAMU


async def test_operator_dipisah_menurut_gudangnya(monkeypatch):
    from app.web import api

    async def g2(user):
        return user.default_warehouse_id == 2

    async def g1(user):
        return user.default_warehouse_id == 1

    monkeypatch.setattr(api, "_is_g2_operator", g2)
    monkeypatch.setattr(api, "_is_g1_operator", g1)

    assert await view_untuk(_Orang("operator", 1)) == SELEPAN
    assert await view_untuk(_Orang("operator", 2)) == POLESAN
    # Operator tanpa gudang bukan view kelima — ia kesalahan pendaftaran.
    assert await view_untuk(_Orang("operator", None)) == TAMU


async def test_tanpa_akun_dan_peran_ngawur_jatuh_ke_tamu():
    assert await view_untuk(None) == TAMU
    for ngawur in ("", "dewa", "  ", "ADMIN; DROP TABLE users"):
        assert await view_untuk(_Orang(ngawur)) == TAMU, ngawur


def test_tangga_peran_tak_ditulis_ulang():
    """Peran disebut satu per satu adalah cara peran baru tertinggal di
    gerbang — sudah terjadi delapan kali di aplikasi ini."""
    from app.web import layar

    # Sejak Tahap 2 tangganya milik paket `hmu_identitas.peran`: view
    # diputuskan `P.view(...)`, bukan daftar nama yang ditulis ulang di sini.
    sumber = inspect.getsource(layar.view_untuk)
    assert "P.view(" in sumber and '"superadmin"' not in sumber


def test_lingkup_gudang_per_view():
    assert gudang1(SELEPAN) and not gudang2(SELEPAN)
    assert gudang2(POLESAN) and not gudang1(POLESAN)
    for v in MEJA:
        assert gudang1(v) and gudang2(v)


# ─────────────────────────── Laci: pintu per view ───────────────────────────

def test_pintu_meja_tertutup_bagi_operator():
    """Keputusan & List audit bukan milik operator — keduanya, bukan salah
    satu. Yang menjaga sungguhan tetap rutenya; ini soal tak menawarkan
    pintu yang akan ditolak."""
    from app.web.nav import TAB

    view = {k: v for k, _, _, _, v in TAB}
    for kunci in ("keputusan", "audit"):
        assert set(view[kunci]) == set(MEJA), kunci

    # Pintu yang dimiliki KEEMPAT view ditulis None, bukan daftar berisi
    # empat nama: daftar yang harus ditambah tiap kali ada view baru adalah
    # daftar yang suatu hari lupa ditambah.
    for kunci in ("beranda", "aksi", "berjalan", "stok", "laporan", "pengaturan"):
        assert view[kunci] is None, kunci


def test_laci_memakai_isi_kolomnya_bukan_sekadar_terisi_atau_tidak():
    """Dulu templat memeriksa "kolomnya terisi?" lalu membandingkan peran
    dengan PERAN_ADMIN_KEATAS — jadi kolomnya boolean yang menyamar sebagai
    nama peran, dan "Super Admin saja" tak bisa ditulis sama sekali."""
    teks = (AKAR / "hmu_tampilan/templates/base.html").read_text()
    assert "VIEW in peran_min" in teks
    assert "PERAN_ADMIN_KEATAS" not in teks


# ────────────────────────── Beranda: empat bentuk ──────────────────────────

def _label(blok):
    return [s["label"] for b in blok for s in b["sel"]]


#: Angka yang HANYA ada di Gudang 1, dan yang hanya di Gudang 2. Dipakai
#: untuk membuktikan tak ada kebocoran antar gudang di layar operator.
_G1_SAJA = ("Gabah masuk", "Pengeringan")
_G2_SAJA = ("PK masuk", "Penyosohan")


async def test_beranda_selepan_tak_berubah():
    """Pemilik menyebutnya sendiri: "sejauh ini optimal untuk gudang
    selepan". Yang optimal tidak diperbaiki hanya karena tetangganya sedang
    dibuat."""
    o = {"gabah_hari_ini": {"total_kg": 41200, "batch": 3},
         "pengeringan": [1], "silo": [{"terisi": True}, {"terisi": False}],
         "giling": [1], "stok_pk": {"total": 8000, "maks": 30000}}
    blok = await petak_beranda(None, SELEPAN, o)
    assert len(blok) == 1 and blok[0]["judul"] is None
    assert _label(blok) == ["Gabah masuk", "Pengeringan", "Silo terisi", "Stok PK"]


async def test_beranda_polesan_tak_menyebut_gudang_sebelah(monkeypatch):
    """Inilah kesalahan yang tak kelihatan: operator polesan disambut empat
    angka Gudang 1, membaca kabar dari gudang sebelah, lalu berhenti membaca
    baris teratas Beranda selamanya."""
    from app.web import layar

    async def palsu(db):
        return [layar._sel("PK masuk", "1.000"), layar._sel("Penyosohan", 1),
                layar._sel("Silo terisi", 1), layar._sel("Tumpukan PK", "500")]

    monkeypatch.setattr(layar, "_petak_g2", palsu)
    blok = await petak_beranda(None, POLESAN, {})
    label = _label(blok)
    assert len(blok) == 1
    for dilarang in _G1_SAJA:
        assert dilarang not in label, dilarang


async def test_beranda_meja_memuat_kedua_gudang(monkeypatch):
    """Admin dan Super Admin memegang dua gudang. Yang tak terlihat oleh
    siapa pun akan terlewat."""
    from app.web import layar

    async def palsu(db):
        return [layar._sel("PK masuk", "1.000"), layar._sel("Penyosohan", 1),
                layar._sel("Silo terisi", 1), layar._sel("Tumpukan PK", "500")]

    monkeypatch.setattr(layar, "_petak_g2", palsu)
    o = {"gabah_hari_ini": {"total_kg": 1, "batch": 1}, "pengeringan": [],
         "silo": [], "giling": [], "stok_pk": {"total": 1, "maks": 0}}

    for view in MEJA:
        blok = await petak_beranda(None, view, o)
        label = _label(blok)
        assert any(x in label for x in _G1_SAJA), view
        assert any(x in label for x in _G2_SAJA), view
        # Petaknya digambar DUA KOLOM. Blok berisi jumlah ganjil tampil
        # sebagai kotak setengah lebar dengan lubang di sebelahnya — dan
        # lubang itu terbaca sebagai sesuatu yang gagal dimuat.
        for b in blok:
            assert len(b["sel"]) % 2 == 0, (view, b["judul"])


async def test_super_dan_admin_tidak_lagi_sama(monkeypatch):
    """Daftar peran sudah lama menuliskan bedanya; layarnya belum pernah
    menunjukkannya."""
    from app.web import layar

    async def palsu(db):
        return [layar._sel(n, 0) for n in
                ("PK masuk", "Penyosohan", "Silo terisi", "Tumpukan PK")]

    monkeypatch.setattr(layar, "_petak_g2", palsu)
    o = {"gabah_hari_ini": {}, "pengeringan": [], "silo": [], "giling": [],
         "stok_pk": {}}
    assert (await petak_beranda(None, SUPER, o)
            != await petak_beranda(None, ADMIN, o))
    # Super Admin melihat kedua gudang sebagai blok BERNAMA — dua baris
    # tanpa judul memaksa orang menebak angka mana milik gudang mana.
    assert all(b["judul"] for b in await petak_beranda(None, SUPER, o))


def test_beranda_tak_memanggil_gudang1_untuk_polesan():
    """`dashboard_data` mahal dan seluruhnya Gudang 1. Operator polesan yang
    menunggunya membayar waktu untuk angka yang tak akan tampil."""
    from app import main

    sumber = inspect.getsource(main.beranda)
    assert "if gudang1(view)" in sumber


# ─────────────────────────── Stok: dua gudang ───────────────────────────

def test_stok_mengikuti_view_pembacanya():
    from app.web import layar_stok

    sumber = inspect.getsource(layar_stok.halaman_stok)
    assert "gudang1(view)" in sumber and "gudang2(view)" in sumber
    # Koreksi hasil giling milik Gudang 1; operator polesan tak punya hasil
    # giling untuk dikoreksi.
    assert "view != POLESAN" in sumber


def test_layar_stok_tak_menyebut_gudang_1_di_menu():
    """Keterangan pintunya dibaca juga oleh operator polesan, yang halaman
    Stoknya tak memuat satu pun barang Gudang 1."""
    from app.web.nav import TAB

    ket = {k: t for k, _, _, t, _ in TAB}
    assert "Gudang 1" not in ket["stok"]


def test_kartu_gudang2_menyebut_asal_barangnya():
    """Aturan pemilik untuk SETIAP kartu. Silo yang cuma menyebut jumlah tak
    memberi tahu PK siapa yang ada di dalamnya."""
    teks = (AKAR / "app/web/templates/stok.html").read_text()
    assert "Pernah masuk" in teks and "anak__baris" in teks


def test_tempat_kosong_tetap_didaftar():
    """Aturan Gudang 1 sengaja dibalik di sini: di sana barisnya LOT, dan lot
    yang habis memang tak ada lagi. Di sini barisnya TEMPAT, dan tempat yang
    kosong tetap ada — silo yang hilang dari daftar terbaca sebagai silo yang
    rusak atau data yang gagal dimuat."""
    from app.services import stok

    sumber = inspect.getsource(stok.pk_gudang2)
    # Yang dilarang: menyaring tempat menurut isinya. Satu-satunya `continue`
    # yang sah adalah silo yang memang tak ada barisnya di basis data.
    assert "if stok <= 0" not in sumber and "if stok:" not in sumber
    assert sumber.count("continue") == 1 and "if silo is None" in sumber


# ─────────────────── Pengaturan: yang hanya milik pemilik ───────────────────

def test_orang_dan_alat_milik_view_super():
    """Daftar peran berbunyi: Super Admin = "semua di atas, DITAMBAH
    mengelola orang, akun, dan alat"."""
    teks = (AKAR / "app/web/templates/pengaturan.html").read_text()
    assert "VIEW == V_SUPER" in teks
    assert "akun.is_admin" not in teks


def test_blok_sistem_tak_bisa_mengunci_semua_orang():
    """Pabrik ini menjalankan SATU akun Admin dan NOL Super Admin. Blok yang
    ketat kepada Admin karenanya menyembunyikan dirinya dari semua orang —
    dan satu-satunya jalan mengangkat Super Admin pertama ada di balik pintu
    yang baru saja ditutup untuk semua. Kunci yang ditinggal di dalam rumah.

    Menyembuhkan dirinya sendiri: begitu ada satu Super Admin aktif, bloknya
    berpindah ke layarnya tanpa ada yang perlu menyentuh apa pun.
    """
    import inspect

    from app.web import pengaturan

    teks = (AKAR / "app/web/templates/pengaturan.html").read_text()
    assert "tuan and not ada_super" in teks
    assert "ada_super=ada_super" in inspect.getsource(pengaturan.halaman_pengaturan)
    # Hitungannya hanya akun AKTIF: Super Admin yang dinonaktifkan tak bisa
    # membuka pintu apa pun, jadi menganggapnya ada sama saja mengunci.
    from app.web import security

    # Hitungannya milik paket identitas (akun aktif DAN orangnya aktif,
    # peran superadmin) — dipakai timbangan dengan aturan yang sama.
    hitung = inspect.getsource(security.ada_superadmin)
    assert "ada_superadmin_aktif" in hitung


def test_pintu_dan_gerbang_memakai_aturan_yang_SAMA():
    """Blok yang tampil lalu menolak saat ditekan lebih buruk daripada blok
    yang tak tampil: yang pertama membuat orang mengira aplikasinya rusak,
    yang kedua cuma tak menawarkan.

    Sempat terjadi persis begitu — layar Pengaturan memakai jaring pengaman
    "belum ada Super Admin", rutenya tidak, jadi Direksi melihat pintunya lalu
    dijawab 403. Keduanya kini bertanya pada fungsi yang sama.
    """
    from app.web import pengaturan, security

    assert "ada_superadmin" in inspect.getsource(security.butuh_super)
    assert "ada_superadmin" in inspect.getsource(pengaturan.halaman_pengaturan)


def test_jaring_pengaman_tak_bisa_dijadikan_jalan_naik():
    """Untuk sampai ke keadaan "tak ada Super Admin", seseorang harus
    menurunkan Super Admin terakhir — dan itu hanya bisa dikerjakan di balik
    pintu yang sama, lewat penjaga yang menolak penurunan itu."""
    from app.web import pengguna, security

    # Jaringnya cuma untuk yang sudah Direksi, bukan siapa saja.
    assert "akun.is_admin" in inspect.getsource(security.butuh_super)
    # Dan penjaga penurunan tetap berdiri.
    assert "admin-terakhir" in inspect.getsource(pengguna.simpan_ubah)


def test_orang_akun_dan_alat_dikunci_ke_super_admin():
    """Tampilan dan wewenang akhirnya sejalan — atas keputusan pemilik, sesudah
    ia mengangkat akun Super Admin pertama pada 10 September 2026.

    Bukan soal kerapian melainkan soal tangga: yang bisa mengelola akun bisa
    mengubah peran, termasuk perannya sendiri. Selama Direksi boleh masuk ke
    halaman ini, tangganya tak punya puncak.
    """
    from app.web import mode_uji, pengaturan, pengguna

    # Seluruh pengelolaan orang & akun.
    sumber = inspect.getsource(pengguna)
    assert "butuh_admin" not in sumber, "masih ada gerbang Direksi di Kelola pengguna"
    for fn in (pengguna.halaman_pengguna, pengguna.orang_baru,
               pengguna.reset_sandi, pengguna.simpan_ubah):
        assert "butuh_super" in inspect.getsource(fn), fn.__name__

    # Alat — dryer & silo.
    assert "butuh_super" in inspect.getsource(pengaturan.halaman_alat)
    assert "butuh_super" in inspect.getsource(pengaturan.tambah_silo)

    # Menghapus data uji.
    assert "akun.is_super" in inspect.getsource(mode_uji.hapus)


def test_setelan_kerja_TETAP_milik_direksi():
    """Yang dikunci pengelolaan ORANG, AKUN, dan ALAT — bukan setelan kerja.

    Target kadar air, sebab berhenti, dan sakelar mutu adalah keputusan
    operasional harian. Menguncinya ke Super Admin berarti tiap penyetelan
    kecil menunggu satu orang, dan yang menunggu satu orang akan dikerjakan
    dengan cara lain.
    """
    from app.web import pengaturan

    for fn in (pengaturan.ubah_target_bawaan, pengaturan.ubah_fitur_mutu,
               pengaturan.ubah_sebab_jeda):
        sumber = inspect.getsource(fn)
        assert "butuh_admin" in sumber, fn.__name__
        assert "butuh_super" not in sumber, fn.__name__


def test_tak_seorang_pun_mengangkat_di_atas_dirinya():
    """Yang bisa mengangkat orang setinggi dirinya bisa mengangkat dirinya
    sendiri. Dijaga di KEDUA jalan masuk — mengubah peran, dan mendaftarkan
    orang baru — karena yang dijaga cuma satu akan dilewati lewat yang lain.
    """
    from app.web import pengguna

    for fn in (pengguna.simpan_ubah, pengguna.orang_baru):
        sumber = inspect.getsource(fn)
        assert "terlalu-tinggi" in sumber, fn.__name__
        assert "terlalu_tinggi(" in sumber, fn.__name__


@pytest.mark.parametrize("view", [SUPER, ADMIN, SELEPAN, POLESAN])
def test_tiap_view_punya_namanya_sendiri(view):
    """Kepala laci menyebut view, bukan peran mentah: "operator" tak menjawab
    "gudang mana" di pabrik yang punya dua."""
    from app.web.layar import NAMA_VIEW

    assert NAMA_VIEW[view] and NAMA_VIEW[view] != view
    assert len({NAMA_VIEW[v] for v in (SUPER, ADMIN, SELEPAN, POLESAN)}) == 4


# ────────────── Katalog "Catat pekerjaan lain" bukan milik selepan ──────────────

def test_katalog_dicabut_dari_selepan():
    """Dari 13 aksi yang diterima operator selepan, 12 dikerjakan dari kartu
    di Antrian tunggu. Katalognya cuma pintu kedua ke pekerjaan yang sudah
    punya pintu."""
    from app.web.nav import TAB

    view = {k: v for k, _, _, _, v in TAB}
    assert SELEPAN not in view["aksi_lain"]
    # Polesan menyusul 21 September 2026: penyosohan, tumpukan → silo, dan
    # PK yang menunggu ditempatkan sudah berkartu; sisanya ke kaki antrean.
    assert POLESAN not in view["aksi_lain"]
    for v in MEJA:
        assert v in view["aksi_lain"], v


def test_alamat_katalog_ikut_ditutup_bukan_cuma_pintunya():
    """Halaman yang katanya tak ada tetapi tetap terbuka adalah halaman yang
    tetap ada — alamatnya bisa diketik, atau tersimpan sebagai pintasan."""
    from app import main

    sumber = inspect.getsource(main.halaman_aksi_lain)
    assert "in (SELEPAN, POLESAN)" in sumber and 'RedirectResponse("/aksi"' in sumber


def test_membatalkan_tidak_ikut_terbuang():
    """"Batalkan input terakhir" satu-satunya aksi selepan yang tak berwujud
    benda di gudang, jadi ia tak punya kartu dan akan hilang sama sekali
    bersama katalognya. Tiap salah ketik lalu berubah jadi panggilan telepon
    ke Admin."""
    teks = (AKAR / "app/web/templates/aksi.html").read_text()
    assert "/aksi?buka=undo" in teks
    # Hanya di layar yang kehilangan katalognya. View lain masih punya
    # katalognya, dan dua pintu ke satu hal adalah dua tempat di kepala orang.
    sebelum = teks.split("/aksi?buka=undo")[0]
    assert "{% if VIEW in (V_SELEPAN, V_POLESAN) %}" in sebelum
    assert "{% if VIEW in (V_SELEPAN, V_POLESAN) %}" not in teks.split("/aksi?buka=undo")[1]
    # Polesan membawa dua aksinya yang tak berkartu ke tempat yang sama.
    assert "/aksi?buka=catat_packing" in teks and "/aksi?buka=catat_bekatul" in teks


def test_layar_kosong_tak_menunjuk_pintu_yang_dicabut():
    """Ajakan menuju halaman yang tak dimiliki pembacanya adalah jalan buntu
    yang tak terlihat sebagai jalan buntu."""
    teks = (AKAR / "app/web/templates/aksi.html").read_text()
    tautan = teks.split('<a href="/aksi-lain">')[0]
    assert "VIEW not in (V_SELEPAN, V_POLESAN)" in tautan


# ─────────── Puncak tangga harus bisa diisi, dan tak boleh dikosongkan ───────────

def test_admin_terakhir_boleh_NAIK_jadi_super_admin():
    """Penjaga "akun tertinggi terakhir" dulu membandingkan NAMA peran, bukan
    tingkatnya: `peran != "admin"` menolak Admin terakhir yang mau naik ke
    Super Admin — padahal tingkatnya bertambah, bukan berkurang.

    Akibatnya di pabrik yang Super Admin-nya belum pernah diangkat, puncak
    tangga tak bisa diisi oleh siapa pun, selamanya. Ditemukan pemilik pada
    10 September 2026, saat mencoba menaikkan akunnya sendiri.
    """
    import inspect

    from app.web import pengguna

    sumber = inspect.getsource(pengguna.simpan_ubah)
    assert "TINGKAT" in sumber, "penjaga masih membandingkan nama peran"
    assert 'peran != "admin"' not in sumber


def test_super_admin_terakhir_tak_boleh_diturunkan():
    """Lubang kedua di penjaga yang sama, arah sebaliknya: syaratnya menyala
    hanya bila peran LAMA-nya "admin", jadi Super Admin terakhir yang
    diturunkan jadi operator lolos — persis lubang yang penjaga ini dibuat
    untuk menutup."""
    import inspect

    from app.web import pengguna

    sumber = inspect.getsource(pengguna.simpan_ubah)
    assert 'a.user.role == "admin"' not in sumber
    assert "a.is_admin" in sumber and "turun" in sumber


def test_tingkat_menjawab_naik_turun_dengan_benar():
    """Perbandingannya diuji langsung, bukan cuma keberadaan namanya di kode."""
    from app.web.lihat_sebagai import TINGKAT

    def turun(lama, baru):
        return TINGKAT.get(baru, 0) < TINGKAT.get(lama, 0)

    assert not turun("admin", "superadmin"), "naik ke Super Admin bukan turun"
    assert turun("superadmin", "admin")
    assert turun("admin", "operator")
    assert turun("superadmin", "operator")
    assert not turun("operator", "admin")
    # Peran yang tak dikenal bernilai 0 — dianggap turun, dan menolak itu
    # sikap yang benar untuk akun tertinggi terakhir.
    assert turun("admin", "dewa")
