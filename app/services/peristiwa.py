"""Menulis ke buku besar peristiwa dan memperbarui proyeksinya.

Satu aturan untuk semua aksi yang pindah ke jalur ini (Tahap 3): satu
pencatatan = SATU transaksi milik pemanggil, yang di dalamnya berurutan —
kunci kiriman, kunci baris sumber daya, tambah peristiwa, constraint yang
menolak keadaan mustahil, pembaruan proyeksi (dan cermin tabel lama). Modul
ini TIDAK commit; gagal di langkah mana pun berarti tak ada yang tersimpan.

`catat()` idempoten pada `kunci_kiriman`: kiriman yang sama dua kali
mengembalikan peristiwa pertama (`baru=False`), tanpa menambah apa pun.

`PENANGAN` memetakan jenis peristiwa → fungsi yang menerapkannya ke
proyeksi. Fungsi yang sama dipakai saat mencatat DAN saat membangun ulang
dari nol, jadi keduanya tak mungkin berbeda.
"""
from __future__ import annotations

import logging
from datetime import date, datetime
from decimal import Decimal
from typing import Awaitable, Callable

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (Peristiwa, ProyeksiGabahMasuk, ProyeksiPindahTumpukanSilo, ProyeksiPkLuarMasuk,
                        ProyeksiPkMasukG2, ProyeksiTransferPk)
from app.models.peristiwa import (DIBATALKAN, GABAH_MASUK, GABAH_MASUK_DIBATALKAN, PK_DIPINDAH_G1G2,
                                  PK_DIPINDAH_G1G2_DIBATALKAN, PK_LUAR_MASUK,
                                  PK_LUAR_MASUK_DIBATALKAN, PK_MASUK_G2, PK_MASUK_G2_DIBATALKAN,
                                  PK_TUMPUKAN_KE_SILO, PK_TUMPUKAN_KE_SILO_DIBATALKAN, TERCATAT)

log = logging.getLogger("peristiwa")


def bersih(nilai):
    """Muatan → bentuk JSON: tanggal/waktu jadi ISO, Decimal jadi angka."""
    if isinstance(nilai, dict):
        return {k: bersih(v) for k, v in nilai.items()}
    if isinstance(nilai, (list, tuple)):
        return [bersih(v) for v in nilai]
    if isinstance(nilai, datetime):
        return nilai.isoformat()
    if isinstance(nilai, date):
        return nilai.isoformat()
    if isinstance(nilai, Decimal):
        return float(nilai)
    return nilai


async def batalkan(db: AsyncSession, *, jenis_lawan: str, peristiwa_id: int, pelaku_id: int | None,
                   muatan: dict) -> Peristiwa:
    """Peristiwa LAWAN untuk `peristiwa_id`. Kuncinya diturunkan dari yang
    dibatalkan, jadi dua pembatalan atas satu kejadian = satu peristiwa."""
    return await catat(db, jenis=jenis_lawan, pelaku_id=pelaku_id,
                       kunci_kiriman=f"{jenis_lawan}:{peristiwa_id}",
                       muatan={"peristiwa_id": peristiwa_id, **muatan},
                       membatalkan_id=peristiwa_id)


async def catat(db: AsyncSession, *, jenis: str, pelaku_id: int | None, kunci_kiriman: str,
                muatan: dict, membatalkan_id: int | None = None,
                waktu: datetime | None = None, terapkan: bool = True) -> Peristiwa:
    """Tambah satu peristiwa (atau kembalikan yang sudah ada untuk kunci itu),
    lalu terapkan ke proyeksinya. Tidak commit.

    Dicoba dalam SAVEPOINT: tabrakan `kunci_kiriman` tak menggugurkan
    transaksi pemanggil — yang sudah dikunci tetap terkunci.
    """
    e = Peristiwa(jenis=jenis, pelaku_id=pelaku_id, kunci_kiriman=kunci_kiriman,
                  muatan=bersih(muatan), membatalkan_id=membatalkan_id)
    if waktu is not None:
        e.waktu = waktu
    try:
        async with db.begin_nested():
            db.add(e)
            await db.flush()
    except IntegrityError as galat:
        if "kunci_kiriman" not in str(getattr(galat, "orig", galat)):
            raise
        ada = (await db.execute(
            select(Peristiwa).where(Peristiwa.kunci_kiriman == kunci_kiriman))).scalars().first()
        if ada is None:
            raise
        ada.baru = False
        return ada
    e.baru = True
    if terapkan:
        await terapkan_ke_proyeksi(db, e)
    return e


async def jumlah_jenis(db: AsyncSession, jenis: str, kunci_muatan: str, nilai) -> int:
    """Berapa peristiwa `jenis` yang muatannya `kunci_muatan` == nilai.
    Dipakai menurunkan kunci kiriman berurutan (pencatatan ke-n satu tiket)."""
    from sqlalchemy import func

    # Tipe kolomnya JSON generik (varian JSONB di Postgres), jadi
    # pembandingnya yang generik pula: `as_string()` jalan di keduanya.
    kolom = Peristiwa.muatan[kunci_muatan].as_string()
    return (await db.execute(
        select(func.count(Peristiwa.id)).where(Peristiwa.jenis == jenis, kolom == str(nilai))
    )).scalar_one()


