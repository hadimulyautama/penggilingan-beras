"""Permintaan dan perpindahan lokasi umum, terpisah dari alih kepemilikan.

Saldo tidak ditulis ketika meminta atau menyetujui. Pencatatan fisik memakai
kunci inventory yang sama dengan produksi/pengeluaran, bukti sumber dan
nonce. Semua bagian satu pencatatan disimpan dalam satu transaksi.
"""
from decimal import Decimal
from sqlalchemy import select, func, or_
from app.database import now_local
from app.models import (PermintaanTransferBarang as Permintaan, TransferBarang as Transfer,
    TransferBarangItem as Item, Warehouse, User, Peristiwa, PermintaanPk, Jasa,
    FinishedGoodsStock, ByproductStock, PackagingPurchase)
from app.services import transfer_barang_sumber as stok
from app.services.kepemilikan import fingerprint, raw
from app.services.peristiwa import catat
from app.peran import can_see_financials
from hmu_identitas import peran as P
D=stok.D
Error=stok.TransferBarangError
AKTIF=('disetujui','dikirim')


async def kunci(db):
    from app.services.barang_keluar import _kunci_saldo_keluar
    await _kunci_saldo_keluar(db)


def admin(user):
    if not can_see_financials(user):raise PermissionError('Persetujuan, penutupan dan koreksi hanya tersedia untuk Admin.')


async def terpakai(db,rid):
    return D(await db.scalar(select(func.coalesce(func.sum(Item.jumlah),0)).join(Transfer).where(Item.permintaan_id==rid,Transfer.status=='selesai')))


async def cadangan(db,jenis,id,*,kecuali=()):
    rs=(await db.scalars(select(Permintaan).where(Permintaan.sumber_jenis==jenis,Permintaan.sumber_id==str(id),Permintaan.status.in_(AKTIF),Permintaan.ditutup.is_(False),Permintaan.id.not_in(kecuali)))).all()
    return sum([max(D(0),D(r.jumlah_setuju)-await terpakai(db,r.id)) for r in rs],D(0))


async def cek_sumber(db,r,user,*,kecuali=(),terkunci=False):
    s=await stok.sumber(db,user=user,jenis=r.sumber_jenis,id=r.sumber_id,kunci=terkunci)
    if s['asal_id']!=r.asal_id or s['pemilik_kunci']!=r.sumber['pemilik_kunci']:
        raise Error('Lokasi atau pemilik sumber sudah berubah. Periksa permintaan; transfer tidak disimpan.')
    s['bebas']=max(D(0),s['tersedia']-await cadangan(db,r.sumber_jenis,r.sumber_id,kecuali=kecuali))
    return s


async def tujuan(db,asal_id,tujuan_id):
    from app.services.transfer_lokasi import tujuan_sah
    try:await tujuan_sah(db,asal_id,tujuan_id)
    except ValueError as e:raise Error(str(e)) from None
    return await db.get(Warehouse,tujuan_id)


async def jejak(db,user,r,aksi,muatan):
    from app.services.activity_log import log_activity
    await log_activity(db,table_name='permintaan_transfer_barang',record_id=r.id,action='UPDATE' if aksi!='minta' else 'INSERT',changed_by=user.id,aksi='transfer_barang_'+aksi,new_value=str(muatan))


