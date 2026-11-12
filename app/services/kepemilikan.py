"""Koreksi per transaksi atas baris persediaan lama; peristiwa tambah-saja.

Tidak ada pool stok tandingan. Saldo tetap dibaca dari layanan inventory lama.
Peristiwa menyimpan semua pecahan sumber dan versi; saldo ditulis atomik oleh
pemanggil. Histori sebelum rincian ini tersedia sengaja tidak direkonstruksi.
"""
from __future__ import annotations
import copy,hashlib,hmac,json,math,uuid
from decimal import Decimal,ROUND_HALF_UP
from datetime import datetime,timezone
from sqlalchemy import Numeric
from sqlalchemy import select,func,or_
from app.database import now_local
from app.config import settings
from app.models import (Peristiwa,ActivityLog,User,Jasa,Pelanggan,Warehouse,
    FinishedGoodsStock,ByproductStock,PackagingPurchase,PackagingLoss,ProductSku,
    OutgoingItem,OutgoingRecord,BrokenKeSilo,PolishingProcess)
from app.peran import can_see_financials,user_wh_scope
from app.penggilingan.inventory.finished_goods import InventoryError
from app.services.activity_log import log_activity
from app.performa import baca_sekali

AWAL='pindah_kepemilikan_rinci'
UBAH='koreksi_kepemilikan_rinci'
MODELS={'barang':FinishedGoodsStock,'curah':ByproductStock,'curah_barang':FinishedGoodsStock,'karung':PackagingPurchase}
AKSI={'barang':'pindah_kepemilikan_produk','curah':'pindah_kepemilikan_produk','curah_barang':'pindah_kepemilikan_produk','karung':'pindah_kepemilikan_karung'}
D=lambda x:Decimal(str(x))
CURAH=('curah','curah_barang')

def raw(row):
    def val(v,c):
        if v is not None and isinstance(c.type,Numeric):return format(D(v).normalize(),'f')
        if isinstance(v,Decimal):return format(v.normalize(),'f')
        if isinstance(v,datetime):return v.astimezone(timezone.utc).isoformat() if v.tzinfo else v.isoformat()
        if hasattr(v,'isoformat'):return v.isoformat()
        return v
    return {c.name:val(getattr(row,c.name),c) for c in row.__table__.columns if c.name not in ('created_at','updated_at')}

def owner(row,kind):return row.pelanggan_id if kind=='karung' else row.jasa_id

def qty(row,kind):return D(row.jumlah_lembar if kind=='karung' else row.jumlah_karung if kind=='barang' else row.berat_total_kg if kind=='curah_barang' else row.berat_kg)
def kg(row,kind):return None if kind=='karung' else D(row.berat_total_kg if kind=='barang' else row.berat_total_kg if kind=='curah_barang' else row.berat_kg)
def set_qty(row,kind,n,w=None):
    if kind=='karung':row.jumlah_lembar=int(n)
    elif kind=='barang':row.jumlah_karung=int(n);row.berat_total_kg=w
    elif kind=='curah_barang':row.berat_total_kg=n
    else:row.berat_kg=n

def set_owner(row,kind,value):
    if kind=='karung':row.pelanggan_id=value
    else:row.jasa_id=value

def fingerprint(data):return hashlib.sha256(json.dumps(data,sort_keys=True,default=str,separators=(',',':')).encode()).hexdigest()
def sign(data):return hmac.new(settings.secret_key.encode(),fingerprint(data).encode(),hashlib.sha256).hexdigest()

async def izin(db,user,warehouses=()):
    if not user or user.status!='aktif' or not can_see_financials(user):raise PermissionError('Koreksi kepemilikan hanya tersedia bagi peran yang berwenang.')
    scope=await user_wh_scope(db,user)
    if scope=='none':raise PermissionError('Gudang efektif tidak mengizinkan akses kepemilikan.')
    if scope!='all':
        for wid in warehouses:
            wh=await db.get(Warehouse,wid)
            wanted=getattr(wh,'kode_fungsi',None)
            if wanted!=scope:raise PermissionError('Sumber berada di luar gudang efektif.')

async def lock(db):
    from app.services.barang_keluar import _kunci_saldo_keluar
    await _kunci_saldo_keluar(db)

async def pihak(db,ident,kind):
    if ident is None:return 'Pabrik'
    if kind=='karung':p=await db.get(Pelanggan,ident)
    else:
        j=await db.get(Jasa,ident)
        if not j:raise InventoryError('Pesanan sumber tidak ditemukan.')
        p=await db.get(Pelanggan,j.pelanggan_id)
    if not p:raise InventoryError('Pelanggan sumber tidak ditemukan.')
    return p.nama_pelanggan+(' · '+j.kode if kind!='karung' else '')

async def pelanggan_ids(db,kind,ids):
    values={x for x in ids if x is not None}
    if kind=='karung':return values
    return set((await db.scalars(select(Jasa.pelanggan_id).where(Jasa.id.in_(values)))).all()) if values else set()

def conditions(kind,identity):
    M=MODELS[kind]
    if kind in ('barang','curah_barang'):return [M.product_sku_id==identity['sku'],M.rice_quality_standard_id==identity['std'],M.curah_kemas_ulang.is_(kind=='curah_barang')]
    if kind=='curah':return [M.jenis_produk==identity['jenis']]
    return [M.packaging_material_id==identity['material'],M.package_size_id==identity['size'],M.brand_id==identity['brand']]

