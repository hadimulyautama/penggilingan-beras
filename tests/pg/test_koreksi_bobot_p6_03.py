"""Korban lama P6-03: giling selesai yang bobot masuknya tak cocok lagi.

QA pra-deploy P6 (21 September 2026): migrasi 0054 hanya menandai giling
yang bahannya MASIH 'menunggu'. Yang terlewat: giling SELESAI dengan bobot
kurang, yang truknya SUDAH ditimbang sejak itu — bahannya kini 'timbangan',
penandanya tetap true, poller dan rekonsiliasi melewatinya (LOT-20260921-06:
7.190 tercatat, 9.190 seharusnya, tak tersentuh).

JANGAN dibetulkan otomatis: revisi tiket yang disengaja sesudah giling tampak
persis sama dari data. Maka rekonsiliasi MENYEBUTNYA (butir ⑪) dan admin
membetulkannya per proses lewat aksi yang tercatat dan bisa dibatalkan.

Korban dibangun di sini persis seperti yang ditinggalkan kode lama: giling
selesai, bahan kemudian punya netto, `bobot_masuk_final = true`. Dibuktikan
GAGAL sebelum perbaikan (kunci `giling_tak_cocok` belum ada; laporan berkata
"Bersih" di atas rendemen yang meleset).
"""
from __future__ import annotations

import pytest
from sqlalchemy import select, text

from tests.pg.test_bobot_belum_final import (  # noqa: F401 — fixture & pembantu
    _batch_gabah, _ke_silo, _lot_kering, _poller, _tiket, _timbang_kedua, pabrik)

pytestmark = pytest.mark.asyncio


async def _korban(pg, pemakai, pemasok, *, kode_tiket: str, nopol: str) -> tuple[str, int]:
    """Heru 7.190 + Joko MENUNGGU → giling selesai 5.700 → Joko ditimbang 2.000
    → lalu penandanya dipaksa true: keadaan yang ditinggalkan kode lama."""
    from app.models import MillingProcess, User
    from app.penggilingan.gudang1.services.milling import finish_milling, start_milling

    async with pg() as db:
        t_heru = await _tiket(db, f"{kode_tiket}-H", nopol=f"{nopol} H", t1=12000, netto=7190,
                              kosong=4810, jenis="GABAH_BASAH", supplier_id=pemasok.id)
        t_joko = await _tiket(db, f"{kode_tiket}-J", nopol=f"{nopol} J", t1=5200,
                              jenis="GABAH_BASAH", supplier_id=pemasok.id)
        await db.commit()
    kh = await _batch_gabah(pg, pemakai, t_heru, "basah")
    kj = await _batch_gabah(pg, pemakai, t_joko, "basah")
    lot = await _lot_kering(pg, pemakai, [kh, kj])
    await _ke_silo(pg, pemakai, None, "A", kode_lot=lot)
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        kode = (await start_milling(db, user=u, nama_silo="A")).proc.kode_proses
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await finish_milling(db, user=u, kode_proses=kode, berat_akhir=5700)
    async with pg() as db:
        await _timbang_kedua(db, t_joko, netto=2000, kosong=3200)
        # Kode lama tak punya penanda: prosesnya tampak final. Batch-nya diisi
        # poller langkah 1 saja (tanpa langkah 4) — persis urutan hari deploy.
        await db.execute(text("UPDATE milling_process SET bobot_masuk_final = true "
                              "WHERE kode_proses = :k"), {"k": kode})
        await db.commit()
    from app.penggilingan.gudang1.services.timbang_link import sinkron_bobot_menunggu
    async with pg() as db:
        await sinkron_bobot_menunggu(db)
    async with pg() as db:
        p = (await db.execute(
            select(MillingProcess).where(MillingProcess.kode_proses == kode))).scalars().one()
        assert p.status == "selesai" and float(p.berat_gabah_masuk_kg) == 7190
        assert p.bobot_masuk_final is True
        return kode, p.id


async def _baca(pg, kode):
    from app.models import MillingProcess

    async with pg() as db:
        return (await db.execute(
            select(MillingProcess).where(MillingProcess.kode_proses == kode))).scalars().one()


async def test_korban_lama_disebut_rekonsiliasi_dan_tak_disentuh_poller(pg, pemakai, pemasok, pabrik):
    from app.penggilingan.gudang1.services.rekonsiliasi import format_rekonsiliasi, rekonsiliasi

    kode, _ = await _korban(pg, pemakai, pemasok, kode_tiket="T-K1", nopol="AD 21 AA")
    await _poller(pg)                                   # poller baru: harus melewatinya
    p = await _baca(pg, kode)
    assert float(p.berat_gabah_masuk_kg) == 7190, "poller tak boleh membetulkan diam-diam"
    async with pg() as db:
        d = await rekonsiliasi(db)
        teks = format_rekonsiliasi(d)
    baris = d["giling_tak_cocok"]
    assert [x["kode_proses"] for x in baris] == [kode]
    assert float(baris[0]["tercatat_kg"]) == 7190 and float(baris[0]["seharusnya_kg"]) == 9190
    assert abs(float(baris[0]["kurang_persen"]) - 21.8) < 0.1
    assert "Bersih" not in teks and kode in teks


