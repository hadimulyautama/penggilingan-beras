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

import asyncio
import datetime
import json
import logging
import os
import urllib.error
import urllib.parse
import urllib.request

from app.kantor import persetujuan as pst

log = logging.getLogger(__name__)

_BASE = os.getenv("GAJIHUB_BASE", "https://pthadimulyautama.api.kledo.com/api/v1")

# tool BACA (read-only)
NAMA_TOOL = ("karyawan_gajihub", "payroll_gajihub", "cuti_gajihub", "pengajuan_gajihub")
# tool USUL (konsekuensial → lewat gerbang tombol pemilik)
NAMA_USUL = ("setujui_pengajuan", "tolak_pengajuan")


def terkonfigurasi() -> bool:
    return bool(os.getenv("GAJIHUB_API_KEY"))


def _boleh(role: str | None) -> bool:
    return (role or "").strip().lower() == "admin"


def _hdr():
    return {"Authorization": "Bearer " + os.environ["GAJIHUB_API_KEY"],
            "Accept": "application/json"}


def _get(path: str, params: dict | None = None):
    url = _BASE + path
    if params:
        url += "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers=_hdr())
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def _patch(path: str, body: dict):
    h = _hdr()
    h["Content-Type"] = "application/json"
    req = urllib.request.Request(_BASE + path, data=json.dumps(body).encode(),
                                 method="PATCH", headers=h)
    with urllib.request.urlopen(req, timeout=25) as r:
        return json.load(r)


def _nm(v):
    """Ambil nama dari field yang bisa dict {name} atau string."""
    if isinstance(v, dict):
        return v.get("name") or v.get("full_name") or v.get("employee_name") or ""
    return str(v) if v not in (None, "") else ""


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


def _menunggu(r: dict) -> bool:
    return not r.get("date_approved") and not r.get("date_declined")


def _presensi_menunggu(dari: str = "", sampai: str = "") -> list[dict]:
    """Log presensi berstatus 'Menunggu Persetujuan' (status id 1) — incl. Mulai/Selesai Lembur."""
    hari = datetime.date.today()
    d = _get("/hr/attendanceLogs/approval/pagination", {
        "hr_attendance_log_status_id": 1,
        "date_started": dari or (hari - datetime.timedelta(days=90)).isoformat(),
        "date_ended": sampai or (hari + datetime.timedelta(days=1)).isoformat(),
        "page": 1, "per_page": 100,
    })
    rows, _ = _rows(d)
    return rows


def daftar_pengajuan(hanya_menunggu: bool = True) -> str:
    """Daftar pengajuan yang MENUNGGU: (a) HR approvals (lembur/cuti resmi) + (b) approval
    PRESENSI (Mulai/Selesai Lembur, koreksi presensi). id ditandai jenisnya (hr-/presensi-)."""
    baris = []
    # (a) HR approvals — lembur/cuti lewat modul pengajuan
    try:
        d = _get("/hr/approvals/pagination", {"page": 1, "per_page": 100})
        hr, _ = _rows(d)
        if hanya_menunggu:
            hr = [r for r in hr if _menunggu(r)]
        for r in hr[:40]:
            typ = _nm(r.get("hr_approval_type")) or "Pengajuan"
            who = _nm(r.get("hr_employee"))
            desc = (r.get("description") or "").strip()
            baris.append(f"• [hr-{r.get('id')}] {typ} — {who}" + (f": {desc}" if desc else ""))
    except Exception:  # noqa: BLE001
        log.warning("ambil HR approvals gagal", exc_info=True)
    # (b) approval PRESENSI — Mulai/Selesai Lembur & koreksi presensi
    try:
        for r in _presensi_menunggu()[:60]:
            typ = _nm(r.get("hr_attendance_log_type")) or "Presensi"
            who = _nm(r.get("hr_employee"))
            when = r.get("datetime") or r.get("created_at") or ""
            lok = _nm(r.get("hr_attendance_location"))
            baris.append(f"• [presensi-{r.get('id')}] {typ} — {who} · {when}"
                         + (f" · {lok}" if lok else ""))
    except Exception:  # noqa: BLE001
        log.warning("ambil approval presensi gagal", exc_info=True)
    if not baris:
        return "Tak ada pengajuan yang menunggu persetujuan di GajiHub. 👍"
    return (f"📥 {len(baris)} pengajuan menunggu persetujuan (GajiHub):\n" + "\n".join(baris)
            + "\nUntuk memutus, sebut id-nya: 'setujui [id]' / 'tolak [id] alasan …' "
              "(mis. presensi-123 atau hr-45).")


