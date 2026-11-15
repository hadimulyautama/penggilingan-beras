"""Distribusi lokasi karung tanpa memecah atau membuat pembelian fiktif.

Jumlah pembelian dan pemakaian tetap dibaca oleh inventory. Perpindahan
hanya menambah delta lokasi; jumlah seluruh gudang tidak berubah.
"""
from decimal import Decimal
from sqlalchemy import select
from app.models import PackagingPurchase, TransferBarang, TransferBarangItem, Warehouse
from app.services.cakupan_fasilitas import lokasi_banyak
D=lambda x:Decimal(str(x or 0))


async def perpindahan(db,ids):
    if not ids:return {}
    rows=(await db.execute(select(TransferBarangItem,TransferBarang).join(TransferBarang,TransferBarang.id==TransferBarangItem.transfer_id).where(
        TransferBarang.status=='selesai',TransferBarangItem.jumlah>0,TransferBarangItem.dampak['jenis'].as_string()=='karung',
        TransferBarangItem.dampak['sumber_id'].as_integer().in_(ids)))).all()
    result={}
    for item,t in rows:
        root=int(item.dampak['sumber_id']);n=D(item.jumlah)
        for wid,sign in [(t.asal_id,-1),(t.tujuan_id,1)]:
            key=(root,wid);result[key]=result.get(key,D(0))+sign*n
    return result


async def kombinasi(db,material,size,brand,owner):
    q=select(PackagingPurchase).where(PackagingPurchase.packaging_material_id==material,PackagingPurchase.package_size_id==size,
        PackagingPurchase.brand_id==brand,PackagingPurchase.pelanggan_id.in_(owner) if isinstance(owner,list) else PackagingPurchase.pelanggan_id==owner)
    return list((await db.scalars(q.order_by(PackagingPurchase.tanggal,PackagingPurchase.waktu,PackagingPurchase.id))).all())


async def delta(db,material,size,brand,owner,warehouse_id):
    rows=await kombinasi(db,material,size,brand,owner)
    return sum((n for (rid,wid),n in (await perpindahan(db,[r.id for r in rows])).items() if wid==warehouse_id),D(0))


async def penempatan(db,material,size,brand,owner):
    rows=await kombinasi(db,material,size,brand,owner)
    loc=await lokasi_banyak(db,PackagingPurchase,[r.id for r in rows]);net=await perpindahan(db,[r.id for r in rows])
    pools={(r.id,loc[r.id]['warehouse_id']):D(r.jumlah_lembar) for r in rows}
    for key,n in net.items():pools[key]=pools.get(key,D(0))+n
    return rows,pools


async def bebas(db,row,warehouse_id):
    from app.penggilingan.inventory.packaging import hitung_stok_kemasan
    rows,pools=await penempatan(db,row.packaging_material_id,row.package_size_id,row.brand_id,row.pelanggan_id)
    total=sum((n for (rid,wid),n in pools.items() if wid==warehouse_id),D(0))
    saldo=D(await hitung_stok_kemasan(db,row.packaging_material_id,row.package_size_id,row.brand_id,pelanggan_id=row.pelanggan_id,warehouse_id=warehouse_id))
    used=max(D(0),total-saldo)
    for r in rows:
        n=max(D(0),pools.get((r.id,warehouse_id),D(0)));take=min(n,used);used-=take
        if r.id==row.id:return n,n-take
    return D(0),D(0)


async def tersebar(db,ids):
    """Dipakai penjaga alih milik: lokasi tidak boleh terseret pemecahan owner."""
    return any(n for n in (await perpindahan(db,ids)).values())
