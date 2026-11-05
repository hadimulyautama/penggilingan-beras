"""Pengalihan bagian bebas PK pabrik ↔ jasa pada sumber dan gudang yang sama."""
from __future__ import annotations

import copy
import hmac
from decimal import Decimal
from sqlalchemy import select, text

from app.database import now_local
from app.domain.gudang import PersediaanError, kg
from app.models import Peristiwa, User, Jasa, Pelanggan, Warehouse, PermintaanPk
from app.services import kepemilikan as umum
from app.services import pk_persediaan as persediaan

D = lambda x: Decimal(str(x))


async def pilihan(db, *, user):
    await umum.izin(db, user)
    sources = await persediaan.baca(db)
    jasa = (await db.execute(select(Jasa.id, Jasa.kode, Jasa.status, Pelanggan.nama_pelanggan)
        .join(Pelanggan, Pelanggan.id == Jasa.pelanggan_id)
        .where(Jasa.status.notin_(['dibatalkan', 'digabung']))
        .order_by(Pelanggan.nama_pelanggan, Jasa.id))).all()
    names = {j.id: j.nama_pelanggan+' · '+j.kode for j in jasa}
    pending=set((await db.scalars(select(PermintaanPk.milling_process_id).where(PermintaanPk.status.in_(['diminta','disetujui','dikirim'])))).all())
    values = []
    for key, source in sources.items():
        if key.startswith('giling:') and source.model.id in pending:continue
        if not source.stok.gudang.aktif or not source.stok.bebas or source.masalah:
            continue
        owners = sorted({b.pemilik_id for b in source.stok.bagian}, key=lambda x:x or 0)
        for owner in owners:
            n = source.bebas(owner)
            if n <= 0:
                continue
            # Lingkup izin tetap diperiksa pada setiap sumber, bukan hanya
            # pada daftar opsi. Gudang baru tunduk pada gerbang yang sama.
            try:
                await umum.izin(db, user, [source.stok.gudang.id])
            except PermissionError:
                continue
            values.append(dict(sumber=key, warehouse_id=source.stok.gudang.id,
                gudang=source.stok.gudang.nama, label=source.label,
                owner=owner, pemilik=names.get(owner, 'Pabrik' if owner is None else 'Pesanan #'+str(owner)),
                tersedia=str(n)))
    warehouses=[]
    for w in (await db.scalars(select(Warehouse).where(Warehouse.aktif.is_(True)).order_by(Warehouse.id))).all():
        try:await umum.izin(db,user,[w.id])
        except PermissionError:continue
        warehouses.append(dict(id=w.id,nama=w.nama_gudang))
    return dict(sumber=values, gudang=warehouses,
                pemilik=[dict(value=j.id,label=names[j.id]) for j in jasa if j.status=='berjalan'])


def isian(req):
    return dict(sumber=req.get('sumber'),warehouse_id=req.get('warehouse_id'),
                dari=req.get('dari'),ke=req.get('ke'),quantity=str(req.get('quantity')),
                reason=(req.get('reason') or '').strip())


async def sumber(db, user, key, warehouse_id=None, *, menulis=True):
    await umum.izin(db, user)
    if not isinstance(key, str) or not key.startswith(('giling:', 'tumpukan:')):
        raise umum.InventoryError('Pilih sumber PK yang sah.')
    values = await persediaan.baca(db, warehouse_id=warehouse_id)
    source = values.get(key)
    if source is None:
        raise umum.InventoryError('Sumber PK tidak ditemukan di gudang yang dipilih.')
    await umum.izin(db, user, [source.stok.gudang.id])
    if not menulis:
        return source
    from app.domain.gudang import Gudang
    warehouse=await db.get(Warehouse,source.stok.gudang.id,with_for_update=True,populate_existing=True)
    source.stok.gudang=Gudang.dari_model(warehouse)
    source.stok.gudang.pastikan_aktif()
    if source.masalah:
        raise umum.InventoryError(source.masalah)
    if not source.stok.bebas:
        raise umum.InventoryError('Hanya hasil PK tercatat yang masih bebas dapat dialihkan; bahan di silo atau bobot belum pasti tidak termasuk.')
    if key.startswith('giling:'):
        pending = await db.scalar(select(PermintaanPk.id).where(
            PermintaanPk.milling_process_id == source.model.id,
            PermintaanPk.status.in_(['diminta', 'disetujui', 'dikirim'])).limit(1))
        if pending:
            raise umum.InventoryError('Lot PK sedang terikat permintaan pemindahan. Selesaikan atau tolak permintaan melalui alurnya dahulu.')
    return source


