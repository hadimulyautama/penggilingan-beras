"""Adaptor lokasi persediaan. Tidak pernah mengubah jasa_id/pelanggan_id.

Angka barang tersedia berasal dari tabel dan pemakaian inventory yang sama.
Bagian yang dipindahkan tetap mempunyai asal produksi/pembelian aslinya;
transfer bukan penerimaan baru, pengemasan baru, atau alih milik.
"""
from decimal import Decimal, InvalidOperation
from sqlalchemy import select, func
from app.database import now_local
from app.models import (FinishedGoodsStock, ByproductStock, PackagingPurchase,
    PurchaseBatch, GabahKeringLot, PkGudang2Intake, Warehouse, User, ProductSku,
    OutgoingItem, OutgoingRecord, SiloStorage, DryingLotBatch, GabahKeringBongkar,
    BrokenKeSilo, HasilSampingKeSilo, Jasa, MillingProcess, MillingProcessSource)
from hmu_identitas import peran as P
from app.peran import can_see_financials
from app.services.cakupan_fasilitas import lokasi, lokasi_banyak

D=lambda x:Decimal(str(x or 0))
MODEL={'barang':FinishedGoodsStock,'curah_barang':FinishedGoodsStock,'curah':ByproductStock,
       'karung':PackagingPurchase,'gabah':PurchaseBatch,'gabah_kering':GabahKeringLot,'pk_tumpukan':PkGudang2Intake,'pk_giling':MillingProcess}
INTEGER={'barang','karung'}
UTUH={'gabah','gabah_kering','pk_tumpukan'}

class TransferBarangError(ValueError):pass


def angka(value,*,nol=False,bulat=False):
    try:n=Decimal(str(value))
    except (InvalidOperation,ValueError,TypeError):raise TransferBarangError('Isi jumlah yang sah.') from None
    if not n.is_finite() or n<0 or not nol and n==0 or n>Decimal('9999999999.99') or n!=n.quantize(Decimal('.01')):
        raise TransferBarangError('Jumlah harus positif dan maksimal dua desimal.')
    if bulat and n!=n.to_integral_value():raise TransferBarangError('Jumlah karung atau lembar harus bilangan bulat.')
    return n


def jumlah(row,jenis):
    return D(row.jumlah_karung if jenis=='barang' else row.jumlah_lembar if jenis=='karung' else row.berat_total_kg if jenis in ('curah_barang','gabah') else row.berat_timbang_kg if jenis=='gabah_kering' else row.berat_kg)


def berat(row,jenis,n):
    if jenis=='karung':return None
    if jenis=='barang':
        from app.penggilingan.gudang2.rencana_beras import berat_karung_nyata
        return berat_karung_nyata(row,int(n))
    return n


def atur(row,jenis,n,w=None):
    if jenis=='barang':row.jumlah_karung=int(n);row.berat_total_kg=w
    elif jenis=='karung':row.jumlah_lembar=int(n)
    elif jenis=='curah_barang':row.berat_total_kg=n
    elif jenis=='curah':row.berat_kg=n
    else:raise TransferBarangError('Lot ini hanya dapat dipindah utuh; bobot asal tidak ditulis ulang.')


async def izin(user):
    if not user or user.status!='aktif' or not (can_see_financials(user) or P.operator_saja(user.role) and user.default_warehouse_id):
        raise PermissionError('Transfer memerlukan akun operasional dengan gudang kerja aktif.')


