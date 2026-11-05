"""Cakupan lokasi berbasis relasi domain; tidak menulis atau menghitung stok.

Fallback kode_fungsi hanya untuk catatan lama tanpa relasi lokasi. Line baru
selalu mempunyai gudang eksplisit. Kategori proses bukan identitas lokasi.
"""
from dataclasses import dataclass

@dataclass(frozen=True)
class KonteksGudang:
    role: str
    default_warehouse_id: int | None
    id: int
    stock_warehouse_filter: int

from sqlalchemy import select,func,case,true,false,or_
from sqlalchemy.orm import aliased
from hmu_identitas import peran as P
from app.models import (Warehouse,LiniProduksi,JenisProsesProduksi,Dryer,Silo,
    PurchaseBatch,PkPurchaseBatch,DryingLot,DryingLotBatch,MillingProcess,
    PolishingProcess,PolishingSiloUsage,SiloStorage,PkGudang2Intake,FinishedGoodsStock,ByproductStock,OutgoingItem,OutgoingRecord,BrokenKeSilo,HasilSampingKeSilo,InternalTransfer)


def lama(kode):
    return select(Warehouse.id).where(Warehouse.kode_fungsi==kode).correlate(None).scalar_subquery()


def lokasi(model):
    """Ekspresi SQL lokasi catatan; bisa dipakai sebelum count/pagination."""
    line=aliased(LiniProduksi)
    if model in (DryingLot,MillingProcess,PolishingProcess):
        utama=select(line.warehouse_id).where(line.id==model.lini_produksi_id).correlate(model).scalar_subquery()
        if model is DryingLot:
            alat=aliased(Dryer)
            asal=select(alat.warehouse_id).where(alat.id==model.dryer_id).correlate(model).scalar_subquery()
        elif model is MillingProcess:
            silo=aliased(Silo)
            asal=select(silo.warehouse_id).where(silo.id==model.silo_id).correlate(model).scalar_subquery()
        else:
            silo=aliased(Silo); usage=aliased(PolishingSiloUsage)
            asal=select(func.min(silo.warehouse_id)).join(usage,usage.silo_id==silo.id).where(usage.polishing_process_id==model.id).having(func.count(func.distinct(silo.warehouse_id))==1).correlate(model).scalar_subquery()
        return func.coalesce(utama,model.warehouse_id,asal,lama('g1')) if model is MillingProcess else func.coalesce(utama,asal,lama('g2' if model is PolishingProcess else 'g1'))
    if model is PurchaseBatch:
        alat=aliased(Dryer);lot=aliased(DryingLot);link=aliased(DryingLotBatch)
        direct=select(alat.warehouse_id).where(alat.id==model.dryer_id).correlate(model).scalar_subquery()
        dried=select(alat.warehouse_id).join(lot,lot.dryer_id==alat.id).join(link,link.drying_lot_id==lot.id).where(link.purchase_batch_id==model.id).limit(1).correlate(model).scalar_subquery()
        return func.coalesce(model.warehouse_id,direct,dried,lama('g1'))
    if model is PkPurchaseBatch:
        return func.coalesce(model.warehouse_id,lama('g2'))
    if model in (FinishedGoodsStock,ByproductStock):
        parent=select(lokasi(PolishingProcess)).where(PolishingProcess.id==model.source_id).correlate(model).scalar_subquery()
        source=case((model.source_type=='polishing',parent),else_=lama('g2'))
        return func.coalesce(model.warehouse_id,source)
    if model is OutgoingRecord:return func.coalesce(model.warehouse_id,lama('g2'))
    if model is OutgoingItem:
        return select(lokasi(OutgoingRecord)).where(OutgoingRecord.id==model.outgoing_record_id).correlate(model).scalar_subquery()
    if model in (BrokenKeSilo,HasilSampingKeSilo,InternalTransfer):
        return func.coalesce(select(Silo.warehouse_id).where(Silo.id==model.silo_id).correlate(model).scalar_subquery(),lama('g2'))
    if model is PkGudang2Intake:
        return func.coalesce(model.warehouse_id,select(PkPurchaseBatch.warehouse_id).where(PkPurchaseBatch.id==model.pk_purchase_batch_id).correlate(model).scalar_subquery(),select(Silo.warehouse_id).where(Silo.id==model.silo_id).correlate(model).scalar_subquery(),lama('g2'))
    if model is Silo:return model.warehouse_id
    raise ValueError('Model cakupan lokasi belum didukung: '+model.__name__)


def batas(user,model,*,baca_pk=False):
    requested=getattr(user,'stock_warehouse_filter',None)
    if requested is not None:
        from types import SimpleNamespace
        actor=SimpleNamespace(role=user.role,default_warehouse_id=user.default_warehouse_id)
        return batas(actor,model,baca_pk=baca_pk) & (lokasi(model)==requested)
    if user is None or P.admin_keatas(user.role):return true()
    if not P.operator_saja(user.role) or not user.default_warehouse_id:return false()
    expr=lokasi(model)
    cocok=expr==user.default_warehouse_id
    if baca_pk and model is MillingProcess:
        # Hak lama G2 membaca PK G1 sebagai calon bahan, bukan mengoperasikan G1.
        cocok=or_(cocok,(user.default_warehouse_id==lama('g2')) & (expr==lama('g1')))
    return cocok


