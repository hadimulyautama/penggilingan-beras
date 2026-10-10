"""Layar Jasa — barang titipan pelanggan, dan apa yang masih ada di pabrik.

Tempat MENAMPILKAN, bukan tempat menerima. Pesanan jasa lahir di Pos Timbang
(pelanggan + pesanannya) lalu diterima operator lewat kartu Antrian tunggu;
halaman ini tak punya tombol "buat pesanan" sama sekali, dan itu disengaja —
pesanan yang bisa dibuat di dua tempat akan dibuat dua kali.

⚠ KENAPA HALAMAN INI HARUS ADA. Saringan `jasa_id IS NULL` membuang barang
pelanggan dari SETIAP layar stok — dan itu benar: ia bukan stok pabrik. Tetapi
akibatnya barang orang lain tak punya satu pun layar: ia ada di gudang,
memakan silo dan lantai, dan tak terbaca di mana pun. Halaman ini yang
menutup lubang yang dibuat saringan itu.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import SessionLocal
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter()


@router.get("/jasa")
async def halaman_jasa(request: Request, akun=Depends(butuh_akun)):
    """Pesanan jasa yang berjalan, sisanya per fase, dan umurnya."""
    from app.peran import can_see_financials
    from app.services.jasa import FASE_JASA, daftar_jasa
    from app.models.jasa import BERJALAN, DIBATALKAN, DIGABUNG, SELESAI

    # Kerja MEJA. Pintunya sudah tak ditawarkan ke operator, tetapi pintu yang
    # disembunyikan bukan penjagaan: alamatnya bisa diketik.
    if not can_see_financials(akun.user):
        raise HTTPException(403, "Layar Jasa milik Admin ke atas.")

    tapis = (request.query_params.get("status") or BERJALAN).strip()
    if tapis not in (BERJALAN, SELESAI, DIBATALKAN, DIGABUNG):
        tapis = BERJALAN
    async with SessionLocal() as db:
        kartu = await daftar_jasa(db, status=tapis)
    # Berapa ton barang orang lain di gudang hari ini — satu angka, dan ia
    # satu-satunya hitungan yang pemilik minta di layar ini (keputusan 10: tak
    # ada ambang, tak ada pagar; angka apa adanya saja).
    #
    # Dijumlah dari `total` tiap pesanan dan DISEBUT sebagai perkiraan: satu
    # muatan bisa terhitung dua kali bila ia sedang berpindah fase, dan angka
    # yang disebut pasti akan dibaca sebagai janji.
    ton = sum(k.sisa.total for k in kartu)
    return await render_laci(
        request, "jasa.html",
        kartu=kartu, FASE_JASA=FASE_JASA, tapis=tapis, ton=ton,
        # DIGABUNG ikut ditawarkan (10 Oktober 2026) — "cermin bertanda, bukan
        # dihapus" berlaku di sini juga: pesanan yang digabung tetap harus
        # bisa DILIHAT (nota-nya menunjuk ke survivor-nya), bukan menghilang
        # dari layar begitu statusnya berubah.
        STATUS_PILIHAN=((BERJALAN, "Berjalan"), (SELESAI, "Selesai"),
                        (DIBATALKAN, "Dibatalkan"), (DIGABUNG, "Digabung")),
    )


@router.get("/jasa/{jasa_id:int}/nota")
async def nota(jasa_id: int, request: Request, akun=Depends(butuh_akun)):
    """Nota satu pesanan — bobot & milik saja, tanpa satu pun angka uang."""
    from app.peran import can_see_financials
    from app.services.jasa import JasaError, nota_jasa

    if not can_see_financials(akun.user):
        raise HTTPException(403, "Layar Jasa milik Admin ke atas.")
    async with SessionLocal() as db:
        try:
            teks = await nota_jasa(db, jasa_id)
        except JasaError as e:
            raise HTTPException(404, e.args[0] if e.args else "Tidak ditemukan.")
    return await render_laci(request, "jasa_nota.html", teks=teks,
                             jasa_id=jasa_id)
