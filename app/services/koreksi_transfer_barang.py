"""Periksa/simpan koreksi lokasi umum. Pratinjau tidak menulis stok.

Pemilik dan hasil ukur produksi tetap. Bagian yang telah dipakai atau
berpindah lagi tidak diambil diam-diam dari sumber lain; koreksi tersebut
menunjukkan penghalangnya agar saldo tidak menjadi negatif.
"""
import copy,hmac
from datetime import datetime,date
from decimal import Decimal
from sqlalchemy import select,func,Numeric,DateTime,Date
from app.models import PermintaanTransferBarang as Permintaan,TransferBarang as Transfer,TransferBarangItem as Item,Peristiwa,Warehouse
from app.services import transfer_barang as s,transfer_barang_sumber as stok
from app.services.kepemilikan import raw,fingerprint,sign
from app.services.peristiwa import catat
from app.services.cakupan_fasilitas import lokasi
D=stok.D


def bentuk(req):return {k:req.get(k) for k in ('aksi','berat_kg','tujuan','alasan','kunci')}

def unit(n,satuan):return dict(jumlah=str(n),satuan=satuan)

def dampak(label,before,after,satuan):return dict(label=label,sebelum=str(before),sesudah=str(after),satuan=satuan)


async def rancang_permintaan(db,rid,req,user):
    r=await db.get(Permintaan,rid,with_for_update=True)
    if not r:raise s.Error('Permintaan tidak ditemukan.')
    old=raw(r);aksi=req['aksi'];done=await s.terpakai(db,r.id);target=r.tujuan_id
    after=copy.deepcopy(old);rows=[]
    if aksi in ('minta','persetujuan'):
        if aksi=='minta' and r.status!='diminta':raise s.Error('Jumlah permintaan hanya dapat diubah sebelum persetujuan.')
        if aksi=='persetujuan' and r.status not in (*s.AKTIF,'selesai','gugur'):raise s.Error('Permintaan ini belum mempunyai persetujuan untuk dikoreksi.')
        n=stok.angka(req.get('berat_kg'),bulat=r.sumber_jenis in stok.INTEGER)
        if aksi=='persetujuan' and n<done:raise s.Error('Persetujuan tidak boleh lebih kecil dari transfer efektif. Koreksi fakta transfer terlebih dahulu.')
        src=None
        perlu=n-(done if aksi=='persetujuan' else 0)
        if aksi=='minta' or not r.ditutup and perlu>0:
            src=await s.cek_sumber(db,r,user,kecuali=(r.id,),terkunci=True)
            if perlu>src['bebas']:raise s.Error('Stok bebas sumber tidak mencukupi jumlah yang diperbaiki.')
            if src['seluruh'] and n!=src['total']:raise s.Error('Sumber ini harus dipindah sebagai satu lot utuh.')
        field='jumlah_minta' if aksi=='minta' else 'jumlah_setuju';after[field]=str(n)
        rows.append(dampak('Diminta' if aksi=='minta' else 'Disetujui',D(getattr(r,field)),n,r.satuan))
        if aksi=='persetujuan':
            val=req.get('tujuan') or ''
            if val.startswith('gudang:') and val.partition(':')[2].isdigit():target=int(val.partition(':')[2])
            if done and target!=r.tujuan_id:raise s.Error('Tujuan tidak dapat diganti sesudah ada transfer fisik.')
            await s.tujuan(db,r.asal_id,target);after['tujuan_id']=target
            if not r.ditutup:after['status']='selesai' if done>=n else 'dikirim' if done else 'disetujui'
    elif aksi=='kembali':
        if done or r.status not in s.AKTIF:raise s.Error('Hanya persetujuan yang belum dipindahkan yang dapat dikembalikan.')
        after.update(status='diminta',jumlah_setuju='0',disetujui_oleh=None,waktu_setuju=None,ditutup=False)
        rows.append(dampak('Cadangan persetujuan',D(r.jumlah_setuju),0,r.satuan))
    elif aksi=='batal':
        if done or r.status not in ('diminta',*s.AKTIF):raise s.Error('Permintaan yang sudah dipindahkan diperbaiki melalui koreksi jumlah transfer.')
        after.update(status='gugur',ditutup=True)
        rows.append(dampak('Cadangan persetujuan',D(r.jumlah_setuju),0,r.satuan))
    elif aksi=='buka':
        if not r.ditutup or D(r.jumlah_setuju)<=done:raise s.Error('Tidak ada sisa persetujuan yang dapat dibuka kembali.')
        src=await s.cek_sumber(db,r,user,kecuali=(r.id,),terkunci=True)
        if D(r.jumlah_setuju)-done>src['bebas']:raise s.Error('Stok bebas belum cukup untuk membuka kembali sisa persetujuan.')
        after.update(status='dikirim' if done else 'disetujui',ditutup=False)
        rows.append(dampak('Cadangan persetujuan',0,D(r.jumlah_setuju)-done,r.satuan))
    else:raise s.Error('Pilih koreksi permintaan yang sah.')
    after['alasan']=req['alasan'].strip()
    plan=dict(jenis='permintaan',ident=rid,aksi=aksi,barang=rows,satuan=r.satuan,status_sesudah=after['status'],snapshot=old,transfer_efektif=str(done),after=after,
        penjelasan='Koreksi permintaan/persetujuan tidak memindahkan barang dan tidak mengganti pemilik.')
    if aksi in ('minta','persetujuan','buka') and src:plan['sumber_sidik']=fingerprint([raw(src['row']),src['tersedia'],src['bebas']])
    async def apply():
        for field in ('jumlah_minta','jumlah_setuju','status','ditutup','alasan','tujuan_id','disetujui_oleh','waktu_setuju'):
            value=after.get(field)
            if field.startswith('jumlah_'):value=D(value)
            if field=='waktu_setuju' and value:value=datetime.fromisoformat(value)
            setattr(r,field,value)
        await s.jejak(db,user,r,'koreksi_permintaan',req['alasan'])
    return plan,apply