def facts(source):
    return dict(sumber=source.stok.sumber,warehouse_id=source.stok.gudang.id,
                bebas=source.stok.bebas,reservasi=str(source.reservasi),
                terikat=[dict(owner=o,transaksi=t,kg=str(n)) for (o,t),n in sorted(source.terikat.items(),key=lambda v:((v[0][0] or 0),v[0][1]))],
                bagian=[dict(owner=b.pemilik_id,kg=str(b.berat_kg),transaksi=b.transaksi_id)
                        for b in source.stok.bagian])


async def validasi(db, user, req):
    body = isian(req)
    if not body['reason']:
        raise umum.InventoryError('Alasan pengalihan wajib diisi.')
    amount = kg(body['quantity'])
    if amount <= 0:
        raise umum.InventoryError('Bobot pengalihan harus lebih dari nol.')
    source = await sumber(db, user, body['sumber'], body['warehouse_id'])
    for owner in [body['dari'], body['ke']]:
        if owner is not None:
            j = await db.get(Jasa, owner,with_for_update=True,populate_existing=True)
            if not j or j.status in ['dibatalkan', 'digabung']:
                raise umum.InventoryError('Pilih pesanan pelanggan jasa yang masih berlaku.')
    if body['ke'] is not None and (await db.get(Jasa,body['ke'])).status!='berjalan':
        raise umum.InventoryError('Pesanan jasa tujuan harus masih berjalan.')
    if amount > source.bebas(body['dari']):
        raise umum.InventoryError('Bobot melebihi bagian bebas pemilik sumber setelah alokasi dan pemakaian.')
    projected = copy.deepcopy(source.stok)
    projected.alihkan(body['dari'], body['ke'], amount, transaksi_id=-1)
    return source, body, projected


def balances(stock):
    owners = {b.pemilik_id for b in stock.bagian}
    return {str(o):{'kg':str(stock.saldo(o))} for o in owners}


async def periksa_awal(db, *, user, req):
    await umum.lock(db)
    source, body, projected = await validasi(db, user, req)
    baseline = umum.sign(facts(source))
    return dict(baseline=baseline,review=umum.sign(dict(baseline=baseline,request=body)),
                plan=dict(balances_before=balances(source.stok), balances_after=balances(projected),
                          physical_before=str(source.stok.fisik_kg),physical_after=str(projected.fisik_kg),
                          gudang=source.stok.gudang.nama,sumber=source.label))


async def simpan_awal(db, *, user, req):
    await umum.izin(db, user)
    await umum.lock(db)
    body = isian(req)
    key = 'pk-kepemilikan-awal:'+str(user.id)+':'+req['key']
    existing = await db.scalar(select(Peristiwa).where(Peristiwa.kunci_kiriman == key))
    if existing:
        if existing.muatan.get('initial_request') != body:
            raise umum.InventoryError('Kunci kiriman sudah digunakan untuk pengalihan yang berbeda.')
        return dict(recorded=True,id=existing.id,event_id=existing.id)
    if not req.get('confirm'):
        raise umum.InventoryError('Konfirmasi dampak pengalihan wajib dicentang.')
    source, body, _ = await validasi(db, user, req)
    baseline = umum.sign(facts(source))
    expected = umum.sign(dict(baseline=baseline,request=body))
    if req.get('baseline') != baseline or not hmac.compare_digest(req.get('review',''), expected):
        raise umum.InventoryError('Saldo atau isian berubah; periksa kembali dampak pengalihan.')
    now = now_local()
    ident = await db.scalar(text("select nextval(pg_get_serial_sequence('peristiwa','id'))"))
    names = {str(o):await umum.pihak(db,o,'pk') for o in {body['dari'],body['ke'],None}}
    source_id = source.model.id
    line = dict(source_id=source_id,target_id=source_id,source_owner=body['dari'],
                quantity=body['quantity'],kg=body['quantity'],
                source_before=dict(source_type='Lot penggilingan' if body['sumber'].startswith('giling:') else 'Tumpukan PK',source_id=source_id))
    state = dict(kind='pk',identity=dict(sumber=body['sumber']),owners=[body['dari']],
                 customer=body['ke'],quantity=body['quantity'],kg=body['quantity'],
                 warehouses=[source.stok.gudang.id],warehouse_scope=None,status='aktif',version=0,
                 parties=names,lines=[line],label=source.label,initial_request=body,
                 pk_moves=[dict(sumber=body['sumber'],dari=body['dari'],ke=body['ke'],
                                kg=body['quantity'],transaksi_id=ident)])
    event = Peristiwa(id=ident,jenis=umum.AWAL,pelaku_id=user.id,kunci_kiriman=key,muatan=state,waktu=now)
    db.add(event)
    await db.flush()
    await umum.audit(db,user,'pk',event.id,{},state,body['reason'],'pindah_kepemilikan_pk')
    return dict(recorded=True,id=event.id,event_id=event.id)


