"""Pencatatan QC lima sampel untuk tiap truk gabah."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PurchaseBatch, PurchaseBatchQc, PurchaseBatchQcSample, User

BIJI_HIJAU = {"hampir_tidak_ada", "sedikit", "sedang", "banyak"}
DENSITI = {"padat", "sedang", "empuk"}


class QcGabahError(ValueError):
    pass


async def catat_qc_gabah(
    db: AsyncSession, *, user: User, kode_batch: str,
    sampel: list[dict], biji_hijau: str, densiti: str, lamur: bool | None = None,
    jumlah_sak_lamur: int | None = None,
) -> tuple[PurchaseBatchQc, float]:
    if len(sampel) != 5:
        raise QcGabahError("QC gabah harus memuat tepat 5 sampel.")
    if biji_hijau not in BIJI_HIJAU:
        raise QcGabahError("Pilih kondisi biji hijau.")
    if densiti not in DENSITI:
        raise QcGabahError("Pilih densiti gabah.")
    batch = (await db.execute(select(PurchaseBatch).where(
        PurchaseBatch.kode_batch == kode_batch,
        PurchaseBatch.dibatalkan_pada.is_(None),
    ).with_for_update())).scalar_one_or_none()
    if batch is None:
        raise QcGabahError("Truk gabah tidak ditemukan atau sudah dibatalkan.")
    ada = (await db.execute(select(PurchaseBatchQc.id).where(
        PurchaseBatchQc.purchase_batch_id == batch.id
    ))).scalar_one_or_none()
    if ada is not None:
        raise QcGabahError("QC untuk truk ini sudah dicatat.")
    if batch.kondisi_gabah == "basah":
        if lamur is None or jumlah_sak_lamur is None or jumlah_sak_lamur < 0:
            raise QcGabahError("Gabah basah wajib mencatat status Lamur dan jumlah sak.")
        if (lamur and jumlah_sak_lamur == 0) or (not lamur and jumlah_sak_lamur != 0):
            raise QcGabahError("Jumlah sak Lamur harus lebih dari 0 jika iya, dan 0 jika tidak.")
    elif batch.kondisi_gabah == "kering":
        if lamur is not None or jumlah_sak_lamur is not None:
            raise QcGabahError("Gabah kering tidak memiliki komponen Lamur.")
    else:
        raise QcGabahError("Kondisi gabah tidak dikenali.")

    nilai_air: list[float] = []
    for nomor, item in enumerate(sampel, start=1):
        try:
            air1, air2 = float(item["kadar_air_1"]), float(item["kadar_air_2"])
        except (KeyError, TypeError, ValueError):
            raise QcGabahError(f"Sampel {nomor}: dua pembacaan kadar air wajib diisi.")
        if not 0 <= air1 <= 100 or not 0 <= air2 <= 100:
            raise QcGabahError(f"Sampel {nomor}: kadar air harus antara 0–100%.")
        nilai_air.extend((air1, air2))

    rata = sum(nilai_air) / 10
    qc = PurchaseBatchQc(
        purchase_batch_id=batch.id, lamur=lamur,
        jumlah_sak_lamur=jumlah_sak_lamur, biji_hijau=biji_hijau,
        densiti=densiti, input_by=user.id,
    )
    db.add(qc)
    await db.flush()
    db.add_all([
        PurchaseBatchQcSample(
            purchase_batch_qc_id=qc.id, nomor_sampel=i,
            kadar_air_1=item["kadar_air_1"], kadar_air_2=item["kadar_air_2"],
        ) for i, item in enumerate(sampel, start=1)
    ])
    batch.kadar_air_awal_persen = rata
    await db.commit()
    await db.refresh(qc)
    return qc, rata