async def balance(db,kind,identity,ident):
    from app.penggilingan.inventory import finished_goods as fg,packaging as pk
    if kind=='barang':return await fg.hitung_stok_finished_goods(db,identity['sku'],identity['std'],jasa_id=ident)
    if kind=='curah_barang':
        rows=(await db.scalars(select(MODELS[kind]).where(*conditions(kind,identity),FinishedGoodsStock.jasa_id==ident))).all()
        return {'kg':sum((max(D(0),kg(r,kind)-D(r.retur_supplier_keluar_kg)) for r in rows),D(0))}
    if kind=='curah':return {'kg':await fg.hitung_stok_byproduct_curah(db,identity['jenis'],jasa_id=ident)}
    return {'lembar':await pk.hitung_stok_kemasan(db,identity['material'],identity['size'],identity['brand'],pelanggan_id=ident)}

async def physical(db,kind,identity):
    M=MODELS[kind]
    if kind=='barang':cols=[func.coalesce(func.sum(M.jumlah_karung),0),func.coalesce(func.sum(M.berat_total_kg),0)]
    elif kind=='curah_barang':cols=[func.coalesce(func.sum(M.berat_total_kg),0)]
    elif kind=='curah':cols=[func.coalesce(func.sum(M.berat_kg),0)]
    else:cols=[func.coalesce(func.sum(M.jumlah_lembar),0)]
    return [str(x) for x in (await db.execute(select(*cols).where(*conditions(kind,identity)))).one()]

@baca_sekali
async def pemakaian_karung_asli(db):
    """Payer kemasan tetap, hanya dari bukti rinci perpindahan baru.

    Koreksi memakai versi efektif; pembatalan nol tidak menambah lembar.
    Hasil dibaca sekali per GET dan tidak membukukan pemakaian baru.
    """
    from sqlalchemy.orm import aliased
    from sqlalchemy.dialects.postgresql import JSONB
    R=aliased(Peristiwa)
    effective=func.coalesce(select(R.muatan['after']).where(R.jenis==UBAH,R.muatan['root_id'].as_integer()==Peristiwa.id).order_by(R.id.desc()).limit(1).correlate(Peristiwa).scalar_subquery(),Peristiwa.muatan).cast(JSONB)
    states=list((await db.scalars(select(effective).where(Peristiwa.jenis==AWAL,Peristiwa.muatan['kind'].as_string()=='barang',Peristiwa.muatan['detail'].as_boolean().is_(True)))).all())
    if not states:return {}
    skus={x.id:x for x in (await db.scalars(select(ProductSku).where(ProductSku.id.in_({v['identity']['sku'] for v in states})))).all()}
    owners={v.get('customer') for v in states}|{line['source_owner'] for v in states for line in v['lines']}
    contacts=dict((await db.execute(select(Jasa.id,Jasa.pelanggan_id).where(Jasa.id.in_(owners-{None})))).all())
    result={}
    for state in states:
        sku=skus[state['identity']['sku']]
        for line in state['lines']:
            if not line['source_before'].get('kemasan_mengurangi_stok') or D(line['quantity'])<=0:continue
            for who,signum in [(line['source_owner'],1),(state.get('customer'),-1)]:
                key=(sku.packaging_material_id,sku.package_size_id,sku.brand_id,contacts.get(who) if who is not None else None)
                result[key]=result.get(key,D(0))+D(line['quantity'])*signum
    return result

async def free_rows(db,kind,identity,ident,*,allocating=False):
    """Bukti ketersediaan per sumber, bukan sekadar saldo pemilik gabungan."""
    M=MODELS[kind];col=M.pelanggan_id if kind=='karung' else M.jasa_id
    rows=list((await db.scalars(select(M).where(*conditions(kind,identity),col==ident).order_by(*([M.tanggal,M.waktu,M.id] if kind=='karung' else [M.waktu,M.id])))).all())
    if kind=='barang':
        from app.penggilingan.gudang2.rencana_beras import sumber_karung_beras
        available,_=await sumber_karung_beras(db,identity['sku'],identity['std'],ident)
        by={r.id:D(n) for r,n,_ in available}
        return [(r,max(D(0),by.get(r.id,D(0)))) for r in rows]
    if kind=='curah_barang':
        from app.services.retur_supplier_reservasi import terikat
        return [(r,max(D(0),kg(r,kind)-D(r.retur_supplier_keluar_kg)-await terikat(db,sumber=f'beras:{r.id}'))) for r in rows]
    if kind=='curah':
        from app.services.retur_supplier_reservasi import terikat
        from app.penggilingan.gudang2 import service as g2
        if identity['jenis']=='broken':
            return [(r,max(D(0),D(await g2._sisa_broken_row(db,r.id))-await terikat(db,sumber=f'broken:{r.id}'))) for r in rows]
        # Bekatul outgoing is pooled. FIFO consumes the same ordered source rows;
        # no inference from the owner's remaining combined balance alone.
        outgoing=D(await db.scalar(select(func.coalesce(func.sum(OutgoingItem.berat_kg),0)).where(OutgoingItem.item_type=='byproduct_curah',OutgoingItem.jenis_byproduct==identity['jenis'],OutgoingItem.jasa_id==ident)))
        from app.services.retur_supplier_stok import keluar_banyak
        returns=await keluar_banyak(db,[f"{identity['jenis']}:{r.id}" for r in rows]) if ident is None else {}
        result=[]
        for r in rows:
            n=max(D(0),qty(r,kind)-returns.get(f"{identity['jenis']}:{r.id}",(D(0),0))[0]);used=min(n,outgoing);outgoing-=used
            result.append((r,max(D(0),n-used-await terikat(db,sumber=f"{identity['jenis']}:{r.id}"))))
        return result
    # Karung kosong has no persisted purchase -> packing allocation. Once
    # any packaging is consumed from this account, a particular purchase
    # cannot be declared free from its aggregated balance. Keep it blocked.
    total=sum((qty(r,kind) for r in rows),D(0));saldo=D((await balance(db,kind,identity,ident))['lembar'])
    if saldo<total:
        if not allocating:return [(r,D(0)) for r in rows]
        used=max(D(0),total-saldo);result=[]
        for r in rows:
            take=min(qty(r,kind),used);used-=take;result.append((r,qty(r,kind)-take))
        return result
    return [(r,qty(r,kind)) for r in rows]

