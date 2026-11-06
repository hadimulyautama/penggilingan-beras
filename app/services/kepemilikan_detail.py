"""Pintu masuk berbasis baris sumber; memakai penulis kepemilikan yang sama.

Tidak membuat penerimaan/pengemasan atau ledger saldo baru. Satu operasi
dapat menunjuk dua peristiwa lama (karung dan curah), dalam satu transaksi.
"""
import copy,hmac,math
from decimal import Decimal,InvalidOperation
from urllib.parse import urlencode
from sqlalchemy import select,func,or_,and_
from sqlalchemy.dialects.postgresql import JSONB
from hmu_identitas import peran as P
from app.models import (Peristiwa,FinishedGoodsStock,ByproductStock,PackagingPurchase,
    ProductSku,Jasa,Pelanggan,Warehouse,PolishingProcess)
from app.peran import can_see_financials
from app.services import kepemilikan as s
from app.services.cakupan_fasilitas import lokasi_banyak
from app.services.peristiwa import bersih

OP='pindah_kepemilikan_detail'
KINDS=tuple(s.MODELS)
D=s.D

def identity(row,kind):
    if kind in ('barang','curah_barang'):return dict(sku=row.product_sku_id,std=row.rice_quality_standard_id)
    if kind=='curah':return dict(jenis=row.jenis_produk)
    return dict(material=row.packaging_material_id,size=row.package_size_id,brand=row.brand_id)

async def bagian_bebas(db,kind,ident,owner):
    """Kurangi sisa perintah sesuai bentuk stok, tanpa menukar karung/curah.

    FIFO dan pemakaian efektif berasal dari pembaca stok lama. Perintah
    masih aktif menahan jumlah yang belum dimuat; supplier sudah tercakup
    pada free_rows sehingga tidak dikurangkan kedua kalinya.
    """
    rows=await s.free_rows(db,kind,ident,owner,allocating=kind!='karung')
    if kind not in ('barang','curah'):return rows
    from app.models import OutgoingItem as I,OutgoingRecord as R
    from app.penggilingan.inventory.models import OUT_PERINTAH
    q=select(I).join(R,R.id==I.outgoing_record_id).where(R.status==OUT_PERINTAH,I.jasa_id==owner)
    if kind=='barang':q=q.where(I.item_type=='finished_goods',I.product_sku_id==ident['sku'],I.rice_quality_standard_id==ident['std'])
    else:q=q.where(I.item_type=='byproduct_curah',I.jenis_byproduct==ident['jenis'])
    pending=D(0)
    for item in (await db.scalars(q)).all():
        if kind=='barang':
            if item.jumlah_karung_perintah is None and D(item.berat_perintah_kg or 0)>D(item.berat_kg or 0):return [(r,D(0)) for r,n in rows]
            pending+=max(D(0),D(item.jumlah_karung_perintah or 0)-D(item.jumlah_karung or 0))
        else:pending+=max(D(0),D(item.berat_perintah_kg or 0)-D(item.berat_kg or 0))
    result=[]
    for row,n in rows:
        held=min(pending,n);pending-=held;result.append((row,n-held))
    return result

