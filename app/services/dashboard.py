"""Data terpadu untuk dashboard staff produksi (web + Telegram).

Satu sumber data: `dashboard_data(db)` → dict terstruktur. Dirender jadi teks
(bot) atau HTML (web). Menampilkan status operasional live, tugas verifikasi/QC,
dan skor supplier.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import now_local
from app.models import (
    DryingLot,
    MillingProcess,
    MillingProcessVerification,
    MillingQcLog,
    PurchaseBatch,
    Silo,
    SiloStorage,
    Supplier,
)
from app.services.analytics import supplier_scorecard_data
from app.services.drying import _latest_log
from app.services.milling import _pk_breakdown, _latest_progress, pk_jenis
from app.services.silo import (
    _active_storage,
    _g1_warehouse_id,
    _lot_kg,
    _lot_suppliers,
)


def _jam(now: datetime, dt: datetime | None) -> float | None:
    return (now - dt).total_seconds() / 3600 if dt else None


async def _gabah_hari_ini(db: AsyncSession, today) -> dict:
    rows = (
        await db.execute(
            select(PurchaseBatch.berat_total_kg, PurchaseBatch.kondisi_gabah)
            .where(PurchaseBatch.tanggal_pembelian == today)
        )
    ).all()
    total = basah = kering = 0.0
    for kg, kondisi in rows:
        kg = float(kg)
        total += kg
        if kondisi == "kering":
            kering += kg
        else:
            basah += kg
    return {"batch": len(rows), "total_kg": total, "basah_kg": basah, "kering_kg": kering}


async def _pengeringan_berjalan(db: AsyncSession, now) -> list[dict]:
    lots = (
        await db.execute(
            select(DryingLot).where(DryingLot.status == "proses").order_by(DryingLot.id)
        )
    ).scalars().all()
    out = []
    for lot in lots:
        log = await _latest_log(db, lot.id)
        ka = None
        if log is not None:
            ka = log.kadar_air_tes_manual
            if ka is None:
                ka = log.kadar_air_indikator
        out.append({
            "kode": lot.kode_lot,
            "kadar_air": float(ka) if ka is not None else None,
            "jam": _jam(now, lot.waktu_mulai_pengeringan),
            "suppliers": await _lot_suppliers(db, lot.id),
            "kg": await _lot_kg(db, lot.id),
        })
    return out


async def _silo_status(db: AsyncSession) -> list[dict]:
    wid = await _g1_warehouse_id(db)
    silos = (
        await db.execute(
            select(Silo).where(Silo.warehouse_id == wid).order_by(Silo.nama_silo)
        )
    ).scalars().all()
    out = []
    for silo in silos:
        st = await _active_storage(db, silo.id)
        item = {
            "nama": silo.nama_silo.replace("Silo ", ""),
            "kapasitas_ton": float(silo.kapasitas_ton) if silo.kapasitas_ton is not None else None,
            "terisi": st is not None,
            "isi": None, "suppliers": [], "kg": 0.0,
        }
        if st is not None:
            if st.drying_lot_id:
                lot = await db.get(DryingLot, st.drying_lot_id)
                item["isi"] = lot.kode_lot if lot else "lot"
                item["suppliers"] = await _lot_suppliers(db, st.drying_lot_id)
                item["kg"] = await _lot_kg(db, st.drying_lot_id)
            elif st.purchase_batch_id:
                b = await db.get(PurchaseBatch, st.purchase_batch_id)
                sup = await db.get(Supplier, b.supplier_id) if b else None
                item["isi"] = b.kode_batch if b else "batch"
                item["suppliers"] = [sup.nama_supplier] if sup else []
                item["kg"] = float(b.berat_total_kg) if b else 0.0
        out.append(item)
    return out


async def _giling_berjalan(db: AsyncSession, now) -> list[dict]:
    procs = (
        await db.execute(
            select(MillingProcess).where(MillingProcess.status == "proses").order_by(MillingProcess.id)
        )
    ).scalars().all()
    out = []
    for proc in procs:
        prog = await _latest_progress(db, proc.id)
        out.append({
            "kode": proc.kode_proses,
            "pk_kg": prog,
            "jenis": await pk_jenis(db, proc),
            "jam": _jam(now, proc.waktu_mulai),
        })
    return out


async def _stok_pk(db: AsyncSession) -> dict:
    procs = (
        await db.execute(select(MillingProcess).order_by(MillingProcess.kode_proses))
    ).scalars().all()
    total = 0.0
    per_jenis: dict[str, float] = {}
    per_proses = []
    for proc in procs:
        bd = await _pk_breakdown(db, proc.id)
        if bd.tersedia <= 0:
            continue
        jenis = await pk_jenis(db, proc) or "?"
        total += bd.tersedia
        per_jenis[jenis] = per_jenis.get(jenis, 0.0) + bd.tersedia
        per_proses.append({"kode": proc.kode_proses, "jenis": jenis, "kg": bd.tersedia})
    return {"total": total, "per_jenis": per_jenis, "per_proses": per_proses}


async def _tugas(db: AsyncSession) -> dict:
    # Verifikasi harga: batch belum diverifikasi.
    vh_rows = (
        await db.execute(
            select(PurchaseBatch, Supplier.nama_supplier)
            .join(Supplier, Supplier.id == PurchaseBatch.supplier_id)
            .where(PurchaseBatch.flag_unverified.is_(True))
            .order_by(PurchaseBatch.id)
        )
    ).all()
    verifikasi_harga = [
        {"kode": b.kode_batch, "supplier": nama, "kg": float(b.berat_total_kg)}
        for b, nama in vh_rows
    ]

    # Milling selesai: butuh QC dan/atau verifikasi output.
    selesai = (
        await db.execute(
            select(MillingProcess).where(MillingProcess.status == "selesai").order_by(MillingProcess.id)
        )
    ).scalars().all()
    qc_output = []
    verifikasi_output = []
    for proc in selesai:
        qc = (
            await db.execute(
                select(func.count()).select_from(MillingQcLog).where(
                    MillingQcLog.milling_process_id == proc.id
                )
            )
        ).scalar_one()
        if not qc:
            qc_output.append({"kode": proc.kode_proses})
        v = (
            await db.execute(
                select(MillingProcessVerification.berat_output_final_kg).where(
                    MillingProcessVerification.milling_process_id == proc.id
                )
            )
        ).scalars().first()
        if not v:
            verifikasi_output.append({"kode": proc.kode_proses})
    return {
        "verifikasi_harga": verifikasi_harga,
        "qc_output": qc_output,
        "verifikasi_output": verifikasi_output,
    }


def _kg(kg: float | None) -> str:
    return f"{kg:,.0f} kg".replace(",", ".") if kg is not None else "-"


def _rp(n: float | None) -> str:
    return "Rp " + f"{n:,.0f}".replace(",", ".") if n is not None else "-"


def render_dashboard_text(data: dict) -> str:
    """Render dashboard sebagai teks Telegram (Markdown)."""
    op = data["operasional"]
    tg = data["tugas"]
    g = op["gabah_hari_ini"]
    lines = [f"📊 *Dashboard Produksi* — {data['generated_at']:%d-%m-%Y %H:%M}", ""]

    lines.append("*🌾 Operasional*")
    lines.append(
        f"• Gabah masuk hari ini: {g['batch']} batch, {_kg(g['total_kg'])} "
        f"(basah {_kg(g['basah_kg'])} · kering {_kg(g['kering_kg'])})"
    )
    if op["pengeringan"]:
        for p in op["pengeringan"]:
            ka = f"KA {p['kadar_air']:.0f}%" if p["kadar_air"] is not None else "KA -"
            jam = f"{p['jam']:.1f} jam" if p["jam"] is not None else "-"
            lines.append(f"• Pengeringan {p['kode']}: {ka}, {jam} ({_kg(p['kg'])})")
    else:
        lines.append("• Pengeringan: tidak ada yang berjalan")
    for s in op["silo"]:
        if s["terisi"]:
            sup = ", ".join(s["suppliers"]) or "-"
            lines.append(f"• Silo {s['nama']}: {s['isi']} ({sup}) {_kg(s['kg'])}")
        else:
            lines.append(f"• Silo {s['nama']}: kosong")
    if op["giling"]:
        for m in op["giling"]:
            jn = f" {m['jenis']}" if m["jenis"] else ""
            jam = f"{m['jam']:.1f} jam" if m["jam"] is not None else "-"
            lines.append(f"• Giling {m['kode']}: PK{jn} {_kg(m['pk_kg'])} ({jam})")
    else:
        lines.append("• Giling: tidak ada yang berjalan")
    stok = op["stok_pk"]
    ringkas = " · ".join(f"{j} {_kg(v)}" for j, v in sorted(stok["per_jenis"].items()))
    lines.append(
        f"• Stok PK siap kirim: {_kg(stok['total'])}"
        + (f" ({ringkas})" if ringkas else "")
    )

    lines.append("\n*✅ Tugas staff*")
    vh, qc, vo = tg["verifikasi_harga"], tg["qc_output"], tg["verifikasi_output"]
    if not (vh or qc or vo):
        lines.append("• Semua beres 🎉")
    else:
        if vh:
            kodes = ", ".join(b["kode"] for b in vh[:8])
            lines.append(f"• Verifikasi harga: {len(vh)} batch → {kodes}")
        if qc:
            lines.append(f"• QC output: {len(qc)} → " + ", ".join(m["kode"] for m in qc[:8]))
        if vo:
            lines.append(
                f"• Verifikasi output: {len(vo)} → " + ", ".join(m["kode"] for m in vo[:8])
            )

    sup = data["supplier"]["diproduksi"]
    if sup:
        lines.append("\n*🏅 Supplier teratas (HPP/kg PK terendah)*")
        medali = ["🥇", "🥈", "🥉"]
        for i, a in enumerate(sup):
            tag = medali[i] if i < len(medali) else "•"
            rend = f" · rendemen {a['rendemen']:.0f}%" if a["rendemen"] is not None else ""
            lines.append(
                f"{tag} {a['nama']} — HPP {_rp(a['hpp_pk'])}/kg{rend} "
                f"· pasok {a['kg'] / 1000:.1f} ton"
            )
    return "\n".join(lines)


def _esc(s) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


def _ton(kg: float | None) -> str:
    return f"{kg / 1000:,.1f} ton".replace(",", ".") if kg else "-"


def render_dashboard_html(data: dict) -> str:
    """Render dashboard sebagai halaman HTML mandiri (disajikan FastAPI)."""
    op, tg = data["operasional"], data["tugas"]
    g = op["gabah_hari_ini"]

    def card(judul: str, isi: str, sub: str = "") -> str:
        subhtml = f'<div class="sub">{sub}</div>' if sub else ""
        return (
            f'<div class="card"><div class="lbl">{judul}</div>'
            f'<div class="val">{isi}</div>{subhtml}</div>'
        )

    # Operasional cards
    peng = op["pengeringan"]
    if peng:
        p = peng[0]
        ka = f"KA {p['kadar_air']:.0f}%" if p["kadar_air"] is not None else "KA -"
        jam = f"{p['jam']:.1f} jam" if p["jam"] is not None else "-"
        peng_val = _esc(p["kode"])
        peng_sub = f"{ka} · {jam} · {_kg(p['kg'])}"
        if len(peng) > 1:
            peng_sub += f" (+{len(peng) - 1} lot)"
    else:
        peng_val, peng_sub = "—", "tidak ada yang berjalan"

    gil = op["giling"]
    if gil:
        m = gil[0]
        jn = f" {m['jenis']}" if m["jenis"] else ""
        jam = f"{m['jam']:.1f} jam" if m["jam"] is not None else "-"
        gil_val = _esc(m["kode"])
        gil_sub = f"PK{jn} {_kg(m['pk_kg'])} · {jam}"
        if len(gil) > 1:
            gil_sub += f" (+{len(gil) - 1} proses)"
    else:
        gil_val, gil_sub = "—", "tidak ada yang berjalan"

    stok = op["stok_pk"]
    ringkas = " · ".join(f"{j} {_kg(v)}" for j, v in sorted(stok["per_jenis"].items()))

    silo_cards = ""
    for s in op["silo"]:
        if s["terisi"]:
            sup = _esc(", ".join(s["suppliers"]) or "-")
            silo_cards += card(f"Silo {_esc(s['nama'])}", _kg(s["kg"]),
                               f"{_esc(s['isi'])} · {sup}")
        else:
            silo_cards += card(f"Silo {_esc(s['nama'])}", "kosong", "&nbsp;")

    op_html = (
        card("Gabah masuk hari ini", _kg(g["total_kg"]),
             f"{g['batch']} batch · basah {_kg(g['basah_kg'])} · kering {_kg(g['kering_kg'])}")
        + card("Pengeringan berjalan", peng_val, peng_sub)
        + card("Giling berjalan", gil_val, gil_sub)
        + card("Stok PK siap kirim", _kg(stok["total"]), ringkas or "&nbsp;")
        + silo_cards
    )

    # Tugas
    def tugas_block(judul: str, items: list, cls: str) -> str:
        if not items:
            return ""
        chips = "".join(f'<span class="chip">{_esc(i["kode"])}</span>' for i in items[:20])
        return (
            f'<div class="task {cls}"><div class="th">{judul} '
            f'<b>({len(items)})</b></div><div class="chips">{chips}</div></div>'
        )

    vh = "".join(
        f'<span class="chip">{_esc(b["kode"])} · {_esc(b["supplier"])}</span>'
        for b in tg["verifikasi_harga"][:20]
    )
    tugas_html = ""
    if tg["verifikasi_harga"]:
        tugas_html += (
            f'<div class="task warn"><div class="th">Verifikasi harga gabah '
            f'<b>({len(tg["verifikasi_harga"])})</b></div><div class="chips">{vh}</div></div>'
        )
    tugas_html += tugas_block("QC output giling", tg["qc_output"], "info")
    tugas_html += tugas_block("Verifikasi output PK", tg["verifikasi_output"], "info")
    if not tugas_html:
        tugas_html = '<div class="ok">✅ Semua tugas beres — tidak ada yang menunggu.</div>'

    # Supplier
    sup_rows = ""
    medali = ["🥇", "🥈", "🥉"]
    for i, a in enumerate(data["supplier"]["diproduksi"]):
        tag = medali[i] if i < len(medali) else "•"
        rend = f"{a['rendemen']:.0f}%" if a["rendemen"] is not None else "-"
        hpp = _rp(a["hpp_pk"]) + "/kg" if a["hpp_pk"] is not None else "-"
        harga = _rp(a["harga_per_kg"]) + "/kg" if a["harga_per_kg"] is not None else "-"
        sup_rows += (
            f"<tr><td>{tag} {_esc(a['nama'])}</td><td>{hpp}</td><td>{rend}</td>"
            f"<td>{harga}</td><td>{_ton(a['kg'])} · {a['n_batch']} batch</td></tr>"
        )
    if not sup_rows:
        sup_rows = '<tr><td colspan="5" class="muted">Belum ada produksi PK.</td></tr>'

    return f"""<!DOCTYPE html>
