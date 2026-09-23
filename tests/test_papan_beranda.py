"""Papan Beranda pemegang kedua gudang — celah ke-5 menjelang app meja dihapus.

Tiga hal yang hanya ada di Beranda Meja sampai 24 September 2026: blok "Perlu
perhatian", rincian keputusan (harga / output / mutu), dan satu baris per gudang.
Perhitungannya pindah ke `services/beranda.py` dan dipakai KEDUA app — dua
Beranda yang menghitung penyimpangan sendiri-sendiri akan menyebut angka berbeda
tentang pabrik yang sama, dan tak ada yang menyadarinya sebab tak ada yang
membuka keduanya berdampingan.
"""
from __future__ import annotations

import inspect

from app.services import beranda as svc
from app.web.layar_keputusan import AKSI_DIKENAL, JENIS_KEPUTUSAN
from tests.bantu import kode_saja


def test_tiap_jenis_keputusan_punya_golongan_tepat_satu():
    """Golongan yang ketinggalan satu jenis membuat rincian di Beranda tak
    berjumlah sama dengan lencananya — dan angka yang tak berjumlah membuat orang
    berhenti mempercayai keduanya.

    Inilah kelas galat yang sama yang menyembunyikan `betulkan_bobot_giling` dari
    setiap layar selama sebulan: daftar di satu tempat, kenyataan di tempat lain,
    dan tak ada yang membandingkannya.
    """
    semua = [a for golongan in svc.GOLONGAN_KEPUTUSAN.values() for a in golongan]
    assert sorted(semua) == sorted(AKSI_DIKENAL), \
        f"selisih: {set(semua) ^ set(AKSI_DIKENAL)}"
    assert len(semua) == len(set(semua)), "satu jenis masuk dua golongan"
    assert len(AKSI_DIKENAL) == len(JENIS_KEPUTUSAN)


def test_rincian_berjumlah_sama_dengan_lencana():
    """Bukan sekadar tiap jenis bergolongan: jumlah ketiganya harus SAMA dengan
    jumlah kartu meja, sebab keduanya tampil berdampingan di satu kartu."""
    meja = [{"aksi": a} for a, _ in JENIS_KEPUTUSAN] + [{"aksi": "verify_gabah"}]
    n = svc.hitung_keputusan(meja)
    assert sum(n.values()) == len(meja)
    assert n["harga"] == 3 and n["output"] == 2 and n["mutu"] == 2


def test_hitung_keputusan_menerima_baris_maupun_dict():
    """Pos Produksi memberi `Baris`, Meja memberi dict hasil JSON. Satu fungsi
    untuk keduanya — dua fungsi berarti dua cara menghitung hal yang sama."""
    from app.services.berjalan import Baris

    b = [Baris(kode="X", isi="", keadaan="", aksi="qc_giling")]
    d = [{"aksi": "qc_giling"}]
    assert svc.hitung_keputusan(b) == svc.hitung_keputusan(d)


def test_perhitungan_tinggal_di_layanan_bukan_di_api_meja():
    from app.web import meja_api

    sumber = inspect.getsource(meja_api)
    for pindah in ("def _perhatian", "def _angka_gudang", "def _ribuan"):
        assert pindah not in sumber, f"{pindah} tertinggal salinannya di meja_api"
    assert "svc_beranda.papan(" in kode_saja(meja_api.beranda)


def test_beranda_produksi_memakai_papan_yang_sama():
    from app import main

    kode = kode_saja(main.beranda)
    assert "svc_beranda.papan(" in kode
    # Bergerbang view meja — bukan peran tersimpan, dan bukan dihitung ulang
    # di templat.
    assert "view in V_MEJA" in kode
    # Bendera bloknya dibaca dari SATU tempat: `papan is not None`. Kalau
    # dibaca dari `view in V_MEJA` lagi, kegagalan kueri akan menggambar blok
    # kosong — dan blok kosong terbaca sebagai "tak ada yang perlu perhatian",
    # kalimat yang paling mahal untuk salah.
    assert "blok_perhatian=papan is not None" in kode
    assert "rinci_keputusan=papan is not None" in kode


def test_perhatian_hanya_memuat_yang_menyimpang():
    """Blok yang selalu berisi mengajari orang mengabaikannya."""
    kode = kode_saja(svc.perhatian)
    # Mesin: hanya yang notanya "hati" — keadaan yang MENAHAN pekerjaan.
    assert "== 'hati'" in kode
    # Tumpukan: hanya bila melewati batas, dan batasnya boleh tak diatur.
    assert "if maks and tump > maks" in kode
    # Harga: hanya yang menggantung lebih dari dua hari.
    assert "timedelta(days=2)" in kode


def test_baris_gudang_dari_daftar_bukan_dua_baris_tetap():
    """Sepuluh gudang = sepuluh baris. Menambah gudang berarti menambah baris di
    master, bukan di kode."""
    kode = kode_saja(svc.baris_gudang)
    assert "for gid, nama, fungsi in GUDANG" in kode
    assert "'g1'" not in kode and "'g2'" not in kode
