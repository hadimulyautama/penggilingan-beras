"""Helper audit trail (activity_logs)."""
from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from hmu_identitas.peran import G1, G2

from app.models import ActivityLog

#: Gudang tempat sebuah tabel dicatat — SATU sumber, dibaca pencatat.
#:
#: Sebuah gabah masuk adalah urusan Gudang 1 apa pun yang tertulis di profil
#: pencatatnya; PK masuk penyosohan adalah urusan Gudang 2. Gudang milik
#: CATATAN, bukan milik orang — itulah yang membuat cakupan pembatalan tak
#: berubah surut ketika operator berpindah gudang (temuan QA P4-02).
#:
#: Pembagiannya mengikuti letak fisik prosesnya, sama dengan tab G1/G2 di
#: layar aksi (`api._ACTION_WH`): selepan, pengeringan, silo gabah, dan
#: giling di Gudang 1; PK masuk, penyosohan, kemasan, barang jadi, dan barang
#: keluar di Gudang 2. Pemindahan PK G1→G2 dicatat pada gudang ASALnya.
#: Yang tak ada di sini (undo, setelan, akun) bukan milik gudang mana pun.
#:
#: Pemanggil yang tahu lebih baik menyebutnya sendiri lewat `gudang=`:
#: barang keluar biasanya berangkat dari Gudang 2, tetapi PK yang dijual
#: mentah berangkat dari Gudang 1.
GUDANG_TABEL: dict[str, str] = {
    # Gudang 1 — selepan
    "purchase_batches": G1, "purchase_batch_verifications": G1,
    "drying_lots": G1, "drying_moisture_logs": G1, "drying_cooling_logs": G1,
    "silo_storage": G1, "silo_moving_logs": G1,
    "milling_process": G1, "milling_progress_logs": G1, "milling_qc_logs": G1,
    "milling_process_verifications": G1,
    "internal_transfers": G1,
    # Gudang 2 — penyosohan
    "pk_purchase_batches": G2, "pk_purchase_verifications": G2,
    "pk_gudang2_intakes": G2, "pk_tumpukan_to_silo": G2,
    "hasil_samping_ke_silo": G2, "beras_ke_silo": G2,
    "polishing_process": G2, "polishing_output_logs": G2, "polishing_silo_usage": G2,
    "packaging_purchases": G2, "finished_goods_stock": G2,
    "byproduct_stock": G2, "byproduct_prices": G2,
    "outgoing_records": G2,
}


async def log_activity(
    db: AsyncSession,
    *,
    table_name: str,
    record_id: int,
    action: str,
    changed_by: int | None = None,
    field_name: str | None = None,
    old_value: str | None = None,
    new_value: str | None = None,
    alasan: str | None = None,
    aksi: str | None = None,
    gudang: str | None = None,
) -> None:
    """Catat satu entri audit. Tidak commit — ikut transaksi pemanggil.

    `aksi` menyebutkan MAKSUD-nya, dan itu yang dipakai pembatalan untuk
    memilih penangan. Tanpanya pembatalan menebak dari nama tabel & kolom —
    dan tebakan itu salah persis pada kasus yang paling mudah keliru: "ubah
    target kadar air" dan "gabungkan batch ke lot" sama-sama UPDATE pada
    `drying_lots`.

    Boleh kosong, dan sebagian besar pemanggil memang belum menyebutkannya:
    yang wajib hanya aksi yang MAKSUDNYA tak bisa dibaca dari tabel & kolom.

    `gudang` disimpulkan dari tabelnya (`GUDANG_TABEL`) bila pemanggil tak
    menyebutkannya — TANPA kueri: fungsi ini ikut transaksi lima puluhan
    pemanggil, dan satu SELECT tambahan di sini adalah perubahan perilaku
    pada semuanya.
    """
    db.add(
        ActivityLog(
            table_name=table_name,
            record_id=record_id,
            action=action,
            field_name=field_name,
            old_value=old_value,
            new_value=new_value,
            changed_by=changed_by,
            alasan_perubahan=alasan,
            aksi=aksi,
            gudang=gudang if gudang is not None else GUDANG_TABEL.get(table_name),
        )
    )
