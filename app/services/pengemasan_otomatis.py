"""Pembaca/pagar hasil otomatis. Tidak membuat transaksi packing/karung."""
from decimal import Decimal as D
from sqlalchemy import select
from app.models import (FinishedGoodsStock,ByproductStock,ProductSku,BerasKeSilo,HasilSampingKeSilo)
from app.services import stok

async def terkait(db,proc,jenis):
    from app.penggilingan.inventory.finished_goods import get_standard
    kat,mutu=stok.kategori_dan_mutu(jenis)
    std=await get_standard(db,mutu) if mutu else None
    rows=list((await db.scalars(select(FinishedGoodsStock).join(ProductSku).where(
        FinishedGoodsStock.source_type=='polishing',FinishedGoodsStock.source_id==proc.id,
        ProductSku.kategori==kat,FinishedGoodsStock.rice_quality_standard_id==(std.id if std else None)).order_by(FinishedGoodsStock.id))).all())
    lots=list((await db.scalars(select(ByproductStock).where(ByproductStock.source_type=='polishing',ByproductStock.source_id==proc.id,ByproductStock.jenis_produk==jenis).order_by(ByproductStock.id))).all())
    moves=[]
    for model in (BerasKeSilo,HasilSampingKeSilo):
        moves+=list((await db.scalars(select(model).where(model.polishing_process_id==proc.id,model.jenis==jenis).order_by(model.id))).all())
    return rows,lots,moves

async def pastikan_hasil(db,proc,lama,baru):
    """Hanya jenis yang berkurang. Pencatatan tersimpan tidak dihapus otomatis.

    Batas ini adalah jumlah yang sudah mempunyai rumah/sumber terhubung,
    bukan larangan menyeluruh ketika ada transaksi produk lain.
    """
    for kind,target in baru.items():
        if D(str(target))>=D(str(lama.get(kind,0))):continue
        rows,lots,moves=await terkait(db,proc,kind)
        if kind not in stok._UKURAN_KEMASAN_OTOMATIS and (rows or lots or moves):
            raise ValueError(f'{kind}: hasil sudah mempunyai catatan kemasan/perpindahan terkait. Gunakan alur koreksi lama untuk jenis nonotomatis.')
        for r in rows+lots+moves:
            value=getattr(r,'berat_total_kg',None) if r in rows else r.berat_kg
            if value is None or not D(str(value)).is_finite() or D(str(value))<0:
                raise ValueError(f'{r.__tablename__} #{r.id}: bobot historis belum sah. Rekonsiliasi sumber sebelum koreksi.')
        minimum=sum((D(str(x.berat_total_kg)) for x in rows),D(0))+sum((D(str(x.berat_kg)) for x in lots+moves),D(0))
        if D(str(target))<minimum:
            codes=[f'kemasan/curah #{r.id} ({r.berat_total_kg} kg; /koreksi-catatan/packing/{r.id})' for r in rows if r.berat_total_kg]
            codes += [f'{r.__tablename__} #{r.id} ({r.berat_kg} kg; /koreksi-catatan/'+('stok-samping' if r in lots else 'beras-silo' if isinstance(r,BerasKeSilo) else 'samping-silo')+f'/{r.id})' for r in lots+moves if r.berat_kg]
            raise ValueError(f'{kind}: hasil {target} kg kurang dari {minimum} kg yang telah dicatat pada sumber terkait: '+ '; '.join(codes)+'. Perbaiki data terkait melalui alur sah; tidak ada pembatalan otomatis.')

async def ringkasan(db,proc,jenis):
    from app.services.jasa import pemilik_hasil_proses,nama_pemilik
    owner=await pemilik_hasil_proses(db,proc.jasa_id,jenis)
    cards=await stok.stok_produk(db,jasa_id=owner)
    card=next((x for x in cards if x.jenis==jenis),None)
    total=(await stok.output_sosoh(db,proc.id)).get(jenis,0)
    # Saldo ini milik pool pemilik, bukan alokasi hasil campuran per proses.
    saldo=card.sisa_kg if card else 0
    size,n,packed,bulk=stok._packing_otomatis(jenis,saldo)
    rows,lots,moves=await terkait(db,proc,jenis)
    return dict(total_proses=total,pemilik_id=owner,pemilik=await nama_pemilik(db,owner) if owner else 'Milik pabrik',
        saldo_pemilik=saldo,ukuran=size,karung=n,berat_terkemas=packed,curah=bulk,
        kemasan_terhubung=[dict(id=r.id,kg=float(r.berat_total_kg),karung=r.jumlah_karung,sku_id=r.product_sku_id,jasa_id=r.jasa_id,pakai_karung=r.kemasan_mengurangi_stok) for r in rows],
        pemakaian=[dict(tabel=x.__tablename__,id=x.id,kg=float(x.berat_kg)) for x in lots+moves])

async def pastikan_saldo(db,proc,kinds):
    from app.services.jasa import pemilik_hasil_proses
    from app.services.barang_keluar import BarisPerintah,tersedia
    for kind in kinds:
        owner=await pemilik_hasil_proses(db,proc.jasa_id,kind)
        cards=await stok.stok_produk(db,jasa_id=owner)
        card=next((x for x in cards if x.jenis==kind),None)
        if card and card.sisa_kg < -.005:
            raise ValueError(f'{kind}: saldo pemilik menjadi {card.sisa_kg:g} kg. Pengiriman/perpindahan terkait sudah memakai hasil; periksa rincian stok dan transaksi asal.')
        if kind in stok._UKURAN_KEMASAN_OTOMATIS:
            free,_=await tersedia(db,BarisPerintah(tipe='byproduct_curah',jenis=kind,jasa_id=owner))
            if free < -.005:raise ValueError(f'{kind}: saldo bebas {free:g} kg setelah alokasi. Periksa perintah/alokasi terkait sebelum mengurangi hasil.')