async def bebas(db,row,jenis):
    """Saldo bebas satu sumber, dengan pengeluaran dipisah per lokasi."""
    from app.services import kepemilikan as baca
    from app.services.kepemilikan_detail import identity
    from app.services.retur_supplier_reservasi import terikat
    if jenis in ('barang','curah_barang'):
        ident=identity(row,jenis);owner=row.pelanggan_id if jenis=='karung' else row.jasa_id
        rows=await baca.free_rows(db,jenis,ident,owner,allocating=True)
        nilai=dict((r.id,n) for r,n in rows).get(row.id,D(0))
        wid=await db.scalar(select(lokasi(FinishedGoodsStock)).where(FinishedGoodsStock.id==row.id))
        # Pemakaian HSS lama menyimpan asal proses, belum baris SKU yang
        # dibuka. Selama jejak itu ada, jangan menyebut suatu baris utuh bebas
        # hanya karena pengeluarannya tidak berbentuk penjualan berkarung.
        if row.source_type=='polishing' and await db.scalar(select(HasilSampingKeSilo.id).where(HasilSampingKeSilo.polishing_process_id==row.source_id,HasilSampingKeSilo.jasa_id==row.jasa_id,lokasi(HasilSampingKeSilo)==wid).limit(1)):
            return D(0)
        if jenis=='curah_barang':
            sku=await db.get(ProductSku,row.product_sku_id)
            places=await lokasi_banyak(db,FinishedGoodsStock,[r.id for r,_ in rows])
            bulk=select(OutgoingItem).where(OutgoingItem.jasa_id==row.jasa_id,lokasi(OutgoingItem)==wid,
                ((OutgoingItem.item_type=='finished_goods') & (OutgoingItem.product_sku_id==row.product_sku_id) & (OutgoingItem.rice_quality_standard_id==row.rice_quality_standard_id) & (OutgoingItem.jumlah_karung==0)) |
                ((OutgoingItem.item_type=='byproduct_curah') & (OutgoingItem.jenis_byproduct==sku.kategori)))
            used=D(0);held=D(0)
            for out in (await db.scalars(bulk)).all():
                used+=D(out.berat_kg)
                record=await db.get(OutgoingRecord,out.outgoing_record_id)
                if record.status=='perintah':held+=max(D(0),D(out.berat_perintah_kg)-D(out.berat_kg))
            ordered=sorted(rows,key=lambda x:(x[0].waktu_penempatan or x[0].waktu,x[0].id))
            for candidate,n in ordered:
                if places[candidate.id]['warehouse_id']!=wid:continue
                take=min(D(n),used);used-=take;n=D(n)-take
                take=min(n,held);held-=take;n-=take
                if candidate.id==row.id:return n
            return D(0)
        if jenis=='barang':
            wid=await db.scalar(select(lokasi(FinishedGoodsStock)).where(FinishedGoodsStock.id==row.id))
            pending=await db.scalar(select(func.coalesce(func.sum(OutgoingItem.jumlah_karung_perintah-OutgoingItem.jumlah_karung),0)).join(OutgoingRecord).where(
                OutgoingRecord.status=='perintah',OutgoingItem.item_type=='finished_goods',OutgoingItem.product_sku_id==row.product_sku_id,
                OutgoingItem.rice_quality_standard_id==row.rice_quality_standard_id,OutgoingItem.jasa_id==row.jasa_id,lokasi(OutgoingItem)==wid))
            nilai=max(D(0),nilai-D(pending))
        return min(jumlah(row,jenis),max(D(0),D(nilai)))
    if jenis=='curah':
        rows=list((await db.scalars(select(ByproductStock).where(ByproductStock.jenis_produk==row.jenis_produk,ByproductStock.jasa_id==row.jasa_id).order_by(func.coalesce(ByproductStock.waktu_penempatan,ByproductStock.waktu),ByproductStock.id))).all())
        wh=await lokasi_banyak(db,ByproductStock,[r.id for r in rows]);wid=wh[row.id]['warehouse_id']
        keluar=D(await db.scalar(select(func.coalesce(func.sum(OutgoingItem.berat_kg),0)).where(OutgoingItem.item_type=='byproduct_curah',OutgoingItem.jenis_byproduct==row.jenis_produk,OutgoingItem.jasa_id==row.jasa_id,lokasi(OutgoingItem)==wid)))
        pending=D(await db.scalar(select(func.coalesce(func.sum(OutgoingItem.berat_perintah_kg-OutgoingItem.berat_kg),0)).join(OutgoingRecord).where(OutgoingRecord.status=='perintah',OutgoingItem.item_type=='byproduct_curah',OutgoingItem.jenis_byproduct==row.jenis_produk,OutgoingItem.jasa_id==row.jasa_id,lokasi(OutgoingItem)==wid)))
        from app.services.retur_supplier_stok import keluar_banyak
        retur=await keluar_banyak(db,[f'{row.jenis_produk}:{r.id}' for r in rows]) if row.jasa_id is None else {}
        for r in rows:
            if wh[r.id]['warehouse_id']!=wid:continue
            dipakai=D(await db.scalar(select(func.coalesce(func.sum(BrokenKeSilo.berat_kg),0)).where(BrokenKeSilo.byproduct_stock_id==r.id))) if r.jenis_produk=='broken' else D(await db.scalar(select(func.coalesce(func.sum(HasilSampingKeSilo.berat_kg),0)).where(HasilSampingKeSilo.byproduct_stock_id==r.id)))
            n=max(D(0),D(r.berat_kg)-dipakai-retur.get(f'{r.jenis_produk}:{r.id}',(D(0),0))[0])
            used=min(n,keluar);keluar-=used;n-=used
            held=min(n,pending);pending-=held;n-=held
            n=max(D(0),n-await terikat(db,sumber=f'{r.jenis_produk}:{r.id}'))
            if r.id==row.id:return n
        return D(0)
    if jenis=='gabah':
        if row.status_batch!='baru' or row.dryer_id or row.berat_total_kg is None or row.sumber_berat=='perkiraan':return D(0)
        if await db.scalar(select(SiloStorage.id).where(SiloStorage.purchase_batch_id==row.id).limit(1)):return D(0)
        if await db.scalar(select(DryingLotBatch.id).where(DryingLotBatch.purchase_batch_id==row.id).limit(1)):return D(0)
        if await db.scalar(select(MillingProcess.id).where(MillingProcess.purchase_batch_id==row.id).limit(1)):return D(0)
        if await db.scalar(select(MillingProcessSource.id).where(MillingProcessSource.purchase_batch_id==row.id).limit(1)):return D(0)
        return jumlah(row,jenis)
    if jenis=='gabah_kering':
        if await db.scalar(select(GabahKeringBongkar.id).where(GabahKeringBongkar.gabah_kering_lot_id==row.id).limit(1)):return D(0)
        if await db.scalar(select(OutgoingItem.id).where(OutgoingItem.gabah_kering_lot_id==row.id).limit(1)):return D(0)
        return jumlah(row,jenis)
    if jenis=='pk_tumpukan':
        if row.silo_id or row.tujuan!='ditumpuk' or not row.bobot_final or row.berat_kg is None:return D(0)
        from app.services.pk_persediaan import baca as baca_pk
        s=(await baca_pk(db)).get('tumpukan:'+str(row.id))
        if not s or s.masalah:return D(0)
        n=D(s.bebas(row.jasa_id))
        return jumlah(row,jenis) if n==jumlah(row,jenis) else D(0)
    raise TransferBarangError('Jenis sumber belum dikenali.')


