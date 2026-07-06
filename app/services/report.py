"""Laporan/ringkasan pembelian gabah untuk pertanyaan pengguna."""
from __future__ import annotations

from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import now_local

_HARI = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]
_BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt",
          "Nov", "Des"]


def _to_local(dt: datetime) -> datetime:
    """Konversi timestamp (UTC) ke zona waktu aplikasi (mis. Asia/Jakarta)."""
    return dt.astimezone(ZoneInfo(settings.app_timezone))


def _fmt_waktu(dt: datetime | None) -> str:
    """Format waktu ramah-manusia: 'Kamis, 03 Jul 2026 08:08'."""
    if dt is None:
        return "-"
    d = _to_local(dt)
    return f"{_HARI[d.weekday()]}, {d.day:02d} {_BULAN[d.month - 1]} {d.year} {d:%H:%M}"


def _fmt_tgl(d: date) -> str:
    """Label tanggal: 'Senin, 03 Jul 2026'."""
    return f"{_HARI[d.weekday()]}, {d.day:02d} {_BULAN[d.month - 1]} {d.year}"
from app.models import (
    DryingLot,
    DryingLotBatch,
    MillingProcess,
    MillingProcessVerification,
    MillingQcLog,
    PurchaseBatch,
    PurchaseBatchVerification,
    Supplier,
)

_LABELS = {
    "hari_ini": "hari ini",
    "kemarin": "kemarin",
    "minggu_ini": "minggu ini",
    "bulan_ini": "bulan ini",
    "semua": "keseluruhan",
}


def _range(periode: str) -> tuple[date | None, date | None]:
    """Kembalikan (start, end) inklusif. (None, None) berarti semua data."""
    today = now_local().date()
    if periode == "hari_ini":
        return today, today
    if periode == "kemarin":
        y = today - timedelta(days=1)
        return y, y
    if periode == "minggu_ini":
        return today - timedelta(days=today.weekday()), today  # Senin s.d. hari ini
    if periode == "bulan_ini":
        return today.replace(day=1), today
    return None, None  # semua


def _fmt_kg(kg: float) -> str:
    return f"{kg:,.0f} kg".replace(",", ".")


async def laporan_pembelian_gabah(
    db: AsyncSession, periode: str | None, tanggal: date | None = None
) -> str:
    """Teks laporan pembelian gabah untuk periode/tanggal (default hari_ini)."""
    if tanggal is not None:
        start = end = tanggal
        label = _fmt_tgl(tanggal)
    else:
        periode = periode if periode in _LABELS else "hari_ini"
        start, end = _range(periode)
        label = _LABELS[periode]

    stmt = select(PurchaseBatch, Supplier.nama_supplier).join(
        Supplier, PurchaseBatch.supplier_id == Supplier.id
    )
    if start is not None:
        stmt = stmt.where(
            PurchaseBatch.tanggal_pembelian >= start,
            PurchaseBatch.tanggal_pembelian <= end,
        )
    stmt = stmt.order_by(PurchaseBatch.id)
    rows = (await db.execute(stmt)).all()

    if not rows:
        return f"📊 Tidak ada pembelian gabah {label}."

    total_kg = 0.0
    basah_kg = 0.0
    kering_kg = 0.0
    unverified = 0
    per_supplier: dict[str, list[float]] = {}  # nama -> [kg, count]
    for batch, nama in rows:
        kg = float(batch.berat_total_kg)
        total_kg += kg
        if batch.kondisi_gabah == "kering":
            kering_kg += kg
        else:
            basah_kg += kg
        if batch.flag_unverified:
            unverified += 1
        agg = per_supplier.setdefault(nama, [0.0, 0])
        agg[0] += kg
        agg[1] += 1

    lines = [
        f"📊 Pembelian gabah {label}:",
        f"• Total: {_fmt_kg(total_kg)} dari {len(rows)} batch",
        f"• Basah: {_fmt_kg(basah_kg)} | Kering: {_fmt_kg(kering_kg)}",
    ]
    lines.append("• Per supplier:")
    for nama, (kg, cnt) in sorted(per_supplier.items(), key=lambda x: -x[1][0]):
        lines.append(f"   - {nama}: {_fmt_kg(kg)} ({cnt} batch)")
    if unverified:
        lines.append(f"⚠️ {unverified} batch belum diverifikasi harganya.")
    return "\n".join(lines)


# ─────────────────────────── Detail / telusur ───────────────────────────
def _rupiah(n: float | None) -> str:
    if n is None:
        return "-"
    return "Rp " + f"{n:,.0f}".replace(",", ".")


