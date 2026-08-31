"""Barang keluar / dikirim: catat dispatch + kurangi stok. Harga OPSIONAL —
penetapan harga & proses jual penuh ada di modul Penjualan.

item_type: finished_goods (karung) / byproduct_curah (bekatul, kg) / pk_langsung
(PK dari Gudang 1, kg→karung CEIL÷50; HANYA staff/admin). Stok BOLEH minus (warning).
"""
from __future__ import annotations

from dataclasses import dataclass
from math import ceil

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import input_time
from app.models import MillingProcess, OutgoingItem, OutgoingRecord
from app.services.activity_log import log_activity
from app.services.codegen import next_outgoing_code
from app.services.transfer import pending_transfer_kg
from app.penggilingan.inventory.packaging import InventoryError, find_or_create_sku, get_standard
from app.penggilingan.inventory.finished_goods import (
    hitung_stok_bekatul,
    hitung_stok_finished_goods,
)


@dataclass
class OutgoingResult:
    kode: str
    label: str
    berat_kg: float
    jumlah_karung: int | None
    warning: str | None = None


async def _new_record(
    db: AsyncSession, *, user, nama_pembeli, metode, no_polisi, nama_ekspedisi,
    warehouse_id, now,
) -> OutgoingRecord:
    rec = OutgoingRecord(
        kode=await next_outgoing_code(db, now.date()),
        warehouse_id=warehouse_id, nama_pembeli=nama_pembeli, metode=metode,
        no_polisi=no_polisi, nama_ekspedisi=nama_ekspedisi,
        tanggal=now.date(), waktu=now, input_by=user.id,
    )
    db.add(rec)
    await db.flush()
    return rec


async def kirim_finished_goods(
    db: AsyncSession, *, user, kategori: str | None, grade: str | None = None,
    brand_nama: str | None = None, material_kode: str | None = None,
    ukuran: int | None = None, jumlah_karung: int | None = None,
    nama_pembeli: str | None = None, metode: str | None = None,
    no_polisi: str | None = None, nama_ekspedisi: str | None = None,
    harga_per_kg: float | None = None, tanggal=None, jam=None,
) -> OutgoingResult:
    if not kategori:
        raise InventoryError("Sebutkan jenis produk (beras/broken/menir/reject).")
    if not material_kode or not ukuran or not jumlah_karung:
        raise InventoryError(
            "Sebutkan jenis karung, ukuran, dan jumlah. Contoh: "
            "`kirim 50 karung premium Imbiss laminasi 25kg ke Toko Makmur`"
        )
    std_id = None
    if kategori == "beras_putih" and grade:
        std = await get_standard(db, grade)
        std_id = std.id if std else None
    sku = await find_or_create_sku(
        db, kategori=kategori, material_kode=material_kode, ukuran=int(ukuran),
        brand_nama=brand_nama,
    )
    berat = float(jumlah_karung) * int(ukuran)
    stok = await hitung_stok_finished_goods(db, sku.id, std_id)
    warning = None
    if jumlah_karung > stok["karung"]:
        warning = (
            f"⚠️ Stok kurang: tersedia {stok['karung']} karung, keluar "
            f"{jumlah_karung}. Stok jadi {stok['karung'] - jumlah_karung}."
        )
    now = input_time(tanggal, jam)
    rec = await _new_record(
        db, user=user, nama_pembeli=nama_pembeli, metode=metode, no_polisi=no_polisi,
        nama_ekspedisi=nama_ekspedisi, warehouse_id=None, now=now,
    )
    db.add(OutgoingItem(
        outgoing_record_id=rec.id, item_type="finished_goods",
        product_sku_id=sku.id, rice_quality_standard_id=std_id,
        jumlah_karung=int(jumlah_karung), berat_kg=berat,
        harga_per_kg=harga_per_kg,
        total_harga=(harga_per_kg * berat) if harga_per_kg is not None else None,
    ))
    await log_activity(
        db, table_name="outgoing_records", record_id=rec.id, action="INSERT",
        changed_by=user.id, new_value=f"{rec.kode} | {kategori}/{grade or '-'} x{jumlah_karung}",
    )
    await db.commit()
    label = kategori + (f" {grade}" if grade else "")
    return OutgoingResult(kode=rec.kode, label=label, berat_kg=berat,
                          jumlah_karung=int(jumlah_karung), warning=warning)


