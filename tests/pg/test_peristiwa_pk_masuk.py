"""Aksi KETIGA di jalur peristiwa: PK MASUK Gudang 2 (ke silo / tumpukan).

Inilah aksi yang membawa temuan P-K-10: pembatalan pemasukan PK yang PK-nya
sudah dipoles membuat silo −7.000 kg, dan yang tumpukannya sudah dipindah
sebagian menghilangkan berat dari dua tempat. Di jalur peristiwa, peristiwa
lawan DITOLAK bila sudah ada pemakaian hilir — bukan diperbaiki sesudahnya.

Titik tulisnya satu (`_add_intake`), jadi pemasukan dari PK luar MAUPUN dari
transfer Gudang 1 sama-sama tercatat sebagai peristiwa `pk_masuk_g2`.
"""
from __future__ import annotations

import asyncio
from datetime import date

import pytest
from sqlalchemy import select, text

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def g2(pg):
    """Gudang 2 + Silo A/B, satu admin, satu pemasok, tiga batch PK luar
    'diterima' yang belum ditempatkan."""
    from app.database import now_local
    from app.models import Silo, Supplier, User, Warehouse
    from app.penggilingan.gudang2.models import PkPurchaseBatch
    from hmu_identitas import peran as P

    async with pg() as db:
        w = Warehouse(nama_gudang="Gudang 2 - Penyosohan", kode_fungsi="g2")
        db.add(w)
        await db.flush()
        db.add_all([Silo(nama_silo="Silo A", warehouse_id=w.id), Silo(nama_silo="Silo B", warehouse_id=w.id)])
        u = User(nama="Elfira", role=P.ADMIN, status="aktif", default_warehouse_id=w.id)
        s = Supplier(nama_supplier="CV PK")
        db.add_all([u, s])
        await db.flush()
        for i, kg in enumerate((8_000, 6_000, 5_000), start=1):
            db.add(PkPurchaseBatch(kode_batch=f"PKB-UJI-0{i}", supplier_id=s.id, berat_total_kg=kg,
                                   tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                                   input_by=u.id, status_batch="diterima", flag_unverified=True,
                                   sumber_berat="manual"))
        await db.commit()
        return {"user_id": u.id}


async def _transfer_g1_ke_silo(pg, user_id, suffix, kg, silo) -> str:
    """PK dari lot giling Gudang 1 sendiri → silo G2, lewat `create_internal_
    transfer` (jalur peristiwa aksi keempat — SAMA `_add_intake` dengan PK
    luar, lihat docstring berkas ini).

    ⚠ Dipakai menggantikan beli-luar-langsung-ke-silo di berkas ini sejak
    Aturan 1 (4 Oktober 2026): PK luar baru tak lagi boleh langsung ke silo,
    tetapi transfer G1→G2 TIDAK ikut berubah — jadi inilah jalur yang
    tersisa untuk menguji cabang SILO `_add_intake` secara langsung, bukan
    jalan pintas yang melompati jalur nyata."""
    from app.database import now_local
    from app.models import (MillingProcess, MillingProgressLog, PurchaseBatch, Silo,
                            Supplier, User, Warehouse)
    from app.services.transfer import create_internal_transfer
    from sqlalchemy import select as _select

    async with pg() as db:
        g1 = (await db.execute(_select(Warehouse).where(
            Warehouse.nama_gudang.like("Gudang 1%")))).scalars().first()
        if g1 is None:
            g1 = Warehouse(nama_gudang="Gudang 1 - Selepan", kode_fungsi="g1")
            db.add(g1)
            await db.flush()
        u = await db.get(User, user_id)
        sup = (await db.execute(_select(Supplier.id))).scalars().first()
        silo_g1 = Silo(nama_silo=f"Silo Selepan {suffix}", warehouse_id=g1.id)
        db.add(silo_g1)
        await db.flush()
        b = PurchaseBatch(kode_batch=f"GB-{suffix}", supplier_id=sup,
                          berat_total_kg=kg, kondisi_gabah="kering",
                          tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
                          input_by=u.id, flag_unverified=False, sumber_berat="timbangan")
        db.add(b)
        await db.flush()
        p = MillingProcess(kode_proses=f"LOT-{suffix}", status="selesai", silo_id=silo_g1.id,
                           berat_gabah_masuk_kg=kg, waktu_mulai=now_local(),
                           waktu_selesai=now_local(), created_by=u.id,
                           purchase_batch_id=b.id)
        db.add(p)
        await db.flush()
        db.add(MillingProgressLog(milling_process_id=p.id, berat_kumulatif_kg=kg,
                                  waktu_update=now_local(), input_by=u.id))
        await db.commit()
    async with pg() as db:
        u = await db.get(User, user_id)
        try:
            r = await create_internal_transfer(db, user=u, kode_proses=f"LOT-{suffix}",
                                               lokasi_tujuan=silo, berat=kg)
        except Exception as e:                           # noqa: BLE001
            return f"DITOLAK: {e}"
        return f"OK {r.lokasi_label}"


