"""Koreksi lokasi pencatatan satu penerimaan; bukan perpindahan fisik.

Sumber stok tetap tabel/pembaca lama. Peristiwa tambah-saja menjadi audit versi,
bukan ledger stok baru. Seluruh perubahan milik transaksi pemanggil.
"""
import hashlib,hmac,json
from datetime import datetime,timezone
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import cast,and_
from sqlalchemy import select,or_,func
from hmu_identitas import peran as P
from app.models import (PurchaseBatch,PkPurchaseBatch,FinishedGoodsStock,ByproductStock,
    Warehouse,Dryer,Silo,DryingLot,DryingLotBatch,SiloStorage,MillingProcess,
    MillingProcessSource,GabahKeringLot,PkGudang2Intake,PkTumpukanToSilo,PolishingProcess,
    PolishingSiloUsage,BrokenKeSilo,BerasKeSilo,OutgoingItem,OutgoingRecord,
    ReturSupplierItem,ReturSupplier,Peristiwa,ActivityLog,LiniProduksi)
from app.services import peristiwa as buku
from app.services.cakupan_fasilitas import lokasi,pilihan_gudang
from app.services.activity_log import log_activity

JENIS='koreksi_gudang_penerimaan'
MODELS={'gabah':PurchaseBatch,'pk':PkPurchaseBatch,'beras':FinishedGoodsStock,'broken':ByproductStock}

class Konflik(ValueError):pass

def izin(user):
    if not user or not P.admin_keatas(user.role):
        raise PermissionError('Koreksi gudang penerimaan memerlukan kewenangan koreksi Admin/Super Admin. Mode lihat sebagai tetap membatasi akses.')

def raw(row):
    return buku.bersih({c.key:(v.astimezone(timezone.utc) if isinstance(v,datetime) and v.tzinfo else v) for c in row.__mapper__.column_attrs for v in [getattr(row,c.key)]})

def sidik(value):return hashlib.sha256(json.dumps(value,sort_keys=True,default=str).encode()).hexdigest()

async def rows(db,model,*where,lock=False):
    q=select(model).where(*where).order_by(model.id).execution_options(populate_existing=True)
    return list((await db.scalars(q.with_for_update() if lock else q)).all())

async def sumber(db,user,tid,kind,id,*,lock=False):
    izin(user)
    model=MODELS.get(kind)
    if model is None:raise ValueError('Jenis penerimaan tidak dikenal.')
    found=await rows(db,model,model.id==id,lock=lock)
    if not found:raise ValueError('Catatan penerimaan tidak ditemukan. Data lama yang sumbernya hilang memerlukan rekonsiliasi.')
    r=found[0]
    linked=r.timbangan_transaksi_id==tid if kind in ('gabah','pk') else r.source_type=='timbangan' and r.source_id==tid
    if not linked:raise PermissionError('Catatan tidak terhubung dengan tiket penerimaan ini.')
    if kind=='broken' and r.jenis_produk!='broken':
        raise ValueError('Catatan ini bukan penerimaan broken.')
    if getattr(r,'dibatalkan_pada',None) or getattr(r,'status_batch','')=='ditolak':
        raise ValueError('Penerimaan dibatalkan/ditolak tidak dapat dikoreksi melalui tindakan ini.')
    wid=await db.scalar(select(lokasi(model)).where(model.id==id))
    if wid is None:raise ValueError('Gudang asal historis belum dapat dibuktikan; perlu rekonsiliasi.')
    return r,wid