async def minta(db,*,user,jenis,id,tujuan_id,jumlah,kunci_kiriman,commit=True,kabari=True):
    await stok.izin(user);await kunci(db)
    if jenis=='pk_giling':
        from app.services.transfer_pk_lokasi import minta as minta_pk
        return await minta_pk(db,user=user,id=id,tujuan_id=tujuan_id,jumlah=jumlah,kunci=kunci_kiriman,commit=commit,kabari=kabari)
    body=dict(jenis=jenis,id=str(id),tujuan_id=tujuan_id,jumlah=str(stok.angka(jumlah,bulat=jenis in stok.INTEGER)))
    key=f'transfer-minta:{user.id}:{kunci_kiriman}';sidik=fingerprint(body)
    old=await db.scalar(select(Permintaan).where(Permintaan.kunci==key))
    if old:
        if old.sidik!=sidik:raise Error('Kunci permintaan sudah dipakai untuk isian berbeda.')
        return dict(ok=True,id=-old.id,ulang=True)
    s=await stok.sumber(db,user=user,jenis=jenis,id=id,kunci=True)
    t=await tujuan(db,s['asal_id'],tujuan_id)
    if not can_see_financials(user) and user.default_warehouse_id not in (s['asal_id'],t.id):raise PermissionError('Permintaan harus melibatkan gudang kerja Anda.')
    n=D(body['jumlah']);bebas=max(D(0),s['tersedia']-await cadangan(db,jenis,s['id']))
    if n>bebas:raise Error('Jumlah melebihi stok bebas sumber.')
    if s['seluruh'] and (n!=s['total'] or n!=bebas):raise Error('Lot ini hanya dapat dipindah utuh sebelum digunakan proses atau pengeluaran.')
    r=Permintaan(sumber_jenis=jenis,sumber_id=s['id'],sumber=stok.publik(s),asal_id=s['asal_id'],tujuan_id=t.id,satuan=s['satuan'],jumlah_minta=n,jumlah_setuju=0,status='diminta',diminta_oleh=user.id,waktu_minta=now_local(),ditutup=False,kunci=key,sidik=sidik)
    db.add(r);await db.flush();await jejak(db,user,r,'minta',f"{s['kode']} · {n} {s['satuan']} · {s['asal']} → {t.nama_gudang}; pemilik tetap {s['pemilik']}")
    if kabari:
        from app.services.notification import create_notification
        await create_notification(db,tipe='transfer_barang',pesan=f"Permintaan transfer {s['label']} · {n} {s['satuan']}. Periksa di halaman Transfer.",target_role=P.ADMIN,table_name='permintaan_transfer_barang',record_id=r.id)
    if commit:await db.commit()
    else:await db.flush()
    return dict(ok=True,id=-r.id,ulang=False)


async def setujui_banyak(db,*,user,items,commit=True):
    await stok.izin(user);admin(user);await kunci(db)
    ids=[int(x['permintaan_id']) for x in items]
    if not ids or len(ids)!=len(set(ids)):raise Error('Pilih permintaan yang berbeda.')
    rows={r.id:r for r in (await db.scalars(select(Permintaan).where(Permintaan.id.in_(ids)).order_by(Permintaan.id).with_for_update())).all()}
    for x in items:
        r=rows.get(int(x['permintaan_id']))
        if not r or r.status!='diminta':raise Error('Permintaan sudah berubah. Perbarui status.')
        s=await cek_sumber(db,r,user,terkunci=True);n=stok.angka(x['berat_kg'],bulat=r.sumber_jenis in stok.INTEGER)
        if n>s['bebas']:raise Error('Stok bebas sumber tidak cukup untuk persetujuan.')
        if s['seluruh'] and (n!=s['total'] or n!=s['bebas']):raise Error('Lot ini hanya dapat dipindah utuh sebelum digunakan.')
        val=x.get('tujuan','');tid=int(val.partition(':')[2]) if val.startswith('gudang:') and val.partition(':')[2].isdigit() else r.tujuan_id
        await tujuan(db,r.asal_id,tid)
        r.tujuan_id=tid;r.jumlah_setuju=n;r.status='disetujui';r.disetujui_oleh=user.id;r.waktu_setuju=now_local()
        await db.flush();await jejak(db,user,r,'setujui',f"Disetujui {n} {r.satuan}; belum memindahkan stok.")
    if commit:await db.commit()
    return dict(ok=True)


