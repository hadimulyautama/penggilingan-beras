"""Operasi Google Drive tingkat-tinggi untuk agen bot Kantor — BACA (read-only).

Diekstrak dari mcp_server.py supaya bot SENDIRI (@hmu_assisten_bot) punya
kemampuan jelajah/cari/baca Drive yang dulu hanya dimiliki Hermes. Fungsi
SINKRON (I/O jaringan blocking) — pemanggil async membungkus dengan
asyncio.to_thread agar tak memblok event loop.
"""
from __future__ import annotations

from app.kantor.drive import client as drv
from app.kantor.drive import mapper
from app.kantor.drive import taksonomi as tx

DRIVE_OFF = "Google Drive belum terkonfigurasi di server ini (env GDRIVE_OAUTH_* belum ada)."


def _client():
    if not drv.terkonfigurasi():
        return None
    return drv.DriveClient()


def _fmt_isi(items) -> str:
    if not items:
        return "(kosong)"
    baris = []
    for f in sorted(items, key=lambda x: (not x.is_folder, x.nama.lower())):
        if f.is_folder:
            baris.append(f"📁 {f.nama}/")
        else:
            sz = f" · {f.size / 1024:.0f} KB" if f.size else ""
            baris.append(f"📄 {f.nama}{sz}")
    return "\n".join(baris)


def _resolve_folder(c, path: str):
    """Navigasi path folder → (folder | None, trail nama, err | None)."""
    segs = [s.strip() for s in path.replace("\\", "/").split("/") if s.strip()]
    if not segs:
        return None, [], "Path folder kosong."
    cur = next((f for f in c.anak() if f.is_folder and (
        mapper.kode_kategori(f.nama) == segs[0] or segs[0].lower() in f.nama.lower())), None)
    if cur is None:
        return None, [], f"Folder '{segs[0]}' tidak ditemukan di root Shared Drive."
    trail = [cur.nama]
    for seg in segs[1:]:
        subs = [x for x in c.anak(cur.id) if x.is_folder]
        nxt = (next((x for x in subs if x.nama == seg), None)
               or next((x for x in subs if seg.lower() in x.nama.lower()), None))
        if nxt is None:
            ada = ", ".join(x.nama for x in subs) or "(tak ada subfolder)"
            return None, trail, (f"Subfolder '{seg}' tak ada di '{' / '.join(trail)}'. "
                                 f"Tersedia: {ada}")
        cur = nxt
        trail.append(cur.nama)
    return cur, trail, None


def transit_id(c) -> str | None:
    """Id folder _TRANSIT di root Shared Drive (untuk simpan draft baru)."""
    for f in c.anak():
        if f.is_folder and mapper.kode_kategori(f.nama) == tx.TRANSIT:
            return f.id
    return None


def daftar_transit() -> str:
    c = _client()
    if c is None:
        return DRIVE_OFF
    tid = transit_id(c)
    if tid is None:
        return "Folder _TRANSIT tidak ditemukan di root Shared Drive."
    isi = c.anak(tid)
    return f"📥 _TRANSIT — {len(isi)} item:\n{_fmt_isi(isi)}"


def daftar_folder(kategori: str) -> str:
    c = _client()
    if c is None:
        return DRIVE_OFF
    q = (kategori or "").strip().lower()
    for f in c.anak():
        if not f.is_folder:
            continue
        if mapper.kode_kategori(f.nama) == (kategori or "").strip() or (q and q in f.nama.lower()):
            isi = c.anak(f.id)
            return f"🗂️ {f.nama} — {len(isi)} item:\n{_fmt_isi(isi)}"
    return f"Folder kategori '{kategori}' tidak ditemukan di root Shared Drive."


def cari_file(kata: str) -> str:
    c = _client()
    if c is None:
        return DRIVE_OFF
    hasil = c.cari(kata, maks=50)
    if not hasil:
        return f"Tidak ada file yang namanya mengandung '{kata}'."
    return f"🔎 {len(hasil)} hasil untuk '{kata}':\n{_fmt_isi(hasil)}"


def buka_folder(path: str) -> str:
    c = _client()
    if c is None:
        return DRIVE_OFF
    folder, trail, err = _resolve_folder(c, path)
    if err:
        return err
    isi = c.anak(folder.id)
    return f"📂 {' / '.join(trail)} — {len(isi)} item:\n{_fmt_isi(isi)}"


