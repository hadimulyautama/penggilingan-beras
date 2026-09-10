---
name: mcp-server
description: MCP server (service kedua di Railway) ekspos data penggilingan read-only untuk agent seperti Hermes
metadata: 
  node_type: memory
  type: project
  originSessionId: e19111b3-aeda-47a7-bccd-ac8a4b2e97d1
  modified: 2026-08-02T08:48:02.206Z
---

Sistem penggilingan punya MCP server (`mcp_server.py`) untuk agent AI eksternal (mis. Hermes dari Hostinger, Cowork/Claude Desktop).

- **Deploy**: service Railway KEDUA bernama `mcp` (project penggilingan-beras), dari repo yang sama (`hadimulyautama/penggilingan-beras`) via `Dockerfile.mcp`. URL: https://mcp-production-3d8e.up.railway.app (endpoint MCP: `/mcp`, healthcheck `/health`).
- **Transport**: streamable-HTTP, digerbang token bearer (env `MCP_AUTH_TOKEN` di service mcp). Env lain: `MCP_TRANSPORT=http`, `RAILWAY_DOCKERFILE_PATH=Dockerfile.mcp`, `DATABASE_URL=${{Postgres.DATABASE_URL}}`. Lokal bisa stdio (`python mcp_server.py`).
- **9 tool READ-ONLY**: simulasi_hpp, tarif_biaya_terkini, stok_gudang1/2, stok_barang_jadi, stok_kemasan, hpp_beras_tren, rekap_produksi_bulanan, item_nyangkut. Membungkus service aplikasi asli (single source of truth). Belum ada tool tulis.
- **Isolasi deps**: image mcp pakai `requirements-mcp.txt` (venv lokal `.venv-mcp`), TERPISAH dari app utama karena `mcp` butuh pydantic≥2.11 & starlette baru yang bentrok dengan aiogram/fastapi terpin. Service mcp TIDAK menjalankan bot (tanpa polling) → tak ada 409.

Jebakan yang sudah teratasi (jangan ulangi): (1) `railway.json` dulu memaksa `dockerfilePath: Dockerfile` untuk SEMUA service — dibuang agar `RAILWAY_DOCKERFILE_PATH` per-service berlaku. (2) pin `mcp>=1.12,<2` — mcp 2.0.0 menghapus `mcp.server.fastmcp`. (3) FastMCP perlu `TransportSecuritySettings(enable_dns_rebinding_protection=False)` agar domain Railway tak ditolak 421 "Invalid Host header".

Terkait: [[railway-deploy]], [[agentic-layer]], [[penggilingan-beras-project]].
