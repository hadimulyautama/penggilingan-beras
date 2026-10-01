"""Tumpukan gabah — dua, tanpa batas, dan sebaiknya kosong.

**Tumpukan adalah tanda, bukan sekadar tempat.** Direksi menyebutnya jelas:
kalau ada tumpukan, berarti ada pembelian yang berlebih. Karena itu isinya
tidak diperlakukan seperti isi silo — ia muncul di layar "Berjalan" sebagai
pekerjaan yang menunggu diselesaikan, bukan sebagai keadaan yang tenang.

⚠ **TETAPI ATURAN ITU UNTUK GABAH YANG DIBELI.** Barang jasa bukan pembelian,
jadi tumpukan berisi gabah pelanggan bukan "pembelian berlebih" — ia pelanggan
yang menunggu giliran giling, keadaan yang memang biasa. Dibiarkan apa adanya,
tiga pelanggan yang menunggu akan berdiri di layar sebagai tiga kesalahan
pembelian; dan daftar yang menagih pekerjaan yang tidak salah akan berhenti
dibaca — bahaya yang sudah ditulis sendiri di `rekonsiliasi.py`.

Maka KALIMATNYA berbeda, bukan kartunya disembunyikan: pelanggan yang menunggu
tetap pekerjaan yang harus terlihat. Dan setiap hitungan "berlebih" di layar
mana pun menyaring `jasa_id IS NULL` — lihat `isi()` dan `jumlah_kg()`.

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
    "kering": ("dryer", "silo", "tumpuk"),
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


async def isi(db: AsyncSession, kondisi: str | None = None, *,
              pemilik: str = "semua") -> list[PurchaseBatch]:
    """Batch yang sedang menumpuk, terbaru dulu.

    `pemilik` memilih SIAPA yang dihitung, dan pemanggilnya harus memilih sadar:

        "semua"   isi lantai apa adanya — untuk kartu & layar operator
        "pabrik"  `jasa_id IS NULL` — untuk hitungan STOK dan "berlebih"
        "jasa"    barang titipan saja

    Bawaannya "semua" supaya kartu tak pernah kehilangan baris tanpa sengaja:
    barang yang hilang dari layar tidak hilang dari lantai gudang. Yang menghitung
    MILIK — stok, "pembelian berlebih" — menyebut "pabrik" terang-terangan.
    """
    q = select(PurchaseBatch).where(PurchaseBatch.status_batch == DITUMPUK)
    if kondisi:
        q = q.where(PurchaseBatch.kondisi_gabah == kondisi)
    if pemilik == "pabrik":
        q = q.where(PurchaseBatch.jasa_id.is_(None))
    elif pemilik == "jasa":
        q = q.where(PurchaseBatch.jasa_id.is_not(None))
    return list((await db.execute(
        q.order_by(PurchaseBatch.id.desc())
    )).scalars().all())


async def jumlah_kg(db: AsyncSession, *, pemilik: str = "pabrik") -> float:
    """Berapa kilogram yang menumpuk — MILIK PABRIK secara bawaan.

    Kebalikan bawaan dari `isi()`, dan itu disengaja: `isi()` memberi KARTU
    (menyembunyikan baris = pekerjaan yang hilang), fungsi ini memberi ANGKA
    STOK (memasukkan barang titipan = stok pabrik yang menggelembung dengan
    barang orang lain). Bawaan yang aman berbeda arah untuk keduanya.
    """
    from app.penggilingan.gudang1.services.bobot import dari_batch

    return sum(dari_batch(b).angka()
               for b in await isi(db, pemilik=pemilik))


async def tempatkan(
    db: AsyncSession, *, user, kode_batch: str, tujuan: str,
    dryer_id: int | None = None, silo_id: int | None = None,
) -> tuple[PurchaseBatch, str, str]:
    """Tempatkan satu batch gabah: dryer, silo, atau tumpukan.

    Mengembalikan (batch, nama tempatnya, peringatan). Peringatan kosong pada
    keadaan biasa; ia terisi saat penempatannya SAH tetapi tidak ideal —
    silo yang isinya jadi campuran, misalnya. Itu bukan galat, jadi ia tak
    boleh lewat sebagai pengecualian; tetapi ia juga tak boleh hilang.

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
        raise TumpukanError("Pilih tujuan: Dryer / Silo / Tumpukan.")

    peringatan = ""
    try:
        if tujuan == "tumpuk":
            await masuk_tumpukan(db, user=user, kode_batch=kode_batch)
            return batch, f"tumpukan {batch.kondisi_gabah}", ""
        if tujuan == "dryer":
            r = await masuk_dryer(db, user=user, kode_batch_list=[kode_batch],
                                  dryer_id=dryer_id)
            tempat = r.nama_dryer or "dryer"
        else:
            from app.penggilingan.gudang1.services.silo import silo_g1_by_id
            silo = await silo_g1_by_id(db, silo_id) if silo_id else None
            if silo is None:
                raise TumpukanError("Pilih silo tujuannya dulu.")
            nama = silo.nama_silo.replace("Silo ", "")
            r_silo = await masuk_silo(db, user=user, nama_silo=nama, kode_lot=None,
                                      kode_batch=kode_batch)
            tempat = silo.nama_silo
            # Silo BOLEH mencampur — tetapi campurannya harus terbaca saat
            # terjadi, bukan ditemukan belakangan lewat laporan. Ini bukan
            # penolakan: menahan gabah sampai ada silo kosong justru
            # memacetkan pengeringan berikutnya.
            if r_silo.campur_asal:
                peringatan = (
                    f"⚠️ {silo.nama_silo} berisi hasil pengeringan sendiri "
                    f"({r_silo.isi_sebelumnya}) — kini tercampur dengan gabah "
                    "beli kering, dan digiling sebagai SATU proses.")
            elif r_silo.digabung:
                peringatan = (f"⚠️ {silo.nama_silo} sudah berisi "
                              f"{r_silo.isi_sebelumnya} — isinya kini tercampur.")
            if r_silo.giling_berjalan:
                peringatan += (
                    ("\n" if peringatan else "")
                    + f"⚠️ {silo.nama_silo} sedang digiling "
                      f"({r_silo.giling_berjalan}) — gilingnya tetap jalan, dan "
                      f"gabah ini masuk sebagai bahan tambahannya "
                      f"(+{r_silo.kg_baris:,.0f} kg).".replace(",", "."))
    except (DryingError, SiloError) as e:
        raise TumpukanError(e.args[0] if e.args else "Gagal memindahkan.")
    return batch, tempat, peringatan
