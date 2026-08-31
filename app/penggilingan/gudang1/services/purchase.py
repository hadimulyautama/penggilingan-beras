"""Logika bisnis pembelian gabah (Gudang 1)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date, time, timedelta

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import input_time, now_local
from app.models import PurchaseBatch, Supplier, User
from app.penggilingan.gudang1.services.timbang_link import ambil_tiket
from app.penggilingan.peta_jenis import intake_dari_jenis
from app.services.activity_log import log_activity
from app.services.codegen import next_purchase_batch_code
from app.services.notification import create_notification


class DailyLimitReached(Exception):
    """Batas maksimal batch pembelian gabah per hari terlampaui."""


async def find_or_create_supplier(db: AsyncSession, nama: str) -> tuple[Supplier, bool]:
    """Cari supplier aktif (case-insensitive). Kembalikan (supplier, dibuat_baru)."""
    nama = nama.strip()
    stmt = select(Supplier).where(
        func.lower(Supplier.nama_supplier) == nama.lower(),
        Supplier.deleted_at.is_(None),
    )
    supplier = (await db.execute(stmt)).scalars().first()
    if supplier:
        return supplier, False
    supplier = Supplier(nama_supplier=nama, status="aktif")
    db.add(supplier)
    await db.flush()
    return supplier, True


async def count_batches_on(db: AsyncSession, tgl: date) -> int:
    stmt = (
        select(func.count())
        .select_from(PurchaseBatch)
        .where(PurchaseBatch.tanggal_pembelian == tgl)
    )
    return (await db.execute(stmt)).scalar_one()


@dataclass
class CreatedBatch:
    batch: PurchaseBatch
    supplier: Supplier
    supplier_created: bool


async def create_purchase_batch(
    db: AsyncSession,
    *,
    user: User,
    nama_supplier: str,
    berat_kg: float,
    kondisi_gabah: str,
    no_polisi_truk: str | None,
    kadar_air_awal_persen: float | None,
    tanggal: date | None = None,
    jam: time | None = None,
) -> CreatedBatch:
    """Buat batch pembelian gabah + audit + notifikasi verifikasi harga.

    `tanggal`/`jam` opsional untuk backdate (isi mundur); default sekarang.
    Melempar DailyLimitReached jika sudah mencapai batas harian.
    """
    now = input_time(tanggal, jam)  # BackdateError bila di masa depan
    if await count_batches_on(db, now.date()) >= settings.max_purchase_batch_per_day:
        raise DailyLimitReached(settings.max_purchase_batch_per_day)

    supplier, created = await find_or_create_supplier(db, nama_supplier)

    kode = await next_purchase_batch_code(db, now.date())
    batch = PurchaseBatch(
        kode_batch=kode,
        supplier_id=supplier.id,
        berat_total_kg=berat_kg,
        no_polisi_truk=no_polisi_truk,
        kondisi_gabah=kondisi_gabah,
        kadar_air_awal_persen=kadar_air_awal_persen,
        tanggal_pembelian=now.date(),
        waktu_pembelian=now,
        input_by=user.id,
        status_batch="baru",
        flag_unverified=True,
    )
    db.add(batch)
    await db.flush()

    await log_activity(
        db,
        table_name="purchase_batches",
        record_id=batch.id,
        action="INSERT",
        changed_by=user.id,
        new_value=f"{kode} | {supplier.nama_supplier} | {berat_kg:.0f}kg | {kondisi_gabah}",
    )
    await create_notification(
        db,
        tipe="verifikasi_harga_gabah",
        pesan=(
            f"🟡 Batch {kode} ({supplier.nama_supplier}, {berat_kg:.0f} kg) "
            f"menunggu verifikasi harga."
        ),
        target_role="staff",
        prioritas="kuning",
        table_name="purchase_batches",
        record_id=batch.id,
    )

    await db.commit()
    await db.refresh(batch)
    return CreatedBatch(batch=batch, supplier=supplier, supplier_created=created)


async def create_purchase_batch_dari_timbang(
    db: AsyncSession,
    *,
    user: User,
    timbangan_transaksi_id: int,
    kadar_air_awal_persen: float | None = None,
    kondisi_gabah: str | None = None,
    tanggal: date | None = None,
    jam: time | None = None,
) -> CreatedBatch:
    """Buat batch gabah DARI tiket TIMBANG (aplikasi terpisah, DB terintegrasi).

    Operator hanya memilih tiket; SUPPLIER, BOBOT, NOPOL diturunkan dari timbang (tak
    diinput ulang → cegah dobel). Bobot & `sumber_berat` ikut tiket: NOTA bila ada,
    selain itu REAL timbang. `timbangan_transaksi_id` UNIQUE → satu tiket satu batch.
    """
    tiket = await ambil_tiket(db, timbangan_transaksi_id)
    if tiket is None:
        raise ValueError("Tiket timbang tidak ditemukan.")
    if tiket.get("arah") != "MASUK":
        raise ValueError("Tiket timbang bukan barang MASUK.")
    # Bobot boleh belum ada (batch dibuat saat bongkar). Referensi bobot = tiket:
    # nota bila ada, selain itu netto timbang. Kosong → status "menunggu bobot",
    # diisi otomatis oleh sinkronisasi saat tiket punya bobot (nota/timbang-2).
    b = tiket.get("berat_hpp_kg")
    ada_bobot = b is not None and float(b) > 0
    berat = float(b) if ada_bobot else None
    sumber = tiket["sumber_berat"] if ada_bobot else "menunggu"

    now = input_time(tanggal, jam)
    if await count_batches_on(db, now.date()) >= settings.max_purchase_batch_per_day:
        raise DailyLimitReached(settings.max_purchase_batch_per_day)

    # Supplier: pakai yang tertaut di tiket bila ada; selain itu cari/buat dari nama pihak.
    if tiket.get("supplier_id"):
        supplier = await db.get(Supplier, tiket["supplier_id"])
        created = False
    else:
        nama = tiket.get("nama_supplier") or tiket.get("pihak_nama") or "Tanpa Nama"
        supplier, created = await find_or_create_supplier(db, nama)

    _info = intake_dari_jenis(tiket.get("jenis_kode", ""))
    kondisi = kondisi_gabah or (_info.kondisi if _info and _info.kondisi else "basah")
    kode = await next_purchase_batch_code(db, now.date())
    batch = PurchaseBatch(
        kode_batch=kode,
        supplier_id=supplier.id,
        berat_total_kg=berat,  # None = menunggu bobot (disinkron dari tiket)
        no_polisi_truk=tiket.get("nomor_polisi"),
        kondisi_gabah=kondisi,
        kadar_air_awal_persen=kadar_air_awal_persen,
        tanggal_pembelian=now.date(),
        waktu_pembelian=now,
        input_by=user.id,
        status_batch="baru",
        flag_unverified=True,
        timbangan_transaksi_id=timbangan_transaksi_id,
        sumber_berat=sumber,
    )
    db.add(batch)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        raise ValueError("Tiket timbang ini sudah ditautkan ke batch lain.")

    b_str = f"{berat:.0f}kg ({sumber})" if ada_bobot else "menunggu bobot"
    await log_activity(
        db, table_name="purchase_batches", record_id=batch.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{kode} | {supplier.nama_supplier} | {b_str} | timbang {tiket['kode']}",
    )
    await create_notification(
        db, tipe="verifikasi_harga_gabah",
        pesan=(f"🟡 Batch {kode} ({supplier.nama_supplier}, {b_str}, "
               f"dari timbang {tiket['kode']}) menunggu verifikasi harga."),
        target_role="staff", prioritas="kuning",
        table_name="purchase_batches", record_id=batch.id,
    )

    await db.commit()
    await db.refresh(batch)
    return CreatedBatch(batch=batch, supplier=supplier, supplier_created=created)


async def undo_purchase_batch(db: AsyncSession, *, batch_id: int, user: User) -> bool:
    """Batalkan batch dalam jendela waktu (default 15 menit) bila belum diproses.

    Kembalikan True jika berhasil dibatalkan.
    """
    batch = await db.get(PurchaseBatch, batch_id)
    if batch is None:
        return False

    window = timedelta(minutes=settings.undo_window_minutes)
    if now_local() - batch.waktu_pembelian > window:
        return False
    if batch.status_batch != "baru":
        return False  # sudah ada transaksi lanjutan (mis. masuk lot/silo)

    await log_activity(
        db,
        table_name="purchase_batches",
        record_id=batch.id,
        action="DELETE",
        changed_by=user.id,
        old_value=batch.kode_batch,
        alasan="Dibatalkan operator dalam jendela undo",
    )
    await db.delete(batch)
    await db.commit()
    return True
