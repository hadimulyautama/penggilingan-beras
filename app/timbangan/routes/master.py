"""Rute master: tara standar, aturan komoditas, dan akun.

Aturan komoditas hanya dapat dilihat di sini, tidak diubah lewat layar. Mengubah
ambang berarti mengubah cara perusahaan menilai kejujuran timbangan — itu
keputusan yang harus lewat revisi SOP, bukan lewat kotak isian di ponsel.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Supplier
from app.timbangan import format as fmt
from app.timbangan import service, setelan
from app.timbangan.config import tsettings
from app.timbangan.db import get_db
from app.timbangan.models import (
    TimbanganAkun,
    TimbanganJenis,
    TimbanganKendaraan,
    TimbanganTaraStandar,
)
from app.timbangan.routes.pos import _angka
from app.timbangan.security import butuh_admin, butuh_akun, butuh_pengawas
from app.timbangan.web import PREFIX, redirect, render

router = APIRouter(prefix=PREFIX)


# ═══════════════════════════ Pengaturan ═══════════════════════════
#
# Katalog seluruh hal yang bisa disetel di modul ini. Sengaja menyebutkan
# TEMPAT tiap parameter diubah, karena ketiganya berbeda sifat:
#
#   data        → baris di database; berubah seketika, tanpa deploy
#   environment → variabel Railway; berubah setelah service dinyalakan ulang
#   kode        → hanya lewat perubahan kode dan tinjauan
#
# Yang TIDAK ada di sini dan memang tidak akan pernah ada: harga, potongan,
# dan segala hal bernilai uang. Operator pos timbang tidak boleh mengetahuinya.

DATA, ENV, KODE = "data", "environment", "kode"

SUMBER_LABEL = {
    DATA: "Data — berubah seketika",
    ENV: "Environment — perlu nyalakan ulang service",
    KODE: "Kode — lewat tinjauan",
}


async def _parameter_alat(db: AsyncSession) -> list[dict]:
    """Nilai yang sedang berlaku, beserta asalnya — data atau environment."""
    nilai = await setelan.semua(db)
    asal = await setelan.asal(db)
    return [
        {"kunci": d.kunci, "nama": d.nama, "satuan": d.satuan, "arti": d.arti,
         "env": d.env, "asal": asal[d.kunci],
         # `angka` masuk ke kotak isian — mentah, supaya bisa langsung diketik
         # ulang. `nilai` untuk dibaca mata, dengan pemisah ribuan.
         "angka": d.format(nilai[d.kunci]),
         "nilai": f"{fmt.angka(nilai[d.kunci], d.desimal)} {d.satuan}",
         "bawaan": fmt.angka(d.bawaan(), d.desimal),
         "batas": f"{fmt.angka(d.minimum, d.desimal)}–"
                  f"{fmt.angka(d.maksimum, d.desimal)} {d.satuan}"}
        for d in setelan.DAFTAR
    ]


def _parameter_bukti() -> list[dict]:
    return [
        {"nama": "Nama perusahaan", "nilai": tsettings.perusahaan_nama,
         "env": "TIMBANGAN_PERUSAHAAN", "arti": "Kepala bukti timbang."},
        {"nama": "Alamat", "nilai": tsettings.perusahaan_alamat,
         "env": "TIMBANGAN_ALAMAT", "arti": "Baris kedua kepala bukti."},
        {"nama": "Nomor telepon", "nilai": tsettings.perusahaan_telepon,
         "env": "TIMBANGAN_TELEPON",
         "arti": "Baris ketiga. Alamat surel sengaja tidak dicetak."},
    ]


def _parameter_sesi() -> list[dict]:
    return [
        {"nama": "Kunci penanda sesi",
         "nilai": "sudah diset" if tsettings.secret_key else
                  "BELUM DISET — sesi hangus tiap kali service restart",
         "env": "TIMBANGAN_SECRET_KEY",
         "arti": "Nilainya tidak pernah ditampilkan di layar mana pun."},
        {"nama": "Batas atas umur sesi",
         "nilai": f"{tsettings.sesi_hari} hari",
         "env": "TIMBANGAN_SESI_HARI",
         "arti": "Jaring pengaman. Sesi normalnya berakhir saat menekan Keluar."},
    ]


@router.get("/pengaturan")
async def pengaturan(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Katalog seluruh data & parameter yang bisa disetel, beserta nilainya."""
    async def hitung(model, *syarat):
        q = select(func.count(model.id))
        for s in syarat:
            q = q.where(s)
        return (await db.execute(q)).scalar_one()

    jumlah = {
        "komoditas": await hitung(TimbanganJenis, TimbanganJenis.status == "aktif"),
        "tara": await hitung(
            TimbanganTaraStandar, TimbanganTaraStandar.status == "BERLAKU"
        ),
        "akun": await hitung(TimbanganAkun, TimbanganAkun.status == "aktif"),
        "kendaraan": await hitung(TimbanganKendaraan),
        "supplier": len(await service.daftar_supplier(db)),
    }

    return render(
        request, "pengaturan.html",
        jumlah=jumlah,
        sakelar=setelan.SAKELAR,
        sakelar_nyala=await setelan.semua_sakelar(db),
        alat=await _parameter_alat(db),
        bukti=_parameter_bukti(),
        sesi=_parameter_sesi(),
        sumber_label=SUMBER_LABEL,
        kembali=f"{PREFIX}/",
    )


