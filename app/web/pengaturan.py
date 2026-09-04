"""Halaman Pengaturan — satu tempat untuk hal yang jarang diubah.

Dipisahkan dari beranda dengan sengaja. Beranda dipakai puluhan kali sehari
dan isinya keadaan pabrik; pengaturan dibuka beberapa kali setahun. Menaruh
keduanya berdampingan membuat yang sering dipakai harus melewati yang jarang.

Tiga bagian, dan urutannya mengikuti seberapa sering dipakai:
  · **Akun saya** — nama & kata sandi, milik siapa pun yang sedang masuk;
  · **Pengguna** — Super Admin saja;
  · **Alat** — dryer & silo, Super Admin saja.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request

from app.database import SessionLocal
from app.models import ProduksiAkun
from app.web.security import butuh_admin, butuh_akun
from app.web.tampilan import redirect, render
from hmu_core import User

router = APIRouter(tags=["webapp"])


@router.get("/pengaturan")
async def halaman_pengaturan(request: Request, akun: ProduksiAkun = Depends(butuh_akun)):
    from app.web.nav import jumlah_menunggu

    return render(
        request, "pengaturan.html", kembali="/",
        MENUNGGU=await jumlah_menunggu(akun.user),
        pesan_ok=_PESAN.get(request.query_params.get("pesan", "")),
    )


#: Hanya kunci yang dikenal yang jadi pesan — teks bebas dari URL tak pernah
#: ditampilkan, supaya halaman ini tak bisa dipakai menitipkan kalimat palsu
#: lewat tautan.
_PESAN = {
    "nama-diganti": "Nama Anda sudah diperbarui.",
    "sandi-diganti": "Kata sandi berhasil diganti.",
    "alat-ditambah": "Alat baru ditambahkan.",
    "alat-diubah": "Alat diperbarui.",
}


@router.post("/pengaturan/nama")
async def ganti_nama(
    request: Request,
    nama: str = Form(...),
    akun: ProduksiAkun = Depends(butuh_akun),
):
    """Ganti nama sendiri — yang tampil di seluruh catatan.

    Namanya BUKAN sekadar label layar: ia menempel pada ribuan catatan lama
    lewat `created_by`, dan yang berubah di sini ikut berubah di semua catatan
    itu. Itu memang yang diinginkan — orangnya sama, ejaannya yang salah — dan
    justru karena itu tak boleh sembarang dikosongkan atau disingkat jadi satu
    huruf, sebab daftar akun lalu mustahil dibaca.
    """
    nama = " ".join(nama.split())
    if len(nama) < 3:
        return redirect("/pengaturan?err=nama-pendek")
    async with SessionLocal() as db:
        orang = await db.get(User, akun.user_id)
        if orang is None:
            return redirect("/pengaturan")
        orang.nama = nama
        await db.commit()
    return redirect("/pengaturan?pesan=nama-diganti")


# ─────────────────────────── Alat: dryer & silo ───────────────────────────

#: Batas yang bukan hiasan. Nol alat membuat seluruh alur berhenti; jumlah
#: yang keterlaluan hampir pasti salah ketik, dan daftar sepanjang itu tak
#: bisa dipakai memilih sambil berdiri.
MAKS_ALAT = 12


@router.get("/pengaturan/alat")
async def halaman_alat(request: Request, akun: ProduksiAkun = Depends(butuh_admin)):
    from app.penggilingan.gudang1.services.drying import dryers_g1
    from app.penggilingan.gudang1.services.silo import _silo_content_kg, silos_g1
    from app.web.nav import jumlah_menunggu

    async with SessionLocal() as db:
        mesin = await dryers_g1(db)
        silo = [(s, await _silo_content_kg(db, s.id)) for s in await silos_g1(db)]
    return render(
        request, "alat.html", kembali="/pengaturan", layar="pengaturan",
        MENUNGGU=await jumlah_menunggu(akun.user),
        mesin=mesin, silo=silo, maks=MAKS_ALAT,
        pesan_ok=_PESAN.get(request.query_params.get("pesan", "")),
        pesan_err=_ERR.get(request.query_params.get("err", "")),
    )


_ERR = {
    "nama-pendek": "Nama alat minimal 3 huruf.",
    "kapasitas": "Kapasitas harus lebih dari 0 kg.",
    "penuh": f"Sudah ada {MAKS_ALAT} alat — hapus atau nonaktifkan dulu.",
    "kembar": "Sudah ada alat dengan nama itu.",
    "terisi": "Alat itu masih ada isinya — kosongkan dulu.",
}


@router.post("/pengaturan/alat/dryer")
async def tambah_dryer(
    request: Request, nama: str = Form(...), kapasitas_kg: int = Form(...),
    akun: ProduksiAkun = Depends(butuh_admin),
):
    """Tambah mesin pengering.

    Kapasitas diminta di sini, bukan diberi bawaan: dua mesin di pabrik yang
    sama belum tentu sama besarnya, dan angka bawaan yang salah akan menolak
    truk atau menerima muatan yang tak kering merata — keduanya diam-diam.
    """
    from app.models import Dryer
    from app.penggilingan.gudang1.services.drying import dryers_g1
    from app.penggilingan.gudang1.services.silo import _g1_warehouse_id

    nama = " ".join(nama.split())
    if len(nama) < 3:
        return redirect("/pengaturan/alat?err=nama-pendek")
    if kapasitas_kg <= 0:
        return redirect("/pengaturan/alat?err=kapasitas")
    async with SessionLocal() as db:
        ada = await dryers_g1(db)
        if len(ada) >= MAKS_ALAT:
            return redirect("/pengaturan/alat?err=penuh")
        if any(d.nama.lower() == nama.lower() for d in ada):
            return redirect("/pengaturan/alat?err=kembar")
        db.add(Dryer(warehouse_id=await _g1_warehouse_id(db), nama=nama,
                     kapasitas_kg=kapasitas_kg, status="aktif"))
        await db.commit()
    return redirect("/pengaturan/alat?pesan=alat-ditambah")


@router.post("/pengaturan/alat/silo")
async def tambah_silo(
    request: Request, nama: str = Form(...),
    akun: ProduksiAkun = Depends(butuh_admin),
):
    """Tambah silo gabah kering.

    Tanpa kapasitas: silo memang tak berbatas (keputusan Direksi 2 September
    2026), dan meminta angka yang tidak dipakai hanya mengundang orang
    mengarangnya.
    """
    from app.models import Silo
    from app.penggilingan.gudang1.services.silo import _g1_warehouse_id, silos_g1

    nama = " ".join(nama.split())
    if nama.lower().startswith("silo "):
        nama = nama[5:].strip()
    if len(nama) < 1:
        return redirect("/pengaturan/alat?err=nama-pendek")
    penuh = f"Silo {nama}"
    async with SessionLocal() as db:
        ada = await silos_g1(db)
        if len(ada) >= MAKS_ALAT:
            return redirect("/pengaturan/alat?err=penuh")
        if any(s.nama_silo.lower() == penuh.lower() for s in ada):
            return redirect("/pengaturan/alat?err=kembar")
        db.add(Silo(warehouse_id=await _g1_warehouse_id(db), nama_silo=penuh,
                    kapasitas_ton=0))
        await db.commit()
    return redirect("/pengaturan/alat?pesan=alat-ditambah")


@router.post("/pengaturan/alat/dryer/status")
async def ubah_status_dryer(
    request: Request, dryer_id: int = Form(...),
    akun: ProduksiAkun = Depends(butuh_admin),
):
    """Nonaktifkan atau aktifkan mesin — TIDAK menghapusnya.

    Mesin tidak pernah dihapus: lot pengeringan lama menunjuk ke sana, dan
    riwayatnya harus tetap bisa dibaca bertahun-tahun setelah mesinnya
    dijual. Yang dimatikan hanya kemampuannya menerima gabah baru.
    """
    from app.models import Dryer
    from app.penggilingan.gudang1.services.drying import active_drying_lot

    async with SessionLocal() as db:
        d = await db.get(Dryer, dryer_id)
        if d is None:
            return redirect("/pengaturan/alat")
        if d.status == "aktif":
            if await active_drying_lot(db, d.id) is not None:
                return redirect("/pengaturan/alat?err=terisi")
            d.status = "nonaktif"
        else:
            d.status = "aktif"
        await db.commit()
    return redirect("/pengaturan/alat?pesan=alat-diubah")
