"""Klasifikasi kategori arsip berbasis ISI (AI) — akurat, bukan tebak nama.

Membaca cuplikan isi dokumen lalu meminta Claude menentukan kategori baku
(00–11) sesuai Pedoman Kearsipan Digital. Dipakai untuk kasus yang tak andal
dengan kata kunci (mis. 'SK Manager Gudang' yang keyword-nya salah tebak 04,
padahal SK = SDM 03).

Mengembalikan: {kode, keyakinan (0-1), alasan}. Keyakinan rendah → tetap
diserahkan ke manusia.
"""
from __future__ import annotations

from app.ai.claude_client import get_client
from app.config import settings
from app.kantor.drive import taksonomi as tx

# Daftar kategori tujuan (00–11 + 99) untuk enum & prompt.
_TUJUAN = [k for k in tx.KATEGORI if k.kode != tx.TRANSIT]
_KODE_ENUM = [k.kode for k in _TUJUAN]


def _peta_kategori() -> str:
    return "\n".join(f"  {k.kode} = {k.nama}: {k.isi}" for k in _TUJUAN)


_TOOL = {
    "name": "klasifikasi",
    "description": (
        "Tentukan kategori arsip yang PALING tepat untuk sebuah dokumen "
        "perusahaan, berdasarkan ISI & fungsinya (bukan sekadar kata di nama)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "kode": {"type": "string", "enum": _KODE_ENUM,
                     "description": "Kode kategori tujuan (00–11 / 99)."},
            "keyakinan": {"type": "number",
                          "description": "Keyakinan 0.0–1.0."},
            "alasan": {"type": "string",
                       "description": "Alasan singkat (1 kalimat)."},
        },
        "required": ["kode", "keyakinan", "alasan"],
    },
}

_SYSTEM = (
    "Anda arsiparis PT Hadi Mulya Utama. Klasifikasikan dokumen ke SATU kategori "
    "arsip digital baku berdasarkan FUNGSI/isinya (Pedoman Kearsipan Digital). "
    "Ingat kaidah: dokumen tentang ORANG/pegawai (SK, kontrak kerja, jobdesk, "
    "surat tugas, paklaring) SELALU ke 03 SDM walau menyebut gudang/mesin. "
    "Pajak selalu 02. Aset/mesin/kendaraan 07. Peta kategori:\n" + _peta_kategori()
)


async def klasifikasi_isi(nama: str, isi_teks: str, *, model: str | None = None) -> dict:
    """Klasifikasi 1 dokumen → {kode, keyakinan, alasan}. {} bila gagal."""
    client = get_client()
    resp = await client.messages.create(
        model=model or settings.agent_model,
        max_tokens=300,
        system=_SYSTEM,
        tools=[_TOOL],
        tool_choice={"type": "tool", "name": "klasifikasi"},
        messages=[{
            "role": "user",
            "content": f"Nama file: {nama}\n\nCuplikan isi:\n{(isi_teks or '')[:3500]}",
        }],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "klasifikasi":
            out = dict(block.input)
            kat = tx.kategori(out.get("kode", ""))
            out["kategori_nama"] = kat.nama if kat else "?"
            return out
    return {}


async def periksa_entri(c, e, *, ambang: float = 0.8) -> dict:
    """Ambil isi entri → klasifikasi AI → verdikt penempatan.

    `c` = DriveClient (utk unduh_teks). Return {entri, kode_ai, yakin, alasan,
    kategori_nama, nyasar}. nyasar=True bila AI yakin (≥ambang) & beda kategori.
    """
    teks = c.unduh_teks(e.id, e.mime)
    r = await klasifikasi_isi(e.nama, teks)
    kode, yakin = r.get("kode"), float(r.get("keyakinan") or 0)
    nyasar = bool(kode and kode != e.kategori and yakin >= ambang)
    return {
        "entri": e, "kode_ai": kode, "yakin": yakin,
        "alasan": r.get("alasan"), "kategori_nama": r.get("kategori_nama"),
        "ada_teks": bool(teks), "nyasar": nyasar,
    }
