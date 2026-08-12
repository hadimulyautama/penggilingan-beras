"""Backend Gmail (Google Workspace) untuk agen Kantor — kelola BANYAK mailbox.

Memakai **Service Account + Domain-wide Delegation**: 1 kredensial yang meng-
impersonate mailbox tertentu (finance@/admin@/wahidnurhani@) di domain
hadimulya.com. Menggantikan backend Zoho lama (surel.py) untuk multi-mailbox.

ENV (service penggilingan-beras):
  GMAIL_SA_JSON   : isi JSON key service account (string JSON penuh, atau base64).
  GMAIL_MAILBOXES : daftar mailbox yang BOLEH dikelola, dipisah koma. Ini juga
                    ALLOW-LIST keamanan — di luar daftar ini ditolak.

Prinsip keamanan (selaras aturan proyek):
  • Baca/cari/draft/label/arsip/tandai-dibaca  → langsung (reversibel).
  • KIRIM email                                → LEWAT gerbang tombol pemilik
    (persetujuan.buat_pending → _lakukan.email_kirim → mail_gmail.kirim).
  • TIDAK ada hapus permanen (scope gmail.modify saja; trash pun tak dipakai).
  • Semua tool baca/tulis email di agen di-gate role='admin'.
"""
from __future__ import annotations

import base64
import json
import logging
import os
from email.mime.text import MIMEText
from email.utils import parseaddr

log = logging.getLogger(__name__)

# gmail.modify = baca + label/arsip + draft (TANPA hapus permanen).
# gmail.send   = kirim (tetap lewat gerbang persetujuan).
_SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

# tool BACA/RAPIKAN (langsung) — vs kirim yang lewat gerbang (lihat agent.py)
NAMA_TOOL = (
    "baca_email", "cari_email", "baca_email_isi",
    "draft_email", "arsip_email", "tandai_dibaca_email", "label_email",
    "batalkan_arsip_email",
)
# tool KIRIM (konsekuensial → gerbang tombol pemilik)
NAMA_USUL = ("kirim_email",)


def _sa_info() -> dict:
    raw = os.getenv("GMAIL_SA_JSON", "").strip()
    if not raw:
        raise RuntimeError("GMAIL_SA_JSON belum diset.")
    if not raw.lstrip().startswith("{"):  # mungkin base64
        raw = base64.b64decode(raw).decode("utf-8")
    return json.loads(raw)


def _pribadi_map() -> dict[str, str]:
    """email(lower) -> refresh_token untuk akun pribadi (OAuth). Dukung beberapa akun:
    GMAIL_PRIBADI_EMAIL/REFRESH_TOKEN, GMAIL_PRIBADI2_*, GMAIL_PRIBADI3_*."""
    out: dict[str, str] = {}
    for suf in ("", "2", "3", "4"):
        e = os.getenv(f"GMAIL_PRIBADI{suf}_EMAIL", "").strip().lower()
        t = os.getenv(f"GMAIL_PRIBADI{suf}_REFRESH_TOKEN", "")
        if e and t:
            out.setdefault(e, t)
    return out


def _pribadi_utama() -> str:
    """Akun pribadi utama (alias 'pribadi')."""
    e = os.getenv("GMAIL_PRIBADI_EMAIL", "").strip().lower()
    pm = _pribadi_map()
    return e if e in pm else next(iter(pm), "")


def daftar_mailbox() -> list[str]:
    ws = [m.strip().lower() for m in os.getenv("GMAIL_MAILBOXES", "").split(",") if m.strip()]
    for pr in _pribadi_map():
        if pr not in ws:
            ws.append(pr)  # akun pribadi (OAuth) ikut dikelola
    return ws


def terkonfigurasi() -> bool:
    return (bool(os.getenv("GMAIL_SA_JSON")) or bool(_pribadi_map())) and bool(daftar_mailbox())


def _mailbox_sah(m: str) -> str:
    """Kembalikan mailbox yang sah (dalam allow-list) atau lempar."""
    m = (m or "").strip().lower()
    boleh = daftar_mailbox()
    if not m and len(boleh) == 1:
        return boleh[0]
    if m in boleh:
        return m
    if m in ("pribadi", "personal", "gmail") and _pribadi_utama():
        return _pribadi_utama()
    # izinkan sebut nama pendek: 'finance' → finance@...
    for x in boleh:
        if x.split("@", 1)[0] == m:
            return x
    raise ValueError(f"Mailbox '{m}' tak dikelola. Pilihan: {', '.join(boleh) or '(kosong)'}")


