"""Adapter idempoten dari proses domain Produksi ke catatan lintas aplikasi."""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import AsyncSession

from hmu_core import (ArusProses, JenisPemilik, JenisProses, PemilikProses,
                      Produk, ProsesOperasional, StatusProses)
from hmu_core.proses_db import ArusProsesTerpadu, ProsesTerpadu


def bentuk_proses(
    *, id: int, kode: str, jenis: JenisProses, status: StatusProses,
    jasa_id: int | None, waktu_mulai=None, waktu_selesai=None,
    pelaksana_id: int | None = None, bahan=(), hasil=(),
    referensi_asal=(),
) -> ProsesOperasional:
    return ProsesOperasional(
        aplikasi="produksi", id=id, kode=kode, jenis=jenis, status=status,
        pemilik=(PemilikProses(JenisPemilik.PABRIK) if jasa_id is None else
                 PemilikProses(JenisPemilik.JASA, id=jasa_id)),
        waktu_mulai=waktu_mulai, waktu_selesai=waktu_selesai,
        pelaksana_id=pelaksana_id, bahan=tuple(bahan), hasil=tuple(hasil),
        referensi_asal=tuple(referensi_asal),
    )


async def simpan_proses_bersama(
    db: AsyncSession, proses: ProsesOperasional, *,
    tabel_sumber: str, id_sumber: int | str,
    metadata_domain: dict | None = None,
) -> ProsesTerpadu:
    """Tulis ulang proyeksi proses dari sumber domain secara atomik.

    Identitasnya unik terhadap tabel dan id lama. Pemanggilan ulang memperbarui
    status/waktu serta mengganti daftar arus, sehingga aman dipakai ketika
    proses mulai dan ketika hasil final tersedia.
    """
    row = (await db.execute(
        select(ProsesTerpadu).options(selectinload(ProsesTerpadu.arus)).where(
            ProsesTerpadu.aplikasi == proses.aplikasi,
            ProsesTerpadu.tabel_sumber == tabel_sumber,
            ProsesTerpadu.id_sumber == str(id_sumber),
        ).with_for_update()
    )).scalar_one_or_none()
    sumber = proses.ke_entitas(
        tabel_sumber=tabel_sumber, id_sumber=id_sumber,
        metadata_domain=metadata_domain,
    )
    if row is None:
        db.add(sumber)
        await db.flush()
        return sumber

    for kolom in (
        "kode", "jenis", "status", "jenis_pemilik", "id_pemilik",
        "nama_pemilik", "waktu_mulai", "waktu_selesai", "pelaksana_id",
        "referensi_asal", "metadata_domain",
    ):
        setattr(row, kolom, getattr(sumber, kolom))
    row.arus.clear()
    row.arus.extend(sumber.arus)
    await db.flush()
    return row


async def tutup_proses_bersama(
    db: AsyncSession, *, tabel_sumber: str, id_sumber: int | str,
    waktu_selesai, hasil=(), metadata_tambahan: dict | None = None,
) -> ProsesTerpadu | None:
    """Sinkronkan penutupan proses dan hasil tanpa mengubah bahan awalnya."""
    row = (await db.execute(
        select(ProsesTerpadu).options(selectinload(ProsesTerpadu.arus)).where(
            ProsesTerpadu.aplikasi == "produksi",
            ProsesTerpadu.tabel_sumber == tabel_sumber,
            ProsesTerpadu.id_sumber == str(id_sumber),
        ).with_for_update()
    )).scalar_one_or_none()
    if row is None:
        return None
    row.status = StatusProses.SELESAI.value
    row.waktu_selesai = waktu_selesai
    if metadata_tambahan:
        row.metadata_domain = {**(row.metadata_domain or {}), **metadata_tambahan}
    row.arus[:] = [a for a in row.arus if a.arah != "hasil"]
    for item in hasil:
        row.arus.append(ArusProsesTerpadu(
            arah="hasil", komoditas=item.produk.komoditas,
            atribut_produk=dict(item.produk.atribut), berat_kg=item.berat_kg,
            referensi=item.referensi, lokasi_id=item.lokasi_id,
            detail={"merek_produk": item.produk.merek_produk,
                    "kemasan": None},
        ))
    await db.flush()
    return row
