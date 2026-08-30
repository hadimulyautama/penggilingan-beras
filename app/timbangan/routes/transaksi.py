"""Rute transaksi: daftar, rincian, koreksi, pembatalan, cetak, pemeriksaan."""
from __future__ import annotations

from datetime import date, timedelta

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.timbangan import logic, service, setelan
from app.timbangan.db import get_db, hari_ini, sekarang
from app.timbangan.models import TimbanganAkun, TimbanganCetak
from app.timbangan.routes.pos import _angka
from app.timbangan.security import butuh_admin, butuh_akun, butuh_pengawas
from app.timbangan.web import PREFIX, redirect, render

router = APIRouter(prefix=PREFIX)

#: Kategori penutup pemeriksaan. Sengaja tidak ada kategori "curang":
#: sistem mencatat temuan, manusia yang menyimpulkan.
KATEGORI_HASIL = {
    "SELISIH_WAJAR": "Selisih masih wajar",
    "SALAH_CATAT": "Salah catat / salah ketik",
    "SUSUT_PERJALANAN": "Susut dalam perjalanan",
    "TARA_TIDAK_SESUAI": "Tara karung tidak sesuai",
    "DOKUMEN_TIDAK_SESUAI": "Dokumen tidak sesuai muatan",
    "PERLU_TINDAK_LANJUT": "Perlu tindak lanjut manajemen",
    "LAIN": "Lainnya",
}


async def _ambil(db: AsyncSession, transaksi_id: int):
    baris = await service.ambil_transaksi(db, transaksi_id)
    if baris is None:
        raise service.LayananError("Transaksi tidak ditemukan.")
    return baris


# ═══════════════════════════ Daftar & rincian ═══════════════════════════

