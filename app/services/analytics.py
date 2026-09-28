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
    Supplier,
)

_BULAN = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt",
          "Nov", "Des"]


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
    turunan: rendemen (%) dan kadar air masuk. `diproduksi` diperingkat dari
    RENDEMEN PK TERTINGGI.

    ⚠ PERINGKATNYA BERUBAH 28 September 2026, dan pemilik perlu tahu: dulu ia
    HPP/kg PK terendah. Harga keluar dari Pos Produksi hari itu (keputusan
    pemilik), jadi dasar lama tak punya bahan baku lagi.

    Rapor ini TIDAK dibiarkan mati, dan itu keputusan yang bisa pemilik balik:
    seluruh fakta lain di dalamnya milik produksi dan tetap ada — pasok, jumlah
    batch, rendemen, kadar air masuk. Untuk aplikasi produksi rendemen justru
    dasar yang lebih tepat: pemasok terbaik adalah yang gabahnya paling banyak
    jadi beras. Keuangan bisa memeringkat dengan biaya di sisi mereka.
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
            "pk_alloc": 0.0, "gabah_milled": 0.0,
        }

    # ── 2. Rendemen: berapa PK yang keluar dari gabah tiap supplier ──
    #
    # Dibagi menurut PORSI BERAT gabahnya dalam lot, sama seperti dulu — yang
    # dibuang cuma suku rupiahnya. Satu lot boleh datang dari beberapa batch
    # beberapa supplier, dan tak ada cara memisahkan PK-nya selain porsi.
    procs = (
        await db.execute(select(MillingProcess).where(MillingProcess.status == "selesai"))
    ).scalars().all()
    for proc in procs:
        output = await _proc_pk_output(db, proc)
        if not output:
            continue
        batches = await _proc_batches(db, proc)
        total_kg = sum(float(b.berat_total_kg or 0) for b, _ in batches)
        if total_kg <= 0:
            continue
        for b, _harga in batches:
            sid = b.supplier_id
            if sid not in agg:
                continue
            share = float(b.berat_total_kg or 0) / total_kg
            agg[sid]["pk_alloc"] += output * share
            agg[sid]["gabah_milled"] += float(b.berat_total_kg or 0)

    for a in agg.values():
        a["rendemen"] = a["pk_alloc"] / a["gabah_milled"] * 100 if a["gabah_milled"] > 0 else None

    rows = list(agg.values())
    diproduksi = [a for a in rows if a["pk_alloc"] > 0]
    belum = [a for a in rows if a["pk_alloc"] <= 0]
    # Rendemen TERTINGGI lebih dulu; yang tak punya angka di belakang.
    diproduksi.sort(key=lambda a: (a["rendemen"] is None, -(a["rendemen"] or 0)))
    return {"diproduksi": diproduksi, "belum": belum}


async def supplier_scorecard(db: AsyncSession) -> str:
    """Rapor supplier: pasok, rendemen, kadar air masuk.

    Diperingkat dari RENDEMEN PK TERTINGGI — pemasok terbaik adalah yang
    gabahnya paling banyak jadi beras. Lihat catatan di
    `supplier_scorecard_data` tentang perubahan dasar peringkatnya.
    """
    data = await supplier_scorecard_data(db)
    diproduksi, belum = data["diproduksi"], data["belum"]
    if not diproduksi and not belum:
        return "📊 Belum ada data pembelian untuk dianalisa."

    lines = ["📊 *Rapor Supplier* (keseluruhan)"]
    medali = ["🥇", "🥈", "🥉"]
    for i, a in enumerate(diproduksi):
        tag = medali[i] if i < len(medali) else "•"
        ka = f"{a['kadar_air']:.0f}%" if a["kadar_air"] is not None else "-"
        r = a["rendemen"]
        lines.append(
            f"\n{tag} *{a['nama']}* — rendemen PK "
            + (f"{r:.1f}%" if r is not None else "-")
            + ("  ⭐ tertinggi" if i == 0 and r is not None else "")
        )
        lines.append(f"• Pasok {_ton(a['kg'])} ({a['n_batch']} batch)")
        lines.append(f"• Kadar air masuk {ka}")
    if belum:
        lines.append("\n_Belum ada produksi PK (hanya pengadaan):_")
        for a in belum:
            lines.append(f"• {a['nama']}: {_ton(a['kg'])} ({a['n_batch']} batch)")
    lines.append(
        "\n_Peringkat = rendemen PK tertinggi. Biaya dan harga ada di "
        "keuangan, tidak lagi di Pos Produksi._"
    )
    return "\n".join(lines)


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


# `biaya_proses_ringkas` DIBUANG 28 September 2026 — lihat catatan di atas.


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
