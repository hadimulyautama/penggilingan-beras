"""Tanda terima kiriman hasil samping: stok dan kunci tersimpan satu transaksi.

Peristiwa ini hanya tanda terima, bukan sumber mutasi/proyeksi kedua. Replay
mengembalikan hasil asli tanpa menghitung atau memindahkan stok lagi.
"""
from dataclasses import asdict, is_dataclass
import re

from sqlalchemy import select
from app.models import Peristiwa
from app.services import peristiwa as buku
from app.services.barang_keluar import _kunci_saldo_keluar
from app.penggilingan.gudang2.service import Gudang2Error

JENIS = "kiriman_hasil_samping_silo"


async def simpan(db, *, user, kunci, aksi, isian, kerjakan):
    if not isinstance(kunci, str) or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", kunci):
        raise Gudang2Error(
            "Kunci kiriman belum tersedia. Buka kembali formulir agar kiriman "
            "ke silo terlindung dari pencatatan ganda.")
    key = "hasil-samping-silo:" + kunci
    isian = buku.bersih(isian)
    # Semua pemindahan/pengeluaran memegang kunci saldo yang sama sebelum
    # memeriksa sumber. Ini melindungi kiriman paralel, termasuk kunci berbeda.
    await _kunci_saldo_keluar(db)
    ada = await db.scalar(select(Peristiwa).where(Peristiwa.kunci_kiriman == key))
    if ada is not None:
        if (ada.jenis != JENIS or ada.pelaku_id != user.id
                or ada.muatan.get("aksi") != aksi or ada.muatan.get("isian") != isian):
            raise Gudang2Error(
                "Kunci kiriman sudah dipakai untuk isian atau petugas lain. "
                "Buka formulir baru untuk pemindahan yang berbeda.")
        return ada.muatan["hasil"]

    # Savepoint mencakup pembukaan karung, pemindahan FIFO, penambahan bahan
    # proses, audit, DAN tanda terima. Kegagalan salah satunya membatalkan semua.
    async with db.begin_nested():
        hasil = await kerjakan()
        hasil = buku.bersih(asdict(hasil) if is_dataclass(hasil) else hasil)
        await buku.catat(db, jenis=JENIS, pelaku_id=user.id, kunci_kiriman=key,
                         muatan=dict(aksi=aksi, isian=isian, hasil=hasil), terapkan=False)
    await db.commit()
    return hasil