def _svc(mailbox: str):
    from googleapiclient.discovery import build
    mb = (mailbox or "").strip().lower()
    pm = _pribadi_map()
    if mb in pm:
        # Akun pribadi (Gmail konsumen) → kredensial OAuth (bukan DWD Workspace).
        from google.oauth2.credentials import Credentials
        cid = os.getenv("GMAIL_OAUTH_CLIENT_ID") or os.environ["GDRIVE_OAUTH_CLIENT_ID"]
        csec = os.getenv("GMAIL_OAUTH_CLIENT_SECRET") or os.environ["GDRIVE_OAUTH_CLIENT_SECRET"]
        creds = Credentials(
            token=None, refresh_token=pm[mb],
            token_uri="https://oauth2.googleapis.com/token",
            client_id=cid, client_secret=csec, scopes=_SCOPES)
    else:
        from google.oauth2 import service_account
        creds = service_account.Credentials.from_service_account_info(
            _sa_info(), scopes=_SCOPES).with_subject(mailbox)
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


# ─────────────────────────── util isi pesan ───────────────────────────
def _hdr(payload: dict, nama: str) -> str:
    for h in payload.get("headers", []):
        if h.get("name", "").lower() == nama.lower():
            return h.get("value", "")
    return ""


def _teks_body(payload: dict) -> str:
    """Ambil body text/plain (rekursif); fallback ke text/html distrip kasar."""
    mime = payload.get("mimeType", "")
    body = payload.get("body", {})
    data = body.get("data")
    if mime == "text/plain" and data:
        return base64.urlsafe_b64decode(data).decode("utf-8", "ignore")
    html = ""
    for part in payload.get("parts", []) or []:
        t = _teks_body(part)
        if t and part.get("mimeType") == "text/plain":
            return t
        if t:
            html = html or t
    if not html and mime == "text/html" and data:
        import re
        raw = base64.urlsafe_b64decode(data).decode("utf-8", "ignore")
        html = re.sub(r"<[^>]+>", " ", raw)
    return html.strip()


# ─────────────────────────── baca / cari ───────────────────────────
def daftar(mailbox: str, kueri: str = "", n: int = 12) -> str:
    mb = _mailbox_sah(mailbox)
    svc = _svc(mb)
    q = kueri or "in:inbox"
    res = svc.users().messages().list(userId="me", q=q, maxResults=min(n, 25)).execute()
    ids = [m["id"] for m in res.get("messages", [])]
    if not ids:
        return f"📭 Tak ada email cocok di {mb} (kueri: {q!r})."
    baris = []
    for mid in ids:
        m = svc.users().messages().get(
            userId="me", id=mid, format="metadata",
            metadataHeaders=["From", "Subject", "Date"]).execute()
        p = m.get("payload", {})
        frm = parseaddr(_hdr(p, "From"))[1] or _hdr(p, "From")
        subj = _hdr(p, "Subject") or "(tanpa subjek)"
        tgl = _hdr(p, "Date")
        belum = "🔵 " if "UNREAD" in m.get("labelIds", []) else ""
        snip = (m.get("snippet", "") or "")[:90]
        baris.append(f"• {belum}[{mid}] {frm} — {subj}\n   {tgl}\n   {snip}")
    return f"📬 {len(baris)} email di {mb} (kueri: {q!r}):\n" + "\n".join(baris) + \
        "\nUntuk isi lengkap: 'baca pesan [id]'. Balas: 'draft [id] …'."


def cari(mailbox: str, kueri: str, n: int = 12) -> str:
    return daftar(mailbox, kueri=kueri, n=n)


def baca_pesan(mailbox: str, message_id: str) -> str:
    mb = _mailbox_sah(mailbox)
    svc = _svc(mb)
    m = svc.users().messages().get(userId="me", id=message_id, format="full").execute()
    p = m.get("payload", {})
    frm = _hdr(p, "From")
    ke = _hdr(p, "To")
    subj = _hdr(p, "Subject") or "(tanpa subjek)"
    tgl = _hdr(p, "Date")
    isi = _teks_body(p) or m.get("snippet", "")
    return (f"✉️ {mb} · pesan [{message_id}]\nDari: {frm}\nKe: {ke}\n"
            f"Tgl: {tgl}\nSubjek: {subj}\n\n{isi[:4000]}")


