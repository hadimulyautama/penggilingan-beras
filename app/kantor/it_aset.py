"""Domain IT Management — BACA (read-only) database "IT Accounts" di Drive.

Sumber tunggal = Google Sheet "IT Accounts (Database)" (tab Services/Keamanan/Akses/
Users/Perbankan/…). TIDAK ada cermin DB — dibaca langsung tiap panggilan (selalu segar,
tak ada risiko sinkron basi). Radar renewal proaktif sudah ditangani deadline_poller.

PRIVASI: hanya kembalikan kolom OPERASIONAL non-rahasia (nama layanan, kategori, paket,
biaya, tgl renewal, PIC, admin, metode login, status 2FA/kepemilikan, siapa punya akses).
TIDAK PERNAH mengembalikan password/secret. Kolom login-email pun tidak ditarik.

Akses: Direksi (admin) ATAU pemegang grant baca domain `folder_it` (mis. Elfira). Selaras
RBAC — lihat rbac._domain_mode.
"""
from __future__ import annotations

import logging
import os
import re
from datetime import date, datetime, timedelta, timezone

log = logging.getLogger("kantor.it_aset")

_SHEET_ID = os.getenv("IT_ACCOUNTS_SHEET_ID",
                      "1BxcGg1GitQmjTwbKRHmXUdiU2c2Z1yXt9TGK7kIOLY0")
_WIB = timezone(timedelta(hours=7))
_BULAN = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "mei": 5, "jun": 6, "jul": 7,
          "agu": 8, "ags": 8, "agt": 8, "aug": 8, "sep": 9, "okt": 10, "oct": 10,
          "nov": 11, "des": 12, "dec": 12}
_ID_BULAN = ["", "Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep",
             "Okt", "Nov", "Des"]
_RE_TGL = re.compile(r"(\d{1,2})\s*([A-Za-z]{3,})\s*(\d{4})")


def terkonfigurasi() -> bool:
    from app.kantor.drive.client import terkonfigurasi as drive_ok
    return drive_ok()


async def _boleh(user_id: int | None, role: str | None) -> bool:
    if (role or "").strip().lower() == "admin":
        return True
    from app.kantor import rbac
    grants = await rbac.grants_user(user_id) if user_id is not None else {}
    return rbac.boleh(grants, "folder_it", "read")


def _parse_tgl(teks: str) -> date | None:
    m = _RE_TGL.search(teks or "")
    if not m:
        return None
    d, bln, th = m.groups()
    bulan = _BULAN.get(bln[:3].lower())
    if not bulan:
        return None
    try:
        return date(int(th), bulan, int(d))
    except ValueError:
        return None


def _sel(row: list, i: int) -> str:
    return str(row[i]).strip() if i < len(row) and row[i] is not None else ""


def _baca_tab(rentang: str) -> list[list]:
    """Baca satu rentang sheet (blocking; panggil via to_thread)."""
    from app.kantor.drive.client import DriveClient
    return DriveClient().sheet_baca(_SHEET_ID, rentang)


def _peta_user(users: list[list]) -> dict[str, str]:
    """UserID → Nama (tab Users: A UserID, B Nama)."""
    return {_sel(r, 0): _sel(r, 1) for r in users if _sel(r, 0) and _sel(r, 1)}


def _nama_user(kode: str, peta: dict[str, str]) -> str:
    """'U01' → 'Ahmad Wahid Nurhani (U01)'; kode tak dikenal → apa adanya."""
    kode = (kode or "").strip()
    nm = peta.get(kode)
    return f"{nm} ({kode})" if nm else kode


