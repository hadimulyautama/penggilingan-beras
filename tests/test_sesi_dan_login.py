"""Orang yang keluar, diganti sandinya, atau dinonaktifkan benar-benar kehilangan akses.

Temuan QA P-S-04 s/d P-S-16 dan X-11, 11 September 2026.

Token sesi bertanda tangan HMAC tanpa catatan apa pun di basis data. Yang
tersimpan di dalamnya hanya nomor akun dan waktu kedaluwarsa, jadi sekali
sebuah token beredar, tak ada satu tindakan pun yang bisa menariknya kembali:

  · "Keluar" hanya menghapus cookie di perangkat yang menekannya. Perangkat
    lain — termasuk yang hilang — tetap masuk sampai 30 hari;
  · mengganti atau mereset sandi tidak memutus sesi yang sudah berjalan,
    jadi sandi yang dicuri tetap berguna sesudah diganti;
  · menonaktifkan orang di `users` tak diperiksa sama sekali; yang dilihat
    hanya status akun produksinya.

Sisanya adalah pintu masuk itu sendiri: tanpa pembatas percobaan, dengan
waktu jawab yang membocorkan nama pengguna mana yang ada, dan dengan
parameter tujuan yang menerima alamat situs lain.
"""
from __future__ import annotations

import json

import pytest

from app.web import security as sec


class AkunPalsu:
    def __init__(self, id: int = 7, mode: str = "pribadi", versi: int = 1):
        self.id = id
        self.mode_perangkat = mode
        self.token_version = versi

    @property
    def sesi_pendek(self) -> bool:
        return self.mode_perangkat == "bersama"


# ────────────────────── P-S-05 · versi token ──────────────────────

def test_token_membawa_versinya():
    """Tanpa nomor versi di dalam token, tak ada apa pun di sisi server yang
    bisa membedakan token lama dari token baru."""
    token = sec.buat_token(AkunPalsu(versi=3))
    muatan = json.loads(sec._b64d(token.split(".")[0]))
    assert muatan.get("v") == 3


def test_token_versi_lama_ditolak():
    """Inilah yang membuat "keluar dari semua perangkat" berarti sesuatu."""
    token = sec.buat_token(AkunPalsu(versi=1))
    assert sec.baca_token(token) == (7, 1)
    # Akunnya naik ke versi 2 → token versi 1 sudah bukan miliknya lagi.
    assert not sec.token_masih_berlaku(sec.baca_token(token), versi_akun=2)
    assert sec.token_masih_berlaku(sec.baca_token(token), versi_akun=1)


def test_token_tanpa_versi_dianggap_versi_satu():
    """Token yang beredar sebelum kolom ini ada tak boleh langsung memutus
    semua orang saat deploy — ia hanya memutus mereka yang versinya sudah
    dinaikkan sesudahnya."""
    muatan = sec._b64e(json.dumps({"sub": 7, "exp": 9_999_999_999}).encode())
    import hashlib
    import hmac as _hmac
    tanda = sec._b64e(_hmac.new(sec._kunci(), muatan.encode(), hashlib.sha256).digest())
    assert sec.baca_token(f"{muatan}.{tanda}") == (7, 1)


@pytest.mark.parametrize("rusak", [
    "", "bukan-token", "a.b", "....", "\udcff.\udcff",
])
def test_token_rusak_tak_pernah_melempar(rusak):
    """Cookie non-ASCII dulu menjatuhkan SETIAP halaman dengan galat 500 —
    bukan halaman masuk, melainkan semuanya. Temuan QA P-S-12."""
    assert sec.baca_token(rusak) is None


def test_nomor_akun_raksasa_ditolak():
    """Id di luar rentang yang mungkin dulu sampai ke basis data dan pulang
    sebagai galat asyncpg mentah."""
    muatan = sec._b64e(json.dumps({"sub": 10 ** 30, "exp": 9_999_999_999}).encode())
    import hashlib
    import hmac as _hmac
    tanda = sec._b64e(_hmac.new(sec._kunci(), muatan.encode(), hashlib.sha256).digest())
    assert sec.baca_token(f"{muatan}.{tanda}") is None


# ────────────────────── P-S-06 · tujuan setelah masuk ──────────────────────

@pytest.mark.parametrize("jahat", [
    "https://evil.example", "//evil.example", "http://evil.example/x",
    "///evil.example", "\\\\evil.example", "javascript:alert(1)",
    "/\\evil.example", " //evil.example",
])
def test_tujuan_ke_situs_lain_ditolak(jahat):
    """Halaman masuk yang mengantar orang ke situs lain adalah halaman masuk
    yang bisa dipakai memanen sandi: alamatnya benar, tampilannya benar, dan
    yang berikutnya terbuka bukan milik kita."""
    assert sec.tujuan_aman(jahat) == "/"


@pytest.mark.parametrize("baik", ["/", "/aksi", "/laporan?bulan=9", "/stok#g1"])
def test_tujuan_relatif_diterima(baik):
    assert sec.tujuan_aman(baik) == baik


def test_tujuan_kosong_jadi_beranda():
    assert sec.tujuan_aman("") == "/"
    assert sec.tujuan_aman(None) == "/"


# ────────────────────── P-S-04 · pembatas percobaan ──────────────────────