async def buat(db,*,user,items,kunci_kiriman,pengiriman_pk_id=None,commit=True):
    await stok.izin(user);await kunci(db)
    payload=dict(items=sorted([dict(permintaan_id=int(x['permintaan_id']),jumlah=str(stok.angka(x['berat_kg']))) for x in items],key=lambda x:x['permintaan_id']),pengiriman_pk_id=pengiriman_pk_id)
    key=f'transfer-barang:{user.id}:{kunci_kiriman}';sidik=fingerprint(payload)
    old=await db.scalar(select(Transfer).where(Transfer.kunci==key))
    if old:
        if old.sidik!=sidik:raise Error('Kunci kiriman sudah dipakai untuk muatan berbeda.')
        return dict(ok=True,id=-old.id,ulang=True)
    ids=[x['permintaan_id'] for x in payload['items']]
    if not ids or len(ids)!=len(set(ids)):raise Error('Pilih permintaan yang berbeda.')
    rows={r.id:r for r in (await db.scalars(select(Permintaan).where(Permintaan.id.in_(ids)).order_by(Permintaan.id).with_for_update())).all()}
    route=None;owner=None;plans=[]
    for x in payload['items']:
        r=rows.get(x['permintaan_id'])
        if not r or r.status not in AKTIF or r.ditutup:raise Error('Pilih permintaan yang sudah disetujui dan belum ditutup.')
        if not can_see_financials(user) and user.default_warehouse_id!=r.asal_id:raise PermissionError('Pencatatan hanya oleh operator gudang asal atau Admin.')
        s=await cek_sumber(db,r,user,kecuali=ids,terkunci=True);n=stok.angka(x['jumlah'],bulat=r.sumber_jenis in stok.INTEGER)
        if n>max(D(0),D(r.jumlah_setuju)-await terpakai(db,r.id)) or n>s['bebas']:raise Error('Jumlah melebihi sisa persetujuan atau stok bebas sumber.')
        await tujuan(db,r.asal_id,r.tujuan_id)
        lintasan=(r.asal_id,r.tujuan_id)
        if route and (route!=lintasan or owner!=s['pemilik_kunci']):raise Error('Gabungkan hanya barang dengan asal, tujuan, dan pemilik yang sama.')
        route=lintasan;owner=s['pemilik_kunci'];plans.append((r,n,s))
    j=Transfer(asal_id=route[0],tujuan_id=route[1],pengiriman_pk_id=pengiriman_pk_id,dibuat_oleh=user.id,waktu=now_local(),status='selesai',kunci=key,sidik=sidik)
    db.add(j);await db.flush()
    effects=[]
    for r,n,s in plans:
        # Pembaca/penulis memeriksa lagi sesudah lot sebelumnya. Dua
        # permintaan atas satu baris tidak bisa memakai kilogram yang sama.
        efek,kg=await stok.pindah(db,user=user,jenis=r.sumber_jenis,id=r.sumber_id,tujuan_id=r.tujuan_id,n=n)
        i=Item(transfer_id=j.id,permintaan_id=r.id,jumlah=n,berat_kg=kg,dampak=efek);db.add(i);await db.flush()
        total=await terpakai(db,r.id);r.status='selesai' if total>=D(r.jumlah_setuju) else 'dikirim'
        effects.append(dict(item_id=i.id,permintaan_id=r.id,**efek));await jejak(db,user,r,'catat',f'Transfer B-{j.id} · {n} {r.satuan}; stok asal berkurang dan tujuan bertambah, pemilik tetap.')
    await catat(db,jenis='transfer_barang',pelaku_id=user.id,kunci_kiriman=key,muatan=dict(transfer_id=j.id,asal_id=j.asal_id,tujuan_id=j.tujuan_id,items=effects),terapkan=False)
    if commit:await db.commit()
    else:await db.flush()
    return dict(ok=True,id=-j.id,ulang=False)


async def keputusan(db,*,user,rid,aksi,alasan):
    await stok.izin(user);admin(user);await kunci(db)
    if not alasan.strip():raise Error('Isi alasan keputusan.')
    r=await db.get(Permintaan,rid,with_for_update=True)
    if not r or aksi=='tolak' and r.status!='diminta' or aksi=='tutup-sisa' and r.status not in AKTIF:raise Error('Permintaan sudah berubah. Perbarui status.')
    n=await terpakai(db,r.id)
    r.status='ditolak' if aksi=='tolak' else 'selesai' if n else 'gugur';r.ditutup=True;r.alasan=alasan.strip()
    await jejak(db,user,r,aksi,alasan.strip());await db.commit();return dict(ok=True)


