"""Email via Zoho Mail REST API (OAuth) untuk agen bot Kantor.

DESAIN: backend (Zoho API) terpisah dari tool. Saat migrasi ke Google/Gmail
nanti, cukup ganti fungsi di modul ini — antarmuka (baca/cari/kirim) & tool agen
TETAP, tak perlu bangun ulang.

Kirim email LEWAT gerbang persetujuan (kirim_email → buat_pending → tombol
pemilik). Baca = langsung (read-only). Kredensial dari env (penggilingan-beras):
  ZOHO_ACCOUNT_ID, ZOHO_REFRESH_TOKEN, ZOHO_CLIENT_ID, ZOHO_CLIENT_SECRET, ZOHO_EMAIL
Region .com (default; ganti ZOHO_ACCOUNTS_HOST/ZOHO_MAIL_HOST bila beda).
"""
from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request

_ACCOUNTS = os.getenv("ZOHO_ACCOUNTS_HOST", "https://accounts.zoho.com")
_MAIL = os.getenv("ZOHO_MAIL_HOST", "https://mail.zoho.com")
_OFF = "Email Zoho belum terkonfigurasi (env ZOHO_* belum lengkap)."
_ENV = ("ZOHO_ACCOUNT_ID", "ZOHO_REFRESH_TOKEN", "ZOHO_CLIENT_ID",
        "ZOHO_CLIENT_SECRET", "ZOHO_EMAIL")
_tok: dict = {"access": None}


def terkonfigurasi() -> bool:
    return all(os.getenv(k) for k in _ENV)


def _refresh_token() -> str:
    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": os.environ["ZOHO_REFRESH_TOKEN"],
        "client_id": os.environ["ZOHO_CLIENT_ID"],
        "client_secret": os.environ["ZOHO_CLIENT_SECRET"],
    }).encode()
    req = urllib.request.Request(f"{_ACCOUNTS}/oauth/v2/token", body, method="POST")
    with urllib.request.urlopen(req) as r:
        data = json.load(r)
    if "access_token" not in data:
        raise RuntimeError(f"gagal refresh token Zoho: {data}")
    _tok["access"] = data["access_token"]
    return _tok["access"]


