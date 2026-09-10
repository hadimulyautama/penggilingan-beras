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
    # `staff` peran LAMA yang masih sah di baris `users` lama.
    assert await view_untuk(_Orang("staff")) == ADMIN


async def test_operator_dipisah_menurut_gudangnya(monkeypatch):
    from app.web import miniapp

    async def g2(user):
        return user.default_warehouse_id == 2

    async def g1(user):
        return user.default_warehouse_id == 1

    monkeypatch.setattr(miniapp, "_is_g2_operator", g2)
    monkeypatch.setattr(miniapp, "_is_g1_operator", g1)

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

    assert "PERAN_STAF_KEATAS" in inspect.getsource(layar.view_untuk)


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
    teks = (AKAR / "app/web/templates/base.html").read_text()
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

def test_orang_dan_alat_hanya_di_view_super():
    """Daftar peran berbunyi: Super Admin = "semua di atas, DITAMBAH
    mengelola orang, akun, dan alat"."""
    teks = (AKAR / "app/web/templates/pengaturan.html").read_text()
    assert "{% if VIEW == V_SUPER %}" in teks
    assert "akun.is_admin" not in teks


def test_rutenya_belum_dipersempit():
    """Yang diubah TAMPILAN, bukan wewenang. Uji ini bukan restu — ia catatan
    bahwa keduanya belum sejalan, supaya perbedaannya disengaja dan bukan
    ditemukan orang lain sebagai kejutan."""
    from app.web import pengguna

    assert "butuh_admin" in inspect.getsource(pengguna.halaman_pengguna)


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
    # Polesan TETAP memilikinya: pekerjaan Gudang 2 belum seluruhnya berkartu.
    assert POLESAN in view["aksi_lain"]
    for v in MEJA:
        assert v in view["aksi_lain"], v


def test_alamat_katalog_ikut_ditutup_bukan_cuma_pintunya():
    """Halaman yang katanya tak ada tetapi tetap terbuka adalah halaman yang
    tetap ada — alamatnya bisa diketik, atau tersimpan sebagai pintasan."""
    from app import main

    sumber = inspect.getsource(main.halaman_aksi_lain)
    assert "== SELEPAN" in sumber and 'RedirectResponse("/aksi"' in sumber


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
    assert sebelum.rstrip().split("\n")[-3:][0].strip() == "{% if VIEW == V_SELEPAN %}"


def test_layar_kosong_tak_menunjuk_pintu_yang_dicabut():
    """Ajakan menuju halaman yang tak dimiliki pembacanya adalah jalan buntu
    yang tak terlihat sebagai jalan buntu."""
    teks = (AKAR / "app/web/templates/aksi.html").read_text()
    tautan = teks.split('<a href="/aksi-lain">')[0]
    assert "VIEW != V_SELEPAN" in tautan
