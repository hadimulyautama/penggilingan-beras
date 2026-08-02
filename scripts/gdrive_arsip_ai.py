"""Arsip AI — klasifikasi baca-isi + pindah ke kategori benar.

Mode (scope):
  transit  : HANYA folder _TRANSIT — disposisi harian file baru (murah).
  all      : SELURUH file berkategori — audit menyeluruh 1x (mahal, ~semua file).
  kandidat : hanya kandidat salah-tempat versi keyword (default, pra-saring cepat).

Opsi: --apply (pindahkan yg nyasar), --limit N (batasi jumlah diperiksa AI).
'hapus'/pindah semua reversible (folder tujuan = kategori root; salah → tinggal balik).

Contoh:
  railway run --service penggilingan-beras python scripts/gdrive_arsip_ai.py transit
  railway run --service penggilingan-beras python scripts/gdrive_arsip_ai.py transit --apply
  railway run --service penggilingan-beras python scripts/gdrive_arsip_ai.py all --limit 50
"""
from __future__ import annotations

import asyncio
import sys

from app.kantor.drive import client, mapper, organizer
from app.kantor.drive import klasifikasi_ai as ai
from app.kantor.drive import taksonomi as tx


async def main() -> None:
    argv = sys.argv
    scope = next((s for s in ("transit", "all", "kandidat") if s in argv), "kandidat")
    apply = "--apply" in argv
    limit = int(argv[argv.index("--limit") + 1]) if "--limit" in argv else None

    c = client.DriveClient()
    print(f"Menelusuri Drive (scope={scope}{' → APPLY' if apply else ''})...")
    snap = mapper.snapshot(c)

    # peta kode kategori → id folder root (tujuan pindah)
    peta = {}
    for f in c.anak():
        if f.is_folder and (k := mapper.kode_kategori(f.nama)):
            peta[k] = f.id

    if scope == "transit":
        entri = [e for e in snap.files if e.kategori == tx.TRANSIT]
    elif scope == "all":
        entri = [e for e in snap.files
                 if e.kategori not in (None, tx.TRANSIT, tx.ARSIP_LAMA)]
    else:
        ids = {t.file_id for t in organizer.audit(snap).salah_tempat}
        entri = [e for e in snap.files if e.id in ids]
    if limit:
        entri = entri[:limit]

    import json
    ambang_pindah = (float(argv[argv.index("--ambang-pindah") + 1])
                     if "--ambang-pindah" in argv else 0.90)
    print(f"{len(entri)} file diperiksa AI. Ambang PINDAH ≥ {ambang_pindah}\n")
    dipindah = nyasar = 0
    review: list[dict] = []
    for e in entri:
        v = await ai.periksa_entri(c, e)
        if not v["nyasar"]:
            continue
        nyasar += 1
        yakin, kode_ai = v["yakin"], v["kode_ai"]
        if apply and yakin >= ambang_pindah and kode_ai in peta:
            c.pindah(e.id, peta[kode_ai], asal_id=e.parent_id)
            dipindah += 1
            print(f"[PINDAH✔] {e.nama[:48]:50} {e.kategori}→{kode_ai} ({yakin:.2f})")
        else:  # 0.80–0.89 (atau tujuan tak dikenal) → review manusia
            review.append({
                "nama": e.nama, "sekarang": e.kategori, "ke": kode_ai,
                "ke_nama": v["kategori_nama"], "yakin": yakin, "alasan": v["alasan"],
            })
            print(f"[REVIEW ] {e.nama[:48]:50} {e.kategori}→{kode_ai} ({yakin:.2f})")

    try:
        with open("/tmp/audit_review.json", "w", encoding="utf-8") as fp:
            json.dump(review, fp, ensure_ascii=False, indent=2)
    except Exception:
        pass
    print(f"\nSelesai. Nyasar {nyasar} · DIPINDAH {dipindah} (≥{ambang_pindah}) · "
          f"REVIEW {len(review)} (0.80–0.89).")


if __name__ == "__main__":
    asyncio.run(main())
