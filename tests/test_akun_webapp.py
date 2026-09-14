"""Uji kredensial & sesi webapp produksi (Fase B, B1).

Yang dijaga di sini adalah janji-janji yang mahal bila dilanggar:

  · sandi tak pernah bisa dibaca balik, dan sandi salah tak pernah lolos;
  · token sesi yang diutak-atik satu huruf pun ditolak — tanda tangannya, bukan
    isinya, yang menentukan;
  · token kedaluwarsa ditolak walau tanda tangannya sah;
  · operator mendapat sesi PENDEK dan admin sesi panjang, karena operator
    memakai perangkat gudang yang dipakai bergantian — sesi panjang di sana
    berarti pekerjaan tercatat atas nama orang sebelumnya.
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest

from app.models.akun import mode_bawaan
from app.web import security as sec


# ─────────────────────────── Sandi ───────────────────────────

def test_sandi_benar_lolos_dan_salah_ditolak():
    h = sec.hash_sandi("gabahkering99")
    assert sec.cek_sandi("gabahkering99", h)
    assert not sec.cek_sandi("gabahkering98", h)
    assert not sec.cek_sandi("", h)


def test_hash_tak_menyimpan_sandi_dan_selalu_bergaram_baru():
    h1 = sec.hash_sandi("sandiyangsama")
    h2 = sec.hash_sandi("sandiyangsama")
    assert "sandiyangsama" not in h1
    assert h1 != h2, "garam harus acak per akun — hash sama = garam dipakai ulang"
    assert sec.cek_sandi("sandiyangsama", h1)
    assert sec.cek_sandi("sandiyangsama", h2)


def test_sandi_terlalu_pendek_ditolak():
    with pytest.raises(ValueError):
        sec.hash_sandi("abc12")


@pytest.mark.parametrize("rusak", ["", "bukan-hash", "scrypt$16384$8$1$abc", "md5$1$1$1$aa$bb"])
def test_hash_rusak_tak_pernah_meloloskan(rusak):
    assert not sec.cek_sandi("apa pun", rusak)


def test_sandi_acak_menghindari_huruf_rancu():
    """Sandi awal dibacakan lewat telepon — 'l' vs '1' dan 'O' vs '0' celaka."""
    contoh = "".join(sec.sandi_acak() for _ in range(40))
    assert not set(contoh) & set("ilo01"), contoh
    assert len(sec.sandi_acak()) == 10
    assert sec.sandi_acak() != sec.sandi_acak()


# ─────────────────────────── Sesi ───────────────────────────

class AkunPalsu:
    def __init__(self, id: int = 7, mode: str = "pribadi"):
        self.id = id
        self.mode_perangkat = mode

    @property
    def sesi_pendek(self) -> bool:
        return self.mode_perangkat == "bersama"


def test_token_pulang_pergi():
    """`baca_token` kini mengembalikan (id, versi) — versinyalah yang membuat
    sesi yang sudah beredar bisa ditarik kembali. Lihat P-S-05 di
    `test_sesi_dan_login.py`."""
    akun = AkunPalsu(id=42)
    assert sec.baca_token(sec.buat_token(akun)) == (42, 1)


def test_token_yang_diutak_atik_ditolak():
    token = sec.buat_token(AkunPalsu(id=1))
    payload, _, tanda = token.partition(".")

    # Isi diganti jadi akun lain, tanda tangan lama dipertahankan.
    palsu = sec._b64e(json.dumps(
        {"sub": 999, "exp": int((datetime.now(timezone.utc) + timedelta(days=1)).timestamp())},
        separators=(",", ":"),
    ).encode())
    assert sec.baca_token(f"{palsu}.{tanda}") is None

    # Tanda tangan diubah satu huruf.
    ubah = ("A" if tanda[0] != "A" else "B") + tanda[1:]
    assert sec.baca_token(f"{payload}.{ubah}") is None


@pytest.mark.parametrize("token", [None, "", "tanpa-titik", "a.b", "..", "x." + "y" * 40])
def test_token_ngawur_ditolak(token):
    assert sec.baca_token(token) is None


def test_token_kedaluwarsa_ditolak_meski_tanda_tangannya_sah():
    lampau = int((datetime.now(timezone.utc) - timedelta(seconds=5)).timestamp())
    payload = sec._b64e(json.dumps({"sub": 3, "exp": lampau}, separators=(",", ":")).encode())
    import hashlib
    import hmac as _hmac
    tanda = sec._b64e(_hmac.new(sec._kunci(), payload.encode(), hashlib.sha256).digest())
    assert sec.baca_token(f"{payload}.{tanda}") is None


def test_umur_sesi_beda_menurut_perangkat():
    from app.config import settings

    panjang = sec.umur_sesi_detik(AkunPalsu(mode="pribadi"))
    pendek = sec.umur_sesi_detik(AkunPalsu(mode="bersama"))
    assert panjang == settings.sesi_hari * 24 * 3600
    assert pendek == settings.sesi_bersama_menit * 60
    assert pendek < panjang, "perangkat gudang harus jauh lebih cepat kedaluwarsa"


# ─────────────────────── Jenis perangkat per peran ───────────────────────

@pytest.mark.parametrize("peran,harapan", [
    ("operator", "bersama"),   # perangkat gudang: data pabrik tak menetap di HP pribadi
    ("admin", "pribadi"),
    ("peran_baru_yang_belum_ada", "pribadi"),
])
def test_mode_perangkat_bawaan_menurut_peran(peran, harapan):
    assert mode_bawaan(peran) == harapan
