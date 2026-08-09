"""Usulan aksi TULIS Drive dari agen bot Kantor — pindah / rename / hapus untuk
FILE **atau** FOLDER, lewat GERBANG persetujuan tombol (app/kantor/persetujuan.py).

Alur: agen memanggil tool → di sini target di-resolve (propose-time, id disimpan
ke payload) → AksiPending(pending) dibuat → pemilik menyetujui via tombol Telegram
→ eksekusi DETERMINISTIK by-id (persetujuan.eksekusi_pending). Agen TIDAK
mengeksekusi Drive langsung; ia hanya mengajukan.

Folder: pindah = isinya ikut, hapus = folder+isinya ke Sampah (operasi Drive
memang berlaku untuk folder). Label FILE/FOLDER ditampilkan di ringkasan agar
pemilik tahu persis yang disetujui.
"""
from __future__ import annotations

import asyncio

from app.kantor import persetujuan as pst
from app.kantor.drive import client as drv
from app.kantor.drive.operasi import DRIVE_OFF, _resolve_folder

NAMA_TOOL = (
    "pindah_item", "rename_item", "hapus_item", "buat_folder", "buat_dokumen",
    "update_sheet", "edit_google_docs", "buat_acara", "ubah_acara", "hapus_acara",
)

_MAKS_LEVEL_FOLDER = 4
_MIME_SHEET = "application/vnd.google-apps.spreadsheet"
_MIME_DOC = "application/vnd.google-apps.document"


def _client():
    return drv.DriveClient() if drv.terkonfigurasi() else None


def _cari_target(c, nama: str):
    """Cari 1 file/folder bernama `nama` (exact diprioritaskan).

    → (item | None, err | None). Bila ambigu/nihil, err menjelaskan supaya agen
    minta nama persis ke pengguna.
    """
    semua = c.cari(nama, maks=25)
    exact = [x for x in semua if x.nama == nama]
    kand = exact or semua
    if not kand:
        return None, f"Tidak ada file/folder bernama '{nama}'."
    if len(kand) > 1:
        daftar = "\n".join(f"• {'📁' if x.is_folder else '📄'} {x.nama}" for x in kand[:10])
        return None, f"Ada {len(kand)} item cocok '{nama}' — minta pengguna sebut nama PERSIS:\n{daftar}"
    return kand[0], None


def _diajukan(aid: int, ring: str) -> str:
    return (
        f"⏳ Diajukan ke pemilik untuk PERSETUJUAN (#{aid}) — BELUM dijalankan.\n"
        f"• {ring}\n"
        "Sampaikan ke pengguna: aksi menunggu persetujuan pemilik (tombol ✅/❌ di "
        "Telegram); baru berjalan setelah pemilik menekan Setujui. Jangan mengaku sudah selesai."
    )


# ─────────────────────── resolusi (sinkron, I/O Drive) ───────────────────────
def _resolve_pindah(nama: str, tujuan: str):
    c = _client()
    if c is None:
        return None, None, DRIVE_OFF
    f, err = _cari_target(c, nama)
    if err:
        return None, None, err
    dest, trail, derr = _resolve_folder(c, tujuan)
    if dest is None:
        return None, None, f"Folder tujuan tidak ditemukan. {derr}"
    if f.is_folder and dest.id == f.id:
        return None, None, "Folder tujuan sama dengan folder yang dipindah."
    lbl = "FOLDER" if f.is_folder else "FILE"
    ikut = " (beserta isinya)" if f.is_folder else ""
    ring = f"Pindah {lbl} *{f.nama}*{ikut} → folder *{' / '.join(trail)}*"
    payload = {
        "file_id": f.id, "tujuan_id": dest.id, "nama": f.nama,
        "tujuan_label": " / ".join(trail), "is_folder": f.is_folder,
    }
    return payload, ring, None


