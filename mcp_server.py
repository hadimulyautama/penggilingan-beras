"""MCP server: ekspos data & simulasi penggilingan beras ke agent (Hermes/Claude).

Membungkus service aplikasi yang sudah ada sebagai MCP tools — SATU sumber
kebenaran, rumus & angka selalu sinkron dengan aplikasi. READ-ONLY (belum ada
tool yang menulis/mengubah data).

Transport (via env MCP_TRANSPORT):
  - "stdio" (default)  : untuk Cowork/Claude Desktop di mesin yang sama.
  - "http"             : streamable-HTTP untuk agent remote (mis. Hermes di
                         VPS Hostinger). WAJIB set MCP_AUTH_TOKEN — tiap request
                         harus membawa header  Authorization: Bearer <token>.

Env lain:
  - MCP_AUTH_TOKEN : token bearer wajib saat transport http.
  - PORT           : port HTTP (default 8080).
  - DATABASE_URL   : dipakai tool read (default menunjuk Postgres lokal).

Jalankan:
  stdio :  python mcp_server.py
  http  :  MCP_TRANSPORT=http MCP_AUTH_TOKEN=xxxx PORT=8080 python mcp_server.py
"""
from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from mcp.server.transport_security import TransportSecuritySettings

from app.config import settings
from app.database import SessionLocal
from app.services.analytics import (
    hpp_trend as _hpp_trend,
    rekap_produksi_bulanan as _rekap_produksi,
    simulasi_hpp as _simulasi_hpp,
)

# Matikan proteksi DNS-rebinding FastMCP (default hanya izinkan host localhost →
# menolak domain Railway dengan 421 "Invalid Host header"). Aman di sini karena
# akses server-to-server sudah dijaga token bearer, bukan konteks browser.
mcp = FastMCP(
    "penggilingan-beras",
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    ),
)


# ─────────────────────────── Simulasi (murni) ───────────────────────────
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
        berat_bahan_kg: Tonase gabah masuk dalam KG (mis. 10000 = 10 ton). WAJIB —
            biaya operator flat per proses dibagi tonase ini.
        rendemen_persen: Rendemen (%) mis. 64. Boleh kosong bila berat_hasil_kg
            diisi (rendemen dihitung otomatis = hasil/bahan).
        berat_hasil_kg: Tonase hasil PK dalam KG (mis. 6400). Menghitung rendemen
            bila rendemen_persen kosong.
        kondisi: 'basah' (default, dikeringkan) atau 'kering'.
        langsung_silo: True bila gabah kering langsung ke silo tanpa pengeringan.
    """
    if kondisi not in ("basah", "kering"):
        return "kondisi harus 'basah' atau 'kering'."
    return _simulasi_hpp(
        harga_gabah, rendemen_persen, kondisi=kondisi,
        langsung_silo=langsung_silo, berat_bahan=berat_bahan_kg,
        berat_hasil=berat_hasil_kg,
    )


@mcp.tool()
def tarif_biaya_terkini() -> dict:
    """Tarif biaya produksi (Rp) yang menjadi asumsi simulasi HPP."""
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


# ─────────────────────────── Data nyata (read-only) ───────────────────────────
@mcp.tool()
async def stok_gudang1() -> str:
    """Status Gudang 1 (Selepan): gabah, pengeringan, silo, giling, PK siap kirim."""
    from app.services.report import status_gudang1
    from app.services.transfer import laporan_pk_siap_transfer
    async with SessionLocal() as db:
        return (await status_gudang1(db)) + "\n\n" + (await laporan_pk_siap_transfer(db))


@mcp.tool()
async def stok_gudang2() -> str:
    """Stok PK Gudang 2 (Penyosohan): silo A/B (+ HPP rata-rata) + tumpukan."""
    from app.gudang2.service import laporan_stok_gudang2
    async with SessionLocal() as db:
        return await laporan_stok_gudang2(db, financial=True)


@mcp.tool()
async def stok_barang_jadi() -> str:
    """Stok barang jadi (beras per jenis) + bekatul curah."""
    from app.inventory.finished_goods import hitung_stok_bekatul, laporan_stok_barang_jadi
    async with SessionLocal() as db:
        bekatul = float(await hitung_stok_bekatul(db))
        return (await laporan_stok_barang_jadi(db)) + f"\n\n🌾 Bekatul curah: {bekatul:,.0f} kg"


@mcp.tool()
async def stok_kemasan() -> str:
    """Stok kemasan (karung) per merk/jenis/ukuran."""
    from app.inventory.packaging import laporan_stok_kemasan
    async with SessionLocal() as db:
        return await laporan_stok_kemasan(db)


@mcp.tool()
async def hpp_beras_tren() -> str:
    """Tren HPP beras dari proses penyosohan terakhir (per periode)."""
    async with SessionLocal() as db:
        return await _hpp_trend(db)


@mcp.tool()
async def rekap_produksi_bulanan() -> str:
    """Rekap produksi PK per bulan + utilisasi vs kapasitas dryer."""
    async with SessionLocal() as db:
        return await _rekap_produksi(db)


@mcp.tool()
async def item_nyangkut() -> str:
    """Item 'nyangkut' lintas siklus yang perlu tindakan (gabah/dryer/silo/giling/
    penyosohan/verifikasi). Berguna sebagai peringatan proaktif untuk manajemen."""
    from app.services.pemantau import pemantau_nyangkut
    async with SessionLocal() as db:
        return await pemantau_nyangkut(db, financial=True, scope="all")


# ─────────────────────────── Entry point ───────────────────────────
def _run_http() -> None:
    """Streamable-HTTP + gerbang token bearer (untuk agent remote spt Hermes)."""
    import uvicorn
    from starlette.types import ASGIApp, Receive, Scope, Send

    token = os.environ.get("MCP_AUTH_TOKEN", "").strip()
    if not token:
        raise SystemExit(
            "MCP_TRANSPORT=http butuh MCP_AUTH_TOKEN (token bearer). "
            "Set env itu dulu — jangan ekspos data pabrik tanpa autentikasi."
        )

    app = mcp.streamable_http_app()

    class BearerGate:
        """Tolak request tanpa 'Authorization: Bearer <token>' yang cocok."""

        def __init__(self, inner: ASGIApp) -> None:
            self.inner = inner

        async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
            if scope["type"] == "http":
                # Healthcheck Railway (/health) TANPA token — bukan endpoint data.
                if scope.get("path") == "/health":
                    await send({"type": "http.response.start", "status": 200,
                                "headers": [(b"content-type", b"application/json")]})
                    await send({"type": "http.response.body",
                                "body": b'{"status":"ok","service":"mcp"}'})
                    return
                headers = dict(scope.get("headers") or [])
                auth = headers.get(b"authorization", b"").decode()
                if auth != f"Bearer {token}":
                    await send({"type": "http.response.start", "status": 401,
                                "headers": [(b"content-type", b"text/plain")]})
                    await send({"type": "http.response.body", "body": b"unauthorized"})
                    return
            await self.inner(scope, receive, send)

    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(BearerGate(app), host="0.0.0.0", port=port)


if __name__ == "__main__":
    if os.environ.get("MCP_TRANSPORT", "stdio").lower() == "http":
        _run_http()
    else:
        mcp.run()
