"""Rekonsiliasi TIMBANGAN ↔ INTAKE produksi (shared DB, read-only).

Menutup celah dobel/bocor + menyoroti selisih nota vs timbang riil:
  1. Tiket MASUK sudah SELESAI tapi BELUM jadi batch → gabah/PK ditimbang tapi tak tercatat.
  2. Batch tertaut dengan SELISIH nota↔timbang (kg, %, Rp) → potensi lebih bayar / kurang terima.
  3. Batch "menunggu bobot" → belum tersinkron dari timbang.
  4. Batch MANUAL (tanpa timbang) → perlu ditinjau.
"""
from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

_SQL_BELUM_TERTAUT = text("""
    SELECT t.kode, t.jenis_kode, t.tanggal, t.nomor_polisi,
           t.netto_timbangan_kg, t.berat_acuan_kg,
           COALESCE(s.nama_supplier, t.pihak_nama) AS nama
      FROM timbangan_transaksi t
      LEFT JOIN suppliers s ON s.id = t.supplier_id
     WHERE t.arah = 'MASUK'
       AND t.status_tiket IN ('SELESAI', 'DITUTUP_PAKSA')
       AND t.id NOT IN (SELECT timbangan_transaksi_id FROM purchase_batches
                          WHERE timbangan_transaksi_id IS NOT NULL)
       AND t.id NOT IN (SELECT timbangan_transaksi_id FROM pk_purchase_batches
                          WHERE timbangan_transaksi_id IS NOT NULL)
     ORDER BY t.tanggal DESC, t.id DESC
""")

# Batch (gabah + PK) tertaut dgn selisih nota↔timbang. UNION dua tabel intake.
_SQL_SELISIH = text("""
    SELECT kode_batch, nama, jenis, nota, timbang, selisih_kg, selisih_persen, harga FROM (
      SELECT b.kode_batch, COALESCE(s.nama_supplier,'?') AS nama, 'gabah' AS jenis,
             t.berat_acuan_kg AS nota, t.netto_timbangan_kg AS timbang,
             t.selisih_kg, t.selisih_persen, v.harga_per_kg AS harga
        FROM purchase_batches b
        JOIN timbangan_transaksi t ON t.id = b.timbangan_transaksi_id
        LEFT JOIN suppliers s ON s.id = b.supplier_id
        LEFT JOIN purchase_batch_verifications v ON v.purchase_batch_id = b.id
      UNION ALL
      SELECT b.kode_batch, COALESCE(s.nama_supplier,'?') AS nama, 'pk' AS jenis,
             t.berat_acuan_kg, t.netto_timbangan_kg, t.selisih_kg, t.selisih_persen,
             v.harga_per_kg
        FROM pk_purchase_batches b
        JOIN timbangan_transaksi t ON t.id = b.timbangan_transaksi_id
        LEFT JOIN suppliers s ON s.id = b.supplier_id
        LEFT JOIN pk_purchase_verifications v ON v.pk_purchase_batch_id = b.id
    ) x
    WHERE timbang IS NOT NULL AND COALESCE(nota,0) > 0
      AND ABS(COALESCE(selisih_kg,0)) > 0
    ORDER BY ABS(COALESCE(selisih_kg,0)) DESC
""")

_SQL_MENUNGGU = text("""
    SELECT kode_batch, 'gabah' j FROM purchase_batches WHERE sumber_berat='menunggu'
    UNION ALL
    SELECT kode_batch, 'pk' j FROM pk_purchase_batches WHERE sumber_berat='menunggu'
""")

