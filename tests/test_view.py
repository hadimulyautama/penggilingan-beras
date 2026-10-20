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
    """Pintu gabungan tersedia; pekerjaan meja tetap dibatasi di layanan/rute."""
    from app.web.nav import TAB
    view={t[0]:t[4] for t in TAB}
    assert set(view['audit'])==set(MEJA)
    assert 'keputusan' not in view and 'mutu' not in view
    for k in ('beranda','barang_masuk','pekerjaan','stok','laporan','pengaturan'):
        assert view[k] is None


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
#: Keluaran `services.beranda.angka_gudang` yang dititipkan ke `petak_beranda`.
#: Angka G2 sengaja dibuat BERBEDA antara stok dan tumpukan: kalau petaknya
#: keliru memungut tumpukan, ujinya harus gagal — dan tumpukan yang kebetulan
#: nol (keadaan hari QA menemukannya) membuat kekeliruan itu lolos.
ANGKA = {"masuk_kg": 1, "masuk_n": 1,
         "g1": {"stok_pk": 1, "tumpukan": 0},
         "g2": {"stok_pk": 10000, "tumpukan": 0},
         "tumpukan_g2_maks": 0}

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
        blok = await petak_beranda(None, view, o, angka=ANGKA)
        label = _label(blok)
        assert any(x in label for x in _G1_SAJA), view
        assert any(x in label for x in _G2_SAJA), view
        # Petaknya digambar DUA KOLOM. Blok berisi jumlah ganjil tampil
        # sebagai kotak setengah lebar dengan lubang di sebelahnya — dan
        # lubang itu terbaca sebagai sesuatu yang gagal dimuat.
        for b in blok:
            assert len(b["sel"]) % 2 == 0, (view, b["judul"])


async def test_stok_pk_admin_dari_layanan_bukan_dari_posisi_petak(monkeypatch):
    """"Stok PK G2" harus menyebut STOK, bukan tumpukan.

    Dulu dua petak itu dipetik berdasarkan POSISI — petak ke-4 tiap gudang —
    lalu keduanya diberi label "Stok PK". Petak ke-4 Gudang 1 memang stok PK;
    petak ke-4 Gudang 2 adalah "Tumpukan PK". Akibatnya, pada satu detik yang
    sama: Beranda Pos Produksi "Stok PK G2 0 kg", Beranda Meja "Stok PK 10.000
    kg" — dan yang benar 10.000 (silo A 6.000 + silo B 4.000). QA 24 September
    2026 (c) butir 3.

    Angka tumpukan di `ANGKA` sengaja NOL, seperti hari QA menemukannya: nol
    yang masuk akal itulah yang membuat kekeliruan ini bertahan.
    """
    from app.web import layar

    async def palsu(db):
        return [layar._sel("PK masuk", "1.000"), layar._sel("Penyosohan", 1),
                layar._sel("Silo terisi", 1), layar._sel("Tumpukan PK", "0")]

    monkeypatch.setattr(layar, "_petak_g2", palsu)
    o = {"gabah_hari_ini": {"total_kg": 1, "batch": 1}, "pengeringan": [],
         "silo": [], "giling": [], "stok_pk": {"total": 1, "maks": 0}}

    blok = await petak_beranda(None, ADMIN, o, angka=ANGKA)
    petak = {p["label"]: p["nilai"] for p in blok[0]["sel"]}
    assert petak["Stok PK G2"] == "10.000", "petak Admin memungut tumpukan, bukan stok"
    assert petak["Stok PK G1"] == "1"


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
            != await petak_beranda(None, ADMIN, o, angka=ANGKA))
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


def test_penyaring_gudang_sama_di_stok_dan_di_berjalan():
    """Pilihan gudang mempertahankan aturan tampilan dan nilai URL sah."""
    from app.web import layar_stok,layar_pekerjaan
    from pathlib import Path
    kode=inspect.getsource(layar_stok.halaman_stok)
    assert 'GUDANG if view in MEJA else ()' in kode
    src=inspect.getsource(layar_pekerjaan.halaman_pekerjaan)
    assert "pilihan(request, 'gudang', {'g1','g2'})" in src
    assert 'x.gudang == gudang' in src
    for nama in ('pekerjaan.html','barang_masuk.html'):
        t=(Path(__file__).resolve().parents[1]/'hmu_tampilan/templates'/nama).read_text()
        assert 'if VIEW in V_MEJA' in t and 'filter_gudang' in t