def salin_sumber(M,snapshot,user,n,w,jenis,warehouse):
    vals={c.name:snapshot.get(c.name) for c in M.__table__.columns if c.name not in ('id','created_at','updated_at')}
    for c in M.__table__.columns:
        if c.name not in vals or vals[c.name] is None:continue
        if isinstance(c.type,Numeric):vals[c.name]=D(vals[c.name])
        elif isinstance(c.type,DateTime):vals[c.name]=datetime.fromisoformat(vals[c.name])
        elif isinstance(c.type,Date):vals[c.name]=date.fromisoformat(vals[c.name])
    out=M(**vals);out.warehouse_id=warehouse;stok.atur(out,jenis,n,w)
    return out


async def rancang_transfer(db,iid,req,user):
    i=await db.get(Item,iid,with_for_update=True)
    if not i:raise s.Error('Item transfer tidak ditemukan.')
    r=await db.get(Permintaan,i.permintaan_id,with_for_update=True);j=await db.get(Transfer,i.transfer_id,with_for_update=True)
    if req['aksi']!='jumlah':raise s.Error('Koreksi barang ini memakai jumlah transfer yang benar.')
    n=stok.angka(req.get('berat_kg'),nol=True,bulat=r.sumber_jenis in stok.INTEGER);lama=D(i.jumlah);delta=n-lama
    if not delta:raise s.Error('Jumlah belum berubah.')
    done=await s.terpakai(db,r.id)
    if done+delta>D(r.jumlah_setuju):raise s.Error('Jumlah transfer melebihi persetujuan. Perbaiki persetujuannya dahulu bila memang diperlukan.')
    e=copy.deepcopy(i.dampak);kind=e['jenis'];src=None;dst=None
    if kind in stok.UTUH and lama and n not in (D(0),lama):raise s.Error('Lot ini dipindah utuh. Batalkan transfer utuh bila belum dipakai, lalu perbaiki sumber yang sebenarnya.')
    if delta>0:
        src=await s.cek_sumber(db,r,user,kecuali=(r.id,),terkunci=True)
        if kind in stok.UTUH and n!=src['total']:raise s.Error('Lot ini dipindah utuh sesuai jumlah sumber saat ini.')
        if delta>src['bebas']:raise s.Error('Stok bebas asal tidak cukup untuk tambahan transfer.')
        if kind not in ('karung',*stok.UTUH):
            target=await db.get(stok.MODEL[kind],e['tujuan_id'],with_for_update=True)
            if lama and (not target or target.jasa_id!=src['row'].jasa_id or await db.scalar(select(lokasi(stok.MODEL[kind])).where(stok.MODEL[kind].id==target.id))!=j.tujuan_id):
                raise s.Error('Lokasi atau pesanan tujuan berubah. Perbaiki catatan lanjutan sebelum menambah transfer.')
        weight=stok.berat(src['row'],kind,delta)
    else:
        key=str(e['tujuan_id'])+('@'+str(j.tujuan_id) if kind=='karung' else '~'+str(r.sumber['pemilik_id'] or 0) if kind=='pk_tumpukan' else '')
        dst=await stok.sumber(db,user=user,jenis=kind,id=key,kunci=True,periksa_izin=False)
        if dst['asal_id']!=j.tujuan_id or dst['pemilik_kunci']!=r.sumber['pemilik_kunci']:
            raise s.Error('Barang tujuan telah berpindah lokasi atau pemilik lagi. Koreksi catatan lanjutan terlebih dahulu.')
        if kind in stok.UTUH and (dst['total']!=lama or dst['tersedia']!=lama):raise s.Error('Bobot atau pemakaian lot telah berubah. Perbaiki catatan sumber/lanjutan sebelum membatalkan transfer utuh.')
        held=await s.cadangan(db,kind,dst['id'])
        if -delta>max(D(0),dst['tersedia']-held):raise s.Error('Bagian tujuan sudah dipakai, dialokasikan, atau masuk proses. Perbaiki catatan lanjutan dahulu; stok tidak diambil dari lot lain.')
        weight=stok.berat(dst['row'],kind,-delta)
    berat_delta=None if weight is None else weight if delta>0 else -weight
    new_weight=None if i.berat_kg is None else D(i.berat_kg)+berat_delta
    if new_weight is not None and new_weight<0:raise s.Error('Bukti berat tujuan tidak cukup untuk koreksi ini.')
    origin_before=src['bebas'] if src else D(0)
    if delta<0:
        try:
            origin=await s.cek_sumber(db,r,user,kecuali=(r.id,),terkunci=True)
            origin_before=origin['bebas']
        except s.Error:origin=None
    snap=dict(item=raw(i),permintaan=raw(r),transfer=raw(j),sumber=raw(src['row']) if src else raw(origin['row']) if delta<0 and origin else None,tujuan=raw(dst['row']) if dst else None,
        sumber_bebas=str(src['bebas']) if src else None,tujuan_bebas=str(dst['tersedia']) if dst else None)
    plan=dict(jenis='transfer',ident=iid,aksi='jumlah',barang=[dampak('Transfer ini',lama,n,r.satuan),dampak('Total transfer permintaan',done,done+delta,r.satuan),dampak('Stok bebas asal',origin_before,origin_before-delta,r.satuan)],snapshot=snap,
        penjelasan='Koreksi hanya memindahkan kembali bagian stok yang masih dapat dibuktikan. Pemilik dan hasil ukur produksi tidak diubah.')
    if dst:plan['barang'].append(dampak('Stok bebas tujuan',dst['tersedia'],dst['tersedia']+delta,r.satuan))
    if new_weight is not None:plan['barang'].append(dampak('Berat transfer',D(i.berat_kg),new_weight,'kg'))
    async def apply():
        nonlocal e
        if lama==0:
            e,newkg=await stok.pindah(db,user=user,jenis=r.sumber_jenis,id=r.sumber_id,tujuan_id=r.tujuan_id,n=n)
            i.berat_kg=newkg
        elif kind=='karung':
            i.berat_kg=None
        elif kind in stok.UTUH:
            dst['row'].warehouse_id=j.asal_id
            if hasattr(dst['row'],'waktu_penempatan'):
                waktu=e.get('sumber_before',{}).get('waktu_penempatan')
                dst['row'].waktu_penempatan=datetime.fromisoformat(waktu) if waktu else None
            i.berat_kg=0
        else:
            M=stok.MODEL[kind]
            source=await db.get(M,e['sumber_id'],with_for_update=True)
            target=await db.get(M,e['tujuan_id'],with_for_update=True)
            if not target:raise s.Error('Stok tujuan sudah tidak tersedia untuk koreksi ini.')
            if delta>0:
                if source is target:
                    # Transfer yang semula dibatalkan sudah ditangani cabang
                    # lama==0. Tambahan tidak boleh berasal dari tujuan sendiri.
                    raise s.Error('Tidak ada tambahan stok yang dapat dibuktikan di gudang asal.')
                if source.jasa_id!=target.jasa_id:raise s.Error('Identitas pesanan sumber dan tujuan telah berubah. Periksa catatan lanjutan sebelum menambah transfer.')
                stok.atur(source,kind,stok.jumlah(source,kind)-delta,D(source.berat_total_kg)-berat_delta if kind=='barang' else None)
                stok.atur(target,kind,stok.jumlah(target,kind)+delta,D(target.berat_total_kg)+berat_delta if kind=='barang' else None)
            elif e.get('utuh') and n==0:
                target.warehouse_id=j.asal_id
                waktu=e.get('sumber_before',{}).get('waktu_penempatan')
                target.waktu_penempatan=datetime.fromisoformat(waktu) if waktu else None
            else:
                stok.atur(target,kind,stok.jumlah(target,kind)+delta,D(target.berat_total_kg)+berat_delta if kind=='barang' else None)
                at_origin=source is not None and source is not target and source.jasa_id==target.jasa_id and await db.scalar(select(lokasi(M)).where(M.id==source.id))==j.asal_id
                if at_origin:
                    stok.atur(source,kind,stok.jumlah(source,kind)-delta,D(source.berat_total_kg)-berat_delta if kind=='barang' else None)
                else:
                    source=salin_sumber(M,e['sumber_before'],user,-delta,-berat_delta if kind=='barang' else None,kind,j.asal_id)
                    source.jasa_id=target.jasa_id
                    db.add(source);await db.flush();e['sumber_id']=source.id;e['utuh']=False
                    r.sumber_id=str(source.id)
                e['sumber_after']=raw(source)
            e['tujuan_after']=raw(target);i.berat_kg=new_weight
        e['jumlah']=str(n);e['berat_kg']=str(i.berat_kg) if i.berat_kg is not None else None
        i.jumlah=n;i.dampak=e
        j.status='selesai'
        await db.flush()
        total=await s.terpakai(db,r.id)
        if not r.ditutup:r.status='selesai' if total>=D(r.jumlah_setuju) else 'dikirim' if total else 'disetujui'
        elif not total:r.status='gugur'
        subtotal=D(await db.scalar(select(func.coalesce(func.sum(Item.jumlah),0)).where(Item.transfer_id==j.id)))
        j.status='selesai' if subtotal>0 or j.pengiriman_pk_id else 'dibatalkan'
        await s.jejak(db,user,r,'koreksi_transfer',req['alasan'])
    return plan,apply