# ─────────────────────────── formatter/logika ───────────────────────────
def _fmt_services(rows: list[list], filter_kata: str = "",
                  peta_user: dict[str, str] | None = None) -> str:
    peta_user = peta_user or {}
    kata = filter_kata.lower().strip()
    baris = []
    for r in rows:
        svc, kat = _sel(r, 1), _sel(r, 2)
        if not svc:
            continue
        if kata and kata not in svc.lower() and kata not in kat.lower():
            continue
        paket, biaya, renew, pic = _sel(r, 8), _sel(r, 9), _sel(r, 10), _sel(r, 5)
        b = f"• {svc} [{kat}]"
        detail = []
        if paket and paket not in ("-", ""):
            detail.append(f"paket {paket}")
        if biaya and biaya not in ("-", ""):
            detail.append(f"biaya {biaya}")
        if renew and renew not in ("-", ""):
            detail.append(f"renewal {renew}")
        if pic:
            detail.append(f"PIC {_nama_user(pic, peta_user)}")
        if detail:
            b += " — " + ", ".join(detail)
        baris.append(b)
    if not baris:
        return "Tak ada layanan yang cocok." if kata else "Database IT kosong."
    judul = f"🗂️ Layanan IT ({len(baris)})"
    if kata:
        judul += f" — filter '{filter_kata}'"
    return judul + ":\n" + "\n".join(baris)


def _fmt_jatuh_tempo(rows: list[list], hari: int) -> str:
    hari_ini = datetime.now(_WIB).date()
    batas = hari_ini + timedelta(days=hari)
    akan, terlewat, berkala = [], [], []
    for r in rows:
        svc, renew = _sel(r, 1), _sel(r, 10)
        if not svc or not renew or renew in ("-", ""):
            continue
        d = _parse_tgl(renew)
        if d is None:
            if renew.lower() in ("bulanan", "tahunan", "berkala"):
                berkala.append(f"• {svc} — {renew}")
            continue
        tgl_str = f"{d.day} {_ID_BULAN[d.month]} {d.year}"
        selisih = (d - hari_ini).days
        if selisih < 0:
            terlewat.append((d, f"• {svc} — {tgl_str} (TERLEWAT {abs(selisih)} hari)"))
        elif d <= batas:
            akan.append((d, f"• {svc} — {tgl_str} ({selisih} hari lagi)"))
    blok = []
    if terlewat:
        blok.append("⚠️ TERLEWAT:\n" + "\n".join(x for _, x in sorted(terlewat)))
    if akan:
        blok.append(f"🔜 Jatuh tempo ≤{hari} hari:\n" + "\n".join(x for _, x in sorted(akan)))
    if berkala:
        blok.append("🔁 Berkala:\n" + "\n".join(berkala))
    if not blok:
        return f"Tak ada langganan yang jatuh tempo dalam {hari} hari ke depan."
    return "⏰ Renewal IT\n\n" + "\n\n".join(blok)


def _fmt_info(nama: str, services: list[list], keamanan: list[list],
              akses: list[list], peta_user: dict[str, str] | None = None) -> str:
    peta_user = peta_user or {}
    kata = nama.lower().strip()
    srow = next((r for r in services if kata in _sel(r, 1).lower()), None)
    if srow is None:
        return f"Layanan '{nama}' tak ditemukan di database IT."
    svc = _sel(srow, 1)
    baris = [f"🔧 {svc}"]
    peta = [("Kategori", 2), ("Paket", 8), ("Biaya", 9), ("Tgl Renewal", 10),
            ("PIC", 5), ("Admin", 7), ("Metode Login", 4), ("Catatan", 11)]
    for label, i in peta:
        v = _sel(srow, i)
        if v and v != "-":
            if label in ("PIC", "Admin"):
                v = _nama_user(v, peta_user)
            baris.append(f"• {label}: {v}")
    krow = next((r for r in keamanan if _sel(r, 1).lower() == svc.lower()
                 or (svc.lower() in _sel(r, 1).lower() and _sel(r, 1))), None)
    if krow is not None:
        for label, i in [("2FA", 4), ("Sifat akun", 5), ("Status kepemilikan", 7)]:
            v = _sel(krow, i)
            if v and v != "-":
                baris.append(f"• {label}: {v}")
    pemakai = [f"{_sel(r, 3)} ({_sel(r, 4)})" for r in akses
               if svc.lower() in _sel(r, 1).lower() and _sel(r, 3)]
    if pemakai:
        baris.append("• Akses: " + ", ".join(dict.fromkeys(pemakai)))
    baris.append("\n(Kredensial/password tak ditampilkan — lihat sheet langsung bila perlu.)")
    return "\n".join(baris)


