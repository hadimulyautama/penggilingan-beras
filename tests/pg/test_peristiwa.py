"""Tulang punggung peristiwa — Tahap 3 rancang ulang (P-K-01, P-K-10, P-K-21).

Buku besar `peristiwa` hanya bertambah (trigger, bukan disiplin); proyeksi
dihitung dari peristiwa di transaksi yang sama dan bisa dibangun ulang dari
nol; satu pencatatan = satu transaksi (kunci kiriman, kunci baris, tambah
peristiwa, constraint, proyeksi) — gagal di mana pun berarti tak ada yang
tersimpan; pembatalan = peristiwa lawan yang menunjuk aslinya.

Aksi PERTAMA yang dipindahkan: "Gabah masuk" (dari tiket timbang). Skenario
r06 dan r13 dari QA/QA-2026-09-11-repro dijalankan ulang di sini, lewat
LAYANAN yang sama dengan yang dipanggil /miniapp/actions/gabah_masuk.
"""
from __future__ import annotations

import asyncio
from datetime import datetime, timezone

import pytest
from sqlalchemy import func, select, text

pytestmark = pytest.mark.asyncio

_SQL_TIKET = text("""
    INSERT INTO timbangan_transaksi
        (kode, tanggal, arah, jenis_kode, cara_timbang, supplier_id, pihak_nama,
         nomor_polisi, timbang1_kg, timbang1_waktu, netto_timbangan_kg,
         berat_acuan_kg, status_tiket, status_transaksi)
    VALUES (:kode, :tanggal, 'MASUK', 'GABAH_BASAH', 'DUA_KALI', :supplier_id, 'Pak Uji',
            'B 1 UJ', 12000, :waktu, 9800, 0, 'TERBUKA', 'AKTIF')
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


async def _operator(pg, nama: str) -> int:
    from app.models import User

    async with pg() as db:
        u = User(nama=nama, role="operator", status="aktif")
        db.add(u)
        await db.commit()
        return u.id


async def _catat(pg, user_id: int, tid: int, *, tumpuk: bool = False) -> str:
    """Seperti `act_gabah_masuk`: catat dari tiket (+ penempatan ke tumpukan)."""
    from app.models import User
    from app.penggilingan.gudang1.services.purchase import create_purchase_batch_dari_timbang
    from app.penggilingan.gudang1.services.tumpukan import masuk_tumpukan

    async with pg() as db:
        u = await db.get(User, user_id)
        try:
            r = await create_purchase_batch_dari_timbang(db, user=u, timbangan_transaksi_id=tid,
                                                         kondisi_gabah="basah")
        except ValueError as e:
            return f"DITOLAK: {e}"
        kode = r.batch.kode_batch
        if tumpuk:
            await masuk_tumpukan(db, user=u, kode_batch=kode)
        return f"OK {kode}"


async def _undo(pg, user_id: int) -> str:
    from app.models import User
    from app.services import undo as svc

    async with pg() as db:
        u = await db.get(User, user_id)
        ids, label = await svc.resolve_actor_ids(db, scope="saya", nama=None, self_id=u.id)
        try:
            return await svc.undo_last(db, actor=u, actor_ids=ids, scope_label=label)
        except svc.UndoError as e:
            return f"UndoError: {e}"


async def _hitung(pg, sql: str, **kw) -> int:
    async with pg() as db:
        return (await db.execute(text(sql), kw)).scalar_one()


# ── 1. Buku besar ───────────────────────────────────────────────────────

async def test_buku_besar_hanya_bertambah(pg, pemakai):
    """UPDATE dan DELETE ditolak basis data — bukan oleh kesopanan kode."""
    from sqlalchemy.exc import DBAPIError

    from app.services import peristiwa as P

    async with pg() as db:
        e = await P.catat(db, jenis="uji", pelaku_id=pemakai.id, kunci_kiriman="uji:1",
                          muatan={"a": 1})
        await db.commit()
    for perintah in ("UPDATE peristiwa SET jenis='diubah' WHERE id=:i",
                     "DELETE FROM peristiwa WHERE id=:i"):
        async with pg() as db:
            with pytest.raises(DBAPIError):
                await db.execute(text(perintah), {"i": e.id})
                await db.commit()
    assert await _hitung(pg, "SELECT count(*) FROM peristiwa WHERE jenis='uji'") == 1


async def test_kunci_kiriman_idempoten(pg, pemakai):
    """Kiriman yang sama dua kali = satu peristiwa; yang kedua menerima yang pertama."""
    from app.services import peristiwa as P

    async with pg() as db:
        a = await P.catat(db, jenis="uji", pelaku_id=pemakai.id, kunci_kiriman="uji:k", muatan={"n": 1})
        await db.commit()
    async with pg() as db:
        b = await P.catat(db, jenis="uji", pelaku_id=pemakai.id, kunci_kiriman="uji:k", muatan={"n": 2})
        await db.commit()
    assert a.id == b.id and b.muatan == {"n": 1} and b.baru is False
    assert await _hitung(pg, "SELECT count(*) FROM peristiwa WHERE kunci_kiriman='uji:k'") == 1


# ── 2. Gabah masuk di jalur peristiwa ──────────────────────────────────

async def test_gabah_masuk_menulis_peristiwa_proyeksi_dan_cermin(pg, pemakai, pemasok):
    from app.models import ActivityLog, Peristiwa, ProyeksiGabahMasuk, PurchaseBatch

    tid = await _tiket(pg, "GM1", pemasok.id)
    hasil = await _catat(pg, pemakai.id, tid)
    assert hasil.startswith("OK GB-")
    kode = hasil.split()[1]
    async with pg() as db:
        e = (await db.execute(select(Peristiwa).where(Peristiwa.jenis == "gabah_masuk"))).scalars().one()
        assert e.muatan["kode_batch"] == kode and e.muatan["timbangan_transaksi_id"] == tid
        assert e.pelaku_id == pemakai.id and e.membatalkan_id is None
        p = await db.get(ProyeksiGabahMasuk, e.id)
        assert p.kode_batch == kode and p.status == "tercatat" and float(p.berat_kg) == 9800
        b = (await db.execute(select(PurchaseBatch).where(PurchaseBatch.kode_batch == kode))).scalars().one()
        assert b.peristiwa_id == e.id and b.timbangan_transaksi_id == tid   # cermin untuk layar lama
        assert (await db.execute(select(func.count(ActivityLog.id)).where(
            ActivityLog.table_name == "purchase_batches", ActivityLog.record_id == b.id))).scalar_one() == 1


async def test_r06_dua_operator_dua_tiket_bersamaan(pg, pemasok):
    """Sepuluh putaran, dua operator, dua truk, pada saat yang sama: semuanya
    sukses dengan kode berbeda, tak ada yang dijawab 'tiket sudah ditautkan'."""
    budi, sari = await _operator(pg, "Budi"), await _operator(pg, "Sari")
    kode = []
    for i in range(10):
        t1, t2 = await _tiket(pg, f"T{i}a", pemasok.id), await _tiket(pg, f"T{i}b", pemasok.id)
        h = await asyncio.gather(_catat(pg, budi, t1), _catat(pg, sari, t2))
        assert all(x.startswith("OK") for x in h), h
        kode += [x.split()[1] for x in h]
    assert len(set(kode)) == 20
    assert await _hitung(pg, "SELECT count(*) FROM peristiwa WHERE jenis='gabah_masuk'") == 20
    assert await _hitung(pg, "SELECT count(*) FROM proyeksi_gabah_masuk WHERE status='tercatat'") == 20


async def test_satu_tiket_dua_operator_hanya_satu_yang_lolos(pg, pemasok):
    """Kunci baris tiket + constraint: satu truk tak pernah terhitung dua kali."""
    budi, sari = await _operator(pg, "Budi"), await _operator(pg, "Sari")
    tid = await _tiket(pg, "SATU", pemasok.id)
    h = await asyncio.gather(*[_catat(pg, budi if i % 2 else sari, tid) for i in range(6)])
    assert sum(x.startswith("OK") for x in h) == 1, h
    assert await _hitung(pg, "SELECT count(*) FROM purchase_batches WHERE timbangan_transaksi_id=:t", t=tid) == 1
    assert await _hitung(pg, "SELECT count(*) FROM peristiwa WHERE jenis='gabah_masuk'") == 1


async def test_r13_batal_lalu_catat_lagi_tak_macet(pg, pemasok):
    """Skenario r13: Budi truk-1, Sari truk-2, Budi batalkan penempatan lalu
    pencatatannya, truk-3, truk-4, truk-1 dicatat ulang — semuanya OK."""
    from app.models import Peristiwa, ProyeksiGabahMasuk

    budi, sari = await _operator(pg, "Budi"), await _operator(pg, "Sari")
    t = [await _tiket(pg, f"K{i}", pemasok.id) for i in range(4)]
    assert (await _catat(pg, budi, t[0], tumpuk=True)).startswith("OK")
    assert (await _catat(pg, sari, t[1], tumpuk=True)).startswith("OK")
    assert "Dibatalkan" in await _undo(pg, budi)          # penempatan
    assert "Dibatalkan" in await _undo(pg, budi)          # pencatatan
    for op, tid in ((sari, t[2]), (budi, t[3]), (budi, t[0])):
        h = await _catat(pg, op, tid, tumpuk=True)
        assert h.startswith("OK"), h
    async with pg() as db:
        semua = (await db.execute(select(Peristiwa).order_by(Peristiwa.id))).scalars().all()
        jenis = [e.jenis for e in semua]
        assert jenis.count("gabah_masuk") == 5 and jenis.count("gabah_masuk_dibatalkan") == 1
        lawan = next(e for e in semua if e.jenis == "gabah_masuk_dibatalkan")
        assert lawan.membatalkan_id == semua[0].id and lawan.muatan["alasan"]
        proy = (await db.execute(select(ProyeksiGabahMasuk).order_by(ProyeksiGabahMasuk.peristiwa_id))).scalars().all()
        assert [p.status for p in proy] == ["dibatalkan", "tercatat", "tercatat", "tercatat", "tercatat"]
        assert proy[0].dibatalkan_peristiwa_id == lawan.id
    # Kode harian tak bertabrakan dan nomornya tak diterbitkan ulang.
    assert await _hitung(pg, "SELECT count(DISTINCT kode_batch) FROM proyeksi_gabah_masuk") == 5
    assert await _hitung(pg, "SELECT count(*) FROM purchase_batches") == 4


async def test_pembatalan_tak_bisa_dua_kali_dan_tak_menghapus_jejak(pg, pemakai, pemasok):
    from app.models import ActivityLog

    tid = await _tiket(pg, "B1", pemasok.id)
    await _catat(pg, pemakai.id, tid)
    assert "Dibatalkan" in await _undo(pg, pemakai.id)
    lagi = await _undo(pg, pemakai.id)
    assert "UndoError" in lagi
    async with pg() as db:
        jejak = (await db.execute(select(ActivityLog).order_by(ActivityLog.id))).scalars().all()
    assert [j.action for j in jejak] == ["INSERT", "UNDO"] and jejak[0].dibatalkan_pada is not None
    assert await _hitung(pg, "SELECT count(*) FROM peristiwa") == 2


async def test_gagal_di_tengah_tak_menyimpan_apa_pun(pg, pemakai, pemasok, monkeypatch):
    """Satu transaksi: bila langkah terakhir gagal, peristiwa, proyeksi, dan
    cermin ikut hilang — tak ada nomor yang terbit setengah."""
    from app.penggilingan.gudang1.services import purchase

    async def meledak(*a, **k):
        raise RuntimeError("uji: gagal sesudah peristiwa ditulis")

    monkeypatch.setattr(purchase, "create_notification", meledak)
    tid = await _tiket(pg, "GGL", pemasok.id)
    with pytest.raises(RuntimeError):
        await _catat(pg, pemakai.id, tid)
    assert await _hitung(pg, "SELECT count(*) FROM peristiwa") == 0
    assert await _hitung(pg, "SELECT count(*) FROM proyeksi_gabah_masuk") == 0
    assert await _hitung(pg, "SELECT count(*) FROM purchase_batches") == 0
    # Dan tiketnya masih bebas dipakai.
    monkeypatch.undo()
    assert (await _catat(pg, pemakai.id, tid)).startswith("OK")


# ── 3. Proyeksi bisa dibangun ulang dari nol ───────────────────────────

async def test_bangun_ulang_sama_dengan_keadaan_hidup(pg, pemasok):
    from app.services import peristiwa as P

    budi = await _operator(pg, "Budi")
    for i in range(3):
        await _catat(pg, budi, await _tiket(pg, f"R{i}", pemasok.id))
    await _undo(pg, budi)

    async def potret():
        async with pg() as db:
            return [tuple(r) for r in (await db.execute(text(
                "SELECT peristiwa_id, kode_batch, timbangan_transaksi_id, supplier_id, berat_kg, "
                "kondisi, tanggal, status, dibatalkan_peristiwa_id, pelaku_id "
                "FROM proyeksi_gabah_masuk ORDER BY peristiwa_id"))).all()]

    hidup = await potret()
    assert len(hidup) == 3 and [r[7] for r in hidup] == ["tercatat", "tercatat", "dibatalkan"]
    async with pg() as db:
        laporan = await P.bangun_ulang(db)
    assert laporan["peristiwa"] == 4 and laporan["proyeksi_gabah_masuk"] == 3
    assert await potret() == hidup
