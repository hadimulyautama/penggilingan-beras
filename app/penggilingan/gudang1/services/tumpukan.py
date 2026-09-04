"""Tumpukan gabah — dua, tanpa batas, dan sebaiknya kosong.

**Tumpukan adalah tanda, bukan sekadar tempat.** Direksi menyebutnya jelas:
kalau ada tumpukan, berarti ada pembelian yang berlebih. Karena itu isinya
tidak diperlakukan seperti isi silo — ia muncul di layar "Berjalan" sebagai
pekerjaan yang menunggu diselesaikan, bukan sebagai keadaan yang tenang.

**Ada dua, dan mana yang dipakai TIDAK disimpan.** Tumpukan basah dan tumpukan
kering; sebuah batch masuk ke tumpukan yang sesuai kondisinya, dan kondisinya
sudah tercatat di batch itu sendiri. Menyimpannya lagi berarti dua tempat yang
suatu hari akan berbeda, dan tak ada yang tahu mana yang benar.

**Keluarnya berbeda menurut kondisinya.** Gabah kering boleh pindah ke dryer
atau ke silo; gabah basah WAJIB ke dryer — ia belum kering, dan silo Gudang 1
menampung gabah kering.

Tanpa batas isi: tumpukan memang tempat gabah menunggu, dan menolak gabah yang
sudah terlanjur datang dan berdiri di halaman tidak membuatnya pergi.
"""
from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import PurchaseBatch
from app.services.activity_log import log_activity

#: Status batch saat berada di tumpukan. Kata yang sama sudah dipakai PK di
#: Gudang 2 — satu kosakata untuk satu keadaan, di kedua gudang.
DITUMPUK = "ditumpuk"

#: Ke mana gabah boleh ditempatkan, menurut kondisinya. Sama untuk gabah yang
#: belum di mana-mana maupun yang sedang menumpuk — tempat yang sah tidak
#: bergantung pada dari mana ia datang, melainkan pada basah atau keringnya.
TUJUAN_PINDAH = {
    "basah": ("dryer", "tumpuk"),
    "kering": ("dryer", "silo_a", "silo_b", "tumpuk"),
}

#: Status batch yang masih menunggu tempat. 'baru' = tercatat tetapi penempatan
#: otomatisnya gagal (dryer sedang dipakai, misalnya) — gabahnya sudah turun
#: dari truk, jadi batch-nya memang harus tetap tersimpan.
MENUNGGU_TEMPAT = ("baru", "ditumpuk")


class TumpukanError(Exception):
    """Kesalahan tumpukan dengan pesan siap-tampil (args[0])."""


async def masuk_tumpukan(db: AsyncSession, *, user, kode_batch: str) -> PurchaseBatch:
    """Taruh satu batch di tumpukan yang sesuai kondisinya."""
    batch = (await db.execute(
        select(PurchaseBatch).where(PurchaseBatch.kode_batch == kode_batch)
    )).scalars().first()
    if batch is None:
        raise TumpukanError(f"Batch {kode_batch} tidak ditemukan.")
    if batch.status_batch not in ("baru", DITUMPUK):
        raise TumpukanError(
            f"Batch {kode_batch} sudah diproses ({batch.status_batch})."
        )
    batch.status_batch = DITUMPUK
    await log_activity(
        db, table_name="purchase_batches", record_id=batch.id, action="UPDATE",
        changed_by=user.id,
        new_value=f"{batch.kode_batch} → tumpukan {batch.kondisi_gabah}",
    )
    await db.commit()
    return batch


async def menunggu_tempat(db: AsyncSession) -> list[PurchaseBatch]:
    """Gabah yang belum ada di dryer, silo, maupun sudah digiling.

    Dua keadaan sekaligus: yang sedang menumpuk, dan yang tercatat tetapi
    penempatan otomatisnya gagal. Keduanya butuh tindakan yang sama — ditaruh
    di suatu tempat — jadi keduanya ditawarkan lewat satu aksi, bukan dua.
    """
    return list((await db.execute(
        select(PurchaseBatch)
        .where(PurchaseBatch.status_batch.in_(MENUNGGU_TEMPAT))
        .order_by(PurchaseBatch.id.desc())
    )).scalars().all())


async def isi(db: AsyncSession, kondisi: str | None = None) -> list[PurchaseBatch]:
    """Batch yang sedang menumpuk, terbaru dulu."""
    q = select(PurchaseBatch).where(PurchaseBatch.status_batch == DITUMPUK)
    if kondisi:
        q = q.where(PurchaseBatch.kondisi_gabah == kondisi)
    return list((await db.execute(
        q.order_by(PurchaseBatch.id.desc())
    )).scalars().all())


async def tempatkan(
    db: AsyncSession, *, user, kode_batch: str, tujuan: str,
    dryer_id: int | None = None,
) -> tuple[PurchaseBatch, str]:
    """Tempatkan satu batch gabah: dryer, silo, atau tumpukan.

    Penempatannya diserahkan ke layanan yang memang memilikinya — `masuk_dryer`
    dan `masuk_silo` — bukan ditulis ulang di sini. Keduanya sudah menegakkan
    aturan dryer dan aturan silo; menyalinnya ke sini berarti dua salinan yang
    suatu hari berbeda, dan yang di sinilah yang akan luput diperbarui.
    """
    from app.penggilingan.gudang1.services.drying import DryingError, masuk_dryer
    from app.penggilingan.gudang1.services.silo import SiloError, masuk_silo

    batch = (await db.execute(
        select(PurchaseBatch).where(PurchaseBatch.kode_batch == kode_batch)
    )).scalars().first()
    if batch is None:
        raise TumpukanError(f"Batch {kode_batch} tidak ditemukan.")
    if batch.status_batch not in MENUNGGU_TEMPAT:
        raise TumpukanError(
            f"Batch {kode_batch} sudah ditempatkan ({batch.status_batch})."
        )

    sah = TUJUAN_PINDAH.get(batch.kondisi_gabah or "", ())
    if tujuan not in sah:
        if batch.kondisi_gabah == "basah":
            raise TumpukanError(
                f"{kode_batch} gabah basah — hanya boleh ke Dryer atau Tumpukan, "
                "belum boleh ke silo."
            )
        raise TumpukanError("Pilih tujuan: Dryer / Silo A / Silo B / Tumpukan.")

    try:
        if tujuan == "tumpuk":
            await masuk_tumpukan(db, user=user, kode_batch=kode_batch)
            return batch, f"tumpukan {batch.kondisi_gabah}"
        if tujuan == "dryer":
            r = await masuk_dryer(db, user=user, kode_batch_list=[kode_batch],
                                  dryer_id=dryer_id)
            tempat = r.nama_dryer or "dryer"
        else:
            nama = "A" if tujuan == "silo_a" else "B"
            await masuk_silo(db, user=user, nama_silo=nama, kode_lot=None,
                             kode_batch=kode_batch)
            tempat = f"Silo {nama}"
    except (DryingError, SiloError) as e:
        raise TumpukanError(e.args[0] if e.args else "Gagal memindahkan.")
    return batch, tempat
