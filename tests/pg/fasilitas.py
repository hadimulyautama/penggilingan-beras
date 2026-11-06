"""Fasilitas fisik eksplisit untuk skenario dua proses bersamaan."""
from sqlalchemy import select,func
from app.models import JenisProsesProduksi,LiniProduksi
from app.services.fasilitas import seed_fasilitas


async def lini_baru(db,user,jenis):
    await seed_fasilitas(db)
    jid=await db.scalar(select(JenisProsesProduksi.id).where(JenisProsesProduksi.kode==jenis))
    nomor=await db.scalar(select(func.count()).select_from(LiniProduksi))
    line=LiniProduksi(kode=f'{jenis}-uji-{nomor+1}',nama=f'Alat uji {nomor+1}',
        warehouse_id=user.default_warehouse_id,jenis_proses_id=jid,aktif=True)
    db.add(line);await db.flush()
    return line.id


async def di_gudang(db, user, kode):
    """Konteks kerja eksplisit tanpa menulis ulang profil pengguna."""
    from app.services.cakupan_fasilitas import KonteksGudang, lama
    wid = await db.scalar(select(lama(kode)))
    assert wid is not None
    return KonteksGudang(role=user.role, id=user.id,
        default_warehouse_id=wid, stock_warehouse_filter=None)
