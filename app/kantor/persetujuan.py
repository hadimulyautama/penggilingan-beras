"""Gerbang PERSETUJUAN MANUSIA untuk aksi Drive konsekuensial (pindah/rename/hapus).

Alur:
  1. Agen (via MCP) MENGAJUKAN aksi  → baris AksiPending(status='pending')
  2. Poller kirim tombol ✅/❌ ke pemilik di Telegram → status='menunggu'
  3. Pemilik menekan tombol            → eksekusi payload DETERMINISTIK (tanpa LLM)
  4. Hasil dicatat                     → status 'dieksekusi'/'ditolak', + kantor_audit_log

KUNCI KEAMANAN: agen (Hermes) TIDAK bisa menekan tombol. Hanya pemilik (admin
Telegram) yang mengeksekusi payload. Ini menutup celah 'self-approve' — dulu agen
memegang token dari usul_* lalu memanggil jalankan_* sendiri.

Dipakai lintas service (satu repo): mcp_server (produsen: buat_pending) dan bot
kantor (konsumen: eksekusi_pending/tolak_pending, dipicu tombol).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from app.database import SessionLocal
from app.kantor.models import AksiPending, KantorAuditLog

log = logging.getLogger("kantor.persetujuan")

# ── status daur hidup ──
PENDING = "pending"       # baru dibuat, belum dikirim ke pemilik
MENUNGGU = "menunggu"     # tombol terkirim, menunggu keputusan
DIEKSEKUSI = "dieksekusi"
DITOLAK = "ditolak"
GAGAL = "gagal"

_AKTIF = (PENDING, MENUNGGU)  # status yang masih boleh diputuskan

# jenis aksi → nama aksi di audit log
_AUDIT_AKSI = {
    "drive_move": "pindah_drive",
    "drive_rename": "rename_drive",
    "drive_delete": "hapus_drive",
}


async def buat_pending(*, jenis: str, ringkasan: str, payload: dict,
                       peran: str = "arsip", diminta_oleh: str = "mcp") -> int:
    """Simpan aksi tertunda (status='pending'). Kembalikan id-nya (untuk tombol)."""
    async with SessionLocal() as db:
        row = AksiPending(
            peran=peran, jenis=jenis, tier="merah", ringkasan=ringkasan,
            payload=json.dumps(payload, ensure_ascii=False),
            status=PENDING, diminta_oleh=diminta_oleh,
        )
        db.add(row)
        await db.commit()
        await db.refresh(row)
        return row.id


def _drive():
    from app.kantor.drive.client import DriveClient, terkonfigurasi
    return DriveClient() if terkonfigurasi() else None


def _lakukan(c, jenis: str, p: dict) -> str:
    """Eksekusi payload deterministik. Melempar Exception bila gagal."""
    if jenis == "drive_move":
        c.pindah(p["file_id"], p["tujuan_id"])
        return f"'{p.get('nama', 'file')}' dipindah ke {p.get('tujuan_label', 'tujuan')}."
    if jenis == "drive_rename":
        c.ganti_nama(p["file_id"], p["nama_baru"])
        return f"Nama diubah: '{p.get('nama_lama', '?')}' → '{p['nama_baru']}'."
    if jenis == "drive_delete":
        c.buang_ke_sampah(p["file_id"])
        return f"'{p.get('nama', 'file')}' dipindah ke Sampah (pulih ~30 hari)."
    raise ValueError(f"jenis aksi tak dikenal: {jenis}")


async def _audit(db, jenis: str, payload: dict, status: str, error: str = "") -> None:
    detail = dict(payload)
    if error:
        detail["error"] = error[:200]
    db.add(KantorAuditLog(
        peran="kantor", aksi=_AUDIT_AKSI.get(jenis, jenis),
        target=payload.get("file_id", ""), status=status,
        detail=json.dumps(detail, ensure_ascii=False),
        aksi_pending_id=payload.get("_aksi_id"),
    ))


async def eksekusi_pending(aksi_id: int, *, diputus_oleh: int | None = None) -> tuple[bool, str]:
    """Eksekusi payload aksi yang DISETUJUI. Deterministik & idempoten."""
    async with SessionLocal() as db:
        row = await db.get(AksiPending, aksi_id)
        if row is None:
            return False, f"Aksi #{aksi_id} tidak ditemukan."
        if row.status not in _AKTIF:
            return False, f"Aksi #{aksi_id} sudah '{row.status}' — tak diproses ulang."
        payload = json.loads(row.payload or "{}")
        payload["_aksi_id"] = row.id
        c = _drive()
        if c is None:
            return False, "Drive belum terkonfigurasi di server ini."
        now = datetime.now(timezone.utc)
        try:
            hasil = _lakukan(c, row.jenis, payload)
        except Exception as e:  # noqa: BLE001
            row.status, row.hasil, row.diputus_oleh, row.diputus_at = GAGAL, str(e)[:300], diputus_oleh, now
            await _audit(db, row.jenis, payload, "gagal", error=str(e))
            await db.commit()
            log.warning("Aksi #%s GAGAL: %s", aksi_id, e)
            return False, f"Gagal menjalankan: {e}"
        row.status, row.hasil, row.diputus_oleh, row.diputus_at = DIEKSEKUSI, hasil, diputus_oleh, now
        await _audit(db, row.jenis, payload, "sukses")
        await db.commit()
        log.info("Aksi #%s dieksekusi: %s", aksi_id, hasil)
        return True, hasil


async def tolak_pending(aksi_id: int, *, diputus_oleh: int | None = None) -> tuple[bool, str]:
    """Tolak aksi tertunda. Tidak ada perubahan pada Drive."""
    async with SessionLocal() as db:
        row = await db.get(AksiPending, aksi_id)
        if row is None:
            return False, f"Aksi #{aksi_id} tidak ditemukan."
        if row.status not in _AKTIF:
            return False, f"Aksi #{aksi_id} sudah '{row.status}'."
        row.status = DITOLAK
        row.diputus_oleh = diputus_oleh
        row.diputus_at = datetime.now(timezone.utc)
        await db.commit()
        return True, "Ditolak. Tidak ada perubahan pada Drive."
