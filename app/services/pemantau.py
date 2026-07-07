"""Pemantau item 'nyangkut' — menyapu titik menggantung lintas siklus.

Banyak langkah butuh aksi/keputusan manusia yang bisa TERLUPA (bukan bisa
di-auto-transisi). Fungsi ini menyorot item yang DIAM terlalu lama supaya
ditindak — lewat panel dashboard / Mini App & pertanyaan bot (agent).
"""
from __future__ import annotations

from sqlalchemy import exists, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import now_local
from app.models import (
    DryingLot,
    DryingLotBatch,
    MillingProcess,
    MillingProcessVerification,
    PkGudang2Intake,
    PkPurchaseBatch,
    PkPurchaseVerification,
    PolishingProcess,
    PurchaseBatch,
    SiloStorage,
)


def _hrs(now, ts) -> float:
    return (now - ts).total_seconds() / 3600 if ts else 0.0


def _fmt(items: list[tuple[str, float]], label: str, thr: float) -> str | None:
    """Baris ringkas bila ada item ≥ ambang. items=(kode, umur_jam)."""
    stale = sorted([x for x in items if x[1] >= thr], key=lambda x: -x[1])
    if not stale:
        return None
    show = ", ".join(k for k, _ in stale[:4]) + (
        f" +{len(stale) - 4} lagi" if len(stale) > 4 else ""
    )
    tua = stale[0][1]
    return f"• {label} — {len(stale)} item (terlama {tua:.0f}j): {show}"


