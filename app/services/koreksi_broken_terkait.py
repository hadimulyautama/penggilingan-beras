"""Pembatalan eksplisit perpindahan broken salah dan pembukuan otomatisnya.

Hanya terkait hasil proses yang sedang dikoreksi. Tidak menerima barang fisik
kembali dan tidak mengubah pemakaian silo yang sudah mempunyai siklus.
Transaksi, penguncian saldo global, snapshot dan idempotensi milik pemanggil.
"""
import json
from decimal import Decimal as D
from sqlalchemy import select,func
from app.models import ByproductStock,BrokenKeSilo,Silo,ActivityLog,OutgoingItem
from app.services import peristiwa as buku
from app.database import now_local

async def konteks(db,proc):
    from app.services.koreksi_bahan_berjalan import raw,siklus_g2
    from app.services.retur_supplier_reservasi import terikat
    from app.services.retur_supplier_stok import keluar
    rows=(await db.execute(select(BrokenKeSilo,ByproductStock).join(ByproductStock,ByproductStock.id==BrokenKeSilo.byproduct_stock_id).where(ByproductStock.source_type=='polishing',ByproductStock.source_id==proc.id,ByproductStock.jenis_produk=='broken').order_by(BrokenKeSilo.id))).all()
    out=[]
    for move,src in rows:
        usage=await siklus_g2(db,move)
        audit=await db.scalar(select(ActivityLog.id).where(ActivityLog.table_name=='byproduct_stock',ActivityLog.record_id==src.id,ActivityLog.action=='INSERT',ActivityLog.aksi=='broken_catat_otomatis',ActivityLog.new_value.startswith(proc.kode_proses+':')).limit(1))
        reserved=await terikat(db,sumber=f'broken:{src.id}')
        supplier=(await keluar(db,sumber=f'broken:{src.id}'))[0]
        sold=await db.scalar(select(func.coalesce(func.sum(OutgoingItem.berat_kg),0)).where(OutgoingItem.item_type=='byproduct_curah',OutgoingItem.jenis_byproduct=='broken',OutgoingItem.jasa_id==src.jasa_id))
        reason=None
        if src.jasa_id!=proc.jasa_id or move.jasa_id!=src.jasa_id:reason='Pemilik pembukuan berbeda; periksa perpindahan kepemilikan terkait.'
        elif src.status!='tersedia':reason='Status pembukuan sumber tidak lagi tersedia.'
        elif usage:reason=f'Bahan terkait siklus #{usage.id}; koreksi pemakaian proses terkait terlebih dahulu.'
        elif not audit:reason='Pembukuan bukan otomatis yang dapat ditelusuri; gunakan koreksi stok terkait.'
        elif reserved or supplier:reason='Sumber terkait alokasi atau barang keluar Retur ke Supplier.'
        elif sold:reason='Ada pengiriman broken curah pemilik terkait; periksa alokasi pengeluaran sebelum koreksi.'
        silo=await db.get(Silo,move.silo_id)
        out.append(dict(id=move.id,kode=move.kode_pindah,kg=float(move.berat_kg),stok_id=src.id,silo=silo.nama_silo if silo else 'Tidak tersedia',silo_id=move.silo_id,boleh_batal=reason is None,penghalang=reason,perpindahan=raw(move),pembukuan=raw(src),audit_otomatis=audit,reservasi=str(reserved),keluar_supplier=str(supplier),keluar_curah=str(sold)))
    return buku.bersih(out)

async def batalkan(db,proc,ids,user,alasan):
    from app.services.koreksi_bahan_berjalan import raw,JENIS
    from app.services.activity_log import log_activity
    if len(ids)!=len(set(ids)):raise ValueError('Perpindahan broken tidak boleh dipilih dua kali.')
    ctx={x['id']:x for x in await konteks(db,proc)}
    if any(i not in ctx for i in ids):raise ValueError('Perpindahan broken bukan bagian hasil proses/pemilik ini.')
    result=[];expected_sources={}
    for ident in sorted(ids):
        e=ctx[ident]
        if not e['boleh_batal']:raise ValueError(e['kode']+': '+e['penghalang'])
        move=await db.scalar(select(BrokenKeSilo).where(BrokenKeSilo.id==ident).with_for_update().execution_options(populate_existing=True))
        src=await db.scalar(select(ByproductStock).where(ByproductStock.id==e['stok_id']).with_for_update().execution_options(populate_existing=True))
        if move is None or src is None or buku.bersih(raw(move))!=e['perpindahan'] or buku.bersih(raw(src))!=expected_sources.get(e['stok_id'],e['pembukuan']):
            raise ValueError('Data perpindahan/pembukuan berubah saat dikunci; periksa ulang.')
        silo=await db.get(Silo,move.silo_id)
        from app.penggilingan.gudang2 import service as g2
        if not silo or not silo.aktif or silo.warehouse_id!=await g2._g2_warehouse_id(db):raise ValueError('Gudang/silo perpindahan tidak lagi sah.')
        previous=dict(perpindahan=raw(move),pembukuan=raw(src),saldo_silo=await g2.hitung_stok_silo(db,silo.id),status_silo=silo.status)
        amount=D(str(move.berat_kg));remaining=D(str(src.berat_kg))-amount
        if remaining<0:raise ValueError('Pembukuan broken kurang dari perpindahan; periksa sumber terbaru.')
        move.dibatalkan_pada=now_local()
        src.berat_kg=remaining
        await db.flush()
        expected_sources[src.id]=buku.bersih(raw(src))
        other=await db.scalar(select(func.coalesce(func.sum(BrokenKeSilo.berat_kg),0)).where(BrokenKeSilo.byproduct_stock_id==src.id))
        if remaining<D(str(other)):raise ValueError('Koreksi melampaui pembukuan yang masih dipakai perpindahan lain.')
        await g2.segarkan_status_silo(db,silo.id)
        for row,old in [(move,previous['perpindahan']),(src,previous['pembukuan'])]:
            await log_activity(db,table_name=row.__tablename__,record_id=row.id,action='UPDATE',changed_by=user.id,field_name='koreksi_broken_terkait',old_value=json.dumps(buku.bersih(old),default=str),new_value=json.dumps(buku.bersih(raw(row)),default=str),alasan=alasan,aksi=JENIS)
        result.append(dict(kode=move.kode_pindah,sebelum=previous,sesudah=dict(perpindahan=raw(move),pembukuan=raw(src),saldo_silo=await g2.hitung_stok_silo(db,silo.id),status_silo=silo.status)))
    return buku.bersih(result)
