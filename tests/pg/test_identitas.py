"""Satu identitas untuk semua pintu — diuji di Postgres lewat HTTP.

Temuan QA X-11 (tiga bendera nonaktif), M-06 (gerbang yang menyebut peran satu
per satu), P-S-10 (jaring pengaman tanpa langit-langit).

Sampai 24 September 2026 sebagian besar berkas ini menguji pintu yang produksi
buka untuk app Meja & Gudang 2 (`/internal/meja/masuk` + header akun). Kedua
app dihapus hari itu atas keputusan pemilik, dan pintunya ikut dicabut — jadi
yang tersisa di sini pintu produksi sendiri (kuki) plus aturan `hmu_identitas.
pintu` yang masih mengatur produksi, timbangan, dan Kantor. Pintu timbangan
diuji di repo timbangan dengan fungsi paket yang sama.
"""
from __future__ import annotations

import httpx
import pytest

pytestmark = pytest.mark.asyncio


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
                w = Warehouse(nama_gudang=gudang + " — uji", kode_fungsi={"Gudang 1": "g1", "Gudang 2": "g2"}[gudang])
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
    from app.main import app

    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://uji")


async def _token(pg, akun_id: int) -> str:
    from app.models import ProduksiAkun
    from app.web.security import buat_token

    async with pg() as db:
        return buat_token(await db.get(ProduksiAkun, akun_id))


# ── Pintu per aplikasi (keputusan pemilik 13 Sep) ──────────────────────
#
# Dulu diuji lewat HTTP ke `/internal/meja/masuk` dengan `aplikasi=meja|gudang2`.
# Pintu itu dicabut bersama kedua app (24 September 2026). Aturannya TIDAK ikut
# dicabut: ia milik paket `hmu_identitas.pintu` dan masih menjaga produksi,
# timbangan, dan Kantor — jadi yang diuji sekarang aturannya langsung, plus
# pintu produksi sendiri lewat kukinya.

async def test_pintu_per_aplikasi_masih_memilah_peran(pg):
    from hmu_identitas import peran as P
    from hmu_identitas import pintu

    # Operator tak masuk lewat pintu meja/kantor, tetapi masuk gudangnya.
    assert pintu.sebab_tolak(P.OPERATOR, pintu.MEJA)
    assert pintu.sebab_tolak(P.OPERATOR, pintu.KANTOR)
    assert pintu.sebab_tolak(P.OPERATOR, pintu.PRODUKSI) is None
    assert pintu.sebab_tolak(P.OPERATOR, pintu.TIMBANGAN) is None
    # Admin: meja & kantor & produksi & timbangan, bukan app operator gudang.
    assert pintu.sebab_tolak(P.ADMIN, pintu.GUDANG2)
    for ap in (pintu.PRODUKSI, pintu.TIMBANGAN, pintu.KANTOR, pintu.MEJA):
        assert pintu.sebab_tolak(P.ADMIN, ap) is None, ap
    # Super Admin ke mana saja.
    for ap in pintu.SEMUA_APLIKASI:
        assert pintu.sebab_tolak(P.SUPERADMIN, ap) is None, ap
    # Dan peran yang dipensiunkan ditolak dengan kalimat yang menyebut sebabnya.
    for lama in P.PERAN_PENSIUN:
        assert "dipensiunkan" in (pintu.sebab_tolak(lama, pintu.PRODUKSI) or "")


async def test_operator_gudang_1_boleh_bekerja_di_gudang_2(pg, monkeypatch):
    """Pemilik 13 Sep 2026: operator saling menggantikan.

    Dulu dibuktikan lewat header `X-Meja-Lihat` dari app Gudang 2. Sekarang
    lewat jalan yang sama yang dipakai orangnya di Pos Produksi: "Kerja di
    gudang" di Pengaturan, yaitu POST /lihat-sebagai lalu kukinya.
    """
    from app.web import csrf

    await _orang(pg, nama="Dany", role="operator", username="dany", gudang="Gudang 2")
    aid, _ = await _orang(pg, nama="Marno", role="operator", username="marno",
                          gudang="Gudang 1")
    async with _klien(monkeypatch) as c:
        t = csrf.terbitkan_baru()
        c.cookies.set("produksi_sesi", await _token(pg, aid))
        c.cookies.set(csrf.NAMA_COOKIE, t)
        # Layar pertamanya gudangnya sendiri.
        assert "Operator selepan" in (await c.get("/pengaturan")).text
        r = await c.post("/lihat-sebagai", data={"peran": "operator:g2", "_csrf": t})
        assert r.status_code in (302, 303)
        # Sesudah itu ia bekerja sebagai operator Gudang 2 — dan pitanya
        # menyebutkannya di atas setiap layar.
        h = (await c.get("/pengaturan")).text
        assert "Operator polesan" in h
        assert "BEKERJA DI GUDANG 2" in h


# ── Satu saklar nonaktif memutus kedua jalur pada permintaan berikutnya ──

async def test_nonaktif_memutus_sesi_pada_permintaan_berikutnya(pg, monkeypatch):
    """Satu saklar di master, dan ia berlaku pada permintaan BERIKUTNYA — bukan
    sesudah sesinya kedaluwarsa sendiri (QA X-11)."""
    from hmu_identitas import masuk

    aid, uid = await _orang(pg, nama="Eka", role="admin", username="eka")
    tok = await _token(pg, aid)
    async with _klien(monkeypatch) as c:
        c.cookies.set("produksi_sesi", tok)
        assert (await c.get("/pengaturan")).status_code == 200

        async with pg() as db:
            await masuk.nonaktifkan(db, uid)

        r = await c.get("/pengaturan")
        assert r.status_code in (302, 303) and "/masuk" in r.headers["location"]
        # Masuk lagi pun ditolak — bukan hanya sesinya yang putus.
        from hmu_identitas import masuk as _m
        async with pg() as db:
            try:
                await _m.periksa_kredensial(db, "eka", "rahasia123")
                gagal = False
            except _m.Tolak:
                gagal = True
        assert gagal, "akun nonaktif masih bisa masuk lagi"


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