# ─────────────────────────── draft (reversibel) ───────────────────────────
def _mime(mb: str, ke: str, subjek: str, isi: str, refs: dict | None = None) -> dict:
    msg = MIMEText(isi, "plain", "utf-8")
    msg["To"] = ke
    msg["From"] = mb
    msg["Subject"] = subjek
    if refs:
        if refs.get("Message-ID"):
            msg["In-Reply-To"] = refs["Message-ID"]
            msg["References"] = refs["Message-ID"]
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    return {"raw": raw}


def _refs_balasan(svc, message_id: str) -> tuple[dict, str, str, str]:
    """Ambil Message-ID/threadId/subjek/pengirim asli utk balasan."""
    m = svc.users().messages().get(
        userId="me", id=message_id, format="metadata",
        metadataHeaders=["Message-ID", "Subject", "From"]).execute()
    p = m.get("payload", {})
    subj = _hdr(p, "Subject")
    if subj and not subj.lower().startswith("re:"):
        subj = "Re: " + subj
    frm = parseaddr(_hdr(p, "From"))[1]
    return {"Message-ID": _hdr(p, "Message-ID")}, m.get("threadId", ""), subj, frm


def buat_draft(mailbox: str, ke: str = "", subjek: str = "", isi: str = "",
               balas_ke_id: str = "") -> str:
    mb = _mailbox_sah(mailbox)
    svc = _svc(mb)
    refs, thread_id = None, None
    if balas_ke_id:
        refs, thread_id, subj0, frm0 = _refs_balasan(svc, balas_ke_id)
        ke = ke or frm0
        subjek = subjek or subj0
    if not ke:
        return "Tujuan (ke) wajib untuk draft."
    body = {"message": _mime(mb, ke, subjek or "(tanpa subjek)", isi, refs)}
    if thread_id:
        body["message"]["threadId"] = thread_id
    d = svc.users().drafts().create(userId="me", body=body).execute()
    return (f"📝 Draft dibuat di {mb} (id draft {d.get('id')}) → ke {ke}, subjek "
            f"'{subjek}'. Tersimpan di folder Draft Gmail untuk kamu review/ubah/kirim. "
            "Untuk mengirim: minta 'kirim' → lewat tombol persetujuanmu.")


# ─────────────────────────── rapikan (reversibel) ───────────────────────────
def _modify(mb: str, message_id: str, tambah=None, hapus=None) -> None:
    _svc(mb).users().messages().modify(
        userId="me", id=message_id,
        body={"addLabelIds": tambah or [], "removeLabelIds": hapus or []}).execute()


def arsipkan(mailbox: str, message_id: str) -> str:
    mb = _mailbox_sah(mailbox)
    _modify(mb, message_id, hapus=["INBOX"])
    return f"🗂️ Pesan [{message_id}] diarsipkan di {mb} (keluar dari Inbox; tetap ada & bisa dicari)."


def tandai_dibaca(mailbox: str, message_id: str, dibaca: bool = True) -> str:
    mb = _mailbox_sah(mailbox)
    if dibaca:
        _modify(mb, message_id, hapus=["UNREAD"])
        return f"✅ Pesan [{message_id}] ditandai DIBACA di {mb}."
    _modify(mb, message_id, tambah=["UNREAD"])
    return f"🔵 Pesan [{message_id}] ditandai BELUM DIBACA di {mb}."


def _label_id(svc, nama: str) -> str:
    for l in svc.users().labels().list(userId="me").execute().get("labels", []):
        if l.get("name", "").lower() == nama.lower():
            return l["id"]
    nl = svc.users().labels().create(userId="me", body={"name": nama}).execute()
    return nl["id"]


def beri_label(mailbox: str, message_id: str, label: str) -> str:
    mb = _mailbox_sah(mailbox)
    svc = _svc(mb)
    lid = _label_id(svc, label)
    svc.users().messages().modify(
        userId="me", id=message_id, body={"addLabelIds": [lid]}).execute()
    return f"🏷️ Label '{label}' ditempel ke pesan [{message_id}] di {mb}."


