"""Jembatan baca-only ke sistem TIMBANGAN (aplikasi terpisah, DB terintegrasi).

Model `timbangan_transaksi` dimiliki repo timbangan; di sini kita hanya MEMBACA lewat
SQL mentah pada DB yang sama. Dipakai intake produksi untuk menaut batch ke tiket timbang
(operator memilih tiket aktif, bukan mengetik bobot/supplier).

Sumber kebenaran: bobot/supplier/nopol dari timbang. Bobot:
  netto_timbangan_kg = bobot TIMBANG (real, wajib)
  berat_acuan_kg     = bobot NOTA/surat jalan (opsional)
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

# Tiket MASUK yang masih TERBUKA & BELUM ditaut batch mana pun.
_SQL_AKTIF = text("""
    SELECT t.id, t.kode, t.jenis_kode, t.tanggal, t.nomor_polisi, t.nama_sopir,
           t.supplier_id, s.nama_supplier, t.pihak_nama,
           t.netto_timbangan_kg, t.berat_acuan_kg, t.selisih_kg, t.selisih_persen,
           t.status_kontrol, t.status_tiket
      FROM timbangan_transaksi t
      LEFT JOIN suppliers s ON s.id = t.supplier_id
     WHERE t.arah = 'MASUK'
       AND t.status_tiket = 'TERBUKA'
       AND t.id NOT IN (SELECT timbangan_transaksi_id FROM purchase_batches
                          WHERE timbangan_transaksi_id IS NOT NULL)
       AND t.id NOT IN (SELECT timbangan_transaksi_id FROM pk_purchase_batches
                          WHERE timbangan_transaksi_id IS NOT NULL)
     ORDER BY t.tanggal DESC, t.id DESC
""")

_SQL_SATU = text("""
    SELECT t.id, t.kode, t.arah, t.jenis_kode, t.tanggal, t.nomor_polisi, t.nama_sopir,
           t.supplier_id, s.nama_supplier, t.pihak_nama,
           t.netto_timbangan_kg, t.berat_acuan_kg, t.selisih_kg, t.selisih_persen,
           t.status_kontrol, t.status_tiket
      FROM timbangan_transaksi t
      LEFT JOIN suppliers s ON s.id = t.supplier_id
     WHERE t.id = :tid
""")


def _row(r) -> dict:
    d = dict(r._mapping)
    # Basis bobot untuk HPP: nota bila ada, selain itu real timbang.
    nota = d.get("berat_acuan_kg")
    real = d.get("netto_timbangan_kg")
    ada_nota = nota is not None and float(nota or 0) > 0
    d["sumber_berat"] = "nota" if ada_nota else "timbangan"
    d["berat_hpp_kg"] = float(nota) if ada_nota else (float(real) if real is not None else None)
    return d


async def tiket_masuk_aktif(db: AsyncSession, jenis_kode: str | None = None) -> list[dict]:
    """Daftar tiket timbang MASUK aktif & belum tertaut (untuk dipilih operator)."""
    rows = (await db.execute(_SQL_AKTIF)).all()
    out = [_row(r) for r in rows]
    if jenis_kode:
        out = [d for d in out if d["jenis_kode"] == jenis_kode]
    return out


async def ambil_tiket(db: AsyncSession, tid: int) -> dict | None:
    """Ambil satu tiket timbang (untuk membentuk batch)."""
    r = (await db.execute(_SQL_SATU, {"tid": tid})).first()
    return _row(r) if r else None


# Isi bobot batch yang MASIH 'menunggu' dari tiket-nya, begitu tiket punya bobot
# (nota atau netto timbang). Bobot efektif = nota bila ada, selain itu netto real.
_SQL_SINKRON = """
    UPDATE {tbl} b SET
        berat_total_kg = COALESCE(NULLIF(t.berat_acuan_kg, 0), t.netto_timbangan_kg),
        sumber_berat   = CASE WHEN COALESCE(t.berat_acuan_kg, 0) > 0
                              THEN 'nota' ELSE 'timbangan' END
      FROM timbangan_transaksi t
     WHERE b.timbangan_transaksi_id = t.id
       AND b.sumber_berat = 'menunggu'
       AND COALESCE(NULLIF(t.berat_acuan_kg, 0), t.netto_timbangan_kg) IS NOT NULL
"""


async def sinkron_bobot_menunggu(db: AsyncSession) -> int:
    """Isi bobot semua batch (gabah & PK) yang 'menunggu' dari tiket timbang-nya.
    → jumlah baris terisi. Idempoten: yang sudah terisi tak disentuh."""
    total = 0
    for tbl in ("purchase_batches", "pk_purchase_batches"):
        res = await db.execute(text(_SQL_SINKRON.format(tbl=tbl)))
        total += res.rowcount or 0
    await db.commit()
    return total