async def warehouse_ids(db,kind,identity,rows):
    if kind!='karung':
        from app.services.cakupan_fasilitas import lokasi_banyak
        found=await lokasi_banyak(db,MODELS[kind],[r.id for r in rows])
        return sorted({x['warehouse_id'] for x in found.values() if x['warehouse_id']})
    from app.penggilingan.inventory.packaging import kemasan_gudang
    from hmu_core import PackagingMaterial
    material=await db.get(PackagingMaterial,identity['material'])
    name=kemasan_gudang(material.kode if material else None)
    ids=list((await db.scalars(select(Warehouse.id).where(Warehouse.kode_fungsi==('g1' if name=='Gudang 1' else 'g2')))).all())
    return ids

async def clone_part(db,row,kind,n,w,new_owner,user):
    data={c.name:getattr(row,c.name) for c in row.__table__.columns if c.name not in ('id','created_at','updated_at')}
    data.update(waktu=now_local(),input_by=user.id)
    if kind=='karung':
        from app.services.codegen import next_packaging_purchase_code
        data['kode']=await next_packaging_purchase_code(db,now_local().date());data['tanggal']=now_local().date();data.pop('harga_per_lembar',None)
    created=MODELS[kind](**data);set_qty(created,kind,n,w);set_owner(created,kind,new_owner);db.add(created);await db.flush();return created

async def free_guard(db,kind,identity,ident,*,detail=False,allocating=False):
    if detail:
        from app.services.kepemilikan_detail import bagian_bebas
        return await bagian_bebas(db,kind,identity,ident)
    return await free_rows(db,kind,identity,ident,allocating=allocating)

async def allocate(db,kind,identity,owners,amount,dest,user,*,source_ids=None,detail=False):
    """One FIFO stock writer shared by initial transfer and later adjustment."""
    from app.penggilingan.gudang2.rencana_beras import berat_karung_nyata
    candidates=[]
    for ident in owners:candidates.extend(await free_guard(db,kind,identity,ident,allocating=True,detail=detail))
    ids=sorted({r.id for r,_ in candidates})
    if ids:await db.scalars(select(MODELS[kind]).where(MODELS[kind].id.in_(ids)).order_by(MODELS[kind].id).with_for_update().execution_options(populate_existing=True))
    candidates=[]
    for ident in owners:candidates.extend(await free_guard(db,kind,identity,ident,allocating=True,detail=detail))
    candidates.sort(key=lambda x:(x[0].tanggal,x[0].waktu,x[0].id) if kind=='karung' else (x[0].waktu,x[0].id))
    if source_ids is not None:candidates=[(r,n) for r,n in candidates if r.id in source_ids]
    left=amount;lines=[]
    for r,available in candidates:
        if left<=0:break
        take=min(left,available)
        if take<=0:continue
        await db.refresh(r,with_for_update=True)
        # Snapshot of every original row; actual kg rounded by the old helper.
        before=raw(r);original_owner=owner(r,kind)
        weight=berat_karung_nyata(r,int(take)) if kind=='barang' else take if kind in CURAH else None
        if take==qty(r,kind):set_owner(r,kind,dest);target=r
        else:
            target=await clone_part(db,r,kind,take,weight,dest,user)
            set_qty(r,kind,qty(r,kind)-take,None if kind=='karung' else kg(r,kind)-weight)
        await db.flush()
        lines.append(dict(source_id=r.id,target_id=target.id,source_owner=original_owner,quantity=str(take),kg=None if weight is None else str(weight),source_before=before,source_after=raw(r),target=raw(target)))
        left-=take
    if left>0:raise InventoryError('Sumber bebas yang dapat ditelusuri tidak cukup. Periksa pemakaian, alokasi, dan baris sumber; transaksi lain tidak diambil.')
    return lines

def audit_summary(state):
    if state['kind']=='pk':
        tujuan=state.get('parties',{}).get(str(state.get('customer')),'Pabrik')
        return str(state['quantity'])+' kg PK → '+tujuan
    kind=state['kind'];n=format(D(state['quantity']).normalize(),'f')
    if state.get('detail'):return n+(' lembar' if kind=='karung' else ' karung' if kind=='barang' else ' kg')+' → '+state.get('parties',{}).get(str(state.get('customer')),'Pabrik')
    if kind=='karung':return n+' lembar → pelanggan'
    weight=format(D(state['kg']).normalize(),'f')
    return (n+' karung ('+weight+'kg)' if kind=='barang' else weight+' kg')+' → pabrik'

async def audit(db,user,kind,root_id,before,after,reason,aksi):
    ids=await pelanggan_ids(db,kind,{x['source_owner'] for x in after.get('lines',[])}|{after.get('customer')}|{x['source_owner'] for x in before.get('lines',[])})
    changed_party=bool(before) and (before.get('owners')!=after.get('owners') or before.get('customer')!=after.get('customer'))
    old_summary='Kepemilikan sebelum koreksi' if changed_party else audit_summary(before) if before else None
    new_summary='Koreksi pemilik tercatat; rincian sumber tersimpan pada transaksi kepemilikan.' if changed_party else audit_summary(after)
    await log_activity(db,table_name='peristiwa',record_id=root_id,action='UPDATE' if before else 'INSERT',changed_by=user.id,field_name='kepemilikan',old_value=old_summary,new_value=new_summary,alasan=reason,aksi=aksi,gudang=after.get('warehouse_scope'),pelanggan_ids=ids)