async def sumber(db,*,user,jenis,id,kunci=False,periksa_izin=True):
    await izin(user)
    bagian=str(id).split('~' if jenis in ('pk_giling','pk_tumpukan') else '@');root=bagian[0]
    if jenis not in MODEL or not root.isdigit() or not 1<=int(root)<=2147483647 or len(bagian)>2 or len(bagian)==2 and (jenis not in ('karung','pk_giling','pk_tumpukan') or not bagian[1].isdigit() or not (0 if jenis in ('pk_giling','pk_tumpukan') else 1)<=int(bagian[1])<=2147483647):raise TransferBarangError('Pilih sumber stok yang sah.')
    M=MODEL[jenis];r=await db.get(M,int(root),populate_existing=True,with_for_update=kunci)
    if not r:raise TransferBarangError('Sumber stok tidak ditemukan.')
    if jenis=='barang' and r.curah_kemas_ulang or jenis=='curah_barang' and not r.curah_kemas_ulang:raise TransferBarangError('Bentuk sumber berbeda. Pilih kembali dari stok.')
    wid=int(bagian[1]) if jenis=='karung' and len(bagian)==2 else await db.scalar(select(lokasi(M)).where(M.id==r.id));w=await db.get(Warehouse,wid) if wid else None
    if not w or not w.aktif:raise TransferBarangError('Gudang sumber tidak aktif atau belum dapat dibuktikan.')
    owner=r.pelanggan_id if jenis=='karung' else (int(bagian[1]) or None) if jenis in ('pk_giling','pk_tumpukan') and len(bagian)==2 else r.jasa_id
    if periksa_izin and not can_see_financials(user) and wid!=user.default_warehouse_id and owner is not None:
        raise PermissionError('Barang pelanggan di gudang lain tidak dapat diminta dari gudang kerja ini.')
    from app.services.kepemilikan import pihak
    pemilik=await pihak(db,owner,'karung' if jenis=='karung' else 'barang')
    pelanggan=owner if jenis=='karung' else (await db.get(Jasa,owner)).pelanggan_id if owner else None
    unit='karung' if jenis=='barang' else 'lembar' if jenis=='karung' else 'kg'
    if jenis in ('barang','curah_barang','curah','karung'):
        from app.services.kepemilikan import describe
        from app.services.kepemilikan_detail import identity
        desc=await describe(db,dict(kind=jenis,identity=identity(r,jenis),warehouses=[wid]))
        label=desc['label'];kode=getattr(r,'kode',None) or f'Baris stok #{r.id}'
    else:
        label=('Gabah '+r.kondisi_gabah if jenis=='gabah' else 'Gabah kering' if jenis=='gabah_kering' else 'PK hasil giling' if jenis=='pk_giling' else 'PK tumpukan')
        kode=getattr(r,'kode_proses',None) or getattr(r,'kode_batch',None) or getattr(r,'kode_lot',None) or f'PK #{r.id}'
    if jenis=='pk_tumpukan':
        from app.models import InternalTransfer,PkPurchaseBatch
        if r.internal_transfer_id:
            tr=await db.get(InternalTransfer,r.internal_transfer_id)
            proc=await db.get(MillingProcess,tr.milling_process_id) if tr else None
            if proc:kode=proc.kode_proses+' · '+tr.kode_transfer
        elif r.pk_purchase_batch_id:
            batch=await db.get(PkPurchaseBatch,r.pk_purchase_batch_id)
            if batch:kode=batch.kode_batch
    from app.services.transfer_lokasi import daftar as daftar_lokasi
    metadata=(await daftar_lokasi(db)).get(wid,{})
    if jenis in ('barang','curah_barang','curah') and r.source_type=='polishing' and r.source_id:
        from app.models import PolishingProcess
        proc=await db.get(PolishingProcess,r.source_id)
        if proc:kode=proc.kode_proses+' · baris '+str(r.id)
    if jenis in ('pk_giling','pk_tumpukan'):
        source=(await pk_sumber(db,kunci=kunci)).get(('giling:' if jenis=='pk_giling' else 'tumpukan:')+str(r.id))
        if not source or source.masalah:raise TransferBarangError('Saldo PK lot ini belum dapat dibuktikan.')
        total=source.stok.saldo(source.pemilik(owner)) if jenis=='pk_giling' else jumlah(r,jenis)
        n=D(source.bebas(owner))
        if jenis=='pk_tumpukan' and n!=total:n=D(0)
    else:total=jumlah(r,jenis)
    if jenis=='karung':
        from app.services.transfer_karung_lokasi import bebas as bebas_karung
        total,n=await bebas_karung(db,r,wid)
    elif jenis not in ('pk_giling','pk_tumpukan'):n=await bebas(db,r,jenis)
    return dict(row=r,jenis=jenis,id=str(r.id)+('@'+str(wid) if jenis=='karung' else '~'+str(owner or 0) if jenis in ('pk_giling','pk_tumpukan') else ''),label=label,kode=kode,satuan=unit,asal_id=wid,asal=w.nama_gudang,asal_lokasi=metadata,company_id=metadata.get('company_id'),
        pemilik_id=owner,pelanggan_id=pelanggan,pemilik=pemilik,pemilik_kunci='pelanggan:'+str(pelanggan) if pelanggan else 'pabrik',
        total=total,tersedia=max(D(0),n),berat_kg=berat(r,jenis,n),seluruh=jenis in UTUH)


