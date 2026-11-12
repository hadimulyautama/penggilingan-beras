"""Katalog laporan per periode untuk setiap tahap operasional Padiflow.

Katalog dan API memakai daftar tahap yang sama. Laporan lama yang sudah
keluar dari katalog tidak dapat dibuka lagi melalui kode API web-nya.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Request

from app.peran import can_see_financials
from app.database import SessionLocal, now_local
from app.models import User
from app.web.security import butuh_akun
from app.web.tampilan import render

router = APIRouter(tags=["laporan"])


@dataclass(frozen=True)
class Laporan:
    kode: str
    nama: str
    arti: str
    #: Perlu melihat angka uang. False = boleh dilihat operator juga.
    uang: bool
    buat: Callable[..., Awaitable[str]]
    #: Menerima rentang tanggal — layar menawarkan pilihan periode.
    berperiode: bool = False


def _daftar() -> tuple[Laporan, ...]:
    """Dibangun di dalam fungsi supaya impor layanan tidak terjadi saat modul
    dimuat — sebagiannya menarik model yang berat, dan halaman masuk tidak
    perlu membayarnya."""
    from app.services.laporan_periode import TAHAP

    # Katalog hanya berisi laporan per tahap yang disepakati. Layanan analisa
    # lama tetap milik konsumennya sendiri, tetapi tidak lagi menjadi pilihan
    # laporan web maupun kode API yang dapat diminta langsung.
    return tuple(Laporan("tahap_" + kode, nama, "Aktivitas tahap ini pada periode pilihan.",
                         False, None, berperiode=True)
                 for kode, (nama, *_) in TAHAP.items())


#: Pilihan periode untuk laporan berentang waktu.
PERIODE = (
    ("hari_ini", "Hari ini"),
    ("kemarin", "Kemarin"),
    ("minggu_ini", "Minggu ini"),
    ("bulan_ini", "Bulan ini"),
    ("30_hari", "30 hari terakhir"),
    ("3_bulan", "3 bulan terakhir"),
    ("tahun_ini", "Tahun ini"),
    ("tahun_lalu", "Tahun lalu"),
    ("semua", "Semua"),
    ("khusus", "Rentang tanggal"),
)


def _rentang(periode: str, dari: date | None = None, sampai: date | None = None) -> tuple[date, date]:
    """Rentang tanggal untuk laporan yang menuntut dua tanggal.

    Terpisah dari `report._range` dengan sengaja: yang di sana boleh menjawab
    (None, None) untuk "semua", dan laporan produksi tidak menerima None.
    """
    if periode == "khusus":
        if dari is None or sampai is None or dari > sampai or sampai == date.max:
            raise HTTPException(422, "Isi tanggal awal dan akhir dengan urutan yang benar.")
        return dari, sampai
    hari = now_local().date()
    if periode == "hari_ini":
        return hari, hari
    if periode == "kemarin":
        return hari - timedelta(days=1), hari - timedelta(days=1)
    if periode == "minggu_ini":
        return hari - timedelta(days=hari.weekday()), hari
    if periode == "bulan_ini":
        return hari.replace(day=1), hari
    if periode == "3_bulan":
        bulan = hari.year * 12 + hari.month - 3
        return date(bulan // 12, bulan % 12 + 1, 1), hari
    if periode == "tahun_ini":
        return date(hari.year, 1, 1), hari
    if periode == "tahun_lalu":
        return date(hari.year - 1, 1, 1), date(hari.year - 1, 12, 31)
    if periode == "30_hari":
        return hari - timedelta(days=29), hari
    return date(2020, 1, 1), hari      # "semua" — sebelum pabrik ini punya data


def boleh_lihat(user: User, lap: Laporan) -> bool:
    return (not lap.uang) or can_see_financials(user)


def daftar_untuk(user: User) -> list[Laporan]:
    return [l for l in _daftar() if boleh_lihat(user, l)]


# ─────────────────────────── Teks → layar ───────────────────────────

#: Laporan ditulis untuk chat, jadi memakai Markdown ringan Telegram.
#: Dibiarkan apa adanya, layar akan penuh bintang; dibuang begitu saja,
#: penekanan yang disengaja penulisnya ikut hilang. Jadi diterjemahkan.
_TEBAL = re.compile(r"\*([^*\n]+)\*")
_MIRING = re.compile(r"_([^_\n]+)_")
_KODE = re.compile(r"`([^`\n]+)`")


def ke_html(teks: str) -> str:
    """Ubah teks laporan jadi HTML yang aman.

    Perhatikan urutannya: escape DULU, baru penanda Markdown diterjemahkan.
    Kebalikannya akan membuat isi laporan — nama supplier, catatan — bisa
    menyelundupkan tag.
    """
    aman = html.escape(teks or "")
    aman = _KODE.sub(r"<code>\1</code>", aman)
    aman = _TEBAL.sub(r"<b>\1</b>", aman)
    aman = _MIRING.sub(r"<i>\1</i>", aman)
    return aman


# ─────────────────────────── Rute ───────────────────────────

@router.get("/laporan")
async def halaman_laporan(request: Request, akun=Depends(butuh_akun)):
    from app.web.nav import lencana
    from app.web.laporan_navigasi import siapkan
    konteks = {}
    await siapkan(request, konteks)
    return render(request, "laporan.html",
                  daftar=[dict(kode=l.kode, nama=l.nama, arti=l.arti, berperiode=l.berperiode,
                               boleh=boleh_lihat(akun.user, l)) for l in _daftar()], periode=PERIODE,
                  **await lencana(akun.user), **konteks)


@router.get("/laporan/{kode}")
async def detail_laporan(request: Request, kode: str, periode: str = "bulan_ini",
                         dari: date | None = None, sampai: date | None = None,
                         akun=Depends(butuh_akun)):
    from urllib.parse import urlencode
    from fastapi.encoders import jsonable_encoder
    from app.services.laporan_periode import ambil
    from app.web.nav import lencana

    lap = next((l for l in _daftar() if l.kode == "tahap_" + kode), None)
    if lap is None:
        raise HTTPException(404, "Laporan tidak dikenal.")
    if not boleh_lihat(akun.user, lap):
        raise HTTPException(403, "Laporan ini tidak tersedia untuk peran Anda.")
    if periode not in {k for k, _ in PERIODE}:
        raise HTTPException(422, "Periode tidak dikenal.")
    awal, akhir = _rentang(periode, dari, sampai)
    async with SessionLocal() as db:
        data = await ambil(db, kode, awal, akhir)
    parameter = dict(periode=periode)
    if periode == "khusus":
        parameter.update(dari=awal.isoformat(), sampai=akhir.isoformat())
    utama = ("penyosohan", "penggilingan", "pengeringan", "transfer_pk")
    katalog = [l for l in _daftar() if boleh_lihat(akun.user, l)]
    urut = sorted(katalog, key=lambda l: utama.index(l.kode.removeprefix("tahap_")) if l.kode.removeprefix("tahap_") in utama else len(utama))
    pilihan = [dict(kode=l.kode.removeprefix("tahap_"), nama=l.nama,
                    kelompok="Proses" if l.kode.removeprefix("tahap_") in utama else "Laporan lainnya") for l in urut]
    return render(request, "laporan_periode_detail.html", laporan=lap, tahap=kode, pilihan_laporan=pilihan,
                  periode=PERIODE, periode_aktif=periode, dari=awal, sampai=akhir,
                  data=jsonable_encoder(data), pdf_href="/laporan-periode/"+kode+".pdf?"+urlencode(parameter),
                  layar="laporan", MENU_AKTIF="laporan", kembali="/laporan",
                  breadcrumb_induk=dict(nama="Laporan periode", alamat="/laporan"),
                  breadcrumb_detail=lap.nama, **await lencana(akun.user))


@router.get("/api/laporan/{kode}")
async def isi_laporan(kode: str, periode: str = "bulan_ini",
                      dari: date | None = None, sampai: date | None = None,
                      akun=Depends(butuh_akun)) -> dict:
    user = akun.user
    lap = next((l for l in _daftar() if l.kode == kode), None)
    if lap is None:
        raise HTTPException(404, "Laporan tidak dikenal.")
    # Diperiksa di sini, bukan hanya disaring di daftar: alamatnya bisa
    # diketik langsung, dan laporan uang tidak boleh terbuka begitu saja.
    if not boleh_lihat(user, lap):
        raise HTTPException(403, "Laporan ini tidak tersedia untuk peran Anda.")

    from app.services.laporan_periode import ambil
    awal, akhir = _rentang(periode, dari, sampai)
    async with SessionLocal() as db:
        data = await ambil(db, lap.kode.removeprefix("tahap_"), awal, akhir)
    return {"nama": lap.nama, "data": data}


@router.get("/laporan-periode/{kode}.pdf")
async def pdf_laporan_periode(kode: str, periode: str = "bulan_ini",
                              dari: date | None = None, sampai: date | None = None,
                              unduh: bool = False, akun=Depends(butuh_akun)):
    from fastapi.responses import Response
    from app.services.laporan_periode import ambil
    from app.web.pdf_periode import buat_pdf

    lap = next((l for l in _daftar() if l.kode == "tahap_" + kode), None)
    if lap is None:
        raise HTTPException(404, "Laporan tidak dikenal.")
    if not boleh_lihat(akun.user, lap):
        raise HTTPException(403, "Laporan ini tidak tersedia untuk peran Anda.")
    awal, akhir = _rentang(periode, dari, sampai)
    async with SessionLocal() as db:
        data = await ambil(db, kode, awal, akhir)
    return Response(buat_pdf(data), media_type="application/pdf", headers={
        "Content-Disposition": f'{"attachment" if unduh else "inline"}; filename="laporan-{kode}-{awal}-{akhir}.pdf"',
        "Cache-Control": "private, no-store",
    })
