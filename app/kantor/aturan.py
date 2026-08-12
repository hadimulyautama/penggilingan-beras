"""Aturan pemilahan email yang DIAJARKAN pemilik — deterministik, dicek sebelum
model. Membuat agen 'belajar dari koreksi': sekali diajari, konsisten selamanya.

Dipakai oleh rapi.proses (pemilahan email) & tool agen (atur_email/lihat_aturan_email).
"""
from __future__ import annotations

import logging

from sqlalchemy import select

from app.database import SessionLocal
from app.kantor.models import AturanEmail

log = logging.getLogger("kantor.aturan")

NAMA_TOOL = ("atur_email", "lihat_aturan_email")


def _normal_verdikt(v: str) -> str:
    v = (v or "").strip().lower()
    if v.startswith("rutin") or "tidak penting" in v or "arsip" in v:
        return "rutin"
    return "penting"


async def tambah(cocok: str, verdikt: str, jenis: str = "from", catatan: str = "") -> str:
    cocok = (cocok or "").strip().lower()
    jenis = jenis if jenis in ("from", "domain", "subjek") else "from"
    verdikt = _normal_verdikt(verdikt)
    if not cocok:
        return "Nilai yang dicocokkan kosong — sebutkan pengirim/domain/kata subjek."
    async with SessionLocal() as db:
        db.add(AturanEmail(jenis=jenis, cocok=cocok, verdikt=verdikt,
                           catatan=(catatan or "")[:255] or None))
        await db.commit()
    ket = "diarsip otomatis (rutin)" if verdikt == "rutin" else "selalu dilaporkan (penting)"
    return f"📌 Dicatat: email dengan {jenis} '{cocok}' → {ket}. Kupakai otomatis mulai sekarang."


async def daftar() -> list[AturanEmail]:
    async with SessionLocal() as db:
        rows = (await db.execute(
            select(AturanEmail).where(AturanEmail.status == "aktif")
            .order_by(AturanEmail.id))).scalars().all()
    return list(rows)


def cocok_dari_list(email: dict, rules: list) -> str | None:
    """Verdikt ('rutin'/'penting') bila ada aturan cocok; None bila tak ada."""
    frm = (email.get("from") or "").lower()
    subj = (email.get("subject") or "").lower()
    dom = frm.split("@")[-1] if "@" in frm else frm
    for a in rules or []:
        c = a.cocok
        if (a.jenis == "domain" and c in dom) or \
           (a.jenis == "subjek" and c in subj) or \
           (a.jenis == "from" and c in frm):
            return a.verdikt
    return None


async def jalankan(nama_tool: str, args: dict, role: str = "staff") -> str:
    if (role or "").strip().lower() != "admin":
        return "Aturan email hanya bisa diatur admin."
    a = args or {}
    if nama_tool == "atur_email":
        return await tambah(a.get("cocok", ""), a.get("verdikt", ""),
                            jenis=a.get("jenis", "from"), catatan=a.get("catatan", ""))
    if nama_tool == "lihat_aturan_email":
        rows = await daftar()
        if not rows:
            return "Belum ada aturan email yang diajarkan."
        baris = [f"• [{r.id}] {r.jenis} '{r.cocok}' → {r.verdikt}" for r in rows]
        return "📋 Aturan pemilahan email:\n" + "\n".join(baris)
    return f"(tool '{nama_tool}' tak dikenal)"
