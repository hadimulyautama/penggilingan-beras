"""Router Mini App Telegram: identitas + dashboard + AKSI CEPAT role-aware.

Tiap endpoint memakai `require_miniapp_user` → tahu SIAPA & role-nya (server-side).
Data & aksi memakai Service yang sama dengan bot (satu sumber kebenaran). Menu
aksi ditentukan SERVER per role: operator G1 (gabah masuk / kadar air / hasil
giling), staff-admin (verifikasi harga / pemindahan PK). Operator tak dapat aksi
keuangan.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.bots.common import can_see_financials, can_transfer_pk
from app.database import SessionLocal
from app.models import User
from app.web.deps import require_miniapp_user

router = APIRouter(prefix="/miniapp", tags=["miniapp"])


def _require(cond: bool, msg: str = "Aksi ini tidak tersedia untuk peran Anda.") -> None:
    if not cond:
        raise HTTPException(status_code=403, detail=msg)


def _rp(n: float) -> str:
    return f"{n:,.0f}".replace(",", ".")


# ─────────────────────────── Identitas ───────────────────────────

@router.get("/me")
async def me(user: User = Depends(require_miniapp_user)) -> dict:
    """Profil + izin user (menentukan tampilan front-end)."""
    return {
        "id": user.id, "nama": user.nama, "role": user.role,
        "default_warehouse_id": user.default_warehouse_id,
        "permissions": {
            "see_financials": can_see_financials(user),
            "transfer_pk": can_transfer_pk(user),
        },
    }


# ─────────────────────────── Dashboard ───────────────────────────

def _clean(s: str) -> str:
    return (s or "").replace("*", "").replace("_", "")


async def _hpp_terkini(db) -> str:
    from sqlalchemy import select
    from app.models import PolishingProcess
    from app.inventory.finished_goods import laporan_hpp_beras
    from app.inventory.packaging import InventoryError
    kode = (
        await db.execute(
            select(PolishingProcess.kode_proses).order_by(PolishingProcess.id.desc()).limit(1)
        )
    ).scalars().first()
    if not kode:
        return "Belum ada penyosohan."
    try:
        return _clean(await laporan_hpp_beras(db, kode))
    except InventoryError:
        return "Belum tersedia (menunggu data lengkap)."


@router.get("/dashboard")
async def dashboard(user: User = Depends(require_miniapp_user)) -> dict:
    """Snapshot dashboard sesuai role. Keuangan (HPP/tugas) hanya staff/admin."""
    fin = can_see_financials(user)
    from app.services.report import status_gudang1, pending_verifikasi
    from app.services.transfer import laporan_pk_siap_transfer
    from app.gudang2.service import laporan_stok_gudang2
    from app.inventory.finished_goods import laporan_stok_barang_jadi, hitung_stok_bekatul
    from app.inventory.packaging import laporan_stok_kemasan

    from app.services.pemantau import pemantau_nyangkut

    sections: list[dict] = []
    async with SessionLocal() as db:
        sections.append({"icon": "⚠️", "title": "Perlu tindakan (nyangkut)", "body": _clean(
            await pemantau_nyangkut(db, financial=fin))})
        sections.append({"icon": "🌾", "title": "Gudang 1 — Selepan", "body": _clean(
            await status_gudang1(db) + "\n\n" + await laporan_pk_siap_transfer(db))})
        sections.append({"icon": "🏭", "title": "Gudang 2 — Penyosohan", "body": _clean(
            await laporan_stok_gudang2(db, financial=fin))})
        bekatul = float(await hitung_stok_bekatul(db))
        sections.append({"icon": "📦", "title": "Barang jadi & bekatul", "body": _clean(
            await laporan_stok_barang_jadi(db) + f"\n\n🌾 Bekatul curah: {_rp(bekatul)} kg")})
        sections.append({"icon": "🧺", "title": "Kemasan", "body": _clean(
            await laporan_stok_kemasan(db))})
        if fin:
            sections.append({"icon": "✅", "title": "Tugas verifikasi & QC", "body": _clean(
                await pending_verifikasi(db))})
            sections.append({"icon": "💰", "title": "HPP beras terkini",
                             "body": await _hpp_terkini(db)})
    return {"user": {"nama": user.nama, "role": user.role, "see_financials": fin},
            "sections": sections}


# ─────────────────────── Aksi cepat: role helper ───────────────────────

async def _is_g1_operator(user: User) -> bool:
    """Admin selalu boleh; operator hanya bila gudang default = Gudang 1."""
    if user.role == "admin":
        return True
    if user.role != "operator":
        return False
    from sqlalchemy import select
    from app.models import Warehouse
    async with SessionLocal() as db:
        wid = (
            await db.execute(
                select(Warehouse.id).where(Warehouse.nama_gudang.like("Gudang 1%"))
            )
        ).scalars().first()
    return wid is not None and user.default_warehouse_id == wid


@router.get("/actions/menu")
async def actions_menu(user: User = Depends(require_miniapp_user)) -> list[dict]:
    """Daftar aksi cepat + spesifikasi field, ditentukan SERVER per role."""
    fin = can_see_financials(user)
    g1 = await _is_g1_operator(user)
    KONDISI = [["basah", "Basah (→ PK KS)"], ["kering", "Kering (→ PK KL)"]]
    TUJUAN = [["silo_a", "Silo A"], ["silo_b", "Silo B"], ["ditumpuk", "Tumpukan"]]
    METODE = [["total", "Total (Rp)"], ["per_kg", "Per kg (Rp)"]]
    actions: list[dict] = []
    if g1:
        actions += [
            {"id": "gabah_masuk", "label": "🌾 Gabah masuk",
             "post": "/miniapp/actions/gabah-masuk", "fields": [
                 {"name": "supplier", "label": "Supplier", "type": "text"},
                 {"name": "berat", "label": "Berat (kg)", "type": "number"},
                 {"name": "kondisi", "label": "Kondisi gabah", "type": "select", "options": KONDISI},
                 {"name": "plat", "label": "Plat truk", "type": "text"},
                 {"name": "tujuan", "label": "Tujuan (wajib pilih)", "type": "select",
                  "options": [["", "— belum ditentukan —"], ["dryer", "Dryer"],
                              ["silo_a", "Silo A"], ["silo_b", "Silo B"]]},
             ]},
            {"id": "kadar_air", "label": "💧 Update kadar air",
             "post": "/miniapp/actions/kadar-air", "fields": [
                 {"name": "kode_lot", "label": "Lot pengeringan", "type": "remote",
                  "source": "/miniapp/actions/drying-active"},
                 {"name": "kadar_air", "label": "Kadar air (%)", "type": "number"},
             ]},
            {"id": "hasil_giling", "label": "⚙️ Update hasil giling",
             "post": "/miniapp/actions/hasil-giling", "fields": [
                 {"name": "kode_proses", "label": "Proses giling", "type": "remote",
                  "source": "/miniapp/actions/milling-active"},
                 {"name": "berat_kumulatif", "label": "PK kumulatif (kg)", "type": "number"},
             ]},
        ]
    if fin:
        actions += [
            {"id": "verify_gabah", "label": "✅ Verifikasi harga gabah",
             "post": "/miniapp/actions/verify-gabah", "fields": [
                 {"name": "kode_batch", "label": "Batch gabah", "type": "remote",
                  "source": "/miniapp/actions/gabah-unverified"},
                 {"name": "metode", "label": "Metode", "type": "select", "options": METODE},
                 {"name": "nilai", "label": "Nilai (Rp)", "type": "number"},
             ]},
            {"id": "transfer_pk", "label": "🚚 Pemindahan PK G1 → G2",
             "post": "/miniapp/actions/transfer-pk", "fields": [
                 {"name": "kode_proses", "label": "PK dari proses", "type": "remote",
                  "source": "/miniapp/actions/pk-transfer"},
                 {"name": "berat", "label": "Berat kg (kosong = semua)", "type": "number"},
                 {"name": "tujuan", "label": "Tujuan", "type": "select", "options": TUJUAN},
             ]},
        ]
    return actions


# ─────────────────────── Aksi cepat: daftar pilihan (remote) ───────────────────────

@router.get("/actions/drying-active")
async def drying_active(user: User = Depends(require_miniapp_user)) -> list[dict]:
    _require(await _is_g1_operator(user))
    from sqlalchemy import select
    from app.models import DryingLot
    async with SessionLocal() as db:
        lots = (
            await db.execute(
                select(DryingLot.kode_lot).where(DryingLot.status == "proses")
                .order_by(DryingLot.id.desc())
            )
        ).scalars().all()
    return [{"value": k, "label": k} for k in lots]


@router.get("/actions/milling-active")
async def milling_active(user: User = Depends(require_miniapp_user)) -> list[dict]:
    _require(await _is_g1_operator(user))
    from sqlalchemy import select
    from app.models import MillingProcess
    async with SessionLocal() as db:
        procs = (
            await db.execute(
                select(MillingProcess.kode_proses).where(MillingProcess.status == "proses")
                .order_by(MillingProcess.id.desc())
            )
        ).scalars().all()
    return [{"value": k, "label": k} for k in procs]


@router.get("/actions/gabah-unverified")
async def gabah_unverified(user: User = Depends(require_miniapp_user)) -> list[dict]:
    _require(can_see_financials(user))
    from sqlalchemy import select
    from app.models import PurchaseBatch, Supplier
    async with SessionLocal() as db:
        rows = (
            await db.execute(
                select(PurchaseBatch, Supplier.nama_supplier)
                .join(Supplier, Supplier.id == PurchaseBatch.supplier_id)
                .where(PurchaseBatch.flag_unverified.is_(True))
                .order_by(PurchaseBatch.id.desc()).limit(30)
            )
        ).all()
    return [{"value": b.kode_batch,
             "label": f"{b.kode_batch} · {s} · {_rp(float(b.berat_total_kg))} kg"}
            for b, s in rows]


@router.get("/actions/pk-transfer")
async def pk_transfer_list(user: User = Depends(require_miniapp_user)) -> list[dict]:
    _require(can_transfer_pk(user))
    from sqlalchemy import select
    from app.models import MillingProcess
    from app.services.transfer import pending_transfer_kg
    from app.gudang1.services.milling import pk_jenis
    out: list[dict] = []
    async with SessionLocal() as db:
        procs = (
            await db.execute(select(MillingProcess).order_by(MillingProcess.kode_proses))
        ).scalars().all()
        for p in procs:
            avail = await pending_transfer_kg(db, p.id)
            if avail > 0:
                jns = await pk_jenis(db, p)
                out.append({"value": p.kode_proses,
                            "label": f"{p.kode_proses} · {jns or '-'} · {_rp(avail)} kg"})
    return out


# ─────────────────────── Aksi cepat: eksekusi (POST) ───────────────────────

def _err(e: Exception, default: str) -> HTTPException:
    return HTTPException(400, str(e.args[0]) if e.args else default)


async def _chat_confirm(user: User, text: str, bot_name: str = "gudang1") -> None:
    """Kirim konfirmasi aksi cepat ke chat Telegram user (best-effort)."""
    from app.bots.notify import notify_user
    await notify_user(user.telegram_user_id, "📱 _(aksi cepat)_ " + text, bot_name)


class GabahMasukReq(BaseModel):
    supplier: str
    berat: float
    kondisi: str
    plat: str | None = None
    tujuan: str | None = None  # utk kering: dryer / silo_a / silo_b


@router.post("/actions/gabah-masuk")
async def act_gabah_masuk(req: GabahMasukReq, user: User = Depends(require_miniapp_user)) -> dict:
    _require(await _is_g1_operator(user))
    if req.kondisi not in ("basah", "kering"):
        raise HTTPException(400, "Kondisi harus basah atau kering.")
    if not (req.plat or "").strip():
        raise HTTPException(400, "Plat truk wajib diisi.")
    # Tujuan WAJIB dipilih (tak boleh default/terlupa) — hindari salah tempat.
    if req.tujuan not in ("dryer", "silo_a", "silo_b"):
        raise HTTPException(400, "Pilih tujuan dulu: Dryer / Silo A / Silo B.")
    if req.kondisi == "basah" and req.tujuan != "dryer":
        raise HTTPException(400, "Gabah basah harus ke Dryer (tak bisa langsung ke silo).")

    from app.gudang1.services.purchase import create_purchase_batch
    from app.gudang1.services.drying import masuk_dryer, DryingError
    from app.gudang1.services.silo import masuk_silo, SiloError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await create_purchase_batch(
                db, user=u, nama_supplier=req.supplier, berat_kg=req.berat,
                kondisi_gabah=req.kondisi, no_polisi_truk=req.plat.strip(),
                kadar_air_awal_persen=None,
            )
        except Exception as e:  # noqa: BLE001
            raise _err(e, "Gagal mencatat gabah.")
        kode = r.batch.kode_batch

        # PENEMPATAN (agar tak nyangkut sebagai 'baru').
        tempat, warn = "", ""
        try:
            if req.tujuan == "dryer":
                await masuk_dryer(db, user=u, kode_batch_list=[kode])
                tempat = "🌫️ masuk dryer (menunggu — ketik `mulai pengeringan` saat dipanaskan)"
            else:  # silo_a / silo_b (kering langsung)
                silo = "A" if req.tujuan == "silo_a" else "B"
                await masuk_silo(db, user=u, nama_silo=silo, kode_lot=None, kode_batch=kode)
                tempat = f"🏗️ masuk Silo {silo} (kering menunggu — lot terbentuk saat digiling)"
        except (DryingError, SiloError) as e:
            warn = f"\n⚠️ Belum ditempatkan: {e.args[0] if e.args else 'gagal'}. Tempatkan manual."

    pesan = f"✓ Gabah *{kode}* ({req.kondisi}) tercatat" + (f".\n{tempat}." if tempat else ".") + warn
    await _chat_confirm(user, pesan, "gudang1")
    return {"ok": True, "pesan": pesan}


class KadarAirReq(BaseModel):
    kode_lot: str
    kadar_air: float


@router.post("/actions/kadar-air")
async def act_kadar_air(req: KadarAirReq, user: User = Depends(require_miniapp_user)) -> dict:
    _require(await _is_g1_operator(user))
    from app.gudang1.services.drying import log_moisture
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            await log_moisture(db, user=u, kode_lot=req.kode_lot,
                               indikator=req.kadar_air, tes_manual=None)
        except Exception as e:  # noqa: BLE001
            raise _err(e, "Gagal update kadar air.")
    pesan = f"✓ Kadar air *{req.kode_lot}*: {req.kadar_air:g}%."
    await _chat_confirm(user, pesan, "gudang1")
    return {"ok": True, "pesan": pesan}


class HasilGilingReq(BaseModel):
    kode_proses: str
    berat_kumulatif: float


@router.post("/actions/hasil-giling")
async def act_hasil_giling(req: HasilGilingReq, user: User = Depends(require_miniapp_user)) -> dict:
    _require(await _is_g1_operator(user))
    from app.gudang1.services.milling import log_progress
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            await log_progress(db, user=u, kode_proses=req.kode_proses,
                               berat_kumulatif=req.berat_kumulatif)
        except Exception as e:  # noqa: BLE001
            raise _err(e, "Gagal update hasil giling.")
    pesan = f"✓ Hasil giling *{req.kode_proses}*: {req.berat_kumulatif:g} kg (kumulatif)."
    await _chat_confirm(user, pesan, "gudang1")
    return {"ok": True, "pesan": pesan}


class VerifyGabahReq(BaseModel):
    kode_batch: str
    metode: str
    nilai: float


@router.post("/actions/verify-gabah")
async def act_verify_gabah(req: VerifyGabahReq, user: User = Depends(require_miniapp_user)) -> dict:
    _require(can_see_financials(user))
    if req.metode not in ("per_kg", "total"):
        raise HTTPException(400, "Metode harus per_kg atau total.")
    from app.services.verification import get_batch_by_kode, verify_gabah_price
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        batch = await get_batch_by_kode(db, req.kode_batch)
        if batch is None:
            raise HTTPException(404, f"Batch {req.kode_batch} tidak ditemukan.")
        try:
            await verify_gabah_price(db, user=u, batch=batch,
                                     metode=req.metode, nilai_rupiah=req.nilai)
        except Exception as e:  # noqa: BLE001
            raise _err(e, "Gagal verifikasi harga.")
    pesan = f"✓ Harga gabah *{req.kode_batch}* diverifikasi & tersimpan."
    await _chat_confirm(user, pesan, "admin")
    return {"ok": True, "pesan": pesan}


class TransferReq(BaseModel):
    kode_proses: str
    tujuan: str
    berat: float | None = None


@router.post("/actions/transfer-pk")
async def act_transfer_pk(req: TransferReq, user: User = Depends(require_miniapp_user)) -> dict:
    _require(can_transfer_pk(user))
    from app.services.transfer import create_internal_transfer, TransferError
    async with SessionLocal() as db:
        u = await db.get(User, user.id)
        try:
            r = await create_internal_transfer(
                db, user=u, kode_proses=req.kode_proses,
                lokasi_tujuan=req.tujuan, berat=req.berat,
            )
        except TransferError as e:
            raise _err(e, "Gagal pemindahan PK.")
    jns = (r.jenis + " ") if r.jenis else ""
    pesan = f"✓ Pemindahan PK *{r.transfer.kode_transfer}*: {jns}→ {r.lokasi_label}."
    await _chat_confirm(user, pesan, "admin")
    return {"ok": True, "pesan": pesan}


# ─────────────────────────── Halaman Mini App ───────────────────────────

_HTML = """<!doctype html>
<html lang="id"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<title>Penggilingan Beras</title>
<script src="https://telegram.org/js/telegram-web-app.js"></script>
<style>
 :root{--bg:var(--tg-theme-bg-color,#f4f5f7);--card:var(--tg-theme-secondary-bg-color,#fff);
   --tx:var(--tg-theme-text-color,#16181c);--mut:var(--tg-theme-hint-color,#8a8f98);
   --ac:var(--tg-theme-button-color,#2c7be5);--acx:var(--tg-theme-button-text-color,#fff);--bd:rgba(128,128,128,.18)}
 *{box-sizing:border-box}
 body{margin:0;padding:14px;font-family:system-ui,-apple-system,sans-serif;background:var(--bg);color:var(--tx);font-size:15px;line-height:1.5}
 .top{display:flex;align-items:center;justify-content:space-between;gap:10px;margin:2px 2px 14px}
 .hi{font-size:18px;font-weight:600} .role{font-size:12px;color:var(--mut)}
 .pill{display:inline-block;padding:2px 9px;border-radius:999px;background:var(--ac);color:var(--acx);font-size:11px;font-weight:600;text-transform:capitalize}
 .btn{border:1px solid var(--bd);background:var(--card);color:var(--ac);border-radius:10px;padding:8px 12px;font-size:13px;font-weight:600}
 .btn.pri{background:var(--ac);color:var(--acx);border-color:var(--ac)}
 .card{background:var(--card);border:1px solid var(--bd);border-radius:14px;padding:13px 15px;margin-bottom:11px}
 .ct{font-size:13px;font-weight:600;color:var(--mut);margin:0 0 7px;letter-spacing:.02em}
 .cb{white-space:pre-wrap;word-break:break-word;margin:0;font-size:14px}
 .act{display:block;width:100%;text-align:left;background:var(--card);border:1px solid var(--bd);border-radius:10px;padding:11px 13px;margin-top:8px;font-size:14px;font-weight:500;color:var(--tx)}
 .muted{color:var(--mut);text-align:center;padding:30px 0}
 .err{color:#d93025;text-align:center;padding:24px 0}
 #modal{display:none;position:fixed;inset:0;background:rgba(0,0,0,.45);align-items:flex-end;justify-content:center;z-index:20}
 .sheet{background:var(--bg);width:100%;max-width:520px;border-radius:16px 16px 0 0;padding:18px 16px 24px;max-height:90vh;overflow:auto}
 .sheet h3{margin:0 0 12px;font-size:16px}
 .sheet label{font-size:12px;color:var(--mut);display:block;margin-top:6px}
 .sheet select,.sheet input{width:100%;padding:10px;margin:4px 0 6px;border:1px solid var(--bd);border-radius:9px;background:var(--card);color:var(--tx);font-size:16px}
 .row{display:flex;gap:10px;margin-top:12px} .row .btn{flex:1;text-align:center;padding:11px}
 #toast{display:none;position:fixed;left:50%;bottom:24px;transform:translateX(-50%);background:#16181c;color:#fff;padding:10px 16px;border-radius:10px;font-size:13px;z-index:30;max-width:90%;text-align:center}
</style></head>
<body>
 <div class="top">
   <div><div class="hi" id="hi">Memuat…</div><div class="role" id="ts"></div></div>
   <button class="btn" onclick="load()">↻ Segarkan</button>
 </div>
 <div id="app"><div class="muted">Memuat data…</div></div>
 <div id="modal" onclick="if(event.target.id==='modal')closeModal()"></div>
 <div id="toast"></div>
<script>
 const tg = window.Telegram && window.Telegram.WebApp;
 if (tg){ tg.ready(); tg.expand(); }
 const H = {Authorization: "tma " + ((tg && tg.initData) || "")};
 let MENU = {};
 function esc(s){const d=document.createElement("div");d.textContent=s==null?"":s;return d.innerHTML;}
 function val(id){const e=document.getElementById(id);return e?e.value:"";}
 function toast(m){const t=document.getElementById("toast");t.textContent=m;t.style.display="block";clearTimeout(t._t);t._t=setTimeout(()=>t.style.display="none",2600);}
 async function getJSON(u){const r=await fetch(u,{headers:H});if(!r.ok){const e=await r.json().catch(()=>({}));throw (e.detail||("HTTP "+r.status));}return r.json();}
 async function post(u,b){const r=await fetch(u,{method:"POST",headers:{...H,"Content-Type":"application/json"},body:JSON.stringify(b)});const j=await r.json().catch(()=>({}));if(!r.ok)throw (j.detail||("HTTP "+r.status));return j;}
 function closeModal(){document.getElementById("modal").style.display="none";}

 async function load(){
   const app=document.getElementById("app");
   try{
     const d = await getJSON("/miniapp/dashboard");
     document.getElementById("hi").textContent="Halo, "+d.user.nama;
     document.getElementById("ts").innerHTML='<span class="pill">'+esc(d.user.role)+'</span>';
     let html="";
     let menu=[]; try{ menu = await getJSON("/miniapp/actions/menu"); }catch(e){}
     if(menu.length){
       MENU={}; menu.forEach(a=>MENU[a.id]=a);
       html += '<div class="card"><p class="ct">⚡ Aksi cepat</p>'+
         menu.map(a=>'<button class="act" onclick="openAction(\\''+a.id+'\\')">'+esc(a.label)+'</button>').join('')+'</div>';
     }
     html += d.sections.map(s=>'<div class="card"><p class="ct">'+esc(s.icon+" "+s.title)+'</p><pre class="cb">'+esc(s.body)+'</pre></div>').join("");
     app.innerHTML = html || '<div class="muted">Belum ada data.</div>';
   }catch(err){
     document.getElementById("hi").textContent="Gagal masuk";
     app.innerHTML='<div class="err">'+esc(String(err))+'</div>';
   }
 }

 function openAction(id){
   const a=MENU[id]; if(!a)return;
   let inner="";
   a.fields.forEach(f=>{
     inner+='<label>'+esc(f.label)+'</label>';
     if(f.type==="select"){
       inner+='<select data-name="'+f.name+'">'+f.options.map(o=>'<option value="'+esc(o[0])+'">'+esc(o[1])+'</option>').join('')+'</select>';
     }else if(f.type==="remote"){
       inner+='<select data-name="'+f.name+'" id="rem_'+f.name+'"><option>memuat…</option></select>';
     }else{
       inner+='<input data-name="'+f.name+'" type="'+(f.type==="number"?"number":"text")+'" inputmode="'+(f.type==="number"?"decimal":"text")+'">';
     }
   });
   const m=document.getElementById("modal");
   m.innerHTML='<div class="sheet"><h3>'+esc(a.label)+'</h3>'+inner+
     '<div class="row"><button class="btn" onclick="closeModal()">Batal</button><button class="btn pri" id="ok">Simpan</button></div></div>';
   m.style.display="flex";
   a.fields.forEach(f=>{ if(f.type==="remote"){ getJSON(f.source).then(list=>{
       const s=document.getElementById("rem_"+f.name);
       s.innerHTML = list.length? list.map(o=>'<option value="'+esc(o.value)+'">'+esc(o.label)+'</option>').join('') : '<option value="">(tidak ada pilihan)</option>';
     }).catch(()=>{}); }});
   document.getElementById("ok").onclick=async()=>{
     const btn=document.getElementById("ok"); btn.disabled=true;
     try{
       const body={};
       m.querySelectorAll("[data-name]").forEach(el=>{ let v=el.value; if(el.type==="number") v=(v===""?null:parseFloat(v)); body[el.getAttribute("data-name")]=v; });
       const res=await post(a.post, body);
       closeModal(); toast(res.pesan||"Berhasil ✓"); load();
     }catch(e){ toast(String(e)); btn.disabled=false; }
   };
 }
 load();
</script></body></html>"""


@router.get("", response_class=HTMLResponse)
async def launch() -> HTMLResponse:
    """Halaman Mini App (dari tombol menu bot). Login otomatis via initData."""
    return HTMLResponse(_HTML)