async def hubungan(db,r,kind,*,lock=False):
    """Hubungan eksplisit diperiksa utuh, termasuk siklus yang telah dilepas.

    Pengeluaran pool tanpa atribusi sumber menjadi penghalang rekonsiliasi,
    bukan dianggap pemakaian pasti dari baris pertama penerimaan.
    """
    evidence=[];related=[];blockers=[]
    def keep(obj):evidence.append([obj.__tablename__,raw(obj)])
    def block(code,why,url=None):blockers.append(dict(kode=code,alasan=why,url=url))
    async def relation(code,typ,obj,wid,url):
        keep(obj)
        related.append(dict(kode=code,jenis=typ,warehouse_id=wid,url=url,status=getattr(obj,'status',None) or 'tercatat'))
    async def silo_ref(sid,code,obj,url):
        values=await rows(db,Silo,Silo.id==sid,lock=lock)
        silo=values[0] if values else None
        if silo:keep(silo)
        await relation(code,'silo',obj,silo.warehouse_id if silo else None,url)
    async def proc_ref(obj,typ):
        wid=None
        if obj.lini_produksi_id:
            lines=await rows(db,LiniProduksi,LiniProduksi.id==obj.lini_produksi_id,lock=lock)
            if lines:keep(lines[0]);wid=lines[0].warehouse_id
        if isinstance(obj,DryingLot) and obj.dryer_id:
            ds=await rows(db,Dryer,Dryer.id==obj.dryer_id,lock=lock)
            if ds:
                keep(ds[0]);dw=ds[0].warehouse_id
                if wid is not None and wid!=dw:block(obj.kode_lot,'Relasi line dan dryer berbeda gudang. Periksa master alat.')
                wid=dw if wid is None else wid
        if isinstance(obj,MillingProcess) and obj.silo_id:
            ss=await rows(db,Silo,Silo.id==obj.silo_id,lock=lock)
            if ss:
                keep(ss[0]);sw=ss[0].warehouse_id
                if wid is not None and wid!=sw:block(obj.kode_proses,'Relasi line dan silo proses berbeda gudang.')
                wid=sw if wid is None else wid
        if isinstance(obj,PolishingProcess):
            usages=await rows(db,PolishingSiloUsage,PolishingSiloUsage.polishing_process_id==obj.id,lock=lock)
            for usage in usages:keep(usage)
            silos=await rows(db,Silo,Silo.id.in_([u.silo_id for u in usages]),lock=lock)
            for silo in silos:keep(silo)
            locations={x.warehouse_id for x in silos}
            if len(locations)==1:
                sw=next(iter(locations))
                if wid is not None and wid!=sw:block(obj.kode_proses,'Relasi line dan siklus silo berbeda gudang.')
                wid=sw if wid is None else wid
            elif len(locations)>1:block(obj.kode_proses,'Siklus proses historis melintasi beberapa gudang; perlu rekonsiliasi sumber.')
        code=getattr(obj,'kode_proses',None) or obj.kode_lot
        url=f'/riwayat-pengeringan/{obj.id}' if typ=='pengeringan' else f'/riwayat-giling/{obj.id}' if typ=='penggilingan' else f'/riwayat-sosoh/{obj.id}'
        if obj.status=='proses':url=f'/proses-aktif/{"pengeringan" if typ=="pengeringan" else "giling" if typ=="penggilingan" else "sosoh"}/{code}'
        await relation(code,typ,obj,wid,url)
    silo_ids=set();lot_ids=[];proc_ids=set()
    if kind=='gabah':
        if r.dryer_id:
            ds=await rows(db,Dryer,Dryer.id==r.dryer_id,lock=lock)
            if ds:await relation(ds[0].nama,'dryer',ds[0],ds[0].warehouse_id,None)
            else:block(r.kode_batch,'Relasi dryer penerimaan tidak ditemukan.')
        links=await rows(db,DryingLotBatch,DryingLotBatch.purchase_batch_id==r.id,lock=lock)
        for link in links:
            keep(link);lot_ids.append(link.drying_lot_id)
        for lot in await rows(db,DryingLot,DryingLot.id.in_(lot_ids),lock=lock):await proc_ref(lot,'pengeringan')
        storages=await rows(db,SiloStorage,or_(SiloStorage.purchase_batch_id==r.id,SiloStorage.drying_lot_id.in_(lot_ids)),SiloStorage.status!='batal',lock=lock)
        for lot in await rows(db,GabahKeringLot,GabahKeringLot.silo_storage_id.in_([x.id for x in storages]),lock=lock):
            keep(lot);block(lot.kode_lot,'Bahan sudah mempunyai lot keluaran timbang/bongkar tersendiri. Periksa seluruh sumber dan lokasi lot terkait sebelum rekonsiliasi gudang.')
        for st in storages:
            silo_ids.add(st.silo_id)
            if st.milling_process_id:proc_ids.add(st.milling_process_id)
            await silo_ref(st.silo_id,f'Isi silo #{st.id} · {st.status}',st,f'/koreksi-bahan/giling/catatan-{st.id}' if st.status=='terisi' else None)
        src=await rows(db,MillingProcessSource,or_(MillingProcessSource.purchase_batch_id==r.id,MillingProcessSource.drying_lot_id.in_(lot_ids),MillingProcessSource.silo_storage_id.in_([x.id for x in storages])),lock=lock)
        for item in src:keep(item);proc_ids.add(item.milling_process_id)
        for pr in await rows(db,MillingProcess,or_(MillingProcess.id.in_(proc_ids),MillingProcess.purchase_batch_id==r.id,MillingProcess.drying_lot_id.in_(lot_ids)),lock=lock):await proc_ref(pr,'penggilingan')
        if r.status_batch not in ('baru','ditumpuk') and not related:block(r.kode_batch,'Status penerimaan menyatakan penempatan/pemakaian, tetapi rincian sumber tidak lengkap.')
    elif kind=='pk':
        intakes=await rows(db,PkGudang2Intake,PkGudang2Intake.pk_purchase_batch_id==r.id,PkGudang2Intake.dibatalkan_pada.is_(None),lock=lock)
        for it in intakes:
            keep(it)
            if it.silo_id:silo_ids.add(it.silo_id);await silo_ref(it.silo_id,f'Penerimaan PK #{it.id}',it,None)
            elif it.warehouse_id is not None:await relation(f'Penerimaan PK #{it.id}','penerimaan PK',it,it.warehouse_id,None)
        for move in await rows(db,PkTumpukanToSilo,PkTumpukanToSilo.pk_gudang2_intake_id.in_([x.id for x in intakes]),PkTumpukanToSilo.dibatalkan_pada.is_(None),lock=lock):
            silo_ids.add(move.silo_id);await silo_ref(move.silo_id,move.kode_pindah,move,f'/koreksi-catatan/pk-silo/{move.id}')
    elif kind=='broken':
        for move in await rows(db,BrokenKeSilo,BrokenKeSilo.byproduct_stock_id==r.id,BrokenKeSilo.dibatalkan_pada.is_(None),lock=lock):
            silo_ids.add(move.silo_id);await silo_ref(move.silo_id,move.kode_pindah,move,f'/koreksi-catatan/broken-silo/{move.id}')
        from app.models import HasilSampingKeSilo
        for move in await rows(db,HasilSampingKeSilo,HasilSampingKeSilo.byproduct_stock_id==r.id,HasilSampingKeSilo.dibatalkan_pada.is_(None),lock=lock):
            silo_ids.add(move.silo_id);await silo_ref(move.silo_id,move.kode_pindah,move,f'/koreksi-catatan/samping-silo/{move.id}')
    elif kind=='beras':
        for move in await rows(db,BerasKeSilo,or_(and_(BerasKeSilo.source_type=='finished_goods',BerasKeSilo.source_id==r.id),and_(BerasKeSilo.source_type==r.source_type,BerasKeSilo.source_id==r.source_id,BerasKeSilo.product_sku_id==r.product_sku_id,BerasKeSilo.jasa_id==r.jasa_id)),BerasKeSilo.dibatalkan_pada.is_(None),lock=lock):
            silo_ids.add(move.silo_id);await silo_ref(move.silo_id,move.kode_pindah,move,f'/koreksi-catatan/beras-silo/{move.id}')
    if silo_ids and kind!='gabah':
        # Siklus tersimpan diperiksa, termasuk yang telah ditutup. Hubungan
        # lama yang tidak menunjuk siklus dapat menahan, tidak ditebak.
        for usage in await rows(db,PolishingSiloUsage,PolishingSiloUsage.silo_id.in_(silo_ids),lock=lock):
            keep(usage);proc_ids.add(usage.polishing_process_id)
        for pr in await rows(db,PolishingProcess,PolishingProcess.id.in_(proc_ids),lock=lock):await proc_ref(pr,'penyosohan')
    fk={'gabah':'purchase_batch_id','pk':'pk_purchase_batch_id','beras':'finished_goods_stock_id','broken':'byproduct_stock_id'}[kind]
    for item in await rows(db,ReturSupplierItem,getattr(ReturSupplierItem,fk)==r.id,lock=lock):
        keep(item);ret=await db.get(ReturSupplier,item.retur_supplier_id)
        block(ret.kode if ret else f'Retur #{item.retur_supplier_id}','Penerimaan mempunyai catatan retur terkait. Periksa alokasi/pembalikan dan dokumen retur sebelum mengoreksi gudang.',f'/retur-supplier/{item.retur_supplier_id}')
    # Pool pengiriman lama tidak menyimpan FK baris penerimaan. Saldo
    # gabungan yang cukup bukan bukti bahwa sumber ini belum dipakai.
    if kind in ('pk','beras','broken'):
        conditions=[OutgoingItem.jasa_id==r.jasa_id]
        if kind=='pk':conditions.append(OutgoingItem.item_type=='pk_g2')
        elif kind=='beras':conditions.extend([OutgoingItem.item_type=='finished_goods',OutgoingItem.product_sku_id==r.product_sku_id,OutgoingItem.rice_quality_standard_id==r.rice_quality_standard_id])
        else:conditions.extend([OutgoingItem.item_type=='byproduct_curah',OutgoingItem.jenis_byproduct==r.jenis_produk])
        items=await rows(db,OutgoingItem,*conditions,lock=lock)
        for item in items:
            rec=await db.get(OutgoingRecord,item.outgoing_record_id,populate_existing=True)
            if rec and rec.status!='batal':
                keep(item);keep(rec);block(rec.kode,'Alokasi/muatan dari pool ini belum menunjuk satu baris penerimaan secara pasti. Periksa sumber pengiriman; saldo gabungan tidak cukup sebagai bukti.',f'/barang-keluar/{rec.id}')
    if kind in ('beras','broken'):
        pool_kind='barang' if kind=='beras' else 'curah'
        payload=cast(Peristiwa.muatan,JSONB)
        ownership=await rows(db,Peristiwa,Peristiwa.jenis=='pindah_kepemilikan_rinci',Peristiwa.muatan['kind'].as_string()==pool_kind,
            or_(payload['lines'].contains([{'source_id':r.id}]),payload['lines'].contains([{'target_id':r.id}])),lock=lock)
        for event in ownership:
            keep(event);block(f'Perpindahan kepemilikan #{event.id}','Sumber/pecahan penerimaan terhubung dengan perpindahan kepemilikan. Periksa seluruh baris asal dan tujuan sebelum merekonsiliasi gudang.')
        if kind=='beras':
            from app.models.kemas_ulang import KemasUlang
            for item in await rows(db,KemasUlang,KemasUlang.sumber_id.in_([x.id for x in await rows(db,FinishedGoodsStock,FinishedGoodsStock.source_type==r.source_type,FinishedGoodsStock.source_id==r.source_id,lock=lock)]),lock=lock):
                keep(item);block(f'Kemas ulang #{item.id}','Sumber sudah dipecah melalui kemas ulang. Gudang tidak boleh dikoreksi hanya pada satu pecahan.')
            siblings=await rows(db,FinishedGoodsStock,FinishedGoodsStock.source_type=='timbangan',FinishedGoodsStock.source_id==r.source_id,FinishedGoodsStock.id!=r.id,lock=lock)
            if siblings and related:block(f'Tiket #{r.source_id}','Tiket memiliki beberapa baris produk/pecahan. Bukti atribusi lokasi per baris harus direkonsiliasi; jangan mengubah salah satu pecahan saja.')
        # Pemecahan kepemilikan/kemas ulang dapat menyisakan baris penerimaan
        # dengan angka efektif berbeda. Jangan memindahkan baris pertama saja.
        audits=await rows(db,ActivityLog,ActivityLog.table_name==r.__tablename__,ActivityLog.record_id==r.id,ActivityLog.aksi.is_not(None),ActivityLog.aksi!=JENIS,lock=lock)
        for log in audits:
            if any(word in log.aksi for word in ('kepemilikan','kemas','packing','pindah')):
                keep(log);block(f'Audit #{log.id}','Sumber memiliki pemecahan/pemakaian kemasan atau kepemilikan. Rincian sumber perlu direkonsiliasi sebelum koreksi gudang.')
    return evidence,related,blockers