def _resolve_rename(nama_lama: str, nama_baru: str):
    c = _client()
    if c is None:
        return None, None, DRIVE_OFF
    f, err = _cari_target(c, nama_lama)
    if err:
        return None, None, err
    if not (nama_baru or "").strip():
        return None, None, "Nama baru kosong."
    lbl = "FOLDER" if f.is_folder else "FILE"
    ring = f"Ubah nama {lbl}: *{f.nama}* → *{nama_baru}*"
    payload = {
        "file_id": f.id, "nama_baru": nama_baru.strip(),
        "nama_lama": f.nama, "is_folder": f.is_folder,
    }
    return payload, ring, None


def _resolve_hapus(nama: str):
    c = _client()
    if c is None:
        return None, None, DRIVE_OFF
    f, err = _cari_target(c, nama)
    if err:
        return None, None, err
    lbl = "FOLDER" if f.is_folder else "FILE"
    ket = ""
    if f.is_folder:
        try:
            ket = f" (berisi {len(c.anak(f.id))} item — semua ikut ke Sampah)"
        except Exception:  # noqa: BLE001
            ket = " (beserta isinya)"
    ring = f"Hapus {lbl} *{f.nama}*{ket} → Sampah (pulih ~30 hari)"
    payload = {"file_id": f.id, "nama": f.nama, "is_folder": f.is_folder}
    return payload, ring, None


# ─────────────────────── usulan (async → gerbang) ───────────────────────
async def _ajukan(resolve, *args, jenis: str) -> str:
    payload, ring, err = await asyncio.to_thread(resolve, *args)
    if err:
        return err
    aid = await pst.buat_pending(
        jenis=jenis, ringkasan=ring, payload=payload, diminta_oleh="bot-kantor")
    return _diajukan(aid, ring)


def _resolve_folder_baru(path: str):
    """Validasi + resolve INDUK folder baru. Aturan: di dalam kategori (00–11/99),
    maks 4 level, induk sudah ada, belum ada folder senama."""
    c = _client()
    if c is None:
        return None, None, DRIVE_OFF
    segs = [s.strip() for s in (path or "").replace("\\", "/").split("/") if s.strip()]
    if len(segs) < 2:
        return None, None, ("Folder baru harus DI DALAM kategori inti (00–11/99) atau "
                            "subfolder-nya — sertakan induknya, mis. '09/Company Profile'.")
    if len(segs) > _MAKS_LEVEL_FOLDER:
        return None, None, f"Terlalu dalam ({len(segs)} level). Maksimal {_MAKS_LEVEL_FOLDER} level."
    nama_baru = segs[-1]
    induk, itrail, ierr = _resolve_folder(c, "/".join(segs[:-1]))
    if induk is None:
        return None, None, f"Folder induk tak ditemukan. {ierr}"
    ada = c.cari_anak(nama_baru, induk.id)
    if ada and ada.is_folder:
        return None, None, f"Folder '{nama_baru}' sudah ada di '{' / '.join(itrail)}'."
    ring = f"Buat folder baru *{nama_baru}* di *{' / '.join(itrail)}*"
    payload = {"parent_id": induk.id, "nama": nama_baru, "path_label": " / ".join(itrail)}
    return payload, ring, None


async def usul_dokumen(judul: str, isi: str, nomor: str = "", nama_file: str = "",
                       tembusan: str = "", tabel_json: str = "") -> str:
    """Usulkan pembuatan .docx berkop → _TRANSIT (DRAFT). Validasi ringan, lalu gerbang."""
    if not (judul or "").strip() or not (isi or "").strip():
        return "Judul dan isi dokumen wajib diisi."
    if (tabel_json or "").strip():
        import json
        try:
            json.loads(tabel_json)
        except Exception as e:  # noqa: BLE001
            return f"tabel_json bukan JSON valid: {e}"
    fn = f"[DRAFT] {(nama_file or judul).strip()}.docx"
    ring = f"Buat dokumen *{judul}* → _TRANSIT sebagai *{fn}* (status DRAFT)"
    payload = {
        "judul": judul, "isi": isi, "nomor": nomor, "nama_file_final": fn,
        "tembusan": tembusan, "tabel_json": tabel_json,
    }
    aid = await pst.buat_pending(
        jenis="drive_dokumen", ringkasan=ring, payload=payload, diminta_oleh="bot-kantor")
    return _diajukan(aid, ring)


