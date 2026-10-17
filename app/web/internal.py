"""API internal PRODUKSI — satu-satunya pintu baca data pabrik untuk Kantor AI.

Alasan ada: Kantor AI berpisah repo & service. Ia TIDAK boleh mengimpor kode
produksi lagi (`app.ai.agent`, `app.services.analytics`, `app.services.dashboard`),
tapi tetap perlu tiga hal itu. Jadi produksi menyediakannya sebagai JSON kecil
ber-token, Kantor memanggilnya lewat `klien_produksi`.

Keamanan:
  - Aktif hanya bila env `INTERNAL_API_TOKEN` diisi (kosong → 404, seperti /dashboard).
  - Setiap permintaan wajib membawa header `X-Internal-Token` yang sama persis.
  - Agent hanya membaca. Endpoint operasi pengiriman yang terpisah hanya
    menautkan/verifikasi tiket untuk pengguna bersama yang dikirim Timbangan.
  - Data uang (HPP/harga) hanya keluar bila pemanggil mengirim financial=true —
    keputusan hak akses tetap di sisi Kantor (RBAC-nya), sama seperti sebelum pisah.
"""
from __future__ import annotations

import hmac
import logging

from fastapi import APIRouter, Header, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.config import settings
from app.database import SessionLocal
from hmu_core.proses_db import ProsesTerpadu

router = APIRouter(prefix="/internal", tags=["internal"])
log = logging.getLogger("web.internal")


def _pastikan_token(token: str | None) -> None:
    if not settings.internal_api_token:
        raise HTTPException(status_code=404, detail="API internal tidak aktif.")
    if not token or not hmac.compare_digest(token, settings.internal_api_token):
        raise HTTPException(status_code=403, detail="Token internal tidak valid.")


def _kunci_teks(value: str | None) -> str:
    return " ".join((value or "").strip().casefold().split())


def _kunci_nopol(value: str | None) -> str:
    return "".join(c for c in (value or "").upper() if c.isalnum())


async def _cocokkan_pengiriman_tiket(db, tid: int):
    """Cari satu pengiriman dimuat dari tiket keluar berdasarkan pelanggan+nopol.

    Kedua nilai ini berasal dari tahap timbang pertama dan tahap muat. Bila
    salah satunya kosong atau hasilnya ganda, integrasi sengaja tidak menebak.
    """
    from sqlalchemy import text
    from app.penggilingan.inventory.models import OUT_DIMUAT, OUT_SELESAI
    from app.services import barang_keluar as bk

    tiket = (await db.execute(text("""
        SELECT t.id, t.arah, t.status_transaksi, t.status_tiket,
               t.nomor_polisi, t.pelanggan_id,
               COALESCE(p.nama_pelanggan, t.pihak_nama) AS pihak
          FROM timbangan_transaksi t
          LEFT JOIN pelanggan p ON p.id = t.pelanggan_id
         WHERE t.id = :tid
    """), {"tid": int(tid)})).mappings().first()
    if (not tiket or tiket["arah"] != "KELUAR"
            or tiket["status_transaksi"] != "AKTIF"
            or tiket["status_tiket"] not in ("TERBUKA", "SELESAI")):
        raise HTTPException(status_code=409, detail="Tiket bukan timbang keluar aktif.")
    nopol = _kunci_nopol(tiket["nomor_polisi"])
    pihak = _kunci_teks(tiket["pihak"])
    if not nopol or not pihak:
        raise HTTPException(status_code=409, detail="Tiket belum memiliki pelanggan dan nomor polisi untuk pencocokan.")

    from app.models import OutgoingRecord
    dipilih = (await db.execute(select(OutgoingRecord).where(
        OutgoingRecord.timbangan_transaksi_id == int(tid),
        OutgoingRecord.status == "perintah").limit(1))).scalar_one_or_none()
    if dipilih is not None:
        raise HTTPException(status_code=409, detail=f"Armada sudah dipilih {dipilih.kode}, tetapi muatan belum dinyatakan selesai di Produksi.")

    candidates = await bk.daftar(db, status=(OUT_DIMUAT, OUT_SELESAI), batas=500)
    cocok = []
    for rec, items in candidates:
        if _kunci_nopol(rec.no_polisi) != nopol:
            continue
        if tiket["pelanggan_id"] is not None and rec.pelanggan_id is not None:
            identitas_pelanggan_sama = rec.pelanggan_id == tiket["pelanggan_id"]
        else:
            identitas_pelanggan_sama = _kunci_teks(rec.nama_pembeli) == pihak
        if (identitas_pelanggan_sama
                and rec.timbangan_transaksi_id in (None, int(tid))
                and (rec.status == OUT_DIMUAT
                     or rec.timbangan_transaksi_id == int(tid))):
            cocok.append((rec, items))
    # Tiket yang sudah lebih dulu ditaut hanya boleh kembali ke transaksi itu.
    sudah = [(rec, items) for rec, items in cocok
             if rec.timbangan_transaksi_id == int(tid)]
    if sudah:
        cocok = sudah
    if len(cocok) != 1:
        alasan = "belum ada perintah Produksi yang dimuat" if not cocok else "cocok dengan lebih dari satu perintah"
        raise HTTPException(status_code=409, detail=f"Pencocokan ditahan: {alasan}; periksa pelanggan dan nomor polisi.")
    return tiket, cocok[0][0], cocok[0][1]


