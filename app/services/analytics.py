"""Lapisan analitik strategis — supplier scorecard & tren HPP.

Catatan atribusi: satu proses milling memakai satu LOT (bisa banyak batch,
mungkin beda supplier). Rendemen & biaya dialokasikan ke supplier secara
PROPORSIONAL berdasarkan bobot (kg) tiap batch dalam lot.
"""
from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import (
    Dryer,
    DryingLotBatch,
    MillingProcess,
    MillingProcessVerification,
    MillingProgressLog,
    MillingQcLog,
    PurchaseBatch,
    PurchaseBatchVerification,
    Supplier,
)
from app.services.costing import production_cost

_BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt",
          "Nov", "Des"]


def _rp(n: float | None) -> str:
    return "Rp " + f"{n:,.0f}".replace(",", ".") if n is not None else "-"


def _ton(kg: float) -> str:
    return f"{kg / 1000:,.1f} ton".replace(",", ".")


async def _proc_pk_output(db: AsyncSession, proc: MillingProcess) -> float | None:
    """PK output sebuah proses: berat terverifikasi > progress terakhir."""
    v = (
        await db.execute(
            select(MillingProcessVerification.berat_output_final_kg).where(
                MillingProcessVerification.milling_process_id == proc.id
            )
        )
    ).scalars().first()
    if v:
        return float(v)
    p = (
        await db.execute(
            select(MillingProgressLog.berat_kumulatif_kg)
            .where(MillingProgressLog.milling_process_id == proc.id)
            .order_by(MillingProgressLog.waktu_update.desc())
            .limit(1)
        )
    ).scalars().first()
    return float(p) if p else None


async def _proc_batches(db: AsyncSession, proc: MillingProcess):
    """Daftar (batch, harga_per_kg|None) sumber sebuah proses.

    Membaca `milling.sumber_batch` — penyelesai yang sama dengan HPP. Dulu
    modul ini menjawabnya sendiri dari penunjuk tunggal `MillingProcess`, dan
    dua jawaban untuk satu pertanyaan cepat atau lambat berbeda: rapor supplier
    akan memuji atau menyalahkan orang berdasarkan gabah yang tidak seluruhnya.
    """
    from app.penggilingan.gudang1.services.milling import sumber_batch

    return [(b, harga) for b, harga, _ in await sumber_batch(db, proc)]