@router.get("/transaksi")
async def daftar(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    q = request.query_params
    f = service.FilterTransaksi(
        arah=q.get("arah") or None,
        jenis_kode=q.get("jenis") or None,
        status_kontrol=q.get("status") or None,
        status_tiket=q.get("tiket") or None,
        cari=q.get("cari") or None,
    )
    # Bawaan 30 hari terakhir, supaya halaman tidak pernah kosong hanya karena
    # petugas lupa mengisi rentang tanggal.
    try:
        f.dari = date.fromisoformat(q["dari"]) if q.get("dari") else \
            hari_ini() - timedelta(days=30)
        f.sampai = date.fromisoformat(q["sampai"]) if q.get("sampai") else hari_ini()
    except ValueError:
        f.dari, f.sampai = hari_ini() - timedelta(days=30), hari_ini()

    halaman = max(1, int(q.get("hal", 1) or 1))
    per_halaman = 50
    return render(
        request, "daftar.html",
        f=f, halaman=halaman, per_halaman=per_halaman,
        total=await service.hitung_transaksi(db, f),
        baris=await service.daftar_transaksi(
            db, f, batas=per_halaman, offset=(halaman - 1) * per_halaman
        ),
        jenis=await service.daftar_jenis(db),
        kembali=f"{PREFIX}/",
    )


@router.get("/transaksi/{transaksi_id}")
async def rincian(
    transaksi_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    try:
        b = await _ambil(db, transaksi_id)
    except service.LayananError as e:
        return redirect("/transaksi", err=str(e))

    aturan = await service.aturan_untuk(db, b.trx.jenis_kode)
    boleh_ubah, sebab = service.boleh_mengubah(b.trx, akun)
    cetak = list((await db.execute(
        select(TimbanganCetak)
        .where(TimbanganCetak.transaksi_id == b.trx.id)
        .order_by(TimbanganCetak.urutan)
    )).scalars())

    return render(
        request, "rincian.html",
        b=b, aturan=aturan,
        pemeriksaan=await service.pemeriksaan_transaksi(db, b.trx.id),
        cetak=cetak,
        boleh_ubah=boleh_ubah, sebab_terkunci=sebab,
        boleh_batal=service.boleh_membatalkan(akun),
        mode_uji_coba=await setelan.sakelar(db, setelan.MODE_UJI_COBA),
        kategori_hasil=KATEGORI_HASIL,
        kembali=f"{PREFIX}/",
    )


# ═══════════════════════════ Koreksi & pembatalan ═══════════════════════

@router.get("/transaksi/{transaksi_id}/koreksi")
async def form_koreksi(
    transaksi_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    try:
        b = await _ambil(db, transaksi_id)
    except service.LayananError as e:
        return redirect("/transaksi", err=str(e))

    boleh, sebab = service.boleh_mengubah(b.trx, akun)
    if not boleh:
        return redirect(f"/transaksi/{transaksi_id}", err=sebab)

    return render(
        request, "koreksi.html",
        b=b, aturan=await service.aturan_untuk(db, b.trx.jenis_kode),
        supplier_pilihan=await service.supplier_pilihan(db),
        kembali=f"{PREFIX}/transaksi/{transaksi_id}",
    )


@router.post("/transaksi/{transaksi_id}/koreksi")
async def simpan_koreksi(
    transaksi_id: int,
    request: Request,
    alasan: str = Form(...),
    timbang1_kg: str = Form(""),
    timbang2_kg: str = Form(""),
    nomor_polisi: str = Form(""),
    nama_sopir: str = Form(""),
    supplier_id: str = Form(""),
    jumlah_karung: str = Form(""),
    tara_per_karung_kg: str = Form(""),
    berat_acuan_kg: str = Form(""),
    nomor_acuan: str = Form(""),
    catatan: str = Form(""),
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    try:
        b = await _ambil(db, transaksi_id)
    except service.LayananError as e:
        return redirect("/transaksi", err=str(e))

    if not (alasan or "").strip():
        return redirect(
            f"/transaksi/{transaksi_id}/koreksi",
            err="Koreksi harus disertai alasan.",
        )

    perubahan: dict = {}
    if timbang1_kg:
        perubahan["timbang1_kg"] = _angka(timbang1_kg)
    if timbang2_kg and b.trx.timbang2_kg is not None:
        perubahan["timbang2_kg"] = _angka(timbang2_kg)
    if nomor_polisi:
        perubahan["nomor_polisi"] = nomor_polisi
    if nama_sopir:
        perubahan["nama_sopir"] = nama_sopir
    if supplier_id.isdigit():
        perubahan["supplier_id"] = int(supplier_id)
    if catatan:
        perubahan["catatan"] = catatan.strip()

    muatan = None
    if jumlah_karung or berat_acuan_kg or tara_per_karung_kg or nomor_acuan:
        lama = b.trx.muatan[0] if b.trx.muatan else None
        muatan = [service.InputMuatan(
            jenis_kode=b.trx.jenis_kode,
            jumlah_karung=int(_angka(
                jumlah_karung, lama.jumlah_karung if lama else 0
            )),
            tara_per_karung_kg=_angka(
                tara_per_karung_kg, float(lama.tara_per_karung_kg) if lama else 0
            ),
            berat_acuan_kg=_angka(
                berat_acuan_kg, float(lama.berat_acuan_kg) if lama else 0
            ),
            nomor_acuan=(nomor_acuan.strip() or (lama.nomor_acuan if lama else None)),
        )]

    try:
        await service.koreksi_transaksi(
            db, akun=akun, trx=b.trx, perubahan=perubahan, muatan=muatan,
            alasan=alasan.strip(),
            ip=request.client.host if request.client else None,
        )
    except (service.LayananError, logic.ValidasiError) as e:
        return redirect(f"/transaksi/{transaksi_id}/koreksi", err=str(e))

    return redirect(
        f"/transaksi/{transaksi_id}",
        ok="Koreksi tersimpan. Angka sebelumnya tetap tercatat di jejak audit.",
    )


@router.post("/transaksi/{transaksi_id}/batal")
async def batalkan(
    transaksi_id: int,
    request: Request,
    alasan: str = Form(...),
    akun: TimbanganAkun = Depends(butuh_pengawas),
    db: AsyncSession = Depends(get_db),
):
    try:
        b = await _ambil(db, transaksi_id)
        await service.void_transaksi(
            db, akun=akun, trx=b.trx, alasan=alasan,
            ip=request.client.host if request.client else None,
        )
    except service.LayananError as e:
        return redirect(f"/transaksi/{transaksi_id}", err=str(e))
    return redirect(
        f"/transaksi/{transaksi_id}",
        ok="Transaksi dibatalkan. Datanya tetap tersimpan.",
    )


@router.post("/transaksi/{transaksi_id}/hapus")
async def hapus(
    transaksi_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_admin),
    db: AsyncSession = Depends(get_db),
):
    """Hapus permanen — hanya Admin, hanya selagi mode uji coba menyala."""
    try:
        b = await _ambil(db, transaksi_id)
        kode = await service.hapus_transaksi(
            db, akun=akun, trx=b.trx,
            ip=request.client.host if request.client else None,
        )
    except service.LayananError as e:
        return redirect(f"/transaksi/{transaksi_id}", err=str(e))
    return redirect("/transaksi", ok=f"{kode} dihapus permanen.")


# ═══════════════════════════ Pemeriksaan ═══════════════════════════

@router.post("/transaksi/{transaksi_id}/periksa")
async def selesaikan_pemeriksaan(
    transaksi_id: int,
    request: Request,
    kategori_hasil: str = Form(...),
    catatan_resolusi: str = Form(...),
    dilaporkan_ke: str = Form(""),
    langkah_ulang_timbang: str = Form(""),
    langkah_hitung_karung: str = Form(""),
    langkah_periksa_tara: str = Form(""),
    langkah_periksa_dokumen: str = Form(""),
    langkah_periksa_muatan: str = Form(""),
    langkah_lapor: str = Form(""),
    akun: TimbanganAkun = Depends(butuh_pengawas),
    db: AsyncSession = Depends(get_db),
):
    lembar = await service.pemeriksaan_transaksi(db, transaksi_id)
    if lembar is None:
        return redirect(
            f"/transaksi/{transaksi_id}",
            err="Transaksi ini tidak punya lembar pemeriksaan.",
        )
    try:
        await service.selesaikan_pemeriksaan(
            db, akun=akun, lembar=lembar,
            langkah={
                "langkah_ulang_timbang": langkah_ulang_timbang.strip() or None,
                "langkah_hitung_karung": langkah_hitung_karung.strip() or None,
                "langkah_periksa_tara": langkah_periksa_tara.strip() or None,
                "langkah_periksa_dokumen": langkah_periksa_dokumen.strip() or None,
                "langkah_periksa_muatan": langkah_periksa_muatan.strip() or None,
                "langkah_lapor": langkah_lapor.strip() or None,
            },
            kategori_hasil=kategori_hasil,
            catatan_resolusi=catatan_resolusi,
            dilaporkan_ke=dilaporkan_ke.strip() or None,
            ip=request.client.host if request.client else None,
        )
    except service.LayananError as e:
        return redirect(f"/transaksi/{transaksi_id}", err=str(e))
    return redirect(f"/transaksi/{transaksi_id}", ok="Pemeriksaan ditutup.")


# ═══════════════════════════ Cetak ═══════════════════════════

@router.get("/transaksi/{transaksi_id}/cetak")
async def pilih_cetak(
    transaksi_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Dua ukuran bukti: struk 80 mm dan lembar setengah NCR."""
    try:
        b = await _ambil(db, transaksi_id)
    except service.LayananError as e:
        return redirect("/transaksi", err=str(e))

    return render(
        request, "cetak_pilih.html",
        b=b, aturan=await service.aturan_untuk(db, b.trx.jenis_kode),
        cetak=await _riwayat_cetak(db, b.trx.id),
        kembali=f"{PREFIX}/transaksi/{transaksi_id}",
    )


async def _riwayat_cetak(db: AsyncSession, transaksi_id: int):
    return list((await db.execute(
        select(TimbanganCetak)
        .where(TimbanganCetak.transaksi_id == transaksi_id)
        .order_by(TimbanganCetak.urutan)
    )).scalars())


async def _bahan_cetak(db: AsyncSession, transaksi_id: int):
    """Data yang sama untuk kedua ukuran — hanya tata letaknya berbeda."""
    b = await _ambil(db, transaksi_id)
    aturan = await service.aturan_untuk(db, b.trx.jenis_kode)
    petugas = {}
    for pid in {b.trx.timbang1_petugas_id, b.trx.timbang2_petugas_id} - {None}:
        orang = await db.get(TimbanganAkun, pid)
        if orang:
            petugas[pid] = orang.nama
    return b, aturan, petugas


@router.get("/transaksi/{transaksi_id}/cetak/80mm")
async def cetak_80mm(
    transaksi_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Struk thermal 80 mm.

    Hasil kontrol gabah bersifat rahasia internal (SOP butir 8) — pada bukti
    yang diberikan ke pengirim, angka selisih TIDAK ikut tercetak. Untuk beras
    PK sebaliknya: Sistem Tara butir 9 mewajibkan notanya diberikan.
    """
    try:
        b, aturan, petugas = await _bahan_cetak(db, transaksi_id)
    except service.LayananError as e:
        return redirect("/transaksi", err=str(e))

    return render(
        request, "cetak.html",
        b=b, aturan=aturan, petugas=petugas,
        tampilkan_selisih=not aturan.rahasia,
    )


@router.get("/transaksi/{transaksi_id}/cetak/ncr")
async def cetak_ncr(
    transaksi_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Lembar setengah NCR, 215 × 165 mm.

    Angka selisih TIDAK PERNAH dicetak di sini, apa pun komoditasnya —
    keputusan Direksi 30 Agustus 2026. Lembar ini diperlakukan sebagai salinan
    untuk pihak luar, jadi hasil kontrol internal tidak ikut dibawa keluar.
    Karena itu templatnya memang tidak punya jalan untuk menampilkannya.
    """
    try:
        b, aturan, petugas = await _bahan_cetak(db, transaksi_id)
    except service.LayananError as e:
        return redirect("/transaksi", err=str(e))

    return render(
        request, "cetak_ncr.html",
        b=b, aturan=aturan, petugas=petugas, dicetak=sekarang(),
    )


@router.post("/transaksi/{transaksi_id}/cetak")
async def catat_cetak(
    transaksi_id: int,
    request: Request,
    alasan: str = Form(""),
    format: str = Form("80MM"),
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    try:
        b = await _ambil(db, transaksi_id)
        await service.catat_cetak(
            db, akun=akun, trx=b.trx, alasan=alasan or None,
            format=format.upper(),
            ip=request.client.host if request.client else None,
        )
    except service.LayananError as e:
        return redirect(f"/transaksi/{transaksi_id}/cetak", err=str(e))
    return redirect(f"/transaksi/{transaksi_id}/cetak", ok="Cetak tercatat.")
