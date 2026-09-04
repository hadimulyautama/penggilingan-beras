"""Bisakah beras PK dirunut mundur sampai ke tiket timbang asalnya?

Pertanyaan pemilik, dijawab dengan menjalankannya — bukan dengan membaca
skema. Skenarionya persis yang ia sebut:

    2 batch gabah BASAH  → satu mesin pengering → satu PGR → Silo A
    1 batch gabah KERING → langsung ke Silo A (tak pernah masuk mesin)
    lalu Silo A digiling → satu LOT

Lalu LOT itu dirunut mundur, satu-satu, sampai ke supplier.

    docker run -d --name hmu-telusur -e POSTGRES_PASSWORD=uji -e POSTGRES_DB=uji \
        -p 55435:5432 postgres:16 && sleep 5
    DATABASE_URL=postgresql+asyncpg://postgres:uji@127.0.0.1:55435/uji \
        .venv/bin/python -m alembic upgrade head
    PYTHONPATH=. .venv/bin/python scripts/telusur_lot.py
"""
import asyncio

from sqlalchemy import select, text

import scripts.skenario_gabah as S
from app.database import SessionLocal
from app.penggilingan.gudang1.models.gudang1 import (
    DryingLot, DryingLotBatch, PurchaseBatch, SiloStorage)
from app.penggilingan.gudang1.models.milling import (
    MillingProcess, MillingProcessSource)
from app.models import Supplier

import httpx
from app.main import app


T = "\033[1m"; N = "\033[0m"; H = "\033[32m"; M = "\033[31m"


async def supplier_kedua() -> int:
    """Supplier BERBEDA untuk gabah keringnya.

    Kalau semua batch dari orang yang sama, laporan yang cuma membaca sumber
    pertama tetap tampak benar — kelalaiannya bersembunyi. Dua nama membuatnya
    tak bisa lagi.
    """
    async with SessionLocal() as db:
        s = Supplier(nama_supplier="Bu Sri")
        db.add(s)
        await db.commit()
        return s.id


async def bangun(op, sid, sid2) -> None:
    """Dua basah lewat pengeringan, satu kering langsung — semuanya ke Silo A."""
    for kode, kg in (("TRX-BASAH-1", 8000), ("TRX-BASAH-2", 9000)):
        await S.tiket(sid, kode, "GABAH_BASAH", netto=kg, nota=kg)
    for _ in range(2):
        t = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
        await op.post("/miniapp/actions/gabah-masuk",
                      json={"timbangan_transaksi_id": t[0]["value"], "tujuan": S.DRYER})

    await op.post("/miniapp/actions/mulai-pengeringan", json={})
    pgr = (await op.get("/miniapp/actions/drying-active")).json()[0]["value"]
    await op.post("/miniapp/actions/kadar-air", json={"kode_lot": pgr, "kadar_air": 14})
    await op.post("/miniapp/actions/selesai-pengeringan", json={"kode_lot": pgr})
    await op.post("/miniapp/actions/selesai-pendinginan", json={"kode_lot": pgr})
    await op.post("/miniapp/actions/pindah-silo", json={"kode_lot": pgr, "silo": "A"})

    await S.tiket(sid2, "TRX-KERING-1", "GABAH_KERING", netto=5000, nota=5000)
    t = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    await op.post("/miniapp/actions/gabah-masuk",
                  json={"timbangan_transaksi_id": t[0]["value"], "tujuan": S.SILO_A})

    r = await op.post("/miniapp/actions/mulai-giling", json={"silo": "A"})
    print(f"    giling: {r.json().get('pesan', r.text)[:80]}")


