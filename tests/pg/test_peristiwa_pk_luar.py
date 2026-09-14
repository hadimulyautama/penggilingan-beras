"""Aksi KEDUA di jalur peristiwa: PK luar masuk dari tiket timbang (Gudang 2).

Kembaran "Gabah masuk" (tests/pg/test_peristiwa.py): satu transaksi, kunci
kiriman idempoten, proyeksi `proyeksi_pk_luar_masuk`, cermin
`pk_purchase_batches` untuk layar lama, pembatalan = peristiwa lawan.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import select, text

pytestmark = pytest.mark.asyncio

_SQL_TIKET = text("""
    INSERT INTO timbangan_transaksi
        (kode, tanggal, arah, jenis_kode, cara_timbang, supplier_id, pihak_nama,
         nomor_polisi, timbang1_kg, timbang1_waktu, netto_timbangan_kg,
         berat_acuan_kg, status_tiket, status_transaksi)
    VALUES (:kode, :tanggal, 'MASUK', 'BERAS_PK', 'DUA_KALI', :supplier_id, 'CV PK',
            'B 9 PK', 12000, :waktu, 8000, 0, 'TERBUKA', 'AKTIF')
    RETURNING id
""")


async def _tiket(pg, kode, supplier_id) -> int:
    from app.database import now_local

    async with pg() as db:
        tid = (await db.execute(_SQL_TIKET, {
            "kode": kode, "tanggal": now_local().date(), "supplier_id": supplier_id,
            "waktu": datetime.now(timezone.utc)})).scalar_one()
        await db.commit()
        return tid


async def _staf(pg, nama: str) -> int:
    from app.models import User
    from hmu_identitas import peran as P

    async with pg() as db:
        u = User(nama=nama, role=P.ADMIN, status="aktif")
        db.add(u)
        await db.commit()
        return u.id


async def _catat(pg, user_id: int, tid: int) -> str:
    from app.models import User
    from app.penggilingan.gudang2.service import Gudang2Error, create_pk_purchase_dari_timbang

    async with pg() as db:
        u = await db.get(User, user_id)
        try:
            r = await create_pk_purchase_dari_timbang(db, user=u, timbangan_transaksi_id=tid,
                                                      jenis_pk="ks")
        except Gudang2Error as e:
            return f"DITOLAK: {e}"
        return f"OK {r.batch.kode_batch}"


async def _undo(pg, user_id: int) -> str:
    from app.models import User
    from app.services import undo as svc

    async with pg() as db:
        u = await db.get(User, user_id)
        c = await svc.cakupan(db, scope="saya", nama=None, self_id=u.id)
        try:
            return await svc.undo_last(db, actor=u, cakupan=c)
        except svc.UndoError as e:
            return f"UndoError: {e}"


async def _hitung(pg, sql: str, **kw) -> int:
    async with pg() as db:
        return (await db.execute(text(sql), kw)).scalar_one()


async def test_pk_luar_menulis_peristiwa_proyeksi_dan_cermin(pg, pemasok):
    from app.models import Peristiwa, PkPurchaseBatch, ProyeksiPkLuarMasuk

    elfira = await _staf(pg, "Elfira")
    tid = await _tiket(pg, "PK1", pemasok.id)
    hasil = await _catat(pg, elfira, tid)
    assert hasil.startswith("OK PKB-"), hasil
    kode = hasil.split()[1]
    async with pg() as db:
        e = (await db.execute(select(Peristiwa).where(Peristiwa.jenis == "pk_luar_masuk"))).scalars().one()
        assert e.muatan["kode_batch"] == kode and e.muatan["jenis_pk"] == "ks"
        p = await db.get(ProyeksiPkLuarMasuk, e.id)
        assert p.status == "tercatat" and float(p.berat_kg) == 8000 and p.jenis_pk == "ks"
        b = (await db.execute(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch == kode))).scalars().one()
        assert b.peristiwa_id == e.id and b.status_batch == "diterima"


async def test_dua_staf_dua_tiket_bersamaan(pg, pemasok):
    a, b = await _staf(pg, "Elfira"), await _staf(pg, "Eka")
    kode = []
    for i in range(10):
        t1, t2 = await _tiket(pg, f"P{i}a", pemasok.id), await _tiket(pg, f"P{i}b", pemasok.id)
        h = await asyncio.gather(_catat(pg, a, t1), _catat(pg, b, t2))
        assert all(x.startswith("OK") for x in h), h
        kode += [x.split()[1] for x in h]
    assert len(set(kode)) == 20
    assert await _hitung(pg, "SELECT count(*) FROM proyeksi_pk_luar_masuk WHERE status='tercatat'") == 20


async def test_satu_tiket_pk_diperebutkan_hanya_satu_lolos(pg, pemasok):
    a, b = await _staf(pg, "Elfira"), await _staf(pg, "Eka")
    tid = await _tiket(pg, "SATU", pemasok.id)
    h = await asyncio.gather(*[_catat(pg, a if i % 2 else b, tid) for i in range(6)])
    assert sum(x.startswith("OK") for x in h) == 1, h
    assert await _hitung(pg, "SELECT count(*) FROM pk_purchase_batches WHERE timbangan_transaksi_id=:t", t=tid) == 1


async def test_batal_lalu_catat_lagi_tiket_yang_sama(pg, pemasok):
    from app.models import Peristiwa, ProyeksiPkLuarMasuk

    elfira = await _staf(pg, "Elfira")
    tid = await _tiket(pg, "ULANG", pemasok.id)
    k1 = (await _catat(pg, elfira, tid)).split()[1]
    assert "Dibatalkan" in await _undo(pg, elfira)
    assert "UndoError" in await _undo(pg, elfira)
    h = await _catat(pg, elfira, tid)
    assert h.startswith("OK") and h.split()[1] != k1
    async with pg() as db:
        jenis = [e.jenis for e in (await db.execute(select(Peristiwa).order_by(Peristiwa.id))).scalars()]
        assert jenis == ["pk_luar_masuk", "pk_luar_masuk_dibatalkan", "pk_luar_masuk"]
        proy = (await db.execute(select(ProyeksiPkLuarMasuk).order_by(ProyeksiPkLuarMasuk.peristiwa_id))).scalars().all()
        assert [p.status for p in proy] == ["dibatalkan", "tercatat"]
    assert await _hitung(pg, "SELECT count(*) FROM pk_purchase_batches WHERE dibatalkan_pada IS NULL") == 1


async def test_gagal_di_tengah_tak_menyimpan_apa_pun(pg, pemasok, monkeypatch):
    from app.penggilingan.gudang2 import service

    async def meledak(*a, **k):
        raise RuntimeError("uji: gagal sesudah peristiwa ditulis")

    monkeypatch.setattr(service, "create_notification", meledak)
    elfira = await _staf(pg, "Elfira")
    tid = await _tiket(pg, "GGL", pemasok.id)
    with pytest.raises(RuntimeError):
        await _catat(pg, elfira, tid)
    for t in ("peristiwa", "proyeksi_pk_luar_masuk", "pk_purchase_batches"):
        assert await _hitung(pg, f"SELECT count(*) FROM {t}") == 0, t
    monkeypatch.undo()
    assert (await _catat(pg, elfira, tid)).startswith("OK")


async def test_bangun_ulang_kedua_proyeksi_sama_dengan_keadaan_hidup(pg, pemasok):
    from app.services import peristiwa as P

    elfira = await _staf(pg, "Elfira")
    for i in range(3):
        await _catat(pg, elfira, await _tiket(pg, f"R{i}", pemasok.id))
    await _undo(pg, elfira)

    async def potret():
        async with pg() as db:
            return [tuple(r) for r in (await db.execute(text(
                "SELECT peristiwa_id, kode_batch, timbangan_transaksi_id, berat_kg, jenis_pk, "
                "status, dibatalkan_peristiwa_id FROM proyeksi_pk_luar_masuk ORDER BY peristiwa_id"))).all()]

    hidup = await potret()
    assert [r[5] for r in hidup] == ["tercatat", "tercatat", "dibatalkan"]
    async with pg() as db:
        laporan = await P.bangun_ulang(db)
    assert laporan["proyeksi_pk_luar_masuk"] == 3 and laporan["proyeksi_gabah_masuk"] == 0
    assert await potret() == hidup
