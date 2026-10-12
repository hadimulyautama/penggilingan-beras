"""Pencatatan mutu gabah: lima catatan per truk, dua bacaan air per catatan."""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PurchaseBatch, PurchaseBatchQc, PurchaseBatchQcSample, User

BIJI_HIJAU = {"hampir_tidak_ada", "sedikit", "sedang", "banyak"}
DENSITI = {"padat", "sedang", "empuk"}


class QcGabahError(ValueError):
    pass


async def catat_qc_gabah(
    db: AsyncSession, *, user: User, kode_batch: str,
    kadar_air_1: float, kadar_air_2: float,
    biji_hijau: str, densiti: str, lamur: bool | None = None,
    jumlah_sak_lamur: int | None = None,
) -> tuple[PurchaseBatchQc, float, int]:
    """Simpan satu catatan lengkap dan perbarui rata-rata seluruh bacaan truk."""
    try:
        air1, air2 = float(kadar_air_1), float(kadar_air_2)
    except (TypeError, ValueError):
        raise QcGabahError("Dua pembacaan kadar air wajib diisi.")
    if not 0 <= air1 <= 100 or not 0 <= air2 <= 100:
        raise QcGabahError("Kadar air harus antara 0–100%.")
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

    qc = (await db.execute(select(PurchaseBatchQc).where(
        PurchaseBatchQc.purchase_batch_id == batch.id
    ).with_for_update())).scalar_one_or_none()
    if qc is None:
        qc = PurchaseBatchQc(
            purchase_batch_id=batch.id, lamur=lamur,
            jumlah_sak_lamur=jumlah_sak_lamur, biji_hijau=biji_hijau,
            densiti=densiti, input_by=user.id,
        )
        db.add(qc)
        await db.flush()
    if qc.ditutup_pada is not None:
        raise QcGabahError("Proses QC truk ini sudah ditutup.")

    jumlah = await db.scalar(select(func.count(PurchaseBatchQcSample.id)).where(
        PurchaseBatchQcSample.purchase_batch_qc_id == qc.id
    ))
    jumlah = int(jumlah or 0)
    if jumlah >= 5:
        raise QcGabahError("QC truk ini sudah lengkap (5 dari 5 pencatatan).")

    db.add(PurchaseBatchQcSample(
        purchase_batch_qc_id=qc.id, nomor_sampel=jumlah + 1,
        kadar_air_1=air1, kadar_air_2=air2, lamur=lamur,
        jumlah_sak_lamur=jumlah_sak_lamur, biji_hijau=biji_hijau,
        densiti=densiti, input_by=user.id,
    ))
    # Kolom parent menyimpan nilai terbaru agar kompatibel dengan ringkasan lama.
    qc.lamur, qc.jumlah_sak_lamur = lamur, jumlah_sak_lamur
    qc.biji_hijau, qc.densiti, qc.input_by = biji_hijau, densiti, user.id
    await db.flush()
    samples = (await db.execute(select(PurchaseBatchQcSample.kadar_air_1,
                                       PurchaseBatchQcSample.kadar_air_2,
                                       PurchaseBatchQcSample.lamur,
                                       PurchaseBatchQcSample.jumlah_sak_lamur).where(
        PurchaseBatchQcSample.purchase_batch_qc_id == qc.id
    ))).all()
    bacaan = [float(value) for row in samples for value in row[:2]]
    rata = sum(bacaan) / len(bacaan)
    if batch.kondisi_gabah == "basah":
        # Kadar air adalah rata-rata; jumlah sak Lamur adalah total tiap baris
        # muatan yang diperiksa. Riwayat tiap pemeriksaan tetap berada di tabel.
        qc.lamur = any(row[2] is True for row in samples)
        qc.jumlah_sak_lamur = sum(int(row[3] or 0) for row in samples)
    else:
        qc.lamur = qc.jumlah_sak_lamur = None
    batch.kadar_air_awal_persen = rata
    await db.commit()
    await db.refresh(qc)
    return qc, rata, jumlah + 1


async def tutup_qc_gabah(
    db: AsyncSession, *, user: User, kode_batch: str,
) -> tuple[PurchaseBatchQc, int]:
    """Tutup QC sebelum 5 catatan hanya setelah setidaknya satu tersimpan."""
    batch = (await db.execute(select(PurchaseBatch).where(
        PurchaseBatch.kode_batch == kode_batch,
        PurchaseBatch.dibatalkan_pada.is_(None),
    ).with_for_update())).scalar_one_or_none()
    if batch is None:
        raise QcGabahError("Truk gabah tidak ditemukan atau sudah dibatalkan.")
    qc = (await db.execute(select(PurchaseBatchQc).where(
        PurchaseBatchQc.purchase_batch_id == batch.id
    ).with_for_update())).scalar_one_or_none()
    if qc is None:
        raise QcGabahError("Belum ada pencatatan QC untuk truk ini.")
    if qc.ditutup_pada is not None:
        raise QcGabahError("Proses QC truk ini sudah ditutup.")
    jumlah = int(await db.scalar(select(func.count(PurchaseBatchQcSample.id)).where(
        PurchaseBatchQcSample.purchase_batch_qc_id == qc.id
    )) or 0)
    if jumlah == 0:
        raise QcGabahError("Catat QC minimal satu kali sebelum menutup proses.")
    if jumlah >= 5:
        raise QcGabahError("QC sudah lengkap (5 dari 5 pencatatan).")
    from app.database import now_local
    qc.ditutup_pada = now_local()
    qc.ditutup_by = user.id
    await db.commit()
    await db.refresh(qc)
    return qc, jumlah