async def context(db, *, user, ident):
    await umum.izin(db, user)
    event, state, _ = await umum.root_state(db, ident)
    await umum.izin(db,user,state['warehouses'])
    source = await sumber(db,user,state['identity']['sumber'],state['warehouses'][0],menulis=False)
    available = source.bebas(state['customer'],transaksi_id=ident) if not source.masalah else D(0)
    if source.masalah:
        available = D(0)
    rows = [dict(**line,free=str(available),used=str(max(D(0),D(state['quantity'])-available)),
                 consistent=True,availability_known=True,
                 blocker='Bagian PK telah berpindah atau terikat. Pratinjau koreksi menelusuri transfer dan bahan proses terkait.' if available<D(state['quantity']) else None)
            for line in state['lines']]
    history = list((await db.scalars(select(Peristiwa).where(Peristiwa.jenis==umum.UBAH,
        Peristiwa.muatan['root_id'].as_integer()==ident).order_by(Peristiwa.id))).all())
    actors = {u.id:u.nama for u in (await db.scalars(select(User))).all()}
    logs = [dict(id=e.id,actor=actors.get(e.pelaku_id,'Tidak tersedia'),time=e.waktu.isoformat(),
                 reason=e.muatan['request']['reason'],before=e.muatan['before'],after=e.muatan['after'],pk_chain=e.muatan.get('pk_chain')) for e in history]
    names = {str(o):await umum.pihak(db,o,'pk') for o in set(state['owners'])|{state['customer'],None}|{b.pemilik_id for b in source.stok.bagian}}
    return dict(id=ident,code='AM-PK-'+str(ident),state=state,original=event.muatan,lines=rows,
        available=str(available),names=names,balances=balances(source.stok),actor=actors.get(event.pelaku_id,'Tidak tersedia'),
        time=event.waktu.isoformat(),history=logs,source_facts=[],
        description=dict(label=state['label'],unit='kg',warehouses=[source.stok.gudang.nama],
                         capacity_note='Penurunan atau pembatalan dapat mengoreksi bobot transfer, silo, dan bahan proses terkait. Periksa seluruh dampak sebelum menyimpan.'),
        baseline=umum.sign(dict(facts=facts(source),state=state)))


