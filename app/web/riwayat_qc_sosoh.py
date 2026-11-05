"""Riwayat QC beras memakai cakupan proses yang sama dengan riwayat sosoh."""
from fastapi import HTTPException
from sqlalchemy import func, select

from app.database import SessionLocal
from app.models import PolishingProcess, SampelQcSosoh
from app.services.qc_sosoh import data_proses
from app.services.cakupan_fasilitas import batas
from app.web.portal.scope import is_customer_read
from app.web.tampilan import render_laci


async def halaman(request, referensi=None):
    lingkup = (PolishingProcess.id.in_(request.state.portal_scope.ids(PolishingProcess))
               if is_customer_read(request) else batas(request.state.akun.user,PolishingProcess))
    async with SessionLocal() as db:
        if referensi is not None:
            proc = await db.scalar(select(PolishingProcess).where(
                PolishingProcess.kode_proses == referensi, lingkup))
            if proc is None:
                raise HTTPException(404, "Catatan QC proses ini tidak ditemukan.")
            data = await data_proses(db, proc)
            if not data["sampel"]:
                raise HTTPException(404, "Catatan QC proses ini tidak ditemukan.")
            return await render_laci(request, "qc_sosoh_riwayat.html", qc_sosoh=data,
                qc_kode=proc.kode_proses, layar="riwayat_qc",
                proses_href=(f"/riwayat-sosoh/{proc.id}" if proc.status == "selesai" else f"/proses-aktif/sosoh/{proc.kode_proses}"))
        rows = (await db.execute(select(PolishingProcess.kode_proses, PolishingProcess.status,
            func.count(SampelQcSosoh.id), func.count(SampelQcSosoh.id).filter(SampelQcSosoh.hasil_pada.is_(None), SampelQcSosoh.dibatalkan_pada.is_(None)))
            .join(SampelQcSosoh, SampelQcSosoh.polishing_process_id == PolishingProcess.id)
            .where(lingkup).group_by(PolishingProcess.id)
            .order_by(func.max(SampelQcSosoh.waktu_sampel).desc(), PolishingProcess.id.desc()).limit(200))).all()
    return await render_laci(request, "qc_sosoh_riwayat.html", layar="riwayat_qc",
        proses_qc=[dict(kode=kode, status=status, jumlah=n, menunggu=m) for kode, status, n, m in rows])