<html lang="id"><head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="60">
<title>Dashboard Produksi — HadiMulya</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font-family:-apple-system,"Segoe UI",Roboto,Arial,sans-serif;
    background:#f1f5f0; color:#14261a; }}
  header {{ background:#14532d; color:#fff; padding:16px 20px; }}
  header h1 {{ margin:0; font-size:19px; }}
  header .ts {{ opacity:.85; font-size:12px; margin-top:3px; }}
  main {{ max-width:960px; margin:0 auto; padding:16px; }}
  h2 {{ font-size:14px; text-transform:uppercase; letter-spacing:.5px; color:#15803d;
    margin:22px 0 10px; }}
  .grid {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(150px,1fr)); gap:10px; }}
  .card {{ background:#fff; border:1px solid #dbe7de; border-radius:12px; padding:12px 14px; }}
  .card .lbl {{ font-size:11px; color:#5b6b60; text-transform:uppercase; letter-spacing:.3px; }}
  .card .val {{ font-size:22px; font-weight:700; color:#14532d; margin-top:3px; }}
  .card .sub {{ font-size:12px; color:#54655b; margin-top:3px; }}
  .task {{ background:#fff; border-radius:12px; padding:12px 14px; margin-bottom:10px;
    border-left:5px solid #94a3b8; }}
  .task.warn {{ border-left-color:#f59e0b; }}
  .task.info {{ border-left-color:#3b82f6; }}
  .task .th {{ font-size:13px; color:#374151; margin-bottom:8px; }}
  .chips {{ display:flex; flex-wrap:wrap; gap:6px; }}
  .chip {{ background:#eef6f0; border:1px solid #cfe6d4; border-radius:20px;
    padding:3px 10px; font-size:12px; color:#14532d; font-family:ui-monospace,Menlo,monospace; }}
  .ok {{ background:#ecfdf3; border:1px solid #bbf7d0; color:#15803d; border-radius:12px;
    padding:14px; font-weight:600; }}
  table {{ width:100%; border-collapse:collapse; background:#fff; border-radius:12px;
    overflow:hidden; font-size:13px; }}
  th,td {{ text-align:left; padding:9px 12px; border-bottom:1px solid #eef2ef; }}
  th {{ background:#f0f7f1; color:#14532d; font-size:11px; text-transform:uppercase; }}
  .muted {{ color:#8a978d; }}
  footer {{ text-align:center; color:#8a978d; font-size:11px; padding:20px; }}
</style></head><body>
<header>
  <h1>📊 Dashboard Produksi</h1>
  <div class="ts">HadiMulya · diperbarui {data['generated_at']:%d-%m-%Y %H:%M} · otomatis refresh 60 dtk</div>
</header>
<main>
  <h2>Status operasional</h2>
  <div class="grid">{op_html}</div>

  <h2>Tugas verifikasi &amp; QC</h2>
  {tugas_html}

  <h2>Skor supplier (HPP/kg PK terendah)</h2>
  <table>
    <tr><th>Supplier</th><th>HPP PK</th><th>Rendemen</th><th>Harga gabah</th><th>Pasok</th></tr>
    {sup_rows}
  </table>
  <footer>Data internal — jangan dibagikan ke luar. Peringkat = HPP/kg PK terendah.</footer>
</main>
</body></html>"""


async def dashboard_data(db: AsyncSession) -> dict:
    """Snapshot terstruktur untuk dashboard staff produksi."""
    now = now_local()
    today = now.date()
    sc = await supplier_scorecard_data(db)
    return {
        "generated_at": now,
        "operasional": {
            "gabah_hari_ini": await _gabah_hari_ini(db, today),
            "pengeringan": await _pengeringan_berjalan(db, now),
            "silo": await _silo_status(db),
            "giling": await _giling_berjalan(db, now),
            "stok_pk": await _stok_pk(db),
        },
        "tugas": await _tugas(db),
        "supplier": {
            "diproduksi": sc["diproduksi"][:5],
            "belum": sc["belum"][:5],
        },
    }