async def pk_sumber(db,*,kunci=False):
    from app.services.pk_persediaan import baca
    if kunci:return await baca(db)
    if 'transfer_pk_katalog' not in db.info:db.info['transfer_pk_katalog']=await baca(db)
    return db.info['transfer_pk_katalog']


def publik(s):
    return {k:str(v) if isinstance(v,Decimal) else v for k,v in s.items() if k!='row'}


async def pindah(db,*,user,jenis,id,tujuan_id,n):
    """Dipanggil setelah kunci saldo dan permintaan. Satu transaksi pemanggil."""
    if jenis=='pk_giling':raise TransferBarangError('PK hasil giling dicatat melalui permintaan lot yang disetujui.')
    s=await sumber(db,user=user,jenis=jenis,id=id,kunci=True,periksa_izin=False);r=s['row']
    if not can_see_financials(user) and user.default_warehouse_id!=s['asal_id']:raise PermissionError('Hanya operator gudang asal atau Admin yang mencatat transfer.')
    if n>s['tersedia']:raise TransferBarangError('Stok bebas sumber sudah berubah atau tidak cukup. Perbarui status.')
    if s['seluruh'] and (n!=s['total'] or n!=s['tersedia']):raise TransferBarangError('Lot ini harus dipindahkan utuh sebelum dipakai proses atau pengeluaran.')
    from app.services.transfer_lokasi import tujuan_sah
    await tujuan_sah(db,s['asal_id'],tujuan_id)
    w=await db.get(Warehouse,tujuan_id)
    if not w or not w.aktif:raise TransferBarangError('Gudang tujuan tidak aktif.')
    from app.services.kepemilikan import raw
    before=raw(r);kg=berat(r,jenis,n)
    if jenis=='karung':
        return dict(jenis=jenis,sumber_id=r.id,tujuan_id=r.id,asal_warehouse=s['asal_id'],tujuan_warehouse=tujuan_id,
            pemilik_id=s['pemilik_id'],satuan='lembar',jumlah=str(n),berat_kg=None,utuh=False,lokasi_saja=True),None
    if jenis=='barang' and r.warehouse_kemasan_id is None:r.warehouse_kemasan_id=s['asal_id']
    if n==s['total']:
        target=r
    else:
        data={c.name:getattr(r,c.name) for c in r.__table__.columns if c.name not in ('id','created_at','updated_at')}
        # Waktu/aktor penerimaan asli tetap. Waktu dan petugas transfer
        # berada pada transaksi TransferBarang, bukan penerimaan pengganti.
        target=MODEL[jenis](**data);atur(target,jenis,n,kg)
        atur(r,jenis,s['total']-n,D(r.berat_total_kg)-kg if jenis=='barang' else None)
        db.add(target)
    target.warehouse_id=tujuan_id
    if hasattr(target,'waktu_penempatan'):target.waktu_penempatan=now_local()
    await db.flush()
    # Identitas pemilik diperiksa lagi pada kedua pecahan, bukan dipercayakan
    # kepada nilai dari formulir. Tidak ada pemanggilan writer alih milik.
    for part in (r,target):
        if (part.pelanggan_id if jenis=='karung' else part.jasa_id)!=(before['jasa_id'] if jenis=='pk_tumpukan' else s['pemilik_id']):
            raise TransferBarangError('Kepemilikan berubah; transfer dibatalkan.')
    return dict(jenis=jenis,sumber_id=r.id,tujuan_id=target.id,asal_warehouse=s['asal_id'],tujuan_warehouse=tujuan_id,
        pemilik_id=s['pemilik_id'],satuan=s['satuan'],jumlah=str(n),berat_kg=str(kg) if kg is not None else None,
        sumber_before=before,sumber_after=raw(r),tujuan_after=raw(target),utuh=r.id==target.id),kg
