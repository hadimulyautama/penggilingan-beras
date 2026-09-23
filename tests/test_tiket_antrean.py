"""Tiket timbang MASUK yang belum dicatat — dan yang dijaga: ia sampai ke
antrean POS PRODUKSI, bukan hanya ke Meja.

Kelas galat yang sudah muncul empat kali di repo ini: **pekerjaan yang ada di
data tetapi tak pernah digambar di layar.** Tiket PK adalah kemunculan yang
paling mahal, sebab pemilik melaporkannya dan perbaikan pertama (7c26a0f)
mendarat di `web/meja_api.py` — modul yang HANYA dipanggil app Meja. Tangkapan
layar pemilik sepanjang 23-24 September semuanya Pos Produksi, jadi jaring itu
tak menyentuh keluhannya sama sekali. Temuan QA 24 September 2026.

Uji di berkas ini menolak kemunduran ke sana: pemancarnya harus tinggal di
`services/berjalan.py` — tempat SEMUA app mengambil antreannya — dan terpasang
pada ketiga jalur peran.
"""
from __future__ import annotations

import ast
import inspect
import pathlib

from tests.bantu import kode_saja

AKAR = pathlib.Path(__file__).resolve().parents[1]


def test_pemancar_tiket_tinggal_di_layanan_bukan_di_api_meja():
    """Sumbernya satu. Dua daftar tiket cepat atau lambat berselisih, dan yang
    salah adalah yang lebih jarang dibuka orang."""
    from app.services import berjalan as svc
    from app.web import meja_api

    assert hasattr(svc, "_tiket_pk_luar") and hasattr(svc, "_tiket_jenis_tak_dikenal")
    sumber_meja = inspect.getsource(meja_api)
    assert "def _tiket_pk_luar" not in sumber_meja, "pemancar tiket disalin lagi ke meja_api"
    assert "def _tiket_jenis_tak_dikenal" not in sumber_meja


def test_terpasang_pada_ketiga_jalur_peran():
    """Admin ke atas, operator Gudang 2, dan kerja meja — masing-masing lewat
    fungsinya sendiri. Fungsi yang ada tetapi tak dipanggil siapa pun adalah
    persis keadaan yang membuat keluhan pemilik tak terjawab selama sehari."""
    from app.services import berjalan as svc

    # Admin/Meja: tiket PK bertindakan.
    g2 = kode_saja(svc.untuk_gudang2)
    assert "_tiket_pk_luar(db, boleh_catat=True)" in g2
    # Operator Gudang 2: kartu diam.
    op = kode_saja(svc.untuk_operator_gudang2)
    assert "_tiket_pk_luar(db, boleh_catat=False)" in op
    # Jenis tak dikenal: kerja meja.
    st = kode_saja(svc.untuk_staff)
    assert "_tiket_jenis_tak_dikenal(db)" in st
    # Dan `untuk()` benar-benar MEMBAWA `menunggu` dari untuk_staff — daftar
    # yang tak diambil adalah daftar yang tak pernah tergambar.
    u = kode_saja(svc.untuk)
    assert "b.menunggu += s.menunggu" in u


def test_tiket_tak_terangkut_dua_kali():
    """Risiko terbesar pemindahan ini (brief 2a & QA): satu tiket dua kartu.

    `meja_api._susun` dulu memanggil kedua pemancar SENDIRI di samping
    `untuk_gudang2`/`untuk_staff`. Sekarang keduanya sudah membawanya, jadi
    memanggilnya lagi berarti tiket yang sama muncul dua kali di antrean yang
    sama — dan yang melihatnya akan mengira ada dua truk.
    """
    from app.web import meja_api

    susun = kode_saja(meja_api._susun)
    assert "_tiket_pk_luar" not in susun
    assert "_tiket_jenis_tak_dikenal" not in susun
    assert "_ser(s.menunggu)" in susun