async def tambahan(db,*,user):
    await stok.izin(user)
    is_admin=can_see_financials(user);wid=user.default_warehouse_id
    q=select(Permintaan).order_by(Permintaan.id)
    if not is_admin:q=q.where(or_(Permintaan.asal_id==wid,Permintaan.tujuan_id==wid))
    rs=list((await db.scalars(q)).all())
    whs={w.id:w for w in (await db.scalars(select(Warehouse))).all()}
    people={u.id:u.nama for u in (await db.scalars(select(User).where(User.id.in_({r.diminta_oleh for r in rs})))).all()}
    from app.services.transfer_lokasi import daftar as daftar_lokasi
    locations=await daftar_lokasi(db)
    result=[]
    for r in rs:
        n=await terpakai(db,r.id);s=r.sumber;available=D(0)
        if r.status in ('diminta',*AKTIF):
            try:available=(await cek_sumber(db,r,user,kecuali=(r.id,)))['bebas']
            except (Error,PermissionError):pass
        result.append(dict(jenis_dokumen='perintah' if r.kunci.startswith('transfer-perintah:') else 'permintaan',id=-r.id,nomor='PTR-'+r.waktu_minta.strftime('%Y%m%d')+'-'+str(r.id).zfill(4),jenis_transfer='barang',sumber_jenis=r.sumber_jenis,sumber_id=r.sumber_id,satuan=r.satuan,seluruh=s['seluruh'],lot=s['label']+' · '+s['kode'],pemilik=s['pemilik'],pemilik_kunci=s['pemilik_kunci'],peminta=people.get(r.diminta_oleh,'Operator'),waktu=r.waktu_minta.isoformat(),status=r.status,sebab=r.alasan,
            asal_id=r.asal_id,asal=whs[r.asal_id].nama_gudang,asal_lokasi=locations.get(r.asal_id,{}),company_id=locations.get(r.asal_id,{}).get('company_id'),tujuan_lokasi=locations.get(r.tujuan_id,{}),tujuan_id=r.tujuan_id,tujuan_nama='Tumpukan' if r.sumber_jenis=='pk_tumpukan' else 'Area stok',tujuan_gudang=whs[r.tujuan_id].nama_gudang,silo_id=None,tujuan='ditumpuk',diminta=str(r.jumlah_minta),disetujui=str(r.jumlah_setuju),sisa=str(max(D(0),D(r.jumlah_setuju)-n)),selesai_kg=str(n),perjalanan_kg='0',bebas=str(available),bertahap=True,boleh_catat=is_admin or wid==r.asal_id))
    jq=select(Transfer).order_by(Transfer.id.desc()).limit(100)
    if not is_admin:jq=jq.where(or_(Transfer.asal_id==wid,Transfer.tujuan_id==wid))
    journeys=[];linked=[]
    from app.services import pengiriman_pk as pk
    for j in (await db.scalars(jq)).all():
        pairs=(await db.execute(select(Item,Permintaan).join(Permintaan).where(Item.transfer_id==j.id).order_by(Item.id))).all()
        its=[dict(id=-i.id,nomor=None,permintaan_id=-r.id,lot=r.sumber['label']+' · '+r.sumber['kode'],jumlah=str(i.jumlah),satuan=r.satuan,berat_kg=str(i.berat_kg) if i.berat_kg is not None else None,pemilik=r.sumber['pemilik'],jenis_transfer='barang',sumber_jenis=r.sumber_jenis,jasa_id=r.sumber['pemilik_id'] if r.sumber_jenis!='karung' else None,jasa=r.sumber['pemilik_id'] is not None,transfer_id=None,pemindahan=[]) for i,r in pairs]
        kg=sum((D(i.berat_kg) for i,r in pairs),D(0));lembar=sum((D(i.jumlah) for i,r in pairs if r.satuan=='lembar'),D(0))
        if j.pengiriman_pk_id:
            p=await pk.rincian(db,j.pengiriman_pk_id);its.extend(p['items']);kg+=D(p['total']);linked.append(j.pengiriman_pk_id)
        journeys.append(dict(id=-j.id,nomor='TRF-'+j.waktu.strftime('%Y%m%d')+'-'+str(j.id).zfill(4),jenis_transfer='barang',waktu=j.waktu.isoformat(),waktu_selesai=j.waktu.isoformat(),status=j.status,pakai_kendaraan=False,nomor_polisi=None,nama_sopir=None,tiket_id=None,total=str(kg),lembar=str(lembar),items=its,
            lintasan=dict(asal=dict(gudang_id=j.asal_id,nama=whs[j.asal_id].nama_gudang),tujuan=dict(gudang_id=j.tujuan_id,silo_id=None,nama='Area stok · '+whs[j.tujuan_id].nama_gudang)),bobot_timbang_kg=None,selisih_kg=None,alasan=None))
    return dict(permintaan=result,pengiriman=journeys,linked=linked,tujuan_barang=[dict(nilai='gudang:'+str(k),id=k,**v,nama=' → '.join([v['pabrik_nama'],v['gudang_nama'],'Area stok'])) for k,v in locations.items() if v['aktif']],boleh_minta_barang=True)