async def _resolve_batches(
    db: AsyncSession, *, supplier, periode, urutan, kondisi, terbaru, kode,
    tanggal=None,
):
    if kode:
        stmt = (
            select(PurchaseBatch, Supplier.nama_supplier)
            .join(Supplier, PurchaseBatch.supplier_id == Supplier.id)
            .where(PurchaseBatch.kode_batch == kode)
        )
        return (await db.execute(stmt)).all()
    if tanggal is not None:
        start = end = tanggal
    else:
        eff = _default_periode(
            periode, supplier=supplier, urutan=urutan, kondisi=kondisi, terbaru=terbaru
        )
        start, end = _range(eff)
    stmt = select(PurchaseBatch, Supplier.nama_supplier).join(
        Supplier, PurchaseBatch.supplier_id == Supplier.id
    )
    if start is not None:
        stmt = stmt.where(
            PurchaseBatch.tanggal_pembelian >= start,
            PurchaseBatch.tanggal_pembelian <= end,
        )
    if supplier:
        stmt = stmt.where(func.lower(Supplier.nama_supplier).like(f"%{supplier.lower()}%"))
    if kondisi in ("basah", "kering"):
        stmt = stmt.where(PurchaseBatch.kondisi_gabah == kondisi)
    rows = (await db.execute(stmt.order_by(PurchaseBatch.kode_batch))).all()
    if terbaru:
        return rows[-1:]
    if urutan:
        return [rows[urutan - 1]] if 1 <= urutan <= len(rows) else []
    return rows


async def resolve_batch_kode_ref(
    db: AsyncSession, *, urutan: int | None = None, supplier: str | None = None,
    terbaru: bool = False,
) -> list[str]:
    """Kode batch yang cocok dengan rujukan deskriptif (urutan/supplier/terbaru).

    Dipakai verifikasi harga saat operator menyebut 'gabah pertama' / 'dari
    catur' / 'yang terakhir' alih-alih kode. Kembalikan daftar kode; 1 = pasti,
    >1 = ambigu (handler menanyakan), 0 = tidak ketemu.
    """
    rows = await _resolve_batches(
        db, supplier=supplier, periode=None, urutan=urutan,
        kondisi=None, terbaru=terbaru, kode=None,
    )
    return [b.kode_batch for b, _ in rows]


async def _batch_detail_card(
    db: AsyncSession, batch: PurchaseBatch, nama: str, financial: bool = True
) -> str:
    verif = (
        await db.execute(
            select(PurchaseBatchVerification).where(
                PurchaseBatchVerification.purchase_batch_id == batch.id
            )
        )
    ).scalars().first()
    ka = f"{batch.kadar_air_awal_persen:g}%" if batch.kadar_air_awal_persen is not None else "-"
    lines = [
        f"🔎 {batch.kode_batch} — {nama}",
        f"• Masuk: {_fmt_waktu(batch.waktu_pembelian)}",
        f"• Berat: {_fmt_kg(float(batch.berat_total_kg))} | Kondisi: {batch.kondisi_gabah}",
        f"• Kadar air awal: {ka}",
        f"• Status: {batch.status_batch}",
    ]
    if not financial:
        lines.append("• Harga: 🔒 khusus staff/admin")
    elif verif and not batch.flag_unverified:
        lines.append(
            f"• Harga: {_rupiah(float(verif.harga_per_kg))}/kg "
            f"(total {_rupiah(float(verif.total_biaya))}) ✓"
        )
    else:
        lines.append("• Harga: ⏳ belum diverifikasi")
    return "\n".join(lines)


async def _latest_kode(db: AsyncSession, model, kode_col) -> str | None:
    return (
        await db.execute(select(kode_col).order_by(model.id.desc()).limit(1))
    ).scalar_one_or_none()


