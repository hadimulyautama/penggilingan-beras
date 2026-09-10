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


async def supplier_lain(nama: list[str]) -> list[int]:
    """Supplier BERBEDA untuk tiap batch.

    Kalau semua batch dari orang yang sama, laporan yang cuma membaca sumber
    pertama tetap tampak benar — kelalaiannya bersembunyi di balik satu nama.
    Tiga nama membuat setiap kelalaian terlihat: yang hilang dari daftar
    adalah orang yang gabahnya ikut tergiling dan ikut dibayar.
    """
    async with SessionLocal() as db:
        objek = [Supplier(nama_supplier=n) for n in nama]
        db.add_all(objek)
        await db.commit()
        return [o.id for o in objek]


async def bangun(op, sids) -> None:
    """Dua basah lewat pengeringan, satu kering langsung — semuanya ke Silo A.

    Tiap batch dari supplier yang BERBEDA, termasuk dua yang dikeringkan
    bersama: begitu keduanya melebur jadi satu PGR, satu-satunya yang menjaga
    nama mereka adalah daftar batch di dalamnya.
    """
    for (kode, kg), sid in zip((("TRX-BASAH-1", 8000), ("TRX-BASAH-2", 9000)), sids):
        await S.tiket(sid, kode, "GABAH_BASAH", netto=kg, nota=kg)
    for _ in range(2):
        t = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
        await op.post("/miniapp/actions/gabah-masuk",
                      json={"timbangan_transaksi_id": t[0]["value"], "tujuan": S.DRYER})

    await op.post("/miniapp/actions/mulai-pengeringan", json={})
    pgr = (await op.get("/miniapp/actions/drying-active")).json()[0]["value"]
    await op.post("/miniapp/actions/kadar-air", json={"kode_lot": pgr, "kadar_air": 14})
    await op.post("/miniapp/actions/selesai-pengeringan",
                  json={"kode_lot": pgr, "kadar_air": 14.0})
    await op.post("/miniapp/actions/selesai-pendinginan", json={"kode_lot": pgr})
    await op.post("/miniapp/actions/pindah-silo", json={"kode_lot": pgr, "silo": "A"})

    await S.tiket(sids[2], "TRX-KERING-1", "GABAH_KERING", netto=5000, nota=5000)
    t = (await op.get("/miniapp/actions/timbang-masuk-aktif")).json()
    await op.post("/miniapp/actions/gabah-masuk",
                  json={"timbangan_transaksi_id": t[0]["value"], "tujuan": S.SILO_A})

    r = await op.post("/miniapp/actions/mulai-giling", json={"silo": "A"})
    print(f"    giling: {r.json().get('pesan', r.text)[:80]}")


#: Tiga harga BERBEDA — satu per supplier. Harga tunggal membuat rata-rata
#: tertimbang tak bisa dibedakan dari "satu harga dikali total", dan cacat
#: semacam itu justru yang paling mahal: ia hanya muncul sebagai angka HPP
#: yang sedikit meleset, tanpa ada yang salah di layar mana pun.
#: Dikunci pada URUTAN batch (-01, -02, -03), bukan pada kode lengkapnya:
#: kode batch memuat tanggal, dan skrip yang mengunci tanggal akan pecah
#: sendiri esok harinya — sudah terjadi sekali.
HARGA_URUT = {"01": 5200.0, "02": 5000.0, "03": 6100.0}


def harga(kode: str) -> float:
    return HARGA_URUT[kode.rsplit("-", 1)[1]]


async def beri_harga(dir_) -> None:
    """Direksi memverifikasi harga tiap batch — masing-masing beda."""
    daftar = (await dir_.get("/miniapp/actions/gabah-unverified")).json()
    for opsi in daftar:
        kode = opsi["value"]
        await dir_.post("/miniapp/actions/verify-gabah", json={
            "kode_batch": kode, "metode": "per_kg", "nilai": harga(kode)})


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

        # ── Uang: rata-rata TERTIMBANG, bukan satu harga dikali total ──
        from app.services.costing import _sumber_info
        kg_c, _dried, kondisi, bahan, _pgr = await _sumber_info(db, proc)
        harap = sum(harga(k) * b for k, b, _t, _s in ketemu)
        polos = harga(ketemu[0][0]) * kg_c   # kalau harga pertama dipakai untuk semua
        print(f"\n{T}Biaya bahan{N}")
        for k, b, _t, sup in ketemu:
            print(f"   {k} · {b:,.0f} kg × Rp{harga(k):,.0f} = Rp{harga(k)*b:,.0f}  ({sup})")
        print(f"   {T}dihitung sistem : Rp{(bahan or 0):,.0f}{N}")
        print(f"   diharapkan      : Rp{harap:,.0f}")
        print(f"   (satu harga × total: Rp{polos:,.0f} — inilah yang SALAH)")
        tepat = bahan is not None and abs(bahan - harap) < 1
        print(("  " + H + "✅ biaya bahan = jumlah per batch, bukan satu harga × total" + N)
              if tepat else ("  " + M + "❌ biaya bahan meleset" + N))
        print(f"  {H}✅{N} kondisi terbaca: {kondisi}")

        DIHARAP = ["Bu Sri", "H. Karyo", "Pak Darto"]
        lengkap = sorted(nama) == DIHARAP
        print(("  " + H + f"✅ laporan menyebut KETIGA supplier: {nama}" + N) if lengkap
              else ("  " + M + f"❌ supplier hilang: ada {nama}, seharusnya {DIHARAP}" + N))

        # Dan tiap supplier harus terbaca di baris asal-usulnya, bukan cuma di judul.
        di_asal = all(any(n in b for b in teks.splitlines()) for n in DIHARAP)
        print(("  " + H + "✅ ketiganya tersebut di rincian asal, bukan cuma judul" + N)
              if di_asal else ("  " + M + "❌ ada supplier yang tak muncul di rincian" + N))
        return utuh and bertiket and lengkap and di_asal and tepat


async def main() -> None:
    S._pastikan_bukan_produksi()
    sid = await S.siapkan()
    tr = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=tr, base_url="http://uji",
                                 follow_redirects=False) as op:
        await S.masuk(op, "sknoperator")
        print(f"{T}Membangun: 2 batch basah (pengeringan) + 1 batch kering "
              f"(langsung) → Silo A → giling{N}")
        lain = await supplier_lain(["Bu Sri", "Pak Darto"])
        await bangun(op, [sid, lain[0], lain[1]])
        async with httpx.AsyncClient(transport=tr, base_url="http://uji",
                                     follow_redirects=False) as dr:
            await S.masuk(dr, "skndireksi")
            await beri_harga(dr)
        ok = await telusur()
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    asyncio.run(main())
