---
name: workspace-layout
description: "Tata letak folder ~/Developer/Hadi Mulya Systems setelah dirapikan 2026-09-02: workspace murni berisi 5 repo sejajar, produksi turun ke produksi/"
metadata:
  type: project
---

`~/Developer/Hadi Mulya Systems` **bukan repo** — ia workspace berisi lima repo sejajar
(dirapikan 2026-09-02; sebelumnya folder ini SEKALIGUS repo produksi, sehingga app/ migrations/
tests/ berserak sejajar dengan repo tetangga):

| Folder | Repo GitHub (org hadimulyautama) | Service Railway |
|---|---|---|
| `produksi/` | penggilingan-beras | penggilingan-beras |
| `kantor/`   | kantor                | kantor |
| `timbangan/`| timbangan             | timbangan |
| `website/`  | hadimulya-website     | — |
| `core/`     | hmu-core              | — |

Root hanya berisi kelima folder itu + `README.md` (peta workspace) + `.claude/`
(settings.local.json & launch.json milik workspace, TIDAK dilacak repo mana pun).

**Konsekuensi praktis:**
- venv produksi kini `produksi/.venv` (dibuat ulang saat pindah → shebang benar, `alembic`
  console-script jalan lagi; masalah shebang basi dari rename folder lama SUDAH BERES).
- `railway link` sudah diulang di `produksi/`. Tiap repo di-link ke service-nya sendiri.
- `graphify-out/` dan `.venv-mcp/` dihapus (turunan / sisa MCP). graphify bisa dibangun ulang.
- Sesi Claude Code tetap dijalankan dari ROOT workspace supaya kunci memori
  `-Users-wahidnurhani-Developer-Hadi-Mulya-Systems` tak berubah.

Peta arsitektur lengkap: `produksi/docs/ARSITEKTUR.md` (v1.4). Lihat juga
[[pisah-kantor-produksi]], [[timbangan-module]], [[company-website-project]].