# ─────────────────────────── notifikasi proaktif ───────────────────────────
_LABEL_NOTIF = "AI-Notif"  # penanda "sudah dikabari ke Telegram" (anti-dobel, tahan restart)


def cek_email_baru(mailbox: str, cap: int = 12, lookback: str = "1d") -> tuple[list[dict], str]:
    """Email INBOX yang BELUM pernah dinotif (tak berlabel AI-Notif) dalam `lookback`.
    Kembalikan (daftar {id,from,subject,when} terbaru dulu, label_id AI-Notif)."""
    mb = _mailbox_sah(mailbox)
    svc = _svc(mb)
    lid = _label_id(svc, _LABEL_NOTIF)  # pastikan label ada
    q = f"in:inbox -label:{_LABEL_NOTIF} newer_than:{lookback}"
    res = svc.users().messages().list(userId="me", q=q, maxResults=cap).execute()
    out = []
    for m in res.get("messages", []):
        d = svc.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject", "Date", "To"]).execute()
        p = d.get("payload", {})
        out.append({
            "id": m["id"],
            "from": parseaddr(_hdr(p, "From"))[1] or _hdr(p, "From"),
            "subject": _hdr(p, "Subject") or "(tanpa subjek)",
            "when": _hdr(p, "Date"),
            "to": _hdr(p, "To"),
        })
    return out, lid


def tandai_ternotif(mailbox: str, ids: list[str], label_id: str | None = None) -> None:
    """Tempel label AI-Notif ke pesan yang sudah dikabari → tak dinotif lagi."""
    svc = _svc(_mailbox_sah(mailbox))
    if label_id is None:
        label_id = _label_id(svc, _LABEL_NOTIF)
    for mid in ids:
        svc.users().messages().modify(
            userId="me", id=mid, body={"addLabelIds": [label_id]}).execute()


# ── pemindai TAGIHAN (Fase 2b): cari email kandidat billing/pengingat ──
_LABEL_TAGIHAN = "AI-Tagihan-Dicek"
_Q_TAGIHAN = ('in:inbox -label:{lbl} newer_than:10d '
              '(invoice OR tagihan OR faktur OR billing OR "jatuh tempo" OR '
              'pembayaran OR "due date" OR "jumlah tagihan" OR reminder)')


def cari_tagihan_kandidat(mailbox: str, cap: int = 8) -> tuple[list[dict], str]:
    """Email INBOX kandidat tagihan (belum dicek) → ([{id,from,subject,date,body}], label_id)."""
    mb = _mailbox_sah(mailbox)
    svc = _svc(mb)
    lid = _label_id(svc, _LABEL_TAGIHAN)
    res = svc.users().messages().list(
        userId="me", q=_Q_TAGIHAN.format(lbl=_LABEL_TAGIHAN), maxResults=cap).execute()
    out = []
    for m in res.get("messages", []):
        d = svc.users().messages().get(userId="me", id=m["id"], format="full").execute()
        p = d.get("payload", {})
        out.append({
            "id": m["id"],
            "from": parseaddr(_hdr(p, "From"))[1] or _hdr(p, "From"),
            "subject": _hdr(p, "Subject") or "",
            "date": _hdr(p, "Date"),
            "body": (_teks_body(p) or d.get("snippet", ""))[:2500],
        })
    return out, lid


def tandai_tagihan_dicek(mailbox: str, ids: list[str], label_id: str | None = None) -> None:
    """Tandai email sudah dipindai tagihan → tak diproses ulang."""
    svc = _svc(_mailbox_sah(mailbox))
    if label_id is None:
        label_id = _label_id(svc, _LABEL_TAGIHAN)
    for mid in ids:
        svc.users().messages().modify(
            userId="me", id=mid, body={"addLabelIds": [label_id]}).execute()


# ── AUTO-RAPI: pilah email rutin (arsip otomatis) / ragu (tanya) / penting (biar) ──
_LABEL_RAPI_CEK = "AI-Rapi-Cek"   # sudah dipilah (jangan ulang)
_LABEL_AUTORAPI = "Auto-Rapi"     # diarsipkan otomatis oleh agen