async def _plan(db, *, user, ident, req):
    current = await context(db,user=user,ident=ident)
    if req.get('baseline') != current['baseline']:
        raise umum.InventoryError('Sumber, saldo, atau transaksi berubah. Baca data terbaru dan periksa ulang.')
    before = current['state']
    if before['status']=='dibatalkan':
        raise umum.InventoryError('Pengalihan PK sudah dibatalkan.')
    body = umum.normalized(req)
    if body['mode'] not in ['ubah','batal'] or not body['reason']:
        raise umum.InventoryError('Pilih koreksi/pembatalan dan isi alasan.')
    if body['source_ids']:
        raise umum.InventoryError('Sumber fisik PK tidak diganti melalui koreksi kepemilikan.')
    amount = D(0) if body['mode']=='batal' else kg(body['quantity'])
    if body['mode']=='ubah' and amount<=0:
        raise umum.InventoryError('Jumlah koreksi harus lebih dari nol.')
    source = await sumber(db,user,before['identity']['sumber'],before['warehouses'][0])
    projected = copy.deepcopy(source.stok)
    source_owner=source.pemilik(before['owners'][0])
    previous_dest=source.pemilik(before['customer'])
    dest = previous_dest if body['customer'] is None else source.pemilik(body['customer'])
    if source_owner is not None and dest is not None:
        raise umum.InventoryError('PK jasa hanya dialihkan ke pabrik.')
    if dest is not None:
        j=await db.get(Jasa,dest,with_for_update=True,populate_existing=True)
        if not j or j.status in ['digabung','dibatalkan']:
            raise umum.InventoryError('Pesanan tujuan tidak berlaku.')
    old = D(before['quantity'])
    if source_owner is not None and (amount<old or dest!=previous_dest):
        origin=await db.get(Jasa,source_owner,with_for_update=True,populate_existing=True)
        if origin is None or origin.status!='berjalan':
            raise umum.InventoryError('Pesanan jasa asal sudah tidak berjalan. Gunakan pengalihan baru ke pesanan aktif pemilik tersebut; stok tidak dikembalikan ke pesanan yang sudah ditutup.')
    moves = []
    chain=None
    reversal=old if dest!=previous_dest else max(D(0),old-amount)
    restored=max(D(0),reversal-source.bebas(previous_dest,transaksi_id=ident))
    if restored:
        from app.services.pk_koreksi_rantai import rancang
        from app.domain.gudang import BagianPK
        chain=await rancang(db,source=source,ident=ident,owner=previous_dest,jumlah=restored,user=user)
        projected.bagian.append(BagianPK(previous_dest,restored,ident))
    def move(a,b,n,tag=None,receipt=ident):
        if n<=0:return
        if tag is not None and n>source.bebas(a,transaksi_id=tag)+(restored if a==previous_dest and tag==ident else D(0)):
            raise umum.InventoryError('Bagian transaksi sudah dipakai atau dialokasikan; hanya bagian bebas yang dapat dibalik.')
        projected.alihkan(a,b,n,transaksi_id=receipt,sumber_transaksi_id=tag)
        moves.append(dict(sumber=source.stok.sumber,dari=a,ke=b,kg=str(n),
                          transaksi_id=receipt,sumber_transaksi_id=tag))
    if dest != previous_dest:
        move(previous_dest,source_owner,old,tag=ident,receipt=0)
        if amount>source.bebas(source_owner)+old:
            raise umum.InventoryError('Bagian PK sumber tidak cukup setelah alokasi lain.')
        move(source_owner,dest,amount)
    elif amount<old:
        move(dest,source_owner,old-amount,tag=ident,receipt=0)
    elif amount>old:
        if amount-old>source.bebas(source_owner):
            raise umum.InventoryError('Tambahan melebihi stok bebas pemilik sumber.')
        move(source_owner,dest,amount-old)
    after = copy.deepcopy(before)
    after.pop('pk_moves',None)
    after.update(owners=[source_owner],customer=dest,quantity=str(amount),kg=str(amount),version=before['version']+1,
                 status='dibatalkan' if body['mode']=='batal' else 'terkoreksi')
    after['lines'][0].update(quantity=str(amount),kg=str(amount))
    after['parties']={str(o):await umum.pihak(db,o,'pk') for o in {source_owner,dest,None}}
    result=dict(root_id=ident,before=before,after=after,request=body,pk_moves=moves,
                balances_before=balances(source.stok),balances_after=balances(projected),
                physical_before=str(source.stok.fisik_kg),physical_after=str(projected.fisik_kg))
    if chain:result['pk_chain']=chain
    return result


async def periksa(db, *, user, ident, req):
    await umum.izin(db,user)
    await umum.lock(db)
    plan=await _plan(db,user=user,ident=ident,req=req)
    return dict(plan=plan,review=umum.sign(dict(plan=plan,baseline=req['baseline'])))


async def simpan(db, *, user, ident, req):
    await umum.izin(db,user)
    await umum.lock(db)
    key='kepemilikan-koreksi:'+str(user.id)+':'+req['key']
    old=await db.scalar(select(Peristiwa).where(Peristiwa.kunci_kiriman==key))
    if old:
        if old.muatan['root_id']!=ident or old.muatan['request']!=umum.normalized(req):
            raise umum.InventoryError('Kunci permintaan sudah dipakai untuk perubahan lain.')
        return dict(recorded=True,event_id=old.id,plan=old.muatan)
    if not req.get('confirm'):
        raise umum.InventoryError('Konfirmasi pemeriksaan dampak wajib dicentang.')
    plan=await _plan(db,user=user,ident=ident,req=req)
    token=umum.sign(dict(plan=plan,baseline=req['baseline']))
    if not hmac.compare_digest(req.get('review',''),token):
        raise umum.InventoryError('Rancangan berubah; periksa dampak lagi.')
    e=Peristiwa(jenis=umum.UBAH,pelaku_id=user.id,kunci_kiriman=key,muatan=plan,
        waktu=now_local(),membatalkan_id=ident if plan['after']['status']=='dibatalkan' else None)
    db.add(e)
    await db.flush()
    if plan.get('pk_chain'):
        from app.services.pk_koreksi_rantai import terapkan
        await terapkan(db,event=e,user=user)
    await umum.audit(db,user,'pk',ident,plan['before'],plan['after'],plan['request']['reason'],
                      'batal_kepemilikan' if plan['after']['status']=='dibatalkan' else 'koreksi_kepemilikan')
    return dict(recorded=True,event_id=e.id,plan=plan)
