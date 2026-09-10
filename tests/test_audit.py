"""Uji List audit — dan batas 48 jam yang ditegakkannya.

Laporan menjawab "berapa"; audit menjawab "siapa mencatat apa, jam berapa" —
dan itu pertanyaan yang muncul justru saat angkanya tidak masuk akal.
"""
from __future__ import annotations

import inspect
from datetime import timedelta

from app.services import audit, undo
from tests.bantu import kode_saja


def test_batas_ditulis_sekali_dipakai_dua_kali():
    """Batas yang DITEGAKKAN dan batas yang DITAMPILKAN tak boleh berbeda.
    Dua angka untuk satu aturan cepat atau lambat berselisih, dan yang salah
    adalah yang lebih jarang dibaca orang."""
    assert audit.BATAS_UBAH is undo.BATAS_UNDO
    assert undo.BATAS_UNDO == timedelta(hours=48)


def test_batas_ditegakkan_di_layanan_bukan_di_layar():
    """Menyembunyikan tombol bukan penjagaan — jalur bot memakai fungsi yang
    sama, dan aturan yang ditulis dua kali berbeda di salah satunya."""
    sumber = kode_saja(undo.undo_last)
    assert "BATAS_UNDO" in sumber
    assert "lewat batas" in inspect.getsource(undo.undo_last)
    # Dan layarnya TIDAK menegakkan sendiri — ia memanggil layanannya.
    from app.web import layar_audit

    tombol = kode_saja(layar_audit.batalkan_terakhir)
    assert "undo_svc.undo_last" in tombol
    assert "BATAS" not in tombol


def test_jejak_undo_sendiri_tak_ikut_didaftar():
    """Baris "undo" cuma menggandakan cerita yang sama dari sisi lain, dan
    akibatnya sudah terlihat pada catatan yang dibatalkan."""
    sumber = kode_saja(audit.daftar)
    assert "ActivityLog.table_name != 'undo'" in sumber


def test_kelompok_memakai_bahasa_orang_bukan_nama_tabel():
    """Operator tak berpikir dalam nama tabel; ia berpikir "gabah masuk"."""
    nama = [n for _, n, _ in audit.KELOMPOK]
    assert "Gabah masuk" in nama and "Pengeringan" in nama and "Giling" in nama
    # Tiap kelompok memetakan ke tabel yang nyata — kelompok yang menunjuk
    # tabel yang tak ada akan diam-diam selalu kosong.
    from app.database import Base

    ada = set(Base.metadata.tables)
    for _, label, tabel in audit.KELOMPOK:
        for t in tabel or ():
            assert t in ada, f"{label}: tabel {t} tidak ada"


def test_hanya_admin_yang_melihat_pintunya():
    """List audit memuat jejak pencatatan berikut tombol yang membatalkannya.
    Orang yang bisa membatalkan catatannya sendiri membuat jejak itu tak ada
    gunanya sebagai jejak."""
    from app.web.nav import TAB

    from app.web.layar import ADMIN, POLESAN, SELEPAN, SUPER

    view = {k: v for k, _, _, _, v in TAB}
    assert set(view["audit"]) == {SUPER, ADMIN}
    assert SELEPAN not in view["audit"] and POLESAN not in view["audit"]
    # Antrean tak punya kolom view sama sekali — keempatnya melihatnya.
    assert view["aksi"] is None


def test_penjagaan_sungguhannya_di_rute():
    """Menyembunyikan pintu di menu bukan penjagaan — alamatnya tetap bisa
    diketik."""
    from app.web import layar_audit

    for fn in (layar_audit.halaman_audit, layar_audit.batalkan_terakhir):
        assert "butuh_admin" in inspect.getsource(fn), fn.__name__


def test_yang_terkunci_dibedakan_sebelum_tulisannya_dibaca():
    import pathlib

    akar = pathlib.Path(__file__).resolve().parents[1]
    css = (akar / "app/web/static/app.css").read_text()
    html = (akar / "app/web/templates/audit.html").read_text()
    assert ".audit--muda" in css and ".audit--tua" in css
    assert "'tua' if not c.muda else 'muda'" in html
    assert "terkunci" in html


# ──────────────────────── Laci harus benar-benar bisa dibuka ────────────────

def test_tombol_menu_ada_di_setiap_layar_menu():
    """Panah "kembali" MENANG atas tombol menu di bilah — jadi layar yang
    memakai keduanya kehilangan menunya. Dan panah "kembali ke beranda" pada
    layar yang sederajat dengan beranda memang tak menjawab apa pun."""
    import types

    from app.web.nav import TAB
    from app.web.tampilan import templates

    akun = types.SimpleNamespace(nama="Pras", peran="superadmin", sesi_pendek=False)
    for kunci, _, _, _, _ in TAB:
        html = templates.get_template("base.html").render(
            request=None, akun=akun, layar=kunci, MENUNGGU=1, MODE_UJI=False,
            LIHAT_SEBAGAI=None, kembali=None)
        assert 'id="buka-laci"' in html, kunci
        assert 'id="laci"' in html, kunci


def test_layar_menu_tak_memakai_panah_kembali():
    """Diperiksa pada rutenya, bukan cuma pada templat: yang mematikan menu
    adalah `kembali=` yang dikirim rute."""
    import inspect

    from app import main
    from app.web import layar_audit, pengaturan

    for fn in (main.halaman_aksi, pengaturan.halaman_pengaturan,
               layar_audit.halaman_audit):
        sumber = inspect.getsource(fn)
        assert "kembali=" not in sumber, fn.__name__


def test_skrip_laci_ikut_berpindah_halaman():
    """`pindah.js` mengganti seluruh isi `.bingkai` dan menjalankan ulang
    skrip yang datang bersamanya. Skrip di LUAR bingkai hanya terpasang sekali
    — dan sesudah perpindahan pertama, tombolnya elemen baru tanpa penangan."""
    import pathlib
    import types

    from app.web.tampilan import templates

    akun = types.SimpleNamespace(nama="Pras", peran="operator", sesi_pendek=False)
    html = templates.get_template("base.html").render(
        request=None, akun=akun, layar="aksi", MENUNGGU=0, MODE_UJI=False,
        LIHAT_SEBAGAI=None, kembali=None)
    bingkai = html.split('<div class="bingkai">')[1].split("\n</div>\n\n<script>")[0]
    assert "buka-laci" in bingkai and "addEventListener" in bingkai

    # Dan `pindah.js` memang menjalankan ulang skrip di dalamnya.
    js = (pathlib.Path(__file__).resolve().parents[1]
          / "app/web/static/pindah.js").read_text()
    assert "replaceChild" in js and "script" in js