def _api(method: str, path: str, body: dict | None = None) -> dict:
    """Panggil Zoho Mail API; refresh access token otomatis saat 401."""
    if not _tok["access"]:
        _refresh_token()
    url = f"{_MAIL}{path}"
    for attempt in range(2):
        headers = {"Authorization": f"Zoho-oauthtoken {_tok['access']}"}
        data = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            data = json.dumps(body).encode()
        req = urllib.request.Request(url, data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as r:
                return json.load(r)
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt == 0:
                _refresh_token()
                continue
            raise RuntimeError(f"Zoho API {e.code}: {e.read().decode('utf-8', 'ignore')[:200]}")
    return {}


def _aid() -> str:
    return os.environ["ZOHO_ACCOUNT_ID"]


def _fmt(rows: list[dict]) -> str:
    baris = []
    for m in rows:
        uid = f"{m.get('folderId', '')}:{m.get('messageId', '')}"
        baris.append(f"• [{uid}] {m.get('fromAddress', '?')} — "
                     f"{m.get('subject', '(tanpa subjek)')}")
    return "\n".join(baris)


def baca_email(maks: int = 10) -> str:
    """Email TERBARU di INBOX (read-only). Hasil menyertakan [uid] untuk baca_email_isi."""
    if not terkonfigurasi():
        return _OFF
    try:
        res = _api("GET", f"/api/accounts/{_aid()}/messages/view?limit={maks}")
    except Exception as e:  # noqa: BLE001
        return f"Gagal ambil email: {e}"
    rows = res.get("data", []) or []
    return f"📧 {len(rows)} email terbaru:\n{_fmt(rows)}" if rows else "INBOX kosong."


def cari_email(kata: str, maks: int = 10) -> str:
    """Cari email (pengirim/subjek/isi mengandung `kata`). Read-only."""
    if not terkonfigurasi():
        return _OFF
    if not (kata or "").strip():
        return "Kata pencarian kosong."
    q = urllib.parse.quote(kata)
    try:
        res = _api("GET", f"/api/accounts/{_aid()}/messages/search?searchKey={q}&limit={maks}")
    except Exception as e:  # noqa: BLE001
        return f"Gagal cari email: {e}"
    rows = res.get("data", []) or []
    return (f"🔎 {len(rows)} email cocok '{kata}':\n{_fmt(rows)}"
            if rows else f"Tak ada email yang cocok '{kata}'.")


def _strip_html(s: str) -> str:
    s = re.sub(r"(?is)<(script|style).*?</\1>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", " ", s)
    s = re.sub(r"\s+\n", "\n", s)
    return re.sub(r"[ \t]{2,}", " ", s).strip()


def baca_email_isi(uid: str) -> str:
    """Isi teks satu email. `uid` = 'folderId:messageId' dari baca_email/cari_email."""
    if not terkonfigurasi():
        return _OFF
    if ":" not in (uid or ""):
        return "uid tak valid — ambil dari baca_email/cari_email (bentuk folderId:messageId)."
    fid, mid = uid.split(":", 1)
    try:
        res = _api("GET", f"/api/accounts/{_aid()}/folders/{fid}/messages/{mid}/content")
    except Exception as e:  # noqa: BLE001
        return f"Gagal baca isi email: {e}"
    d = res.get("data", {}) or {}
    isi = d.get("content", "") or ""
    teks = _strip_html(isi) if "<" in isi else isi
    return f"📧 {d.get('subject', '')}\nDari: {d.get('fromAddress', '')}\n\n{teks[:3000]}"


def kirim(ke: str, subjek: str, isi: str) -> None:
    """Kirim email via Zoho API. Dipanggil eksekutor SETELAH persetujuan pemilik."""
    _api("POST", f"/api/accounts/{_aid()}/messages", {
        "fromAddress": os.environ["ZOHO_EMAIL"],
        "toAddress": ke,
        "subject": subjek,
        "content": isi,
        "mailFormat": "plaintext",
    })


# ─────────────────────── dispatch tool (dipakai agen) ───────────────────────
_BACA = {
    "baca_email": lambda a: baca_email(int(a.get("maks", 10) or 10)),
    "cari_email": lambda a: cari_email(a.get("kata", ""), int(a.get("maks", 10) or 10)),
    "baca_email_isi": lambda a: baca_email_isi(a.get("uid", "")),
}
NAMA_BACA = tuple(_BACA)
NAMA_TULIS = ("kirim_email",)


def jalankan_baca(nama_tool: str, args: dict) -> str:
    fn = _BACA.get(nama_tool)
    return fn(args or {}) if fn else f"(tool '{nama_tool}' tak dikenal)"


async def jalankan_tulis(nama_tool: str, args: dict) -> str:
    """Usulkan kirim email → gerbang persetujuan pemilik."""
    from app.kantor import persetujuan as pst

    a = args or {}
    if nama_tool != "kirim_email":
        return f"(aksi '{nama_tool}' tak dikenal)"
    ke, subjek, isi = a.get("ke", ""), a.get("subjek", ""), a.get("isi", "")
    if not ke.strip() or not subjek.strip() or not isi.strip():
        return "Penerima (ke), subjek, dan isi wajib diisi."
    ring = f"Kirim email ke *{ke}* — subjek: *{subjek}*"
    aid = await pst.buat_pending(
        jenis="email_kirim", ringkasan=ring,
        payload={"ke": ke, "subjek": subjek, "isi": isi}, diminta_oleh="bot-kantor")
    return (f"⏳ Diajukan ke pemilik untuk PERSETUJUAN (#{aid}) — BELUM dikirim.\n"
            f"• {ring}\nSampaikan ke pengguna: email MENUNGGU persetujuan pemilik "
            "(tombol ✅/❌); baru terkirim setelah Setujui. Jangan mengaku sudah terkirim.")
