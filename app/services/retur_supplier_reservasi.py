"""Alokasi pengajuan aktif, terpisah dari pembaca stok fisik.

Pemanggil memakai kunci saldo barang keluar yang sama. Tidak pernah membuat
OutgoingItem atau mengubah baris penerimaan. Batal hanya melepas alokasi.
"""
from decimal import Decimal
from sqlalchemy import select, func
from app.models.retur_supplier import ReturSupplier, ReturSupplierItem as Item


async def terikat(db, *, sku_id=None, std_id=None, jenis=None, pk=False,
                  sumber=None, kecuali=None):
    q = select(func.coalesce(func.sum(Item.bobot_kg), 0)).join(
        ReturSupplier, ReturSupplier.id == Item.retur_supplier_id).where(
            ReturSupplier.status == 'diajukan')
    if kecuali is not None:
        q = q.where(ReturSupplier.id != kecuali)
    if sumber is not None:
        q = q.where(Item.kunci_sumber == sumber)
    elif sku_id is not None:
        q = q.where(Item.product_sku_id == sku_id,Item.tipe_pool=='finished_goods',
            Item.rice_quality_standard_id.is_(None) if std_id is None
            else Item.rice_quality_standard_id == std_id)
    elif jenis is not None:
        q = q.where(Item.jenis_produk == jenis)
    elif pk:
        q = q.where(Item.tipe_pool == 'pk_g2')
    else:
        return Decimal(0)
    return Decimal(str(await db.scalar(q)))


async def pastikan_sumber_bebas(db, sumber):
    """Penempatan utuh tidak boleh memindah barang yang sedang dialokasikan."""
    if await terikat(db, sumber=sumber) > 0:
        raise ValueError('Sumber masih dialokasikan pada pengajuan Retur ke Supplier. '
                         'Batalkan pengajuan yang sah sebelum memindahkan barang ini.')


async def karung_terikat(db, sumber, *, kecuali=None):
    q=select(func.coalesce(func.sum(Item.jumlah),0))\
        .join(ReturSupplier,ReturSupplier.id==Item.retur_supplier_id)
    q=q.where(ReturSupplier.status=='diajukan',Item.kunci_sumber==sumber,Item.satuan=='karung')
    if kecuali is not None:q=q.where(ReturSupplier.id!=kecuali)
    return int(await db.scalar(q))


async def terikat_banyak(db,keys,*,karung=False):
    if not keys:return {}
    q=select(Item.kunci_sumber,func.sum(Item.jumlah if karung else Item.bobot_kg)).join(ReturSupplier,ReturSupplier.id==Item.retur_supplier_id).where(ReturSupplier.status=='diajukan',Item.kunci_sumber.in_(keys))
    if karung:q=q.where(Item.satuan=='karung')
    return {k:Decimal(str(n)) for k,n in (await db.execute(q.group_by(Item.kunci_sumber))).all()}


async def pastikan_boleh_batal_sumber(db,key):
    from app.services.barang_keluar import _kunci_saldo_keluar
    await _kunci_saldo_keluar(db)
    if await db.scalar(select(Item.id).join(ReturSupplier,ReturSupplier.id==Item.retur_supplier_id)
            .where(Item.kunci_sumber==key,ReturSupplier.status!='dibatalkan').limit(1)):
        raise ValueError('Sumber memiliki pengajuan Retur ke Supplier aktif atau barang keluar tercatat. Periksa/koreksi hubungan hilir melalui alur yang berwenang sebelum membatalkan penerimaan.')
