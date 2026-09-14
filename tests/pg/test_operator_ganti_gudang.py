"""Operator boleh memegang lebih dari satu gudang — temuan QA P4-01 (KRITIS).

Pemilik: "operator bisa jadi operator gudang 1 atau gudang 2, karena saling
backup jika ada yang berhalangan." Sejak 13 Sep 2026 `users.default_warehouse_id`
hanya gudang UTAMA (layar pertama); gudang yang sedang DIKERJAKAN adalah
keadaan SESI — kuki `produksi_lihat` = `operator:g2`, dipasang lewat
"Kerja di gudang" di Pengaturan, dan diterapkan `akun_opsional` pada objek
pengguna SESUDAH sesi basis data ditutup sehingga tak pernah ikut tersimpan.

Yang dijaga di sini, lewat HTTP di Postgres:
- operator bergantian mengerjakan G1 dan G2 tanpa admin menyentuh apa pun;
- satu sesi = satu gudang: aksi gudang sebelah ditolak sampai ia berpindah;
- gudang aktif satu perangkat tak mempengaruhi perangkat lain orang yang sama;
- catatan yang dibuat jatuh ke gudang yang AKTIF, dan profilnya tetap;
- ia TAHU sedang di gudang mana: pita mencolok di atas setiap layar;
- akun yang dinonaktifkan terputus di sesi yang sedang terbuka.
"""
from __future__ import annotations

from datetime import date

import httpx
import pytest
from sqlalchemy import select

pytestmark = pytest.mark.asyncio

KUKI_GUDANG = "produksi_lihat"


async def _orang(pg, *, nama, role, username, gudang_id, sandi="rahasia123") -> tuple[int, int]:
    from app.models import ProduksiAkun, User
    from hmu_identitas import sandi as S
    from hmu_identitas.model import mode_bawaan

    async with pg() as db:
        u = User(nama=nama, role=role, status="aktif", default_warehouse_id=gudang_id)
        db.add(u)
        await db.flush()
        a = ProduksiAkun(user_id=u.id, username=username, password_hash=S.hash_sandi(sandi),
                         status="aktif", mode_perangkat=mode_bawaan(role))
        db.add(a)
        await db.commit()
        return a.id, u.id


async def _token(pg, akun_id: int) -> str:
    from app.models import ProduksiAkun
    from app.web.security import buat_token

    async with pg() as db:
        return buat_token(await db.get(ProduksiAkun, akun_id))


def _klien(token: str, *, gudang: str | None = None) -> httpx.AsyncClient:
    """Satu perangkat: sesi + CSRF, dan (bila diminta) gudang yang dipilih."""
    from app.main import app
    from app.web import csrf, security

    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://uji")
    t = csrf.terbitkan_baru()
    c.cookies.set(security.NAMA_COOKIE, token)
    c.cookies.set(csrf.NAMA_COOKIE, t)
    if gudang:
        c.cookies.set(KUKI_GUDANG, f"operator:{gudang}")
    c.headers[csrf.NAMA_HEADER] = t
    c._csrf = t
    return c


async def _gudang_di_db(pg, user_id: int) -> int | None:
    from app.models import User

    async with pg() as db:
        return (await db.get(User, user_id)).default_warehouse_id


@pytest.fixture
async def pabrik(pg, pemasok):
    """Dua gudang, silo G2, satu operator berprofil Gudang 1, satu admin, dan
    satu PK luar 15 t yang sudah ditumpuk di Gudang 2 (pekerjaan admin)."""
    from app.database import now_local
    from app.models import Silo, Warehouse
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import masukkan_pk_luar
    from app.models import User
    from hmu_identitas import peran as P

    async with pg() as db:
        g1 = Warehouse(nama_gudang="Gudang 1 - Selepan")
        g2 = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add_all([g1, g2])
        await db.flush()
        db.add_all([Silo(nama_silo="Silo A", warehouse_id=g2.id), Silo(nama_silo="Silo B", warehouse_id=g2.id)])
        await db.commit()
        g1_id, g2_id = g1.id, g2.id
    op_akun, op = await _orang(pg, nama="Marno", role=P.OPERATOR, username="marno", gudang_id=g1_id)
    adm_akun, adm = await _orang(pg, nama="Elfira", role=P.ADMIN, username="elfira", gudang_id=None)
    async with pg() as db:
        db.add(PkPurchaseBatch(kode_batch="PKB-UJI-01", supplier_id=pemasok.id, berat_total_kg=15_000,
                               tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                               input_by=adm, status_batch="diterima", flag_unverified=True,
                               sumber_berat="manual"))
        await db.commit()
        a = await db.get(User, adm)
        r = await masukkan_pk_luar(db, user=a, kode="PKB-UJI-01", tujuan="ditumpuk")
        intake = r.intake.id
    return {"g1": g1_id, "g2": g2_id, "op": op, "op_akun": op_akun, "adm": adm, "intake": intake,
            "token": await _token(pg, op_akun)}


G1_SAJA = "/miniapp/actions/drying-active"      # gerbang _is_g1_operator
G2_SAJA = "/miniapp/actions/polishing-active"   # gerbang _is_g2_operator