async def rancang(db,*,jenis,ident,user,req):
    await stok.izin(user);s.admin(user);await s.kunci(db)
    if not req.get('alasan','').strip():raise s.Error('Isi alasan koreksi.')
    if ident<=0:raise s.Error('Pilih catatan yang sah.')
    return await (rancang_permintaan(db,ident,req,user) if jenis=='permintaan' else rancang_transfer(db,ident,req,user))


async def periksa(db,*,jenis,ident,user,req):
    p,_=await rancang(db,jenis=jenis,ident=ident,user=user,req=req)
    p['isian']=bentuk(req)
    return dict(rancangan=p,pemeriksaan=sign(p))


async def simpan(db,*,jenis,ident,user,req):
    await stok.izin(user);s.admin(user);await s.kunci(db)
    key=f'koreksi-transfer-barang:{user.id}:{req["kunci"]}'
    signature=fingerprint([jenis,ident,bentuk(req)])
    old=await db.scalar(select(Peristiwa).where(Peristiwa.kunci_kiriman==key))
    if old:
        if old.muatan.get('sidik')!=signature:raise s.Error('Kunci koreksi telah dipakai untuk isian berbeda.')
        return dict(ok=True,peristiwa_id=old.id,ulang=True)
    if req.get('konfirmasi') is not True:raise s.Error('Periksa dampak dan centang konfirmasi terlebih dahulu.')
    p,apply=await rancang(db,jenis=jenis,ident=ident,user=user,req=req);p['isian']=bentuk(req)
    if not hmac.compare_digest(req.get('pemeriksaan',''),sign(p)):raise s.Error('Catatan terkait berubah. Periksa dampak ulang sebelum menyimpan; belum ada perubahan tersimpan.')
    await apply()
    ev=await catat(db,jenis='koreksi_transfer_barang',pelaku_id=user.id,kunci_kiriman=key,muatan=dict(jenis=jenis,ident=ident,isian=bentuk(req),rancangan=p,sidik=signature),terapkan=False)
    await db.commit();return dict(ok=True,peristiwa_id=ev.id,ulang=False)