# Batch tertaut yang bobot tersimpannya BEDA dari tiket SAAT INI (tiket direvisi)
# TAPI sudah terverifikasi harga / (gabah) sudah digiling → TIDAK di-auto-resync
# (nilai finansial/rendemen beku). Perlu ditinjau manual.
_SQL_REVISI = text("""
    SELECT kode_batch, nama, jenis, tersimpan, tiket_now, status, terverifikasi FROM (
      SELECT b.kode_batch, COALESCE(s.nama_supplier,'?') AS nama, 'gabah' AS jenis,
             b.berat_total_kg AS tersimpan,
             COALESCE(NULLIF(t.berat_acuan_kg,0), t.netto_timbangan_kg) AS tiket_now,
             b.status_batch AS status, (NOT b.flag_unverified) AS terverifikasi
        FROM purchase_batches b
        JOIN timbangan_transaksi t ON t.id = b.timbangan_transaksi_id
        LEFT JOIN suppliers s ON s.id = b.supplier_id
       WHERE b.sumber_berat IN ('nota','timbangan')
      UNION ALL
      SELECT b.kode_batch, COALESCE(s.nama_supplier,'?'), 'pk',
             b.berat_total_kg, COALESCE(NULLIF(t.berat_acuan_kg,0), t.netto_timbangan_kg),
             b.status_batch, (NOT b.flag_unverified)
        FROM pk_purchase_batches b
        JOIN timbangan_transaksi t ON t.id = b.timbangan_transaksi_id
        LEFT JOIN suppliers s ON s.id = b.supplier_id
       WHERE b.sumber_berat IN ('nota','timbangan')
    ) x
    WHERE tiket_now IS NOT NULL
      AND tersimpan IS DISTINCT FROM tiket_now
      AND (terverifikasi = true OR status = 'digiling')
    ORDER BY ABS(COALESCE(tersimpan,0) - tiket_now) DESC
""")

_SQL_MANUAL = text("""
    SELECT count(*) FROM (
      SELECT id FROM purchase_batches WHERE sumber_berat='manual'
      UNION ALL SELECT id FROM pk_purchase_batches WHERE sumber_berat='manual'
    ) z
""")


async def rekonsiliasi(db: AsyncSession) -> dict:
    belum = [dict(r._mapping) for r in (await db.execute(_SQL_BELUM_TERTAUT)).all()]
    selisih = [dict(r._mapping) for r in (await db.execute(_SQL_SELISIH)).all()]
    revisi = [dict(r._mapping) for r in (await db.execute(_SQL_REVISI)).all()]
    menunggu = [dict(r._mapping) for r in (await db.execute(_SQL_MENUNGGU)).all()]
    n_manual = (await db.execute(_SQL_MANUAL)).scalar_one()
    return {"belum_tertaut": belum, "selisih": selisih, "revisi": revisi,
            "menunggu": menunggu, "jumlah_manual": int(n_manual or 0)}


def _kg(v) -> str:
    return f"{float(v or 0):,.0f}".replace(",", ".")


def format_rekonsiliasi(d: dict) -> str:
    baris = ["🔎 Rekonsiliasi Timbangan ↔ Intake"]
    belum = d["belum_tertaut"]
    baris.append(f"\n① Timbang MASUK selesai tapi BELUM jadi batch: {len(belum)}")
    for t in belum[:10]:
        b = t.get("berat_acuan_kg") or t.get("netto_timbangan_kg")
        baris.append(f"   • {t['kode']} · {t.get('nama') or '?'} · {t['jenis_kode']} · {_kg(b)} kg")
    sel = d["selisih"]
    baris.append(f"\n② Selisih nota ↔ timbang riil: {len(sel)} batch")
    for x in sel[:10]:
        rp = (float(x.get("selisih_kg") or 0) * float(x["harga"])) if x.get("harga") else None
        rps = f" ≈ Rp {_kg(rp)}" if rp is not None else ""
        baris.append(f"   • {x['kode_batch']} ({x['nama']}): nota {_kg(x['nota'])} vs timbang "
                     f"{_kg(x['timbang'])} → selisih {_kg(x['selisih_kg'])} kg "
                     f"({float(x.get('selisih_persen') or 0):.1f}%){rps}")
    rev = d.get("revisi", [])
    baris.append(f"\n③ Bobot tiket BERUBAH setelah verifikasi/giling (perlu tinjau): {len(rev)}")
    for x in rev[:10]:
        tag = "terverifikasi" if x.get("terverifikasi") else str(x.get("status") or "")
        baris.append(f"   • {x['kode_batch']} ({x['nama']}): tersimpan {_kg(x['tersimpan'])} kg "
                     f"→ tiket kini {_kg(x['tiket_now'])} kg [{tag}] — tak diubah otomatis")
    baris.append(f"\n④ Batch menunggu bobot: {len(d['menunggu'])}"
                 + (" — " + ", ".join(m['kode_batch'] for m in d['menunggu'][:10]) if d['menunggu'] else ""))
    baris.append(f"⑤ Batch manual (tanpa timbang): {d['jumlah_manual']}")
    if not belum and not sel and not rev and not d["menunggu"]:
        baris.append("\n✅ Bersih — semua timbang tertaut & tak ada selisih.")
    return "\n".join(baris)
