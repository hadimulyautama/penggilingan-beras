"""Jembatan ke modul **AI Agent Production** (pabrik).

Prinsip integrasi: modul produksi tetap UTUH (agen + ~20 tool-nya) dan kini
tinggal di service-nya sendiri. Kantor tidak menyalin tool-nya — ia
**mendelegasikan** pertanyaan produksi lewat API internal
(`/internal/produksi/tanya`), yang menjawab otoritatif.

Read-only untuk sekarang (allow_write=False): pertanyaan/analitik/HPP/status. Aksi
tulis produksi tetap lewat jalur operator/pabrik (belum didelegasikan dari Kantor).
"""
from __future__ import annotations

from app.kantor import klien_produksi
from app.kantor import rbac

NAMA_TOOL = {"tanya_produksi"}

TOOLS = [
    {
        "name": "tanya_produksi",
        "description": (
            "Delegasikan pertanyaan PRODUKSI PABRIK ke modul AI Agent Production: "
            "produksi · milling/selepan · pengeringan · silo · penyosohan · stok "
            "gabah/PK/beras · rendemen · HPP · analitik biaya · verifikasi harga · "
            "status batch/lot. Pakai untuk APA PUN soal operasional pabrik & data "
            "produksi — modul itu menjawab dengan tarif & data resmi. Teruskan "
            "pertanyaan pengguna apa adanya."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "pertanyaan": {"type": "string", "description": "Pertanyaan produksi pengguna, apa adanya."},
            },
            "required": ["pertanyaan"],
        },
    }
]


async def jalankan(name: str, args: dict, user_id: int | None, role: str) -> str:
    pertanyaan = (args or {}).get("pertanyaan", "").strip()
    if not pertanyaan:
        return "Sebutkan pertanyaan produksinya."
    # Boleh lihat data uang produksi (HPP/harga) bila Direksi (admin) atau punya
    # grant baca 'keuangan'. Selain itu → jawaban tanpa nilai uang (sesuai gate pabrik).
    grants = await rbac.grants_user(user_id) if user_id is not None else {}
    financial = role == "admin" or rbac.boleh(grants, "keuangan", "read")
    try:
        teks = await klien_produksi.tanya(pertanyaan, role=role, financial=financial)
    except klien_produksi.ProduksiTakTersedia as e:
        return f"⚠️ {e}"
    return teks or "Modul produksi belum bisa menjawab itu."
