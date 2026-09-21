"""Giling SELESAI yang bobot masuknya tak cocok lagi dengan bobot bahannya —
deteksi dan koreksi atas permintaan admin (QA pra-deploy P6, 21 Sep 2026).

Celahnya: migrasi 0054 menandai `bobot_masuk_final = false` hanya untuk
giling yang bahannya MASIH 'menunggu'. Korban lama P6-03 terlewat — giling
yang selesai dengan bobot masuk kurang, lalu truknya SUDAH ditimbang sejak
itu. Bahannya kini 'timbangan'/'nota', jadi syaratnya tak kena: penandanya
tetap true, poller baru dan rekonsiliasi sama-sama melewatinya.

JANGAN dibetulkan otomatis. Dari data lama tak bisa dibedakan dua hal yang
tampak sama: (a) korban P6-03 — bobot truk terisi SESUDAH giling selesai;
(b) bobot tiket yang DIREVISI dengan sengaja sesudah giling, yang memang
dirancang untuk ditinjau manusia (rekonsiliasi butir ③). Menyamakan keduanya
diam-diam akan mengubah angka yang mungkin sudah benar. Maka: daftarnya
disebut di rekonsiliasi, dan yang membetulkan adalah admin, per kode proses,
lewat aksi yang tercatat di jejak audit dan bisa dibatalkan.
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import MillingProcess, MillingProcessSource
from app.services.activity_log import log_activity

#: Tag di jejak audit — dipakai pembatalan memilih penangannya.
TAG_BETULKAN = "betulkan_bobot"

#: Selisih di bawah ini bukan ketidakcocokan: pembulatan timbangan.
AMBANG_KG = 1.0

# Kueri QA/alat/p7/deteksi_korban_p6-03.sql — diuji dua arah oleh QA
# (menemukan korban dengan tepat; nol baris pada data yang sudah benar).
# Bahan yang masih belum pasti TIDAK masuk: itu urusan poller & butir ⑩.
_SQL_TAK_COCOK = text("""
    WITH bahan AS (
      SELECT s.milling_process_id,
             SUM(b.berat_total_kg) AS bobot_bahan_kini,
             BOOL_OR(b.sumber_berat IN ('menunggu', 'perkiraan')) AS masih_belum_pasti
        FROM milling_process_sources s
        LEFT JOIN drying_lot_batches dlb ON dlb.drying_lot_id = s.drying_lot_id
        JOIN purchase_batches b ON b.id = COALESCE(s.purchase_batch_id, dlb.purchase_batch_id)
       WHERE b.dibatalkan_pada IS NULL          -- cermin bertanda
       GROUP BY s.milling_process_id
    )
    SELECT m.id, m.kode_proses,
           m.waktu_mulai                                   AS mulai,
           m.berat_gabah_masuk_kg                          AS tercatat_kg,
           bahan.bobot_bahan_kini                          AS seharusnya_kg,
           bahan.bobot_bahan_kini - m.berat_gabah_masuk_kg AS kurang_kg,
           ROUND(100 * (bahan.bobot_bahan_kini - m.berat_gabah_masuk_kg)
                 / NULLIF(bahan.bobot_bahan_kini, 0), 1)  AS kurang_persen
      FROM milling_process m
      JOIN bahan ON bahan.milling_process_id = m.id
     WHERE m.status = 'selesai'
       AND m.bobot_masuk_final = true
       AND NOT bahan.masih_belum_pasti
       AND ABS(bahan.bobot_bahan_kini - COALESCE(m.berat_gabah_masuk_kg, 0)) > :ambang
     ORDER BY m.waktu_mulai DESC
