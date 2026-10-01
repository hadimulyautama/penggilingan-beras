"""Data terpadu untuk dashboard staff produksi (web + Telegram).

Satu sumber data: `dashboard_data(db)` → dict terstruktur. Dirender jadi teks
(bot) atau HTML (web). Menampilkan status operasional live & tugas verifikasi/QC.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
import logging

from app.database import now_local

log = logging.getLogger("dashboard")
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
from app.penggilingan.gudang1.services.drying import _latest_log
from app.penggilingan.gudang1.services.milling import (
    pk_breakdown_banyak,
    pk_jenis_banyak,
    progress_banyak,
)
from app.penggilingan.gudang1.services.silo import (
    _active_storage,
    _g1_warehouse_id,
    _lot_kg,
    _lot_suppliers,
)


def _jam(now: datetime, dt: datetime | None) -> float | None:
    return (now - dt).total_seconds() / 3600 if dt else None


async def _gabah_hari_ini(db: AsyncSession, today) -> dict:
    """Gabah yang MASUK hari ini — termasuk yang dititipkan, disebut terpisah.

    Pertanyaan baris ini "apa yang turun dari truk hari ini", bukan "apa yang
    pabrik beli", jadi gabah jasa ikut dihitung: menyembunyikannya membuat
    dashboard berselisih dengan jumlah tiket timbang hari itu, dan selisih yang
    tak dijelaskan selalu dicari sebagai kesalahan.

    Tetapi ia DISEBUT TERPISAH (`jasa_kg`, `jasa_batch`), sebab yang membaca
    angka "gabah masuk" sebagian memakainya untuk memperkirakan pembelian — dan
    dua arti dalam satu angka adalah cara tercepat membuat keduanya salah.
    """
    rows = (
        await db.execute(
            select(PurchaseBatch.berat_total_kg, PurchaseBatch.kondisi_gabah,
                   PurchaseBatch.jasa_id)
            .where(PurchaseBatch.tanggal_pembelian == today)
        )
    ).all()
    total = basah = kering = 0.0
    jasa_kg = 0.0
    jasa_batch = 0
    menunggu = 0
    for kg, kondisi, jasa_id in rows:
        if jasa_id is not None:
            jasa_batch += 1
            if kg is not None:
                jasa_kg += float(kg)
        # ── Berat NULL adalah keadaan yang SAH ──
        #
        # Batch yang tiketnya sudah ditautkan tetapi timbangan KEDUA-nya belum
        # turun memang belum punya berat. `float(None)` di sini membuat
        # Beranda kosong DIAM-DIAM dan `/internal/produksi/operasional`
        # menjawab 500 — sehingga briefing Kantor berkata "sistem produksi
        # bermasalah" untuk keadaan yang sebetulnya normal: satu truk sedang
        # di jembatan. Temuan QA X-06.
        if kg is None:
            menunggu += 1
            continue
        kg = float(kg)
        total += kg
        if kondisi == "kering":
            kering += kg
        else:
            basah += kg
    # Yang menunggu disebut TERPISAH, bukan dijumlahkan sebagai nol: nol
    # membuatnya hilang dari pandangan justru saat ia perlu ditindak.
    return {"batch": len(rows), "total_kg": total, "basah_kg": basah,
            "kering_kg": kering, "menunggu_bobot": menunggu,
            "jasa_kg": jasa_kg, "jasa_batch": jasa_batch}


async def _pengeringan_berjalan(db: AsyncSession, now) -> list[dict]:
    lots = (
        await db.execute(
            select(DryingLot).where(DryingLot.status == "proses").order_by(DryingLot.id)
        )
    ).scalars().all()

    bawaan = float(settings.kadar_air_target_persen)
    out = []
    for lot in lots:
        # Target milik LOT lebih dulu — operator menetapkannya sebelum mesin
        # dinyalakan, dan itu yang sesungguhnya dituju muatan ini. Setelan
        # aplikasi hanya nilai bawaan untuk lot lama yang belum punya.
        target = (float(lot.target_kadar_air)
                  if lot.target_kadar_air is not None else bawaan)
        log = await _latest_log(db, lot.id)
        tes = float(log.kadar_air_tes_manual) if log is not None and log.kadar_air_tes_manual is not None else None
        mesin = float(log.kadar_air_indikator) if log is not None and log.kadar_air_indikator is not None else None
        # `kadar_air` dipertahankan untuk pembaca lama (bot, ringkasan teks).
        ka = tes if tes is not None else mesin

        # Titik tolak dan rumusnya dipinjam dari layanan pengeringan — layar
        # Beranda memakai yang sama persis, dan dua salinan rumus yang sama
        # adalah dua angka yang cepat atau lambat berbeda.
        from app.penggilingan.gudang1.services.drying import kadar_air_awal, kemajuan

        awal = await kadar_air_awal(db, lot.id)
        maju = kemajuan(awal, ka, target)

        out.append({
            "kode": lot.kode_lot,
            "kadar_air": ka,
            "tes": tes,
            "mesin": mesin,
            "awal": awal,
            "target": target,
            "maju": maju,
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
                item["kg"] = float(b.berat_total_kg or 0) if b else 0.0
        out.append(item)
    return out


async def _giling_berjalan(db: AsyncSession, now) -> list[dict]:
    procs = (
        await db.execute(
            select(MillingProcess).where(MillingProcess.status == "proses").order_by(MillingProcess.id)
        )
    ).scalars().all()
    # Dua pertanyaan untuk SELURUH proses sekaligus, bukan dua kueri per
    # proses. Lihat `milling.pk_jenis_banyak` untuk sebabnya.
    prog = await progress_banyak(db, [p.id for p in procs])
    jenis = await pk_jenis_banyak(db, procs)
    return [{
        "kode": proc.kode_proses,
        "pk_kg": prog.get(proc.id),
        "jenis": jenis.get(proc.id),
        "jam": _jam(now, proc.waktu_mulai),
    } for proc in procs]


async def _stok_pk(db: AsyncSession) -> dict:
    """PK siap kirim, per proses giling.

    Dulu: SELURUH proses giling dibaca tanpa saringan apa pun, lalu empat
    kueri dikeluarkan untuk masing-masing di dalam gelung. Dengan data
    setahun itu ribuan kueri untuk menghitung stok yang isinya belasan baris —
    dan hampir semuanya menjawab "tersedia 0" untuk proses yang sudah lama
    habis terkirim. Temuan QA P-S-02.

    Sekarang: satu kueri untuk daftar prosesnya, lalu tujuh kueri untuk
    seluruh sisanya, berapa pun banyak prosesnya.
    """
    # ⚠ `jasa_id IS NULL`: "PK siap kirim" adalah stok PABRIK. PK pelanggan
    # tidak siap dikirim ke mana pun selain kembali ke pemiliknya, dan kartu yang
    # menjumlahkannya ke sini mengajari pembacanya memperlakukan barang orang
    # lain sebagai persediaan.
    procs = (
        await db.execute(select(MillingProcess)
                         .where(MillingProcess.jasa_id.is_(None))
                         .order_by(MillingProcess.kode_proses))
    ).scalars().all()
    rincian = await pk_breakdown_banyak(db, [p.id for p in procs])
    # Jenis PK hanya dicari untuk proses yang MASIH punya stok — itu pekerjaan
    # paling mahal di sini, dan proses yang stoknya nol tak muncul di layar
    # mana pun.
    punya = [p for p in procs if rincian[p.id].tersedia > 0]
    peta_jenis = await pk_jenis_banyak(db, punya)

    total = 0.0
    per_jenis: dict[str, float] = {}
    per_proses = []
    for proc in punya:
        bd = rincian[proc.id]
        jenis = peta_jenis.get(proc.id) or "?"
        total += bd.tersedia
        per_jenis[jenis] = per_jenis.get(jenis, 0.0) + bd.tersedia
        hari = None
        if proc.waktu_selesai or proc.waktu_mulai:
            sejak = proc.waktu_selesai or proc.waktu_mulai
            hari = (now_local() - sejak).total_seconds() / 86400
        per_proses.append({"kode": proc.kode_proses, "jenis": jenis,
                           "kg": bd.tersedia, "hari": hari})
    # Yang paling lama menumpuk disebut lebih dulu: itulah yang harus dikirim
    # duluan, dan urutan daftar adalah cara termurah mengatakannya.
    per_proses.sort(key=lambda p: (p["hari"] is None, -(p["hari"] or 0)))
    return {"total": total, "per_jenis": per_jenis, "per_proses": per_proses,
            "maks": settings.g1_pk_tumpukan_maks_kg}


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
        {"kode": b.kode_batch, "supplier": nama, "kg": float(b.berat_total_kg or 0)}
        for b, nama in vh_rows
    ]

    # Milling selesai: butuh QC dan/atau verifikasi output.
    selesai = (
        await db.execute(
            select(MillingProcess).where(MillingProcess.status == "selesai").order_by(MillingProcess.id)
        )
    ).scalars().all()
    # Dua pertanyaan, dua kueri — bukan dua kueri PER PROSES. Daftar ini
    # memuat seluruh giling yang pernah selesai, jadi dengan data setahun
    # gelung lamanya sendirian mengeluarkan ribuan kueri. Temuan QA P-S-02.
    ids = [p.id for p in selesai]
    sudah_qc = set((await db.execute(
        select(MillingQcLog.milling_process_id)
        .where(MillingQcLog.milling_process_id.in_(ids))
        .group_by(MillingQcLog.milling_process_id)
    )).scalars()) if ids else set()
    sudah_verif = set((await db.execute(
        select(MillingProcessVerification.milling_process_id)
        .where(MillingProcessVerification.milling_process_id.in_(ids),
               MillingProcessVerification.berat_output_final_kg.isnot(None))
    )).scalars()) if ids else set()

    qc_output = [{"kode": p.kode_proses} for p in selesai if p.id not in sudah_qc]
    verifikasi_output = [{"kode": p.kode_proses} for p in selesai
                         if p.id not in sudah_verif]
    return {
        "verifikasi_harga": verifikasi_harga,
        "qc_output": qc_output,
        "verifikasi_output": verifikasi_output,
    }


def _kg(kg: float | None) -> str:
    return f"{kg:,.0f} kg".replace(",", ".") if kg is not None else "-"


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
    # Disebut hanya bila ada: baris "jasa 0 kg" tiap hari melatih mata
    # melewatinya, lalu ia tak terbaca juga pada hari angkanya besar.
    if g.get("jasa_batch"):
        lines.append(
            f"   _termasuk JASA (titipan pelanggan): {g['jasa_batch']} batch, "
            f"{_kg(g['jasa_kg'])} — bukan pembelian_"
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
    maks = stok.get("maks") or 0
    lines.append(
        f"• PK menumpuk di Gudang 1: {_kg(stok['total'])}"
        + (f" / maks {maks / 1000:g} ton" if maks else "")
        + (f" ({ringkas})" if ringkas else "")
    )
    # Tumpukan yang cuma disebut jumlahnya tak bisa ditindaklanjuti: yang perlu
    # diputuskan adalah LOT MANA yang dikirim duluan, dan jawabannya hampir
    # selalu "yang paling lama menunggu".
    for p in stok["per_proses"]:
        umur = f" · menunggu {p['hari']:.0f} hari" if p["hari"] is not None else ""
        lines.append(f"   ‣ {p['kode']} · {p['jenis']} {_kg(p['kg'])}{umur}")
    if maks and stok["total"] > maks:
        lines.append(f"   ⚠️ Melewati batas lantai {maks / 1000:g} ton — kirim ke penyosohan.")

    # Berapa lama pabrik berhenti hari ini — disebut hanya bila memang
    # berhenti. Baris "0 jam" tiap hari akan berhenti dibaca justru pada hari
    # angkanya berubah.
    bh = op.get("berhenti") or {}
    if bh.get("per_sebab"):
        lines.append(f"• Pabrik berhenti: {bh['total_jam']:.1f} jam")
        for s in bh["per_sebab"][:4]:
            lines.append(f"   ‣ {s['sebab']} · {s['jam']:.1f} jam · {s['kali']}×")

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
    return "\n".join(lines)


def _esc(s) -> str:
    return (
        str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


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
             f"{g['batch']} batch · basah {_kg(g['basah_kg'])} · kering {_kg(g['kering_kg'])}"
             # Disebut hanya bila ada — lihat catatan di `render_dashboard_text`.
             + (f" · termasuk JASA {_kg(g['jasa_kg'])}" if g.get("jasa_batch") else ""))
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
  <footer>Data internal — jangan dibagikan ke luar.</footer>
</main>
</body></html>"""