async def konteks(db,*,user,tid,kind,id,lock=False):
    r,wid=await sumber(db,user,tid,kind,id,lock=lock)
    wh=await pilihan_gudang(db,user)
    old=await db.get(Warehouse,wid,populate_existing=True)
    if not old:raise ValueError('Gudang asal tidak ditemukan.')
    evidence,related,blocks=await hubungan(db,r,kind,lock=lock)
    hist=await rows(db,Peristiwa,Peristiwa.jenis==JENIS,Peristiwa.muatan['sumber'].as_string()==f'{kind}:{id}')
    facts=[raw(r),raw(old),[raw(w) for w in wh],evidence,[x.id for x in hist]]
    result=dict(tiket_id=tid,sumber=f'{kind}:{id}',kode=getattr(r,'kode_batch',None) or f'{kind.upper()} #{id}',
        gudang_id=wid,gudang=old.nama_gudang,warehouse_id_tersimpan=r.warehouse_id,
        pilihan=[dict(value=w.id,label=w.nama_gudang) for w in wh],
        bobot=getattr(r,'berat_total_kg',getattr(r,'berat_kg',None)),karung=getattr(r,'jumlah_karung',None),jasa_id=r.jasa_id,
        versi=1+len(hist),relasi=related,penghalang=blocks,
        riwayat=[dict(id=x.id,waktu=x.waktu,petugas_id=x.pelaku_id,**x.muatan) for x in hist])
    result['dasar']=sidik(facts)
    return buku.bersih(result)

