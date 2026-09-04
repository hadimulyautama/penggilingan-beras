"""Kerangka tampilan webapp: Jinja, render, dan pengalihan.

Dipisah dari rutenya supaya modul rute tidak saling mengimpor hanya untuk
memakai `render`.
"""
from __future__ import annotations

from pathlib import Path

from fastapi import Request
from fastapi.responses import RedirectResponse
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

#: Dinaikkan setiap kali CSS atau JS berubah.
#:
#: Tanpa ini, perangkat yang sudah pernah membuka aplikasi akan memakai berkas
#: lama tanpa ada yang menyadarinya — dan pada layar pencatatan, JavaScript
#: lama berarti formulir yang bentuknya sudah berubah di server tetap dirender
#: dengan aturan yang sudah dicabut.
VERSI = "25"

templates.env.globals["VERSI"] = VERSI

from app.web.nav import TAB          # noqa: E402  (butuh `templates` di atas)

templates.env.globals["TAB"] = TAB
templates.env.globals["TAB_KUNCI"] = {k for k, _, _ in TAB}


def render(request: Request, nama: str, *, status_code: int = 200, **konteks):
    """Render template dengan konteks bawaan (akun yang sedang masuk).

    `layar` diturunkan dari nama template, bukan dikirim tiap pemanggil: bilah
    navigasi harus menyala di tab yang benar, dan satu pemanggil yang lupa
    mengirimnya berarti satu layar yang tabnya mati tanpa ada yang menyadari.
    """
    konteks.setdefault("akun", getattr(request.state, "akun", None))
    konteks.setdefault("layar", nama.replace(".html", ""))
    konteks.setdefault("MENUNGGU", 0)
    return templates.TemplateResponse(request, nama, konteks, status_code=status_code)


def redirect(tujuan: str) -> RedirectResponse:
    """Pengalihan setelah POST — 303 supaya peramban beralih ke GET."""
    return RedirectResponse(tujuan, status_code=303)
