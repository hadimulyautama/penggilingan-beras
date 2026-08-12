"""Lapis TRIAGE murah (Haiku) di depan agent Sonnet.

Tujuan: pesan SEPELE (sapaan, terima kasih, basa-basi, konfirmasi paham) dijawab
langsung oleh model murah → tak membebani Sonnet. SEMUA yang butuh data/tool/
tindakan/pengetahuan perusahaan, atau merujuk konteks/tugas sebelumnya, atau bila
RAGU → diserahkan ke agen (eskalasi). Konservatif: default eskalasi.

Aman: bila Haiku gagal/timeout/format aneh → otomatis eskalasi (tak pernah
memblok). Tak pernah menghasilkan aksi/janji tindakan.
"""
from __future__ import annotations

import logging

from app.ai.claude_client import get_client
from app.config import settings

log = logging.getLogger("kantor.triage")

_TOOL = [{
    "name": "putuskan",
    "description": "Putuskan apakah pesan cukup dijawab langsung (obrolan ringan) "
                   "atau perlu agen penuh (butuh data/tool/tindakan).",
    "input_schema": {
        "type": "object",
        "properties": {
            "perlu_agen": {
                "type": "boolean",
                "description": "true bila butuh data/tool/tindakan/pengetahuan "
                               "perusahaan, merujuk tugas/konteks sebelumnya, atau "
                               "kamu ragu. false HANYA untuk obrolan sosial murni.",
            },
            "balasan": {
                "type": "string",
                "description": "Balasan singkat & ramah (Bahasa Indonesia), HANYA "
                               "diisi bila perlu_agen=false.",
            },
        },
        "required": ["perlu_agen"],
    },
}]

_SYS = (
    "Kamu lapis TRIAGE (resepsionis) untuk asisten kantor 'Kantor AI' milik "
    "PT Hadi Mulya Utama. Tugasmu HANYA memilah pesan dari {nama} lewat tool "
    "'putuskan':\n\n"
    "perlu_agen=FALSE (kamu jawab langsung, isi 'balasan') HANYA untuk obrolan "
    "sosial MURNI yang tak butuh data perusahaan: sapaan (halo, pagi, apa kabar), "
    "ucapan terima kasih, basa-basi, atau konfirmasi paham (oke, siap, baik, "
    "mantap, sip). Balasan: singkat, ramah, Bahasa Indonesia, tanpa mengarang "
    "fakta/angka & tanpa menjanjikan tindakan.\n\n"
    "perlu_agen=TRUE (serahkan ke agen) untuk SEMUA yang lain: minta data/laporan/"
    "stok/HPP/keuangan, email, HR/gaji/lembur/cuti, file/Drive/dokumen, kalender, "
    "pengetahuan/SOP, pertanyaan 'kamu bisa apa', tugas/tindakan apa pun, ATAU yang "
    "merujuk konteks/tugas sebelumnya, ATAU jika kamu RAGU sedikit pun. "
    "Saat ragu, SELALU TRUE."
)


async def triage(text: str, *, nama_user: str = "",
                 riwayat: list[dict] | None = None) -> tuple[bool, str]:
    """Kembalikan (ditangani, balasan). ditangani=True → jawab langsung dgn balasan;
    False → panggil agen Sonnet seperti biasa."""
    try:
        client = get_client()
        pesan = [*(riwayat or [])[-4:], {"role": "user", "content": text}]
        resp = await client.messages.create(
            model=settings.miniapp_model,  # Haiku (murah)
            max_tokens=300,
            system=_SYS.format(nama=nama_user or "pengguna"),
            tools=_TOOL,
            tool_choice={"type": "tool", "name": "putuskan"},
            messages=pesan,
        )
        data = None
        for blok in resp.content:
            if getattr(blok, "type", None) == "tool_use" and blok.name == "putuskan":
                data = blok.input or {}
                break
        if not data or data.get("perlu_agen", True):
            return (False, "")
        balasan = (data.get("balasan") or "").strip()
        if not balasan:
            return (False, "")
        log.info("triage: ditangani (hemat Sonnet) — '%s'", text[:40])
        return (True, balasan)
    except Exception:  # noqa: BLE001 — apa pun gagal → eskalasi (jangan blok)
        log.warning("triage gagal → eskalasi ke agen", exc_info=True)
        return (False, "")