async def _masukkan(pg, user_id, kode, tujuan) -> str:
    from app.models import User
    from app.penggilingan.gudang2.service import Gudang2Error, masukkan_pk_luar

    async with pg() as db:
        u = await db.get(User, user_id)
        try:
            r = await masukkan_pk_luar(db, user=u, kode=kode, tujuan=tujuan)
        except Gudang2Error as e:
            return f"DITOLAK: {e}"
        return f"OK intake#{r.intake.id}"


async def _undo(pg, user_id) -> str:
    from app.models import User
    from app.services import undo as svc

    async with pg() as db:
        u = await db.get(User, user_id)
        c = await svc.cakupan(db, scope="saya", nama=None, self_id=u.id)
        try:
            return await svc.undo_last(db, actor=u, cakupan=c)
        except svc.UndoError as e:
            return f"UndoError: {e}"


async def _hitung(pg, sql, **kw):
    async with pg() as db:
        return (await db.execute(text(sql), kw)).scalar_one()


async def _stok_silo(pg, huruf) -> float:
    from app.penggilingan.gudang2.service import get_g2_silo, hitung_stok_silo

    async with pg() as db:
        silo = await get_g2_silo(db, huruf)
        return await hitung_stok_silo(db, silo.id)


async def test_pk_masuk_menulis_peristiwa_proyeksi_dan_cermin(pg, g2):
    """⚠ Cabang SILO diuji lewat TRANSFER G1→G2, bukan PK luar langsung
    (Aturan 1, 4 Oktober 2026 melarang itu) — `_add_intake` tetap satu titik
    tulis untuk keduanya, jadi muatan `pk_masuk_g2` yang diperiksa di sini
    sama persis bentuknya, cuma `sumber_tipe`-nya berbeda."""
    from app.models import Peristiwa, PkGudang2Intake, ProyeksiPkMasukG2

    assert (await _transfer_g1_ke_silo(pg, g2["user_id"], "PPM-01", 8_000, "A")).startswith("OK")
    assert (await _masukkan(pg, g2["user_id"], "PKB-UJI-02", "ditumpuk")).startswith("OK")
    async with pg() as db:
        ev = (await db.execute(select(Peristiwa).where(Peristiwa.jenis == "pk_masuk_g2")
                               .order_by(Peristiwa.id))).scalars().all()
        # Muatannya menyimpan JENIS tempatnya, dan silo MANA sebagai rujukan.
        # Dulu di sini "silo_a" — nama silo yang ikut jadi kosakata datanya
        # sendiri, dan kosakata seperti itu tak bisa tumbuh: silo ketiga tak
        # punya kata (migrasi 0057). Yang dijaga sekarang lebih kuat, bukan
        # lebih longgar: identitas silonya harus ikut TERBAWA, bukan
        # tersembunyi di dalam katanya.
        assert [e.muatan["tujuan"] for e in ev] == ["silo", "ditumpuk"]
        from app.penggilingan.gudang2.service import get_g2_silo

        silo_a = await get_g2_silo(db, "A")
        assert ev[0].muatan["silo_id"] == silo_a.id
        assert ev[1].muatan["silo_id"] is None, "tumpukan tak punya silo"
        assert ev[0].muatan["sumber_tipe"] == "transfer_internal" and ev[0].muatan["berat_kg"] == 8000
        proy = (await db.execute(select(ProyeksiPkMasukG2).order_by(ProyeksiPkMasukG2.peristiwa_id))).scalars().all()
        assert [p.status for p in proy] == ["tercatat", "tercatat"] and proy[0].silo_id is not None
        it = (await db.execute(select(PkGudang2Intake).order_by(PkGudang2Intake.id))).scalars().all()
        assert [i.peristiwa_id for i in it] == [ev[0].id, ev[1].id]
    assert await _stok_silo(pg, "A") == 8_000


