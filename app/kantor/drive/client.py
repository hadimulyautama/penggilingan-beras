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
# drive = kelola file; spreadsheets = baca/edit Sheets; documents = baca/edit Docs.
# Aman ditambah lebih dulu: operasi Drive tetap jalan dgn token lama (scope drive);
# Sheets/Docs baru berfungsi setelah refresh token di-issue ulang dgn scope ini.
_SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/documents",
    "https://www.googleapis.com/auth/calendar",
]
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
        self._svc_sheets = None
        self._svc_docs = None
        self._svc_cal = None
        self._karantina_id: str | None = None

    # ─────────────────────────── koneksi ───────────────────────────
    def _kredensial(self):
        if not terkonfigurasi():
            raise DriveTidakDikonfigurasi(
                "Env GDRIVE_OAUTH_* / GDRIVE_ROOT_FOLDER_ID belum lengkap."
            )
        from google.oauth2.credentials import Credentials
        return Credentials(
            token=None,
            refresh_token=os.environ["GDRIVE_OAUTH_REFRESH_TOKEN"],
            token_uri=_TOKEN_URI,
            client_id=os.environ["GDRIVE_OAUTH_CLIENT_ID"],
            client_secret=os.environ["GDRIVE_OAUTH_CLIENT_SECRET"],
            scopes=_SCOPES,
        )

    def _service(self):
        if self._svc is None:
            from googleapiclient.discovery import build
            self._svc = build("drive", "v3", credentials=self._kredensial(),
                              cache_discovery=False)
        return self._svc

    def _sheets(self):
        if self._svc_sheets is None:
            from googleapiclient.discovery import build
            self._svc_sheets = build("sheets", "v4", credentials=self._kredensial(),
                                     cache_discovery=False)
        return self._svc_sheets

    def _docs(self):
        if self._svc_docs is None:
            from googleapiclient.discovery import build
            self._svc_docs = build("docs", "v1", credentials=self._kredensial(),
                                   cache_discovery=False)
        return self._svc_docs

    # ─────────────────────────── Google Sheets ───────────────────────────
    def sheet_baca(self, spreadsheet_id: str, rentang: str) -> list[list[str]]:
        """Baca nilai sebuah rentang (mis. 'Sheet1!A1:D20'). → list baris."""
        r = self._sheets().spreadsheets().values().get(
            spreadsheetId=spreadsheet_id, range=rentang).execute()
        return r.get("values", [])

    def sheet_tulis(self, spreadsheet_id: str, rentang: str,
                    nilai: list[list]) -> None:
        """Tulis `nilai` (list baris) ke `rentang`. USER_ENTERED (hormati format)."""
        if self.dry_run:
            log.info("[dry_run] tulis sheet %s %s = %r", spreadsheet_id, rentang, nilai)
            return
        self._sheets().spreadsheets().values().update(
            spreadsheetId=spreadsheet_id, range=rentang,
            valueInputOption="USER_ENTERED", body={"values": nilai},
        ).execute()

    # ─────────────────────────── Google Docs ───────────────────────────
    def docs_teks(self, document_id: str) -> str:
        """Ambil teks polos isi Google Doc."""
        doc = self._docs().documents().get(documentId=document_id).execute()
        keping: list[str] = []
        for el in doc.get("body", {}).get("content", []):
            for pe in el.get("paragraph", {}).get("elements", []):
                t = pe.get("textRun", {}).get("content")
                if t:
                    keping.append(t)
        return "".join(keping)

    def docs_ganti_teks(self, document_id: str, cari: str, ganti: str) -> int:
        """Ganti SEMUA kemunculan `cari` → `ganti` di Google Doc. → jumlah diganti."""
        if self.dry_run:
            log.info("[dry_run] docs ganti %s: %r→%r", document_id, cari, ganti)
            return 0
        res = self._docs().documents().batchUpdate(
            documentId=document_id,
            body={"requests": [{"replaceAllText": {
                "containsText": {"text": cari, "matchCase": True},
                "replaceText": ganti,
            }}]},
        ).execute()
        rep = res.get("replies", [{}])
        return rep[0].get("replaceAllText", {}).get("occurrencesChanged", 0) if rep else 0

    # ─────────────────────────── Google Calendar ───────────────────────────
    def _calendar(self):
        if self._svc_cal is None:
            from googleapiclient.discovery import build
            self._svc_cal = build("calendar", "v3", credentials=self._kredensial(),
                                  cache_discovery=False)
        return self._svc_cal

    def kalender_daftar(self) -> list[dict]:
        """Daftar kalender yang bisa diakses (milik sendiri + yang dibagikan).
        → list {id, nama, akses}. `id` dipakai sbg target operasi ('primary' = utama)."""
        r = self._calendar().calendarList().list().execute()
        out: list[dict] = []
        for c in r.get("items", []):
            out.append({
                "id": c.get("id", ""),
                "nama": c.get("summaryOverride") or c.get("summary", ""),
                "akses": c.get("accessRole", ""),  # owner/writer/reader
                "utama": bool(c.get("primary")),
            })
        return out

    def kalender_acara(self, time_min: str, time_max: str, *,
                       cal_id: str = "primary", maks: int = 20) -> list[dict]:
        """Daftar acara sebuah kalender di rentang waktu (RFC3339). → list
        {ringkasan, mulai, selesai, lokasi, id}. `cal_id` = 'primary' atau email kalender."""
        r = self._calendar().events().list(
            calendarId=cal_id, timeMin=time_min, timeMax=time_max,
            singleEvents=True, orderBy="startTime", maxResults=maks,
        ).execute()
        out: list[dict] = []
        for e in r.get("items", []):
            s, en = e.get("start", {}), e.get("end", {})
            out.append({
                "ringkasan": e.get("summary", "(tanpa judul)"),
                "mulai": s.get("dateTime") or s.get("date", ""),
                "selesai": en.get("dateTime") or en.get("date", ""),
                "lokasi": e.get("location", ""),
                "id": e.get("id", ""),
            })
        return out

    def kalender_buat(self, ringkasan: str, mulai: str, selesai: str, *,
                      deskripsi: str = "", lokasi: str = "", cal_id: str = "primary",
                      tz: str = "Asia/Jakarta") -> str:
        """Buat acara di kalender `cal_id`. mulai/selesai = 'YYYY-MM-DDTHH:MM:SS'
        (waktu lokal `tz`). → link acara (htmlLink)."""
        if self.dry_run:
            log.info("[dry_run] buat acara %r %s→%s @%s", ringkasan, mulai, selesai, cal_id)
            return "(dry_run)"
        body = {
            "summary": ringkasan,
            "start": {"dateTime": mulai, "timeZone": tz},
            "end": {"dateTime": selesai, "timeZone": tz},
        }
        if deskripsi:
            body["description"] = deskripsi
        if lokasi:
            body["location"] = lokasi
        ev = self._calendar().events().insert(calendarId=cal_id, body=body).execute()
        return ev.get("htmlLink", "(acara dibuat)")

    def kalender_ubah(self, event_id: str, *, cal_id: str = "primary",
                      ringkasan: str = "", mulai: str = "", selesai: str = "",
                      deskripsi: str = "", lokasi: str = "",
                      tz: str = "Asia/Jakarta") -> str:
        """Ubah acara (hanya field non-kosong yang diubah). → link acara."""
        if self.dry_run:
            log.info("[dry_run] ubah acara %s @%s", event_id, cal_id)
            return "(dry_run)"
        patch: dict = {}
        if ringkasan:
            patch["summary"] = ringkasan
        if mulai:
            patch["start"] = {"dateTime": mulai, "timeZone": tz}
        if selesai:
            patch["end"] = {"dateTime": selesai, "timeZone": tz}
        if deskripsi:
            patch["description"] = deskripsi
        if lokasi:
            patch["location"] = lokasi
        ev = self._calendar().events().patch(
            calendarId=cal_id, eventId=event_id, body=patch).execute()
        return ev.get("htmlLink", "(acara diubah)")

    def kalender_hapus(self, event_id: str, *, cal_id: str = "primary") -> None:
        """Hapus acara dari kalender."""
        if self.dry_run:
            log.info("[dry_run] hapus acara %s @%s", event_id, cal_id)
            return
        self._calendar().events().delete(calendarId=cal_id, eventId=event_id).execute()

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

    def buang_ke_sampah(self, file_id: str) -> None:
        """'Hapus' berpagar: pindah file ke Trash Drive (reversible ~30 hari).

        BUKAN hapus permanen. File hilang dari folder tapi masih bisa dipulihkan
        dari Sampah sampai Drive menghapusnya otomatis.
        """
        if self.dry_run:
            log.info("[dry_run] buang ke sampah %s", file_id)
            return
        self._service().files().update(
            fileId=file_id, body={"trashed": True}, **_SHARED
        ).execute()

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