def test_saringan_stok_ikut_ke_seluruh_blok_halamannya():
    """Membuka "Gudang 1" lalu melihat barang jadi Gudang 2 di bawahnya
    membuat penyaringnya berbohong — kalimat yang sama sudah dipakai Meja.

    Karung PINDAH ke halamannya sendiri (`/stok-karung`) 7 Oktober 2026 dan
    tak lagi punya pil `?gudang=` di sini — lihat
    `test_stok_karung_filter_gudang1_tetap_ada_di_rute` (tests/test_stok.py)
    untuk penyaringnya yang sekarang."""
    from app.web import layar_stok

    kode = inspect.getsource(layar_stok.halaman_stok)
    assert 'gudang in ("", "g1")' in kode and 'gudang in ("", "g2")' in kode


def test_layar_stok_tak_menyebut_gudang_1_di_menu():
    """Keterangan pintunya dibaca juga oleh operator polesan, yang halaman
    Stoknya tak memuat satu pun barang Gudang 1."""
    from app.web.nav import TAB

    ket = {t[0]: t[3] for t in TAB}
    assert "Gudang 1" not in ket["stok"]


def test_kartu_gudang2_menyebut_asal_barangnya():
    """Aturan pemilik untuk SETIAP kartu. Kartu yang cuma menyebut jumlah tak
    memberi tahu PK siapa yang ada di dalamnya.

    Sampai 5 Oktober 2026 asalnya tersembunyi di laci "Pernah masuk" di dalam
    satu kartu Tumpukan bersama. Keputusan pemilik hari itu membuang lacinya:
    satu kartu kini SATU pemasukan (`t.kode` — "<asal> · <kode batch>"), jadi
    asalnya ada di KEPALA kartu, bukan lagi di rincian yang perlu dibuka —
    "Pernah masuk" sendiri cuma pernah berdiri di laci lama itu, jadi
    lenyapnya dari seluruh berkas inilah buktinya.
    """
    teks = ((AKAR / "hmu_tampilan/templates/stok.html").read_text()
            + (AKAR / "hmu_tampilan/templates/_stok_pk_daftar.html").read_text())
    assert "{{- t.kode" in teks or "{{ t.kode" in teks, "kepala kartu G2 tak menyebut asalnya"
    # Markup-nya persis, bukan sekadar frasanya — catatan di atas blok ini
    # SENGAJA menyebut nama laci lama sebagai sejarah; yang diperiksa di sini
    # elemennya, "Pernah masuk · {{ ... }}", bukan kalimat yang mengenangnya.
    assert "Pernah masuk ·" not in teks, "laci lama masih ada — kartu seharusnya tak berlaci lagi"


def test_kartu_gudang2_mutu_langsung_terlihat_tanpa_laci():
    """Keputusan pemilik 5 Oktober 2026: *"bagaimana kami bisa tau kualitas
    per kode bahan. tetap harus ditampilkan per kode bahan."* Mutu (`t.mutu`)
    harus tergambar di kepala kartu — di dalam `{% if mutu_aktif %}`, sama
    seperti kartu lot Gudang 1 — bukan dilipat di laci."""
    teks = ((AKAR / "hmu_tampilan/templates/stok.html").read_text()
            + (AKAR / "hmu_tampilan/templates/_stok_pk_daftar.html").read_text())
    detail = (AKAR / "hmu_tampilan/templates/_stok_pk_detail.html").read_text()
    assert "mutu_mobile(t.mutu, t.kelas)" in teks
    assert "for label, nilai in t.mutu" in detail
    assert "boleh_pindah_tumpukan" in teks, "tombol Masukkan ke silo tak ada"
    assert "pindah_tumpukan_silo" in detail


def test_tempat_hanya_tumpukan_dan_disaring_kosong():
    """Keputusan pemilik 4 Oktober 2026: silo tak boleh menyimpan stok berdiri
    di kartu Stok, dan isinya cuma hitungan masuk-keluar, bukan ukuran fisik.
    Jadi `pk_gudang2` tak boleh lagi menyebut silo sama sekali, dan Tumpukan
    kini memakai aturan Gudang 1 — habis = tak didaftar — bukan aturan silo
    lama ("tempat kosong tetap ditampilkan")."""
    from app.services import stok

    sumber = inspect.getsource(stok.pk_gudang2)
    # Yang dilarang: membangun baris silo sama sekali — bukan sekadar
    # menyebut katanya (docstring-nya sendiri menjelaskan KENAPA tak ada).
    assert "hitung_stok_silo" not in sumber and 'kode=f"Silo' not in sumber
    assert "if tump <= 0" in sumber and "return []" in sumber


# ─────────────────── Pengaturan: yang hanya milik pemilik ───────────────────

