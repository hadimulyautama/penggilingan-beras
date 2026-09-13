"""API internal untuk Operasi Gudang 2 (repo `gudang2/`, service `gudang2`).

Kenapa ada: pemilik memutuskan 12 September 2026 bahwa aplikasi operator
Gudang 2 berdiri sebagai service sendiri, dan — seperti Meja Administrasi —
TIPIS di atas Pos Produksi: "semua tidak punya tabel, database dipakai
bersama, agar semuanya terintegrasi". Tabel dan aturan tetap milik repo ini;
gudang2 menggambar dan meneruskan.

Yang ada di sini hanyalah bungkus JSON atas layanan yang sudah ada:
`services.berjalan.untuk_operator_gudang2`, `layar._petak_g2`, dan stok
barang jadi. Aksi tulis (`/miniapp/*`), laporan (`/api/laporan/*`), masuk,
akun, dan ganti sandi TIDAK dibungkus ulang — gudang2 memanggil pintu yang
sama dengan Meja (`/internal/meja/masuk`, `/internal/meja/saya`,
`/internal/meja/akun/*`), karena orangnya sama: akun `produksi_akun`.

Keamanan: token service & header akun yang SAMA dengan Meja
(`X-Internal-Token`, `X-Meja-Akun`, `X-Meja-Versi`; `MEJA_API_TOKEN`).
Satu token untuk dua service satelit — keduanya berjalan di jaringan privat
Railway yang sama, dan dua rahasia untuk satu pintu hanya menggandakan
tempat bocornya. Gerbang perannya operator Gudang 2 (admin ke atas ikut
lolos, seperti di seluruh `/miniapp/*`).
"""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select

from app.database import SessionLocal
from app.models import ProduksiAkun
from app.web.meja_api import _ser, akun_meja

router = APIRouter(prefix="/internal/gudang2", tags=["internal-gudang2"])
log = logging.getLogger("web.gudang2_api")


async def akun_operator_g2(akun: ProduksiAkun = Depends(akun_meja)) -> ProduksiAkun:
    """Operator Gudang 2 (atau admin ke atas) — gerbang yang sama dengan
    aksi `/miniapp/*` Gudang 2, supaya layar dan aksinya tak pernah berbeda
    pendapat tentang siapa yang boleh."""
    from app.web.miniapp import _is_g2_operator

    if not await _is_g2_operator(akun.user):
        raise HTTPException(403, "Hanya untuk operator Gudang 2.")
    return akun


def _kartu_json(b) -> dict:
    """Berjalan → JSON. `lencana` dihitung dari daftar yang sama."""
    return {
        "menunggu": _ser(b.menunggu), "berjalan": _ser(b.berjalan),
        "transit": _ser(b.transit),
        "lencana": {"MENUNGGU": b.jumlah_menunggu, "BERJALAN": b.jumlah_berjalan,
                    "KEPUTUSAN": 0},
    }


@router.get("/beranda")
async def beranda(akun: ProduksiAkun = Depends(akun_operator_g2)) -> dict:
    from app.services.berjalan import untuk_operator_gudang2
    from app.web.layar import _petak_g2

    async with SessionLocal() as db:
        b = await untuk_operator_gudang2(db)
        petak = await _petak_g2(db)
    return {**_kartu_json(b), "petak": [{"judul": None, "sel": petak}]}


@router.get("/kartu")
async def kartu(akun: ProduksiAkun = Depends(akun_operator_g2)) -> dict:
    """Antrean (tumpukan + silo) dan mesin yang menyala — dipakai Antrian
    tunggu, Sedang berjalan, dan lencana laci."""
    from app.services.berjalan import untuk_operator_gudang2

    async with SessionLocal() as db:
        return _kartu_json(await untuk_operator_gudang2(db))


#: Urutan & nama jenis di layar Stok. Kategori SKU produksi → jenis layar.
_GRADES = ("premium", "medsuper", "medium", "sayur")
_NAMA_KATEGORI = {"beras_b": "Beras B (olah ulang)", "menir": "Menir",
                  "broken": "Broken", "reject": "Reject"}