async def initial(db,*,user,kind,identity,owners,amount,customer=None,commit=True,key=None,source_ids=None,from_detail=False,note='',return_event=False):
    await lock(db);await db.flush()
    amount=D(amount)
    if not amount.is_finite() or amount<=0 or kind not in CURAH and amount!=amount.to_integral_value():raise InventoryError('Jumlah harus positif; karung dan lembar harus bilangan bulat.')
    if kind in CURAH and amount!=amount.quantize(D('.01')):raise InventoryError('Bobot mengikuti presisi penyimpanan dua desimal kg.')
    if from_detail:
        await izin(db,user)
        if not source_ids or len(owners)!=1 or owners[0]==customer:raise InventoryError('Pilih satu sumber dan pemilik tujuan yang berbeda.')
        for who in set(owners)|{customer}:await pihak(db,who,kind)
    elif kind=='karung':
        if not customer:raise InventoryError('Sebutkan pelanggan tujuan.')
        await pihak(db,customer,kind)
    else:
        for oid in owners:
            if oid is None:raise InventoryError('Barang pabrik tidak dipindahkan ke pabrik lagi.')
            await pihak(db,oid,kind)
        if len(owners)>1 and len(await pelanggan_ids(db,kind,set(owners)))!=1:raise InventoryError('Pesanan sumber harus milik pelanggan yang sama.')
    # Same public balance validation as the old services.
    balances=[await balance(db,kind,identity,o) for o in owners]
    total=sum((D(b['lembar' if kind=='karung' else 'karung' if kind=='barang' else 'kg']) for b in balances),D(0))
    if amount>total:raise InventoryError(f'Sisa sumber tinggal {total} '+('lembar' if kind=='karung' else 'karung' if kind=='barang' else 'kg')+'.')
    original=await physical(db,kind,identity)
    lines=await allocate(db,kind,identity,owners,amount,customer if (kind=='karung' or from_detail) else None,user,source_ids=source_ids,detail=from_detail)
    rows=[await db.get(MODELS[kind],x['target_id']) for x in lines]
    warehouses=await warehouse_ids(db,kind,identity,rows)
    scopes={getattr(await db.get(Warehouse,w),'kode_fungsi',None) for w in warehouses};warehouse_scope=next(iter(scopes)) if len(scopes)==1 else None
    state=dict(detail=from_detail,note=note,bound_source_ids=source_ids or [],warehouse_scope=warehouse_scope,parties={str(o):await pihak(db,o,kind) for o in set(owners)|{customer,None}},kind=kind,identity=identity,owners=owners,customer=customer,warehouses=warehouses,lines=lines,quantity=str(amount),kg=None if kind=='karung' else str(sum((D(x['kg']) for x in lines),D(0))),version=0,status='aktif')
    if original!=await physical(db,kind,identity):raise InventoryError('Konservasi stok fisik gagal; seluruh perubahan harus dibatalkan.')
    event=Peristiwa(jenis=AWAL,pelaku_id=user.id,kunci_kiriman=key or 'kepemilikan:'+uuid.uuid4().hex,muatan=state);db.add(event);await db.flush()
    await audit(db,user,kind,event.id,{},state,note or 'Pencatatan perpindahan baru',AKSI[kind])
    if commit:await db.commit()
    if return_event:return event
    return amount if kind=='karung' else D(state['kg'])

async def root_state(db,ident,*,locked=False):
    event=await db.scalar(select(Peristiwa).where(Peristiwa.id==ident,Peristiwa.jenis==AWAL).with_for_update() if locked else select(Peristiwa).where(Peristiwa.id==ident,Peristiwa.jenis==AWAL))
    if not event:raise InventoryError('Transaksi perpindahan tidak ditemukan.')
    latest=await db.scalar(select(Peristiwa).where(Peristiwa.jenis==UBAH,Peristiwa.muatan['root_id'].as_integer()==ident).order_by(Peristiwa.id.desc()).limit(1))
    return event,copy.deepcopy(latest.muatan['after'] if latest else event.muatan),latest

async def evidence(db,state,selected=()):
    kind=state['kind'];M=MODELS[kind];identity=state['identity'];target_owner=state.get('customer')
    free={r.id:n for r,n in await free_guard(db,kind,identity,target_owner,detail=state.get('detail',False))}
    facts=[]
    for line in state['lines']:
        r=await db.get(M,line['target_id'],populate_existing=True)
        facts.append(dict(id=line['target_id'],row=raw(r) if r else None,free=str(free.get(line['target_id'],D(0)))))
    source=[]
    for rid in sorted(set(selected)):
        r=await db.get(M,rid,populate_existing=True)
        if not r or any(getattr(r,k)!=v for k,v in ({'product_sku_id':identity['sku'],'rice_quality_standard_id':identity['std'],'curah_kemas_ulang':False} if kind=='barang' else {'product_sku_id':identity['sku'],'rice_quality_standard_id':identity['std'],'curah_kemas_ulang':True} if kind=='curah_barang' else {'jenis_produk':identity['jenis']} if kind=='curah' else {'packaging_material_id':identity['material'],'package_size_id':identity['size'],'brand_id':identity['brand']}).items()):raise InventoryError('Jenis, SKU, mutu, atau kemasan sumber pengganti tidak sesuai transaksi asal.')
        wh=await warehouse_ids(db,kind,identity,[r])
        if kind!='karung' and set(wh)-set(state['warehouses']):raise InventoryError('Lokasi sumber pengganti harus sesuai transaksi asal.')
        who=owner(r,kind)
        if kind!='karung' and who is None and not state.get('detail'):raise InventoryError('Sumber pengganti harus milik pesanan jasa, bukan stok pabrik.')
        availability={x.id:n for x,n in await free_guard(db,kind,identity,who,allocating=True,detail=state.get('detail',False))}
        source.append(dict(id=rid,row=raw(r),free=str(availability.get(rid,D(0)))))
    owners=set(state['owners'])|({state['customer']} if state.get('customer') else set())
    balances={str(o):await balance(db,kind,identity,o) for o in owners|{None}}
    return dict(state=state,targets=facts,sources=source,balances=balances,physical=await physical(db,kind,identity))

