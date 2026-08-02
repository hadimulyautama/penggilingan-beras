"""Uji koneksi Google Drive (read-only) — bukti akses berhasil.

Membaca kredensial dari environment (di Railway, atau via `railway run`), lalu
menyebutkan folder tingkat atas Shared Drive PT. TIDAK mengubah apa pun.

Jalankan (memakai kredensial yang tersimpan di Railway):
    railway run python scripts/gdrive_selftest.py
"""
from __future__ import annotations

from app.kantor.drive import client


def main() -> None:
    if not client.terkonfigurasi():
        raise SystemExit(
            "Kredensial belum lengkap. Pastikan GDRIVE_OAUTH_* & "
            "GDRIVE_ROOT_FOLDER_ID ada (jalankan lewat `railway run`)."
        )
    c = client.DriveClient()
    folder = c.selftest()
    print(f"\n✅ SAMBUNG BERHASIL. {len(folder)} folder tingkat atas di Shared Drive PT:")
    for nama in sorted(folder):
        print(f"  • {nama}")


if __name__ == "__main__":
    main()