async def supplier_scorecard_data(db: AsyncSession) -> dict:
    """Data terstruktur scorecard supplier (dipakai teks bot & dashboard).

    Kembalikan {"diproduksi": [...], "belum": [...]}, tiap item punya field
    turunan: harga_per_kg, rendemen (%), hpp_pk. `diproduksi` diperingkat dari
    HPP/kg PK terendah.
    """
    # ── 1. Pengadaan per supplier (semua batch) ──
    prow = (
        await db.execute(
            select(
                Supplier.id, Supplier.nama_supplier,
                func.count(PurchaseBatch.id),
                func.coalesce(func.sum(PurchaseBatch.berat_total_kg), 0),
                func.avg(PurchaseBatch.kadar_air_awal_persen),
            )
            .join(PurchaseBatch, PurchaseBatch.supplier_id == Supplier.id)
            .group_by(Supplier.id, Supplier.nama_supplier)
        )
    ).all()
    if not prow:
        return {"diproduksi": [], "belum": []}

    agg: dict[int, dict] = {}
    for sid, nama, nbatch, kg, ka in prow:
        agg[sid] = {
            "nama": nama, "n_batch": int(nbatch), "kg": float(kg),
            "kadar_air": float(ka) if ka is not None else None,
            "biaya_verif": 0.0, "kg_verif": 0.0,
            "pk_alloc": 0.0, "gabah_milled": 0.0,
            "cost_milled": 0.0, "pk_for_hpp": 0.0,
        }

    vrow = (
        await db.execute(
            select(
                PurchaseBatch.supplier_id,
                func.coalesce(func.sum(PurchaseBatch.berat_total_kg * PurchaseBatchVerification.harga_per_kg), 0),
                func.coalesce(func.sum(PurchaseBatch.berat_total_kg), 0),
            )
            .join(PurchaseBatchVerification, PurchaseBatchVerification.purchase_batch_id == PurchaseBatch.id)
            .where(PurchaseBatchVerification.harga_per_kg.isnot(None))
            .group_by(PurchaseBatch.supplier_id)
        )
    ).all()
    for sid, biaya, kgv in vrow:
        if sid in agg:
            agg[sid]["biaya_verif"] = float(biaya)
            agg[sid]["kg_verif"] = float(kgv)

    procs = (
        await db.execute(select(MillingProcess).where(MillingProcess.status == "selesai"))
    ).scalars().all()
    for proc in procs:
        bd = await production_cost(db, proc)
        if bd is None:
            continue
        output = bd.pk_output
        batches = await _proc_batches(db, proc)
        total_kg = sum(float(b.berat_total_kg or 0) for b, _ in batches)
        if total_kg <= 0:
            continue
        total_cost = bd.total_penuh
        for b, _harga in batches:
            sid = b.supplier_id
            if sid not in agg:
                continue
            share = float(b.berat_total_kg or 0) / total_kg
            agg[sid]["pk_alloc"] += output * share
            agg[sid]["gabah_milled"] += float(b.berat_total_kg or 0)
            if total_cost is not None:
                agg[sid]["cost_milled"] += total_cost * share
                agg[sid]["pk_for_hpp"] += output * share

    for a in agg.values():
        a["harga_per_kg"] = a["biaya_verif"] / a["kg_verif"] if a["kg_verif"] > 0 else None
        a["rendemen"] = a["pk_alloc"] / a["gabah_milled"] * 100 if a["gabah_milled"] > 0 else None
        a["hpp_pk"] = a["cost_milled"] / a["pk_for_hpp"] if a["pk_for_hpp"] > 0 else None

    rows = list(agg.values())
    diproduksi = [a for a in rows if a["pk_alloc"] > 0]
    belum = [a for a in rows if a["pk_alloc"] <= 0]
    diproduksi.sort(key=lambda a: (a["hpp_pk"] is None, a["hpp_pk"] or 0))
    return {"diproduksi": diproduksi, "belum": belum}


async def supplier_scorecard(db: AsyncSession) -> str:
    """Skor per supplier: pasok, harga, rendemen, kualitas, HPP/kg PK.

    Diperingkat dari HPP/kg PK terendah (paling hemat = paling menguntungkan
    pada harga jual PK yang sama).
    """
    data = await supplier_scorecard_data(db)
    diproduksi, belum = data["diproduksi"], data["belum"]
    if not diproduksi and not belum:
        return "📊 Belum ada data pembelian untuk dianalisa."

    lines = ["📊 *Supplier Scorecard* (keseluruhan)"]
    medali = ["🥇", "🥈", "🥉"]
    for i, a in enumerate(diproduksi):
        tag = medali[i] if i < len(medali) else "•"
        ka = f"{a['kadar_air']:.0f}%" if a["kadar_air"] is not None else "-"
        h = a["hpp_pk"]
        lines.append(
            f"\n{tag} *{a['nama']}* — HPP PK {_rp(h)}/kg"
            + ("  ⭐ terhemat" if i == 0 and h is not None else "")
        )
        lines.append(
            f"• Pasok {_ton(a['kg'])} ({a['n_batch']} batch) · harga ~{_rp(a['harga_per_kg'])}/kg"
        )
        lines.append(
            f"• Rendemen PK {a['rendemen']:.1f}% · kadar air masuk {ka}"
            if a["rendemen"] is not None else f"• kadar air masuk {ka}"
        )
    if belum:
        lines.append("\n_Belum ada produksi PK (hanya pengadaan):_")
        for a in belum:
            lines.append(
                f"• {a['nama']}: {_ton(a['kg'])} ({a['n_batch']} batch) "
                f"· ~{_rp(a['harga_per_kg'])}/kg"
            )
    lines.append(
        "\n_Peringkat = HPP/kg PK terendah (harga + rendemen). Profit riil butuh "
        "harga jual PK._"
    )
    return "\n".join(lines)