async def detail_query(
    db: AsyncSession,
    *,
    target: str | None,
    kode: str | None = None,
    supplier: str | None = None,
    periode: str | None = None,
    urutan: int | None = None,
    kondisi: str | None = None,
    terbaru: bool = False,
    tanggal: date | None = None,
    ctx_batch: str | None = None,
    ctx_lot: str | None = None,
    ctx_mil: str | None = None,
    financial: bool = True,
) -> str:
    from app.gudang1.services.drying import laporan_pengeringan
    from app.gudang1.services.milling import laporan_milling

    if kode:
        if kode.startswith("LOT"):
            return await laporan_pengeringan(db, kode)
        if kode.startswith("MIL"):
            return await laporan_milling(db, kode)
        rows = await _resolve_batches(
            db, supplier=None, periode=None, urutan=None, kondisi=None, terbaru=False, kode=kode
        )
        if not rows:
            return f"🔎 Batch {kode} tidak ditemukan."
        return await _batch_detail_card(db, *rows[0], financial=financial)

    if target == "lot":
        lk = None if terbaru else ctx_lot
        lk = lk or await _latest_kode(db, DryingLot, DryingLot.kode_lot)
        if not lk:
            return "Belum ada lot pengeringan."
        return await laporan_pengeringan(db, lk)

    if target == "milling":
        mk = None if terbaru else ctx_mil
        mk = mk or await _latest_kode(db, MillingProcess, MillingProcess.kode_proses)
        if not mk:
            return "Belum ada proses giling."
        return await laporan_milling(db, mk)

    # target batch (default)
    has_ref = any([supplier, urutan, kondisi, terbaru, tanggal])
    if not has_ref and ctx_batch:
        rows = await _resolve_batches(
            db, supplier=None, periode=None, urutan=None, kondisi=None, terbaru=False, kode=ctx_batch
        )
    else:
        rows = await _resolve_batches(
            db, supplier=supplier, periode=periode, urutan=urutan,
            kondisi=kondisi, terbaru=terbaru, kode=None, tanggal=tanggal,
        )
    if not rows:
        return "🔎 Tidak ada gabah yang cocok dengan kriteria itu."
    cards = [await _batch_detail_card(db, b, nama, financial) for b, nama in rows[:5]]
    out = "\n\n".join(cards)
    if len(rows) > 5:
        out += f"\n\n…dan {len(rows) - 5} lagi."
    return out


# ─────────────────────────── Status berjalan ───────────────────────────
async def status_gudang1(db: AsyncSession) -> str:
    """Gabungan semua proses yang sedang berlangsung di Gudang 1."""
    from app.gudang1.services.drying import dryer_load_kg, laporan_pengeringan
    from app.gudang1.services.milling import laporan_milling
    from app.gudang1.services.silo import laporan_silo
    from app.models import SiloStorage
    from app.services.transfer import laporan_pk_siap_transfer

    # Milling berjalan?
    mill_running = (
        await db.execute(
            select(func.count())
            .select_from(MillingProcess)
            .where(MillingProcess.status == "proses")
        )
    ).scalar_one()
    # Gabah di dryer (menunggu/dikeringkan/didinginkan)?
    in_dryer = await dryer_load_kg(db)
    # Isi silo (lot hasil pengeringan ATAU kering menunggu)?
    silo_isi = (
        await db.execute(
            select(func.count()).select_from(SiloStorage)
            .where(SiloStorage.status == "terisi")
        )
    ).scalar_one()

    if not mill_running and in_dryer <= 0 and not silo_isi:
        return (
            "📍 Gudang 1: tidak ada gabah/proses saat ini.\n"
            "(Dryer & silo kosong, tak ada giling aktif.)"
        )

    parts = ["📍 Status Gudang 1:\n"]
    if in_dryer > 0:
        parts.append(await laporan_pengeringan(db))
    if silo_isi:
        parts.append(await laporan_silo(db))
    if mill_running:
        parts.append(await laporan_milling(db))
    # Info tambahan PK menunggu transfer (bila ada).
    trf = await laporan_pk_siap_transfer(db)
    if "Tidak ada" not in trf:
        parts.append(trf)
    return "\n\n".join(parts)


