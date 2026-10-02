"""Grup "Menunggu keputusan" — sub-menu kembaran Antrian tunggu.

Keputusan pemilik 2 Oktober 2026: *"lakukan yang sama ke menunggu
keputusan."* Bentuknya sama persis dengan `tests/test_grup_antrean.py` —
termasuk invarian paling pentingnya: Σ grup == panjang daftar, dan grup
terakhir adalah KOMPLEMEN, bukan daftar tertutup.

Bedanya satu: grupnya TIDAK ditulis tangan di sini. `GRUP_KEPUTUSAN` dan
`grup_keputusan()` DITURUNKAN dari `services/keputusan.GOLONGAN` — taksonomi
yang sudah dipakai Beranda ("N permintaan · N output · N mutu"). Memetakan
nama aksi tangan kedua kalinya adalah jalan yang sama yang membuat tiga nama
salah ketik di `_GRUP_AKSI` (lihat `tests/test_grup_antrean.py`); sumber
tunggal tak bisa berselisih dengan dirinya sendiri.
"""
from __future__ import annotations

import pytest

from app.services import keputusan as K
from app.services.berjalan import (GRUP_KEPUTUSAN, Baris, Berjalan,
                                   grup_keputusan)

KUNCI = {k for k, _ in GRUP_KEPUTUSAN}


def _kartu(aksi=None, kode="X-1"):
    return Baris(kode=kode, isi="", keadaan="", aksi=aksi)


def test_mutu_tak_ada_di_grup_keputusan():
    """⭐ Mutu punya layarnya sendiri (`/mutu`). Golongan "mutu" tak boleh
    muncul di sub-menu halaman ini — ia menjanjikan pekerjaan yang tak
    pernah digambar di sana."""
    assert K.MUTU not in KUNCI
    assert "mutu" not in KUNCI


def test_golongan_turun_langsung_dari_keputusan_py():
    """Tak ditulis tangan: tiap golongan non-mutu di `K.GOLONGAN` wajib
    muncul, dan nama-nama aksi di dalamnya wajib dikenali `grup_keputusan`
    tanpa satu pun salah ketik."""
    for golongan, daftar_aksi in K.GOLONGAN.items():
        if golongan == K.MUTU:
            continue
        assert golongan in KUNCI, f"golongan {golongan!r} tak ada di GRUP_KEPUTUSAN"
        for aksi in daftar_aksi:
            assert grup_keputusan(_kartu(aksi=aksi)) == golongan, aksi


def test_grup_terakhir_komplemen():
    """Aksi yang belum (atau tak pernah) diberi golongan tetap kebagian
    grup — "Lainnya", sama seperti jaring `keputusan.html` sendiri."""
    for aneh in (_kartu(aksi="aksi_yang_belum_ada"), _kartu(aksi=None),
                 _kartu(aksi="")):
        assert grup_keputusan(aneh) == GRUP_KEPUTUSAN[-1][0] == "lain"


def test_jumlah_grup_keputusan_menjumlah_tepat_non_mutu():
    """⭐ INVARIAN: Σ grup == panjang `meja` NON-MUTU.

    Baris mutu HARUS dilompati, bukan dihitung sebagai "lain" — kalau tidak,
    lencana sub-menu ini mengklaim pekerjaan yang sebenarnya ada di halaman
    Mutu & QC.
    """
    b = Berjalan(meja=[
        _kartu(aksi="acc_permintaan_pk"), _kartu(aksi="tutup_permintaan_pk"),
        _kartu(aksi="betulkan_bobot_giling"), _kartu(aksi="qc_giling"),
        _kartu(aksi="qc_pk_luar"), _kartu(aksi="belum_dikenal"),
    ])
    n = b.jumlah_grup_keputusan()
    non_mutu = [x for x in b.meja if not K.golongan_mutu(x.aksi)]
    assert sum(n.values()) == len(non_mutu) == 4, "mutu ikut terhitung atau ada yang hilang"
    assert set(n) == KUNCI
    assert n["permintaan"] == 2
    assert n["output"] == 1
    assert n["lain"] == 1


def test_submenu_keputusan_butuh_dua_golongan_berisi():
    """Syarat sama dengan Antrian tunggu: dropdown tanpa pilihan merampas
    satu ketukan."""
    satu = Berjalan(meja=[_kartu(aksi="acc_permintaan_pk"),
                          _kartu(aksi="tutup_permintaan_pk")])
    assert "keputusan" not in satu.submenu()

    dua = Berjalan(meja=[_kartu(aksi="acc_permintaan_pk"),
                         _kartu(aksi="betulkan_bobot_giling")])
    assert "keputusan" in dua.submenu()


def test_submenu_keputusan_semua_dulu_dan_angkanya_sepadan():
    b = Berjalan(meja=[_kartu(aksi="acc_permintaan_pk"),
                       _kartu(aksi="tutup_permintaan_pk"),
                       _kartu(aksi="betulkan_bobot_giling"),
                       _kartu(aksi="qc_giling")])  # mutu — tak ikut terhitung
    sub = b.submenu()["keputusan"]
    alamat, nama, jml = sub[0]
    assert (alamat, nama) == ("/keputusan", "Semua")
    assert jml == b.jumlah_keputusan == 3, "mutu ikut masuk hitungan 'Semua'"
    assert sum(j for _, _, j in sub[1:]) == 3
    assert all(a.startswith("/keputusan?golongan=") for a, _, _ in sub[1:])