async def hpp_trend(db: AsyncSession) -> str:
    """Tren HPP per kg PK per bulan (rata-rata tertimbang output)."""
    procs = (
        await db.execute(
            select(MillingProcess)
            .where(MillingProcess.status == "selesai", MillingProcess.waktu_selesai.isnot(None))
            .order_by(MillingProcess.waktu_selesai)
        )
    ).scalars().all()

    per_bulan: dict[tuple[int, int], list[float]] = {}  # (thn,bln) -> [cost, output]
    for proc in procs:
        v = (
            await db.execute(
                select(MillingProcessVerification.berat_output_final_kg).where(
                    MillingProcessVerification.milling_process_id == proc.id
                )
            )
        ).scalars().first()
        if not v:
            continue  # output belum terverifikasi
        bd = await production_cost(db, proc)
        if bd is None or bd.total_penuh is None:
            continue  # biaya bahan baku belum lengkap
        key = (proc.waktu_selesai.year, proc.waktu_selesai.month)
        acc = per_bulan.setdefault(key, [0.0, 0.0])
        acc[0] += bd.total_penuh
        acc[1] += bd.pk_output

    if not per_bulan:
        return (
            "📉 Belum ada data HPP. Butuh proses giling yang SELESAI dengan "
            "output PK terverifikasi dan harga gabah terverifikasi."
        )
    lines = ["📉 *Tren HPP penuh per kg PK* (per bulan):"]
    prev = None
    for (thn, bln) in sorted(per_bulan):
        cost, out = per_bulan[(thn, bln)]
        hpp = cost / out if out else 0
        arah = ""
        if prev is not None:
            arah = " 🔺" if hpp > prev else (" 🔻" if hpp < prev else " ➡️")
        lines.append(f"• {_BULAN[bln - 1]} {thn}: {_rp(hpp)}/kg (PK {_ton(out)}){arah}")
        prev = hpp
    return "\n".join(lines)


async def biaya_produksi_detail(db: AsyncSession, kode_proses: str | None = None) -> str:
    """Rincian biaya produksi + HPP penuh sebuah proses (default: terakhir)."""
    q = select(MillingProcess)
    if kode_proses:
        q = q.where(MillingProcess.kode_proses == kode_proses)
    else:
        q = q.where(MillingProcess.status == "selesai").order_by(MillingProcess.id.desc())
    proc = (await db.execute(q.limit(1))).scalars().first()
    if proc is None:
        return "Proses giling tidak ditemukan." if kode_proses else "Belum ada proses giling selesai."
    bd = await production_cost(db, proc)
    if bd is None:
        return f"{proc.kode_proses}: output PK belum ada — biaya belum bisa dihitung."

    rend = bd.pk_output / bd.kg_gabah * 100 if bd.kg_gabah else 0
    ker = f" ({bd.kondisi}{'/dikeringkan' if bd.dried else '/langsung silo'})" if bd.kondisi else ""
    lines = [
        f"💵 *Rincian biaya {proc.kode_proses}*",
        f"Gabah {_ton(bd.kg_gabah)}{ker} → PK {_ton(bd.pk_output)} (rendemen {rend:.1f}%)",
        f"• Bahan baku (gabah): {_rp(bd.bahan_baku)}",
        f"• Bongkar: {_rp(bd.bongkar)}",
        f"• Pengeringan: {_rp(bd.pengeringan)}",
        f"• Operator: {_rp(bd.operator)}",
        f"• Tenaga milling: {_rp(bd.tenaga_milling)}",
        f"• Rubber roll: {_rp(bd.rubber_roll)}",
    ]
    if bd.listrik:
        lines.append(f"• Listrik/mesin: {_rp(bd.listrik)}")
    lines.append(f"• _Subtotal operasional: {_rp(bd.operasional)}_")
    if bd.total_penuh is not None:
        hpp_bahan = bd.bahan_baku / bd.pk_output if bd.pk_output else 0
        hpp_op = bd.operasional / bd.pk_output if bd.pk_output else 0
        lines.append(f"*Total: {_rp(bd.total_penuh)}*")
        lines.append(
            f"*HPP penuh: {_rp(bd.hpp_penuh)}/kg PK* "
            f"(bahan baku {_rp(hpp_bahan)} + operasional {_rp(hpp_op)})"
        )
    else:
        lines.append(
            f"_Operasional {_rp(bd.operasional / bd.pk_output)}/kg PK. "
            "Bahan baku belum diverifikasi → HPP penuh belum bisa dihitung._"
        )
    return "\n".join(lines)