async def katalog(db,*,user,jenis='',warehouse_id=None,cari='',halaman=1,posisi=0):
    """Pemilih sumber fisik, semua jenis memakai izin dan saldo yang sama."""
    from sqlalchemy import literal,union_all
    from app.services.transfer_lokasi import daftar as daftar_lokasi
    from app.services.cakupan_fasilitas import lokasi
    from hmu_identitas.ruang_data import RuangData
    await stok.izin(user)
    if jenis and jenis not in stok.MODEL:raise Error('Pilih jenis barang yang tersedia.')
    locations=await daftar_lokasi(db)
    ruang=RuangData.lingkungan()
    whs={k:v for k,v in locations.items() if v['aktif'] and (not ruang or v['company_id']==ruang.company_id)}
    candidates=[]
    for kind in ([jenis] if jenis else stok.MODEL):
        M=stok.MODEL[kind]
        q=select(literal(kind).label('jenis'),M.id.label('id'))
        if kind=='barang':q=q.where(M.curah_kemas_ulang.is_(False),M.jumlah_karung>0)
        elif kind=='curah_barang':q=q.where(M.curah_kemas_ulang.is_(True),M.berat_total_kg>0)
        elif kind=='curah':q=q.where(M.berat_kg>0)
        elif kind=='karung':q=q.where(M.jumlah_lembar>0)
        elif kind=='gabah':q=q.where(M.status_batch=='baru',M.berat_total_kg>0)
        elif kind=='pk_tumpukan':q=q.where(M.tujuan=='ditumpuk',M.berat_kg>0)
        elif kind=='pk_giling':q=q.where(M.status.in_(['proses','selesai']))
        else:q=q.where(M.berat_timbang_kg>0)
        if kind!='karung':
            q=q.where(lokasi(M).in_(whs))
            if warehouse_id:q=q.where(lokasi(M)==warehouse_id)
            if not can_see_financials(user) and kind not in ('pk_giling','pk_tumpukan'):q=q.where(or_(lokasi(M)==user.default_warehouse_id,M.jasa_id.is_(None)))
        candidates.append(q)
    pool=union_all(*candidates).subquery()
    total=await db.scalar(select(func.count()).select_from(pool))
    offset=posisi or (halaman-1)*20
    found=[];scanned=0
    # Halaman tidak berhenti pada 20 kandidat yang sudah habis. Lanjutkan
    # membaca sumber sampai ada pilihan yang dapat diminta atau batas kerja.
    while offset<total and len(found)<20 and scanned<500:
        rows=(await db.execute(select(pool).order_by(pool.c.jenis,pool.c.id.desc()).offset(offset).limit(50))).all()
        for kind,id in rows:
            vals=[str(id)]
            if kind in ('pk_giling','pk_tumpukan'):
                pk=(await stok.pk_sumber(db)).get(('giling:' if kind=='pk_giling' else 'tumpukan:')+str(id))
                vals=[str(id)+'~'+str(owner or 0) for owner in {b.pemilik_id for b in pk.stok.bagian}] if pk else []
            if kind=='karung':
                row=await db.get(stok.MODEL[kind],id)
                from app.services.transfer_karung_lokasi import penempatan
                _,pools=await penempatan(db,row.packaging_material_id,row.package_size_id,row.brand_id,row.pelanggan_id)
                vals=[f'{id}@{wid}' for rid,wid in pools if rid==id and pools[(rid,wid)]>0 and wid in whs and (not warehouse_id or wid==warehouse_id)]
            for val in vals:
                try:source=await stok.sumber(db,user=user,jenis=kind,id=val)
                except (Error,PermissionError):continue
                n=max(D(0),source['tersedia']-await cadangan(db,kind,source['id']))
                search=' '.join(str(source.get(k,'')) for k in ('label','kode','pemilik','asal'))+' '+str(source.get('asal_lokasi',{}).get('pabrik_nama',''))
                if n<=0 or cari and cari.casefold() not in search.casefold():continue
                source['tersedia']=n;found.append(stok.publik(source))
            offset+=1;scanned+=1
            if len(found)>=20 or scanned>=500:break
    return dict(items=found,posisi=offset,lanjut=offset<total,
        gudang=[dict(id=k,**v,nama=' → '.join([v['pabrik_nama'],v['gudang_nama']])) for k,v in whs.items()])


async def periksa_gabungan(db,*,user,items):
    """Bukti lintasan semua tipe sebelum satu pun saldo diubah."""
    from app.services import pengiriman_pk as pk
    route=None;owner=None
    for x in items:
        id=int(x['permintaan_id'])
        if id<0:
            r=await db.get(Permintaan,-id)
            if not r:raise Error('Permintaan tidak ditemukan.')
            cur=(r.asal_id,r.tujuan_id,None);who=r.sumber['pemilik_kunci']
        else:
            r=await db.get(PermintaanPk,id)
            if not r:raise Error('Permintaan PK tidak ditemukan.')
            _,a,t,silo=await pk._rute(db,r)
            cur=(a.id,t.id,silo.id if silo else None)
            customer=(await db.get(Jasa,r.jasa_id)).pelanggan_id if r.jasa_id else None
            who='pelanggan:'+str(customer) if customer else 'pabrik'
        if route and (route!=cur or owner!=who):raise Error('Gabungkan hanya barang dengan asal, tujuan, dan pemilik yang sama.')
        route=cur;owner=who