async def rencana(db,*,user,tid,kind,id,req,lock=False):
    ctx=await konteks(db,user=user,tid=tid,kind=kind,id=id,lock=lock)
    if ctx['dasar']!=req['dasar']:raise Konflik('Saldo, gudang, relasi, atau versi berubah. Isian tetap tersedia; baca data terbaru dan periksa ulang.')
    if not req['alasan'].strip():raise ValueError('Alasan koreksi wajib diisi.')
    dest=next((w for w in ctx['pilihan'] if w['value']==req['warehouse_id']),None)
    if not dest:raise PermissionError('Gudang tujuan tidak aktif atau di luar kewenangan koreksi.')
    if dest['value']==ctx['gudang_id']:raise ValueError('Gudang yang dipilih sama dengan gudang efektif saat ini.')
    blocked=list(ctx['penghalang'])
    for rel in ctx['relasi']:
        if rel['warehouse_id']!=dest['value']:
            blocked.append(dict(kode=rel['kode'],url=rel['url'],alasan='Gudang silo/alat/proses terkait berbeda dari tujuan koreksi. Periksa penempatan/proses terkait atau gunakan alur perpindahan fisik yang sah.' if rel['warehouse_id'] is not None else 'Lokasi relasi historis belum dapat dibuktikan. Perlu rekonsiliasi.'))
    return dict(sumber=ctx['sumber'],kode=ctx['kode'],tiket_id=tid,dasar=ctx['dasar'],
        sebelum=dict(warehouse_id=ctx['gudang_id'],gudang=ctx['gudang'],versi=ctx['versi']),
        sesudah=dict(warehouse_id=dest['value'],gudang=dest['label'],versi=ctx['versi']+1),
        bobot=ctx['bobot'],karung=ctx['karung'],jasa_id=ctx['jasa_id'],alasan=req['alasan'].strip(),
        relasi=ctx['relasi'],penghalang=blocked,boleh_simpan=not blocked,
        dampak='Hanya lokasi pencatatan penerimaan. Bobot, pemilik, silo, hasil, tiket timbang, dan QC tidak diubah.',
        isian_warehouse_id_sebelum=ctx['warehouse_id_tersimpan'])

