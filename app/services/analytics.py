"""Lapisan analitik strategis — supplier scorecard & tren HPP.

Catatan atribusi: satu proses milling memakai satu LOT (bisa banyak batch,
mungkin beda supplier). Rendemen & biaya dialokasikan ke supplier secara
PROPORSIONAL berdasarkan bobot (kg) tiap batch dalam lot.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    DryingLotBatch,
    MillingProcess,
    MillingProcessVerification,
    MillingProgressLog,
    MillingQcLog,
    PurchaseBatch,
    PurchaseBatchVerification,
    Supplier,
)
from app.services.costing import production_cost

_BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt",
          "Nov", "Des"]


def _rp(n: float | None) -> str:
    return "Rp " + f"{n:,.0f}".replace(",", ".") if n is not None else "-"


def _ton(kg: float) -> str:
    return f"{kg / 1000:,.1f} ton".replace(",", ".")


async def _proc_pk_output(db: AsyncSession, proc: MillingProcess) -> float | None:
    """PK output sebuah proses: berat terverifikasi > progress terakhir."""
    v = (
        await db.execute(
            select(MillingProcessVerification.berat_output_final_kg).where(
                MillingProcessVerification.milling_process_id == proc.id
            )
        )
    ).scalars().first()
    if v:
        return float(v)
    p = (
        await db.execute(
            select(MillingProgressLog.berat_kumulatif_kg)
            .where(MillingProgressLog.milling_process_id == proc.id)
            .order_by(MillingProgressLog.waktu_update.desc())
            .limit(1)
        )
    ).scalars().first()
    return float(p) if p else None


async def _proc_batches(db: AsyncSession, proc: MillingProcess):
    """Daftar (batch, harga_per_kg|None) sumber sebuah proses."""
    if proc.drying_lot_id:
        rows = (
            await db.execute(
                select(PurchaseBatch, PurchaseBatchVerification.harga_per_kg)
                .join(DryingLotBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
                .join(
                    PurchaseBatchVerification,
                    PurchaseBatchVerification.purchase_batch_id == PurchaseBatch.id,
                    isouter=True,
                )
                .where(DryingLotBatch.drying_lot_id == proc.drying_lot_id)
            )
        ).all()
        return rows
    if proc.purchase_batch_id:
        row = (
            await db.execute(
                select(PurchaseBatch, PurchaseBatchVerification.harga_per_kg)
                .join(
                    PurchaseBatchVerification,
                    PurchaseBatchVerification.purchase_batch_id == PurchaseBatch.id,
                    isouter=True,
                )
                .where(PurchaseBatch.id == proc.purchase_batch_id)
            )
        ).all()
        return row
    return []


async def supplier_scorecard(db: AsyncSession) -> str:
    """Skor per supplier: pasok, harga, rendemen, kualitas, HPP/kg PK.

    Diperingkat dari HPP/kg PK terendah (paling hemat = paling menguntungkan
    pada harga jual PK yang sama).
    """
    # ── 1. Pengadaan per supplier (semua batch) ──
    prow = (
        await db.execute(
            select(
                Supplier.id, Supplier.nama_supplier,
                func.count(PurchaseBatch.id),
                func.coalesce(func.sum(PurchaseBatch.berat_total_kg), 0),
                func.avg(PurchaseBatch.kadar_air_awal_persen),
            )
            .join(PurchaseBatch, PurchaseBatch.supplier_id == Supplier.id)
            .group_by(Supplier.id, Supplier.nama_supplier)
        )
    ).all()
    if not prow:
        return "📊 Belum ada data pembelian untuk dianalisa."

    agg: dict[int, dict] = {}
    for sid, nama, nbatch, kg, ka in prow:
        agg[sid] = {
            "nama": nama, "n_batch": int(nbatch), "kg": float(kg),
            "kadar_air": float(ka) if ka is not None else None,
            "biaya_verif": 0.0, "kg_verif": 0.0,      # utk harga rata2
            "pk_alloc": 0.0, "gabah_milled": 0.0,     # utk rendemen (semua proses)
            "cost_milled": 0.0, "pk_for_hpp": 0.0,    # utk HPP penuh (proses berbiaya)
        }

    # Harga rata-rata tertimbang (dari batch terverifikasi).
    vrow = (
        await db.execute(
            select(
                PurchaseBatch.supplier_id,
                func.coalesce(func.sum(PurchaseBatch.berat_total_kg * PurchaseBatchVerification.harga_per_kg), 0),
                func.coalesce(func.sum(PurchaseBatch.berat_total_kg), 0),
            )
            .join(PurchaseBatchVerification, PurchaseBatchVerification.purchase_batch_id == PurchaseBatch.id)
            .where(PurchaseBatchVerification.harga_per_kg.isnot(None))
            .group_by(PurchaseBatch.supplier_id)
        )
    ).all()
    for sid, biaya, kgv in vrow:
        if sid in agg:
            agg[sid]["biaya_verif"] = float(biaya)
            agg[sid]["kg_verif"] = float(kgv)

    # ── 2. Rendemen & biaya termilling (alokasi proporsional) ──
    procs = (
        await db.execute(select(MillingProcess).where(MillingProcess.status == "selesai"))
    ).scalars().all()
    for proc in procs:
        bd = await production_cost(db, proc)
        if bd is None:
            continue
        output = bd.pk_output
        batches = await _proc_batches(db, proc)
        total_kg = sum(float(b.berat_total_kg) for b, _ in batches)
        if total_kg <= 0:
            continue
        total_cost = bd.total_penuh  # None bila bahan baku belum verif
        for b, _harga in batches:
            sid = b.supplier_id
            if sid not in agg:
                continue
            share = float(b.berat_total_kg) / total_kg
            agg[sid]["pk_alloc"] += output * share
            agg[sid]["gabah_milled"] += float(b.berat_total_kg)
            if total_cost is not None:
                agg[sid]["cost_milled"] += total_cost * share
                agg[sid]["pk_for_hpp"] += output * share

    # ── 3. Susun & peringkat (HPP penuh: bahan baku + operasional) ──
    def hpp(a):
        return a["cost_milled"] / a["pk_for_hpp"] if a["pk_for_hpp"] > 0 else None

    rows = list(agg.values())
    diproduksi = [a for a in rows if a["pk_alloc"] > 0]
    belum = [a for a in rows if a["pk_alloc"] <= 0]
    diproduksi.sort(key=lambda a: (hpp(a) is None, hpp(a) or 0))

    lines = ["📊 *Supplier Scorecard* (keseluruhan)"]
    medali = ["🥇", "🥈", "🥉"]
    for i, a in enumerate(diproduksi):
        tag = medali[i] if i < len(medali) else "•"
        harga = a["biaya_verif"] / a["kg_verif"] if a["kg_verif"] > 0 else None
        rend = a["pk_alloc"] / a["gabah_milled"] * 100 if a["gabah_milled"] > 0 else None
        ka = f"{a['kadar_air']:.0f}%" if a["kadar_air"] is not None else "-"
        h = hpp(a)
        lines.append(
            f"\n{tag} *{a['nama']}* — HPP PK {_rp(h)}/kg"
            + ("  ⭐ terhemat" if i == 0 and h is not None else "")
        )
        lines.append(
            f"• Pasok {_ton(a['kg'])} ({a['n_batch']} batch) · harga ~{_rp(harga)}/kg"
        )
        lines.append(
            f"• Rendemen PK {rend:.1f}% · kadar air masuk {ka}"
            if rend is not None else f"• kadar air masuk {ka}"
        )
    if belum:
        lines.append("\n_Belum ada produksi PK (hanya pengadaan):_")
        for a in belum:
            harga = a["biaya_verif"] / a["kg_verif"] if a["kg_verif"] > 0 else None
            lines.append(f"• {a['nama']}: {_ton(a['kg'])} ({a['n_batch']} batch) · ~{_rp(harga)}/kg")
    lines.append(
        "\n_Peringkat = HPP/kg PK terendah (harga + rendemen). Profit riil butuh "
        "harga jual PK._"
    )
    return "\n".join(lines)


async def hpp_trend(db: AsyncSession) -> str:
    """Tren HPP per kg PK per bulan (rata-rata tertimbang output)."""
    procs = (
        await db.execute(
            select(MillingProcess)
            .where(MillingProcess.status == "selesai", MillingProcess.waktu_selesai.isnot(None))
            .order_by(MillingProcess.waktu_selesai)
        )
    ).scalars().all()

    per_bulan: dict[tuple[int, int], list[float]] = {}  # (thn,bln) -> [cost, output]
    for proc in procs:
        v = (
            await db.execute(
                select(MillingProcessVerification.berat_output_final_kg).where(
                    MillingProcessVerification.milling_process_id == proc.id
                )
            )
        ).scalars().first()
        if not v:
            continue  # output belum terverifikasi
        bd = await production_cost(db, proc)
        if bd is None or bd.total_penuh is None:
            continue  # biaya bahan baku belum lengkap
        key = (proc.waktu_selesai.year, proc.waktu_selesai.month)
        acc = per_bulan.setdefault(key, [0.0, 0.0])
        acc[0] += bd.total_penuh
        acc[1] += bd.pk_output

    if not per_bulan:
        return (
            "📉 Belum ada data HPP. Butuh proses giling yang SELESAI dengan "
            "output PK terverifikasi dan harga gabah terverifikasi."
        )
    lines = ["📉 *Tren HPP penuh per kg PK* (per bulan):"]
    prev = None
    for (thn, bln) in sorted(per_bulan):
        cost, out = per_bulan[(thn, bln)]
        hpp = cost / out if out else 0
        arah = ""
        if prev is not None:
            arah = " 🔺" if hpp > prev else (" 🔻" if hpp < prev else " ➡️")
        lines.append(f"• {_BULAN[bln - 1]} {thn}: {_rp(hpp)}/kg (PK {_ton(out)}){arah}")
        prev = hpp
    return "\n".join(lines)


async def biaya_produksi_detail(db: AsyncSession, kode_proses: str | None = None) -> str:
    """Rincian biaya produksi + HPP penuh sebuah proses (default: terakhir)."""
    q = select(MillingProcess)
    if kode_proses:
        q = q.where(MillingProcess.kode_proses == kode_proses)
    else:
        q = q.where(MillingProcess.status == "selesai").order_by(MillingProcess.id.desc())
    proc = (await db.execute(q.limit(1))).scalars().first()
    if proc is None:
        return "Proses giling tidak ditemukan." if kode_proses else "Belum ada proses giling selesai."
    bd = await production_cost(db, proc)
    if bd is None:
        return f"{proc.kode_proses}: output PK belum ada — biaya belum bisa dihitung."

    rend = bd.pk_output / bd.kg_gabah * 100 if bd.kg_gabah else 0
    ker = f" ({bd.kondisi}{'/dikeringkan' if bd.dried else '/langsung silo'})" if bd.kondisi else ""
    lines = [
        f"💵 *Rincian biaya {proc.kode_proses}*",
        f"Gabah {_ton(bd.kg_gabah)}{ker} → PK {_ton(bd.pk_output)} (rendemen {rend:.1f}%)",
        f"• Bahan baku (gabah): {_rp(bd.bahan_baku)}",
        f"• Bongkar: {_rp(bd.bongkar)}",
        f"• Pengeringan: {_rp(bd.pengeringan)}",
        f"• Operator: {_rp(bd.operator)}",
        f"• Tenaga milling: {_rp(bd.tenaga_milling)}",
        f"• Rubber roll: {_rp(bd.rubber_roll)}",
    ]
    if bd.listrik:
        lines.append(f"• Listrik/mesin: {_rp(bd.listrik)}")
    lines.append(f"• _Subtotal operasional: {_rp(bd.operasional)}_")
    if bd.total_penuh is not None:
        hpp_bahan = bd.bahan_baku / bd.pk_output if bd.pk_output else 0
        hpp_op = bd.operasional / bd.pk_output if bd.pk_output else 0
        lines.append(f"*Total: {_rp(bd.total_penuh)}*")
        lines.append(
            f"*HPP penuh: {_rp(bd.hpp_penuh)}/kg PK* "
            f"(bahan baku {_rp(hpp_bahan)} + operasional {_rp(hpp_op)})"
        )
    else:
        lines.append(
            f"_Operasional {_rp(bd.operasional / bd.pk_output)}/kg PK. "
            "Bahan baku belum diverifikasi → HPP penuh belum bisa dihitung._"
        )
    return "\n".join(lines)


def simulasi_hpp(
    harga_gabah: float | None, rendemen_persen: float | None, *,
    kondisi: str = "basah", langsung_silo: bool = False,
) -> str:
    """What-if HPP dari harga gabah & rendemen (pakai tarif biaya terkini)."""
    from app.config import settings as s

    if not harga_gabah or not rendemen_persen:
        return (
            "Sebutkan harga gabah & rendemen, contoh:\n"
            "`simulasi hpp gabah 7800 rendemen 64`"
        )
    rend = rendemen_persen / 100
    if rend <= 0 or rend > 1:
        return "Rendemen harus antara 1–100 persen."

    if langsung_silo:
        dry, jalur = 0.0, "kering · langsung silo (tanpa pengeringan)"
    elif kondisi == "kering":
        dry, jalur = s.biaya_pengeringan_kering_per_kg, "kering · tetap dikeringkan"
    else:
        dry, jalur = s.biaya_pengeringan_basah_per_kg, "basah · dikeringkan"

    rubber = s.rubber_roll_harga_per_set / (s.rubber_roll_umur_ton * 1000)
    per_gabah = (
        s.biaya_bongkar_per_kg_gabah + dry + s.biaya_operator_per_kg_gabah
        + rubber + s.biaya_listrik_milling_per_kg_gabah
    )
    milling_labor = s.biaya_tenaga_milling_per_kg_pk * rend  # per kg gabah
    op = per_gabah + milling_labor
    total_gabah = harga_gabah + op
    hpp_pk = total_gabah / rend

    return "\n".join([
        f"🧮 *Simulasi HPP* — gabah {jalur}, rendemen {rendemen_persen:g}%",
        f"• Harga gabah: {_rp(harga_gabah)}/kg",
        f"• Biaya proses: {_rp(op)}/kg gabah",
        f"   (bongkar {_rp(s.biaya_bongkar_per_kg_gabah)} · pengeringan {_rp(dry)} · "
        f"operator {_rp(s.biaya_operator_per_kg_gabah)} · rubber {_rp(rubber)} · "
        f"listrik {_rp(s.biaya_listrik_milling_per_kg_gabah)} · tenaga giling {_rp(milling_labor)})",
        f"\n➡️ *HPP: {_rp(hpp_pk)}/kg PK*  ·  {_rp(total_gabah)}/kg gabah basah",
        f"_(bahan baku {_rp(harga_gabah / rend)} + operasional {_rp(op / rend)} per kg PK)_",
    ])