class TanyaIn(BaseModel):
    pertanyaan: str
    role: str = "admin"
    financial: bool = False


class HppIn(BaseModel):
    harga_gabah: float | None = None
    rendemen_persen: float | None = None
    kondisi: str = "basah"
    langsung_silo: bool = False
    berat_bahan: float | None = None
    berat_hasil: float | None = None


@router.get("/pengiriman/tiket/{tid}/muatan")
async def pengiriman_muatan_tiket(
    tid: int, x_internal_token: str | None = Header(default=None),
) -> dict:
    """Rincian barang yang benar-benar dicatat dimuat, untuk layar timbang 2."""
    _pastikan_token(x_internal_token)
    async with SessionLocal() as db:
        _tiket, rec, items = await _cocokkan_pengiriman_tiket(db, tid)
        muatan = []
        from app.models import KemasanTara, PackagingMaterial, PackageSize
        for item in items:
            tara = 0
            produk = {}
            if item.item_type == "byproduct_curah":
                kode = (item.jenis_byproduct or "").upper()
                label = (item.jenis_byproduct or "Hasil samping").title() + " (curah)"
            elif item.item_type == "finished_goods":
                from app.penggilingan.inventory.models import ProductSku
                from app.services.stok import jenis_produk
                from hmu_core import (Brand, PackageSize, PackagingMaterial,
                                      RiceQualityStandard)

                detail = (await db.execute(
                    select(ProductSku.kategori, RiceQualityStandard.kode,
                           Brand.nama, PackagingMaterial.nama, PackageSize.ukuran_kg,
                           ProductSku.brand_id, ProductSku.packaging_material_id, ProductSku.package_size_id)
                    .select_from(ProductSku)
                    .join(RiceQualityStandard,
                          RiceQualityStandard.id == item.rice_quality_standard_id,
                          isouter=True)
                    .join(Brand, Brand.id == ProductSku.brand_id, isouter=True)
                    .join(PackagingMaterial,
                          PackagingMaterial.id == ProductSku.packaging_material_id)
                    .join(PackageSize, PackageSize.id == ProductSku.package_size_id)
                    .where(ProductSku.id == item.product_sku_id)
                )).first()
                if detail is None:
                    raise HTTPException(status_code=409, detail="SKU muatan tidak ditemukan di Produksi.")
                tara = await db.scalar(select(KemasanTara.tara_per_karung_kg).where(
                    KemasanTara.packaging_material_id == detail[6],
                    KemasanTara.package_size_id == detail[7]))
                if tara is None:
                    raise HTTPException(409, 'Tara kemasan belum ditetapkan. Isi di Pengaturan Pos Timbang.')
                produk = dict(kualitas_id=item.rice_quality_standard_id,
                    merek_produk_id=detail[5], packaging_material_id=detail[6], package_size_id=detail[7])
                jenis = jenis_produk(detail[0], detail[1])
                if jenis in ("broken", "menir", "bekatul", "reject"):
                    kode, label = jenis.upper(), jenis.title()
                else:
                    kode = "BERAS"
                    label = "Beras putih" + (f" · {jenis}" if jenis != "beras_putih" else "")
                kemasan = " · ".join(str(x) for x in detail[2:4] if x)
                if detail[4]:
                    kemasan += (" · " if kemasan else "") + f"{detail[4]} kg"
                if kemasan:
                    label += f" · {kemasan}"
            elif item.item_type in ("pk_langsung", "pk_g2"):
                kode, label = "BERAS_PK", "Beras pecah kulit (PK)"
                tara = await db.scalar(select(KemasanTara.tara_per_karung_kg)
                    .join(PackagingMaterial, PackagingMaterial.id == KemasanTara.packaging_material_id)
                    .join(PackageSize, PackageSize.id == KemasanTara.package_size_id)
                    .where(PackagingMaterial.kode == 'karung_pk', PackageSize.ukuran_kg == 50))
                if tara is None:
                    raise HTTPException(409, 'Tara karung PK 50 kg belum ditetapkan di Pengaturan Pos Timbang.')
            elif item.item_type == "gabah_langsung":
                kode, label = "GABAH_KERING", "Gabah kering"
                # Jalur gabah menyebut karung 50 kg tanpa jenis bahannya.
                # Aman hanya selama seluruh tara 50 kg sepakat. Bila kelak
                # dibedakan, jangan menebak jenis karung yang benar-benar dimuat.
                taras = (await db.scalars(select(KemasanTara.tara_per_karung_kg)
                    .join(PackageSize, PackageSize.id == KemasanTara.package_size_id)
                    .join(PackagingMaterial, PackagingMaterial.id == KemasanTara.packaging_material_id)
                    .where(PackageSize.ukuran_kg == 50, PackagingMaterial.aktif.is_(True)).distinct())).all()
                if len(taras) != 1:
                    raise HTTPException(409, 'Jenis karung gabah 50 kg perlu dirinci karena tara kemasannya berbeda.')
                tara = taras[0]
            else:
                raise HTTPException(status_code=409, detail=f"Jenis muatan {item.item_type} belum didukung integrasi timbang.")
            muatan.append({
                "jenis_kode": kode,
                "nama": label,
                "berat_kg": float(item.berat_kg or 0),
                "jumlah_karung": int(item.jumlah_karung or 0),
                "tara_per_karung_kg": str(tara),
                **produk,
            })
        return {"kode_perintah": rec.kode, "pelanggan": rec.nama_pembeli,
                "nomor_polisi": rec.no_polisi, "muatan": muatan}