async def context(db,*,user,ident,selected=()):
    await izin(db,user)
    event,state,last=await root_state(db,ident)
    if state['kind']=='pk':
        from app.services.pk_kepemilikan import context as pk_context
        return await pk_context(db,user=user,ident=ident)
    await izin(db,user,state['warehouses'])
    facts=await evidence(db,state,selected)
    names={str(o):await pihak(db,o,state['kind']) for o in set(state['owners'])|{state.get('customer'),None}}
    actor=await db.get(User,event.pelaku_id) if event.pelaku_id else None
    rows=[];available=D(0);unknown=False
    packaging_unproven=False
    if state['kind']=='karung':
        M=MODELS['karung'];total=await db.scalar(select(func.coalesce(func.sum(M.jumlah_lembar),0)).where(*conditions('karung',state['identity']),M.pelanggan_id==state['customer']))
        packaging_unproven=D(facts['balances'][str(state['customer'])]['lembar'])<D(total)
    for line,f in zip(state['lines'],facts['targets']):
        n=D(line['quantity']);free=min(n,D(f['free']))
        valid=f['row']==line['target']
        # A source row touched by another stock operation cannot be silently
        # reconstructed from this account's aggregate balance.
        known=valid and not packaging_unproven
        if not known:unknown=True
        available+=free if known else D(0)
        r=await db.get(MODELS[state['kind']],line['target_id'])
        obstacle=await blocker(db,state,r) if r and (not known or free<n) and n else None
        rows.append(dict(**line,free=str(free) if known else None,used=str(max(D(0),n-free)) if known else None,consistent=valid,availability_known=known,blocker=obstacle))
    history=list((await db.scalars(select(Peristiwa).where(Peristiwa.jenis==UBAH,Peristiwa.muatan['root_id'].as_integer()==ident).order_by(Peristiwa.id))).all())
    actors={u.id:u.nama for u in (await db.scalars(select(User).where(User.id.in_({e.pelaku_id for e in history if e.pelaku_id})))).all()}
    logs=[dict(id=e.id,actor=actors.get(e.pelaku_id,'Tidak tersedia'),time=e.waktu.isoformat(),reason=e.muatan['request']['reason'],before=e.muatan['before'],after=e.muatan['after']) for e in history]
    description=await describe(db,state)
    return dict(description=description,id=ident,code=('AM-KRG-' if state['kind']=='karung' else 'AM-BRG-')+str(ident),state=state,original=event.muatan,lines=rows,available=None if unknown else str(available),names=names,balances=facts['balances'],actor=actor.nama if actor else 'Tidak tersedia',time=event.waktu.isoformat(),history=logs,baseline=sign(facts),source_facts=facts['sources'])

def normalized(req):
    return dict(mode=req.get('mode'),quantity=str(req.get('quantity')) if req.get('quantity') is not None else None,customer=req.get('customer'),source_ids=sorted(set(req.get('source_ids') or [])),reason=(req.get('reason') or '').strip())

async def give_back(db,state,amount,user):
    kind=state['kind'];M=MODELS[kind]
    from app.penggilingan.gudang2.rencana_beras import berat_karung_nyata
    dest=state.get('customer')
    free={r.id:n for r,n in await free_guard(db,kind,state['identity'],dest,detail=state.get('detail',False))}
    left=amount;changes=[]
    for line in reversed(state['lines']):
        if left<=0:break
        n=D(line['quantity']);take=min(left,n)
        if not take:continue
        row=await db.get(M,line['target_id'],populate_existing=True,with_for_update=True)
        if not row or raw(row)!=line['target']:
            raise InventoryError(f"Sumber #{line['target_id']} telah berubah atau dipakai transaksi terkait. Periksa detail sumber; saldo pemilik lain tidak dapat menggantikannya.")
        if take>free.get(row.id,D(0)):
            detail=await blocker(db,state,row)
            raise InventoryError(f"Perpindahan sumber #{row.id} hanya memiliki {free.get(row.id,D(0))} bagian bebas; perlu mengembalikan {take}. {detail}")
        original=raw(row);restored=None
        weight=berat_karung_nyata(row,int(take)) if kind=='barang' else take if kind in CURAH else None
        if take==qty(row,kind):set_owner(row,kind,line['source_owner'])
        else:
            restored=await clone_part(db,row,kind,take,weight,line['source_owner'],user)
            set_qty(row,kind,qty(row,kind)-take,None if kind=='karung' else kg(row,kind)-weight)
        await db.flush()
        changes.append(dict(source_before=original,source_after=raw(row),restored=raw(restored) if restored else None))
        line['quantity']=str(n-take)
        if kind!='karung':line['kg']=str(D(line['kg'])-weight)
        line['target']=raw(row)
        left-=take
    if left>0:raise InventoryError('Rincian sumber transaksi tidak mencakup jumlah yang akan dibalik.')
    await db.flush()
    return changes