async def boleh_jenis(db,user,kode):
    if P.admin_keatas(user.role):return True
    if not P.operator_saja(user.role) or not user.default_warehouse_id:return False
    q=select(LiniProduksi.id).join(JenisProsesProduksi).join(Warehouse).where(
        LiniProduksi.warehouse_id==user.default_warehouse_id,LiniProduksi.aktif.is_(True),
        JenisProsesProduksi.aktif.is_(True),JenisProsesProduksi.kode==kode,Warehouse.aktif.is_(True))
    if await db.scalar(q.limit(1)):return True
    # Peran lama tetap dapat membuka riwayat meski fasilitas diarsipkan.
    legacy='g2' if kode=='penyosohan' else 'g1'
    return bool(await db.scalar(select(Warehouse.id).where(Warehouse.id==user.default_warehouse_id,Warehouse.kode_fungsi==legacy,Warehouse.aktif.is_(True))))


async def boleh_objek(db,user,model,id):
    return bool(await db.scalar(select(model.id).where(model.id==id,batas(user,model))))


async def gudang_penerimaan(db,user,*,warehouse_id=None,jenis='pengeringan'):
    from app.services.fasilitas import izin_gudang,FasilitasError
    if warehouse_id is None:
        warehouse_id=user.default_warehouse_id if P.operator_saja(user.role) else await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g1'))
    w=await db.get(Warehouse,warehouse_id) if warehouse_id else None
    if not w or not w.aktif or not izin_gudang(user,w.id):raise FasilitasError('Gudang penerimaan tidak tersedia atau di luar kewenangan.')
    if not await boleh_jenis(db,user,jenis):raise FasilitasError('Gudang kerja belum mempunyai fasilitas untuk tindakan ini.')
    return w.id

async def pilihan_gudang(db,user):
    if P.admin_keatas(user.role):q=select(Warehouse).where(Warehouse.aktif.is_(True))
    elif P.operator_saja(user.role) and user.default_warehouse_id:
        q=select(Warehouse).where(Warehouse.aktif.is_(True),Warehouse.id==user.default_warehouse_id)
    else:return []
    return list((await db.execute(q.order_by(Warehouse.id))).scalars())

async def pilih_gudang_penerima(db,user,warehouse_id,*,legacy='g1'):
    from app.services.fasilitas import FasilitasError
    rows=await pilihan_gudang(db,user)
    if warehouse_id is None:
        if len(rows)==1:return rows[0].id
        old=next((w for w in rows if w.kode_fungsi==legacy),None)
        if old:return old.id
        raise FasilitasError('Pilih gudang penerima.')
    if not any(w.id==warehouse_id for w in rows):raise FasilitasError('Gudang penerima tidak aktif atau di luar kewenangan Anda.')
    return warehouse_id

async def lokasi_banyak(db,model,ids):
    if not ids:return {}
    pairs=dict((await db.execute(select(model.id,lokasi(model)).where(model.id.in_(ids)))).all())
    wh={w.id:w for w in (await db.execute(select(Warehouse).where(Warehouse.id.in_(set(pairs.values())-{None})))).scalars()}
    return {id:dict(warehouse_id=wid,gudang_nama=wh[wid].nama_gudang if wid in wh else 'Lokasi belum tercatat',
                   gudang_kode=(wh[wid].kode_fungsi or f'wh:{wid}') if wid in wh else '') for id,wid in pairs.items()}

async def konteks_baca_gudang(db,user,kode):
    """Tambahan filter baca saja. Tidak mengganti identitas atau izin aktor."""
    from types import SimpleNamespace
    if not kode:return user
    if kode.startswith('wh:') and kode[3:].isdigit():q=select(Warehouse.id).where(Warehouse.id==int(kode[3:]))
    else:q=select(Warehouse.id).where(Warehouse.kode_fungsi==kode)
    wid=await db.scalar(q)
    return KonteksGudang(role=user.role,default_warehouse_id=user.default_warehouse_id,id=user.id,stock_warehouse_filter=wid or -1)

async def pilihan_filter_stok(db,user):
    """Daftar lokasi, dengan pengecualian baca PK G1 bagi operator G2 lama."""
    rows=await pilihan_gudang(db,user)
    if P.operator_saja(user.role):
        own=await db.get(Warehouse,user.default_warehouse_id)
        if own and own.kode_fungsi=='g2':
            other=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g1',Warehouse.aktif.is_(True)))
            if other and all(w.id!=other.id for w in rows):rows.append(other)
    return tuple((w.kode_fungsi or f'wh:{w.id}',w.nama_gudang,'') for w in sorted(rows,key=lambda w:w.id))