# ─────────────────────────── tools ───────────────────────────
async def jalankan(nama_tool: str, args: dict, user_id: int | None = None,
                   role: str = "staff") -> str:
    if not terkonfigurasi():
        return "Google Drive belum terkonfigurasi — database IT tak bisa dibaca."
    if not await _boleh(user_id, role):
        return "Database IT Accounts hanya untuk Direksi / pemegang akses IT (folder_it)."
    import asyncio
    a = args or {}
    try:
        if nama_tool == "register_it":
            rows, users = await asyncio.gather(
                asyncio.to_thread(_baca_tab, "Services!A2:L300"),
                asyncio.to_thread(_baca_tab, "Users!A2:C300"),
            )
            return _fmt_services(rows, str(a.get("filter", "")), _peta_user(users))
        if nama_tool == "cek_jatuh_tempo_it":
            rows = await asyncio.to_thread(_baca_tab, "Services!A2:L300")
            return _fmt_jatuh_tempo(rows, int(a.get("hari", 45) or 45))
        if nama_tool == "info_layanan_it":
            nama = str(a.get("layanan", "")).strip()
            if not nama:
                return "Sebutkan nama layanannya (mis. 'Railway', 'Kledo')."
            services, keamanan, akses, users = await asyncio.gather(
                asyncio.to_thread(_baca_tab, "Services!A2:L300"),
                asyncio.to_thread(_baca_tab, "Keamanan!A2:I300"),
                asyncio.to_thread(_baca_tab, "Akses!A2:H300"),
                asyncio.to_thread(_baca_tab, "Users!A2:C300"),
            )
            return _fmt_info(nama, services, keamanan, akses, _peta_user(users))
    except Exception:  # noqa: BLE001
        log.exception("baca database IT gagal")
        return "Gagal membaca database IT (cek koneksi Drive)."
    return f"(tool IT '{nama_tool}' tak dikenal)"


TOOLS = [
    {"name": "register_it", "description":
        "Daftar LAYANAN/langganan IT perusahaan dari database IT Accounts (tab Services): "
        "nama, kategori, paket, biaya, tgl renewal, PIC. READ-ONLY, Direksi/akses IT saja. "
        "Pakai untuk 'ada langganan apa saja', 'daftar software/tools', 'layanan kategori X'. "
        "Opsional filter kata (nama/kategori).",
     "input_schema": {"type": "object", "properties": {
         "filter": {"type": "string", "description": "Kata saring nama/kategori (opsional)."}}}},
    {"name": "cek_jatuh_tempo_it", "description":
        "Langganan IT yang akan JATUH TEMPO / renewal (dan yang sudah terlewat) dari tab "
        "Services. READ-ONLY. Pakai untuk 'langganan apa yang mau jatuh tempo', 'renewal "
        "bulan ini', 'ada yang terlewat?'. (Radar harian otomatis sudah jalan terpisah.)",
     "input_schema": {"type": "object", "properties": {
         "hari": {"type": "integer", "description": "Cakupan ke depan (hari), default 45."}}}},
    {"name": "info_layanan_it", "description":
        "Detail SATU layanan IT (non-rahasia): kategori, paket, biaya, renewal, PIC, admin, "
        "metode login, status 2FA/kepemilikan, siapa yang punya akses. READ-ONLY, Direksi/"
        "akses IT saja. TIDAK menampilkan password. Pakai untuk 'PIC/admin Railway siapa', "
        "'paket & biaya Kledo', 'siapa punya akses ke X'.",
     "input_schema": {"type": "object", "properties": {
         "layanan": {"type": "string", "description": "Nama layanan (mis. 'Railway', 'Kledo')."}},
         "required": ["layanan"]}},
]

NAMA_TOOL = {t["name"] for t in TOOLS}
