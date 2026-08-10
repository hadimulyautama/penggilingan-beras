"""Integrasi GajiHub (HR/payroll) — READ-ONLY, khusus ADMIN.

Data karyawan/gaji/cuti bersumber dari GajiHub via REST API (dilayani di domain
Kledo — satu grup). Env:
  GAJIHUB_API_KEY : Personal Access Token ('gajihub_pat_...')
  GAJIHUB_BASE    : opsional, base URL (default subdomain perusahaan)

Prinsip: bot MERANGKUM, tidak menghitung ulang — angka gaji tetap dari GajiHub
(anti tumpang-tindih). Sensitif (gaji/PII) → hanya role 'admin' yang boleh.
Tidak ada tool tulis di sini (murni baca).
"""
from __future__ import annotations

import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

log = logging.getLogger(__name__)

_BASE = os.getenv("GAJIHUB_BASE", "https://pthadimulyautama.api.kledo.com/api/v1")

NAMA_TOOL = ("karyawan_gajihub", "payroll_gajihub", "cuti_gajihub")


def terkonfigurasi() -> bool:
    return bool(os.getenv("GAJIHUB_API_KEY"))


def _boleh(role: str | None) -> bool:
    return (role or "").strip().lower() == "admin"


def _get(path: str, params: dict | None = None):
    tok = os.environ["GAJIHUB_API_KEY"]
    url = _BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(
        url, headers={"Authorization": "Bearer " + tok, "Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def _rows(d):
    """Normalisasi bentuk pagination Kledo → (list, total)."""
    data = d.get("data", d) if isinstance(d, dict) else d
    if isinstance(data, dict) and isinstance(data.get("data"), list):
        return data["data"], data.get("total")
    if isinstance(data, list):
        return data, len(data)
    return [], 0


# ─────────────────────────── fungsi baca ───────────────────────────
def daftar_karyawan(aktif_saja: bool = True) -> str:
    d = _get("/hr/employees/pagination", {"page": 1, "per_page": 300})
    rows, _ = _rows(d)
    if aktif_saja:
        rows = [r for r in rows if r.get("is_active")]
    if not rows:
        return "Tak ada data karyawan di GajiHub."
    rows.sort(key=lambda r: (r.get("code") or "", r.get("name") or ""))
    baris = [f"• {r.get('code', '')} — {r.get('name', '')}"
             + ("" if r.get("is_active") else " (nonaktif)") for r in rows]
    ket = " aktif" if aktif_saja else ""
    return f"👥 {len(rows)} karyawan{ket} (GajiHub):\n" + "\n".join(baris[:120])


def rekap_gaji() -> str:
    d = _get("/hr/salarySlips/pagination", {"page": 1, "per_page": 50})
    rows, _ = _rows(d)
    if not rows:
        return "Belum ada periode slip gaji tercatat di GajiHub."
    rows.sort(key=lambda r: str(r.get("period_started") or ""), reverse=True)
    baris = []
    for r in rows[:24]:
        nama = r.get("name") or r.get("period") or f"slip #{r.get('id')}"
        per = r.get("period") or r.get("period_started") or ""
        baris.append(f"• {nama}" + (f" — {per}" if per else ""))
    return (f"💰 {len(rows)} periode slip gaji (GajiHub):\n" + "\n".join(baris)
            + "\nUntuk rincian per karyawan pada satu periode, sebut nama periodenya.")


def cuti(nama: str = "") -> str:
    # data cuti dikelompokkan per karyawan; bisa perlu filter tahun
    try:
        d = _get("/hr/leaves/all/employees")
        rows, _ = _rows(d)
    except urllib.error.HTTPError as e:  # noqa: BLE001
        return f"Gagal ambil data cuti (HTTP {e.code})."
    if not rows:
        return ("Belum ada data cuti yang tercatat/terambil dari GajiHub "
                "(mungkin perlu filter tahun — bisa kuperbaiki bila kamu mau).")
    if nama:
        rows = [r for r in rows if nama.lower() in json.dumps(r, ensure_ascii=False).lower()]
        if not rows:
            return f"Tak ada data cuti untuk '{nama}'."
    return f"🌴 Data cuti (GajiHub): {len(rows)} entri. (Format rincian menyusul.)"


def jalankan(nama_tool: str, args: dict, role: str = "staff") -> str:
    if not terkonfigurasi():
        return "GajiHub belum terkonfigurasi (GAJIHUB_API_KEY belum ada di server)."
    if not _boleh(role):
        return "Data GajiHub (karyawan/gaji/cuti) bersifat sensitif — khusus admin."
    a = args or {}
    try:
        if nama_tool == "karyawan_gajihub":
            return daftar_karyawan(aktif_saja=not bool(a.get("termasuk_nonaktif")))
        if nama_tool == "payroll_gajihub":
            return rekap_gaji()
        if nama_tool == "cuti_gajihub":
            return cuti(a.get("nama", ""))
    except urllib.error.HTTPError as e:  # noqa: BLE001
        log.warning("GajiHub HTTP %s pada %s", e.code, nama_tool)
        return f"GajiHub menolak permintaan (HTTP {e.code})."
    except Exception:  # noqa: BLE001
        log.warning("GajiHub error pada %s", nama_tool, exc_info=True)
        return "Gagal mengambil data dari GajiHub (jaringan/format)."
    return f"(tool '{nama_tool}' tak dikenal)"
