"""Audit arsip Shared Drive (READ-ONLY) — telusuri, deteksi, laporkan.

Tidak mengubah apa pun; hanya melihat & melaporkan (nyasar / _TRANSIT / nama).
Jalankan dengan kredensial Railway:
    railway run --service penggilingan-beras python scripts/gdrive_scan.py
"""
from __future__ import annotations

from app.kantor.drive import client, mapper, organizer


def main() -> None:
    if not client.terkonfigurasi():
        raise SystemExit("Kredensial Drive belum ada (jalankan lewat `railway run`).")
    c = client.DriveClient(dry_run=True)   # dry_run: jaga-jaga, tak menulis
    print("Menelusuri Shared Drive PT (read-only)...")
    snap = mapper.snapshot(c)
    n_file = len(snap.files)
    n_folder = sum(1 for e in snap.entri if e.is_folder)
    print(f"Selesai: {n_folder} folder, {n_file} file"
          + (" (kena batas aman)" if snap.kena_batas else "") + ".\n")
    lap = organizer.audit(snap)
    print(organizer.ringkas(lap))


if __name__ == "__main__":
    main()