def _cari_by_mime(c, nama: str, mime: str, label: str):
    """Cari 1 file Google-native (Sheet/Doc) bernama `nama`. → (item|None, err|None)."""
    kand = [x for x in c.cari(nama, maks=25) if x.mime == mime]
    exact = [x for x in kand if x.nama == nama]
    kand = exact or kand
    if not kand:
        return None, f"{label} bernama '{nama}' tak ditemukan."
    if len(kand) > 1:
        return None, (f"Ada {len(kand)} {label} cocok '{nama}' — minta pengguna sebut "
                      "nama PERSIS:\n" + "\n".join(f"• {x.nama}" for x in kand[:10]))
    return kand[0], None


def _resolve_update_sheet(nama_sheet: str, sel: str, nilai: str):
    c = _client()
    if c is None:
        return None, None, DRIVE_OFF
    f, err = _cari_by_mime(c, nama_sheet, _MIME_SHEET, "Google Sheet")
    if err:
        return None, None, err
    if not (sel or "").strip():
        return None, None, "Sel/rentang (notasi A1) wajib, mis. 'Register!D5'."
    ring = f"Isi sel {sel} di Sheet *{f.nama}* → *{nilai}*"
    payload = {"spreadsheet_id": f.id, "spreadsheet_nama": f.nama, "sel": sel, "nilai": nilai}
    return payload, ring, None


def _resolve_edit_docs(nama_doc: str, cari: str, ganti: str):
    c = _client()
    if c is None:
        return None, None, DRIVE_OFF
    f, err = _cari_by_mime(c, nama_doc, _MIME_DOC, "Google Doc")
    if err:
        return None, None, err
    if not (cari or "").strip():
        return None, None, "Teks yang dicari wajib diisi."
    ring = f"Ganti teks di Doc *{f.nama}*: '{cari}' → '{ganti}'"
    payload = {"document_id": f.id, "doc_nama": f.nama, "cari": cari, "ganti": ganti}
    return payload, ring, None


async def usul_buat_acara(judul: str, mulai: str, selesai: str,
                          deskripsi: str = "", lokasi: str = "",
                          kalender: str = "primary") -> str:
    """Usulkan pembuatan acara Calendar. mulai/selesai = 'YYYY-MM-DDTHH:MM:SS'."""
    if not (judul or "").strip() or not (mulai or "").strip() or not (selesai or "").strip():
        return "Judul, waktu mulai, dan waktu selesai wajib diisi."
    lok = f"  @ {lokasi}" if lokasi else ""
    kal = "" if (kalender or "primary") == "primary" else f"  [kalender: {kalender}]"
    ring = f"Buat acara *{judul}* — {mulai} s/d {selesai}{lok}{kal}"
    payload = {"judul": judul, "mulai": mulai, "selesai": selesai,
               "deskripsi": deskripsi, "lokasi": lokasi, "cal_id": kalender or "primary"}
    aid = await pst.buat_pending(
        jenis="kalender_buat", ringkasan=ring, payload=payload, diminta_oleh="bot-kantor")
    return _diajukan(aid, ring)