def cari_rapi_kandidat(mailbox: str, cap: int = 12) -> tuple[list[dict], str]:
    """Email INBOX yang BELUM dipilah → ([{id,from,subject,snippet}], label_id AI-Rapi-Cek)."""
    mb = _mailbox_sah(mailbox)
    svc = _svc(mb)
    lid = _label_id(svc, _LABEL_RAPI_CEK)
    res = svc.users().messages().list(
        userId="me", q=f"in:inbox -label:{_LABEL_RAPI_CEK} newer_than:7d",
        maxResults=cap).execute()
    out = []
    for m in res.get("messages", []):
        d = svc.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject"]).execute()
        p = d.get("payload", {})
        out.append({
            "id": m["id"],
            "from": parseaddr(_hdr(p, "From"))[1] or _hdr(p, "From"),
            "subject": _hdr(p, "Subject") or "",
            "snippet": (d.get("snippet", "") or "")[:400],
        })
    return out, lid


def tandai_rapi_cek(mailbox: str, ids: list[str], label_id: str | None = None) -> None:
    """Tandai email sudah dipilah auto-rapi → tak diproses ulang."""
    svc = _svc(_mailbox_sah(mailbox))
    if label_id is None:
        label_id = _label_id(svc, _LABEL_RAPI_CEK)
    for mid in ids:
        svc.users().messages().modify(
            userId="me", id=mid, body={"addLabelIds": [label_id]}).execute()


def arsip_rutin(mailbox: str, message_id: str) -> None:
    """Arsipkan email rutin: keluar Inbox + label Auto-Rapi + AI-Notif (agar tak
    dinotifikasikan lagi). Reversibel (tetap ada & bisa dicari)."""
    mb = _mailbox_sah(mailbox)
    svc = _svc(mb)
    add = [_label_id(svc, _LABEL_AUTORAPI), _label_id(svc, _LABEL_NOTIF)]
    svc.users().messages().modify(
        userId="me", id=message_id,
        body={"addLabelIds": add, "removeLabelIds": ["INBOX"]}).execute()


def _arsip_terbaru(mailbox: str, n: int = 10) -> list[dict]:
    mb = _mailbox_sah(mailbox)
    svc = _svc(mb)
    res = svc.users().messages().list(
        userId="me", q=f"label:{_LABEL_AUTORAPI} newer_than:3d", maxResults=n).execute()
    out = []
    for m in res.get("messages", []):
        d = svc.users().messages().get(
            userId="me", id=m["id"], format="metadata",
            metadataHeaders=["From", "Subject"]).execute()
        p = d.get("payload", {})
        out.append({"id": m["id"],
                    "from": parseaddr(_hdr(p, "From"))[1] or _hdr(p, "From"),
                    "subject": _hdr(p, "Subject") or ""})
    return out


def batalkan_arsip(mailbox: str, n: int = 5) -> str:
    """Kembalikan n email yang baru diarsip OTOMATIS (Auto-Rapi) ke Inbox."""
    mb = _mailbox_sah(mailbox)
    svc = _svc(mb)
    lid = _label_id(svc, _LABEL_AUTORAPI)
    items = _arsip_terbaru(mb, n)
    if not items:
        return f"Tak ada email yang baru diarsip otomatis di {mb} (3 hari terakhir)."
    for e in items:
        svc.users().messages().modify(
            userId="me", id=e["id"],
            body={"addLabelIds": ["INBOX"], "removeLabelIds": [lid]}).execute()
    baris = [f"• {e['from']} — {e['subject']}" for e in items]
    return f"↩️ {len(items)} email dikembalikan ke inbox {mb}:\n" + "\n".join(baris)


# ─────────────────────────── KIRIM (dipanggil GERBANG saja) ───────────────────────────
def kirim(mailbox: str, ke: str, subjek: str, isi: str, balas_ke_id: str = "") -> str:
    """Kirim email. HANYA dipanggil oleh persetujuan._lakukan setelah pemilik
    menekan tombol ✅ — jangan dipanggil langsung oleh agen."""
    mb = _mailbox_sah(mailbox)
    svc = _svc(mb)
    refs, thread_id = None, None
    if balas_ke_id:
        refs, thread_id, subj0, frm0 = _refs_balasan(svc, balas_ke_id)
        ke = ke or frm0
        subjek = subjek or subj0
    body = _mime(mb, ke, subjek, isi, refs)
    if thread_id:
        body["threadId"] = thread_id
    r = svc.users().messages().send(userId="me", body=body).execute()
    return f"📧 Email terkirim dari {mb} ke {ke} — subjek '{subjek}' (id {r.get('id')})."