def test_percobaan_gagal_berulang_akhirnya_ditahan():
    """Tanpa pembatas, seluruh daftar sandi bisa dicoba satu per satu, dan
    tak ada satu baris pun yang mencatat bahwa itu terjadi."""
    from app.web import gerbang_masuk as gm

    gm.bersihkan()
    for _ in range(gm.BATAS_GAGAL):
        assert gm.boleh_coba("budi", "10.0.0.1") is None
        gm.catat_gagal("budi", "10.0.0.1")
    tunggu = gm.boleh_coba("budi", "10.0.0.1")
    assert tunggu is not None and tunggu > 0


def test_pembatas_dipisah_per_nama_dan_ip():
    """Satu orang yang salah ketik tak boleh mengunci orang lain di gudang
    yang sama, dan satu penebak tak boleh mengunci nama korbannya."""
    from app.web import gerbang_masuk as gm

    gm.bersihkan()
    for _ in range(gm.BATAS_GAGAL):
        gm.catat_gagal("budi", "10.0.0.1")
    assert gm.boleh_coba("budi", "10.0.0.1") is not None
    assert gm.boleh_coba("sari", "10.0.0.1") is None
    assert gm.boleh_coba("budi", "10.0.0.2") is None


def test_masuk_yang_berhasil_menghapus_hitungannya():
    from app.web import gerbang_masuk as gm

    gm.bersihkan()
    for _ in range(gm.BATAS_GAGAL - 1):
        gm.catat_gagal("budi", "10.0.0.1")
    gm.catat_berhasil("budi", "10.0.0.1")
    for _ in range(gm.BATAS_GAGAL - 1):
        gm.catat_gagal("budi", "10.0.0.1")
    assert gm.boleh_coba("budi", "10.0.0.1") is None


# ────────────────────── P-S-13 · waktu jawab tak membocorkan ──────────────────────

def test_ada_hash_tiruan_untuk_nama_tak_dikenal():
    """Nama yang tak ada dulu dijawab dalam 5 ms dan nama yang ada dalam 55 ms.
    Selisih itu adalah daftar nama pengguna yang bisa dipanen siapa saja."""
    assert sec.cek_sandi("apa pun", sec.HASH_TIRUAN) is False
    assert sec.HASH_TIRUAN.startswith("scrypt$")


async def test_cek_sandi_bisa_dijalankan_di_luar_event_loop():
    """scrypt memakan ~50 ms CPU. Dijalankan langsung di event loop, dua belas
    permintaan bersamaan menaikkan /health dari 4 ms ke 119 ms — seluruh
    aplikasi ikut tersendat oleh orang yang sedang mengetik sandi."""
    h = sec.hash_sandi("gabahkering99")
    assert await sec.cek_sandi_async("gabahkering99", h) is True
    assert await sec.cek_sandi_async("salah", h) is False


# ────────────────────── P-S-15 · CSRF ──────────────────────

def test_token_csrf_dicocokkan_konstan_waktu():
    from app.web import csrf

    t = csrf.terbitkan_baru()
    assert csrf.cocok(t, t) is True
    assert csrf.cocok(t, "x" * len(t)) is False
    assert csrf.cocok("", "") is False
    assert csrf.cocok(t, None) is False


def test_metode_aman_tak_butuh_token():
    from app.web import csrf

    assert csrf.perlu_periksa("GET", "/aksi") is False
    assert csrf.perlu_periksa("HEAD", "/") is False
    assert csrf.perlu_periksa("POST", "/masuk") is True
    assert csrf.perlu_periksa("POST", "/api/actions/jalankan") is True


def test_kait_kesehatan_tak_ikut_dipagari():
    """/health dipanggil Railway tanpa peramban dan tanpa cookie."""
    from app.web import csrf

    assert csrf.perlu_periksa("POST", "/health") is False


# ────────────────────── P-S-14 · token dashboard ──────────────────────

def test_token_dashboard_dibandingkan_konstan_waktu():
    import inspect

    from app import main

    sumber = inspect.getsource(main.dashboard)
    assert "compare_digest" in sumber, "pembanding '!=' membocorkan panjang cocoknya"


# ────────────────────── P-S-16 · SECRET_KEY wajib ──────────────────────

def test_secret_key_kosong_di_produksi_menggagalkan_start(monkeypatch):
    """Kunci sementara berarti seluruh sesi hangus tiap deploy — dan lebih
    buruk, ia membuat kekeliruan konfigurasi tampak seperti gangguan biasa."""
    from app.config import settings
    from app.web import security as s

    monkeypatch.setattr(settings, "secret_key", "", raising=False)
    monkeypatch.setattr(settings, "lingkungan_produksi", True, raising=False)
    s._KUNCI_SEMENTARA = None
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        s._kunci()


def test_secret_key_kosong_di_laptop_masih_boleh(monkeypatch):
    """Pagar yang menghalangi pengembangan akan dimatikan orang, dan yang
    dimatikan tak pernah dinyalakan lagi."""
    from app.config import settings
    from app.web import security as s

    monkeypatch.setattr(settings, "secret_key", "", raising=False)
    monkeypatch.setattr(settings, "lingkungan_produksi", False, raising=False)
    s._KUNCI_SEMENTARA = None
    assert len(s._kunci()) == 32
