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
from app.kantor import mail_gmail

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
    "Kamu pemilah email untuk merapikan inbox. Isi tool 'pilah_email'. Pemilik HANYA "
    "mau diberi tahu untuk email yang BENAR-BENAR PENTING (butuh tindakan/responnya); "
    "sisanya rapikan DIAM-diam tanpa mengganggu. "
    "ATURAN MUTLAK: KODE OTP, verifikasi, login/sign-in, keamanan akun, reset/ubah "
    "password, peringatan keamanan → SELALU 'penting'. JANGAN disentuh. "
    "'penting' (dilaporkan) HANYA bila email MENUNTUT TINDAKAN/RESPONS pemilik: "
    "TAGIHAN/invoice BELUM dibayar (ada jatuh tempo), permintaan/pertanyaan/ajakan "
    "langsung dari ORANG (pelanggan/mitra/karyawan/rekan) yang menunggu jawaban, "
    "surat hukum/kontrak/pemerintah/pajak yang perlu ditindak, ATAU keamanan/OTP. "
    "'rutin' (arsip DIAM, TAK dilaporkan) untuk yang TAK menuntut tindakan: promosi/"
    "iklan, newsletter, notif media sosial, no-reply informatif, notifikasi/"
    "pemberitahuan otomatis bank/e-wallet/fintech (mutasi/saldo/e-statement/struk/"
    "receipt selesai), laporan periodik otomatis (GajiHub presensi dll), konfirmasi/"
    "resi selesai, DAN email FYI/pemberitahuan/CC yang cuma memberi info tanpa minta "
    "balasan — WALAU dari orang. "
    "'ragu' hanya bila benar-benar tak bisa ditentukan. "
    "PRINSIP: kalau tak jelas MENUNTUT tindakan pemilik → JANGAN 'penting'. Lebih baik "
    "rapikan diam-diam daripada mengganggu dengan email tak penting."
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
        # Tak jelas → JANGAN ganggu Telegram & JANGAN arsip (aman): dibiarkan di inbox
        # untuk ditinjau pemilik sendiri. (Dulu: kirim tombol penting/tidak — kini
        # dihapus agar hanya email PENTING yang muncul di Telegram.)
        return "diam"
    return "penting"
