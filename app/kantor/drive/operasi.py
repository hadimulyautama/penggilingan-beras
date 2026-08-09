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


def daftar_transit() -> str:
    c = _client()
    if c is None:
        return DRIVE_OFF
    for f in c.anak():
        if f.is_folder and mapper.kode_kategori(f.nama) == tx.TRANSIT:
            isi = c.anak(f.id)
            return f"📥 {f.nama} — {len(isi)} item:\n{_fmt_isi(isi)}"
    return "Folder _TRANSIT tidak ditemukan di root Shared Drive."


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


_DISPATCH = {
    "daftar_transit": lambda a: daftar_transit(),
    "daftar_folder": lambda a: daftar_folder(a.get("kategori", "")),
    "cari_file": lambda a: cari_file(a.get("kata", "")),
    "buka_folder": lambda a: buka_folder(a.get("path", "")),
    "baca_dokumen": lambda a: baca_dokumen(a.get("nama", "")),
    "audit_draft_nyasar": lambda a: audit_draft_nyasar(),
}

NAMA_TOOL = tuple(_DISPATCH)


def jalankan(nama_tool: str, args: dict) -> str:
    """Dispatch tool BACA Drive (sinkron). Kembalikan teks hasil."""
    fn = _DISPATCH.get(nama_tool)
    return fn(args or {}) if fn else f"(tool '{nama_tool}' tidak dikenal)"