async def sumber(db,user,kind,id,*,locked=False):
    if kind not in KINDS:raise s.InventoryError('Jenis sumber tidak sah.')
    if not user or not (P.operator_saja(user.role) or P.admin_keatas(user.role)):raise PermissionError('Sumber stok ini memerlukan akses aplikasi operasional.')
    row=await db.get(s.MODELS[kind],id,populate_existing=True,with_for_update=locked)
    if not row:raise s.InventoryError('Baris sumber tidak ditemukan; data historis tidak ditebak.')
    if kind=='barang' and row.curah_kemas_ulang or kind=='curah_barang' and (not row.curah_kemas_ulang or row.jumlah_karung!=0):raise s.InventoryError('Bentuk stok sumber berbeda. Buka baris yang benar dari detail.')
    ident=identity(row,kind)
    whs=await s.warehouse_ids(db,kind,ident,[row])
    if len(whs)!=1:raise s.InventoryError('Lokasi sumber belum dapat dibuktikan.')
    if not P.admin_keatas(user.role) and user.default_warehouse_id!=whs[0]:raise PermissionError('Sumber di luar gudang efektif.')
    wh=await db.get(Warehouse,whs[0]);owner=s.owner(row,kind)
    if kind=='karung' and not P.admin_keatas(user.role) and wh.kode_fungsi!='g2':raise PermissionError('Hak baca karung mengikuti layar karung yang berlaku.')
    desc=await s.describe(db,dict(kind=kind,identity=ident,warehouses=whs))
    total=s.qty(row,kind);free=dict((r.id,n) for r,n in await bagian_bebas(db,kind,ident,owner)).get(row.id,D(0))
    free=max(D(0),min(total,free))
    bag_weight=s.kg(row,kind)
    if kind=='barang':
        from app.penggilingan.gudang2.rencana_beras import berat_karung_nyata
        free_weight=berat_karung_nyata(row,int(free))
    else:free_weight=None if kind=='karung' else free
    code=getattr(row,'kode',None) or f'{kind} #{row.id}'
    if kind!='karung' and row.source_id is not None:
        code=f'{row.source_type} #{row.source_id} · baris #{row.id}'
        if row.source_type=='polishing':
            pr=await db.get(PolishingProcess,row.source_id)
            if pr:code=f'{pr.kode_proses} · baris #{row.id}'
    allowed=bool(can_see_financials(user) and wh.aktif)
    if allowed:
        try:await s.izin(db,user,whs)
        except PermissionError:allowed=False
    return dict(row=row,raw=s.raw(row),kind=kind,id=id,identity=ident,owner=owner,
        pemilik=await s.pihak(db,owner,kind),warehouse_id=wh.id,gudang=wh.nama_gudang,
        label=desc['label'],code=code,unit=desc['unit'],total=total,available=free,
        warning=('Pemakaian karung sudah ada, tetapi hubungan pemakaian ke baris pembelian ini belum terbukti. Bagian yang aman dipindahkan belum dapat ditentukan; perlu rekonsiliasi sumber.' if kind=='karung' and free==0 and total>0 else ''),
        reserved=total-free,weight=bag_weight,available_weight=free_weight,can_transfer=allowed)

async def daftar_produk(db,*,user,jenis,owners,page=1):
    """Daftar sumber sebelum formulir, tidak memilih FIFO secara terselubung."""
    from app.services.cakupan_fasilitas import batas
    from app.services.stok import jenis_produk
    from app.services.jasa import nama_pemilik_banyak
    sku_rows=(await db.execute(select(ProductSku.id,ProductSku.kategori))).all()
    from app.models import RiceQualityStandard
    standards={x.id:x.kode for x in (await db.scalars(select(RiceQualityStandard))).all()}
    # Kategori standar mengikuti helper lama; hanya ID master kecil dibaca.
    from sqlalchemy import literal,union_all
    combinations=[and_(FinishedGoodsStock.product_sku_id==sku.id, FinishedGoodsStock.rice_quality_standard_id.is_(None) if std is None else FinishedGoodsStock.rice_quality_standard_id==std) for sku in sku_rows for std in [None,*standards] if jenis_produk(sku.kategori,standards.get(std))==jenis]
    q1=select(literal('fg').label('kind'),FinishedGoodsStock.id.label('id'),FinishedGoodsStock.waktu.label('time')).where(
        FinishedGoodsStock.jasa_id.in_(owners) if None not in owners else FinishedGoodsStock.jasa_id.is_(None),
        FinishedGoodsStock.berat_total_kg>0,batas(user,FinishedGoodsStock),or_(*combinations) if combinations else False)
    q2=select(literal('curah').label('kind'),ByproductStock.id.label('id'),ByproductStock.waktu.label('time')).where(ByproductStock.jenis_produk==jenis,ByproductStock.jasa_id.in_(owners) if None not in owners else ByproductStock.jasa_id.is_(None),ByproductStock.berat_kg>0,batas(user,ByproductStock))
    union=union_all(q1,q2).subquery();total=await db.scalar(select(func.count()).select_from(union))
    chosen=(await db.execute(select(union).order_by(union.c.time.desc(),union.c.kind,union.c.id.desc()).offset((page-1)*25).limit(25))).all()
    fgs={r.id:r for r in (await db.scalars(select(FinishedGoodsStock).where(FinishedGoodsStock.id.in_([x.id for x in chosen if x.kind=='fg'])))).all()}
    bps={r.id:r for r in (await db.scalars(select(ByproductStock).where(ByproductStock.id.in_([x.id for x in chosen if x.kind=='curah'])))).all()}
    names=await nama_pemilik_banyak(db,{r.jasa_id for r in [*fgs.values(),*bps.values()] if r.jasa_id})
    locations={**{('fg',k):v for k,v in (await lokasi_banyak(db,FinishedGoodsStock,list(fgs))).items()},**{('curah',k):v for k,v in (await lokasi_banyak(db,ByproductStock,list(bps))).items()}}
    items=[]
    for item in chosen:
        r=(fgs if item.kind=='fg' else bps)[item.id];kind='curah' if item.kind=='curah' else 'curah_barang' if r.curah_kemas_ulang else 'barang'
        items.append(dict(url=f'/stok/sumber/{kind}/{r.id}',code=(f'{r.source_type} #{r.source_id} · ' if r.source_id else '')+f'baris #{r.id}',owner=names.get(r.jasa_id,'Pabrik'),gudang=locations[(item.kind,item.id)]['gudang_nama'],unit='karung' if kind=='barang' else 'kg',quantity=str(s.qty(r,kind)),weight=str(s.kg(r,kind))))
    return dict(items=items,total=total,page=page,pages=math.ceil(total/25))

