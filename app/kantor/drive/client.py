"""Penghubung Google Drive (OAuth refresh token) — CRUD berpagar untuk Shared Drive.

Autentikasi via refresh token di brankas server (env), BUKAN file kunci
(diblok org policy). Semua operasi memakai parameter Shared Drive
(supportsAllDrives / includeItemsFromAllDrives / corpora=drive+driveId).

PENGAMAN (guardrail):
  - "hapus" = pindah ke folder `99 Arsip Lama` (karantina), BUKAN hapus permanen.
  - ruang gerak dibatasi Shared Drive `GDRIVE_ROOT_FOLDER_ID`.
  - mode dry_run: hanya mencatat rencana, tidak mengubah apa pun.

Env: GDRIVE_OAUTH_CLIENT_ID, GDRIVE_OAUTH_CLIENT_SECRET,
     GDRIVE_OAUTH_REFRESH_TOKEN, GDRIVE_ROOT_FOLDER_ID.
"""
from __future__ import annotations

import io
import logging
import os
from dataclasses import dataclass

log = logging.getLogger("kantor.drive")

# Ekspor Google-native → teks. docx/pdf diunduh & diparse.
_EXPORT = {
    "application/vnd.google-apps.document": "text/plain",
    "application/vnd.google-apps.spreadsheet": "text/csv",
    "application/vnd.google-apps.presentation": "text/plain",
}
_DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
_PDF = "application/pdf"


def _teks_docx(raw: bytes) -> str:
    from docx import Document
    doc = Document(io.BytesIO(raw))
    return "\n".join(p.text for p in doc.paragraphs if p.text.strip())


def _teks_pdf(raw: bytes) -> str:
    from pypdf import PdfReader
    r = PdfReader(io.BytesIO(raw))
    return "\n".join((pg.extract_text() or "") for pg in r.pages[:3])

_TOKEN_URI = "https://oauth2.googleapis.com/token"
_SCOPES = ["https://www.googleapis.com/auth/drive"]
_KARANTINA = "99 - Arsip Lama"  # nama folder kategori tujuan "hapus" (persis di Drive)

# Parameter Shared Drive untuk operasi FILE (get/create/update). CATATAN:
# includeItemsFromAllDrives hanya valid untuk files().list — JANGAN dipakai di sini.
_SHARED = dict(supportsAllDrives=True)


def terkonfigurasi() -> bool:
    """True bila semua env kredensial + root folder tersedia."""
    return all(
        os.getenv(k)
        for k in (
            "GDRIVE_OAUTH_CLIENT_ID",
            "GDRIVE_OAUTH_CLIENT_SECRET",
            "GDRIVE_OAUTH_REFRESH_TOKEN",
            "GDRIVE_ROOT_FOLDER_ID",
        )
    )


@dataclass
class FileDrive:
    id: str
    nama: str
    mime: str
    parents: tuple[str, ...] = ()
    md5: str | None = None       # checksum isi (hanya file biner, bukan Google-native)
    size: int | None = None

    @property
    def is_folder(self) -> bool:
        return self.mime == "application/vnd.google-apps.folder"


class DriveTidakDikonfigurasi(RuntimeError):
    pass