def simulasi_hpp(
    harga_gabah: float | None, rendemen_persen: float | None, *,
    kondisi: str = "basah", langsung_silo: bool = False,
    berat_bahan: float | None = None, berat_hasil: float | None = None,
) -> str:
    """What-if HPP dari harga gabah & rendemen (pakai tarif biaya terkini).

    Rendemen bisa diberikan langsung (persen) ATAU dihitung dari tonase bahan &
    hasil (berat_hasil / berat_bahan). Tak butuh batch/data nyata."""
    from app.config import settings as s

    # Rendemen dari tonase bila tak disebut eksplisit.
    if not rendemen_persen and berat_bahan and berat_hasil:
        if berat_bahan <= 0:
            return "Tonase bahan harus lebih dari 0."
        rendemen_persen = berat_hasil / berat_bahan * 100
    if not harga_gabah or not rendemen_persen:
        return (
            "Sebutkan harga beli + rendemen ATAU tonase bahan & hasil, contoh:\n"
            "`simulasi hpp gabah 7800 rendemen 64`\n"
            "`simulasi hpp bahan 10 ton hasil 6,4 ton harga 7800`"
        )
    rend = rendemen_persen / 100
    if rend <= 0 or rend > 1:
        return "Rendemen harus antara 1–100 persen (cek tonase bahan ≥ hasil)."

    # Biaya operator FLAT per proses → butuh tonase bahan untuk dibagi per kg.
    if not berat_bahan:
        return (
            f"Sebutkan TONASE bahannya juga — biaya operator {_rp(s.biaya_operator_per_proses)} "
            "FLAT per proses milling dibagi tonase. Contoh:\n"
            "`simulasi hpp bahan 10 ton hasil 6,4 ton harga 7800`"
        )
    operator_kg = s.biaya_operator_per_proses / berat_bahan

    if langsung_silo:
        dry, jalur = 0.0, "kering · langsung silo (tanpa pengeringan)"
    elif kondisi == "kering":
        dry, jalur = s.biaya_pengeringan_kering_per_kg, "kering · tetap dikeringkan"
    else:
        dry, jalur = s.biaya_pengeringan_basah_per_kg, "basah · dikeringkan"

    rubber = s.rubber_roll_harga_per_set / (s.rubber_roll_umur_ton * 1000)
    per_gabah = (
        s.biaya_bongkar_per_kg_gabah + dry + operator_kg
        + rubber + s.biaya_listrik_milling_per_kg_gabah
    )
    milling_labor = s.biaya_tenaga_milling_per_kg_pk * rend  # per kg gabah
    op = per_gabah + milling_labor
    total_gabah = harga_gabah + op
    hpp_pk = total_gabah / rend

    return "\n".join([
        f"🧮 *Simulasi HPP* — gabah {jalur}, rendemen {rendemen_persen:g}%",
        f"• Tonase: {berat_bahan:g} kg bahan"
        + (f" → {berat_hasil:g} kg hasil" if berat_hasil else ""),
        f"• Harga gabah: {_rp(harga_gabah)}/kg",
        f"• Biaya proses: {_rp(op)}/kg gabah",
        f"   (bongkar {_rp(s.biaya_bongkar_per_kg_gabah)} · pengeringan {_rp(dry)} · "
        f"operator {_rp(operator_kg)}/kg ({_rp(s.biaya_operator_per_proses)} flat ÷ {berat_bahan:g} kg) · "
        f"rubber {_rp(rubber)} · listrik {_rp(s.biaya_listrik_milling_per_kg_gabah)} · "
        f"tenaga giling {_rp(milling_labor)})",
        f"\n➡️ *HPP: {_rp(hpp_pk)}/kg PK*  ·  {_rp(total_gabah)}/kg gabah",
        f"_(bahan baku {_rp(harga_gabah / rend)} + operasional {_rp(op / rend)} per kg PK)_",
    ])


