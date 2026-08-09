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

NAMA_TOOL = ("pindah_item", "rename_item", "hapus_item", "buat_folder", "buat_dokumen")

_MAKS_LEVEL_FOLDER = 4


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
    return f"(aksi '{nama_tool}' tidak dikenal)"
