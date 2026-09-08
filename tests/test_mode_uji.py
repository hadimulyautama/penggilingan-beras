"""Penjaga mode uji.

Fitur ini menghapus data di basis yang DIPAKAI BERSAMA dua aplikasi lain.
Versi pertamanya memakai `TRUNCATE ... CASCADE` dan menyapu seluruh tiket
timbang — 2 menjadi 0 — karena CASCADE merambat keluar lewat foreign key yang
MASUK, ke tabel yang produksi bahkan tak mengenalnya. Uji di sinilah yang
menangkapnya sebelum terkirim.
"""
from __future__ import annotations

import inspect

import pytest

from tests.bantu import kode_saja

from app.database import Base
from app.web import mode_uji


def test_tak_satu_pun_tabel_timbangan_dalam_jangkauan():
    """Sasaran penghapusan hanya tabel yang didefinisikan produksi sendiri."""
    assert not [t for t in Base.metadata.tables if t.startswith("timbangan")]
    assert not [t for t in mode_uji._tabel_dihapus() if t.startswith("timbangan")]


def test_tabel_milik_bersama_dipertahankan():
    """Tiga tabel yang tampak "milik produksi" padahal dipakai aplikasi lain.

    `suppliers` ditunjuk Timbangan dengan kolom WAJIB ISI; `kantor_config` &
    `kantor_llm_usage` memuat kill-switch dan BATAS BIAYA LLM yang dipakai
    bersama layanan Kantor. Tak satu pun terlihat asing dari namanya saja.
    """
    for nama in ("suppliers", "kantor_config", "kantor_llm_usage"):
        assert nama in mode_uji.DIPERTAHANKAN, nama
        assert nama not in mode_uji._tabel_dihapus(), nama


def test_akun_dan_alat_dipertahankan():
    """Menghapus akun berarti mengunci diri sendiri di luar aplikasi."""
    for nama in ("users", "produksi_akun", "warehouses", "silos", "dryers"):
        assert nama in mode_uji.DIPERTAHANKAN, nama


def test_tak_memakai_cascade():
    """CASCADE-lah yang dulu menyapu tiket. Ia tak boleh kembali."""
    kode = kode_saja(mode_uji._kosongkan)
    assert "CASCADE" not in kode.upper()
    assert "DELETE FROM" in kode


def test_urutan_hapus_dari_metadata_bukan_daftar_tangan():
    """Daftar yang ditulis tangan akan basi pada tabel berikutnya."""
    assert "Base.metadata.sorted_tables" in kode_saja(mode_uji._kosongkan)


@pytest.mark.asyncio
async def test_mati_total_saat_mode_uji_padam():
    """Mematikannya bukan menyembunyikan tombol — endpointnya ikut menolak."""
    from fastapi import HTTPException

    from app.config import settings

    asli = settings.mode_uji
    try:
        settings.mode_uji = False
        with pytest.raises(HTTPException) as e:
            mode_uji._wajib_mode_uji()
        assert e.value.status_code == 404
        settings.mode_uji = True
        mode_uji._wajib_mode_uji()      # tidak melempar
    finally:
        settings.mode_uji = asli


def test_setelan_pabrik_tidak_ikut_terhapus():
    """Ia segolongan dengan alat: menggambarkan PABRIKNYA, bukan pekerjaannya.
    Menghapusnya berarti diam-diam mengembalikan target kadar air dan daftar
    sebab berhenti ke bawaan, tanpa satu layar pun menyebutkan itu terjadi."""
    from app.web.mode_uji import DIPERTAHANKAN, _tabel_dihapus

    assert "setelan_pabrik" in DIPERTAHANKAN
    assert "setelan_pabrik" not in _tabel_dihapus()