async def blocker(db,state,row):
    """Only authorized dependencies; caller already authorized all owners."""
    kind=state['kind'];ident=owner(row,kind)
    if kind=='curah' and state['identity']['jenis']=='broken':
        moves=(await db.scalars(select(BrokenKeSilo).where(BrokenKeSilo.byproduct_stock_id==row.id,BrokenKeSilo.dibatalkan_pada.is_(None)).order_by(BrokenKeSilo.id))).all()
        if moves:return 'Terkait '+', '.join(m.kode_pindah for m in moves[:5])+'. Periksa detail pemindahan silo melalui alur yang sah.'
    if kind in ('barang','curah'):
        q=select(OutgoingRecord.kode).join(OutgoingItem,OutgoingItem.outgoing_record_id==OutgoingRecord.id).where(OutgoingItem.jasa_id==ident)
        if kind=='barang':q=q.where(OutgoingItem.product_sku_id==state['identity']['sku'],OutgoingItem.rice_quality_standard_id==state['identity']['std'])
        else:q=q.where(OutgoingItem.jenis_byproduct==state['identity']['jenis'])
        codes=list((await db.scalars(q.distinct().limit(5))).all())
        if codes:return 'Pengiriman terkait: '+', '.join(codes)+'. Periksa muatan/alokasi melalui alur yang sah.'
    if kind=='karung':return 'Pemakaian karung/pengemasan atau kehilangan sudah tercatat. Hubungan pembelian-ke-pemakaian belum membuktikan bagian transaksi ini bebas; perlu rekonsiliasi sumber, bukan memakai saldo gabungan.'
    return 'Periksa alokasi, silo, kemas ulang, retur, dan pemakaian lanjutan sumber tersebut melalui detail stok.'

async def apply(db,*,user,ident,req):
    event,state,last=await root_state(db,ident,locked=True)
    await izin(db,user,state['warehouses'])
    if not state['warehouses']:raise InventoryError('Gudang sumber belum dapat dibuktikan. Perlu rekonsiliasi sumber sebelum koreksi.')
    body=normalized(req);before=copy.deepcopy(state)
    if state['status']=='dibatalkan':raise InventoryError('Perpindahan ini sudah dibatalkan; stok tidak dibalik lagi.')
    if body['mode'] not in ('ubah','batal'):raise InventoryError('Pilih Ubah atau Batalkan perpindahan.')
    if not body['reason']:raise InventoryError('Alasan koreksi atau pembatalan wajib diisi.')
    amount=D(0) if body['mode']=='batal' else D(body['quantity'] or 'NaN')
    kind=state['kind']
    if not amount.is_finite() or amount<0 or body['mode']=='ubah' and amount==0 or kind not in CURAH and amount!=amount.to_integral_value():raise InventoryError('Jumlah harus positif; gunakan Batalkan untuk pembalikan penuh. Karung dan lembar harus bulat.')
    if kind in CURAH and amount!=amount.quantize(D('.01')):raise InventoryError('Bobot menggunakan presisi penyimpanan dua desimal kg.')
    customer=state.get('customer') if body['customer'] is None else body['customer']
    if kind=='karung':await pihak(db,customer,kind)
    elif body['customer'] is not None and not state.get('detail'):raise InventoryError('Barang jasa harus memilih baris sumber/pesanan yang benar, bukan hanya nama pelanggan.')
    selected=body['source_ids']
    facts=await evidence(db,state,selected)
    owners=list(state['owners'])
    if selected and kind!='karung':owners=sorted({x['row']['jasa_id'] for x in facts['sources']})
    if len(owners)>1 and len(await pelanggan_ids(db,kind,set(owners)))!=1:raise InventoryError('Sumber pengganti dari pelanggan berbeda tidak digabung.')
    if state.get('detail') and customer in owners:raise InventoryError('Pemilik tujuan sama dengan asal.')
    changed_owner=customer!=state.get('customer') or owners!=state['owners']
    old=D(state['quantity'])
    if amount==old and not changed_owner and not selected:raise InventoryError('Belum ada perubahan jumlah atau pemilik.')
    ids_for_balance=set(state['owners'])|set(owners)|{None}
    ids_for_balance|={state.get('customer'),customer}
    balances_before={str(i):await balance(db,kind,state['identity'],i) for i in ids_for_balance}
    original=await physical(db,kind,state['identity']);mutations=[]
    if changed_owner or selected and kind!='karung':
        mutations+=await give_back(db,state,old,user)
        state['lines']=[];state['customer']=customer
        state['lines']=await allocate(db,kind,state['identity'],owners,amount,customer,user,source_ids=selected or state.get('bound_source_ids') or None,detail=state.get('detail',False))
    elif amount<old:mutations+=await give_back(db,state,old-amount,user)
    elif amount>old:
        state['lines']+=await allocate(db,kind,state['identity'],owners,amount-old,customer,user,source_ids=selected or state.get('bound_source_ids') or None,detail=state.get('detail',False))
    if selected and state.get('detail'):state['bound_source_ids']=selected
    state['owners']=owners;state['parties']={str(o):await pihak(db,o,kind) for o in set(owners)|{customer,None}};state['quantity']=str(amount)
    state['kg']=None if kind=='karung' else str(sum((D(x['kg']) for x in state['lines']),D(0)))
    state['version']+=1;state['status']='dibatalkan' if body['mode']=='batal' else 'terkoreksi'
    await db.flush()
    if await physical(db,kind,state['identity'])!=original:raise InventoryError('Total fisik tidak seimbang; seluruh perubahan dibatalkan.')
    balances_after={str(i):await balance(db,kind,state['identity'],i) for i in ids_for_balance}
    for b in balances_after.values():
        if any(D(v)<0 for v in b.values()):raise InventoryError('Perubahan menghasilkan saldo pemilik negatif; periksa transaksi terkait.')
    return dict(mutations=mutations,root_id=ident,request=body,before=before,after=state,balances_before=balances_before,balances_after=balances_after,physical=original)

async def lock_sources(db,ident,selected=()):
    _,state,_=await root_state(db,ident,locked=True)
    M=MODELS[state['kind']]
    ids=sorted({x['target_id'] for x in state['lines']}|set(selected))
    if ids:await db.scalars(select(M).where(M.id.in_(ids)).order_by(M.id).with_for_update().execution_options(populate_existing=True))

