"""Dedup berbasis ISI (MD5) — HANYA duplikat DALAM SATU FOLDER (aman).

Duplikat lintas-folder yang disengaja (mis. KK sama di folder tiap anggota
keluarga) TIDAK disentuh. Default read-only; `--apply` memindah salinan
berlebih ke '99 - Arsip Lama' (sisakan 1 nama terbersih). Reversible.

Jalankan:
    railway run --service penggilingan-beras python scripts/gdrive_dedup_check.py
    railway run --service penggilingan-beras python scripts/gdrive_dedup_check.py --apply
"""
from __future__ import annotations

import re
import sys
from collections import defaultdict

from app.kantor.drive import client, mapper
from app.kantor.drive import taksonomi as tx

_MARKER = re.compile(r"\(\d+\)|\bcopy\b|- copy", re.I)


def _kanonik(es: list) -> object:
    """Entri yang DIPERTAHANKAN: tanpa penanda salinan dulu, lalu nama terpendek."""
    return min(es, key=lambda e: (bool(_MARKER.search(e.nama)), len(e.nama)))


def main() -> None:
    apply = "--apply" in sys.argv
    # batas opsional: --apply 5 = terapkan 5 pertama; --apply = semua
    batas = -1
    if apply:
        i = sys.argv.index("--apply")
        if i + 1 < len(sys.argv) and sys.argv[i + 1].isdigit():
            batas = int(sys.argv[i + 1])
    c = client.DriveClient()
    print(f"Menelusuri Drive + MD5 (read-only{'' if not apply else ' → lalu APPLY'})...")
    snap = mapper.snapshot(c)

    # kunci = (folder yang sama, isi identik)
    grup: dict[tuple, list] = defaultdict(list)
    for e in snap.files:
        # KECUALIKAN isi folder 99 (target karantina) — jangan makan ekor sendiri.
        if e.md5 and e.kategori != tx.ARSIP_LAMA:
            grup[(e.parent_id, e.md5)].append(e)
    dupe = {k: es for k, es in grup.items() if len(es) > 1}
    redundan = sum(len(es) - 1 for es in dupe.values())
    print(f"\nGrup duplikat SEFOLDER (isi identik): {len(dupe)} · "
          f"file redundan: {redundan}\n")

    dipindah = 0
    for (_, _), es in sorted(dupe.items(), key=lambda kv: -len(kv[1]))[:60]:
        keep = _kanonik(es)
        others = [e for e in es if e.id != keep.id]
        print(f"  [{len(es)}x] simpan: {keep.nama}  (buang {len(others)})")
        for e in others[:4]:
            print(f"        → 99: {e.nama}")
        if len(others) > 4:
            print(f"        … +{len(others)-4} lagi")
        if apply:
            for e in others:
                if batas >= 0 and dipindah >= batas:
                    break
                c.karantina(e.id, asal_id=e.parent_id)
                print(f"        ✔ dipindah: {e.nama}")
                dipindah += 1

    if apply:
        print(f"\n✔ DIPINDAH ke 99 - Arsip Lama: {dipindah} file (reversible).")
    else:
        print(f"\nRencana: {redundan} file akan dipindah ke 99 (jalankan --apply).")


if __name__ == "__main__":
    main()