def baca_dokumen(nama: str) -> str:
    c = _client()
    if c is None:
        return DRIVE_OFF
    kand = [x for x in c.cari(nama, maks=25) if not x.is_folder and x.nama == nama]
    if not kand:
        kand = [x for x in c.cari(nama, maks=25) if not x.is_folder]
    if not kand:
        return f"File '{nama}' tidak ditemukan."
    if len(kand) > 1:
        return "Beberapa file cocok — sebut nama persis:\n" + "\n".join(f"• {f.nama}" for f in kand[:10])
    f = kand[0]
    try:
        mime = c._service().files().get(
            fileId=f.id, fields="mimeType", supportsAllDrives=True).execute()["mimeType"]
        teks = c.unduh_teks(f.id, mime, maks=3000)
    except Exception as e:  # noqa: BLE001
        return f"Gagal baca isi: {e}"
    if not teks.strip():
        return f"(Isi '{f.nama}' tak bisa diekstrak — kemungkinan gambar/scan.)"
    return f"📄 {f.nama}:\n{teks}"


def audit_draft_nyasar() -> str:
    """Pindai SELURUH pohon Drive (semua subfolder) → daftar file 'draft' yang
    berada DI LUAR _TRANSIT. Satu panggilan (rekursif) — untuk audit menyeluruh.
    """
    c = _client()
    if c is None:
        return DRIVE_OFF
    snap = mapper.snapshot(c)
    nyasar = [e for e in snap.files
              if "draft" in e.nama.lower() and e.kategori != tx.TRANSIT]
    if not nyasar:
        return ("✅ Tidak ada draft yang nyasar — tak ditemukan file berlabel 'draft' "
                "di luar folder _TRANSIT.")
    nyasar.sort(key=lambda e: e.jalur.lower())
    baris = [f"📄 {e.nama}  —  di: {e.jalur or '(root)'}" for e in nyasar[:100]]
    ket = f"\n(ditampilkan 100 dari {len(nyasar)})" if len(nyasar) > 100 else ""
    return (f"⚠️ {len(nyasar)} draft NYASAR di luar _TRANSIT (seharusnya draft ada di "
            f"_TRANSIT):\n" + "\n".join(baris) + ket)


def daftar_kalender() -> str:
    """Daftar kalender yang bisa dikelola (milik sendiri + yang dibagikan)."""
    c = _client()
    if c is None:
        return DRIVE_OFF
    ks = c.kalender_daftar()
    if not ks:
        return "Tak ada kalender yang bisa diakses."
    baris = []
    for k in ks:
        tag = " (utama)" if k["utama"] else ""
        baris.append(f"• {k['nama']}{tag} — akses: {k['akses']} — id: {k['id']}")
    return (f"🗓️ {len(ks)} kalender bisa dikelola:\n" + "\n".join(baris)
            + "\n(pakai 'id' sebagai target kalender untuk lihat/buat/ubah/hapus acara)")


def lihat_agenda(dari: str, sampai: str = "", kalender: str = "primary") -> str:
    """Daftar acara Google Calendar dari `dari` s/d `sampai` (ISO YYYY-MM-DD) di
    `kalender` ('primary' atau id/email kalender). `sampai` kosong = hari `dari`."""
    import os
    from datetime import date, datetime, time
    from zoneinfo import ZoneInfo

    c = _client()
    if c is None:
        return DRIVE_OFF
    z = ZoneInfo(os.getenv("APP_TIMEZONE", "Asia/Jakarta"))
    try:
        tmin = datetime.combine(date.fromisoformat(dari), time(0, 0), z).isoformat()
        tmax = datetime.combine(date.fromisoformat(sampai or dari), time(23, 59, 59), z).isoformat()
    except ValueError:
        return "Tanggal tak valid — pakai format YYYY-MM-DD."
    acara = c.kalender_acara(tmin, tmax, cal_id=kalender or "primary", maks=30)
    if not acara:
        return f"Tak ada acara antara {dari} dan {sampai or dari}."
    baris = []
    for a in acara:
        lok = f"  @ {a['lokasi']}" if a["lokasi"] else ""
        # id acara disertakan agar agen bisa ubah/hapus acara tsb.
        baris.append(f"• [{a['id']}] {a['mulai']} — {a['ringkasan']}{lok}")
    return f"📅 {len(acara)} acara ({dari} s/d {sampai or dari}):\n" + "\n".join(baris)


_MIME_SHEET = "application/vnd.google-apps.spreadsheet"
_MAKS_BACA_SHEET = 12000  # batas karakter output baca tab (hindari kepotong dini)