""")


async def giling_tak_cocok(db: AsyncSession) -> list[dict]:
    """Giling selesai yang bobot masuknya berbeda > 1 kg dari jumlah bobot
    bahannya SEKARANG — korban P6-03 lama ATAU revisi tiket yang disengaja.
    Keduanya tampak sama dari data; yang membedakan adalah manusia."""
    rows = (await db.execute(_SQL_TAK_COCOK, {"ambang": AMBANG_KG})).all()
    return [dict(r._mapping) for r in rows]


class KoreksiError(Exception):
    """Pesan siap-tampil (args[0])."""


@dataclass
class HasilBetulkan:
    proc: MillingProcess
    tercatat_kg: float | None
    sekarang_kg: float | None
    final: bool


async def betulkan_bobot_masuk(
    db: AsyncSession, *, user, kode_proses: str | None,
) -> HasilBetulkan:
    """Tandai satu giling selesai "bobot masuk belum final", lalu samakan
    bahannya SEKARANG JUGA lewat jalur poller yang sama (`resinkron_bahan_
    berjalan`) — admin melihat angkanya berubah, tak menunggu tiga menit.

    Cuplikan bobot lama (proses + tiap sumbernya) disimpan di jejak audit
    sebagai `old_value`, supaya pembatalan bisa mengembalikannya persis.
    """
    from app.penggilingan.gudang1.services.milling import resinkron_bahan_berjalan

    if not kode_proses:
        raise KoreksiError("Pilih giling yang mau dibetulkan dulu.")
    proc = (await db.execute(
        select(MillingProcess).where(MillingProcess.kode_proses == kode_proses)
    )).scalars().first()
    if proc is None:
        raise KoreksiError(f"Proses {kode_proses} tidak ditemukan.")
    if proc.status != "selesai":
        raise KoreksiError(
            f"{kode_proses} masih berjalan — bahannya disamakan poller sendiri, "
            "tak perlu dibetulkan.")
    if not proc.bobot_masuk_final:
        raise KoreksiError(
            f"{kode_proses} sudah bertanda belum final; poller akan "
            "membetulkannya paling lama 3 menit lagi.")
    sumber = (await db.execute(
        select(MillingProcessSource).where(MillingProcessSource.milling_process_id == proc.id)
    )).scalars().all()
    if not sumber:
        raise KoreksiError(
            f"{kode_proses} tak punya daftar bahan (proses lama, sebelum penautan "
            "timbang) — tak ada yang bisa dibaca ulang.")
    tercatat = float(proc.berat_gabah_masuk_kg) if proc.berat_gabah_masuk_kg is not None else None
    cuplikan = {
        "berat_gabah_masuk_kg": tercatat,
        "sumber": {str(s.id): (float(s.berat_kg) if s.berat_kg is not None else None)
                   for s in sumber},
    }
    proc.bobot_masuk_final = False
    await log_activity(
        db, table_name="milling_process", record_id=proc.id, action="UPDATE",
        changed_by=user.id, field_name="bobot_masuk_final",
        old_value=json.dumps(cuplikan), new_value="belum final — disamakan dengan bobot bahan",
        alasan="admin membetulkan bobot masuk giling yang tak cocok dengan bahannya",
        aksi=TAG_BETULKAN,
    )
    await db.flush()
    # Jalur yang SAMA dengan poller — bukan salinan rumusnya.
    await resinkron_bahan_berjalan(db)
    await db.commit()
    await db.refresh(proc)
    sekarang = float(proc.berat_gabah_masuk_kg) if proc.berat_gabah_masuk_kg is not None else None
    return HasilBetulkan(proc=proc, tercatat_kg=tercatat, sekarang_kg=sekarang,
                         final=bool(proc.bobot_masuk_final))


async def kembalikan_bobot_masuk(db: AsyncSession, proc_id: int, cuplikan_json: str | None) -> str:
    """Pembatalan `betulkan_bobot_masuk`: kembalikan cuplikan lama persis,
    dan tandai final lagi supaya poller tak menyamakannya kembali."""
    proc = await db.get(MillingProcess, proc_id)
    if proc is None:
        raise KoreksiError("Proses giling sudah tidak ada.")
    try:
        cuplikan = json.loads(cuplikan_json or "")
    except (TypeError, ValueError):
        raise KoreksiError("Jejak koreksinya tak memuat bobot lama — tak bisa dikembalikan.")
    lama = cuplikan.get("berat_gabah_masuk_kg")
    proc.berat_gabah_masuk_kg = lama
    proc.bobot_masuk_final = True
    for s in (await db.execute(
        select(MillingProcessSource).where(MillingProcessSource.milling_process_id == proc.id)
    )).scalars().all():
        if str(s.id) in cuplikan.get("sumber", {}):
            s.berat_kg = cuplikan["sumber"][str(s.id)]
    sebut = f"{float(lama):,.0f} kg".replace(",", ".") if lama is not None else "belum diketahui"
    return f"Bobot masuk {proc.kode_proses} dikembalikan ke {sebut} (bertanda final lagi)."