async def inspect(db,*,user,ident,req):
    event=await db.get(Peristiwa,ident)
    if event is not None and event.jenis==AWAL and event.muatan.get('kind')=='pk':
        from app.services.pk_kepemilikan import periksa
        return await periksa(db,user=user,ident=ident,req=req)
    await izin(db,user);await lock(db)
    await lock_sources(db,ident,req.get('source_ids') or [])
    current=await context(db,user=user,ident=ident)
    if req.get('baseline')!=current['baseline']:raise InventoryError('Data atau saldo berubah. Isian dipertahankan; baca data terbaru dan periksa ulang.')
    event,state,_=await root_state(db,ident)
    facts=await evidence(db,state,req.get('source_ids') or [])
    plan=None
    async with db.begin_nested() as savepoint:
        plan=await apply(db,user=user,ident=ident,req=req)
        plan=copy.deepcopy(plan)
        await savepoint.rollback()
    return dict(plan=plan,review=sign(dict(facts=facts,request=normalized(req),baseline=req['baseline'])))

async def save(db,*,user,ident,req):
    event=await db.get(Peristiwa,ident)
    if event is not None and event.jenis==AWAL and event.muatan.get('kind')=='pk':
        from app.services.pk_kepemilikan import simpan
        return await simpan(db,user=user,ident=ident,req=req)
    await izin(db,user);await lock(db)
    key='kepemilikan-koreksi:'+str(user.id)+':'+req['key']
    existing=await db.scalar(select(Peristiwa).where(Peristiwa.kunci_kiriman==key))
    if existing:
        if existing.muatan['root_id']!=ident or existing.muatan['request']!=normalized(req):raise InventoryError('Kunci permintaan sudah dipakai untuk perubahan lain.')
        return dict(recorded=True,event_id=existing.id,plan=existing.muatan)
    if not req.get('confirm'):raise InventoryError('Konfirmasi pemeriksaan dampak wajib dicentang.')
    await lock_sources(db,ident,req.get('source_ids') or [])
    current=await context(db,user=user,ident=ident)
    if req.get('baseline')!=current['baseline']:raise InventoryError('Data atau saldo berubah sejak pemeriksaan. Periksa ulang; tidak ada perubahan disimpan.')
    event,state,_=await root_state(db,ident,locked=True)
    facts=await evidence(db,state,req.get('source_ids') or [])
    token=sign(dict(facts=facts,request=normalized(req),baseline=req['baseline']))
    if not hmac.compare_digest(req.get('review',''),token):raise InventoryError('Rancangan berubah atau pemeriksaan tidak sah. Periksa dampak lagi.')
    plan=await apply(db,user=user,ident=ident,req=req)
    e=Peristiwa(jenis=UBAH,pelaku_id=user.id,kunci_kiriman=key,muatan=plan,membatalkan_id=ident if plan['after']['status']=='dibatalkan' else None);db.add(e);await db.flush()
    await audit(db,user,state['kind'],ident,plan['before'],plan['after'],plan['request']['reason'],'batal_kepemilikan' if plan['after']['status']=='dibatalkan' else 'koreksi_kepemilikan')
    return dict(recorded=True,event_id=e.id,plan=plan)

async def sources(db,*,user,ident,search='',page=1):
    await izin(db,user);_,state,_=await root_state(db,ident);await izin(db,user,state['warehouses'])
    kind=state['kind']
    if kind=='pk':return dict(items=[],total=0,page=1,pages=0,fixed_source=True)
    M=MODELS[kind]
    if kind=='karung':return dict(items=[],total=0,page=1,pages=0)
    q=select(M).where(*conditions(kind,state['identity']),M.jasa_id.is_not(None))
    if kind=='barang' and state['warehouses']:q=q.where(M.warehouse_id.in_(state['warehouses']))
    term=search.strip()
    if term:
        ids=select(Jasa.id).join(Pelanggan,Pelanggan.id==Jasa.pelanggan_id).where(or_(Jasa.kode.ilike('%'+term+'%'),Pelanggan.nama_pelanggan.ilike('%'+term+'%')))
        q=q.where(or_(M.jasa_id.in_(ids),M.id==int(term) if term.isdigit() else False))
    total=await db.scalar(select(func.count()).select_from(q.subquery()));page=max(1,min(page,max(1,math.ceil(total/25))))
    rows=list((await db.scalars(q.order_by(M.waktu,M.id).offset((page-1)*25).limit(25))).all());result=[];pools={}
    for row in rows:
        if row.jasa_id not in pools:pools[row.jasa_id]={r.id:n for r,n in await free_rows(db,kind,state['identity'],row.jasa_id,allocating=True)}
        available=pools[row.jasa_id].get(row.id,D(0));name=await pihak(db,row.jasa_id,kind)
        result.append(dict(id=row.id,owner=row.jasa_id,label=name+' · sumber #'+str(row.id)+' · '+str(available)+(' karung' if kind=='barang' else ' kg'),available=str(available),kg=str(kg(row,kind)),source_type=row.source_type,source_id=row.source_id))
    return dict(items=result,total=total,page=page,pages=math.ceil(total/25))

