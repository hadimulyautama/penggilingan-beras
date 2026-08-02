"""Rapikan nama file + deteksi duplikat di Shared Drive.

DEFAULT dry-run (read-only): hanya cetak rencana "nama lama → nama baru" +
daftar duplikat, TANPA mengubah apa pun. `--apply N` menerapkan N rename pertama.

Jalankan:
    railway run --service penggilingan-beras python scripts/gdrive_rapikan.py
    railway run --service penggilingan-beras python scripts/gdrive_rapikan.py --apply 3
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

from app.kantor.dokumen import konsistensi as kons
from app.kantor.drive import client, mapper, organizer


def main() -> None:
    apply_n = 0
    if len(sys.argv) >= 3 and sys.argv[1] == "--apply":
        apply_n = int(sys.argv[2])

    c = client.DriveClient()  # kredensial dari Railway
    print("Menelusuri Shared Drive (read-only)...")
    snap = mapper.snapshot(c)
    lap = organizer.audit(snap)

    # ── Rencana rename ──
    print(f"\n=== RENCANA RAPIKAN NAMA: {len(lap.nama)} file ===")
    applied = 0
    for i, t in enumerate(lap.nama, 1):
        mark = ""
        if i <= apply_n:
            c.ganti_nama(t.file_id, t.nama_usul)
            applied += 1
            mark = "   ✔ DITERAPKAN"
        print(f"{i:3}. {t.nama}  →  {t.nama_usul}{mark}")

    # ── Duplikat: nama ternormalisasi sama dalam satu folder ──
    grup: dict[tuple, list[str]] = defaultdict(list)
    for e in snap.files:
        base = os.path.splitext(kons.rapikan_nama(e.nama))[0].lower().strip()
        grup[(e.parent_id, base)].append(e.nama)
    dupe = {k: v for k, v in grup.items() if len(v) > 1}
    print(f"\n=== DUPLIKAT (nama mirip dalam 1 folder): {len(dupe)} grup ===")
    for (_, base), nama_list in list(dupe.items())[:40]:
        print(f"  • {base}:  {' | '.join(nama_list)}")

    print(f"\nRingkas: {len(lap.nama)} rename direncanakan, {applied} diterapkan; "
          f"{len(dupe)} grup duplikat.")


if __name__ == "__main__":
    main()