async def _berhenti_hari_ini(db: AsyncSession, now) -> dict:
    from datetime import time as _time

    from app.penggilingan.gudang1.services.jeda import rekap_berhenti

    pagi = datetime.combine(now.date(), _time.min, tzinfo=now.tzinfo)
    rekap = await rekap_berhenti(db, sejak=pagi, sampai=now)
    return {
        "total_jam": sum(b.detik for b in rekap) / 3600,
        "per_sebab": [{"sebab": b.sebab, "jam": b.detik / 3600, "kali": b.kali}
                      for b in rekap],
    }


async def _aman(nama: str, coro, bawaan):
    """Jalankan satu bagian dashboard; kegagalannya tak menjatuhkan sisanya.

    Sebelum ini seluruh halaman disusun dalam satu ekspresi, jadi satu galat
    di satu bagian mengosongkan SEMUANYA — dan diam-diam: Beranda tampil
    kosong tanpa menyebutkan ada yang gagal, sementara `/internal` menjawab
    500 sehingga briefing Kantor berkata "sistem produksi bermasalah".

    Bagian yang gagal mengembalikan bawaannya dan MENYEBUTKAN dirinya di
    `galat`, supaya yang hilang terlihat sebagai bagian yang hilang — bukan
    sebagai pabrik yang tak bekerja.
    """
    try:
        return await coro, None
    except Exception as e:  # noqa: BLE001
        log.exception("Bagian dashboard '%s' gagal", nama)
        return bawaan, f"{nama}: {type(e).__name__}"