def test_orang_dan_alat_milik_view_super():
    """Daftar peran berbunyi: Super Admin = "semua di atas, DITAMBAH
    mengelola orang, akun, dan alat".

    Syaratnya pindah dari templat ke RUTE pada Tahap 2 (23 September 2026):
    `pengaturan.html` satu berkas di paket untuk tiga app, dan templat bersama
    tak boleh menebak peran — ia memasang blok yang app-nya nyatakan. Jadi yang
    diperiksa di sini syarat di rutenya, dan bahwa templatnya memang cuma
    membaca benderanya.
    """
    import inspect

    from app.web import pengaturan

    rute = inspect.getsource(pengaturan.halaman_pengaturan)
    assert "blok_kelola=view == V_SUPER" in rute
    assert "akun.is_admin" not in rute

    teks = (AKAR / "hmu_tampilan/templates/pengaturan.html").read_text()
    assert "{% if blok_kelola %}" in teks
    assert "VIEW == V_SUPER" not in teks, "templat bersama menebak peran lagi"


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

    # Syaratnya di RUTE sejak Tahap 2 — templatnya bersama untuk tiga app.
    rute = inspect.getsource(pengaturan.halaman_pengaturan)
    assert "tuan and not ada_super" in rute
    assert "ada_super=ada_super" in rute
    # Dan kalimat yang menjelaskan kenapa bloknya masih terbuka ikut dipasang
    # hanya selama pinjaman itu berlaku: blok yang muncul lalu hilang sendiri
    # tanpa keterangan terbaca sebagai aplikasi yang berubah-ubah.
    assert "kelola_darurat=view != V_SUPER" in rute
    teks = (AKAR / "hmu_tampilan/templates/pengaturan.html").read_text()
    assert "{% if kelola_darurat %}" in teks
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

    view = {t[0]: t[4] for t in TAB}
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
    # Daftar tombolnya pindah dari templat ke RUTE pada Tahap 2 (23 September
    # 2026): `aksi.html` satu berkas di paket untuk tiga app. Diuji sebagai
    # PERILAKU per view, bukan sebagai kalimat di markup — yang harus tetap
    # benar adalah jawabannya, juga bila namanya berubah.
    from app.main import _pintasan_aksi
    from app.web.layar import ADMIN, POLESAN, SELEPAN, SUPER, TAMU

    selepan = dict(_pintasan_aksi(SELEPAN))
    assert "undo" in selepan, "selepan kehilangan tombol batalkan"

    # Polesan membawa dua aksinya yang tak berkartu ke tempat yang sama:
    # packing & bekatul curah lahir SESUDAH proses ditutup.
    polesan = dict(_pintasan_aksi(POLESAN))
    assert set(polesan) == {"undo", "catat_packing", "catat_bekatul"}

    # View lain masih punya katalognya di laci, dan dua pintu ke satu hal
    # adalah dua tempat di kepala orang.
    for view in (ADMIN, SUPER, TAMU):
        assert _pintasan_aksi(view) == (), view

    # Templat bersama hanya MENGGAMBAR daftarnya; ia tak menebak siapa.
    teks = (AKAR / "hmu_tampilan/templates/aksi.html").read_text()
    assert "{% if PINTASAN %}" in teks
    assert "buka=undo" not in teks and "V_SELEPAN" not in teks


def test_layar_kosong_tak_menunjuk_pintu_yang_dicabut():
    """Ajakan menuju halaman yang tak dimiliki pembacanya adalah jalan buntu
    yang tak terlihat sebagai jalan buntu.

    Diuji dengan MERENDER layarnya, bukan dengan membaca syaratnya. Pada 23
    September 2026 syarat yang benar tetap ada di berkasnya tetapi tak berlaku:
    kalimat ini pindah ke makro `_kata_aksi.html`, dan makro yang diimpor TANPA
    `with context` tidak melihat `VIEW` — `Undefined not in (…)` bernilai True,
    jadi ajakannya muncul justru bagi yang tak punya pintunya. Uji yang membaca
    syaratnya lulus; yang menangkapnya potret HTML per peran. Sejak itu uji ini
    membaca HASILNYA.
    """
    import types

    from app.web.layar import ADMIN, POLESAN, SELEPAN, SUPER, TAMU
    from app.web.tampilan import templates

    def gambar(view: str) -> str:
        akun = types.SimpleNamespace(nama="Uji", sesi_pendek=False)
        return templates.get_template("aksi.html").render(
            request=None, akun=akun, layar="aksi", VIEW=view, LIHAT_SEBAGAI=None,
            PERAN_ASLI=view, CSRF="c", TERIK=False, MENUNGGU=0, BERJALAN=0,
            KEPUTUSAN=0, MODE_UJI=False, kembali=None, menunggu=[], berjalan=[],
            buka="", nilai="", lama=lambda t: "",
            KELOMPOK_ATAS="tumpukan", judul_atas="Menumpuk di lantai",
            judul_bawah="Bisa dikerjakan sekarang", PINTASAN=())

    # Operator tak mendapat laci "Catat pekerjaan lain" — jadi tak diajak.
    for view in (SELEPAN, POLESAN):
        html = gambar(view)
        assert "Tidak ada yang menunggu Anda" in html, view
        assert "/aksi-lain" not in html, f"{view} diajak ke pintu yang dicabut"

    # Yang memang punya pintunya tetap diajak.
    for view in (ADMIN, SUPER, TAMU):
        assert "/aksi-lain" in gambar(view), view

    # Dan paket tak memuat ajakan itu: Gudang 2 menawarkan katalognya, Pos
    # Produksi tidak, dan paket tak tahu yang mana.
    paket = (AKAR / "hmu_tampilan/templates/aksi.html").read_text()
    assert '<a href="/aksi-lain">' not in paket
    # Makronya WAJIB diimpor `with context`, kalau tidak syarat di dalamnya
    # tak pernah berlaku.
    assert '{% import "_kata_aksi.html" as kata with context %}' in paket


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


