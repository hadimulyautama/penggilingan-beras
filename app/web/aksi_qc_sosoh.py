"""Pencatatan dua tahap: ambil sampel di mesin, isi hasil pemeriksaan kemudian."""
from datetime import datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select

from app.config import settings
from app.database import SessionLocal, now_local
from app.models import PolishingProcess, SampelQcSosoh, User
from app.peran import can_see_financials
from app.services import qc_sosoh as svc
from app.web.deps import pengguna_aksi

router = APIRouter(prefix="/api/actions", tags=["api"])


def spesifikasi():
    return [
        {"akses": "admin", "id": "sampel_qc_sosoh", "label": "Ambil sampel QC beras",
         "post": "/api/actions/sampel-qc-sosoh",
         "hint": "Boleh sebelum hasil timbang. Pilih jenis beras saat sampel diambil; pergantian garapan tidak mengubah sampel ini. Waktu kosong berarti sekarang (WIB).",
         "fields": [
             {"name": "kode_proses", "label": "Proses sosoh", "type": "remote", "source": "/api/actions/proses-qc-sosoh", "kosong": "Belum ada proses sosoh."},
             {"name": "jenis", "label": "Jenis beras saat sampel diambil", "type": "select", "options": [["", "— pilih jenis beras —"], *[[k, v] for k, v in svc.JENIS.items()]]},
             {"name": "waktu_sampel", "label": "Waktu pengambilan WIB (kosong: sekarang)", "type": "datetime-local"}]},
        {"akses": "admin", "id": "qc_sosoh", "label": "Isi hasil QC beras",
         "post": "/api/actions/qc-sosoh",
         "hint": "Pilih nomor sampel. Proses, jenis beras, dan waktu pengambilan mengikuti sampel tersebut. Isi minimal satu hasil pemeriksaan.",
         "fields": [
             {"name": "sampel_id", "label": "Sampel yang diperiksa", "type": "remote", "source": "/api/actions/sampel-qc-sosoh-menunggu", "kosong": "Semua sampel sudah diisi hasilnya. Catat pengambilan sampel baru terlebih dahulu."},
             *[{"name": k, "label": svc.label_komponen(k), "type": "text", "inputmode": "decimal"} for k in svc.ANGKA],
             {"name": "catatan_lab", "label": "Catatan lab", "type": "text"}]},
        {"akses": "admin", "id": "batalkan_sampel_qc_sosoh", "label": "Batalkan sampel QC beras",
         "post": "/api/actions/batalkan-sampel-qc-sosoh",
         "hint": "Sampel yang salah dicatat dikeluarkan dari estimasi. Identitas dan hasil lab tetap tersimpan dalam riwayat.",
         "fields": [
             {"name": "sampel_id", "label": "Sampel yang dibatalkan", "type": "remote", "source": "/api/actions/sampel-qc-sosoh-aktif", "kosong": "Belum ada sampel aktif."},
             {"name": "alasan", "label": "Alasan pembatalan", "type": "text", "wajib": True}]}]


async def _izin(user):
    if not can_see_financials(user):
        raise HTTPException(403, "Pencatatan QC hanya untuk Admin ke atas.")
    from app.web.api import _wajib_mutu
    await _wajib_mutu()


class SampelReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kode_proses: str
    jenis: str
    kunci_kiriman: str | None = Field(default=None, min_length=1, max_length=80)
    waktu_sampel: datetime | None = None