# ───────────────────────── Penangan per jenis ─────────────────────────

async def _gabah_masuk(db: AsyncSession, e: Peristiwa) -> None:
    m = e.muatan
    e.proyeksi = ProyeksiGabahMasuk(
        peristiwa_id=e.id, kode_batch=m["kode_batch"],
        timbangan_transaksi_id=m.get("timbangan_transaksi_id"),
        supplier_id=m.get("supplier_id"), nama_supplier=m.get("nama_supplier"),
        berat_kg=m.get("berat_kg"), sumber_berat=m.get("sumber_berat", "manual"),
        kondisi=m["kondisi"], no_polisi=m.get("no_polisi"),
        tanggal=date.fromisoformat(m["tanggal"]),
        waktu=datetime.fromisoformat(m["waktu"]),
        pelaku_id=e.pelaku_id, status=TERCATAT,
        purchase_batch_id=m.get("purchase_batch_id"),
    )
    db.add(e.proyeksi)
    await db.flush()


async def _gabah_masuk_dibatalkan(db: AsyncSession, e: Peristiwa) -> None:
    p = await db.get(ProyeksiGabahMasuk, e.membatalkan_id)
    if p is None:
        raise ValueError(f"peristiwa {e.id} membatalkan gabah_masuk #{e.membatalkan_id} yang tak ada")
    p.status = DIBATALKAN
    p.dibatalkan_peristiwa_id = e.id
    await db.flush()


async def _pk_luar_masuk(db: AsyncSession, e: Peristiwa) -> None:
    m = e.muatan
    e.proyeksi = ProyeksiPkLuarMasuk(
        peristiwa_id=e.id, kode_batch=m["kode_batch"],
        timbangan_transaksi_id=m.get("timbangan_transaksi_id"),
        supplier_id=m.get("supplier_id"), nama_supplier=m.get("nama_supplier"),
        berat_kg=m.get("berat_kg"), sumber_berat=m.get("sumber_berat", "manual"),
        jenis_pk=m.get("jenis_pk"), kadar_air=m.get("kadar_air"), no_polisi=m.get("no_polisi"),
        tanggal=date.fromisoformat(m["tanggal"]),
        waktu=datetime.fromisoformat(m["waktu"]),
        pelaku_id=e.pelaku_id, status=TERCATAT,
        pk_purchase_batch_id=m.get("pk_purchase_batch_id"),
    )
    db.add(e.proyeksi)
    await db.flush()


async def _pk_luar_masuk_dibatalkan(db: AsyncSession, e: Peristiwa) -> None:
    p = await db.get(ProyeksiPkLuarMasuk, e.membatalkan_id)
    if p is None:
        raise ValueError(f"peristiwa {e.id} membatalkan pk_luar_masuk #{e.membatalkan_id} yang tak ada")
    p.status = DIBATALKAN
    p.dibatalkan_peristiwa_id = e.id
    await db.flush()


async def _pk_masuk_g2(db: AsyncSession, e: Peristiwa) -> None:
    m = e.muatan
    e.proyeksi = ProyeksiPkMasukG2(
        peristiwa_id=e.id, sumber_tipe=m["sumber_tipe"],
        pk_purchase_batch_id=m.get("pk_purchase_batch_id"),
        internal_transfer_id=m.get("internal_transfer_id"),
        tujuan=m["tujuan"], silo_id=m.get("silo_id"), berat_kg=m["berat_kg"],
        hpp_per_kg=m.get("hpp_per_kg"), ke_proses=m.get("ke_proses"),
        tanggal=date.fromisoformat(m["tanggal"]), waktu=datetime.fromisoformat(m["waktu"]),
        pelaku_id=e.pelaku_id, status=TERCATAT, intake_id=m.get("intake_id"),
    )
    db.add(e.proyeksi)
    await db.flush()
    # Pemasukan pasangan sebuah transfer: tautkan ke proyeksi transfernya.
    # Dibaca dari MUATAN, jadi bangun-ulang menghasilkan tautan yang sama.
    if m.get("transfer_peristiwa_id"):
        pt = await db.get(ProyeksiTransferPk, m["transfer_peristiwa_id"])
        if pt is not None:
            pt.intake_peristiwa_id = e.id
            await db.flush()


async def _pk_masuk_g2_dibatalkan(db: AsyncSession, e: Peristiwa) -> None:
    p = await db.get(ProyeksiPkMasukG2, e.membatalkan_id)
    if p is None:
        raise ValueError(f"peristiwa {e.id} membatalkan pk_masuk_g2 #{e.membatalkan_id} yang tak ada")
    p.status = DIBATALKAN
    p.dibatalkan_peristiwa_id = e.id
    await db.flush()