async def listing(db,*,user,kind=None,status=None,search='',page=1,legacy=False):
    await izin(db,user)
    if legacy:
        q=select(ActivityLog).where(ActivityLog.aksi.in_(set(AKSI.values())),ActivityLog.table_name!='peristiwa')
        if kind=='pk':q=q.where(ActivityLog.aksi=='pindah_kepemilikan_pk')
        elif kind in ['produk','barang','curah']:q=q.where(ActivityLog.aksi=='pindah_kepemilikan_produk')
        elif kind=='karung':q=q.where(ActivityLog.aksi=='pindah_kepemilikan_karung')
        scope=await user_wh_scope(db,user)
        if scope!='all':q=q.where(ActivityLog.gudang==scope)
        if search.strip():q=q.where(or_(ActivityLog.new_value.ilike('%'+search.strip()+'%'),ActivityLog.old_value.ilike('%'+search.strip()+'%')))
        total=await db.scalar(select(func.count()).select_from(q.subquery()));page=max(1,min(page,max(1,math.ceil(total/25))))
        rows=list((await db.scalars(q.order_by(ActivityLog.id.desc()).offset((page-1)*25).limit(25))).all())
        return dict(items=[dict(id='lama-'+str(e.id),code='Audit #'+str(e.id),kind='historis',status='sumber_belum_terbukti',quantity=None,kg=None,time=e.waktu_perubahan.isoformat(),summary=e.new_value or e.old_value or 'Tidak tersedia') for e in rows],total=total,page=page,pages=math.ceil(total/25),legacy=True)
    if kind=='produk':kind_group=['barang','curah','curah_barang']
    else:kind_group=[kind] if kind else []
    from sqlalchemy.orm import aliased
    from sqlalchemy.dialects.postgresql import JSONB
    R=aliased(Peristiwa)
    current=func.coalesce(select(R.muatan['after']).where(R.jenis==UBAH,R.muatan['root_id'].as_integer()==Peristiwa.id).order_by(R.id.desc()).limit(1).correlate(Peristiwa).scalar_subquery(),Peristiwa.muatan).cast(JSONB)
    q=select(Peristiwa,current.label('state')).where(Peristiwa.jenis==AWAL)
    if kind_group:q=q.where(Peristiwa.muatan['kind'].as_string().in_(kind_group))
    if status:q=q.where(current['status'].astext==status)
    if search.strip():q=q.where(or_(current.cast(__import__('sqlalchemy').String).ilike('%'+search.strip()+'%'),Peristiwa.id==int(search.strip()) if search.strip().isdigit() else False))
    scope=await user_wh_scope(db,user)
    if scope!='all':
        whs=list((await db.scalars(select(Warehouse.id).where(Warehouse.kode_fungsi==scope))).all())
        q=q.where(or_(*(Peristiwa.muatan['warehouses'].contains([wid]) for wid in whs))) if whs else q.where(False)
    total=await db.scalar(select(func.count()).select_from(q.subquery()));page=max(1,min(page,max(1,math.ceil(total/25))))
    rows=(await db.execute(q.order_by(Peristiwa.id.desc()).offset((page-1)*25).limit(25))).all()
    items=[]
    for e,st in rows:
        names=st.get('parties',{})
        def name(owner):
            return names.get(str(owner)) or ('Pabrik' if owner is None else 'Pemilik belum tercatat')
        description = dict(label=st.get('label','PK'),unit='kg') if st['kind']=='pk' else await describe(db,st)
        asal='; '.join(dict.fromkeys(name(owner) for owner in st['owners']))
        tujuan=name(st.get('customer'))
        items.append(dict(id=e.id,code=('AM-PK-' if st['kind']=='pk' else 'AM-KRG-' if st['kind']=='karung' else 'AM-BRG-')+str(e.id),
                          kind=st['kind'],status=st['status'],quantity=st['quantity'],kg=st['kg'],time=e.waktu.isoformat(),
                          label=description['label'],unit=description['unit'],from_label=asal,to_label=tujuan,
                          summary=asal+' → '+tujuan+' · '+description['label']))
    return dict(items=items,total=total,page=page,pages=math.ceil(total/25),legacy=False)


async def legacy_detail(db,*,user,ident):
    await izin(db,user)
    e=await db.get(ActivityLog,ident)
    if not e or e.aksi not in set(AKSI.values()) or e.table_name=='peristiwa':raise InventoryError('Catatan historis tidak ditemukan.')
    scope=await user_wh_scope(db,user)
    if scope!='all' and e.gudang!=scope:raise PermissionError('Catatan historis di luar gudang efektif.')
    return dict(id='lama-'+str(e.id),code='Audit #'+str(e.id),legacy=True,summary=e.new_value or e.old_value or 'Tidak tersedia',time=e.waktu_perubahan.isoformat(),reason=e.alasan_perubahan,actor=e.changed_by,warning='Rincian semua baris sumber transaksi lama belum tersimpan. Koreksi ditahan sampai bukti sumber direkonsiliasi; saldo sekarang tidak dipakai untuk menebak pembalikan.')

async def describe(db,state):
    from hmu_core import PackagingMaterial,PackageSize,Brand,RiceQualityStandard
    kind=state['kind'];identity=state['identity'];grade=None
    if kind=='curah':label=identity['jenis'].title()+' curah'
    else:
        sku=await db.get(ProductSku,identity['sku']) if kind in ('barang','curah_barang') else None
        material=await db.get(PackagingMaterial,sku.packaging_material_id if sku else identity['material'])
        size=await db.get(PackageSize,sku.package_size_id if sku else identity['size'])
        bid=sku.brand_id if sku else identity['brand'];brand=await db.get(Brand,bid) if bid else None
        std=await db.get(RiceQualityStandard,identity['std']) if kind in ('barang','curah_barang') and identity['std'] else None
        label=(sku.kategori.replace('_',' ').title() if sku else 'Karung kosong')+' · '+(getattr(material,'nama',None) or material.kode)+' · '+str(size.ukuran_kg)+' kg'+(' · '+brand.nama if brand else '')+(' · '+std.nama if std else '')
    whs=[await db.get(Warehouse,wid) for wid in state['warehouses']]
    return dict(label=label,unit='lembar' if kind=='karung' else 'karung' if kind=='barang' else 'kg',warehouses=[w.nama_gudang for w in whs if w],capacity_note='Ukuran kg adalah kapasitas kemasan, bukan bobot karung.' if kind=='karung' else None)