async def pemantau_nyangkut(
    db: AsyncSession, *, financial: bool = True, scope: str = "all"
) -> str:
    """Laporan item nyangkut. `scope`: 'all'/'g1'/'g2' — operator hanya lihat
    gudangnya. Verifikasi hanya untuk financial (staff/admin)."""
    now = now_local()
    fh = settings.nyangkut_fisik_jam
    vh = settings.nyangkut_verif_jam
    fisik_g1: list[str] = []
    fisik_g2: list[str] = []
    verif: list[str] = []
    g1 = scope in ("all", "g1")
    g2 = scope in ("all", "g2")

    def add(bucket, line):
        if line:
            bucket.append(line)

    # ── FISIK: langkah tersendat (operator) ──
    # 1. Gabah 'baru' belum diproses (dikeringkan/silo).
    rows = (await db.execute(
        select(PurchaseBatch).where(PurchaseBatch.status_batch == "baru")
    )).scalars().all()
    add(fisik_g1, _fmt([(b.kode_batch, _hrs(now, b.waktu_pembelian)) for b in rows],
                    "Gabah belum diproses", fh))

    # 2. Menunggu di dryer (lepas), belum 'mulai pengeringan'.
    in_lot = select(DryingLotBatch.purchase_batch_id)
    rows = (await db.execute(
        select(PurchaseBatch).where(
            PurchaseBatch.status_batch == "di_dryer", PurchaseBatch.id.not_in(in_lot)
        )
    )).scalars().all()
    add(fisik_g1, _fmt([(b.kode_batch, _hrs(now, b.waktu_pembelian)) for b in rows],
                    "Di dryer, belum mulai pengeringan", fh))

    # 3. Lot selesai dikeringkan (dryer_id NULL = kering-langsung, sudah di silo).
    belum_silo = ~exists().where(SiloStorage.drying_lot_id == DryingLot.id)
    rows = [l for l in (await db.execute(
        select(DryingLot).where(DryingLot.status == "selesai", belum_silo)
    )).scalars().all() if l.dryer_id is not None]
    # 3a. Masih didinginkan — belum dinyatakan selesai pendinginan.
    add(fisik_g1, _fmt(
        [(l.kode_lot, _hrs(now, l.waktu_selesai_pengeringan))
         for l in rows if l.waktu_selesai_pendinginan is None],
        "Didinginkan, belum dinyatakan selesai", fh))
    # 3b. Sudah dingin (dryer idle) tapi belum dipindah ke silo — downtime dryer.
    add(fisik_g1, _fmt(
        [(l.kode_lot, _hrs(now, l.waktu_selesai_pendinginan))
         for l in rows if l.waktu_selesai_pendinginan is not None],
        "Sudah dingin, belum ke silo", fh))

    # 4. Kering menunggu di silo (belum digiling).
    rows = (await db.execute(
        select(SiloStorage, PurchaseBatch)
        .join(PurchaseBatch, PurchaseBatch.id == SiloStorage.purchase_batch_id)
        .where(
            SiloStorage.status == "terisi",
            SiloStorage.drying_lot_id.is_(None),
            SiloStorage.purchase_batch_id.is_not(None),
        )
    )).all()
    add(fisik_g1, _fmt([(b.kode_batch, _hrs(now, s.tanggal_masuk)) for s, b in rows],
                    "Kering di silo, belum digiling", fh))

    # 5. Milling berjalan lama (belum selesai).
    rows = (await db.execute(
        select(MillingProcess).where(MillingProcess.status == "proses")
    )).scalars().all()
    add(fisik_g1, _fmt([(m.kode_proses, _hrs(now, m.waktu_mulai)) for m in rows],
                    "Penggilingan berjalan lama", fh))

    # 6. Penyosohan berjalan lama.
    rows = (await db.execute(
        select(PolishingProcess).where(PolishingProcess.status == "proses")
    )).scalars().all()
    add(fisik_g2, _fmt([(p.kode_proses, _hrs(now, p.waktu_mulai)) for p in rows],
                    "Penyosohan berjalan lama", fh))

    # 7. PK luar diterima, belum dimasukkan silo/tumpuk.
    ada_intake = ~exists().where(PkGudang2Intake.pk_purchase_batch_id == PkPurchaseBatch.id)
    rows = (await db.execute(
        select(PkPurchaseBatch).where(
            PkPurchaseBatch.status_batch == "diterima", ada_intake
        )
    )).scalars().all()
    add(fisik_g2, _fmt([(b.kode_batch, _hrs(now, b.waktu_pembelian)) for b in rows],
                    "PK diterima, belum dimasukkan", fh))

    # ── VERIFIKASI: tertunda (staff/admin) ──
    if financial:
        # 8. Harga gabah belum diverifikasi.
        rows = (await db.execute(
            select(PurchaseBatch).where(PurchaseBatch.flag_unverified.is_(True))
        )).scalars().all()
        add(verif, _fmt([(b.kode_batch, _hrs(now, b.waktu_pembelian)) for b in rows],
                        "Harga gabah belum diverifikasi", vh))

        # 9. Output milling belum di-QC (selesai tapi tak ada verifikasi output).
        sudah_verif = ~exists().where(
            (MillingProcessVerification.milling_process_id == MillingProcess.id)
            & (MillingProcessVerification.berat_output_final_kg.is_not(None))
        )
        rows = (await db.execute(
            select(MillingProcess).where(
                MillingProcess.status == "selesai", sudah_verif
            )
        )).scalars().all()
        add(verif, _fmt(
            [(m.kode_proses, _hrs(now, m.waktu_selesai or m.waktu_mulai)) for m in rows],
            "Output giling belum di-QC", vh))

        # 10a. PK luar (sudah masuk) belum diinput kualitasnya.
        qc_ada = exists().where(
            (PkPurchaseVerification.pk_purchase_batch_id == PkPurchaseBatch.id)
            & or_(
                PkPurchaseVerification.kadar_air.is_not(None),
                PkPurchaseVerification.broken_persen.is_not(None),
                PkPurchaseVerification.penyusutan_persen.is_not(None),
                PkPurchaseVerification.butir_kuning.is_not(None),
                PkPurchaseVerification.catatan_lab.is_not(None),
            )
        )
        rows = (await db.execute(
            select(PkPurchaseBatch).where(
                PkPurchaseBatch.status_batch.in_(("diterima", "di_silo", "ditumpuk")),
                ~qc_ada,
            )
        )).scalars().all()
        add(verif, _fmt([(b.kode_batch, _hrs(now, b.waktu_pembelian)) for b in rows],
                        "PK luar belum diinput kualitas", vh))

        # 10b. PK luar harga belum diverifikasi.
        rows = (await db.execute(
            select(PkPurchaseBatch).where(PkPurchaseBatch.flag_unverified.is_(True))
        )).scalars().all()
        add(verif, _fmt([(b.kode_batch, _hrs(now, b.waktu_pembelian)) for b in rows],
                        "Harga PK luar belum diverifikasi", vh))

    parts: list[str] = []
    fisik = (fisik_g1 if g1 else []) + (fisik_g2 if g2 else [])
    if fisik:
        parts.append("🔧 *Perlu diproses:*\n" + "\n".join(fisik))
    if financial and verif:
        parts.append("📋 *Perlu verifikasi:*\n" + "\n".join(verif))
    if not parts:
        return "✅ Tidak ada yang nyangkut — semua mengalir lancar."
    return "⚠️ *Item nyangkut (perlu tindakan):*\n\n" + "\n\n".join(parts)
