"""Auto-RAPI email (Fase pelengkap): pilah email inbox dengan Haiku.

- rutin_tak_penting → ARSIP OTOMATIS (reversibel; keluar inbox, tetap ada) + label Auto-Rapi.
- penting          → biarkan di inbox.
- ragu             → TANYA pemilik dulu (usul arsip lewat gerbang tombol).

Konservatif: ragu sedikit pun → 'ragu' (tanya), JANGAN 'rutin'. Tak ada hapus permanen.
"""
from __future__ import annotations

import logging

from app.ai import guard
from app.config import settings
from app.kantor import mail_gmail, persetujuan as pst

log = logging.getLogger("kantor.rapi")

_TOOL = [{
    "name": "pilah_email",
    "description": "Klasifikasi satu email inbox untuk merapikan.",
    "input_schema": {
        "type": "object",
        "properties": {
            "kategori": {
                "type": "string",
                "enum": ["rutin", "penting", "ragu"],
                "description": "rutin = notifikasi/promosi/newsletter otomatis yang tak "
                               "butuh tindakan (aman diarsipkan). penting = butuh "
                               "perhatian/tindakan (tagihan, dari orang, pelanggan, "
                               "karyawan, hukum, kontrak, finansial). ragu = tak yakin.",
            },
            "alasan": {"type": "string", "description": "Alasan singkat."},
        },
        "required": ["kategori"],
    },
}]

_SYS = (
    "Kamu pemilah email untuk merapikan inbox. Isi tool 'pilah_email'. "
    "ATURAN MUTLAK: email berisi KODE OTP, verifikasi, login/sign-in, keamanan akun, "
    "reset/ubah password, atau peringatan keamanan → SELALU 'penting'. JANGAN PERNAH "
    "'rutin' untuk email seperti itu — jangan disentuh. "
    "'rutin' (cukup dirapikan, TAK perlu dilaporkan) untuk email otomatis yang tak "
    "butuh tindakan DAN bukan keamanan: promosi/iklan, newsletter, notifikasi sosial "
    "media, no-reply informatif, NOTIFIKASI/pemberitahuan otomatis dari "
    "bank/e-wallet/fintech (BRI, BCA, Mandiri, dll) — transaksi, mutasi, saldo, "
    "e-statement, struk/receipt pembayaran yang sudah selesai, DAN laporan "
    "harian/periodik otomatis dari aplikasi HR/absensi (mis. GajiHub: rekap "
    "presensi/aktivitas harian) atau aplikasi lain. 'penting' untuk yang "
    "butuh perhatian: TAGIHAN/invoice yang BELUM dibayar (ada jatuh tempo), email dari "
    "ORANG (bukan sistem), pelanggan/mitra, karyawan/HR, hukum/kontrak/pemerintah, "
    "ATAU keamanan/login/OTP. "
    "'ragu' bila tak yakin. PRINSIP: sedikit saja ragu → 'ragu' (JANGAN 'rutin'). "
    "Lebih baik bertanya daripada salah mengarsipkan."
)


async def _pilah(email: dict) -> dict:
    isi = f"Dari: {email.get('from', '')}\nSubjek: {email.get('subject', '')}\n\n{email.get('snippet', '')}"
    resp = await guard.panggil(
        pemanggil="rapi",
        model=settings.miniapp_model,  # Haiku (murah)
        max_tokens=150,
        system=_SYS,
        tools=_TOOL,
        tool_choice={"type": "tool", "name": "pilah_email"},
        messages=[{"role": "user", "content": isi}],
    )
    for b in resp.content:
        if getattr(b, "type", None) == "tool_use" and b.name == "pilah_email":
            return b.input or {}
    return {}


async def proses(mailbox: str, email: dict, aturan_list: list | None = None) -> str:
    """Pilah 1 email → tindakan. Return 'arsip' | 'usul' | 'penting'.
    Cek ATURAN pemilik (deterministik) DULU; kalau tak ada, baru klasifikasi Haiku."""
    from app.kantor import aturan
    kat = aturan.cocok_dari_list(email, aturan_list or [])  # 'rutin'/'penting'/None
    if kat is None:
        try:
            data = await _pilah(email)
        except Exception:  # noqa: BLE001
            log.warning("pilah email gagal (dianggap penting)", exc_info=True)
            return "penting"
        kat = (data.get("kategori") or "ragu").lower()
    frm, subj = email.get("from", ""), email.get("subject", "")
    if kat == "rutin":
        try:
            mail_gmail.arsip_rutin(mailbox, email["id"])
            log.info("auto-arsip rutin: %s — %s", frm, subj[:40])
            return "arsip"
        except Exception:  # noqa: BLE001
            log.warning("auto-arsip gagal", exc_info=True)
            return "penting"
    if kat == "ragu":
        ring = f"Dari {frm} — \"{subj}\"  (mailbox: {mailbox})"
        await pst.buat_pending(
            jenis="email_arsip", ringkasan=ring, diminta_oleh="bot-rapi",
            payload={"mailbox": mailbox, "id": email["id"],
                     "ringkasan_item": f"{frm} — {subj}"})
        return "usul"
    return "penting"