@router.post("/pengiriman/tiket/{tid}/verifikasi")
async def verifikasi_pengiriman_tiket(
    tid: int,
    x_operator_akun: int = Header(alias="X-Operator-Akun"),
    x_internal_token: str | None = Header(default=None),
) -> dict:
    """Tautkan tiket dan verifikasi otomatis untuk muatan yang cocok."""
    _pastikan_token(x_internal_token)
    from hmu_identitas.model import Akun
    from hmu_core import User
    from app.services import barang_keluar as bk
    from app.penggilingan.inventory.models import OUT_SELESAI

    async with SessionLocal() as db:
        _tiket, rec, _items = await _cocokkan_pengiriman_tiket(db, tid)
        if rec.status == OUT_SELESAI and rec.timbangan_transaksi_id == int(tid):
            return {"selesai": True, "kode_perintah": rec.kode,
                    "catatan": "Sudah tertaut dan terverifikasi sebelumnya."}
        akun = await db.get(Akun, int(x_operator_akun))
        user = await db.get(User, akun.user_id) if akun else None
        if user is None or user.status != "aktif":
            raise HTTPException(status_code=403, detail="Akun operator Timbangan tidak terhubung ke pengguna aktif Produksi.")
        if rec.timbangan_transaksi_id not in (None, int(tid)):
            raise HTTPException(status_code=409, detail="Perintah ini sudah tertaut ke tiket timbang lain.")
        try:
            _rec, catatan = await bk.verifikasi(
                db, user=user, rec_id=rec.id, timbangan_transaksi_id=int(tid),
            )
            return {"selesai": True, "kode_perintah": rec.kode, "catatan": catatan}
        except bk.BarangKeluarError as exc:
            pesan = str(exc)
            # Jangan tautkan/menutup sebelum Admin memberi sebab selisih.
            # Tiket tetap tersedia di daftar verifikasi manual.
            if "melewati batas wajar" in pesan:
                return {"selesai": False, "peringatan": pesan,
                        "kode_perintah": rec.kode}
            raise HTTPException(status_code=409, detail=pesan) from exc