def _cari_sheet(c, nama: str):
    """Cari 1 Google Sheet bernama `nama` (exact diprioritaskan). → (item|None, err)."""
    kand = [x for x in c.cari(nama, maks=25) if x.mime == _MIME_SHEET]
    exact = [x for x in kand if x.nama == nama]
    kand = exact or kand
    if not kand:
        return None, f"Google Sheet '{nama}' tak ditemukan."
    if len(kand) > 1:
        return None, ("Beberapa Sheet cocok — sebut nama PERSIS:\n"
                      + "\n".join(f"• {x.nama}" for x in kand[:10]))
    return kand[0], None


def daftar_tab(nama_sheet: str) -> str:
    """Daftar semua TAB (worksheet) dalam sebuah Spreadsheet + ukurannya."""
    c = _client()
    if c is None:
        return DRIVE_OFF
    f, err = _cari_sheet(c, nama_sheet)
    if err:
        return err
    tabs = c.sheet_daftar_tab(f.id)
    if not tabs:
        return f"Sheet '{f.nama}' tak punya tab terbaca."
    baris = [f"• {t['judul']}  ({t['baris']}×{t['kolom']})" for t in tabs]
    return (f"📑 Sheet '{f.nama}' punya {len(tabs)} tab:\n" + "\n".join(baris)
            + "\nBaca isi satu tab dengan baca_sheet(nama_sheet, tab).")


def baca_sheet(nama_sheet: str, tab: str = "", rentang: str = "") -> str:
    """Baca isi sebuah TAB Sheet (bukan cuma tab pertama; tanpa kepotong 3000).
    `tab` kosong = tab pertama. `rentang` opsional (mis. 'A1:E40')."""
    c = _client()
    if c is None:
        return DRIVE_OFF
    f, err = _cari_sheet(c, nama_sheet)
    if err:
        return err
    tabs = c.sheet_daftar_tab(f.id)
    judul_tabs = [t["judul"] for t in tabs]
    if tab:
        cocok = [j for j in judul_tabs if j == tab] or [j for j in judul_tabs if tab.lower() in j.lower()]
        if not cocok:
            return (f"Tab '{tab}' tak ada di '{f.nama}'. Tab tersedia: "
                    + ", ".join(judul_tabs))
        nama_tab = cocok[0]
    else:
        nama_tab = judul_tabs[0] if judul_tabs else ""
    rng = f"'{nama_tab}'!{rentang}" if rentang else f"'{nama_tab}'"
    data = c.sheet_baca(f.id, rng)
    if not data:
        return f"(Tab '{nama_tab}' di '{f.nama}' kosong.)"
    baris = [" | ".join(str(x) for x in r) for r in data]
    teks = "\n".join(baris)
    potong = ""
    if len(teks) > _MAKS_BACA_SHEET:
        teks = teks[:_MAKS_BACA_SHEET]
        potong = (f"\n… (dipotong — tab besar; baca bagian tertentu dengan rentang, "
                  f"mis. baca_sheet('{f.nama}','{nama_tab}','A18:Z40'))")
    return f"📄 {f.nama} › tab '{nama_tab}' ({len(data)} baris):\n{teks}{potong}"


_DISPATCH = {
    "daftar_transit": lambda a: daftar_transit(),
    "daftar_tab_sheet": lambda a: daftar_tab(a.get("nama_sheet", "")),
    "baca_sheet": lambda a: baca_sheet(
        a.get("nama_sheet", ""), a.get("tab", ""), a.get("rentang", "")),
    "daftar_folder": lambda a: daftar_folder(a.get("kategori", "")),
    "cari_file": lambda a: cari_file(a.get("kata", "")),
    "buka_folder": lambda a: buka_folder(a.get("path", "")),
    "baca_dokumen": lambda a: baca_dokumen(a.get("nama", "")),
    "audit_draft_nyasar": lambda a: audit_draft_nyasar(),
    "daftar_kalender": lambda a: daftar_kalender(),
    "lihat_agenda": lambda a: lihat_agenda(
        a.get("dari", ""), a.get("sampai", ""), a.get("kalender", "primary")),
}

NAMA_TOOL = tuple(_DISPATCH)


def jalankan(nama_tool: str, args: dict) -> str:
    """Dispatch tool BACA Drive (sinkron). Kembalikan teks hasil."""
    fn = _DISPATCH.get(nama_tool)
    return fn(args or {}) if fn else f"(tool '{nama_tool}' tidak dikenal)"
