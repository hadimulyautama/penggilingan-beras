"""Satu identitas untuk semua pintu — diuji di Postgres lewat HTTP.

Temuan QA X-11 (tiga bendera nonaktif), M-06 (gerbang Meja menyebut peran
satu per satu), P-S-10 (jaring pengaman tanpa langit-langit). Yang dijaga
di sini adalah PINTU produksi dan pintu yang produksi buka untuk Meja &
Gudang 2 (`/internal/meja/masuk` + header akun) — pintu timbangan diuji di
repo timbangan dengan fungsi paket yang sama.
"""
from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.asyncio

TOKEN_MEJA = "token-uji-meja"


async def _orang(pg, *, nama, role, username, gudang: str | None = None, sandi="rahasia123") -> tuple[int, int]:
    from sqlalchemy import select

    from app.models import ProduksiAkun, User, Warehouse
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    async with pg() as db:
        wid = None
        if gudang:
            wid = (await db.execute(select(Warehouse.id).where(Warehouse.nama_gudang.like(gudang + "%")))).scalars().first()
            if wid is None:
                w = Warehouse(nama_gudang=gudang + " — uji")
                db.add(w)
                await db.flush()
                wid = w.id
        u = User(nama=nama, role=role, status="aktif", default_warehouse_id=wid)
        db.add(u)
        await db.flush()
        a = ProduksiAkun(user_id=u.id, username=username, password_hash=S.hash_sandi(sandi),
                         status="aktif", mode_perangkat=mode_bawaan(role))
        db.add(a)
        await db.commit()
        return a.id, u.id


def _klien(monkeypatch) -> httpx.AsyncClient:
    from app.config import settings
    from app.main import app

    monkeypatch.setattr(settings, "meja_api_token", TOKEN_MEJA)
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://uji")


async def _token(pg, akun_id: int) -> str:
    from app.models import ProduksiAkun
    from app.web.security import buat_token

    async with pg() as db:
        return buat_token(await db.get(ProduksiAkun, akun_id))


async def _masuk_meja(c, username, aplikasi, sandi="rahasia123"):
    return await c.post("/internal/meja/masuk",
                        json={"username": username, "sandi": sandi, "aplikasi": aplikasi},
                        headers={"X-Internal-Token": TOKEN_MEJA})


# ── Pintu per aplikasi (keputusan pemilik 13 Sep) ──────────────────────

async def test_operator_tak_masuk_meja_tapi_masuk_gudangnya(pg, monkeypatch):
    await _orang(pg, nama="Dany", role="operator", username="dany", gudang="Gudang 2")
    async with _klien(monkeypatch) as c:
        r = await _masuk_meja(c, "dany", "meja")
        assert r.status_code == 403 and "operator" in r.json()["detail"].lower()
        r = await _masuk_meja(c, "dany", "gudang2")
        assert r.status_code == 200 and r.json()["lingkup"] == "g2"


async def test_operator_gudang_1_boleh_masuk_gudang_2_dan_bekerja_di_sana(pg, monkeypatch):
    """Pemilik 13 Sep 2026: operator saling menggantikan. Operator Gudang 1
    masuk aplikasi Gudang 2, dan dengan header `X-Meja-Lihat: operator:g2`
    produksi memperlakukannya sebagai operator Gudang 2 (view polesan)."""
    await _orang(pg, nama="Dany", role="operator", username="dany", gudang="Gudang 2")  # gudang 2 ada
    aid, _ = await _orang(pg, nama="Marno", role="operator", username="marno", gudang="Gudang 1")
    async with _klien(monkeypatch) as c:
        r = await _masuk_meja(c, "marno", "gudang2")
        assert r.status_code == 200 and r.json()["lingkup"] == "g1"
        kepala = {"X-Internal-Token": TOKEN_MEJA, "X-Meja-Akun": str(aid), "X-Meja-Versi": str(r.json()["versi"])}
        saya = (await c.get("/internal/meja/saya", headers=kepala)).json()
        assert saya["view"] == "selepan"
        saya2 = (await c.get("/internal/meja/saya", headers={**kepala, "X-Meja-Lihat": "operator:g2"})).json()
        assert saya2["view"] == "polesan" and saya2["peran"] == "operator"
        assert (await c.get("/internal/gudang2/beranda", headers={**kepala, "X-Meja-Lihat": "operator:g2"})).status_code == 200


async def test_admin_masuk_meja_tak_masuk_gudang_2_superadmin_kemana_saja(pg, monkeypatch):
    await _orang(pg, nama="Elfira", role="admin", username="elfira")
    await _orang(pg, nama="Wahid", role="superadmin", username="wahid")
    async with _klien(monkeypatch) as c:
        assert (await _masuk_meja(c, "elfira", "meja")).status_code == 200
        assert (await _masuk_meja(c, "elfira", "gudang2")).status_code == 403
        for ap in ("meja", "gudang2", "produksi", "timbangan"):
            assert (await _masuk_meja(c, "wahid", ap)).status_code == 200, ap


# ── Satu saklar nonaktif memutus kedua jalur pada permintaan berikutnya ──

async def test_nonaktif_memutus_cookie_dan_jalur_meja(pg, monkeypatch):
    from hmu_identitas import masuk

    aid, uid = await _orang(pg, nama="Eka", role="admin", username="eka")
    tok = await _token(pg, aid)
    async with _klien(monkeypatch) as c:
        r = await _masuk_meja(c, "eka", "meja")
        versi = r.json()["versi"]
        kepala = {"X-Internal-Token": TOKEN_MEJA, "X-Meja-Akun": str(aid), "X-Meja-Versi": str(versi)}
        assert (await c.get("/internal/meja/saya", headers=kepala)).status_code == 200
        c.cookies.set("produksi_sesi", tok)
        assert (await c.get("/pengaturan")).status_code == 200

        async with pg() as db:
            await masuk.nonaktifkan(db, uid)

        assert (await c.get("/internal/meja/saya", headers=kepala)).status_code == 401
        r = await c.get("/pengaturan")
        assert r.status_code in (302, 303) and "/masuk" in r.headers["location"]
        # Masuk lagi pun ditolak — bukan hanya sesinya yang putus.
        assert (await _masuk_meja(c, "eka", "meja")).status_code == 403


# ── Jaring pengaman: Super Admin aktif terakhir tak bisa dinonaktifkan ──

async def test_superadmin_terakhir_tak_bisa_dinonaktifkan_lewat_layar(pg, monkeypatch):
    from app.web import csrf

    bos, _ = await _orang(pg, nama="Wahid", role="superadmin", username="wahid")
    async with _klien(monkeypatch) as c:
        t = csrf.terbitkan_baru()
        c.cookies.set("produksi_sesi", await _token(pg, bos))
        c.cookies.set(csrf.NAMA_COOKIE, t)
        r = await c.post("/pengguna/status", data={"akun_id": bos, "_csrf": t})
        assert r.status_code == 200 and "terakhir" in r.text
        c2 = await c.get("/pengaturan")
        assert c2.status_code == 200  # masih masuk: tak ada yang berubah