@router.post("/produksi/tanya")
async def produksi_tanya(
    body: TanyaIn, x_internal_token: str | None = Header(default=None)
) -> dict:
    """Delegasikan pertanyaan produksi ke AI Agent pabrik (read-only)."""
    _pastikan_token(x_internal_token)
    from app.ai import agent as agen_produksi

    pertanyaan = (body.pertanyaan or "").strip()
    if not pertanyaan:
        raise HTTPException(status_code=422, detail="Pertanyaan kosong.")
    reply = await agen_produksi.run_agent(
        text=pertanyaan, role=body.role, financial=body.financial,
    )
    return {"teks": reply.text or ""}


# Rute `/produksi/hpp` (simulasi what-if) DIBUANG 28 September 2026 bersama
# seluruh HPP: harga keluar dari Pos Produksi (keputusan pemilik). Yang
# memanggilnya dari luar akan menerima 404, dan itu jawaban yang benar —
# simulasi yang memakai tarif yang tak lagi dipelihara lebih buruk daripada
# tak ada simulasi.


@router.get("/produksi/operasional")
async def produksi_operasional(
    x_internal_token: str | None = Header(default=None)
) -> dict:
    """Ringkasan operasional hari ini (bahan briefing pagi Kantor)."""
    _pastikan_token(x_internal_token)
    from app.services.dashboard import dashboard_data

    async with SessionLocal() as db:
        data = await dashboard_data(db)
    return data.get("operasional", {}) or {}


@router.get("/produksi/proses")
async def produksi_proses(
    x_internal_token: str | None = Header(default=None),
    jenis: str | None = Query(default=None, max_length=40),
    status: str | None = Query(default=None, max_length=20),
    kode: str | None = Query(default=None, max_length=80),
    batas: int = Query(default=50, ge=1, le=100),
) -> dict:
    """Baca daftar proses operasional bersama untuk Kantor (read-only)."""
    _pastikan_token(x_internal_token)
    async with SessionLocal() as db:
        q = (select(ProsesTerpadu)
             .options(selectinload(ProsesTerpadu.arus))
             .order_by(ProsesTerpadu.waktu_mulai.desc().nullslast(),
                       ProsesTerpadu.id.desc())
             .limit(batas))
        if jenis:
            q = q.where(ProsesTerpadu.jenis == jenis.strip().lower())
        if status:
            q = q.where(ProsesTerpadu.status == status.strip().lower())
        if kode:
            q = q.where(ProsesTerpadu.kode.ilike(f"%{kode.strip()}%"))
        rows = (await db.execute(q)).scalars().unique().all()

    return {"proses": [{
        "aplikasi": row.aplikasi,
        "tabel_sumber": row.tabel_sumber,
        "id_sumber": row.id_sumber,
        "kode": row.kode,
        "jenis": row.jenis,
        "status": row.status,
        "pemilik": {"jenis": row.jenis_pemilik, "id": row.id_pemilik,
                    "nama": row.nama_pemilik},
        "waktu_mulai": row.waktu_mulai.isoformat() if row.waktu_mulai else None,
        "waktu_selesai": row.waktu_selesai.isoformat() if row.waktu_selesai else None,
        "pelaksana_id": row.pelaksana_id,
        "referensi_asal": row.referensi_asal or [],
        "bahan": [{"komoditas": a.komoditas,
                   "atribut": a.atribut_produk or {}, "berat_kg": float(a.berat_kg),
                   "referensi": a.referensi, "lokasi_id": a.lokasi_id,
                   "detail": a.detail or {}}
                  for a in row.arus if a.arah == "bahan"],
        "hasil": [{"komoditas": a.komoditas,
                   "atribut": a.atribut_produk or {}, "berat_kg": float(a.berat_kg),
                   "referensi": a.referensi, "lokasi_id": a.lokasi_id,
                   "detail": a.detail or {}}
                  for a in row.arus if a.arah == "hasil"],
        "metadata": row.metadata_domain or {},
    } for row in rows]}


@router.get('/retur/tiket/{tid}/muatan')
async def retur_muatan_tiket(
    tid: int, x_internal_token: str | None = Header(default=None),
) -> dict:
    """Rincian bongkar resmi; tidak mengirim harga atau menambah stok."""
    _pastikan_token(x_internal_token)
    from app.services.retur import baca_muatan
    async with SessionLocal() as db:
        try:
            return await baca_muatan(db, tid)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