async def kirim_bekatul(
    db: AsyncSession, *, user, berat_kg: float | None, nama_pembeli: str | None = None,
    metode: str | None = None, no_polisi: str | None = None,
    nama_ekspedisi: str | None = None, harga_per_kg: float | None = None,
    tanggal=None, jam=None,
) -> OutgoingResult:
    if not berat_kg:
        raise InventoryError("Sebutkan berat bekatul yang dikirim (kg).")
    stok = await hitung_stok_bekatul(db)
    warning = None
    if float(berat_kg) > stok:
        warning = f"⚠️ Stok bekatul kurang: tersedia {stok:.0f} kg, keluar {float(berat_kg):.0f} kg."
    now = input_time(tanggal, jam)
    rec = await _new_record(
        db, user=user, nama_pembeli=nama_pembeli, metode=metode, no_polisi=no_polisi,
        nama_ekspedisi=nama_ekspedisi, warehouse_id=None, now=now,
    )
    db.add(OutgoingItem(
        outgoing_record_id=rec.id, item_type="byproduct_curah",
        jenis_byproduct="bekatul", berat_kg=berat_kg, harga_per_kg=harga_per_kg,
        total_harga=(harga_per_kg * float(berat_kg)) if harga_per_kg is not None else None,
    ))
    await log_activity(
        db, table_name="outgoing_records", record_id=rec.id, action="INSERT",
        changed_by=user.id, new_value=f"{rec.kode} | bekatul {berat_kg:.0f}kg",
    )
    await db.commit()
    return OutgoingResult(kode=rec.kode, label="bekatul (curah)", berat_kg=float(berat_kg),
                          jumlah_karung=None, warning=warning)


async def jual_pk_langsung(
    db: AsyncSession, *, user, kode_mil: str | None, berat_kg: float | None,
    nama_pembeli: str | None = None, metode: str | None = None,
    no_polisi: str | None = None, nama_ekspedisi: str | None = None,
    harga_per_kg: float | None = None, tanggal=None, jam=None,
) -> OutgoingResult:
    """Jual PK langsung dari Gudang 1 (HANYA staff/admin). Karung PK 50kg CEIL."""
    if user.role not in ("staff", "admin"):
        raise InventoryError("Penjualan PK langsung hanya bisa oleh Staff atau Admin.")
    if not kode_mil or not berat_kg:
        raise InventoryError("Sebutkan proses PK (MIL-...) & beratnya. Contoh: `jual PK langsung 2 ton dari MIL-...`")
    proc = (
        await db.execute(select(MillingProcess).where(MillingProcess.kode_proses == kode_mil))
    ).scalars().first()
    if proc is None:
        raise InventoryError(f"Proses {kode_mil} tidak ditemukan.")
    avail = await pending_transfer_kg(db, proc.id)
    warning = None
    if float(berat_kg) > avail:
        warning = f"⚠️ Stok PK {kode_mil} kurang: tersedia {avail:.0f} kg, jual {float(berat_kg):.0f} kg."
    karung = ceil(float(berat_kg) / 50)
    now = input_time(tanggal, jam)
    rec = await _new_record(
        db, user=user, nama_pembeli=nama_pembeli, metode=metode, no_polisi=no_polisi,
        nama_ekspedisi=nama_ekspedisi, warehouse_id=None, now=now,
    )
    db.add(OutgoingItem(
        outgoing_record_id=rec.id, item_type="pk_langsung",
        milling_process_id=proc.id, jumlah_karung=karung, berat_kg=berat_kg,
        harga_per_kg=harga_per_kg,
        total_harga=(harga_per_kg * float(berat_kg)) if harga_per_kg is not None else None,
    ))
    await log_activity(
        db, table_name="outgoing_records", record_id=rec.id, action="INSERT",
        changed_by=user.id, new_value=f"{rec.kode} | PK langsung {kode_mil} {berat_kg:.0f}kg ({karung} karung)",
    )
    await db.commit()
    return OutgoingResult(kode=rec.kode, label=f"PK langsung {kode_mil}",
                          berat_kg=float(berat_kg), jumlah_karung=karung, warning=warning)


def _kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


async def laporan_barang_keluar(db: AsyncSession) -> str:
    rows = (
        await db.execute(
            select(OutgoingRecord).order_by(OutgoingRecord.id.desc()).limit(10)
        )
    ).scalars().all()
    if not rows:
        return "🚚 Belum ada barang keluar."
    lines = ["🚚 Barang keluar terakhir:"]
    for r in rows:
        items = (
            await db.execute(
                select(OutgoingItem).where(OutgoingItem.outgoing_record_id == r.id)
            )
        ).scalars().all()
        isi = ", ".join(f"{it.item_type} {_kg(float(it.berat_kg))}" for it in items)
        pembeli = f" → {r.nama_pembeli}" if r.nama_pembeli else ""
        lines.append(f"• {r.kode}: {isi}{pembeli}")
    return "\n".join(lines)
