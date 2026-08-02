"""Penerbit nomor naskah dinas dari register (DB) — anti-bentrok, reset tahunan.

Sumber tunggal nomor. Urut dihitung per (jenis, kode, tahun); baris batal tetap
dihitung agar urutan tidak dipakai ulang. Bentrok (race) ditangani dengan retry
memanfaatkan UniqueConstraint uq_nomor_urut.

Acuan: Pedoman Tata Naskah Dinas (PDM/TND/PT-HMU/01).
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.kantor.dokumen import format as fmt
from app.kantor.models import NomorDokumen

_MAKS_RETRY = 5


async def urut_terakhir(
    db: AsyncSession, jenis: str, kode: str, divisi: str, tahun: int
) -> int:
    """Urut tertinggi utk (jenis, kode, divisi, tahun); 0 bila belum ada."""
    stmt = select(func.max(NomorDokumen.urut)).where(
        NomorDokumen.jenis == jenis,
        NomorDokumen.kode == kode.upper(),
        NomorDokumen.divisi == fmt.normal_divisi(divisi),
        NomorDokumen.tahun == tahun,
    )
    return (await db.execute(stmt)).scalar() or 0


async def terbitkan_nomor_surat(
    db: AsyncSession,
    *,
    kode: str,
    divisi: str,
    bulan: int,
    tahun: int,
    perihal: str | None = None,
    pihak: str | None = None,
    pembuat: str | None = None,
    file_ref: str | None = None,
) -> NomorDokumen:
    """Terbitkan nomor surat berikutnya & catat di register. Commit di sini.

    Raise ValueError bila kode tak dikenali atau bulan tak valid. Aman terhadap
    penerbitan paralel: bila urut bentrok, dicoba ulang dengan urut berikutnya.
    """
    kode = kode.upper()
    divisi = fmt.normal_divisi(divisi)
    if not fmt.kode_dikenali(kode):
        raise ValueError(f"Kode perihal tidak dikenali: {kode!r}")
    fmt.bulan_romawi(bulan)  # validasi bulan (raise bila di luar 1-12)

    last = await urut_terakhir(db, "surat", kode, divisi, tahun)
    for i in range(_MAKS_RETRY):
        urut = last + 1 + i
        row = NomorDokumen(
            nomor_lengkap=fmt.build_nomor_surat(urut, kode, divisi, bulan, tahun),
            jenis="surat",
            kode=kode,
            divisi=divisi,
            tahun=tahun,
            bulan=bulan,
            urut=urut,
            perihal=perihal,
            pihak=pihak,
            pembuat=pembuat,
            file_ref=file_ref,
            status="aktif",
        )
        db.add(row)
        try:
            await db.commit()
        except IntegrityError:
            await db.rollback()
            continue  # bentrok urut/nomor → coba urut berikutnya
        await db.refresh(row)
        return row
    raise RuntimeError(
        f"Gagal terbitkan nomor surat {kode}/{tahun} setelah {_MAKS_RETRY} percobaan."
    )


async def batalkan_nomor(db: AsyncSession, nomor_lengkap: str) -> bool:
    """Tandai sebuah nomor sebagai 'batal' (tidak dihapus). True bila ditemukan."""
    stmt = select(NomorDokumen).where(NomorDokumen.nomor_lengkap == nomor_lengkap)
    row = (await db.execute(stmt)).scalar_one_or_none()
    if row is None:
        return False
    row.status = "batal"
    await db.commit()
    return True