# ─────────────────────────── Pending verifikasi ───────────────────────────
async def pending_verifikasi(db: AsyncSession) -> str:
    """Daftar yang masih perlu diverifikasi staff/admin."""
    lines: list[str] = []

    # 1. Harga gabah belum diverifikasi.
    batches = (
        await db.execute(
            select(PurchaseBatch, Supplier.nama_supplier)
            .join(Supplier, PurchaseBatch.supplier_id == Supplier.id)
            .where(PurchaseBatch.flag_unverified.is_(True))
            .order_by(PurchaseBatch.kode_batch)
        )
    ).all()
    if batches:
        lines.append(f"💰 Harga gabah belum diverifikasi ({len(batches)}):")
        for b, nama in batches[:10]:
            lines.append(f"• {b.kode_batch} — {nama}, {_fmt_kg(float(b.berat_total_kg))}")

    # 2. Output PK milling (selesai) belum diverifikasi.
    verified_ids = select(MillingProcessVerification.milling_process_id)
    mills = (
        await db.execute(
            select(MillingProcess)
            .where(
                MillingProcess.status == "selesai",
                MillingProcess.id.not_in(verified_ids),
            )
            .order_by(MillingProcess.kode_proses)
        )
    ).scalars().all()
    if mills:
        lines.append(f"\n⚙️ Output PK belum diverifikasi ({len(mills)}):")
        for m in mills[:10]:
            lines.append(f"• {m.kode_proses}")

    # 3. Milling (selesai) belum ada QC.
    qc_ids = select(MillingQcLog.milling_process_id).distinct()
    no_qc = (
        await db.execute(
            select(MillingProcess.kode_proses)
            .where(
                MillingProcess.status == "selesai",
                MillingProcess.id.not_in(qc_ids),
            )
            .order_by(MillingProcess.kode_proses)
        )
    ).scalars().all()
    if no_qc:
        lines.append(f"\n🔬 Milling belum ada QC ({len(no_qc)}):")
        for k in no_qc[:10]:
            lines.append(f"• {k}")

    if not lines:
        return "✅ Tidak ada yang perlu diverifikasi. Semua beres."
    return "📋 Perlu ditindaklanjuti:\n" + "\n".join(lines)


# ─────────────────────────── Cari kode ───────────────────────────
def _default_periode(periode: str | None, *, supplier: str | None, urutan: int | None,
                     kondisi: str | None, terbaru: bool = False) -> str:
    if periode in _LABELS:
        return periode
    if terbaru:
        return "semua"  # 'paling terakhir/terbaru' -> cari lintas seluruh waktu
    if urutan or kondisi:
        return "hari_ini"
    if supplier:
        return "semua"
    return "hari_ini"


