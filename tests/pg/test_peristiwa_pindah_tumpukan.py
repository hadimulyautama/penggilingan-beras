"""Aksi KELIMA di jalur peristiwa: pindah PK dari tumpukan ke silo (Gudang 2).

Pekerjaan operator Gudang 2 (keputusan pemilik 12 Sep 2026), boleh sebagian.
Sampai kini ia satu-satunya aksi stok Gudang 2 yang TAK punya pembatalan;
di jalur peristiwa ia dapat pembatalan lewat peristiwa lawan, dengan penjaga
hilir yang sama seperti pemasukan PK (P-K-10): silo yang sudah dipoles
sesudahnya, atau sedang dipoles, menolak pembatalan. Tumpukan sumbernya
dikunci saat dibaca supaya dua operator tak memindahkan sisa yang sama.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest
from sqlalchemy import select, text

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def g2(pg, pemasok):
    """Gudang 2 + Silo A/B, satu operator G2 dan satu admin, satu PK luar
    15.000 kg yang sudah DITUMPUK (lewat jalur peristiwa aksi ketiga)."""
    from app.database import now_local
    from app.models import Silo, User, Warehouse
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import masukkan_pk_luar
    from hmu_identitas import peran as P

    async with pg() as db:
        w = Warehouse(nama_gudang="Gudang 2 - Penyosohan")
        db.add(w)
        await db.flush()
        db.add_all([Silo(nama_silo="Silo A", warehouse_id=w.id), Silo(nama_silo="Silo B", warehouse_id=w.id)])
        op = User(nama="Dany", role=P.OPERATOR, status="aktif", default_warehouse_id=w.id)
        adm = User(nama="Elfira", role=P.ADMIN, status="aktif", default_warehouse_id=w.id)
        db.add_all([op, adm])
        await db.flush()
        db.add(PkPurchaseBatch(kode_batch="PKB-UJI-01", supplier_id=pemasok.id, berat_total_kg=15_000,
                               tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                               input_by=adm.id, status_batch="diterima", flag_unverified=True,
                               sumber_berat="manual"))
        await db.commit()
        await db.refresh(adm)
        r = await masukkan_pk_luar(db, user=adm, kode="PKB-UJI-01", tujuan="ditumpuk")
        return {"op": op.id, "adm": adm.id, "intake": r.intake.id}


async def _pindah(pg, user_id, intake_id, silo="A", berat=None) -> str:
    from app.models import User
    from app.penggilingan.gudang2.service import Gudang2Error, pindah_tumpukan_ke_silo

    async with pg() as db:
        u = await db.get(User, user_id)
        try:
            r = await pindah_tumpukan_ke_silo(db, user=u, intake_id=intake_id, nama_silo=silo, berat=berat)
        except Gudang2Error as e:
            return f"DITOLAK: {e}"
        return f"OK {r.kode_pindah} {r.berat_kg:.0f} sisa={r.sisa_tumpukan_intake:.0f}"


async def _undo(pg, user_id) -> str:
    from app.models import User
    from app.services import undo as svc

    async with pg() as db:
        u = await db.get(User, user_id)
        ids, label = await svc.resolve_actor_ids(db, scope="saya", nama=None, self_id=u.id)
        try:
            return await svc.undo_last(db, actor=u, actor_ids=ids, scope_label=label)
        except svc.UndoError as e:
            return f"UndoError: {e}"


async def _hitung(pg, sql, **kw):
    async with pg() as db:
        return (await db.execute(text(sql), kw)).scalar_one()


async def _stok(pg, huruf=None) -> float:
    from app.penggilingan.gudang2.service import get_g2_silo, hitung_stok_silo, hitung_stok_tumpukan

    async with pg() as db:
        if huruf is None:
            return await hitung_stok_tumpukan(db)
        return await hitung_stok_silo(db, (await get_g2_silo(db, huruf)).id)


async def test_pindah_menulis_peristiwa_proyeksi_dan_cermin(pg, g2):
    from app.models import Peristiwa, PkTumpukanToSilo, ProyeksiPindahTumpukanSilo

    h = await _pindah(pg, g2["op"], g2["intake"], "A", 3_000)
    assert h.startswith("OK PTS-") and h.endswith("sisa=12000"), h
    async with pg() as db:
        e = (await db.execute(select(Peristiwa).where(Peristiwa.jenis == "pk_tumpukan_ke_silo"))).scalars().one()
        assert e.muatan["berat_kg"] == 3000 and e.muatan["intake_id"] == g2["intake"]
        p = await db.get(ProyeksiPindahTumpukanSilo, e.id)
        assert p.status == "tercatat" and p.silo_id is not None and p.ke_proses is None
        m = (await db.execute(select(PkTumpukanToSilo))).scalars().one()
        assert m.peristiwa_id == e.id and float(m.berat_kg) == 3000
    assert await _stok(pg) == 12_000 and await _stok(pg, "A") == 3_000


async def test_dua_operator_memindahkan_sisa_yang_sama_bersamaan(pg, g2):
    """Keduanya membaca 'sisa 15.000' — tanpa kunci baris, 20.000 kg pindah
    dari tumpukan berisi 15.000. Dengan kunci: yang kedua ditolak/dipotong."""
    h = await asyncio.gather(_pindah(pg, g2["op"], g2["intake"], "A", 10_000),
                             _pindah(pg, g2["adm"], g2["intake"], "B", 10_000))
    dipindah = await _hitung(pg, "SELECT coalesce(sum(berat_kg),0) FROM pk_tumpukan_to_silo")
    assert float(dipindah) <= 15_000, (h, dipindah)
    assert await _stok(pg) >= 0
    assert sum(x.startswith("OK") for x in h) == 1, h


async def test_batal_sebelum_dipakai_mengembalikan_tumpukan(pg, g2):
    await _pindah(pg, g2["op"], g2["intake"], "A", 3_000)
    assert "Dibatalkan" in await _undo(pg, g2["op"])
    assert await _stok(pg) == 15_000 and await _stok(pg, "A") == 0
    assert await _hitung(pg, "SELECT count(*) FROM pk_tumpukan_to_silo") == 0
    assert await _hitung(pg, "SELECT count(*) FROM proyeksi_pindah_tumpukan_silo WHERE status='dibatalkan'") == 1
    assert "UndoError" in await _undo(pg, g2["op"])
    assert (await _pindah(pg, g2["op"], g2["intake"], "B", 15_000)).startswith("OK")


async def test_pk10_batal_ditolak_bila_silonya_dipoles_sesudahnya(pg, g2):
    from app.models import ActivityLog, User
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.services import undo as svc

    await _pindah(pg, g2["op"], g2["intake"], "A", 5_000)
    async with pg() as db:
        u = await db.get(User, g2["op"])
        await mulai_penyosohan(db, user=u, nama_silos=["A"])
    async with pg() as db:
        log = (await db.execute(select(ActivityLog).where(ActivityLog.table_name == "pk_tumpukan_to_silo"))).scalars().one()
        with pytest.raises(svc.UndoError) as e:
            await svc._undo_one(db, log)
    assert "dipoles" in str(e.value)
    assert await _stok(pg, "A") == 5_000 and await _stok(pg) == 10_000


async def test_pk10_batal_ditolak_saat_dituang_ke_proses_berjalan(pg, g2):
    from app.models import User
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    from app.penggilingan.gudang2.service import masukkan_pk_luar
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from app.database import now_local

    async with pg() as db:
        u = await db.get(User, g2["adm"])
        s = (await db.execute(text("SELECT supplier_id FROM pk_purchase_batches LIMIT 1"))).scalar_one()
        db.add(PkPurchaseBatch(kode_batch="PKB-UJI-02", supplier_id=s, berat_total_kg=2_000,
                               tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                               input_by=u.id, status_batch="diterima", flag_unverified=True,
                               sumber_berat="manual"))
        await db.commit()
        await masukkan_pk_luar(db, user=u, kode="PKB-UJI-02", tujuan="silo_a")
        await mulai_penyosohan(db, user=u, nama_silos=["A"])
    h = await _pindah(pg, g2["op"], g2["intake"], "A", 1_000)
    assert h.startswith("OK"), h
    assert await _hitung(pg, "SELECT berat_masuk_kg FROM polishing_silo_usage") == 1_000
    u = await _undo(pg, g2["op"])
    assert "UndoError" in u and ("dipoles" in u or "penyosohan" in u)
    assert await _hitung(pg, "SELECT count(*) FROM pk_tumpukan_to_silo") == 1


async def test_gagal_di_tengah_tak_menyimpan_apa_pun(pg, g2, monkeypatch):
    from app.penggilingan.gudang2 import service

    async def meledak(*a, **k):
        raise RuntimeError("uji")

    monkeypatch.setattr(service, "log_activity", meledak)
    with pytest.raises(RuntimeError):
        await _pindah(pg, g2["op"], g2["intake"], "A", 3_000)
    for t in ("proyeksi_pindah_tumpukan_silo", "pk_tumpukan_to_silo"):
        assert await _hitung(pg, f"SELECT count(*) FROM {t}") == 0, t
    assert await _hitung(pg, "SELECT count(*) FROM peristiwa WHERE jenis='pk_tumpukan_ke_silo'") == 0
    assert await _stok(pg) == 15_000
    monkeypatch.undo()
    assert (await _pindah(pg, g2["op"], g2["intake"], "A", 3_000)).startswith("OK")


async def test_bangun_ulang_sama_dengan_keadaan_hidup(pg, g2):
    from app.services import peristiwa as P

    await _pindah(pg, g2["op"], g2["intake"], "A", 3_000)
    await _pindah(pg, g2["op"], g2["intake"], "B", 2_000)
    await _undo(pg, g2["op"])

    async def potret():
        async with pg() as db:
            return [tuple(r) for r in (await db.execute(text(
                "SELECT peristiwa_id, kode_pindah, intake_id, silo_id, berat_kg, status, "
                "dibatalkan_peristiwa_id FROM proyeksi_pindah_tumpukan_silo ORDER BY peristiwa_id"))).all()]

    hidup = await potret()
    assert [r[5] for r in hidup] == ["tercatat", "dibatalkan"]
    async with pg() as db:
        laporan = await P.bangun_ulang(db)
    assert laporan["proyeksi_pindah_tumpukan_silo"] == 2
    assert await potret() == hidup
