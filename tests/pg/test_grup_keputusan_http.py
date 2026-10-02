"""Sub-menu "Menunggu keputusan" lewat jalur HTTP sungguhan.

Keputusan pemilik 2 Oktober 2026: *"lakukan yang sama ke menunggu
keputusan"* — diperjelas *"buat sub menu juga sesuai kategori"*. Grouping
murninya sudah diuji atas angka telanjang di `tests/test_grup_keputusan.py`
(Σ kategori, mutu dikecualikan, syarat dua kategori, kategori == blok
halaman) — di sini yang dibuktikan jalur SUNGGUHANNYA: `/keputusan`
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


async def test_permintaan_tergambar_dan_kategori_lain_kosong(pg, pabrik):
    """⭐ REPRODUKSI SUNGGUHAN: satu permintaan PK nyata, dibaca lewat
    `/keputusan` DAN `/keputusan?kategori=betulkan_bobot_giling` oleh Admin
    yang sungguh login."""
    await _minta(pg, pabrik["op2"])
    c = await _klien(pg, pabrik["adm"])
    try:
        semua = await c.get("/keputusan")
        lain = await c.get("/keputusan?kategori=betulkan_bobot_giling")
        ngawur = await c.get("/keputusan?kategori=tidak-ada")
    finally:
        await c.aclose()

    assert semua.status_code == 200
    assert pabrik["lot"] in semua.text
    # `<div class="saring">` — penanda blok pil ITU SENDIRI di halaman ini.
    # `<a class="pil` SAJA pernah dipakai dan ternyata longgar: kartu
    # "Setujui/Tolak permintaan" sungguhan merender `class="pilihan__satu"`
    # sebagai `<a>`, yang diawali huruf sama ("pil"). `keputusan.html` tak
    # punya fitur lain yang memakai `.saring` (beda dengan `aksi.html`, yang
    # memakainya untuk kotak cari) — jadi di SINI penandanya aman dipakai.
    assert '<div class="saring">' not in semua.text

    assert lain.status_code == 200
    assert "Kategori ini kosong" in lain.text
    assert pabrik["lot"] not in lain.text

    # Alamat kategori yang tak dikenal diperlakukan seperti "semua" — bukan
    # galat, sebab ia bisa datang dari tautan lama atau salah ketik.
    assert ngawur.status_code == 200
    assert pabrik["lot"] in ngawur.text


async def test_dua_kategori_lahir_dari_satu_lot_tetap_terpisah(pg, pabrik):
    """⭐ INTI PERMINTAANNYA, via HTTP: "Permintaan lot PK dari Gudang 2"
    DAN "Kiriman PK menunggu ditutup" adalah DUA kategori — bukan satu
    golongan "permintaan" tergabung — begitu permintaan yang sama berjalan
    sampai tahap kirim."""
    from sqlalchemy import select

    from app.models import User
    from app.services.permintaan_pk import kirim, setujui

    pid = (await _minta(pg, pabrik["op2"])).id
    async with pg() as db:
        adm = await db.get(User, pabrik["adm"])
        await setujui(db, user=adm, permintaan_id=pid, tujuan="A", berat=1_000)
    async with pg() as db:
        # "Kiriman PK menunggu ditutup" muncul begitu statusnya DIKIRIM —
        # disetujui saja belum cukup (kartunya masih "menunggu Gudang 1
        # memuat", bukan "menunggu ditutup Admin").
        op1 = await db.get(User, pabrik["op1"])
        await kirim(db, user=op1, permintaan_id=pid, berat=1_000)

    c = await _klien(pg, pabrik["adm"])
    try:
        semua = await c.get("/keputusan")
        satu = await c.get("/keputusan?kategori=tutup_permintaan_pk")
    finally:
        await c.aclose()

    assert semua.status_code == 200
    assert "Kiriman PK menunggu ditutup" in semua.text
    assert satu.status_code == 200
    assert pabrik["lot"] in satu.text


async def test_submenu_keputusan_di_laci_sesuai_isi_sungguhan(pg, pabrik):
    """`Berjalan.submenu()["keputusan"]` dihitung dari jalur AGREGASI penuh
    (`svc.untuk`), bukan dipanggil terisolasi — membuktikan ia benar-benar
    terhubung ke `can_see_financials` dan pengumpulan `untuk_gudang2`/
    `untuk_staff` yang sesungguhnya dipakai server."""
    from app.models import User
    from app.services import berjalan as svc

    await _minta(pg, pabrik["op2"])
    async with pg() as db:
        adm = await db.get(User, pabrik["adm"])
        b = await svc.untuk(db, adm)

    # Satu kategori saja ("acc_permintaan_pk") → sub-menu TAK ditawarkan di
    # laci, persis seperti Antrian tunggu saat cuma satu grup berisi.
    assert "keputusan" not in b.submenu()
    assert b.jumlah_keputusan == 1