async def daftar_karung(db,*,user,material,size,brand='',owner=None,page=1):
    from app.penggilingan.inventory.packaging import get_material,get_size,get_brand
    mat=await get_material(db,material);sz=await get_size(db,size);br=await get_brand(db,brand) if brand else None
    if not mat or not sz or brand and not br:raise s.InventoryError('Identitas karung tidak ditemukan.')
    identity_=dict(material=mat.id,size=sz.id,brand=br.id if br else None)
    # Scope sama dengan halaman dan sumber; tidak membaca rekening lain.
    whs=await s.warehouse_ids(db,'karung',identity_,[])
    if not user or not (P.admin_keatas(user.role) or P.operator_saja(user.role)):raise PermissionError('Akses stok karung diperlukan.')
    if not P.admin_keatas(user.role):
        wh=await db.get(Warehouse,whs[0]) if whs else None
        if not wh or user.default_warehouse_id!=wh.id or wh.kode_fungsi!='g2':raise PermissionError('Karung di luar hak baca gudang efektif.')
    q=select(PackagingPurchase).where(*s.conditions('karung',identity_),PackagingPurchase.pelanggan_id==owner)
    total=await db.scalar(select(func.count()).select_from(q.subquery()))
    rows=(await db.scalars(q.order_by(PackagingPurchase.waktu.desc(),PackagingPurchase.id.desc()).offset((page-1)*25).limit(25))).all()
    owner_label=await s.pihak(db,owner,'karung')
    return dict(items=[dict(url=f'/stok/sumber/karung/{r.id}',code=r.kode,owner=owner_label,gudang='',unit='lembar',quantity=str(r.jumlah_lembar),weight=None) for r in rows],total=total,page=page,pages=math.ceil(total/25))

def visible(src):return {k:(str(v) if isinstance(v,Decimal) else v) for k,v in src.items() if k not in ['row','raw','identity']}

async def cocok_bulk(db,user,primary,bulk_key):
    try:kind,id=bulk_key.split(':');id=int(id)
    except (ValueError,AttributeError):raise s.InventoryError('Sumber curah tidak sah.')
    if primary['kind']!='barang' or kind not in s.CURAH:raise s.InventoryError('Pilih karung dan curah dari partai yang sama.')
    bulk=await sumber(db,user,kind,id)
    a=primary['row'];b=bulk['row']
    if not a.source_id or (a.source_type,a.source_id,primary['owner'],primary['warehouse_id'])!=(b.source_type,b.source_id,bulk['owner'],bulk['warehouse_id']):raise s.InventoryError('Asal partai, pemilik, atau lokasi curah berbeda; sumber tidak digabung.')
    if kind=='curah_barang' and primary['identity']!=bulk['identity']:raise s.InventoryError('SKU/mutu curah berbeda dari karung.')
    if kind=='curah':
        sku=await db.get(ProductSku,a.product_sku_id)
        if sku.kategori!=b.jenis_produk:raise s.InventoryError('Jenis curah berbeda dari barang berkarung.')
    return bulk