async def usul_ubah_acara(event_id: str, judul: str = "", mulai: str = "",
                          selesai: str = "", deskripsi: str = "", lokasi: str = "",
                          kalender: str = "primary") -> str:
    """Usulkan perubahan acara Calendar (field kosong = tak diubah)."""
    if not (event_id or "").strip():
        return "event_id wajib — ambil dari lihat_agenda dulu."
    ubah = [x for x in (
        f"judul→'{judul}'" if judul else "",
        f"mulai→{mulai}" if mulai else "",
        f"selesai→{selesai}" if selesai else "",
        f"lokasi→'{lokasi}'" if lokasi else "",
        "deskripsi diperbarui" if deskripsi else "",
    ) if x]
    if not ubah:
        return "Tak ada yang diubah — sebutkan minimal satu field (judul/mulai/selesai/lokasi/deskripsi)."
    ring = f"Ubah acara (id {event_id}): " + ", ".join(ubah)
    payload = {"event_id": event_id, "judul": judul, "mulai": mulai, "selesai": selesai,
               "deskripsi": deskripsi, "lokasi": lokasi, "cal_id": kalender or "primary"}
    aid = await pst.buat_pending(
        jenis="kalender_ubah", ringkasan=ring, payload=payload, diminta_oleh="bot-kantor")
    return _diajukan(aid, ring)


async def usul_hapus_acara(event_id: str, ringkasan_acara: str = "",
                           kalender: str = "primary") -> str:
    """Usulkan penghapusan acara Calendar."""
    if not (event_id or "").strip():
        return "event_id wajib — ambil dari lihat_agenda dulu."
    ring = f"Hapus acara *{ringkasan_acara or event_id}* (id {event_id})"
    payload = {"event_id": event_id, "ringkasan_acara": ringkasan_acara,
               "cal_id": kalender or "primary"}
    aid = await pst.buat_pending(
        jenis="kalender_hapus", ringkasan=ring, payload=payload, diminta_oleh="bot-kantor")
    return _diajukan(aid, ring)


async def jalankan_usul(nama_tool: str, args: dict) -> str:
    """Dispatch tool TULIS → buat usulan yang menunggu tombol persetujuan pemilik."""
    a = args or {}
    if nama_tool == "pindah_item":
        return await _ajukan(_resolve_pindah, a.get("nama", ""), a.get("tujuan", ""), jenis="drive_move")
    if nama_tool == "rename_item":
        return await _ajukan(_resolve_rename, a.get("nama_lama", ""), a.get("nama_baru", ""), jenis="drive_rename")
    if nama_tool == "hapus_item":
        return await _ajukan(_resolve_hapus, a.get("nama", ""), jenis="drive_delete")
    if nama_tool == "buat_folder":
        return await _ajukan(_resolve_folder_baru, a.get("path", ""), jenis="drive_mkdir")
    if nama_tool == "buat_dokumen":
        return await usul_dokumen(
            a.get("judul", ""), a.get("isi", ""), a.get("nomor", ""),
            a.get("nama_file", ""), a.get("tembusan", ""), a.get("tabel_json", ""))
    if nama_tool == "update_sheet":
        return await _ajukan(_resolve_update_sheet, a.get("nama_sheet", ""),
                             a.get("sel", ""), a.get("nilai", ""), jenis="sheet_update")
    if nama_tool == "edit_google_docs":
        return await _ajukan(_resolve_edit_docs, a.get("nama_doc", ""),
                             a.get("cari", ""), a.get("ganti", ""), jenis="docs_ganti")
    if nama_tool == "buat_acara":
        return await usul_buat_acara(
            a.get("judul", ""), a.get("mulai", ""), a.get("selesai", ""),
            a.get("deskripsi", ""), a.get("lokasi", ""), a.get("kalender", "primary"))
    if nama_tool == "ubah_acara":
        return await usul_ubah_acara(
            a.get("event_id", ""), a.get("judul", ""), a.get("mulai", ""),
            a.get("selesai", ""), a.get("deskripsi", ""), a.get("lokasi", ""),
            a.get("kalender", "primary"))
    if nama_tool == "hapus_acara":
        return await usul_hapus_acara(
            a.get("event_id", ""), a.get("ringkasan_acara", ""), a.get("kalender", "primary"))
    return f"(aksi '{nama_tool}' tidak dikenal)"