def test_jalur_gabah_dan_jalur_pk_tak_saling_masuk():
    """GABAH_KERING hanya di jalur gabah; BERAS_PK hanya di jalur PK.

    Syaratnya dibaca dari PETA JENIS di kedua sisi, bukan ditebak dari awalan
    kode: taksonomi jenis Pos Timbang berbasis data dan bisa bertambah, dan
    menebak dari nama berarti komoditas baru diam-diam dianggap gabah kering.
    """
    from app.penggilingan.peta_jenis import PETA_MASUK, intake_dari_jenis
    from app.services import berjalan as svc

    gabah = kode_saja(svc._tiket_belum_ditaut)
    # `kode_saja` menormalkan kutipnya, jadi yang diperiksa isinya — bukan
    # gaya kutipnya.
    assert "info.model != 'gabah'" in gabah and "continue" in gabah
    pk = kode_saja(svc._tiket_pk_luar)
    assert "is_pk(t.get(" in pk and "continue" in pk
    # Premis petanya, supaya uji ini gagal kalau petanya berubah di bawahnya.
    assert intake_dari_jenis("GABAH_KERING").model == "gabah"
    assert intake_dari_jenis("BERAS_PK").model == "pk"
    assert "BERAS_MASUK" not in PETA_MASUK, "sudah dipetakan — tinjau uji ini"


def test_kartu_diam_benar_benar_diam():
    """Operator Gudang 2 melihat tiket PK tetapi tak bisa menekannya.

    Penempatan PK datang bukan tugasnya (pemilik, 12 September 2026) dan
    gerbang `create_pk_purchase_dari_timbang` memang menolaknya. Kartu yang
    menjanjikan borang lalu ditolak 403 lebih buruk daripada kartu diam —
    tetapi kartunya tetap harus ADA: barangnya berdiri di halamannya.
    """
    from app.services import berjalan as svc

    kode = kode_saja(svc._tiket_pk_luar)
    # Aksi & pilihan hanya dipasang bila boleh mencatat.
    assert "aksi='catat_pk_luar' if boleh_catat else None" in kode
    assert "if boleh_catat else []" in kode
    # Kepingan keadaan menerangkan SEBABNYA, di tempat orang mencarinya.
    assert "dicatat Admin" in kode
    assert "keadaan='' if boleh_catat else" in kode
    # Gerbang perannya sendiri tidak diubah oleh perbaikan ini.
    from app.penggilingan.gudang2 import service as g2svc

    assert "PERAN_ADMIN_KEATAS" in kode_saja(g2svc.create_pk_purchase_dari_timbang)


def test_kartu_jenis_tak_dikenal_tanpa_tindakan_apa_pun():
    """Yang benar memang belum ada. Menawarkan borang yang akan menolak isinya
    lebih buruk daripada tak menawarkan apa pun.

    Dibaca dari AST, bukan dari teks: `aksi=None` yang tertulis pun akan
    terbaca oleh `test_setiap_kartu_membentang_di_tempat` sebagai kartu
    bertindakan yang lupa membawa `pilihan`.
    """
    from app.services import berjalan as svc

    pohon = ast.parse(kode_saja(svc._tiket_jenis_tak_dikenal))
    panggil = [n for n in ast.walk(pohon)
               if isinstance(n, ast.Call) and getattr(n.func, "id", None) == "Baris"]
    assert len(panggil) == 1
    kunci = {k.arg for k in panggil[0].keywords}
    assert not (kunci & {"aksi", "nilai", "pilihan", "tombol"}), kunci
    # Dan ia menyebut KODE jenisnya — itu yang dipakai memetakannya nanti.
    kode = kode_saja(svc._tiket_jenis_tak_dikenal)
    assert "jenis_kode" in kode and "Jenis timbang" in kode


def test_blok_tiket_punya_judulnya_sendiri_di_pos_produksi():
    """Kartu diam tak boleh berdiri di bawah judul "Bisa dikerjakan sekarang".

    Judul yang menjanjikan sesuatu yang tak terjadi membuat orang menekan
    berulang lalu menyimpulkan aplikasinya rusak — dan kesimpulan itu menempel
    pada seluruh layar, bukan pada satu kartu.
    """
    utama = (AKAR / "app/main.py").read_text()
    assert 'KELOMPOK_TENGAH="tiket"' in utama
    assert 'judul_tengah="Tiket timbang belum dicatat"' in utama
    tpl = (AKAR / "hmu_tampilan/templates/aksi.html").read_text()
    assert "{% if KELOMPOK_TENGAH %}" in tpl
    # Bawaannya kosong DI TEMPLAT: app yang tak punya blok tengah tak perlu
    # tahu bahwa blok itu ada, dan keluarannya harus sama seperti sebelumnya.
    assert 'KELOMPOK_TENGAH|default("", true)' in tpl