async def _avg_rendemen(db: AsyncSession) -> float:
    """Rendemen rata-rata dari proses selesai berbobot output. Fallback asумsi."""
    from app.config import settings as s
    procs = (
        await db.execute(select(MillingProcess).where(MillingProcess.status == "selesai"))
    ).scalars().all()
    tot_pk = tot_gabah = 0.0
    for p in procs:
        out = await _proc_pk_output(db, p)
        if out and p.berat_gabah_masuk_kg:
            tot_pk += out
            tot_gabah += float(p.berat_gabah_masuk_kg)
    if tot_gabah > 0:
        return tot_pk / tot_gabah
    return s.rendemen_asumsi_persen / 100


async def biaya_proses_ringkas(db: AsyncSession) -> str:
    """Biaya PROSES (operasional, tanpa harga gabah) per kg gabah — tiap jalur."""
    from app.config import settings as s
    rend = await _avg_rendemen(db)
    rubber = s.rubber_roll_harga_per_set / (s.rubber_roll_umur_ton * 1000)
    tetap = (
        s.biaya_bongkar_per_kg_gabah
        + rubber + s.biaya_listrik_milling_per_kg_gabah
    )  # per kg gabah, di luar pengeringan & operator (operator kini flat/proses)
    milling = s.biaya_tenaga_milling_per_kg_pk * rend  # per kg gabah
    op_10ton = s.biaya_operator_per_proses / 10000  # ilustrasi @ 10 ton

    def total(dry):
        return tetap + dry + milling

    return "\n".join([
        f"🏭 *Biaya proses per kg gabah* (operasional, di luar harga beli)",
        f"_Tenaga giling {_rp(s.biaya_tenaga_milling_per_kg_pk)}/kg PK "
        f"≈ {_rp(milling)}/kg gabah @ rendemen {rend * 100:.0f}%_",
        f"_Operator {_rp(s.biaya_operator_per_proses)} FLAT/proses "
        f"(≈ {_rp(op_10ton)}/kg @ 10 ton) — belum termasuk di angka /kg di bawah._",
        f"\n• Basah (dikeringkan): *{_rp(total(s.biaya_pengeringan_basah_per_kg))}/kg gabah*",
        f"• Kering (tetap dikeringkan): *{_rp(total(s.biaya_pengeringan_kering_per_kg))}/kg*",
        f"• Kering langsung silo (tanpa pengeringan): *{_rp(total(0))}/kg*",
        f"\nKomponen tetap/kg gabah: bongkar {_rp(s.biaya_bongkar_per_kg_gabah)} · "
        f"rubber {_rp(rubber)} · listrik {_rp(s.biaya_listrik_milling_per_kg_gabah)} "
        f"+ pengeringan (sesuai jalur) + giling {_rp(milling)} "
        f"+ operator {_rp(s.biaya_operator_per_proses)} flat/proses.",
    ])