async def test_r01_satu_pk_diketuk_dua_kali_bersamaan(pg, g2):
    """⚠ Tujuannya "ditumpuk" (Aturan 1, 4 Oktober 2026): dengan "silo_a" pagar
    baru menolak KEDUA kiriman sebelum sempat berlomba, dan balapannya
    (temuan P-K-04, kunci batch) tak pernah tersentuh — penjaga yang lulus
    tanpa menguji apa pun."""
    from app.penggilingan.gudang2.service import hitung_stok_tumpukan

    for _ in range(5):
        h = await asyncio.gather(*[_masukkan(pg, g2["user_id"], "PKB-UJI-01", "ditumpuk") for _ in range(2)])
        assert sum(x.startswith("OK") for x in h) <= 1, h
    assert await _hitung(pg, "SELECT count(*) FROM pk_gudang2_intakes") == 1
    assert await _hitung(pg, "SELECT count(*) FROM peristiwa WHERE jenis='pk_masuk_g2'") == 1
    async with pg() as db:
        assert await hitung_stok_tumpukan(db) == 8_000


async def test_batal_sebelum_dipakai_adalah_peristiwa_lawan(pg, g2):
    from app.models import PkPurchaseBatch
    from app.penggilingan.gudang2.service import hitung_stok_tumpukan

    await _masukkan(pg, g2["user_id"], "PKB-UJI-01", "ditumpuk")
    async with pg() as db:
        assert await hitung_stok_tumpukan(db) == 8_000
    assert "Dibatalkan" in await _undo(pg, g2["user_id"])
    async with pg() as db:
        assert await hitung_stok_tumpukan(db) == 0
    assert await _hitung(pg, "SELECT count(*) FROM peristiwa") == 2
    assert await _hitung(pg, "SELECT count(*) FROM proyeksi_pk_masuk_g2 WHERE status='dibatalkan'") == 1
    assert await _hitung(pg, "SELECT count(*) FROM pk_gudang2_intakes WHERE dibatalkan_pada IS NOT NULL") == 1
    async with pg() as db:
        b = (await db.execute(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch == "PKB-UJI-01"))).scalars().one()
        assert b.status_batch == "diterima"
    # Bisa dimasukkan lagi — pembatalan tak meninggalkan kunci apa pun.
    assert (await _masukkan(pg, g2["user_id"], "PKB-UJI-01", "ditumpuk")).startswith("OK")


async def test_pk10_batal_ditolak_bila_silonya_sudah_dipoles(pg, g2):
    """Skenario r07-E: masuk Silo A, dipoles sampai selesai, lalu 'Batalkan'.
    Dulu silo jadi −7.000 kg. Sekarang ditolak, stok tetap.

    ⚠ Masuknya lewat TRANSFER G1→G2 (Aturan 1, 4 Oktober 2026 melarang PK
    luar baru langsung ke silo) — tapi P-K-10 menjaga HILIRNYA (intake yang
    sudah dipoles), bukan asalnya, jadi penjaga yang sama tetap teruji."""
    from app.models import User
    from app.penggilingan.gudang2.polishing import catat_output, mulai_penyosohan, selesai_penyosohan

    uid = g2["user_id"]
    await _transfer_g1_ke_silo(pg, uid, "PK10A", 8_000, "A")
    async with pg() as db:
        u = await db.get(User, uid)
        r = await mulai_penyosohan(db, user=u, nama_silos=["A"])
        await catat_output(db, user=u, kode=r.proc.kode_proses, jenis="premium", berat_kumulatif=5_000)
        await selesai_penyosohan(db, user=u, kode=r.proc.kode_proses, nama_silo="A", sisa_kg=1_000)
    assert await _stok_silo(pg, "A") == 1_000
    # Jejak terakhir milik penyosohan; yang dibidik pemasukan PK-nya.
    from app.models import ActivityLog
    from app.services import undo as svc

    async with pg() as db:
        u = await db.get(User, uid)
        log = (await db.execute(select(ActivityLog).where(ActivityLog.table_name == "pk_gudang2_intakes"))).scalars().one()
        with pytest.raises(svc.UndoError) as e:
            await svc._undo_one(db, log)
    assert "dipoles" in str(e.value) or "penyosohan" in str(e.value)
    assert await _stok_silo(pg, "A") == 1_000
    assert await _hitung(pg, "SELECT count(*) FROM peristiwa WHERE jenis='pk_masuk_g2_dibatalkan'") == 0