@router.get("/stok")
async def stok(akun: ProduksiAkun = Depends(akun_operator_g2)) -> dict:
    """Stok = PRODUK & HASIL SAMPING (keputusan pemilik 12 September 2026),
    bukan PK — PK adalah antrean, di `/kartu`.

    Satu kartu = satu SKU × mutu (jenis · merk · kemasan · ukuran); stoknya
    masuk − keluar lewat `hitung_stok_finished_goods`, rinciannya per proses
    penyosohan asal supaya "dari sosohan mana" tetap terjawab saat ada
    keluhan mutu. Bekatul curah berdiri sendiri: ia tak pernah dikemas.
    """
    from app.penggilingan.gudang2.models import PolishingProcess
    from app.penggilingan.inventory import finished_goods as bj
    from app.penggilingan.inventory.models import (
        Brand, ByproductStock, FinishedGoodsStock, PackageSize, PackagingMaterial,
        ProductSku, RiceQualityStandard)
    from app.services.berjalan import untuk_operator_gudang2

    async with SessionLocal() as db:
        baris = (await db.execute(
            select(FinishedGoodsStock, ProductSku, Brand.nama, PackagingMaterial.nama,
                   PackageSize.ukuran_kg, RiceQualityStandard.kode, RiceQualityStandard.nama,
                   PolishingProcess.kode_proses)
            .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
            .join(PackagingMaterial, PackagingMaterial.id == ProductSku.packaging_material_id)
            .join(PackageSize, PackageSize.id == ProductSku.package_size_id)
            .join(Brand, Brand.id == ProductSku.brand_id, isouter=True)
            .join(RiceQualityStandard,
                  RiceQualityStandard.id == FinishedGoodsStock.rice_quality_standard_id,
                  isouter=True)
            .join(PolishingProcess,
                  (PolishingProcess.id == FinishedGoodsStock.source_id)
                  & (FinishedGoodsStock.source_type == "polishing"), isouter=True)
            .order_by(FinishedGoodsStock.waktu.desc())
        )).all()

        kartu: dict[tuple, dict] = {}
        for fg, sku, merk, kemasan, ukuran, mutu_kode, mutu_nama, pol in baris:
            kunci = (sku.id, fg.rice_quality_standard_id)
            k = kartu.get(kunci)
            if k is None:
                stok_ = await bj.hitung_stok_finished_goods(db, sku.id, fg.rice_quality_standard_id)
                if stok_["karung"] <= 0 and stok_["kg"] <= 0:
                    kartu[kunci] = None
                    continue
                if sku.kategori == "beras_putih":
                    jenis = (mutu_kode or "").lower() or "beras_putih"
                    nama = mutu_nama or "Beras putih"
                else:
                    jenis = sku.kategori
                    nama = _NAMA_KATEGORI.get(sku.kategori, sku.kategori.title())
                if merk:
                    nama += f" · {merk}"
                k = kartu[kunci] = {
                    "jenis": jenis, "nama": nama, "kemasan": f"{kemasan} {ukuran} kg",
                    "ukuran": int(ukuran), "karung": stok_["karung"], "kg": stok_["kg"],
                    "asal": [], "_pol": {}}
            if k is None:
                continue
            if pol:
                a = k["_pol"].setdefault(pol, [0, 0.0])
                a[0] += int(fg.jumlah_karung)
                a[1] += float(fg.berat_total_kg)
        produk, samping = [], []
        for k in kartu.values():
            if k is None:
                continue
            k["asal"] = [(pol, f"{kg:,.0f} kg".replace(",", "."), f"{n} karung")
                         for pol, (n, kg) in k.pop("_pol").items()]
            (produk if k["jenis"] in _GRADES or k["jenis"] == "beras_putih" else samping).append(k)

        # Bekatul curah — masuk − keluar, rincian per proses.
        curah = await bj.hitung_stok_bekatul(db)
        if curah > 0:
            per_pol = (await db.execute(
                select(PolishingProcess.kode_proses, ByproductStock.berat_kg)
                .join(PolishingProcess, PolishingProcess.id == ByproductStock.source_id)
                .where(ByproductStock.jenis_produk == "bekatul",
                       ByproductStock.source_type == "polishing")
                .order_by(ByproductStock.waktu.desc())
            )).all()
            samping.append({
                "jenis": "bekatul", "nama": "Bekatul", "kemasan": "curah", "ukuran": 0,
                "karung": 0, "kg": curah,
                "asal": [(kode, f"{float(kg):,.0f} kg".replace(",", "."), "curah")
                         for kode, kg in per_pol][:8]})
        urut = {j: n for n, j in enumerate(
            ("premium", "medsuper", "medium", "sayur", "beras_putih", "beras_b",
             "bekatul", "menir", "broken", "reject"))}
        produk.sort(key=lambda k: (urut.get(k["jenis"], 99), k["nama"], k["ukuran"]))
        samping.sort(key=lambda k: (urut.get(k["jenis"], 99), k["nama"], k["ukuran"]))
        b = await untuk_operator_gudang2(db)
    return {"produk": produk, "samping": samping, "lencana": _kartu_json(b)["lencana"]}
