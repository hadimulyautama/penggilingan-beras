"""Sub-menu "Menunggu keputusan" lewat jalur HTTP sungguhan.

Keputusan pemilik 2 Oktober 2026: *"lakukan yang sama ke menunggu
keputusan."* Grouping murninya sudah diuji atas angka telanjang di
`tests/test_grup_keputusan.py` (Σ grup, mutu dikecualikan, syarat dua
golongan) — di sini yang dibuktikan jalur SUNGGUHANNYA: `/keputusan`
dirender lewat HTTP atas data real (`permintaan_pk.minta()`, fixture yang
sama dipakai `tests/pg/test_permintaan_pk.py`), bukan `Baris` buatan tangan.
"""
from __future__ import annotations

import httpx
import pytest

from tests.pg.test_permintaan_pk import _minta, pabrik  # noqa: F401 — fixture

pytestmark = pytest.mark.asyncio


async def _klien(pg, uid) -> httpx.AsyncClient:
    from app.main import app
    from app.models import User
    from app.web import csrf, security

    async with pg() as db:
        u = await db.get(User, uid)
        tok = security.buat_token_untuk_user(u) if hasattr(
            security, "buat_token_untuk_user") else None
    if tok is None:
        # Jalur yang dipakai seluruh uji HTTP lain di repo ini: akun login
        # sungguhan, bukan menembus token langsung dari `User`.
        from app.models import ProduksiAkun
        from hmu_identitas import sandi as S
        from hmu_identitas.model import mode_bawaan

        async with pg() as db:
            u = await db.get(User, uid)
            a = ProduksiAkun(user_id=u.id, username=f"gk{u.id}",
                             password_hash=S.hash_sandi("rahasia123"),
                             status="aktif", mode_perangkat=mode_bawaan(u.role))
            db.add(a)
            await db.commit()
            tok = security.buat_token(a)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),
                          base_url="http://uji", follow_redirects=True)
    c.cookies.set(security.NAMA_COOKIE, tok)
    c.cookies.set(csrf.NAMA_COOKIE, csrf.terbitkan_baru())
    return c


async def test_permintaan_tergambar_dan_golongan_lain_kosong(pg, pabrik):
    """⭐ REPRODUKSI SUNGGUHAN: satu permintaan PK nyata, dibaca lewat
    `/keputusan` DAN `/keputusan?golongan=output` oleh Admin yang sungguh
    login."""
    await _minta(pg, pabrik["op2"])
    c = await _klien(pg, pabrik["adm"])
    try:
        semua = await c.get("/keputusan")
        output = await c.get("/keputusan?golongan=output")
        ngawur = await c.get("/keputusan?golongan=tidak-ada")
    finally:
        await c.aclose()

    assert semua.status_code == 200
    assert pabrik["lot"] in semua.text
    # Satu golongan saja berisi — dropdown tak ditawarkan di dalam halaman
    # (syarat ≥2, sama dengan Antrian tunggu), tetapi alamat golongan lain
    # tetap SAH dan menjawab kosong, bukan 404/422.
    assert '<div class="saring">' not in semua.text

    assert output.status_code == 200
    assert "Golongan ini kosong" in output.text
    assert pabrik["lot"] not in output.text

    # Alamat golongan yang tak dikenal diperlakukan seperti "semua" — bukan
    # galat, sebab ia bisa datang dari tautan lama atau salah ketik.
    assert ngawur.status_code == 200
    assert pabrik["lot"] in ngawur.text


async def test_submenu_keputusan_di_laci_sesuai_isi_sungguhan(pg, pabrik):
    """`Berjalan.submenu()["keputusan"]` dihitung dari jalur AGREGASI penuh
    (`svc.untuk`), bukan dipanggil terisolasi — membuktikan ia benar-benar
    terhubung ke `can_see_financials` dan pengumpulan `untuk_gudang2`/
    `untuk_staff` yang sesungguhnya dipakai server."""
    from sqlalchemy import select

    from app.models import User
    from app.services import berjalan as svc

    await _minta(pg, pabrik["op2"])
    async with pg() as db:
        adm = await db.get(User, pabrik["adm"])
        b = await svc.untuk(db, adm)

    # Satu golongan saja ("permintaan") → sub-menu TAK ditawarkan di laci,
    # persis seperti Antrian tunggu saat cuma satu grup berisi.
    assert "keputusan" not in b.submenu()
    assert b.jumlah_keputusan == 1
