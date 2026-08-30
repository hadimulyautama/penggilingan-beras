"""Rute pos timbang — layar yang dipakai petugas berdiri di dekat jembatan.

Urutannya sengaja pendek: beranda → pilih komoditas → timbang pertama →
(truk bongkar) → timbang kedua → hasil. Tidak ada layar yang bisa dilewati,
dan tidak ada layar tambahan yang tidak dipakai setiap hari.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.timbangan import logic, service
from app.timbangan.db import get_db, hari_ini, sekarang
from app.timbangan.models import CARA_DUA_KALI, CARA_SEKALI, TimbanganAkun
from app.timbangan.security import butuh_akun
from app.timbangan.web import PREFIX, redirect, render

router = APIRouter(prefix=PREFIX)


def _angka(teks: str | None, bawaan: float = 0.0) -> float:
    """Terima '13.600', '13,600', '13600', '0.250' — petugas mengetik apa adanya.

    Satu titik dengan tiga angka di belakangnya ambigu: '13.600' berarti tiga
    belas ribu enam ratus, tetapi '0.250' berarti seperempat kilogram. Yang
    membedakan adalah angka di depan titik — tidak ada orang yang menulis
    '0.250' untuk maksud dua ratus lima puluh.

    Salah menebak di sini berakibat fatal: tara 0,25 kg yang terbaca 250 kg
    membuat setiap transaksi gabah ditolak sebagai mustahil.
    """
    if teks is None:
        return bawaan
    bersih = str(teks).strip().replace(" ", "")
    if not bersih:
        return bawaan

    if "," in bersih:
        # Koma dipakai desimal → titik pasti pemisah ribuan.
        bersih = bersih.replace(".", "").replace(",", ".")
    elif bersih.count(".") > 1:
        # '1.234.567' — hanya mungkin pemisah ribuan.
        bersih = bersih.replace(".", "")
    elif bersih.count(".") == 1:
        depan, belakang = bersih.split(".")
        ribuan = len(belakang) == 3 and depan.lstrip("-+").lstrip("0") != ""
        if ribuan:
            bersih = bersih.replace(".", "")
    try:
        return float(bersih)
    except ValueError:
        return bawaan


def _waktu_operator(teks: str | None) -> datetime | None:
    """Jam yang boleh dikoreksi petugas bila ia mencatat terlambat."""
    if not teks:
        return None
    for pola in ("%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M"):
        try:
            return datetime.strptime(teks, pola)
        except ValueError:
            continue
    return None


# ═══════════════════════════ Beranda ═══════════════════════════

@router.get("/")
async def beranda(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Satu layar: apa yang sedang berjalan, dan apa yang bisa dimulai."""
    terbuka = await service.tiket_terbuka(db)
    # Selain Admin, daftar hari ini dipersempit ke timbangan orang ini
    # sendiri. Bukan sekadar kerapian: rinciannya memang tidak boleh dibuka
    # olehnya, jadi menampilkannya hanya menyodorkan tautan yang berujung
    # "akses ditolak".
    hari = await service.daftar_transaksi(
        db,
        service.FilterTransaksi(
            dari=hari_ini(), sampai=hari_ini(),
            petugas_id=None if akun.is_admin else akun.id,
        ),
        batas=8,
    )
    return render(
        request, "beranda.html",
        terbuka=terbuka,
        hari_ini_daftar=hari,
        menganggur={b.trx.id for b in await service.tiket_menganggur(db)},
    )