async def konteks(db,*,user,kind,id,bulk_key='',page=1,bulk_page=1):
    primary=await sumber(db,user,kind,id)
    bulk=await cocok_bulk(db,user,primary,bulk_key) if bulk_key else None
    parts=[primary]+([bulk] if bulk else [])
    facts=[dict(raw=x['raw'],kind=x['kind'],free=str(x['available']),warehouse=x['warehouse_id']) for x in parts]
    history=[];M=Peristiwa
    line_filter=or_(M.muatan['lines'].cast(JSONB).contains([{'source_id':id}]),M.muatan['lines'].cast(JSONB).contains([{'target_id':id}]))
    restored=select(M.muatan['root_id'].as_integer()).where(M.jenis==s.UBAH,M.muatan['mutations'].cast(JSONB).contains([{'restored':{'id':id}}]))
    q=select(M).where(M.jenis==s.AWAL,M.muatan['kind'].as_string()==kind,or_(line_filter,M.id.in_(restored)))
    total=await db.scalar(select(func.count()).select_from(q.subquery()))
    for event in (await db.scalars(q.order_by(M.id.desc()).offset((page-1)*25).limit(25))).all():
        _,state,_=await s.root_state(db,event.id)
        history.append(dict(id=event.id,url='/kepemilikan/'+str(event.id),time=event.waktu.isoformat(),status=state['status'],quantity=state['quantity'],kg=state['kg'],from_label=state.get('parties',{}).get(str(state['owners'][0]),'Tidak tercatat'),to_label=state.get('parties',{}).get(str(state.get('customer')),'Pabrik'),note=state.get('note','')))
    options=[];bulk_total=0
    if kind=='barang' and primary['row'].source_id:
        from sqlalchemy import literal,union_all
        from app.services.cakupan_fasilitas import lokasi
        row=primary['row'];sku=await db.get(ProductSku,row.product_sku_id)
        candidates=[]
        for k,model in [('curah_barang',FinishedGoodsStock),('curah',ByproductStock)]:
            conditions=[model.source_type==row.source_type,model.source_id==row.source_id,model.jasa_id==row.jasa_id,lokasi(model)==primary['warehouse_id']]
            if k=='curah_barang':conditions += [model.curah_kemas_ulang.is_(True),model.berat_total_kg>0,model.product_sku_id==row.product_sku_id,model.rice_quality_standard_id==row.rice_quality_standard_id]
            else:conditions += [model.jenis_produk==sku.kategori,model.berat_kg>0]
            candidates.append(select(literal(k).label('kind'),model.id.label('id')).where(*conditions))
        all_candidates=union_all(*candidates).subquery()
        bulk_total=await db.scalar(select(func.count()).select_from(all_candidates))
        chosen=(await db.execute(select(all_candidates).order_by(all_candidates.c.kind,all_candidates.c.id).offset((bulk_page-1)*25).limit(25))).all()
        for candidate in chosen:
            try:found=await cocok_bulk(db,user,primary,f'{candidate.kind}:{candidate.id}')
            except (s.InventoryError,PermissionError):continue
            options.append(dict(key=f'{candidate.kind}:{candidate.id}',label=found['code'],quantity=str(found['total'])))
    return dict(parts=[visible(x) for x in parts],baseline=s.sign(facts),can_transfer=all(x['can_transfer'] for x in parts),bulk_key=bulk_key,
        bulk_options=options,bulk_page=bulk_page,bulk_pages=math.ceil(bulk_total/25),bulk_total=bulk_total,history=history,history_total=total,page=page,pages=math.ceil(total/25),back=f'/stok/sumber/{kind}/{id}')

