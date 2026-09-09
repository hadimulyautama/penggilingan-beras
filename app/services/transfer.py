"""Logika bisnis transfer internal Gudang 1 -> Gudang 2 + HPP snapshot PK."""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import now_local
from app.models import (
    InternalTransfer,
    MillingProcess,
    MillingProcessVerification,
    MillingProgressLog,
)
from app.services.activity_log import log_activity
from app.services.codegen import next_transfer_code
from app.services.costing import production_cost
from app.penggilingan.gudang1.services.milling import pk_jenis

_LOKASI = {"silo_a": "Silo A", "silo_b": "Silo B", "ditumpuk": "tumpukan"}


class TransferError(Exception):
    """Kesalahan transfer dengan pesan siap-tampil (args[0])."""


async def hpp_per_kg_pk(db: AsyncSession, proc: MillingProcess) -> float | None:
    """HPP per kg PK (hasil giling) = biaya PRODUKSI PENUH ÷ output PK terverifikasi.

    Biaya penuh = bahan gabah + biaya giling (bongkar/pengeringan/operator/tenaga/listrik/
    rubber), via production_cost().total_penuh. Menempel ke PK saat masuk silo → mengalir
    lewat wavg silo ke HPP beras. None bila belum lengkap (gabah belum diverifikasi / output
    belum ada). CATATAN: PK BELI LUAR tak melewati fungsi ini — HPP-nya = harga beli."""
    verif = (
        await db.execute(
            select(MillingProcessVerification).where(
                MillingProcessVerification.milling_process_id == proc.id
            )
        )
    ).scalars().first()
    if verif is None or not verif.berat_output_final_kg:
        return None
    bd = await production_cost(db, proc)
    if bd is None or bd.total_penuh is None:  # bahan_baku None → gabah belum diverifikasi
        return None
    output = float(verif.berat_output_final_kg)
    return bd.total_penuh / output if output else None


#: Berapa PK dihasilkan sebuah giling — SATU jawaban untuk seluruh aplikasi.
#:
#: Dulu ditulis ulang di sini, membaca progres operator saja. Dua jawaban untuk
#: satu pertanyaan akan berselisih cepat atau lambat, dan yang salah adalah
#: yang lebih jarang dibaca — di sini artinya PK terverifikasi yang tak bisa
#: dikirim ke Gudang 2 karena stoknya terbaca nol.
from app.penggilingan.gudang1.services.milling import _produced_pk  # noqa: E402


async def _transferred_pk(db: AsyncSession, proc_id: int) -> float:
    r = (
        await db.execute(
            select(func.coalesce(func.sum(InternalTransfer.berat_kg), 0)).where(
                InternalTransfer.milling_process_id == proc_id,
                InternalTransfer.status == "terkirim",
            )
        )
    ).scalar_one()
    return float(r)


async def _sold_pk_langsung(db: AsyncSession, proc_id: int) -> float:
    """PK yang sudah DIJUAL LANGSUNG dari Gudang 1 (barang keluar pk_langsung)."""
    from app.models import OutgoingItem
    r = (
        await db.execute(
            select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0)).where(
                OutgoingItem.item_type == "pk_langsung",
                OutgoingItem.milling_process_id == proc_id,
            )
        )
    ).scalar_one()
    return float(r)


async def pending_transfer_kg(db: AsyncSession, proc_id: int) -> float:
    """PK tersedia (stok) = produksi − yang ditransfer − yang dijual langsung."""
    return max(
        await _produced_pk(db, proc_id)
        - await _transferred_pk(db, proc_id)
        - await _sold_pk_langsung(db, proc_id),
        0.0,
    )


@dataclass
class TransferResult:
    transfer: InternalTransfer
    kode_proses: str
    lokasi_label: str
    hpp_per_kg: float | None
    jenis: str | None = None  # KS / KL / MIX


async def create_internal_transfer(
    db: AsyncSession, *, user, kode_proses: str, lokasi_tujuan: str,
    berat: float | None = None,
) -> TransferResult:
    """Kirim PK dari sebuah milling ke Gudang 2. Mengurangi stok siap kirim.

    `berat` opsional: bila tidak disebut, kirim SEMUA stok yang tersedia.
    """
    if lokasi_tujuan not in _LOKASI:
        raise TransferError("Tujuan harus: Silo A, Silo B, atau ditumpuk.")
    proc = (
        await db.execute(
            select(MillingProcess).where(MillingProcess.kode_proses == kode_proses)
        )
    ).scalars().first()
    if proc is None:
        raise TransferError(f"Proses {kode_proses} tidak ditemukan.")

    tersedia = await pending_transfer_kg(db, proc.id)
    if tersedia <= 0:
        raise TransferError(
            f"Tidak ada stok PK dari {kode_proses} untuk dikirim "
            "(hasil giling belum dicatat, atau semua sudah terkirim)."
        )
    kirim = tersedia if berat is None else min(float(berat), tersedia)

    hpp = await hpp_per_kg_pk(db, proc)
    jenis = await pk_jenis(db, proc)
    now = now_local()
    transfer = InternalTransfer(
        kode_transfer=await next_transfer_code(db),
        milling_process_id=proc.id,
        drying_lot_id=proc.drying_lot_id,
        berat_kg=kirim,
        lokasi_tujuan=lokasi_tujuan,
        hpp_per_kg=hpp,
        waktu=now,
        created_by=user.id,
        status="terkirim",
    )
    db.add(transfer)
    await db.flush()
    await log_activity(
        db, table_name="internal_transfers", record_id=transfer.id, action="INSERT",
        changed_by=user.id,
        new_value=f"{transfer.kode_transfer} | {kirim:.0f}kg -> {_LOKASI[lokasi_tujuan]} | hpp={hpp}",
    )
    # PK LANGSUNG masuk stok Gudang 2 — staff/admin sudah menentukan tujuan saat
    # kirim, jadi tak perlu langkah 'terima' terpisah oleh operator G2.
    # (_add_intake menjalankan guard kapasitas tumpukan lalu commit.)
    from app.penggilingan.gudang2.service import Gudang2Error, _add_intake
    try:
        await _add_intake(
            db, user=user, sumber_tipe="transfer_internal", tujuan=lokasi_tujuan,
            berat_kg=kirim, hpp_per_kg=hpp, tanggal=None, jam=None,
            internal_transfer_id=transfer.id,
        )
    except Gudang2Error as e:  # mis. tumpukan G2 penuh → batalkan transfer
        raise TransferError(e.args[0] if e.args else "Gagal memasukkan PK ke Gudang 2.")
    await db.refresh(transfer)
    return TransferResult(
        transfer=transfer, kode_proses=kode_proses,
        lokasi_label=_LOKASI[lokasi_tujuan], hpp_per_kg=hpp, jenis=jenis,
    )