async def test_aksi_betulkan_menyamakan_dan_menghitung_ulang(pg, pemakai, pemasok, pabrik):
    from app.models import User
    from app.penggilingan.gudang1.services.koreksi_bobot import betulkan_bobot_masuk
    from app.penggilingan.gudang1.services.milling import hitung_rendemen
    from app.penggilingan.gudang1.services.rekonsiliasi import rekonsiliasi

    kode, _ = await _korban(pg, pemakai, pemasok, kode_tiket="T-K2", nopol="AD 22 BB")
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        r = await betulkan_bobot_masuk(db, user=u, kode_proses=kode)
    assert (r.tercatat_kg, r.sekarang_kg, r.final) == (7190, 9190, True)
    await _poller(pg)                                   # idempoten sesudahnya
    p = await _baca(pg, kode)
    assert float(p.berat_gabah_masuk_kg) == 9190 and p.bobot_masuk_final is True
    assert abs(hitung_rendemen(5700, p.berat_gabah_masuk_kg) - 62.0) < 0.1
    async with pg() as db:
        d = await rekonsiliasi(db)
    assert not d["giling_tak_cocok"], "butirnya kosong kembali"


async def test_revisi_tiket_sengaja_disebut_tetapi_tak_diubah_sampai_admin_memilih(
        pg, pemakai, pemasok, pabrik):
    """Giling selesai dengan bahan final, lalu bobot tiketnya direvisi. Ia
    muncul di daftar yang sama — dan TETAP tak berubah lewat poller."""
    from app.models import User
    from app.penggilingan.gudang1.services.koreksi_bobot import betulkan_bobot_masuk
    from app.penggilingan.gudang1.services.milling import finish_milling, start_milling
    from app.penggilingan.gudang1.services.rekonsiliasi import rekonsiliasi

    async with pg() as db:
        tid = await _tiket(db, "T-REV", nopol="AD 23 CC", t1=15000, netto=10000, kosong=5000,
                           supplier_id=pemasok.id)
        await db.commit()
    kode_b = await _batch_gabah(pg, pemakai, tid)
    await _ke_silo(pg, pemakai, kode_b, "B")
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        kode = (await start_milling(db, user=u, nama_silo="B")).proc.kode_proses
    async with pg() as db:
        u = await db.get(User, pemakai.id)
        await finish_milling(db, user=u, kode_proses=kode, berat_akhir=6000)
    # Revisi yang disengaja sesudah giling: bobot batch berubah, proses tidak.
    async with pg() as db:
        await db.execute(text("UPDATE purchase_batches SET berat_total_kg = 10500 "
                              "WHERE kode_batch = :k"), {"k": kode_b})
        await db.commit()
    await _poller(pg)
    p = await _baca(pg, kode)
    assert float(p.berat_gabah_masuk_kg) == 10000, "revisi sengaja tak boleh masuk sendiri"
    async with pg() as db:
        d = await rekonsiliasi(db)
    assert [x["kode_proses"] for x in d["giling_tak_cocok"]] == [kode]
    # Admin memutuskan: baru sesudah itu berubah.
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        await betulkan_bobot_masuk(db, user=u, kode_proses=kode)
    assert float((await _baca(pg, kode)).berat_gabah_masuk_kg) == 10500


async def test_betulkan_tercatat_dan_bisa_dibatalkan(pg, pemakai, pemasok, pabrik):
    from app.models import ActivityLog, User
    from app.penggilingan.gudang1.services.koreksi_bobot import (
        TAG_BETULKAN, betulkan_bobot_masuk)
    from app.services import undo

    kode, pid = await _korban(pg, pemakai, pemasok, kode_tiket="T-K4", nopol="AD 24 DD")
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        await betulkan_bobot_masuk(db, user=u, kode_proses=kode)
    assert float((await _baca(pg, kode)).berat_gabah_masuk_kg) == 9190
    async with pg() as db:
        log = (await db.execute(
            select(ActivityLog).where(ActivityLog.record_id == pid,
                                      ActivityLog.table_name == "milling_process",
                                      ActivityLog.aksi == TAG_BETULKAN)
        )).scalars().first()
        assert log is not None and log.changed_by == pabrik["admin"]
        assert "7190" in (log.old_value or "")
    async with pg() as db:
        u = await db.get(User, pabrik["admin"])
        c = await undo.cakupan(db, scope="saya", nama=None, self_id=u.id)
        pesan = await undo.undo_last(db, actor=u, cakupan=c)
        await db.commit()
    assert "dikembalikan" in pesan
    p = await _baca(pg, kode)
    assert float(p.berat_gabah_masuk_kg) == 7190 and p.bobot_masuk_final is True
    await _poller(pg)
    assert float((await _baca(pg, kode)).berat_gabah_masuk_kg) == 7190, \
        "sesudah dibatalkan, poller tak boleh menyamakannya lagi"