def cap(user,plan,key):
    from app.web.security import _kunci
    return hmac.new(_kunci(),json.dumps([user.id,user.role,user.default_warehouse_id,key,plan],sort_keys=True,default=str).encode(),hashlib.sha256).hexdigest()

async def periksa(db,**kw):
    plan=await rencana(db,**kw)
    return dict(rencana=plan,pemeriksaan=cap(kw['user'],plan,kw['req']['kunci']))

async def simpan(db,*,user,tid,kind,id,req):
    izin(user)
    from app.services.barang_keluar import _kunci_saldo_keluar
    await _kunci_saldo_keluar(db)
    await rows(db,Warehouse,lock=True)
    key=f'{JENIS}:{user.id}:{req["kunci"]}'
    old=await db.scalar(select(Peristiwa).where(Peristiwa.kunci_kiriman==key))
    isian=buku.bersih(dict(tid=tid,kind=kind,id=id,warehouse_id=req['warehouse_id'],alasan=req['alasan'].strip()))
    if old:
        await sumber(db,user,tid,kind,id)
        if old.muatan['isian']!=isian:raise Konflik('Kunci ini sudah dipakai untuk isian berbeda. Periksa hasil tersimpan.')
        return dict(tercatat=True,sudah_tercatat=True,peristiwa_id=old.id,hasil=old.muatan['hasil'])
    plan=await rencana(db,user=user,tid=tid,kind=kind,id=id,req=req,lock=True)
    if not plan['boleh_simpan']:raise Konflik('Koreksi ditahan oleh catatan terkait; periksa rincian penghalang sebelum menyimpan.')
    if not req.get('konfirmasi') or not hmac.compare_digest(req.get('pemeriksaan',''),cap(user,plan,req['kunci'])):
        raise Konflik('Periksa dampak terbaru dan konfirmasikan sebelum menyimpan.')
    r,_=await sumber(db,user,tid,kind,id,lock=True)
    before=raw(r)
    r.warehouse_id=req['warehouse_id'];await db.flush();await db.refresh(r)
    # Satu kolom efektif diubah. Angka historis lain tidak disentuh.
    after=raw(r)
    event=await buku.catat(db,jenis=JENIS,pelaku_id=user.id,kunci_kiriman=key,terapkan=False,
        muatan=dict(sumber=f'{kind}:{id}',isian=isian,sebelum=before,sesudah=after,hasil=plan))
    tags={w.kode_fungsi for w in (await db.scalars(select(Warehouse).where(Warehouse.id.in_([plan['sebelum']['warehouse_id'],r.warehouse_id])))).all() if w.kode_fungsi and len(w.kode_fungsi)<=2}
    for tag in sorted(tags) or ['']:
        await log_activity(db,table_name=r.__tablename__,record_id=r.id,action='UPDATE',changed_by=user.id,
            field_name='warehouse_id',old_value=str(plan['sebelum']['warehouse_id']),new_value=str(r.warehouse_id),
            alasan=req['alasan'].strip()+f' · operasi #{event.id}',aksi=JENIS,gudang=tag)
    return dict(tercatat=True,sudah_tercatat=False,peristiwa_id=event.id,hasil=plan)

async def terapkan_peristiwa(db,event):
    """Replay hanya memperbarui lokasi efektif; tidak membukukan stok kedua."""
    data=event.muatan;kind,id=data['sumber'].split(':');model=MODELS[kind]
    row=await db.get(model,int(id))
    if row:row.warehouse_id=data['sesudah']['warehouse_id']