async def pelanggan(db,*,user,kind,id,q='',page=1):
    src=await sumber(db,user,kind,id);await s.izin(db,user,[src['warehouse_id']])
    source_customer=src['owner'] if kind=='karung' else (await db.get(Jasa,src['owner'])).pelanggan_id if src['owner'] else None
    query=select(Pelanggan.id,Pelanggan.nama_pelanggan).where(Pelanggan.status=='aktif',Pelanggan.deleted_at.is_(None))
    if source_customer:query=query.where(Pelanggan.id!=source_customer)
    if q.strip():query=query.where(Pelanggan.nama_pelanggan.ilike('%'+q.strip()+'%'))
    if kind!='karung':query=query.add_columns(Jasa.id.label('jasa_id'),Jasa.kode).join(Jasa,Jasa.pelanggan_id==Pelanggan.id).where(Jasa.status=='berjalan')
    total=await db.scalar(select(func.count()).select_from(query.subquery()))
    rows=(await db.execute(query.order_by(Pelanggan.nama_pelanggan,Pelanggan.id,*([Jasa.id] if kind!='karung' else [])).offset((page-1)*20).limit(20))).all()
    return dict(items=[dict(value=('pelanggan:'+str(r.id)) if kind=='karung' else 'jasa:'+str(r.jasa_id),label=r.nama_pelanggan+(' · '+r.kode if kind!='karung' else '')) for r in rows],total=total,page=page,pages=math.ceil(total/20),factory=src['owner'] is not None)

def normalized(req):return dict(destination=req['destination'],quantity=str(D(req['quantity'])),bulk=str(D(req.get('bulk',0))),bulk_key=req.get('bulk_key') or '',note=(req.get('note') or '').strip())

async def tujuan(db,user,src,dest):
    if dest=='pabrik':value=None
    else:
        prefix,sep,ident=dest.partition(':')
        if prefix!=('pelanggan' if src['kind']=='karung' else 'jasa') or not sep or not ident.isascii() or not ident.isdigit():raise s.InventoryError('Pilih pemilik tujuan yang sah.')
        value=int(ident)
        customer=await db.get(Pelanggan,value) if src['kind']=='karung' else None
        if src['kind']!='karung':
            order=await db.get(Jasa,value,populate_existing=True,with_for_update=True)
            if not order or order.status!='berjalan':raise s.InventoryError('Pesanan jasa tujuan harus masih berjalan; tidak membuat pesanan atau penerimaan baru.')
            customer=await db.get(Pelanggan,order.pelanggan_id)
            if src['owner']:
                old=await db.get(Jasa,src['owner'])
                if old and old.pelanggan_id==customer.id:raise s.InventoryError('Pelanggan tujuan sama dengan pemilik asal.')
        if not customer or customer.status!='aktif' or customer.deleted_at is not None:raise s.InventoryError('Pelanggan tujuan tidak tersedia.')
    if value==src['owner']:raise s.InventoryError('Pemilik asal tidak boleh menjadi tujuan.')
    return value,await s.pihak(db,value,src['kind'])

async def saldo_tujuan(db,src,dest):
    """Saldo bebas pada lokasi sumber, tanpa membuka saldo gudang lain."""
    if src['kind']=='karung':return await s.balance(db,'karung',src['identity'],dest)
    rows=await bagian_bebas(db,src['kind'],src['identity'],dest)
    locations=await lokasi_banyak(db,s.MODELS[src['kind']],[r.id for r,n in rows])
    rows=[(r,n) for r,n in rows if locations.get(r.id,{}).get('warehouse_id')==src['warehouse_id']]
    if src['kind']=='barang':
        from app.penggilingan.gudang2.rencana_beras import berat_karung_nyata
        return dict(karung=sum((n for r,n in rows),D(0)),kg=sum((berat_karung_nyata(r,int(n)) for r,n in rows),D(0)))
    return dict(kg=sum((n for r,n in rows),D(0)))

