"""Penelusur (snapshot) struktur Shared Drive → daftar entri berkategori.

Menelusuri pohon folder dari root Shared Drive, mencatat tiap file/folder beserta
KATEGORI tingkat-atas tempatnya berada (00–11 / 99 / _TRANSIT / None=nyasar di root).
Dipakai audit_draft_nyasar (operasi.py) untuk mendeteksi file nyasar.

Batas aman (maks_folder/maks_file) mencegah penelusuran meledak pada Drive besar.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.kantor.drive import taksonomi as tx
from app.kantor.drive.client import DriveClient, FileDrive

# "00 - Legalitas..." -> "00" ; "_TRANSIT (INBOX...)" -> "_TRANSIT" ; "99 - .." -> "99"
_RE_KODE = re.compile(r"^\s*(_TRANSIT|\d{2})\b")


def kode_kategori(nama_folder: str) -> str | None:
    """Ambil kode kategori dari nama folder tingkat-atas, atau None bila tak baku."""
    m = _RE_KODE.match(nama_folder)
    if not m:
        return None
    kode = m.group(1)
    return kode if (kode == tx.TRANSIT or tx.kategori(kode)) else None


@dataclass
class Entri:
    id: str
    nama: str
    is_folder: bool
    parent_id: str
    kategori: str | None       # kode kategori tingkat-atas; None = nyasar (root)
    jalur: str                 # breadcrumb, mis. "03 - SDM/02 Kontrak Kerja"
    md5: str | None = None     # checksum isi (file biner) → deteksi duplikat isi
    size: int | None = None
    mime: str = ""             # utk pilih cara ekstraksi teks (klasifikasi AI)


@dataclass
class Snapshot:
    entri: list[Entri] = field(default_factory=list)
    kena_batas: bool = False

    @property
    def files(self) -> list[Entri]:
        return [e for e in self.entri if not e.is_folder]


def snapshot(
    client: DriveClient, *, maks_folder: int = 400, maks_file: int = 6000
) -> Snapshot:
    """Telusuri pohon Shared Drive → Snapshot semua entri berkategori."""
    snap = Snapshot()
    # antre: (folder_id, kategori_kode, jalur)
    antre: list[tuple[str, str | None, str]] = [(client.root_id, None, "")]
    n_folder = 0

    while antre:
        fid, kat, jalur = antre.pop(0)
        n_folder += 1
        if n_folder > maks_folder:
            snap.kena_batas = True
            break
        for f in client.anak(fid):  # sudah paginasi
            di_root = fid == client.root_id
            # kategori anak: bila di root & folder → kodenya; selain itu warisi induk
            if di_root and f.is_folder:
                anak_kat = kode_kategori(f.nama)
            else:
                anak_kat = kat
            anak_jalur = f"{jalur}/{f.nama}".strip("/")
            snap.entri.append(Entri(
                id=f.id, nama=f.nama, is_folder=f.is_folder,
                parent_id=fid, kategori=anak_kat, jalur=anak_jalur,
                md5=f.md5, size=f.size, mime=f.mime,
            ))
            if f.is_folder:
                antre.append((f.id, anak_kat, anak_jalur))
            elif len(snap.files) > maks_file:
                snap.kena_batas = True
                return snap
    return snap