def test_nomor_urut_hanya_untuk_tabel_berkolom_id():
    """`setelan_pabrik` berkunci `kunci`, bukan `id`. Penjaga
    `pg_get_serial_sequence(...) IS NOT NULL` tak menolong — Postgres sudah
    menyerah saat mencari kolomnya, dan seluruh penghapusan jatuh dengan
    Internal Server Error SESUDAH DELETE-nya terlanjur berjalan."""
    import inspect

    from app.database import Base
    from app.web import mode_uji

    sumber = inspect.getsource(mode_uji._kosongkan)
    assert 'berid = {t.name for t in Base.metadata.sorted_tables if "id" in t.columns}' in sumber
    assert "for nama in [n for n in urut if n in berid]:" in sumber

    # Dan memang ada tabel tanpa `id` di basis data ini — kalau tidak, tesnya
    # menjaga sesuatu yang tak pernah terjadi.
    tanpa_id = {t.name for t in Base.metadata.sorted_tables if "id" not in t.columns}
    assert tanpa_id, "tak ada tabel tanpa id — penjaganya jadi tak berarti"


def test_tombol_kembalikan_data_uji():
    """Pemilik: harus ada tombol reset agar data dummy kembali seperti awal
    dan data entry test bisa terhapus.

    Menghapus saja meninggalkan tiap layar kosong, dan sesudah itu tak ada
    yang bisa dicoba sampai seseorang mengisinya lagi dari laptop.
    """
    import inspect
    import pathlib

    from app.web import mode_uji

    assert hasattr(mode_uji, "ulangi")
    sumber = inspect.getsource(mode_uji.ulangi)
    assert "_wajib_mode_uji()" in sumber, "di luar mode uji tak boleh ada sama sekali"
    assert "akun.is_admin" in sumber
    assert "await _kosongkan()" in sumber, "menghapus dulu, baru mengisi"
    assert "data_uji.isi(akun)" in sumber

    # Kalimatnya BERBEDA dari tombol hapus. Dua tombol yang menuntut kalimat
    # sama adalah dua tombol yang bisa tertukar justru saat orangnya sudah
    # hafal mengetiknya.
    assert mode_uji.KALIMAT_ULANG != mode_uji.KALIMAT
    assert f'"{mode_uji.KALIMAT_ULANG}"' in sumber or "KALIMAT_ULANG" in sumber

    html = (pathlib.Path(__file__).resolve().parents[1]
            / "app/web/templates/mode_uji.html").read_text()
    assert 'action="/pengaturan/mode-uji/ulangi"' in html
    assert "Kembalikan data uji" in html


def test_satu_isi_dipakai_skrip_dan_tombol():
    """Kalau skripnya punya salinan pengisiannya sendiri, data yang dibuat
    dari laptop dan data yang dibuat dari layar akan berbeda — dan yang diuji
    orang jadi bukan yang dipakai orang."""
    import pathlib

    from app.services import data_uji

    assert hasattr(data_uji, "isi")
    skrip = (pathlib.Path(__file__).resolve().parents[1]
             / "scripts/isi_dummy.py").read_text()
    assert "data_uji.isi(akun)" in skrip
    assert "IZIN_DUMMY" in skrip, "skripnya tetap berpagar"


def test_data_uji_dibuat_lewat_endpoint_bukan_insert():
    """Baris yang disuntikkan langsung bisa saja mustahil menurut aturan
    aplikasinya sendiri, dan data uji yang mustahil membuat layarnya terlihat
    benar padahal menampilkan keadaan yang tak pernah bisa terjadi."""
    import inspect

    from app.services import data_uji

    sumber = inspect.getsource(data_uji.isi)
    assert "ASGITransport" in sumber, "memanggil aplikasinya sendiri, tanpa jaringan"
    assert "/miniapp/actions/gabah-masuk" in sumber
    # Satu-satunya INSERT langsung: tiket timbang, milik aplikasi lain.
    insert = inspect.getsource(data_uji)
    assert insert.count("INSERT INTO") == 2, "hanya pemasok & tiket timbang"
    assert "INSERT INTO timbangan_transaksi" in insert