async def periksa(db,*,user,kind,id,req):
    src=await sumber(db,user,kind,id);await s.izin(db,user,[src['warehouse_id']])
    if not src['can_transfer']:raise PermissionError('Sumber tidak mengizinkan perpindahan.')
    ctx=await konteks(db,user=user,kind=kind,id=id,bulk_key=req.get('bulk_key',''))
    if req['baseline']!=ctx['baseline']:raise s.InventoryError('Saldo atau identitas sumber berubah. Isian dipertahankan; periksa ulang data terbaru.')
    body=normalized(req);dest,label=await tujuan(db,user,src,body['destination'])
    sources=[src]+([await cocok_bulk(db,user,src,body['bulk_key'])] if body['bulk_key'] else [])
    quantities=[D(body['quantity'])]+([D(body['bulk'])] if len(sources)==2 else [])
    if len(sources)==1 and D(body['bulk'])!=0:raise s.InventoryError('Curah hanya dapat diisi jika baris sumbernya dipilih dari detail.')
    if any(not n.is_finite() for n in quantities):raise s.InventoryError('Jumlah harus berupa angka yang sah.')
    if sum(quantities)<=0:raise s.InventoryError('Total perpindahan harus lebih dari nol.')
    parts=[]
    for x,n in zip(sources,quantities):
        if not n.is_finite() or n<0 or (x['kind'] not in s.CURAH and n!=n.to_integral_value()):raise s.InventoryError('Jumlah tidak sah; karung/lembar wajib bilangan bulat dan tidak negatif.')
        if x['kind'] in s.CURAH and n!=n.quantize(D('.01')):raise s.InventoryError('Kg mengikuti presisi penyimpanan dua desimal.')
        if n>x['available']:raise s.InventoryError(f"Sumber {x['code']} hanya tersedia {x['available']} {x['unit']}; stok terikat tidak ikut dipindahkan.")
        if x['kind']=='barang':
            from app.penggilingan.gudang2.rencana_beras import berat_karung_nyata
            weight=berat_karung_nyata(x['row'],int(n))
        else:weight=None if x['kind']=='karung' else n
        target=await saldo_tujuan(db,x,dest)
        parts.append(dict(**visible(x),quantity=str(n),kg=None if weight is None else str(weight),after=str(x['total']-n),available_after=str(x['available']-n),destination_before=bersih(target)))
    plan=dict(parts=parts,from_label=src['pemilik'],to_label=label,to_owner=dest,note=body['note'],baseline=ctx['baseline'],request=body,physical_unchanged=True)
    return dict(plan=plan,review=s.sign(dict(actor=user.id,key=req['key'],plan=plan)))

async def simpan(db,*,user,kind,id,req):
    await s.izin(db,user);await s.lock(db)
    key=f'kepemilikan-detail:{user.id}:{req["key"]}';body=normalized(req)
    old=await db.scalar(select(Peristiwa).where(Peristiwa.kunci_kiriman==key,Peristiwa.jenis==OP))
    if old:
        if old.muatan['source']!=f'{kind}:{id}' or old.muatan['request']!=body:raise s.InventoryError('Kunci permintaan sudah digunakan untuk isian berbeda.')
        await sumber(db,user,kind,id)
        return dict(recorded=True,retry=True,**old.muatan['result'])
    await sumber(db,user,kind,id,locked=True)
    if body['bulk_key']:
        k,i=body['bulk_key'].split(':');await sumber(db,user,k,int(i),locked=True)
    checked=await periksa(db,user=user,kind=kind,id=id,req=req)
    if not req.get('confirm') or not hmac.compare_digest(req.get('review',''),checked['review']):raise s.InventoryError('Periksa ulang dampak terbaru dan konfirmasikan sebelum menyimpan.')
    events=[]
    for part in checked['plan']['parts']:
        if D(part['quantity'])==0:continue
        src=await sumber(db,user,part['kind'],part['id'],locked=True)
        event=await s.initial(db,user=user,kind=part['kind'],identity=src['identity'],owners=[src['owner']],amount=D(part['quantity']),customer=checked['plan']['to_owner'],commit=False,key=key+':'+str(len(events)),source_ids=[src['id']],from_detail=True,note=body['note'],return_event=True)
        events.append(event.id)
    result=dict(events=events,back=f'/stok/sumber/{kind}/{id}',message='Kepemilikan dipindahkan; stok fisik dan lokasi tetap.')
    db.add(Peristiwa(jenis=OP,pelaku_id=user.id,kunci_kiriman=key,muatan=dict(source=f'{kind}:{id}',request=body,result=result)));await db.flush()
    return dict(recorded=True,retry=False,**result)