# ─────────────────────────── dispatch tool baca/rapikan ───────────────────────────
def jalankan(nama_tool: str, args: dict, role: str = "staff") -> str:
    if not terkonfigurasi():
        return "Gmail belum terkonfigurasi (GMAIL_SA_JSON / GMAIL_MAILBOXES belum ada)."
    if (role or "").strip().lower() != "admin":
        return "Pengelolaan email (finance@/admin@/wahidnurhani@) khusus admin."
    a = args or {}
    mb = a.get("mailbox", "")
    n = int(a.get("maks") or a.get("n") or 12)
    pid = a.get("uid", "") or a.get("id", "") or a.get("message_id", "")
    try:
        if nama_tool == "baca_email":
            return daftar(mb, kueri=a.get("kueri", ""), n=n)
        if nama_tool == "cari_email":
            return cari(mb, kueri=a.get("kata", "") or a.get("kueri", ""), n=n)
        if nama_tool == "baca_email_isi":
            return baca_pesan(mb, pid)
        if nama_tool == "draft_email":
            return buat_draft(mb, ke=a.get("ke", ""), subjek=a.get("subjek", ""),
                              isi=a.get("isi", ""),
                              balas_ke_id=a.get("balas_ke_id", "") or a.get("uid", ""))
        if nama_tool == "arsip_email":
            return arsipkan(mb, pid)
        if nama_tool == "tandai_dibaca_email":
            return tandai_dibaca(mb, pid, dibaca=bool(a.get("dibaca", True)))
        if nama_tool == "label_email":
            return beri_label(mb, pid, a.get("label", ""))
        if nama_tool == "batalkan_arsip_email":
            return batalkan_arsip(mb, int(a.get("n", 5) or 5))
    except ValueError as e:  # mailbox tak sah, dst.
        return str(e)
    except Exception:  # noqa: BLE001
        log.warning("Gmail error pada %s", nama_tool, exc_info=True)
        return "Gagal mengakses Gmail (izin/jaringan). Cek Domain-wide Delegation & scope."
    return f"(tool '{nama_tool}' tak dikenal)"


async def usul_kirim(args: dict, role: str = "staff") -> str:
    """Usulkan KIRIM email → gerbang tombol pemilik (tak langsung terkirim)."""
    from app.kantor import persetujuan as pst
    if not terkonfigurasi():
        return "Gmail belum terkonfigurasi (GMAIL_SA_JSON / GMAIL_MAILBOXES belum ada)."
    if (role or "").strip().lower() != "admin":
        return "Mengirim email atas nama perusahaan khusus admin."
    a = args or {}
    try:
        mb = _mailbox_sah(a.get("mailbox", ""))
    except ValueError as e:
        return str(e)
    ke, subjek, isi = a.get("ke", ""), a.get("subjek", ""), a.get("isi", "")
    balas = a.get("balas_ke_id", "") or a.get("uid", "")
    if not (ke.strip() and subjek.strip() and isi.strip()) and not balas:
        return "Penerima (ke), subjek, dan isi wajib diisi (atau sebut balas_ke_id)."
    ring = f"Kirim email DARI *{mb}* ke *{ke or '(pengirim asli)'}* — subjek: *{subjek}*"
    aid = await pst.buat_pending(
        jenis="email_kirim", ringkasan=ring, diminta_oleh="bot-kantor",
        payload={"mailbox": mb, "ke": ke, "subjek": subjek, "isi": isi,
                 "balas_ke_id": balas})
    return (f"⏳ Diajukan ke pemilik untuk PERSETUJUAN (#{aid}) — BELUM dikirim.\n"
            f"• {ring}\nSampaikan: email MENUNGGU tombol ✅/❌ pemilik; baru terkirim "
            "setelah Setujui. Jangan mengaku sudah terkirim.")
