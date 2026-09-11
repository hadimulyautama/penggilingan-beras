"""Formulir POST benar-benar dipagari, dan yang sah benar-benar lewat.

Temuan QA P-S-15. Diuji lewat HTTP sungguhan, bukan lewat pemanggilan fungsi,
karena yang bisa salah justru di lapisan itu: middleware memegang objek
`Request` sendiri, terpisah dari yang diterima rutenya. Membaca badan
permintaan di middleware tanpa mengembalikannya membuat SETIAP kiriman
formulir menggantung — dan menggantung tak berbunyi seperti galat, jadi ia
bisa lolos ke produksi.
"""
from __future__ import annotations

import httpx
import pytest

from app.main import app
from app.web import csrf


@pytest.fixture
def klien():
    transport = httpx.ASGITransport(app=app)
    return httpx.AsyncClient(transport=transport, base_url="http://uji")


async def test_post_tanpa_token_ditolak(klien):
    async with klien as c:
        r = await c.post("/masuk", data={"username": "budi", "sandi": "x"})
    assert r.status_code == 403
    assert "kedaluwarsa" in r.text.lower()


class _SesiKosong:
    """Basis data tiruan yang tak punya satu akun pun.

    Ujinya tentang LAPISAN HTTP, bukan tentang kredensial — memakai Postgres
    di sini hanya menambah satu alasan uji ini gagal karena hal lain.
    """

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def execute(self, *_a, **_k):
        class _Hasil:
            def scalars(self_inner):
                return self_inner

            def first(self_inner):
                return None

        return _Hasil()


async def test_post_dengan_token_cocok_diteruskan(klien, monkeypatch):
    """Yang diuji: permintaannya SAMPAI ke rutenya dan badannya UTUH.

    Jawabannya bukan 403 dan bukan menggantung; isinya kembali ke formulir
    masuk dengan pesan "nama pengguna atau kata sandi salah" — artinya rute
    benar-benar membaca `username` dan `sandi` dari badan yang sama, sesudah
    middleware membacanya lebih dulu.
    """
    from app.web import auth

    monkeypatch.setattr(auth, "SessionLocal", _SesiKosong)

    t = csrf.terbitkan_baru()
    async with klien as c:
        c.cookies.set(csrf.NAMA_COOKIE, t)
        r = await c.post("/masuk", data={"username": "tidakada",
                                         "sandi": "salahsekali", "_csrf": t})
    assert r.status_code == 200
    assert "salah" in r.text.lower()
    # Nama pengguna dikembalikan ke formulir — bukti badannya sampai utuh.
    assert "tidakada" in r.text


async def test_token_tak_cocok_ditolak(klien):
    async with klien as c:
        c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
        r = await c.post("/masuk", data={"username": "budi", "sandi": "x",
                                         "_csrf": csrf.terbitkan_baru()})
    assert r.status_code == 403


async def test_permintaan_json_boleh_pakai_header(klien):
    """Layar aksi mengirim JSON, bukan formulir. Ia membaca tokennya dari
    kuki-nya sendiri dan menaruhnya di header."""
    t = csrf.terbitkan_baru()
    async with klien as c:
        c.cookies.set(csrf.NAMA_COOKIE, t)
        r = await c.post("/miniapp/actions/tak-ada", json={"a": 1},
                         headers={csrf.NAMA_HEADER: t})
    assert r.status_code != 403


async def test_halaman_masuk_membawa_token_di_formulirnya(klien):
    async with klien as c:
        r = await c.get("/masuk")
    assert r.status_code == 200
    assert 'name="_csrf"' in r.text
    assert csrf.NAMA_COOKIE in r.headers.get("set-cookie", "")


async def test_health_tak_ikut_dipagari(klien):
    async with klien as c:
        r = await c.get("/health")
    assert r.status_code == 200