# ─────────────────────────── Laporan ───────────────────────────
def _kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


def _rp(n: float | None) -> str:
    return "Rp " + f"{n:,.0f}".replace(",", ".") if n is not None else "-"


async def laporan_pk_siap_transfer(db: AsyncSession) -> str:
    """PK yang menumpuk di Gudang 1 — dan karena itu juga yang siap dikirim.

    Dua sebutan untuk satu tumpukan yang sama. "Menumpuk" adalah tempatnya,
    "siap kirim" adalah apa yang bisa dilakukan padanya; keduanya tak pernah
    berbeda isinya, karena PK meninggalkan lantai Gudang 1 tepat pada saat
    transfernya dicatat.

    Diurut yang PALING LAMA MENUNGGU lebih dulu. Tumpukan yang cuma disebut
    jumlahnya tak bisa ditindaklanjuti: yang perlu diputuskan adalah lot mana
    yang berangkat duluan, dan jawabannya hampir selalu yang paling lama
    menunggu.
    """
    procs = (
        await db.execute(select(MillingProcess).order_by(MillingProcess.kode_proses))
    ).scalars().all()
    items: list[tuple[str, str | None, float, float | None]] = []
    for p in procs:
        avail = await pending_transfer_kg(db, p.id)
        if avail > 0:
            sejak = p.waktu_selesai or p.waktu_mulai
            hari = ((now_local() - sejak).total_seconds() / 86400) if sejak else None
            items.append((p.kode_proses, await pk_jenis(db, p), avail, hari))
    if not items:
        return "🚚 Lantai PK Gudang 1 kosong — tidak ada yang menunggu dikirim."
    items.sort(key=lambda it: (it[3] is None, -(it[3] or 0)))

    total = sum(a for _, _, a, _ in items)
    sub: dict[str, float] = {}
    for _, jenis, a, _ in items:
        sub[jenis or "?"] = sub.get(jenis or "?", 0.0) + a
    ringkas = " · ".join(f"{j} {_kg(v)}" for j, v in sorted(sub.items()))
    cap = settings.g1_pk_tumpukan_maks_kg
    lines = [
        f"🚚 PK menumpuk di Gudang 1: {_kg(total)}"
        + (f" / maks {cap / 1000:g} ton" if cap else "")
        + f"  ({ringkas})"
    ]
    for kode, jenis, a, hari in items:
        umur = f" · menunggu {hari:.0f} hari" if hari is not None else ""
        lines.append(f"• {jenis or '-'} dari {kode}: {_kg(a)}{umur}")
    if cap and total > cap:
        lines.append(
            f"⚠️ Melewati batas lantai {cap / 1000:g} ton — kirim ke gudang penyosohan."
        )
    return "\n".join(lines)


async def laporan_transfer(db: AsyncSession, financial: bool = True) -> str:
    """Riwayat transfer internal (terbaru dulu). HPP hanya untuk staff/admin."""
    rows = (
        await db.execute(
            select(InternalTransfer, MillingProcess)
            .join(MillingProcess, MillingProcess.id == InternalTransfer.milling_process_id)
            .order_by(InternalTransfer.id.desc())
            .limit(10)
        )
    ).all()
    if not rows:
        return "🚚 Belum ada transfer ke Gudang 2."
    lines = ["🚚 Transfer terakhir ke Gudang 2:"]
    for t, proc in rows:
        hpp = (
            f" · HPP {_rp(float(t.hpp_per_kg))}/kg"
            if financial and t.hpp_per_kg is not None
            else ""
        )
        jenis = await pk_jenis(db, proc)
        jlbl = f"{jenis} " if jenis else ""
        lines.append(
            f"• {t.kode_transfer}: {jlbl}{_kg(float(t.berat_kg))} dari {proc.kode_proses} "
            f"→ {_LOKASI.get(t.lokasi_tujuan, t.lokasi_tujuan)}{hpp}"
        )
    return "\n".join(lines)