async def _pk_dipindah_g1g2(db: AsyncSession, e: Peristiwa) -> None:
    m = e.muatan
    e.proyeksi = ProyeksiTransferPk(
        peristiwa_id=e.id, kode_transfer=m["kode_transfer"],
        milling_process_id=m.get("milling_process_id"), kode_proses=m.get("kode_proses"),
        berat_kg=m["berat_kg"], lokasi_tujuan=m["lokasi_tujuan"], hpp_per_kg=m.get("hpp_per_kg"),
        jenis=m.get("jenis"), tanggal=date.fromisoformat(m["tanggal"]),
        waktu=datetime.fromisoformat(m["waktu"]), pelaku_id=e.pelaku_id, status=TERCATAT,
        intake_peristiwa_id=m.get("intake_peristiwa_id"), transfer_id=m.get("transfer_id"),
    )
    db.add(e.proyeksi)
    await db.flush()


async def _pk_dipindah_g1g2_dibatalkan(db: AsyncSession, e: Peristiwa) -> None:
    p = await db.get(ProyeksiTransferPk, e.membatalkan_id)
    if p is None:
        raise ValueError(f"peristiwa {e.id} membatalkan pk_dipindah_g1g2 #{e.membatalkan_id} yang tak ada")
    p.status = DIBATALKAN
    p.dibatalkan_peristiwa_id = e.id
    await db.flush()


async def _pk_tumpukan_ke_silo(db: AsyncSession, e: Peristiwa) -> None:
    m = e.muatan
    e.proyeksi = ProyeksiPindahTumpukanSilo(
        peristiwa_id=e.id, kode_pindah=m["kode_pindah"], intake_id=m["intake_id"],
        intake_peristiwa_id=m.get("intake_peristiwa_id"), silo_id=m["silo_id"],
        berat_kg=m["berat_kg"], ke_proses=m.get("ke_proses"),
        tanggal=date.fromisoformat(m["tanggal"]), waktu=datetime.fromisoformat(m["waktu"]),
        pelaku_id=e.pelaku_id, status=TERCATAT, move_id=m.get("move_id"),
    )
    db.add(e.proyeksi)
    await db.flush()


async def _pk_tumpukan_ke_silo_dibatalkan(db: AsyncSession, e: Peristiwa) -> None:
    p = await db.get(ProyeksiPindahTumpukanSilo, e.membatalkan_id)
    if p is None:
        raise ValueError(f"peristiwa {e.id} membatalkan pk_tumpukan_ke_silo #{e.membatalkan_id} yang tak ada")
    p.status = DIBATALKAN
    p.dibatalkan_peristiwa_id = e.id
    await db.flush()


PENANGAN: dict[str, Callable[[AsyncSession, Peristiwa], Awaitable[None]]] = {
    GABAH_MASUK: _gabah_masuk,
    GABAH_MASUK_DIBATALKAN: _gabah_masuk_dibatalkan,
    PK_LUAR_MASUK: _pk_luar_masuk,
    PK_LUAR_MASUK_DIBATALKAN: _pk_luar_masuk_dibatalkan,
    PK_MASUK_G2: _pk_masuk_g2,
    PK_MASUK_G2_DIBATALKAN: _pk_masuk_g2_dibatalkan,
    PK_DIPINDAH_G1G2: _pk_dipindah_g1g2,
    PK_DIPINDAH_G1G2_DIBATALKAN: _pk_dipindah_g1g2_dibatalkan,
    PK_TUMPUKAN_KE_SILO: _pk_tumpukan_ke_silo,
    PK_TUMPUKAN_KE_SILO_DIBATALKAN: _pk_tumpukan_ke_silo_dibatalkan,
}

#: Tabel proyeksi yang dikosongkan lalu diisi ulang saat membangun dari nol.
TABEL_PROYEKSI = (ProyeksiGabahMasuk, ProyeksiPkLuarMasuk, ProyeksiPkMasukG2, ProyeksiTransferPk,
                  ProyeksiPindahTumpukanSilo)


async def terapkan_ke_proyeksi(db: AsyncSession, e: Peristiwa) -> None:
    fn = PENANGAN.get(e.jenis)
    if fn is not None:
        await fn(db, e)


async def bangun_ulang(db: AsyncSession) -> dict[str, int]:
    """Kosongkan seluruh proyeksi, lalu terapkan kembali semua peristiwa
    berurutan id. Mengembalikan hitungan per tabel. Commit di akhir.

    Inilah bukti bahwa proyeksi memang turunan: bila hasilnya berbeda dari
    keadaan hidup, yang salah adalah penangannya — dan uji
    `test_bangun_ulang_sama_dengan_keadaan_hidup` menangkapnya.
    """
    for tabel in TABEL_PROYEKSI:
        await db.execute(delete(tabel))
    n = 0
    hasil = (await db.execute(select(Peristiwa).order_by(Peristiwa.id))).scalars()
    for e in hasil:
        await terapkan_ke_proyeksi(db, e)
        n += 1
    laporan = {"peristiwa": n}
    for tabel in TABEL_PROYEKSI:
        from sqlalchemy import func
        laporan[tabel.__tablename__] = (await db.execute(
            select(func.count()).select_from(tabel))).scalar_one()
    await db.commit()
    return laporan
