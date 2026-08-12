"""Fase 2b — ekstraksi TAGIHAN dari email (Haiku) → usul pengingat lewat gerbang.

Alur: pemindai menemukan email kandidat → `proses_email_tagihan` memakai Haiku
(murah) untuk menilai "ini tagihan berjatuh-tempo atau bukan" + ekstrak {vendor,
jatuh_tempo, jumlah}. Bila valid & yakin → ajukan aksi `kalender_buat` ke gerbang
tombol pemilik (persetujuan). Setelah pemilik ✅, acara 🔔 masuk kalender → otomatis
muncul di Radar Jatuh Tempo & Briefing.

Konservatif & anti-mengarang: notifikasi transaksi/promosi/OTP → BUKAN tagihan;
tanpa tanggal jelas → tak diusulkan.
"""
from __future__ import annotations

import logging
from datetime import date

from app.ai.claude_client import get_client
from app.config import settings
from app.kantor import persetujuan as pst

log = logging.getLogger("kantor.billing")

_TOOL = [{
    "name": "ekstrak_tagihan",
    "description": "Ekstrak info tagihan/jatuh tempo dari sebuah email.",
    "input_schema": {
        "type": "object",
        "properties": {
            "ada_tagihan": {
                "type": "boolean",
                "description": "true HANYA bila email ini benar-benar TAGIHAN/invoice/"
                               "pengingat pembayaran dengan TENGGAT. Notifikasi transaksi "
                               "bank, mutasi, struk, promosi, newsletter, OTP → false.",
            },
            "vendor": {"type": "string", "description": "Nama penagih/penyedia."},
            "jatuh_tempo": {
                "type": "string",
                "description": "Tanggal jatuh tempo, format YYYY-MM-DD. Kosongkan bila "
                               "tak ada tanggal pasti di email (JANGAN mengarang).",
            },
            "jumlah": {"type": "string", "description": "Nominal bila ada, mis. 'Rp1.250.000'."},
            "keyakinan": {"type": "string", "enum": ["tinggi", "sedang", "rendah"]},
        },
        "required": ["ada_tagihan", "keyakinan"],
    },
}]

_SYS = (
    "Kamu pengekstrak TAGIHAN dari email. Isi tool 'ekstrak_tagihan'. "
    "ada_tagihan=true HANYA untuk tagihan/invoice/pengingat pembayaran yang punya "
    "TENGGAT bayar. Notifikasi transaksi/mutasi bank, struk, promosi, newsletter, "
    "OTP/verifikasi → ada_tagihan=false. 'jatuh_tempo' WAJIB format YYYY-MM-DD dan "
    "HARUS berasal dari isi email; bila tak ada tanggal pasti, kosongkan & "
    "keyakinan=rendah. DILARANG mengarang tanggal/nominal."
)


async def _ekstrak(email: dict) -> dict:
    client = get_client()
    isi = (f"Dari: {email.get('from', '')}\nSubjek: {email.get('subject', '')}\n"
           f"Tanggal email: {email.get('date', '')}\n\n{email.get('body', '')}")
    resp = await client.messages.create(
        model=settings.miniapp_model,  # Haiku (murah)
        max_tokens=300,
        system=_SYS,
        tools=_TOOL,
        tool_choice={"type": "tool", "name": "ekstrak_tagihan"},
        messages=[{"role": "user", "content": isi}],
    )
    for b in resp.content:
        if getattr(b, "type", None) == "tool_use" and b.name == "ekstrak_tagihan":
            return b.input or {}
    return {}


def _tgl_valid(s: str) -> date | None:
    try:
        d = date.fromisoformat((s or "")[:10])
    except ValueError:
        return None
    return d if date(2020, 1, 1) <= d <= date(2100, 1, 1) else None


async def proses_email_tagihan(mailbox: str, email: dict) -> bool:
    """Nilai 1 email. True bila tagihan valid & diajukan ke gerbang pemilik."""
    try:
        data = await _ekstrak(email)
    except Exception:  # noqa: BLE001
        log.warning("ekstrak tagihan gagal", exc_info=True)
        return False
    if not data.get("ada_tagihan") or data.get("keyakinan") == "rendah":
        return False
    d = _tgl_valid(data.get("jatuh_tempo", ""))
    if not d:
        return False
    vendor = (data.get("vendor") or email.get("from", "")).strip()
    jumlah = (data.get("jumlah") or "").strip()
    judul = f"🔔 Tagihan {vendor}" + (f" — {jumlah}" if jumlah else "")
    ring = (f"Tambah pengingat tenggat: {judul} pada {d.isoformat()} "
            f"(terdeteksi dari email di {mailbox}). Muncul di Radar Jatuh Tempo.")
    payload = {
        "judul": judul,
        "mulai": f"{d.isoformat()}T09:00:00",
        "selesai": f"{d.isoformat()}T09:30:00",
        "deskripsi": (f"Auto dari email {email.get('from', '')} — subjek: "
                      f"{email.get('subject', '')}. Verifikasi nominal & tenggat."),
        "cal_id": "primary",
    }
    await pst.buat_pending(jenis="kalender_buat", ringkasan=ring,
                           payload=payload, diminta_oleh="bot-tagihan")
    log.info("tagihan diusulkan: %s (%s)", judul, d)
    return True