class DriveClient:
    """Klien Drive berpagar. Lazy-connect: kredensial dibaca saat pertama dipakai."""

    def __init__(self, *, dry_run: bool = False) -> None:
        self.dry_run = dry_run
        self.root_id = os.getenv("GDRIVE_ROOT_FOLDER_ID", "")
        self._svc = None
        self._karantina_id: str | None = None

    # ─────────────────────────── koneksi ───────────────────────────
    def _service(self):
        if self._svc is not None:
            return self._svc
        if not terkonfigurasi():
            raise DriveTidakDikonfigurasi(
                "Env GDRIVE_OAUTH_* / GDRIVE_ROOT_FOLDER_ID belum lengkap."
            )
        from google.oauth2.credentials import Credentials
        from googleapiclient.discovery import build

        creds = Credentials(
            token=None,
            refresh_token=os.environ["GDRIVE_OAUTH_REFRESH_TOKEN"],
            token_uri=_TOKEN_URI,
            client_id=os.environ["GDRIVE_OAUTH_CLIENT_ID"],
            client_secret=os.environ["GDRIVE_OAUTH_CLIENT_SECRET"],
            scopes=_SCOPES,
        )
        self._svc = build("drive", "v3", credentials=creds, cache_discovery=False)
        return self._svc

    def _q(self, **params):
        """Query files().list dgn parameter Shared Drive terpasang.

        list() menerima includeItemsFromAllDrives (tak seperti update/create/get).
        """
        return self._service().files().list(
            corpora="drive", driveId=self.root_id,
            supportsAllDrives=True, includeItemsFromAllDrives=True, **params
        ).execute()

    # ─────────────────────────── baca ───────────────────────────
    def anak(self, folder_id: str | None = None) -> list[FileDrive]:
        """Daftar isi langsung sebuah folder (default: root Shared Drive)."""
        parent = folder_id or self.root_id
        out: list[FileDrive] = []
        page = None
        while True:
            res = self._q(
                q=f"'{parent}' in parents and trashed=false",
                fields="nextPageToken, files(id,name,mimeType,parents,md5Checksum,size)",
                pageSize=1000,
                pageToken=page,
            )
            for f in res.get("files", []):
                out.append(FileDrive(
                    id=f["id"], nama=f["name"], mime=f["mimeType"],
                    parents=tuple(f.get("parents", [])),
                    md5=f.get("md5Checksum"),
                    size=int(f["size"]) if f.get("size") else None,
                ))
            page = res.get("nextPageToken")
            if not page:
                break
        return out

    def cari_anak(self, nama: str, parent_id: str | None = None) -> FileDrive | None:
        """Cari 1 anak berdasarkan nama persis dalam sebuah folder."""
        for f in self.anak(parent_id):
            if f.nama == nama:
                return f
        return None

    def cari(self, kata: str, *, maks: int = 50) -> list[FileDrive]:
        """Cari file/folder yg namanya MENGANDUNG `kata` di seluruh Shared Drive."""
        aman = kata.replace("\\", "\\\\").replace("'", "\\'")
        res = self._q(
            q=f"name contains '{aman}' and trashed=false",
            fields="files(id,name,mimeType,parents,md5Checksum,size)",
            pageSize=min(max(maks, 1), 100),
        )
        out: list[FileDrive] = []
        for f in res.get("files", []):
            out.append(FileDrive(
                id=f["id"], nama=f["name"], mime=f["mimeType"],
                parents=tuple(f.get("parents", [])),
                md5=f.get("md5Checksum"),
                size=int(f["size"]) if f.get("size") else None,
            ))
        return out

    def unduh_teks(self, file_id: str, mime: str, *, maks: int = 6000) -> str:
        """Ekstrak teks isi dokumen (utk klasifikasi AI). '' bila tak didukung/gagal.

        Google Docs/Sheets/Slides → export; docx/pdf → unduh & parse. Tipe lain
        (gambar dsb) → '' (klasifikasi jatuh ke nama saja)."""
        svc = self._service()
        try:
            if mime in _EXPORT:
                data = svc.files().export(fileId=file_id, mimeType=_EXPORT[mime]).execute()
                teks = data.decode("utf-8", "ignore") if isinstance(data, (bytes, bytearray)) else str(data)
            elif mime in (_DOCX, _PDF):
                raw = svc.files().get_media(fileId=file_id, supportsAllDrives=True).execute()
                teks = _teks_docx(raw) if mime == _DOCX else _teks_pdf(raw)
            else:
                return ""
        except Exception:
            log.exception("Gagal unduh/ekstrak teks %s", file_id)
            return ""
        return (teks or "")[:maks]

    # ─────────────────────────── tulis (berpagar) ───────────────────────────
    def pastikan_folder(self, nama: str, parent_id: str | None = None) -> str:
        """Kembalikan id folder `nama` di bawah parent; buat bila belum ada."""
        parent = parent_id or self.root_id
        ada = self.cari_anak(nama, parent)
        if ada and ada.is_folder:
            return ada.id
        if self.dry_run:
            log.info("[dry_run] buat folder %r di %s", nama, parent)
            return "(dry_run)"
        meta = {
            "name": nama,
            "mimeType": "application/vnd.google-apps.folder",
            "parents": [parent],
        }
        f = self._service().files().create(
            body=meta, fields="id", **_SHARED
        ).execute()
        return f["id"]

    def ganti_nama(self, file_id: str, nama_baru: str) -> None:
        if self.dry_run:
            log.info("[dry_run] rename %s -> %r", file_id, nama_baru)
            return
        self._service().files().update(
            fileId=file_id, body={"name": nama_baru}, **_SHARED
        ).execute()

    def pindah(self, file_id: str, tujuan_id: str, asal_id: str | None = None) -> None:
        """Pindah file ke folder tujuan (lepas parent lama, pasang parent baru)."""
        if self.dry_run:
            log.info("[dry_run] pindah %s -> %s", file_id, tujuan_id)
            return
        kwargs = dict(fileId=file_id, addParents=tujuan_id, fields="id,parents", **_SHARED)
        if asal_id:
            kwargs["removeParents"] = asal_id
        else:
            cur = self._service().files().get(
                fileId=file_id, fields="parents", **_SHARED
            ).execute()
            if cur.get("parents"):
                kwargs["removeParents"] = ",".join(cur["parents"])
        self._service().files().update(**kwargs).execute()

    def karantina(self, file_id: str, asal_id: str | None = None) -> str:
        """"Hapus" berpagar: pindah file ke `99 Arsip Lama`. TIDAK hapus permanen."""
        if self._karantina_id is None:
            self._karantina_id = self.pastikan_folder(_KARANTINA)
        self.pindah(file_id, self._karantina_id, asal_id)
        return self._karantina_id

    def buat_file(self, nama: str, data: bytes, mime: str, parent_id: str) -> str:
        """Unggah file baru (bytes) ke folder tujuan. Kembalikan id file baru."""
        if self.dry_run:
            log.info("[dry_run] buat file %r di %s (%d byte)", nama, parent_id, len(data))
            return "(dry_run)"
        import io as _io

        from googleapiclient.http import MediaIoBaseUpload

        media = MediaIoBaseUpload(_io.BytesIO(data), mimetype=mime, resumable=False)
        meta = {"name": nama, "parents": [parent_id]}
        f = self._service().files().create(
            body=meta, media_body=media, fields="id", **_SHARED
        ).execute()
        return f["id"]

    # ─────────────────────────── uji koneksi ───────────────────────────
    def selftest(self) -> list[str]:
        """Uji sambungan: kembalikan nama folder tingkat atas Shared Drive.

        Dipakai saat deploy untuk memastikan kredensial & akses benar.
        """
        return [f.nama for f in self.anak() if f.is_folder]