async def dashboard_data(db: AsyncSession) -> dict:
    """Snapshot terstruktur untuk dashboard staff produksi."""
    now = now_local()
    today = now.date()
    galat: list[str] = []

    async def ambil(nama, coro, bawaan):
        nilai, pesan = await _aman(nama, coro, bawaan)
        if pesan:
            galat.append(pesan)
        return nilai

    operasional = {
        "gabah_hari_ini": await ambil(
            "gabah hari ini", _gabah_hari_ini(db, today),
            {"batch": 0, "total_kg": 0.0, "basah_kg": 0.0, "kering_kg": 0.0,
             "menunggu_bobot": 0}),
        "pengeringan": await ambil("pengeringan", _pengeringan_berjalan(db, now), []),
        "silo": await ambil("silo", _silo_status(db), []),
        "giling": await ambil("giling", _giling_berjalan(db, now), []),
        "stok_pk": await ambil("stok PK", _stok_pk(db), []),
        # Berapa lama pabrik BERHENTI hari ini, dijumlah per sebab.
        # Satu-satunya angka di dashboard ini yang bisa langsung diperbaiki
        # besok — dan ia hanya ada karena tiap jeda mencatat sebabnya, bukan
        # cuma mencatat bahwa berhenti.
        "berhenti": await ambil("berhenti", _berhenti_hari_ini(db, now), []),
    }
    return {
        "generated_at": now,
        "operasional": operasional,
        "tugas": await ambil("tugas", _tugas(db), []),
        # Kosong = semua bagian berhasil. Disebutkan apa adanya supaya
        # pembacanya tahu angka mana yang sedang tak bisa dipercaya.
        "galat": galat,
    }
