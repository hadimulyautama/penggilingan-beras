"""Uji pemicu sinkron kontak Kledo (`app/services/kledo_sinkron.py`) di Postgres.

Beda dari `core/tests/test_kledo_kontak.py`: berkas itu membuktikan rutin
`hmu_core.kledo_kontak.sinkron()` sendiri idempoten — yang DIBUKTIKAN DI SINI
adalah lapisan di atasnya yang baru (4 Oktober 2026): status/lock-nya, dan
bahwa memicunya dua kali berturut-turut — persis "tekan tombolnya dua kali"
pada perintah pemilik — menghasilkan laporan kedua yang TIDAK menyebut "baru"
atau "diperbarui" sama sekali (keduanya nol, dan `_ringkas_gabungan` sengaja
membuang bagian yang nilainya nol — lihat modulnya).

Berjalan HANYA bila `UJI_PG_URL` disetel (lihat `tests/pg/conftest.py`).
Jaringan ke Kledo ditambal — tak ada panggilan sungguhan ke internet.
"""
from __future__ import annotations

import asyncio

import pytest


def _kontak(kid: int, nama: str, tipe=(3,)) -> dict:
    return {"id": kid, "name": nama, "type_ids": list(tipe), "is_archive": 0,
            "phone": None, "address": None}


#: Dua pelanggan — cukup untuk membuktikan "baru" lalu "tak berubah", tanpa
#: menunggu ~600 kontak sungguhan yang justru alasan putaran ini LATAR.
CONTOH = [_kontak(9001, "Toko Uji Kledo Satu"), _kontak(9002, "Toko Uji Kledo Dua")]


async def _tunggu_selesai(kledo_sinkron, maks_detik: float = 10.0) -> None:
    langkah = 0.05
    for _ in range(int(maks_detik / langkah)):
        if not kledo_sinkron.status().sedang_berjalan:
            return
        await asyncio.sleep(langkah)
    pytest.fail("sinkron tak selesai dalam waktu yang wajar — kemungkinan macet")


async def test_tekan_dua_kali_kedua_tak_menyebut_baru_atau_diperbarui(pg, monkeypatch):
    from hmu_core import kledo_kontak

    from app.services import kledo_sinkron

    async def palsu(tipe: int):
        return [k for k in CONTOH if tipe in k["type_ids"]]

    monkeypatch.setattr(kledo_kontak, "ambil_kontak", palsu)

    # Keadaan modul ini singleton proses (lihat docstring-nya) — disetel ulang
    # di sini supaya uji ini tak mewarisi sisa dari uji lain yang pernah
    # menyentuhnya dalam proses pytest yang sama.
    kledo_sinkron._sedang_berjalan = False
    kledo_sinkron._hasil_terakhir = None
    kledo_sinkron._gagal_terakhir = None
    kledo_sinkron._selesai_pada = None

    # ── Tekan pertama: dua pelanggan baru ──
    assert kledo_sinkron.mulai() is True
    await _tunggu_selesai(kledo_sinkron)
    s1 = kledo_sinkron.status()
    assert s1.gagal_terakhir is None, s1.gagal_terakhir
    assert "2 baru" in s1.hasil_terakhir, s1.hasil_terakhir

    # ── Tekan kedua: tak ada yang baru, tak ada yang berubah ──
    #
    # Ini bukti idempotensi persis seperti yang diminta pemilik: angka "baru"
    # DAN "diperbarui" pada penekanan kedua harus nol. `_ringkas_gabungan`
    # membuang bagian bernilai nol, jadi substring ini seharusnya tak muncul
    # SAMA SEKALI pada bagian per-jenis dari laporan kedua.
    #
    # Dipotong SETELAH tanda pisah "—": kalimat pembukanya sendiri berbunyi
    # "Kontak diperbarui" (kata yang sama, makna berbeda — status halaman
    # ini sudah "diperbarui" dengan menjalankan sinkron, lepas dari apakah
    # ada BARIS yang berubah) dan akan mencemari pemeriksaan substring kalau
    # tidak dipotong dulu.
    assert kledo_sinkron.mulai() is True   # putaran pertama sudah selesai, kunci terbuka lagi
    await _tunggu_selesai(kledo_sinkron)
    s2 = kledo_sinkron.status()
    assert s2.gagal_terakhir is None, s2.gagal_terakhir
    rincian = s2.hasil_terakhir.split("—", 1)[1]
    assert "baru" not in rincian, s2.hasil_terakhir
    assert "diperbarui" not in rincian, s2.hasil_terakhir
    assert "tak berubah" in rincian, s2.hasil_terakhir


async def test_dua_pemicu_bersamaan_yang_kedua_ditolak_dengan_tenang(pg, monkeypatch):
    """`mulai()` adalah "satu kunci sederhana" (permintaan pemilik, bagian 5b):
    pemanggil kedua SELAGI yang pertama masih berjalan harus melihat `False`,
    bukan memulai putaran kedua yang memboroskan kuota API Kledo dan
    menghasilkan dua laporan yang membingungkan."""
    from hmu_core import kledo_kontak

    from app.services import kledo_sinkron

    async def lambat(tipe: int):
        await asyncio.sleep(0.3)
        return [k for k in CONTOH if tipe in k["type_ids"]]

    monkeypatch.setattr(kledo_kontak, "ambil_kontak", lambat)

    kledo_sinkron._sedang_berjalan = False
    kledo_sinkron._hasil_terakhir = None
    kledo_sinkron._gagal_terakhir = None
    kledo_sinkron._selesai_pada = None

    assert kledo_sinkron.mulai() is True
    assert kledo_sinkron.status().sedang_berjalan is True
    # Pemanggil KEDUA, selagi yang pertama masih di tengah mengambil kontak.
    assert kledo_sinkron.mulai() is False

    await _tunggu_selesai(kledo_sinkron)
    assert kledo_sinkron.status().sedang_berjalan is False