@router.post("/pengaturan")
async def simpan_pengaturan(
    request: Request,
    kunci: str = Form(...),
    nilai: str = Form(""),
    aksi: str = Form("simpan"),
    akun: TimbanganAkun = Depends(butuh_admin),
    db: AsyncSession = Depends(get_db),
):
    """Setel satu parameter operasional, atau kembalikan ke bawaannya."""
    d = setelan.PETA.get(kunci)
    if d is None:
        return redirect("/pengaturan", err="Setelan tidak dikenal.")
    try:
        if aksi == "bawaan":
            hasil = await setelan.kembalikan_bawaan(db, akun=akun, kunci=kunci)
            pesan = (f"{d.nama} kembali ke bawaan "
                     f"{fmt.angka(hasil, d.desimal)} {d.satuan}.")
        else:
            hasil = await setelan.simpan(db, akun=akun, kunci=kunci, teks=nilai)
            pesan = f"{d.nama} kini {fmt.angka(hasil, d.desimal)} {d.satuan}."
        await db.commit()
    except setelan.SetelanError as e:
        return redirect("/pengaturan", err=str(e))
    return redirect("/pengaturan", ok=pesan)


@router.post("/pengaturan/sakelar")
async def setel_sakelar(
    request: Request,
    kunci: str = Form(...),
    nyala: str = Form("0"),
    akun: TimbanganAkun = Depends(butuh_admin),
    db: AsyncSession = Depends(get_db),
):
    """Nyalakan atau matikan satu sakelar. Admin saja."""
    try:
        hidup = await setelan.setel_sakelar(
            db, akun=akun, kunci=kunci, nyala=nyala in ("1", "ya", "on", "true")
        )
        await db.commit()
    except setelan.SetelanError as e:
        return redirect("/pengaturan", err=str(e))
    nama = setelan.PETA_SAKELAR[kunci].nama
    return redirect(
        "/pengaturan",
        ok=f"{nama} {'dinyalakan' if hidup else 'dimatikan'}.",
    )


@router.get("/aturan")
async def aturan(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_akun),
    db: AsyncSession = Depends(get_db),
):
    """Rujukan cepat: aturan yang sedang berlaku untuk tiap komoditas."""
    return render(
        request, "aturan.html",
        jenis=await service.daftar_jenis(db),
        peta=await service.peta_aturan(db),
        kembali=f"{PREFIX}/",
    )


@router.get("/tara")
async def daftar_tara(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_pengawas),
    db: AsyncSession = Depends(get_db),
):
    baris = list((await db.execute(
        select(TimbanganTaraStandar)
        .order_by(TimbanganTaraStandar.status, TimbanganTaraStandar.id.desc())
    )).scalars())
    return render(
        request, "tara.html",
        baris=baris,
        supplier=await service.daftar_supplier(db),
        jenis=await service.daftar_jenis(db),
        nama_pihak={s.id: s.nama_supplier
                    for s in await service.daftar_supplier(db)},
        kembali=f"{PREFIX}/laporan",
    )