@router.get("/pilih/{arah}")
async def pilih_jenis(
    arah: str,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Komoditas yang ditawarkan mengikuti arah barang.

    Barang masuk dan barang keluar bukan daftar yang sama — menir, bekatul,
    dan reject tidak pernah dibeli, jadi tidak pernah muncul di sisi masuk.
    """
    arah = arah.upper()
    if arah not in (logic.MASUK, logic.KELUAR, logic.BEBAS):
        return redirect("/", err="Arah barang tidak dikenal.")

    jenis = await service.daftar_jenis(db, arah=arah)
    if arah != logic.BEBAS:
        jenis = [j for j in jenis if j.arah == arah]

    peta = await service.peta_aturan(db)
    return render(
        request, "pilih_jenis.html",
        arah=arah, jenis=jenis, peta=peta, kembali=f"{PREFIX}/",
    )


# ═══════════════════════════ Timbang pertama ═══════════════════════════

@router.get("/timbang/{jenis_kode}")
async def form_timbang_pertama(
    jenis_kode: str,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    try:
        aturan = await service.aturan_untuk(db, jenis_kode.upper())
    except service.LayananError as e:
        return redirect("/", err=str(e))

    tara, asal = await service.tara_disarankan(db, supplier_id=None, aturan=aturan)
    sering, lainnya = await service.supplier_pilihan(db)
    return render(
        request, "timbang1.html",
        aturan=aturan,
        kode=await service.kode_baru(db, akun),
        supplier_sering=sering,
        supplier_lainnya=lainnya,
        tara=tara,
        asal_tara=asal,
        sekarang=sekarang(),
        kembali=f"{PREFIX}/pilih/{aturan.arah}",
    )


@router.post("/timbang/{jenis_kode}")
async def simpan_timbang_pertama(
    jenis_kode: str,
    request: Request,
    kode: str = Form(...),
    berat_kg: str = Form(...),
    cara_timbang: str = Form(CARA_DUA_KALI),
    supplier_id: str = Form(""),
    pihak_nama: str = Form(""),
    nomor_polisi: str = Form(""),
    nama_sopir: str = Form(""),
    nomor_acuan: str = Form(""),
    jumlah_karung: str = Form("0"),
    tara_per_karung_kg: str = Form("0"),
    berat_acuan_kg: str = Form("0"),
    tara_lain_kg: str = Form("0"),
    waktu: str = Form(""),
    catatan: str = Form(""),
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    jenis_kode = jenis_kode.upper()
    muatan: list[service.InputMuatan] = []
    if cara_timbang != CARA_SEKALI or jenis_kode != "BEBAS":
        muatan = [service.InputMuatan(
            jenis_kode=jenis_kode,
            jumlah_karung=int(_angka(jumlah_karung)),
            tara_per_karung_kg=_angka(tara_per_karung_kg),
            berat_acuan_kg=_angka(berat_acuan_kg),
            nomor_acuan=nomor_acuan.strip() or None,
        )]

    data = service.InputTimbang(
        kode=kode.strip(),
        arah=(await service.aturan_untuk(db, jenis_kode)).arah,
        jenis_kode=jenis_kode,
        berat_kg=_angka(berat_kg),
        waktu_operator=_waktu_operator(waktu),
        cara_timbang=cara_timbang,
        supplier_id=int(supplier_id) if supplier_id.isdigit() else None,
        pihak_nama=pihak_nama.strip() or None,
        nomor_polisi=nomor_polisi.strip() or None,
        nama_sopir=nama_sopir.strip() or None,
        tara_lain_kg=_angka(tara_lain_kg),
        muatan=muatan,
        catatan=catatan.strip() or None,
        perangkat_kode=akun.perangkat_kode,
    )

    try:
        trx = await service.simpan_timbang_pertama(
            db, akun=akun, data=data,
            ip=request.client.host if request.client else None,
        )
    except (service.LayananError, logic.ValidasiError) as e:
        return redirect(f"/timbang/{jenis_kode}", err=str(e))

    if trx.selesai:
        return redirect(f"/transaksi/{trx.id}", ok="Timbangan tersimpan.")
    return redirect(f"/transaksi/{trx.id}", ok="Timbang pertama tersimpan.")


# ═══════════════════════════ Timbang kedua ═══════════════════════════

@router.get("/tiket")
async def daftar_tiket(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    return render(
        request, "tiket.html",
        terbuka=await service.tiket_terbuka(db),
        menganggur={b.trx.id for b in await service.tiket_menganggur(db)},
        kembali=f"{PREFIX}/",
    )


@router.get("/tiket/{transaksi_id}")
async def form_timbang_kedua(
    transaksi_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    baris = await service.ambil_transaksi(db, transaksi_id)
    if baris is None:
        return redirect("/tiket", err="Tiket tidak ditemukan.")
    if baris.trx.selesai:
        return redirect(f"/transaksi/{transaksi_id}")

    aturan = await service.aturan_untuk(db, baris.trx.jenis_kode)
    return render(
        request, "timbang2.html",
        b=baris, aturan=aturan, sekarang=sekarang(),
        kembali=f"{PREFIX}/tiket",
    )


@router.post("/tiket/{transaksi_id}")
async def simpan_timbang_kedua(
    transaksi_id: int,
    request: Request,
    berat_kg: str = Form(...),
    jumlah_karung: str = Form(""),
    tara_per_karung_kg: str = Form(""),
    berat_acuan_kg: str = Form(""),
    nomor_acuan: str = Form(""),
    waktu: str = Form(""),
    catatan: str = Form(""),
    aksi: str = Form("selesai"),
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    baris = await service.ambil_transaksi(db, transaksi_id)
    if baris is None:
        return redirect("/tiket", err="Tiket tidak ditemukan.")

    # Jumlah karung & berat nota sering baru diketahui setelah bongkar —
    # karena itu boleh diisi di tahap kedua, bukan hanya di tahap pertama.
    muatan = None
    if jumlah_karung or berat_acuan_kg:
        lama = baris.trx.muatan[0] if baris.trx.muatan else None
        muatan = [service.InputMuatan(
            jenis_kode=baris.trx.jenis_kode,
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
        trx = await service.simpan_timbang_kedua(
            db, akun=akun, kode=baris.trx.kode,
            berat_kg=_angka(berat_kg),
            waktu_operator=_waktu_operator(waktu),
            muatan=muatan,
            catatan=catatan.strip() or None,
            selesaikan=aksi != "sementara",
            ip=request.client.host if request.client else None,
        )
    except (service.LayananError, logic.ValidasiError) as e:
        return redirect(f"/tiket/{transaksi_id}", err=str(e))

    if aksi == "sementara":
        return redirect(
            f"/tiket/{transaksi_id}",
            ok="Tersimpan. Tiket masih terbuka — selesaikan setelah jumlah "
               "karung pasti.",
        )
    return redirect(f"/transaksi/{trx.id}", ok="Timbangan selesai dan tersimpan.")


@router.post("/tiket/{transaksi_id}/tutup")
async def tutup_paksa_tiket(
    transaksi_id: int,
    request: Request,
    alasan: str = Form(...),
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    baris = await service.ambil_transaksi(db, transaksi_id)
    if baris is None:
        return redirect("/tiket", err="Tiket tidak ditemukan.")
    try:
        await service.tutup_paksa(
            db, akun=akun, trx=baris.trx, alasan=alasan,
            ip=request.client.host if request.client else None,
        )
    except service.LayananError as e:
        return redirect(f"/tiket/{transaksi_id}", err=str(e))
    return redirect("/tiket", ok="Tiket ditutup beserta alasannya.")