def test_kalimat_pengalih_hanya_untuk_pemegang_kedua_gudang():
    """Antrean gudang pindah layar untuk admin ke atas — dan itu benar.

    `berjalan.untuk()` menaruh kartu silo & mesin di `transit` bagi yang
    memegang KEDUA gudang ("keadaan fisik gudang adalah kabar, bukan tugasnya"),
    dan `/aksi` hanya merender `menunggu`. Pemilik melaporkannya 23 September
    2026: "sebagai super admin saya tidak melihat antrian tunggu untuk gudang
    2" — padahal ia ada, di layar sebelah. Pembagiannya TIDAK diubah; yang
    ditambahkan hanya kalimat yang menyebutkannya.

    Diuji per peran dengan MERENDER layarnya, dan syaratnya dibaca dari sumber
    yang sama yang memindahkan kartunya (`can_see_financials`) — supaya kalimat
    dan perpindahan tak pernah bisa berselisih.
    """
    import types

    from app.peran import can_see_financials
    from app.web.tampilan import templates

    def gambar(*, pengalih: bool, ada_isi: bool) -> str:
        akun = types.SimpleNamespace(nama="Uji", sesi_pendek=False)
        b = [("Silo A", "1", "x")] if ada_isi else []
        return templates.get_template("aksi.html").render(
            request=None, akun=akun, layar="aksi", VIEW="x", LIHAT_SEBAGAI=None,
            PERAN_ASLI="x", CSRF="c", TERIK=False, MENUNGGU=0, BERJALAN=0,
            KEPUTUSAN=0, MODE_UJI=False, kembali=None, berjalan=[],
            menunggu=[types.SimpleNamespace(
                kode="Silo A", isi="PK", keadaan="", aksi=None, nilai=None,
                sejak=None, fase="silo", pilihan=[], judul="Silo A", utama=None,
                sub=None, fakta=[], anak=[], nota=None, nota_jenis=None,
                catatan=[], tombol=[], kelompok=None, ringkas=None, maju=None)
            ] if ada_isi else [],
            buka="", nilai="", lama=lambda t: "", KELOMPOK_ATAS="tumpukan",
            judul_atas="Menumpuk di lantai", judul_bawah="Bisa dikerjakan sekarang",
            PINTASAN=(), blok_pengalih=pengalih)

    # Admin ke atas: kalimatnya ada, dan ia menunjuk layar yang benar.
    html = gambar(pengalih=True, ada_isi=True)
    assert "Silo &amp; mesin kedua gudang ada di" in html
    assert 'href="/berjalan"' in html

    # Operator: tak ada yang pindah, jadi tak ada yang diterangkan.
    assert "kedua gudang ada di" not in gambar(pengalih=False, ada_isi=True)

    # ANTREAN KOSONG pun tetap, dan justru terutama saat itu: bagi admin
    # antrean ini memang kosong — itulah layar yang melahirkan keluhannya.
    # Percobaan pertama memberinya syarat "hanya bila berisi", dan potret per
    # peran memperlihatkan kalimatnya hilang tepat di layar yang membutuhkannya.
    assert "kedua gudang ada di" in gambar(pengalih=True, ada_isi=False)

    # Dan rutenya memakai syarat yang SAMA dengan yang memindahkan kartunya.
    from app import main

    rute = inspect.getsource(main.halaman_aksi)
    assert "halaman_pekerjaan(request,akun)" in rute
    pindah = inspect.getsource(__import__(
        "app.services.berjalan", fromlist=["untuk"]).untuk)
    assert "can_see_financials(user)" in pindah
    assert callable(can_see_financials)