async def _lot_supplier_names(db: AsyncSession, lot_id: int) -> list[str]:
    stmt = (
        select(Supplier.nama_supplier)
        .select_from(DryingLotBatch)
        .join(PurchaseBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
        .join(Supplier, PurchaseBatch.supplier_id == Supplier.id)
        .where(DryingLotBatch.drying_lot_id == lot_id)
        .distinct()
    )
    return list((await db.execute(stmt)).scalars().all())


async def cari_kode(
    db: AsyncSession,
    *,
    target: str | None,
    supplier: str | None = None,
    periode: str | None = None,
    urutan: int | None = None,
    kondisi: str | None = None,
    terbaru: bool = False,
    tanggal: date | None = None,
) -> str:
    """Cari kode batch/lot berdasarkan ciri (supplier/hari/urutan/kondisi/terbaru)."""
    if tanggal is not None:
        start = end = tanggal
        label = _fmt_tgl(tanggal)
    else:
        eff = _default_periode(
            periode, supplier=supplier, urutan=urutan, kondisi=kondisi, terbaru=terbaru
        )
        label = _LABELS[eff]
        start, end = _range(eff)

    if target == "lot":
        stmt = select(DryingLot)
        if start is not None:
            stmt = stmt.where(
                func.date(DryingLot.created_at) >= start,
                func.date(DryingLot.created_at) <= end,
            )
        if supplier:
            sub = (
                select(DryingLotBatch.drying_lot_id)
                .join(PurchaseBatch, DryingLotBatch.purchase_batch_id == PurchaseBatch.id)
                .join(Supplier, PurchaseBatch.supplier_id == Supplier.id)
                .where(func.lower(Supplier.nama_supplier).like(f"%{supplier.lower()}%"))
            )
            stmt = stmt.where(DryingLot.id.in_(sub))
        lots = list((await db.execute(stmt.order_by(DryingLot.kode_lot))).scalars().all())
        ket = f"{label}" + (f", supplier {supplier}" if supplier else "")
        if not lots:
            return f"🔎 Tidak ada lot pengeringan yang cocok ({ket})."
        if terbaru:
            lots = lots[-1:]
        elif urutan:
            if not 1 <= urutan <= len(lots):
                return f"🔎 Lot ke-{urutan} tidak ada (hanya {len(lots)} cocok, {ket})."
            lots = [lots[urutan - 1]]
        lines = [f"🔎 Kode lot ({ket}):"]
        for lot in lots[:10]:
            sups = ", ".join(await _lot_supplier_names(db, lot.id)) or "-"
            lines.append(f"• {lot.kode_lot} — {lot.status}, dari {sups}")
        if len(lots) > 10:
            lines.append(f"…dan {len(lots) - 10} lot lain.")
        return "\n".join(lines)

    # target batch (default)
    stmt = select(PurchaseBatch, Supplier.nama_supplier).join(
        Supplier, PurchaseBatch.supplier_id == Supplier.id
    )
    if start is not None:
        stmt = stmt.where(
            PurchaseBatch.tanggal_pembelian >= start,
            PurchaseBatch.tanggal_pembelian <= end,
        )
    if supplier:
        stmt = stmt.where(func.lower(Supplier.nama_supplier).like(f"%{supplier.lower()}%"))
    if kondisi in ("basah", "kering"):
        stmt = stmt.where(PurchaseBatch.kondisi_gabah == kondisi)
    rows = (await db.execute(stmt.order_by(PurchaseBatch.kode_batch))).all()

    ket_parts = [label]
    if supplier:
        ket_parts.append(f"supplier {supplier}")
    if kondisi:
        ket_parts.append(kondisi)
    ket = ", ".join(ket_parts)
    if not rows:
        return f"🔎 Tidak ada batch yang cocok ({ket})."
    if terbaru:
        rows = rows[-1:]
    elif urutan:
        if not 1 <= urutan <= len(rows):
            return f"🔎 Batch ke-{urutan} tidak ada (hanya {len(rows)} cocok, {ket})."
        rows = [rows[urutan - 1]]
    lines = [f"🔎 Kode batch ({ket}):"]
    for batch, nama in rows[:10]:
        flag = " · belum diverifikasi" if batch.flag_unverified else ""
        lines.append(
            f"• {batch.kode_batch} — {nama}, {_fmt_kg(float(batch.berat_total_kg))}, "
            f"{batch.kondisi_gabah}{flag}"
        )
    if len(rows) > 10:
        lines.append(f"…dan {len(rows) - 10} batch lain.")
    return "\n".join(lines)


# ─────────────────── Analitik jam kedatangan gabah ───────────────────
async def insight_jam_kedatangan(
    db: AsyncSession, *, supplier: str | None = None, periode: str | None = None,
    tanggal: date | None = None,
) -> str:
    """Analisa pola jam kedatangan gabah (insight untuk pimpinan/operasional).

    Default lintas seluruh waktu agar polanya bermakna. Bila `tanggal`
    diberikan, batasi ke satu hari itu.
    """
    if tanggal is not None:
        start = end = tanggal
        ket_periode = _fmt_tgl(tanggal)
    else:
        eff = periode if periode in _LABELS else "semua"
        start, end = _range(eff)
        ket_periode = _LABELS[eff]
    stmt = select(PurchaseBatch.waktu_pembelian).join(
        Supplier, PurchaseBatch.supplier_id == Supplier.id
    )
    if start is not None:
        stmt = stmt.where(
            PurchaseBatch.tanggal_pembelian >= start,
            PurchaseBatch.tanggal_pembelian <= end,
        )
    if supplier:
        stmt = stmt.where(func.lower(Supplier.nama_supplier).like(f"%{supplier.lower()}%"))
    waktu = [w for w in (await db.execute(stmt)).scalars().all() if w is not None]

    ket = ket_periode + (f" · supplier {supplier}" if supplier else "")
    if not waktu:
        return f"📊 Belum ada data jam kedatangan ({ket})."

    times = [_to_local(w) for w in waktu]
    n = len(times)
    mins = [t.hour * 60 + t.minute for t in times]  # menit sejak 00:00
    earliest = min(times, key=lambda t: (t.hour, t.minute))
    latest = max(times, key=lambda t: (t.hour, t.minute))
    avg_m = sum(mins) / n
    ah, am = int(avg_m // 60), int(avg_m % 60)

    # Histogram per jam.
    buckets: dict[int, int] = {}
    for t in times:
        buckets[t.hour] = buckets.get(t.hour, 0) + 1
    busiest_h = max(buckets, key=lambda h: buckets[h])

    lines = [
        f"📊 Pola jam kedatangan gabah ({ket} · {n} batch):",
        f"• Paling pagi {earliest:%H:%M} · paling siang {latest:%H:%M}",
        f"• Rata-rata masuk ~{ah:02d}:{am:02d}",
        f"• Jam tersibuk {busiest_h:02d}:00–{busiest_h + 1:02d}:00 ({buckets[busiest_h]} batch)",
    ]
    if n >= 2:
        lines.append("• Sebaran per jam:")
        for h in sorted(buckets):
            lines.append(f"   {h:02d}:00  {'█' * buckets[h]} {buckets[h]}")
    return "\n".join(lines)