async def telusur() -> None:
    """Runut mundur dari LOT sampai supplier, dan hitung apakah utuh."""
    async with SessionLocal() as db:
        proc = (await db.execute(
            select(MillingProcess).order_by(MillingProcess.id.desc()).limit(1)
        )).scalars().first()
        print(f"\n{T}LOT {proc.kode_proses}{N}")

        sumber = (await db.execute(
            select(MillingProcessSource)
            .where(MillingProcessSource.milling_process_id == proc.id)
            .order_by(MillingProcessSource.id)
        )).scalars().all()

        ketemu: list[tuple[str, float, str, str]] = []
        for s in sumber:
            gudang = (await db.get(SiloStorage, s.silo_storage_id))
            if s.drying_lot_id:
                lot = await db.get(DryingLot, s.drying_lot_id)
                print(f"  ├─ dari pengeringan {T}{lot.kode_lot}{N} "
                      f"({float(s.berat_kg):,.0f} kg, silo-row #{gudang.id})")
                bids = (await db.execute(
                    select(DryingLotBatch.purchase_batch_id)
                    .where(DryingLotBatch.drying_lot_id == lot.id)
                )).scalars().all()
                anak = [await db.get(PurchaseBatch, b) for b in bids]
            else:
                print(f"  ├─ gabah kering langsung "
                      f"({float(s.berat_kg):,.0f} kg, silo-row #{gudang.id})")
                anak = [await db.get(PurchaseBatch, s.purchase_batch_id)]

            for b in anak:
                sup = await db.get(Supplier, b.supplier_id)
                tk = None
                if b.timbangan_transaksi_id:
                    tk = (await db.execute(text(
                        "SELECT kode FROM timbangan_transaksi WHERE id = :i"
                    ), {"i": b.timbangan_transaksi_id})).scalar()
                print(f"  │    └─ batch {T}{b.kode_batch}{N} · {b.kondisi_gabah} · "
                      f"{float(b.berat_total_kg or 0):,.0f} kg · "
                      f"tiket {tk or '—'} · {sup.nama_supplier}")
                ketemu.append((b.kode_batch, float(b.berat_total_kg or 0),
                               tk or "", sup.nama_supplier))

        # Laporan yang dilihat orang — bukan cuma tabelnya.
        from app.penggilingan.gudang1.services.milling import (
            _milling_supplier_names, laporan_milling)
        nama = await _milling_supplier_names(db, proc)
        teks = await laporan_milling(db, proc.kode_proses)
        print(f"\n{T}Laporan yang dilihat orang:{N}")
        for b in teks.splitlines():
            print("   " + b)

        semua = (await db.execute(select(PurchaseBatch))).scalars().all()
        kg_lot = sum(k[1] for k in ketemu)
        kg_semua = sum(float(b.berat_total_kg or 0) for b in semua)

        print(f"\n  {T}total dirunut{N}: {len(ketemu)} batch · {kg_lot:,.0f} kg")
        print(f"  {T}gabah yang pernah masuk{N}: {len(semua)} batch · {kg_semua:,.0f} kg")

        utuh = len(ketemu) == len(semua) == 3 and abs(kg_lot - kg_semua) < 0.5
        bertiket = all(k[2] for k in ketemu)
        print(("\n  " + H + "✅ UTUH" + N) if utuh else ("\n  " + M + "❌ ADA YANG HILANG" + N))
        print(("  " + H + "✅ tiap batch menyebut tiket timbangnya" + N) if bertiket
              else ("  " + M + "❌ ada batch tanpa tiket" + N))

        dua = sorted(nama) == ["Bu Sri", "H. Karyo"]
        print(("  " + H + f"✅ laporan menyebut KEDUA supplier: {nama}" + N) if dua
              else ("  " + M + f"❌ supplier hilang dari laporan: {nama}" + N))
        return utuh and bertiket and dua


async def main() -> None:
    S._pastikan_bukan_produksi()
    sid = await S.siapkan()
    tr = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=tr, base_url="http://uji",
                                 follow_redirects=False) as op:
        await S.masuk(op, "sknoperator")
        print(f"{T}Membangun: 2 batch basah (pengeringan) + 1 batch kering "
              f"(langsung) → Silo A → giling{N}")
        sid2 = await supplier_kedua()
        await bangun(op, sid, sid2)
        ok = await telusur()
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
