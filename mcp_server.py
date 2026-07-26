"""MCP server: ekspos SIMULASI HPP penggilingan beras ke Cowork / Claude.

Membungkus fungsi murni `app.services.analytics.simulasi_hpp` sebagai satu MCP
tool. TIDAK butuh database, token, atau koneksi apa pun — tarif biaya dibaca
dari `app.config.settings` (punya nilai default; bisa dioverride lewat .env).
Karena memakai fungsi asli, rumus & tarif selalu sinkron dengan aplikasi.

Jalankan (transport stdio, untuk Cowork/Claude Desktop):
    python mcp_server.py
"""
from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from app.config import settings
from app.services.analytics import simulasi_hpp as _simulasi_hpp

mcp = FastMCP("penggilingan-hpp")


@mcp.tool()
def simulasi_hpp(
    harga_gabah: float,
    berat_bahan_kg: float,
    rendemen_persen: float | None = None,
    berat_hasil_kg: float | None = None,
    kondisi: str = "basah",
    langsung_silo: bool = False,
) -> str:
    """Simulasi (what-if) HPP beras pecah kulit (PK) dari harga gabah & rendemen.

    Menghitung HPP per kg PK memakai tarif biaya terkini pabrik (bongkar,
    pengeringan, operator FLAT per proses, rubber roll, listrik, tenaga giling).
    Murni skenario angka — TIDAK memakai data batch/stok nyata.

    Args:
        harga_gabah: Harga beli gabah, Rp per kg (mis. 7800).
        berat_bahan_kg: Tonase gabah masuk dalam KG (mis. 10000 = 10 ton).
            WAJIB — biaya operator flat per proses dibagi tonase ini.
        rendemen_persen: Rendemen (%) mis. 64. Boleh kosong bila
            berat_hasil_kg diisi (rendemen dihitung otomatis = hasil/bahan).
        berat_hasil_kg: Tonase hasil PK dalam KG (mis. 6400). Dipakai untuk
            menghitung rendemen bila rendemen_persen kosong.
        kondisi: 'basah' (default, dikeringkan) atau 'kering'.
        langsung_silo: True bila gabah kering langsung ke silo tanpa pengeringan.

    Returns:
        Ringkasan HPP per kg PK + rincian komponen biaya (teks siap dibaca).
    """
    if kondisi not in ("basah", "kering"):
        return "kondisi harus 'basah' atau 'kering'."
    return _simulasi_hpp(
        harga_gabah,
        rendemen_persen,
        kondisi=kondisi,
        langsung_silo=langsung_silo,
        berat_bahan=berat_bahan_kg,
        berat_hasil=berat_hasil_kg,
    )


@mcp.tool()
def tarif_biaya_terkini() -> dict:
    """Tarif biaya produksi yang dipakai simulasi HPP (Rp, kecuali disebut lain).

    Berguna agar Cowork tahu asumsi angka di balik simulasi.
    """
    s = settings
    return {
        "biaya_bongkar_per_kg_gabah": s.biaya_bongkar_per_kg_gabah,
        "biaya_operator_per_proses_milling": s.biaya_operator_per_proses,
        "biaya_tenaga_milling_per_kg_pk": s.biaya_tenaga_milling_per_kg_pk,
        "biaya_pengeringan_basah_per_kg": s.biaya_pengeringan_basah_per_kg,
        "biaya_pengeringan_kering_per_kg": s.biaya_pengeringan_kering_per_kg,
        "biaya_listrik_milling_per_kg_gabah": s.biaya_listrik_milling_per_kg_gabah,
        "rubber_roll_harga_per_set": s.rubber_roll_harga_per_set,
        "rubber_roll_umur_ton": s.rubber_roll_umur_ton,
        "rendemen_asumsi_persen": s.rendemen_asumsi_persen,
    }


if __name__ == "__main__":
    mcp.run()
