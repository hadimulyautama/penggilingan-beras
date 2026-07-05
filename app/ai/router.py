"""Router niat SATU-panggilan (Sonnet) — pengganti cascade 'coba semua parser'.

Sebelumnya tiap pesan mencoba ~15 parser berurutan (tiap parser = 1 panggilan
LLM) → lambat. Di sini SATU panggilan mengklasifikasi pesan ke sebuah DOMAIN,
lalu bot cukup memanggil handler domain itu (yang mengekstrak detailnya).

Bila router salah/ragu, handler domain akan mengembalikan False dan bot jatuh ke
jalur cadangan (chain lama / agent) → tak ada regresi kebenaran.
"""
from __future__ import annotations

from app.ai.claude_client import get_client
from app.config import settings

# Domain yang dikenal. 'lainnya' = bukan perintah (pertanyaan/analitik/bebas) →
# bot lanjut ke jalur baca + agent.
DOMAINS = [
    "verifikasi_harga_gabah",  # tetapkan/verifikasi harga gabah (GB-...)
    "milling_qc",              # QC / verifikasi output milling (MIL-...)
    "transfer_pk",             # kirim/terima PK Gudang 1 -> Gudang 2 (TRF-...)
    "gudang2",                 # beli PK luar, QC PK luar, stok/silo Gudang 2
    "penyosohan",              # mulai/hasil/selesai penyosohan (POL-...)
    "kemasan",                 # beli/stok karung
    "barang_jadi",             # packing, bekatul, harga byproduct, HPP, stok BJ
    "barang_keluar",           # kirim/jual barang keluar (OUT-...)
    "pembelian_gabah",         # catat gabah masuk (Gudang 1)
    "pengeringan",             # keringkan/selesai pengeringan (LOT-...)
    "silo_g1",                 # masukkan lot ke silo / pindah dryer->silo (G1)
    "kelola_user",             # daftar/aktif/nonaktif pengguna
    "undo",                    # batalkan input terakhir
    "lainnya",                 # pertanyaan/laporan/bebas -> jalur baca + agent
]

_ROUTE_TOOL = {
    "name": "route",
    "description": (
        "Klasifikasikan pesan ke satu DOMAIN pabrik penggilingan beras. Pilih "
        "domain berdasarkan SUBJEK, baik itu PERINTAH (catat/ubah/verifikasi) "
        "MAUPUN PERTANYAAN/laporan tentang subjek itu — mis. 'berapa stok gudang "
        "2' dan 'stok silo A' = gudang2; 'stok karung' = kemasan; 'stok barang "
        "jadi'/'HPP beras' = barang_jadi. Gunakan 'lainnya' HANYA untuk pesan "
        "lintas-domain / ringkasan menyeluruh, analitik tren, sapaan, atau yang "
        "tak jelas subjeknya."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "domain": {
                "type": "string",
                "enum": DOMAINS,
                "description": (
                    "Domain aksi. Contoh: 'gabah masuk 5 ton'->pembelian_gabah; "
                    "'keringkan LOT-..'->pengeringan; 'giling silo A'->milling_qc "
                    "TIDAK (itu penyosohan? bukan) — 'giling/hasil PK' Gudang 1 = "
                    "milling_qc hanya utk QC/verifikasi output; mulai giling & hasil "
                    "PK Gudang 1 tetap di operator (pembelian? tidak). Gunakan: "
                    "'terima TRF-..'->transfer_pk; 'beli PK dari..'/'stok gudang 2'/"
                    "'stok silo A'->gudang2; 'QC PKB-..'->gudang2; 'mulai penyosohan'/"
                    "'hasil premium 5 ton'/'POL-.. selesai'->penyosohan; 'beli karung'"
                    "->kemasan; 'packing..'/'bekatul..'->barang_jadi; 'kirim..'/'jual "
                    "PK..'->barang_keluar; 'verifikasi GB-.. 7500'->verifikasi_harga_"
                    "gabah; 'daftar Budi operator'->kelola_user; 'batalkan input'->"
                    "undo. Pertanyaan/laporan/HPP/analitik/sapaan->lainnya."
                ),
            }
        },
        "required": ["domain"],
    },
}


async def route_domain(text: str, *, model: str | None = None) -> str:
    """Satu panggilan LLM → domain aksi (salah satu DOMAINS).

    `model` default = settings.agent_model (Sonnet). Klasifikasi ringan seperti
    ini juga cocok untuk model kecil (Haiku) bila latency jadi prioritas.
    """
    client = get_client()
    resp = await client.messages.create(
        model=model or settings.agent_model,
        max_tokens=120,
        tools=[_ROUTE_TOOL],
        tool_choice={"type": "tool", "name": "route"},
        messages=[{"role": "user", "content": text}],
    )
    for block in resp.content:
        if block.type == "tool_use" and block.name == "route":
            d = (block.input or {}).get("domain")
            if d in DOMAINS:
                return d
    return "lainnya"
