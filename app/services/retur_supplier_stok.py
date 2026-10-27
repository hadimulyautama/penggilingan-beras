"""Suku keluar supplier pada pembaca stok resmi, bersumber dari satu peristiwa.

Tidak menimpa penerimaan dan tidak menulis OutgoingItem penjualan. Alokasi
aktif berada di retur_supplier_reservasi; suku fisik hanya ada setelah
proyeksi peristiwa barang keluar tercatat.
"""
from decimal import Decimal
from sqlalchemy import select,func
from app.models.retur_supplier import ReturSupplierItem as I,ReturSupplierAktual as A,ReturSupplierKeluar as K
from app.models.retur_supplier_koreksi import ReturSupplierSelisih as S


def efektif(kolom):
    """Mutasi awal ditambah selisih; bukan pembalikan dan pengeluaran ulang."""
    return getattr(A,kolom)+select(func.coalesce(func.sum(getattr(S,kolom)),0)).where(S.item_id==I.id).correlate(I).scalar_subquery()


def kueri():
    return select(func.coalesce(func.sum(efektif('bobot_kg')),0),func.coalesce(func.sum(efektif('jumlah')),0)).select_from(A).join(I,I.id==A.item_id).join(K,K.retur_supplier_id==I.retur_supplier_id)


async def keluar(db,*,sumber=None,tipe=None,sku=None,std=None,jenis=None):
    q=kueri()
    if sumber is not None:q=q.where(I.kunci_sumber==sumber)
    if tipe is not None:q=q.where(I.tipe_pool==tipe)
    if sku is not None:q=q.where(I.product_sku_id==sku,I.rice_quality_standard_id==std)
    if jenis is not None:q=q.where(I.jenis_produk==jenis)
    kg,n=(await db.execute(q)).one()
    return Decimal(str(kg)),Decimal(str(n))


async def curah_beras(db,row):
    kg,_=await keluar(db,sumber=f'beras:{row.id}')
    return Decimal(str(row.berat_total_kg))-kg


async def keluar_banyak(db,keys):
    if not keys:return {}
    q=select(I.kunci_sumber,func.sum(efektif('bobot_kg')),func.sum(efektif('jumlah'))).select_from(A).join(I,I.id==A.item_id).join(K,K.retur_supplier_id==I.retur_supplier_id).where(I.kunci_sumber.in_(keys)).group_by(I.kunci_sumber)
    return {k:(Decimal(str(kg)),Decimal(str(n))) for k,kg,n in (await db.execute(q)).all()}