def _idlist(ids) -> list[int]:
    """Normalisasi id (int / str / 'a,b' / list) → list int untuk field 'ids' (array)."""
    seq = ids if isinstance(ids, (list, tuple)) else str(ids).split(",")
    out = []
    for x in seq:
        try:
            out.append(int(str(x).strip()))
        except (TypeError, ValueError):
            continue
    return out


def setujui(ids, catatan: str = "") -> dict:
    return _patch("/hr/approvals/approve",
                  {"ids": _idlist(ids), "description": catatan or "Disetujui via Kantor AI"})


def tolak(ids, catatan: str = "") -> dict:
    return _patch("/hr/approvals/decline",
                  {"ids": _idlist(ids), "description": catatan or "Ditolak via Kantor AI"})


def setujui_presensi(ids) -> dict:
    return _patch("/hr/attendanceLogs/approve", {"ids": _idlist(ids)})


def tolak_presensi(ids) -> dict:
    return _patch("/hr/attendanceLogs/reject", {"ids": _idlist(ids)})


def _diajukan(aid: int, ring: str) -> str:
    return (f"⏳ Diajukan ke pemilik untuk PERSETUJUAN (#{aid}) — BELUM dijalankan.\n"
            f"• {ring}\n"
            "Sampaikan: menunggu tombol ✅/❌ pemilik di Telegram; jangan mengaku sudah selesai.")


def _urai_id(tagged) -> tuple[str, str]:
    """'presensi-123' → ('presensi','123'); 'hr-45'/'45' → ('hr','45')."""
    s = str(tagged or "").strip()
    if s.lower().startswith("presensi-"):
        return "presensi", s.split("-", 1)[1]
    if s.lower().startswith("hr-"):
        return "hr", s.split("-", 1)[1]
    return "hr", s


async def usul_keputusan(tagged_id, *, tolak: bool = False, alasan: str = "") -> str:
    """Usulkan SETUJUI/TOLAK sebuah pengajuan (hr-* atau presensi-*) → gerbang tombol pemilik."""
    if not str(tagged_id or "").strip():
        return "Sebutkan id pengajuan (lihat dari pengajuan_gajihub, mis. presensi-123)."
    kind, num = _urai_id(tagged_id)

    def _detail():
        if kind == "presensi":
            for r in _presensi_menunggu():
                if str(r.get("id")) == str(num):
                    return (_nm(r.get("hr_attendance_log_type")) or "Presensi",
                            _nm(r.get("hr_employee")),
                            (r.get("datetime") or r.get("note") or "").strip())
            return None
        d = _get("/hr/approvals/pagination", {"page": 1, "per_page": 100})
        for r in _rows(d)[0]:
            if str(r.get("id")) == str(num) and _menunggu(r):
                return (_nm(r.get("hr_approval_type")) or "Pengajuan",
                        _nm(r.get("hr_employee")), (r.get("description") or "").strip())
        return None

    info = await asyncio.to_thread(_detail)
    if info is None:
        return f"Pengajuan {tagged_id} tak ditemukan / sudah diputus — cek lagi pengajuan_gajihub."
    typ, who, desc = info
    aksi = "TOLAK" if tolak else "SETUJUI"
    ring = f"{aksi} {typ} *{who}*" + (f" — {desc}" if desc else "")
    payload = {"kind": kind, "ids": str(num), "catatan": alasan,
               "ringkasan_item": f"{typ} {who}"}
    aid = await pst.buat_pending(
        jenis=("gajihub_tolak" if tolak else "gajihub_setujui"),
        ringkasan=ring, payload=payload, diminta_oleh="bot-kantor")
    return _diajukan(aid, ring)


async def jalankan_usul(nama_tool: str, args: dict, role: str = "staff") -> str:
    if not terkonfigurasi():
        return "GajiHub belum terkonfigurasi di server ini."
    if not _boleh(role):
        return "Menyetujui/menolak pengajuan HR khusus admin."
    a = args or {}
    if nama_tool == "setujui_pengajuan":
        return await usul_keputusan(a.get("id", ""), tolak=False, alasan=a.get("alasan", ""))
    if nama_tool == "tolak_pengajuan":
        return await usul_keputusan(a.get("id", ""), tolak=True, alasan=a.get("alasan", ""))
    return f"(usul '{nama_tool}' tak dikenal)"


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
        if nama_tool == "pengajuan_gajihub":
            return daftar_pengajuan(hanya_menunggu=not bool(a.get("semua")))
    except urllib.error.HTTPError as e:  # noqa: BLE001
        log.warning("GajiHub HTTP %s pada %s", e.code, nama_tool)
        return f"GajiHub menolak permintaan (HTTP {e.code})."
    except Exception:  # noqa: BLE001
        log.warning("GajiHub error pada %s", nama_tool, exc_info=True)
        return "Gagal mengambil data dari GajiHub (jaringan/format)."
    return f"(tool '{nama_tool}' tak dikenal)"