class HasilReq(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    sampel_id: int = Field(gt=0)
    kadar_air: Decimal | None = Field(default=None, ge=0, le=100)
    broken_persen: Decimal | None = Field(default=None, ge=0, le=100)
    md: Decimal | None = Field(default=None, ge=0, le=svc.BATAS_ANGKA)
    transparant: Decimal | None = Field(default=None, ge=0, le=svc.BATAS_ANGKA)
    whiteness: Decimal | None = Field(default=None, ge=0, le=svc.BATAS_ANGKA)
    catatan_lab: str | None = Field(default=None, max_length=500)

    @field_validator(*svc.ANGKA, mode='before')
    @classmethod
    def desimal_berkoma(cls, nilai):
        if isinstance(nilai, str):
            return nilai.strip().replace(',', '.') or None
        return nilai


class BatalReq(BaseModel):
    model_config = ConfigDict(extra="forbid")
    sampel_id: int = Field(gt=0)
    alasan: str = Field(min_length=1, max_length=500)


@router.get("/proses-qc-sosoh")
async def proses_qc(user: User = Depends(pengguna_aksi)):
    await _izin(user)
    async with SessionLocal() as db:
        rows = (await db.scalars(select(PolishingProcess).where(PolishingProcess.status == 'proses')
                                  .order_by(PolishingProcess.id.desc()))).all()
    return [dict(value=p.kode_proses, label=f"{p.kode_proses} · {'berjalan' if p.status == 'proses' else 'selesai'}") for p in rows]


@router.get("/sampel-qc-sosoh-menunggu")
async def sampel_menunggu(user: User = Depends(pengguna_aksi)):
    await _izin(user)
    async with SessionLocal() as db:
        rows = (await db.execute(select(SampelQcSosoh, PolishingProcess.kode_proses)
            .join(PolishingProcess, PolishingProcess.id == SampelQcSosoh.polishing_process_id)
            .where(SampelQcSosoh.hasil_pada.is_(None), SampelQcSosoh.dibatalkan_pada.is_(None))
            .order_by(SampelQcSosoh.waktu_sampel, SampelQcSosoh.id))).all()
    from app.database import berzona
    return [dict(value=str(q.id), label=f"Sampel #{q.id} · {kode} · {svc.JENIS[q.jenis]} · {berzona(q.waktu_sampel):%d/%m %H:%M}") for q, kode in rows]


@router.get("/sampel-qc-sosoh-aktif")
async def sampel_aktif(user: User = Depends(pengguna_aksi)):
    await _izin(user)
    async with SessionLocal() as db:
        rows = (await db.execute(select(SampelQcSosoh, PolishingProcess.kode_proses)
            .join(PolishingProcess, PolishingProcess.id == SampelQcSosoh.polishing_process_id)
            .where(SampelQcSosoh.dibatalkan_pada.is_(None))
            .order_by(SampelQcSosoh.waktu_sampel.desc(), SampelQcSosoh.id.desc()))).all()
    from app.database import berzona
    return [dict(value=str(q.id), label=f"Sampel #{q.id} · {kode} · {svc.JENIS[q.jenis]} · {berzona(q.waktu_sampel):%d/%m %H:%M}") for q, kode in rows]


@router.post("/sampel-qc-sosoh")
async def catat_sampel(req: SampelReq, user: User = Depends(pengguna_aksi)):
    await _izin(user)
    try:
        waktu = req.waktu_sampel or now_local()
        if waktu.tzinfo is None:
            waktu = waktu.replace(tzinfo=ZoneInfo(settings.app_timezone))
        async with SessionLocal() as db:
            q = await svc.ambil_sampel(db, user=user, kode_proses=req.kode_proses, jenis=req.jenis, waktu_sampel=waktu, kunci_kiriman=req.kunci_kiriman)
    except svc.QcSosohError as e:
        raise HTTPException(400, str(e)) from e
    return dict(ok=True, sampel_id=q.id, jenis=q.jenis, waktu_sampel=q.waktu_sampel.isoformat(),
                pesan=f"Sampel #{q.id} · {svc.JENIS[q.jenis]} tercatat. Hasil QC dapat diisi setelah pemeriksaan selesai.")


@router.post("/qc-sosoh")
async def catat_hasil(req: HasilReq, user: User = Depends(pengguna_aksi)):
    await _izin(user)
    try:
        async with SessionLocal() as db:
            q = await svc.isi_hasil(db, user=user, **req.model_dump())
    except svc.QcSosohError as e:
        raise HTTPException(400, str(e)) from e
    return dict(ok=True, sampel_id=q.id, pesan=f"QC sampel #{q.id} tersimpan sebagai {svc.JENIS[q.jenis]} sesuai pengambilan awal.")


@router.post("/batalkan-sampel-qc-sosoh")
async def batalkan(req: BatalReq, user: User = Depends(pengguna_aksi)):
    await _izin(user)
    try:
        async with SessionLocal() as db:
            q = await svc.batalkan_sampel(db, user=user, **req.model_dump())
    except svc.QcSosohError as e:
        raise HTTPException(400, str(e)) from e
    return dict(ok=True, pesan=f"Sampel #{q.id} dibatalkan. Riwayat tetap tersimpan; estimasi mengikuti sampel yang aktif.")
