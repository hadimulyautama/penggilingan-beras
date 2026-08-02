"""Audit file NYASAR akurat — verifikasi kandidat dengan BACA ISI (AI). READ-ONLY.

Kandidat 'salah kategori' dari keyword (tak andal) diperiksa ulang: unduh teks →
klasifikasi AI → bandingkan dgn lokasi sekarang. Hanya yang AI yakin (≥0.8) beda
dari lokasi sekarang = nyasar terkonfirmasi.

Jalankan:
    railway run --service penggilingan-beras python scripts/gdrive_nyasar_ai.py
"""
from __future__ import annotations

import asyncio

from app.kantor.drive import client, mapper, organizer
from app.kantor.drive import klasifikasi_ai as ai


async def main() -> None:
    c = client.DriveClient()
    print("Menelusuri Drive...")
    snap = mapper.snapshot(c)
    lap = organizer.audit(snap)
    by_id = {e.id: e for e in snap.files}
    kandidat = lap.salah_tempat
    print(f"Kandidat salah-tempat (keyword): {len(kandidat)}. Verifikasi baca-isi...\n")

    konfirmasi = []
    for t in kandidat:
        e = by_id.get(t.file_id)
        teks = c.unduh_teks(e.id, e.mime) if e else ""
        r = await ai.klasifikasi_isi(t.nama, teks)
        kode_ai, yakin = r.get("kode"), float(r.get("keyakinan") or 0)
        sekarang = e.kategori if e else "?"
        cocok = kode_ai == sekarang
        status = "OK di tempat" if cocok else ("NYASAR" if yakin >= 0.8 else "ragu")
        adakah = "•" if teks else "○"  # ○ = teks tak terekstrak (nama saja)
        print(f"[{status:11}] {adakah} {t.nama[:44]:46} skrg {sekarang} | AI {kode_ai} ({yakin:.2f}) — {(r.get('alasan') or '')[:60]}")
        if not cocok and yakin >= 0.8:
            konfirmasi.append((t.nama, sekarang, kode_ai, r.get("kategori_nama"), r.get("alasan")))

    print(f"\n=== NYASAR TERKONFIRMASI AI (keyakinan ≥ 0.8): {len(konfirmasi)} ===")
    for nama, skr, ke, kenama, alasan in konfirmasi:
        print(f"  • {nama}\n      {skr} → {ke} {kenama}  |  {alasan}")


if __name__ == "__main__":
    asyncio.run(main())