async def rekap_produksi_bulanan(db: AsyncSession) -> str:
    """Rekap produksi PK per bulan + utilisasi vs kapasitas teoritis dryer."""
    from app.config import settings as s
    dryer = (await db.execute(select(Dryer).limit(1))).scalars().first()
    cap_kg = float(dryer.kapasitas_kg) if dryer else 30000
    teoritis_gabah = cap_kg * s.kapasitas_siklus_dryer_per_hari * s.kapasitas_hari_kerja_per_bulan

    procs = (
        await db.execute(
            select(MillingProcess)
            .where(MillingProcess.status == "selesai", MillingProcess.waktu_selesai.isnot(None))
            .order_by(MillingProcess.waktu_selesai)
        )
    ).scalars().all()
    per_bulan: dict[tuple[int, int], list[float]] = {}  # -> [gabah, pk, n]
    for p in procs:
        out = await _proc_pk_output(db, p)
        if not out:
            continue
        key = (p.waktu_selesai.year, p.waktu_selesai.month)
        acc = per_bulan.setdefault(key, [0.0, 0.0, 0])
        acc[0] += float(p.berat_gabah_masuk_kg or 0)
        acc[1] += out
        acc[2] += 1

    lines = [
        "📅 *Rekap Produksi Bulanan & Utilisasi*",
        f"_Kapasitas teoritis: {cap_kg / 1000:g} t × {s.kapasitas_siklus_dryer_per_hari:g} "
        f"siklus/hari × {s.kapasitas_hari_kerja_per_bulan} hari = "
        f"{_ton(teoritis_gabah)} gabah/bulan (asumsi, bisa diubah)._",
    ]
    if not per_bulan:
        lines.append("\nBelum ada produksi PK yang selesai.")
        return "\n".join(lines)
    for (thn, bln) in sorted(per_bulan):
        gabah, pk, n = per_bulan[(thn, bln)]
        rend = pk / gabah * 100 if gabah else 0
        util = gabah / teoritis_gabah * 100 if teoritis_gabah else 0
        lines.append(
            f"\n• *{_BULAN[bln - 1]} {thn}*: PK {_ton(pk)} dari gabah {_ton(gabah)} "
            f"(rendemen {rend:.1f}%, {n} proses)"
        )
        lines.append(f"   Utilisasi kapasitas: *{util:.1f}%* ({_ton(gabah)} / {_ton(teoritis_gabah)})")
    return "\n".join(lines)


async def analisa_musiman(db: AsyncSession) -> str:
    """Pola musiman kualitas gabah masuk, dikelompokkan per bulan kalender.

    Sinyal kualitas: kadar air awal (rendah=kering/bagus) + proporsi basah +
    volume. Butuh data lintas beberapa bulan/tahun agar polanya valid.
    """
    from sqlalchemy import case, extract

    rows = (
        await db.execute(
            select(
                extract("month", PurchaseBatch.tanggal_pembelian),
                func.count(PurchaseBatch.id),
                func.coalesce(func.sum(PurchaseBatch.berat_total_kg), 0),
                func.avg(PurchaseBatch.kadar_air_awal_persen),
                func.coalesce(
                    func.sum(
                        case((PurchaseBatch.kondisi_gabah == "basah", PurchaseBatch.berat_total_kg), else_=0)
                    ), 0,
                ),
                func.count(PurchaseBatch.kadar_air_awal_persen),
            )
            .group_by(extract("month", PurchaseBatch.tanggal_pembelian))
            .order_by(extract("month", PurchaseBatch.tanggal_pembelian))
        )
    ).all()
    if not rows:
        return "🌾 Belum ada data pembelian untuk analisa musiman."

    lines = [
        "🌾 *Analisa Musiman Kualitas Gabah* (per bulan kalender)",
        "_Kualitas: kadar air awal (rendah = lebih kering/bagus) & proporsi basah._",
    ]
    best = None  # (bulan, kadar_air) kadar air terendah
    ada_ka = False
    for bln, n, kg, ka, basah_kg, n_ka in rows:
        b = int(bln)
        pct_basah = float(basah_kg) / float(kg) * 100 if kg else 0
        ka_txt = f"{float(ka):.1f}%" if ka is not None else "-"
        if ka is not None:
            ada_ka = True
            if best is None or float(ka) < best[1]:
                best = (b, float(ka))
        lines.append(
            f"\n• *{_BULAN[b - 1]}*: {int(n)} batch · {_ton(float(kg))} · "
            f"{pct_basah:.0f}% basah · kadar air awal {ka_txt}"
        )
    if best is not None:
        lines.append(f"\n🏆 Kadar air awal terendah: *{_BULAN[best[0] - 1]}* ({best[1]:.1f}%).")
    if not ada_ka:
        lines.append(
            "\n⚠️ Kadar air awal belum banyak dicatat — catat saat pembelian "
            "('gabah masuk ... kadar air 24%') agar analisa kualitas lebih tajam."
        )
    lines.append("_Pola musiman valid setelah terkumpul data ≥1 tahun._")
    return "\n".join(lines)
