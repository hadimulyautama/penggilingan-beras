"""Pembaca saldo untuk rencana dan writer Isi Silo, tanpa pembukuan baru."""
from sqlalchemy import select
from app.models import ByproductStock, FinishedGoodsStock, ProductSku, PackageSize
from app.services.cakupan_fasilitas import lokasi


async def curah_bebas(db, row):
    from app.penggilingan.gudang2.service import _sisa_broken_row
    from app.services.transfer_barang_sumber import bebas
    return max(0.0, min(await _sisa_broken_row(db, row.id), float(await bebas(db, row, 'curah'))))


async def karung_bebas(db, row):
    from app.penggilingan.inventory.finished_goods import sisa_karung_per_sumber
    # Pembaca yang sudah dipakai writer: FIFO pengeluaran/lokasi dan retur.
    rows = await sisa_karung_per_sumber(db, row.product_sku_id,
        row.rice_quality_standard_id, jasa_id=row.jasa_id, source_type=None)
    return max(0, min(int(row.jumlah_karung or 0), next((n for r,n,_ in rows if r.id==row.id),0)))


async def proses(db, proc, owner, wid):
    from app.services.jasa import pemilik_hasil_proses
    from app.services.stok import output_sosoh
    from app.penggilingan.inventory.finished_goods import _broken_dibukukan
    def milik(c):return c.is_(None) if owner is None else c==owner
    curah=[]
    rows=(await db.scalars(select(ByproductStock).where(
        ByproductStock.jenis_produk=='broken',ByproductStock.source_type=='polishing',
        ByproductStock.source_id==proc.id,milik(ByproductStock.jasa_id),lokasi(ByproductStock)==wid)
        .order_by(ByproductStock.waktu,ByproductStock.id))).all()
    for r in rows:
        w=await curah_bebas(db,r)
        if w>0.5:curah.append((r.id,w))
    packs=[]
    rows=(await db.execute(select(FinishedGoodsStock,PackageSize.ukuran_kg)
        .join(ProductSku,ProductSku.id==FinishedGoodsStock.product_sku_id)
        .outerjoin(PackageSize,PackageSize.id==ProductSku.package_size_id)
        .where(ProductSku.kategori=='broken',FinishedGoodsStock.source_type=='polishing',
            FinishedGoodsStock.source_id==proc.id,milik(FinishedGoodsStock.jasa_id),lokasi(FinishedGoodsStock)==wid)
        .order_by(FinishedGoodsStock.waktu,FinishedGoodsStock.id))).all()
    for r,size in rows:
        n=await karung_bebas(db,r)
        # Writer membuka karung utuh berdasarkan ukuran SKU yang sama.
        if n and size:packs.append(dict(id=r.id,n=n,ukuran=float(size),kg=n*float(size)))
    mesin=0.0
    if owner==await pemilik_hasil_proses(db,proc.jasa_id,'broken'):
        mesin=max(0.0,float((await output_sosoh(db,proc.id)).get('broken') or 0)-await _broken_dibukukan(db,proc.id))
    if mesin<=0.5:mesin=0.0
    return dict(curah=curah,packs=packs,mesin=mesin,
        total=sum(w for _,w in curah)+sum(p['kg'] for p in packs)+mesin)
