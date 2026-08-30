"""Perakitan webapp Timbangan: template, filter, penanganan error, router.

Dipasang lewat `pasang(app)` — modul tetap mandiri, satu baris untuk
menyematkan atau melepas. Itu yang memungkinkan modul ini nanti dijalankan
sebagai service Railway tersendiri tanpa mengubah kode sedikit pun.
"""
from __future__ import annotations

import logging
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.timbangan import format as fmt
from app.timbangan import logic
from app.timbangan.config import tsettings
from app.timbangan.models import (
    JENIS_FOTO,
    ROLE_LABEL,
    ROLES,
    STATUS_SUPPLIER,
    TIKET_DITUTUP_PAKSA,
    TIKET_SELESAI,
    TIKET_TERBUKA,
)

log = logging.getLogger("timbangan.web")

BASE_DIR = Path(__file__).parent
PREFIX = "/timbangan"

# Dinaikkan bila CSS/JS berubah, supaya perangkat tidak memakai berkas lama.
VERSI = "10"

#: Warna tiap status. Dipisahkan dari `logic` karena ini urusan tampilan.
NADA_STATUS = {
    logic.NORMAL: "aman",
    logic.PERLU_PEMERIKSAAN: "hati",
    logic.INVESTIGASI: "bahaya",
    logic.KURANG: "bahaya",
    logic.KELEBIHAN: "hati",
    logic.TANPA_KONTROL: "netral",
}

NAMA_JENIS = {a.kode: a.nama for a in logic.JENIS_AWAL}


def ringkas_aturan(aturan: logic.AturanJenis) -> str:
    """Satu kalimat aturan komoditas untuk ditempel di atas layar isian.

    Petugas perlu tahu angka apa yang sedang dipakai menilai timbangannya,
    tanpa harus membuka dokumen.
    """
    bagian = []
    tara = aturan.tara_default()
    if aturan.sumber_tara == logic.TARA_MANUAL:
        bagian.append("tara diisi manual")
    elif tara:
        bagian.append(f"tara {fmt.angka(tara, 3)} kg/karung")

    if aturan.ambang_jenis == logic.AMBANG_PER_TON:
        bagian.append(f"batas {fmt.angka(aturan.ambang_nilai, 2)} kg per ton")
    elif aturan.ambang_jenis == logic.AMBANG_PER_KARUNG:
        bagian.append(f"batas {fmt.angka(aturan.ambang_nilai, 3)} kg per karung")
    elif aturan.ambang_jenis == logic.AMBANG_TETAP:
        bagian.append(f"batas {fmt.angka(aturan.ambang_nilai, 0)} kg")

    if aturan.ambang_arah == logic.ARAH_KURANG_SAJA:
        bagian.append("lebih diperbolehkan")
    elif aturan.ambang_arah == logic.ARAH_TIDAK_BOLEH_KURANG:
        bagian.append("tidak boleh kurang")

    return " · ".join(bagian) if bagian else "tanpa kontrol"


templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters.update({
    "angka": fmt.angka, "kg": fmt.kg, "kg_tanda": fmt.kg_tanda,
    "persen": fmt.persen, "ton": fmt.ton, "tgl": fmt.tgl,
    "tgl_jam": fmt.tgl_jam, "iso": fmt.iso, "jam": fmt.jam,
})
templates.env.globals.update({
    "PREFIX": PREFIX,
    "VERSI": VERSI,
    "PERUSAHAAN": tsettings.perusahaan_nama,
    "ALAMAT": tsettings.perusahaan_alamat,
    "TELEPON": tsettings.perusahaan_telepon,
    "STATUS_LABEL": logic.STATUS_LABEL,
    "NADA_STATUS": NADA_STATUS,
    "NAMA_JENIS": NAMA_JENIS,
    "ringkas_aturan": ringkas_aturan,
    "MASUK": logic.MASUK,
    "KELUAR": logic.KELUAR,
    "BEBAS": logic.BEBAS,
    "TRANSFER": logic.TRANSFER,
    "TIKET_TERBUKA": TIKET_TERBUKA,
    "TIKET_SELESAI": TIKET_SELESAI,
    "TIKET_DITUTUP_PAKSA": TIKET_DITUTUP_PAKSA,
    "STATUS_SUPPLIER": STATUS_SUPPLIER,
    "JENIS_FOTO": JENIS_FOTO,
    "ROLES": ROLES,
    "ROLE_LABEL": ROLE_LABEL,
})


def render(request: Request, nama: str, **konteks) -> HTMLResponse:
    """Render template dengan konteks standar (akun, pesan kilat, setelan).

    Setelan diambil dari permintaan ini — bukan dari nilai saat proses
    dinyalakan — supaya angka di layar selalu sama dengan angka yang dipakai
    server menolak input.
    """
    aktif = getattr(request.state, "setelan", None) or {}
    dasar = {
        "akun": getattr(request.state, "akun", None),
        "pesan_ok": request.query_params.get("ok"),
        "pesan_err": request.query_params.get("err"),
        "halaman": nama.replace(".html", ""),
        "kembali": None,
        "KAPASITAS_KG": aktif.get(
            "kapasitas_jembatan_kg", tsettings.kapasitas_jembatan_kg
        ),
        "KELIPATAN_TERA": aktif.get(
            "kelipatan_tera_kg", tsettings.kelipatan_tera_kg
        ),
        "JUMLAH_TIKET": getattr(request.state, "jumlah_tiket", 0),
    }
    dasar.update(konteks)
    return templates.TemplateResponse(request, nama, dasar)


def redirect(path: str, *, ok: str | None = None, err: str | None = None):
    """Redirect POST-ke-GET (pola PRG) sambil membawa pesan kilat.

    Tanpa ini, menyegarkan halaman setelah menyimpan akan mengirim ulang
    formulir — di pos timbang itu berarti transaksi ganda.
    """
    url = f"{PREFIX}{path}"
    if ok:
        url += ("&" if "?" in url else "?") + "ok=" + quote(ok)
    if err:
        url += ("&" if "?" in url else "?") + "err=" + quote(err)
    return RedirectResponse(url, status_code=303)


def pasang(app: FastAPI) -> None:
    """Sematkan modul Timbangan ke aplikasi FastAPI."""
    from app.timbangan.routes import router
    from app.timbangan.security import AksesDitolak, ButuhLogin

    app.include_router(router)
    app.mount(
        f"{PREFIX}/static",
        StaticFiles(directory=str(BASE_DIR / "static")),
        name="timbangan_static",
    )

    @app.exception_handler(ButuhLogin)
    async def _butuh_login(request: Request, exc: ButuhLogin):
        tujuan = request.url.path
        if request.url.query:
            tujuan += "?" + request.url.query
        return RedirectResponse(f"{PREFIX}/masuk?next={quote(tujuan)}", status_code=303)

    @app.exception_handler(AksesDitolak)
    async def _akses_ditolak(request: Request, exc: AksesDitolak):
        return templates.TemplateResponse(
            request, "error.html",
            {"akun": getattr(request.state, "akun", None),
             "kembali": PREFIX + "/", "kode": 403, "judul": "Akses ditolak",
             "pesan": str(exc)},
            status_code=403,
        )

    log.info("Modul Timbangan terpasang di %s", PREFIX)
