"""Layar laporan: satu daftar, satu isi, dipilih server.

Laporan di aplikasi ini sudah lama menghasilkan **teks siap baca** — ditulis
untuk chat, tetapi isinya bukan milik chat. Yang belum ada hanya layarnya.
Karena itu tidak ada laporan yang ditulis ulang di sini; berkas ini hanya
mendaftar mana yang ada, siapa yang boleh melihatnya, dan bagaimana teksnya
sampai ke layar tanpa membawa bintang-bintang Markdown.

**Siapa melihat apa ditentukan di sini, bukan di layar.** Laporan yang memuat
harga, HPP, dan nilai persediaan hanya untuk staff/admin. Operator melihat
laporan kerja: status gudang, apa yang sedang berjalan, stok fisik. Bukan
karena angkanya rahasia dari orangnya, melainkan karena perangkat gudang
dipakai bergantian dan berdiri di tempat terbuka.
"""
from __future__ import annotations

import html
import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Awaitable, Callable

from fastapi import APIRouter, Depends, HTTPException, Request

from app.bots.common import can_see_financials
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
    from app.penggilingan.inventory import finished_goods as bj
    from app.penggilingan.inventory import outgoing as keluar
    from app.penggilingan.inventory import packaging as kms
    from app.services import analytics, report

    return (
        # ── Laporan kerja: boleh dilihat siapa pun yang bekerja ──
        Laporan("status_gudang", "Status Gudang 1", "Apa yang sedang berjalan sekarang.",
                False, report.status_gudang1),
        Laporan("pending_verifikasi", "Menunggu verifikasi",
                "Yang tertahan menunggu tindakan orang lain.",
                False, report.pending_verifikasi),
        Laporan("produksi", "Riwayat produksi", "Giling & pengeringan pada rentang waktu.",
                False, None, berperiode=True),
        Laporan("stok_kemasan", "Stok karung", "Sisa karung per jenis, ukuran, dan merk.",
                False, kms.laporan_stok_kemasan),
        Laporan("stok_barang_jadi", "Stok barang jadi", "Beras yang sudah dikemas dan hasil samping.",
                False, bj.laporan_stok_barang_jadi),
        Laporan("barang_keluar", "Barang keluar", "Pengiriman terakhir beserta pembelinya.",
                False, keluar.laporan_barang_keluar),
        Laporan("jam_kedatangan", "Jam kedatangan gabah",
                "Kapan truk datang — dasar mengatur giliran jaga.",
                False, report.insight_jam_kedatangan),

        # ── Laporan uang: staff & admin ──
        Laporan("pembelian_gabah", "Pembelian gabah", "Gabah masuk beserta harganya.",
                True, None, berperiode=True),
        Laporan("hpp_beras", "HPP beras", "Harga pokok beras dari penyosohan terakhir.",
                True, lambda db: bj.laporan_hpp_beras(db, None)),
        Laporan("hpp_trend", "Tren HPP", "Arah harga pokok dari waktu ke waktu.",
                True, analytics.hpp_trend),
        Laporan("biaya_proses", "Biaya proses", "Biaya per proses giling & penyosohan.",
                True, analytics.biaya_proses_ringkas),
        Laporan("supplier", "Rapor supplier", "Siapa yang timbangannya paling jujur.",
                True, analytics.supplier_scorecard),
        Laporan("rekap_bulanan", "Rekap bulanan", "Ringkasan produksi sebulan.",
                True, analytics.rekap_produksi_bulanan),
        Laporan("musiman", "Analisa musiman", "Pola panen sepanjang tahun.",
                True, analytics.analisa_musiman),
    )


#: Pilihan periode untuk laporan berentang waktu.
PERIODE = (
    ("hari_ini", "Hari ini"),
    ("kemarin", "Kemarin"),
    ("minggu_ini", "Minggu ini"),
    ("bulan_ini", "Bulan ini"),
    ("30_hari", "30 hari terakhir"),
    ("semua", "Semua"),
)


def _rentang(periode: str) -> tuple[date, date]:
    """Rentang tanggal untuk laporan yang menuntut dua tanggal.

    Terpisah dari `report._range` dengan sengaja: yang di sana boleh menjawab
    (None, None) untuk "semua", dan laporan produksi tidak menerima None.
    """
    hari = now_local().date()
    if periode == "hari_ini":
        return hari, hari
    if periode == "kemarin":
        return hari - timedelta(days=1), hari - timedelta(days=1)
    if periode == "minggu_ini":
        return hari - timedelta(days=hari.weekday()), hari
    if periode == "bulan_ini":
        return hari.replace(day=1), hari
    if periode == "30_hari":
        return hari - timedelta(days=30), hari
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
    from app.web.nav import jumlah_menunggu
    return render(request, "laporan.html",
                  daftar=daftar_untuk(akun.user), periode=PERIODE,
                  MENUNGGU=await jumlah_menunggu(akun.user))


@router.get("/api/laporan/{kode}")
async def isi_laporan(kode: str, periode: str = "bulan_ini",
                      akun=Depends(butuh_akun)) -> dict:
    user = akun.user
    lap = next((l for l in _daftar() if l.kode == kode), None)
    if lap is None:
        raise HTTPException(404, "Laporan tidak dikenal.")
    # Diperiksa di sini, bukan hanya disaring di daftar: alamatnya bisa
    # diketik langsung, dan laporan uang tidak boleh terbuka begitu saja.
    if not boleh_lihat(user, lap):
        raise HTTPException(403, "Laporan ini tidak tersedia untuk peran Anda.")

    from app.services import report
    async with SessionLocal() as db:
        if lap.kode == "produksi":
            dari, sampai = _rentang(periode)
            teks = await report.laporan_produksi_histori(db, dari, sampai)
        elif lap.kode == "pembelian_gabah":
            teks = await report.laporan_pembelian_gabah(db, periode)
        else:
            teks = await lap.buat(db)
    return {"nama": lap.nama, "isi": ke_html(teks)}