async def test_operator_bergantian_gudang_tanpa_admin(pg, pabrik):
    """G1 → pindah ke G2 → kembali, semuanya dari layarnya sendiri. Dan satu
    sesi hanya satu gudang: yang di seberang tertutup sampai ia berpindah."""
    async with _klien(pabrik["token"]) as c:
        assert (await c.get(G1_SAJA)).status_code == 200
        assert (await c.get(G2_SAJA)).status_code == 403

        r = await c.post("/lihat-sebagai", data={"peran": "operator:g2", "_csrf": c._csrf})
        assert r.status_code == 303 and c.cookies.get(KUKI_GUDANG) == "operator:g2"
        assert (await c.get(G2_SAJA)).status_code == 200
        assert (await c.get(G1_SAJA)).status_code == 403

        r = await c.post("/lihat-sebagai/selesai", data={"_csrf": c._csrf})
        assert r.status_code == 303
        assert (await c.get(G1_SAJA)).status_code == 200
        assert (await c.get(G2_SAJA)).status_code == 403
    # Profilnya tak pernah disentuh.
    assert await _gudang_di_db(pg, pabrik["op"]) == pabrik["g1"]


async def test_gudang_aktif_milik_sesi_bukan_milik_orangnya(pg, pabrik):
    """Ponsel A sedang di Gudang 2, perangkat gudang B tetap di Gudang 1 —
    orang yang sama, sesi yang sama, kuki yang berbeda."""
    async with _klien(pabrik["token"], gudang="g2") as a, _klien(pabrik["token"]) as b:
        assert (await a.get("/miniapp/me")).json()["default_warehouse_id"] == pabrik["g2"]
        assert (await b.get("/miniapp/me")).json()["default_warehouse_id"] == pabrik["g1"]
        assert (await a.get(G2_SAJA)).status_code == 200
        assert (await b.get(G2_SAJA)).status_code == 403
    assert await _gudang_di_db(pg, pabrik["op"]) == pabrik["g1"]


async def test_catatan_jatuh_ke_gudang_yang_aktif_saat_itu(pg, pabrik):
    """Operator Gudang 1 yang sedang menggantikan di Gudang 2 memindahkan PK
    dari tumpukan ke silo: catatannya milik Gudang 2 — dan cakupan pembatalan
    'operator Gudang 2' menemukannya (sambungan ke P4-02)."""
    from app.models import ActivityLog
    from app.services import undo as svc

    isi = {"tumpukan": str(pabrik["intake"]), "silo": "A", "berat_kg": 5000}
    async with _klien(pabrik["token"]) as b:
        # Di sesi Gudang 1 pekerjaan Gudang 2 ditolak — bukan tercatat ke gudang yang salah.
        assert (await b.post("/miniapp/actions/pindah-tumpukan-silo", json=isi)).status_code == 403
    async with _klien(pabrik["token"], gudang="g2") as a:
        r = await a.post("/miniapp/actions/pindah-tumpukan-silo", json=isi)
        assert r.status_code == 200, r.text
        assert r.json()["ok"] is True

    async with pg() as db:
        log = (await db.execute(
            select(ActivityLog).where(ActivityLog.changed_by == pabrik["op"])
            .order_by(ActivityLog.id.desc()))).scalars().first()
        assert log.table_name == "pk_tumpukan_to_silo" and log.gudang == "g2"
        c2 = await svc.cakupan(db, scope="operator_gudang2", nama=None, self_id=0)
        c1 = await svc.cakupan(db, scope="operator_gudang1", nama=None, self_id=0)
        assert (await svc.pratinjau_terakhir(db, cakupan=c2)).log_id == log.id
        assert await svc.pratinjau_terakhir(db, cakupan=c1) is None
    assert await _gudang_di_db(pg, pabrik["op"]) == pabrik["g1"]


async def test_operator_tahu_sedang_di_gudang_mana(pg, pabrik):
    """Salah kira gudang = mencatat ke tempat yang salah. Pita di atas setiap
    layar menyebutnya, dan hilang begitu ia kembali ke gudang utamanya."""
    async with _klien(pabrik["token"], gudang="g2") as a, _klien(pabrik["token"]) as b:
        di_g2 = (await a.get("/")).text
        di_g1 = (await b.get("/")).text
    assert "BEKERJA DI GUDANG 2" in di_g2 and "bukan gudang utama" in di_g2
    assert "BEKERJA DI GUDANG" not in di_g1
    assert "Operator polesan" in di_g2 and "Operator selepan" in di_g1


async def test_dinonaktifkan_memutus_sesi_yang_sedang_menggantikan(pg, pabrik):
    """Izin dicabut = akun dinonaktifkan (satu saklar untuk semua aplikasi);
    sesi yang terbuka di gudang seberang terputus pada permintaan berikutnya."""
    from hmu_identitas import masuk

    async with _klien(pabrik["token"], gudang="g2") as a:
        assert (await a.get(G2_SAJA)).status_code == 200
        async with pg() as db:
            await masuk.nonaktifkan(db, pabrik["op"])
        assert (await a.get(G2_SAJA)).status_code == 401
