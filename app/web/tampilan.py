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
VERSI = "2"

templates.env.globals["VERSI"] = VERSI


def render(request: Request, nama: str, *, status_code: int = 200, **konteks):
    """Render template dengan konteks bawaan (akun yang sedang masuk)."""
    konteks.setdefault("akun", getattr(request.state, "akun", None))
    return templates.TemplateResponse(request, nama, konteks, status_code=status_code)


def redirect(tujuan: str) -> RedirectResponse:
    """Pengalihan setelah POST — 303 supaya peramban beralih ke GET."""
    return RedirectResponse(tujuan, status_code=303)