def test_submenu_keputusan_dan_antrean_independen():
    """Kedua pintu bisa punya sub-menu SENDIRI-SENDIRI — satu berisi,
    satunya tidak, tanpa saling memengaruhi."""
    b = Berjalan(
        menunggu=[_kartu(aksi="gabah_masuk"), _kartu(aksi="catat_packing")],
        meja=[_kartu(aksi="acc_permintaan_pk")],  # cuma satu golongan
    )
    sub = b.submenu()
    assert "aksi" in sub
    assert "keputusan" not in sub


# ══════════════ Yang TERGAMBAR: pil halaman & sub-menu laci ══════════════

import types

from app.web.tampilan import templates


def _akun_kep(peran="admin"):
    a = types.SimpleNamespace(nama="Elfira", peran=peran, sesi_pendek=False)
    a.is_admin = peran in ("admin", "superadmin")
    return a


def _kartu_kep(aksi, kode="X-1", isi="isi", keadaan="", judul=None):
    return Baris(kode=kode, isi=isi, keadaan=keadaan, aksi=aksi,
                judul=judul or kode, utama=("1", "x"))


def _layar_keputusan(meja_tampil, *, semua_meja=None, golongan="",
                     pil=None, total=None):
    """Layar `/keputusan`, dengan nilai yang DIKIRIM RUTENYA — bukan diketik
    ulang: `halaman_keputusan` menyusunnya dari `GRUP_KEPUTUSAN` dan
    `jumlah_grup_keputusan()`."""
    from app.web.layar_keputusan import AKSI_DIKENAL, JENIS_KEPUTUSAN

    n = {k: sum(1 for x in meja_tampil if grup_keputusan(x) == k)
         for k, _ in GRUP_KEPUTUSAN}
    return templates.get_template("keputusan.html").render(
        request=None, akun=_akun_kep(), layar="keputusan", MENUNGGU=0,
        KEPUTUSAN=len(meja_tampil), MODE_UJI=False, LIHAT_SEBAGAI=None,
        kembali=None, meja=meja_tampil,
        semua_meja=(semua_meja if semua_meja is not None else meja_tampil),
        lama=lambda t: "", JENIS_KEPUTUSAN=JENIS_KEPUTUSAN,
        AKSI_DIKENAL=AKSI_DIKENAL, buka="", nilai="",
        GRUP_PIL=(pil if pil is not None
                  else [(k, nm, n[k]) for k, nm in GRUP_KEPUTUSAN
                        if n[k] or k == golongan]),
        GRUP_KINI=golongan,
        GRUP_TOTAL=(total if total is not None else sum(n.values())))


def test_pil_golongan_tergambar_dengan_dua_golongan():
    dua = [_kartu_kep("acc_permintaan_pk"), _kartu_kep("betulkan_bobot_giling")]
    h = _layar_keputusan(dua)
    assert "Permintaan PK" in h and "Output giling" in h
    assert "pil--on" in h
    assert 'class="pil__jml"' in h


def test_pil_tak_tergambar_bila_satu_golongan():
    satu = [_kartu_kep("acc_permintaan_pk"), _kartu_kep("tutup_permintaan_pk",
                                                        kode="X-2")]
    h = _layar_keputusan(satu)
    assert 'class="pil' not in h


def test_golongan_kosong_tak_berkata_semua_sudah_diverifikasi():
    h = _layar_keputusan([], semua_meja=[], golongan="output")
    assert "Golongan ini kosong" in h
    assert "sudah diverifikasi" not in h


def test_keputusan_benar_benar_kosong_tetap_memakai_kalimat_lama():
    h = _layar_keputusan([], semua_meja=[])
    assert "Tak ada yang menunggu keputusan" in h
    assert "Golongan ini kosong" not in h


def test_pintu_keputusan_jadi_summary_saat_bersub_menu():
    sub = {"keputusan": [("/keputusan", "Semua", 3),
                         ("/keputusan?golongan=permintaan", "Permintaan PK", 2),
                         ("/keputusan?golongan=output", "Output giling", 1)]}
    from app.web.nav import TAB

    h = templates.get_template("base.html").render(
        request=None, akun=_akun_kep(), layar="beranda", MENUNGGU=0,
        MODE_UJI=False, LIHAT_SEBAGAI=None, kembali=None, TAB=TAB,
        SUBMENU=sub, VIEW="admin", CSRF="x")
    assert "pintu-lipat" in h
    for nama in ("Semua", "Permintaan PK", "Output giling"):
        assert nama in h
    assert 'href="/keputusan"' in h
    assert 'href="/keputusan?golongan=permintaan"' in h


def test_kedua_pintu_bisa_bersub_menu_bersamaan():
    """Antrian tunggu DAN Menunggu keputusan dua-duanya bersub-menu pada
    laci yang sama, tanpa saling menimpa."""
    sub = {
        "aksi": [("/aksi", "Semua", 3), ("/aksi?grup=bahan", "Bahan baku", 2),
                ("/aksi?grup=packing", "Tunggu packing", 1)],
        "keputusan": [("/keputusan", "Semua", 2),
                     ("/keputusan?golongan=permintaan", "Permintaan PK", 1),
                     ("/keputusan?golongan=output", "Output giling", 1)],
    }
    from app.web.nav import TAB

    h = templates.get_template("base.html").render(
        request=None, akun=_akun_kep(), layar="beranda", MENUNGGU=3,
        KEPUTUSAN=2, MODE_UJI=False, LIHAT_SEBAGAI=None, kembali=None,
        TAB=TAB, SUBMENU=sub, VIEW="admin", CSRF="x")
    assert h.count("pintu-lipat") == 2
    assert 'href="/aksi?grup=bahan"' in h
    assert 'href="/keputusan?golongan=permintaan"' in h