async def test_pk10_batal_ditolak_saat_penyosohan_masih_berjalan(pg, g2):
    """PK dituang ke silo yang sedang dipoles ikut jadi bahan proses (berat_masuk);
    membatalkannya di tengah proses akan membuat rumus terpakai bohong.

    ⚠ Keduanya masuk lewat TRANSFER G1→G2 (Aturan 1, 4 Oktober 2026 melarang
    PK luar baru langsung ke silo) — P-K-10 menjaga HILIRNYA, bukan asalnya."""
    from app.models import User
    from app.penggilingan.gudang2.polishing import mulai_penyosohan

    uid = g2["user_id"]
    await _transfer_g1_ke_silo(pg, uid, "PK10B1", 8_000, "A")
    async with pg() as db:
        u = await db.get(User, uid)
        await mulai_penyosohan(db, user=u, nama_silos=["A"])
    assert (await _transfer_g1_ke_silo(pg, uid, "PK10B2", 3_000, "A")).startswith("OK")
    h = await _undo(pg, uid)
    assert "UndoError" in h and ("penyosohan" in h or "dipoles" in h)
    assert await _hitung(pg, "SELECT count(*) FROM pk_gudang2_intakes") == 2


async def test_pk10_batal_tumpukan_ditolak_bila_sudah_dipindah_sebagian(pg, g2):
    from app.models import PkGudang2Intake, User
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo

    uid = g2["user_id"]
    await _masukkan(pg, uid, "PKB-UJI-01", "ditumpuk")
    async with pg() as db:
        u = await db.get(User, uid)
        it = (await db.execute(select(PkGudang2Intake))).scalars().one()
        await pindah_tumpukan_ke_silo(db, user=u, intake_id=it.id, nama_silo="A", berat=3_000)
    from app.models import ActivityLog
    from app.services import undo as svc

    async with pg() as db:
        log = (await db.execute(select(ActivityLog).where(ActivityLog.table_name == "pk_gudang2_intakes"))).scalars().one()
        with pytest.raises(svc.UndoError) as e:
            await svc._undo_one(db, log)
    assert "dipindah" in str(e.value)
    assert await _hitung(pg, "SELECT count(*) FROM pk_gudang2_intakes") == 1


async def test_gagal_di_tengah_tak_menyimpan_apa_pun(pg, g2, monkeypatch):
    from app.penggilingan.gudang2 import service

    async def meledak(*a, **k):
        raise RuntimeError("uji")

    monkeypatch.setattr(service, "log_activity", meledak)
    with pytest.raises(RuntimeError):
        await _masukkan(pg, g2["user_id"], "PKB-UJI-01", "ditumpuk")
    for t in ("peristiwa", "proyeksi_pk_masuk_g2", "pk_gudang2_intakes"):
        assert await _hitung(pg, f"SELECT count(*) FROM {t}") == 0, t
    monkeypatch.undo()
    assert (await _masukkan(pg, g2["user_id"], "PKB-UJI-01", "ditumpuk")).startswith("OK")


async def test_bangun_ulang_sama_dengan_keadaan_hidup(pg, g2):
    from app.services import peristiwa as P

    uid = g2["user_id"]
    await _masukkan(pg, uid, "PKB-UJI-01", "ditumpuk")
    await _masukkan(pg, uid, "PKB-UJI-02", "ditumpuk")
    await _undo(pg, uid)

    async def potret():
        async with pg() as db:
            return [tuple(r) for r in (await db.execute(text(
                "SELECT peristiwa_id, sumber_tipe, pk_purchase_batch_id, tujuan, silo_id, berat_kg, "
                "status, dibatalkan_peristiwa_id FROM proyeksi_pk_masuk_g2 ORDER BY peristiwa_id"))).all()]

    hidup = await potret()
    assert [r[6] for r in hidup] == ["tercatat", "dibatalkan"]
    async with pg() as db:
        laporan = await P.bangun_ulang(db)
    assert laporan["proyeksi_pk_masuk_g2"] == 2
    assert await potret() == hidup