@router.post("/tara")
async def simpan_tara(
    request: Request,
    jenis_kode: str = Form(...),
    jumlah_sampel: str = Form(...),
    total_berat_kg: str = Form(...),
    supplier_id: str = Form(""),
    jenis_karung: str = Form(""),
    alasan: str = Form(""),
    akun: TimbanganAkun = Depends(butuh_pengawas),
    db: AsyncSession = Depends(get_db),
):
    try:
        baris = await service.simpan_tara_standar(
            db, akun=akun,
            supplier_id=int(supplier_id) if supplier_id.isdigit() else None,
            jenis_kode=jenis_kode,
            jumlah_sampel=int(_angka(jumlah_sampel)),
            total_berat_kg=_angka(total_berat_kg),
            jenis_karung=jenis_karung.strip() or None,
            alasan=alasan.strip() or None,
        )
        await db.commit()
    except service.LayananError as e:
        return redirect("/tara", err=str(e))
    return redirect(
        "/tara",
        ok=f"Tara baru {baris.tara_per_karung_kg:.3f} kg/karung berlaku mulai hari ini.",
    )


@router.get("/pengguna")
async def daftar_pengguna(
    request: Request,
    akun: TimbanganAkun = Depends(butuh_admin),
    db: AsyncSession = Depends(get_db),
):
    return render(
        request, "pengguna.html",
        baris=list((await db.execute(
            select(TimbanganAkun).order_by(TimbanganAkun.nama)
        )).scalars()),
        kembali=f"{PREFIX}/laporan",
    )


@router.post("/pengguna")
async def simpan_pengguna(
    request: Request,
    username: str = Form(...),
    nama: str = Form(...),
    role: str = Form(...),
    sandi: str = Form(...),
    perangkat_kode: str = Form(""),
    akun: TimbanganAkun = Depends(butuh_admin),
    db: AsyncSession = Depends(get_db),
):
    from app.timbangan.security import hash_sandi

    bersih = username.strip().lower()
    ada = (await db.execute(
        select(TimbanganAkun).where(TimbanganAkun.username == bersih)
    )).scalars().first()
    if ada is not None:
        return redirect("/pengguna", err=f"Nama pengguna '{bersih}' sudah dipakai.")

    try:
        sandi_hash = hash_sandi(sandi)
    except ValueError as e:
        return redirect("/pengguna", err=str(e))

    baru = TimbanganAkun(
        username=bersih, nama=nama.strip(), role=role,
        password_hash=sandi_hash,
        perangkat_kode=(perangkat_kode.strip().upper() or None),
    )
    db.add(baru)
    await db.flush()
    await service.catat_audit(
        db, akun=akun, aksi="BUAT_AKUN", entitas="akun", entitas_id=baru.id,
        ringkasan=f"{baru.username} sebagai {baru.role}",
    )
    await db.commit()
    return redirect("/pengguna", ok=f"Akun {baru.nama} dibuat.")


@router.post("/pengguna/{akun_id}/status")
async def ubah_status_pengguna(
    akun_id: int,
    request: Request,
    akun: TimbanganAkun = Depends(butuh_admin),
    db: AsyncSession = Depends(get_db),
):
    orang = await db.get(TimbanganAkun, akun_id)
    if orang is None:
        return redirect("/pengguna", err="Akun tidak ditemukan.")
    if orang.id == akun.id:
        return redirect("/pengguna", err="Anda tidak bisa menonaktifkan akun sendiri.")

    orang.status = "nonaktif" if orang.status == "aktif" else "aktif"
    await service.catat_audit(
        db, akun=akun, aksi="UBAH_STATUS_AKUN", entitas="akun", entitas_id=orang.id,
        ringkasan=f"{orang.username} → {orang.status}",
    )
    await db.commit()
    return redirect("/pengguna", ok=f"{orang.nama} kini {orang.status}.")
