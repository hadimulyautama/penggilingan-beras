"""Pengelompokan baca-saja. Saldo tetap milik pembaca Stok, bukan buku baru.

ID pelanggan adalah batas pengelompokan; nama, nomor urut dan status pesanan
tidak pernah dipakai untuk menebak kepemilikan atau alokasi hasil campuran.
"""
from urllib.parse import urlencode

from sqlalchemy import select,text,or_

from app.models import (Jasa, Pelanggan, PurchaseBatch, DryingLot, DryingLotBatch,
                        MillingProcess, MillingProcessSource, InternalTransfer,
                        PkPurchaseBatch, PkGudang2Intake, PkTumpukanToSilo,
                        PolishingProcess, PolishingSiloUsage, Silo, SiloStorage,
                        OutgoingRecord, OutgoingItem, BrokenKeSilo, BerasKeSilo,
                        HasilSampingKeSilo)
from app.services import stok
from app.services.bahan_silo import kg_rinci

STATUS = (('','Semua pesanan'), ('berjalan','Berjalan'), ('selesai','Selesai'),
          ('dibatalkan','Dibatalkan'), ('digabung','Digabung'))


def alamat(pid, tab='ringkasan'):
    return f'/jasa/pelanggan/{pid}?' + urlencode({'tab':tab})


def ke(href, kembali):
    return href + ('&' if '?' in href else '?') + urlencode({'kembali_jasa':kembali})


def pesanan_baris(j):
    from app.database import now_local
    kini = now_local()
    return dict(id=j.id, kode=j.kode, status=j.status, catatan=j.catatan,
                tanggal=j.created_at, digabung_ke_id=j.digabung_ke_id,
                umur_hari=max((kini-(j.created_at or kini)).days,0),
                boleh_tutup=False, sebab='', boleh_batal=False)


async def daftar(db, *, cari='', status='', halaman=1):
    rows = (await db.execute(select(Pelanggan.id, Pelanggan.nama_pelanggan,
                                   Jasa.id, Jasa.status)
        .join(Jasa, Jasa.pelanggan_id==Pelanggan.id)
        .order_by(Pelanggan.nama_pelanggan, Pelanggan.id, Jasa.id))).all()
    grup = {}
    for pid,nama,jid,s in rows:
        g = grup.setdefault(pid, dict(id=pid,nama=nama,pesanan=[],status=set()))
        g['pesanan'].append(jid)
        g['status'].add(s)
    tickets=(await db.execute(text("SELECT DISTINCT p.id,p.nama_pelanggan FROM pelanggan p JOIN timbangan_transaksi t ON t.pelanggan_id=p.id WHERE t.arah='MASUK' AND t.jasa=TRUE"))).all()
    for pid,nama in tickets:
        grup.setdefault(pid,dict(id=pid,nama=nama,pesanan=[],status=set()))
    # Filter status menentukan pelanggan yang ditawarkan. Ringkasannya selalu
    # membaca SELURUH pesanannya agar pesanan selesai/batal tidak menyamarkan
    # barang yang ternyata masih tersisa.
    ids = [pid for pid,g in grup.items() if (not status or status in g['status'])
           and (not cari or cari.casefold() in g['nama'].casefold())]
    if cari:
        kode = (await db.scalars(select(Jasa.pelanggan_id).where(
            Jasa.kode.ilike('%'+cari+'%')))).all()
        ids = list(dict.fromkeys(ids+[pid for pid in kode if pid in grup
                    and (not status or status in grup[pid]['status'])]))
    jumlah = len(ids)
    akhir = max(1,(jumlah+9)//10)
    halaman = min(max(halaman,1),akhir)
    g1,g2 = await stok.pk_gudang1(db), await stok.pk_gudang2(db)
    kartu = [await pelanggan(db,pid,rinci=False,pk=(g1,g2))
             for pid in ids[(halaman-1)*10:halaman*10]]
    return dict(kartu=kartu,jumlah=jumlah,halaman=halaman,akhir=akhir)


async def pelanggan(db, pid, *, rinci=True, pk=None):
    p = await db.get(Pelanggan,pid)
    orders = list((await db.scalars(select(Jasa).where(Jasa.pelanggan_id==pid)
                                  .order_by(Jasa.id.desc()))).all())
    ada_tiket=await db.scalar(text("SELECT EXISTS(SELECT 1 FROM timbangan_transaksi WHERE arah='MASUK' AND jasa=TRUE AND pelanggan_id=:pid)"),{'pid':pid}) if not orders else True
    if p is None or not ada_tiket:
        return None
    ids = {j.id for j in orders}
    kode = {j.id:j.kode for j in orders}
    d = dict(id=pid,nama=p.nama_pelanggan,pesanan=[pesanan_baris(j) for j in orders],
             penerimaan=[],proses=[],stok=[],pengiriman=[],retur=[],kondisi=[],
             pk_kg=0,beras_kg=0,samping_kg=0,pekerjaan=0,berjalan=0)
    # Per pelanggan SATU panggilan dengan semua pesanan; hasil campuran tidak
    # pernah disalin sebagai saldo penuh ke setiap pesanan asal.
    produk = await stok.stok_produk(db,jasa_id=sorted(ids)) if ids else []
    g1,g2 = pk if pk is not None else (await stok.pk_gudang1(db),await stok.pk_gudang2(db))
    for gudang,rows in [('g1',g1),('g2',g2)]:
        for r in rows:
            if r.jasa_id not in ids:
                continue
            d['pk_kg'] += r.tersedia
            ident = r.kode if gudang=='g1' else r.intake_id
            href = '/stok/pk/detail?' + urlencode({'gudang':gudang,'kode' if gudang=='g1' else 'id':ident,'jasa':1})
            final = not r.berjalan and not r.belum_dicatat if gudang=='g1' else r.bobot_final
            d['stok'].append(dict(nama='PK',kode=r.kode,kg=r.tersedia,
                lokasi='Tumpukan · Gudang '+('1' if gudang=='g1' else '2'),
                final=final,href=href,pesanan=kode.get(r.jasa_id),rincian=r.bahan))
            if gudang=='g1' and r.belum_dicatat:
                d['stok'][-1]['kg']=None
    for k in produk:
        if abs(k.sisa_kg)<0.0001 and not k.alarm:
            continue
        bidang = 'beras_kg' if stok.adalah_beras(k.jenis) else 'samping_kg'
        d[bidang] += k.sisa_kg
        d['stok'].append(dict(nama=k.nama,kode='Saldo per pelanggan',kg=k.sisa_kg,
            lokasi='Gudang 2',final=not bool(k.belum_final_kg),pesanan=None,
            href='/stok-produk-jasa/detail?'+urlencode(dict(pelanggan_id=pid,jenis=k.jenis)),
            rincian=[(x.kode,kg_rinci(x.kg),x.ket or '') for x in k.hasil],
            kemasan_kg=k.dikemas_kg,curah_kg=k.curah_kg))
    from app.penggilingan.gudang1.services.bobot import dari_batch
    from app.penggilingan.gudang1.services.silo import _row_bobot
    batches = list((await db.scalars(select(PurchaseBatch).where(PurchaseBatch.jasa_id.in_(ids)))).all())
    for b in batches:
        if b.status_batch in ('baru','ditumpuk','di_dryer','dikeringkan'):
            bobot = dari_batch(b)
            d['stok'].append(dict(nama='Gabah '+b.kondisi_gabah,kode=b.kode_batch,
                kg=bobot.kg if bobot.diketahui else None,final=bobot.pasti,
                lokasi=('Pengering · Gudang 1' if b.status_batch in ('di_dryer','dikeringkan') else 'Menunggu penempatan · Gudang 1' if b.status_batch=='baru' else 'Tumpukan · Gudang 1'),
                pesanan=kode[b.jasa_id],href='/barang-masuk/'+str(b.timbangan_transaksi_id) if b.timbangan_transaksi_id else '',rincian=[]))
    for r,nama in (await db.execute(select(SiloStorage,Silo.nama_silo).join(Silo,Silo.id==SiloStorage.silo_id)
            .where(SiloStorage.jasa_id.in_(ids),SiloStorage.status=='terisi'))).all():
        b = await _row_bobot(db,r)
        d['stok'].append(dict(nama='Gabah · bahan proses',kode=nama,kg=b.kg if b.diketahui else None,
            final=b.pasti, lokasi='Silo · Gudang 1',pesanan=kode[r.jasa_id],href='',rincian=[]))
    from app.models import GabahKeringLot
    from app.penggilingan.gudang1.services.gabah_kering import pending_gabah_kering_kg
    for lot in (await db.scalars(select(GabahKeringLot).where(GabahKeringLot.jasa_id.in_(ids)))).all():
        kg = await pending_gabah_kering_kg(db,lot.id)
        if kg>0:
            d['stok'].append(dict(nama='Gabah kering ditimbang',kode=lot.kode_lot,kg=kg,final=True,
                lokasi='Tumpukan · Gudang 1',pesanan=kode[lot.jasa_id],href='',rincian=[]))
    # Riwayat penerimaan yang sudah dicatat tetap memakai pembaca Barang
    # Masuk; tiket asal terpisah dari pesanan pemilik catatan saat ini.
    from app.services.barang_masuk import riwayat
    diterima = await riwayat(db,g1=True,g2=True,jasa_ids=ids)
    for t in diterima:
        cat = [c for c in t['catatan'] if c['jasa_id'] in ids]
        if not cat:
            continue
        d['penerimaan'].append(dict(id=t['id'],kode=t['kode'],jenis=t['jenis_nama'] or t['jenis_kode'],
            catatan=cat,pesanan=kode.get(t['jasa_id'],'Pesanan asal belum tersedia'),
            status=t['status_tiket'],href=f"/barang-masuk/{t['id']}"))
    # Batch warisan tanpa FK tiket tidak dihilangkan atau dicocokkan lewat nama.
    for b in batches:
        if not b.timbangan_transaksi_id:
            d['penerimaan'].append(dict(id=None,kode=b.kode_batch,jenis='Gabah '+b.kondisi_gabah,
                catatan=[dict(berat=b.berat_total_kg,sumber_berat=b.sumber_berat,waktu=b.waktu_pembelian,status=b.status_batch)],
                pesanan=kode[b.jasa_id],status='Tautan tiket belum tersedia',href=''))
    for pkl in (await db.scalars(select(PkPurchaseBatch).where(PkPurchaseBatch.jasa_id.in_(ids),PkPurchaseBatch.timbangan_transaksi_id.is_(None)))).all():
        d['penerimaan'].append(dict(id=None,kode=pkl.kode_batch,jenis='PK',
            catatan=[dict(berat=pkl.berat_total_kg,sumber_berat=pkl.sumber_berat,waktu=pkl.waktu_pembelian,status=pkl.status_batch)],
            pesanan=kode[pkl.jasa_id],status='Tautan tiket belum tersedia',href=''))
    # Pending diambil dari kartu operasional di rute pemanggil; pembaca ini
    # tidak menawarkan penerimaan yang tidak ditawarkan sumber lama.
    pols = list((await db.scalars(select(PolishingProcess).where(PolishingProcess.jasa_id.in_(ids)).order_by(PolishingProcess.id.desc()))).all())
    dryers = list((await db.scalars(select(DryingLot).where(DryingLot.jasa_id.in_(ids)))).all())
    mills = list((await db.scalars(select(MillingProcess).where(MillingProcess.jasa_id.in_(ids)))).all())
    transfers = list((await db.scalars(select(InternalTransfer).where(InternalTransfer.jasa_id.in_(ids)))).all())
    for jenis,rows,attr,prefix in [('pengeringan',dryers,'kode_lot','riwayat-pengeringan'),('giling',mills,'kode_proses','riwayat-giling'),('transfer',transfers,'kode_transfer','riwayat-transfer'),('sosoh',pols,'kode_proses','riwayat-sosoh')]:
        for r in rows:
            aktif = jenis!='transfer' and r.status=='proses'
            if aktif:
                d['berjalan'] += 1
            kode_r = getattr(r,attr)
            d['proses'].append(dict(id=r.id,jenis=jenis,kode=kode_r,status=r.status,
                pesanan=kode.get(r.jasa_id),href=f'/proses-aktif/{jenis}/{kode_r}' if aktif else f'/{prefix}/{r.id}',
                sumber=[],hasil=None))
    if rinci:
        from app.services.barang_masuk import rincian_lokasi
        for t in d['penerimaan']:
            if t['id'] is not None:
                t['lokasi'],t['proses'],_=await rincian_lokasi(db,t['catatan'])
        from app.services.jasa import boleh_ditutup,pernah_ada_barang
        for j,r in zip(orders,d['pesanan']):
            r['boleh_tutup'],r['sebab'] = await boleh_ditutup(db,j.id)
            r['boleh_batal'] = j.status=='berjalan' and not await pernah_ada_barang(db,j.id)
        for r in d['proses']:
            await _sumber_proses(db,r,ids)
        await _pengiriman(db,d,ids)
    if d['pk_kg']>0:
        d['kondisi'].append('PK tersisa')
    if d['beras_kg']>0 or d['samping_kg']>0:
        d['kondisi'].append('Hasil belum diambil')
    if d['berjalan']:
        d['kondisi'].append('Proses berjalan')
    if any(r['nama'].startswith('Gabah') for r in d['stok']):
        d['kondisi'].append('Bahan masih di pabrik')
    return d


async def saring_kartu(db, rows, pid):
    """Penyaring tampilan saja, SESUDAH daftar dibatasi izin oleh sumbernya."""
    from sqlalchemy import text
    ids=set((await db.scalars(select(Jasa.id).where(Jasa.pelanggan_id==pid))).all())
    kode=set((await db.scalars(text("SELECT kode FROM timbangan_transaksi WHERE arah='MASUK' AND jasa=TRUE AND pelanggan_id=:pid"),{'pid':pid})).all())
    return [r for r in rows if r.kode in kode or
            bool(({r.jasa_id} | set(r.pemilik_ids or ())) & ids)]


async def _sumber_proses(db,r,ids):
    if r['jenis']=='pengeringan':
        for b in (await db.scalars(select(PurchaseBatch).join(DryingLotBatch,DryingLotBatch.purchase_batch_id==PurchaseBatch.id).where(DryingLotBatch.drying_lot_id==r['id'],PurchaseBatch.jasa_id.in_(ids)))).all():
            r['sumber'].append(dict(kode=b.kode_batch,kg=None,ket='Bobot masuk pada penerimaan; bukan berat setelah kering',href=f'/barang-masuk/{b.timbangan_transaksi_id}' if b.timbangan_transaksi_id else ''))
    elif r['jenis']=='giling':
        sources = (await db.scalars(select(MillingProcessSource).where(MillingProcessSource.milling_process_id==r['id']))).all()
        for s in sources:
            href,kode='', 'Asal belum tersedia'
            if s.drying_lot_id:
                b = await db.get(DryingLot,s.drying_lot_id)
                if b and b.jasa_id in ids:
                    kode,href=b.kode_lot,f'/riwayat-pengeringan/{b.id}'
            elif s.purchase_batch_id:
                b = await db.get(PurchaseBatch,s.purchase_batch_id)
                if b and b.jasa_id in ids:
                    kode,href=b.kode_batch,f'/barang-masuk/{b.timbangan_transaksi_id}' if b.timbangan_transaksi_id else ''
            r['sumber'].append(dict(kode=kode,kg=s.berat_terpakai_kg,ket='Terpakai' if s.berat_terpakai_kg is not None else 'Pemakaian belum final',href=href))
    elif r['jenis']=='transfer':
        t=await db.get(InternalTransfer,r['id'])
        m=await db.get(MillingProcess,t.milling_process_id)
        if m and m.jasa_id in ids:
            r['sumber'].append(dict(kode=m.kode_proses,kg=t.berat_kg,ket='PK ditransfer',href=f'/riwayat-giling/{m.id}'))
    else:
        await _sumber_sosoh(db,r,ids)
    if not r['sumber']:
        r['sumber'].append(dict(kode='Keterkaitan sumber belum tersedia',kg=None,ket='Tidak dibuat berdasarkan nama, tanggal atau berat',href=''))


async def _sumber_sosoh(db,r,ids):
    usages=(await db.scalars(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==r['id']).order_by(PolishingSiloUsage.id))).all()
    for u in usages:
        silo=await db.get(Silo,u.silo_id)
        # Hanya relasi struktural yang dibaca. Seluruh riwayat silo diperiksa,
        # bukan menyamakan waktu asal dengan waktu proses untuk menebak lot.
        direct=list((await db.scalars(select(PkGudang2Intake).where(PkGudang2Intake.silo_id==u.silo_id))).all())
        pindah=list((await db.scalars(select(PkTumpukanToSilo).where(PkTumpukanToSilo.silo_id==u.silo_id))).all())
        origins={i.id:i for i in direct}
        for x in pindah:
            i=await db.get(PkGudang2Intake,x.pk_gudang2_intake_id)
            if i:
                origins[i.id]=i
        lain=0
        for M in (BrokenKeSilo,BerasKeSilo,HasilSampingKeSilo):
            lain+=len((await db.scalars(select(M.id).where(M.silo_id==u.silo_id))).all())
        unik=len(origins)==1 and not lain and all(i.jasa_id in ids for i in origins.values())
        for i in origins.values():
            if i.jasa_id not in ids or not unik:
                continue
            kode,href=f'Penerimaan PK #{i.id}',f'/stok/pk/detail?gudang=g2&id={i.id}&jasa=1'
            if i.internal_transfer_id:
                t=await db.get(InternalTransfer,i.internal_transfer_id)
                if t and t.jasa_id in ids:
                    kode,href=t.kode_transfer,f'/riwayat-transfer/{t.id}'
            elif i.pk_purchase_batch_id:
                p=await db.get(PkPurchaseBatch,i.pk_purchase_batch_id)
                if p and p.jasa_id in ids:
                    kode,href=p.kode_batch,f'/barang-masuk/{p.timbangan_transaksi_id}' if p.timbangan_transaksi_id else ''
            r['sumber'].append(dict(kode=kode,kg=u.berat_terpakai_kg if unik else None,
                ket=(silo.nama_silo if silo else 'Silo tidak ditemukan')+' · '+('Terpakai' if unik and u.berat_akhir_kg is not None else 'Pemakaian belum final' if unik else 'Pembagian per sumber belum tersedia'),href=href))
        if not origins or not unik:
            r['sumber'].append(dict(kode=(silo.nama_silo if silo else 'Silo tidak ditemukan')+f' · pemakaian #{u.id}',kg=u.berat_terpakai_kg,
                ket='Terpakai per pemakaian silo; alokasi lot belum tersedia' if u.berat_akhir_kg is not None else 'Sisa belum dicatat; pemakaian belum final',href=''))
    hasil=await stok.output_sosoh(db,r['id'])
    bahan=sum(float(u.berat_terpakai_kg) for u in usages if u.berat_terpakai_kg is not None)
    final=bool(usages) and all(u.berat_akhir_kg is not None for u in usages) and r['status']=='selesai'
    r['hasil']=dict(jenis=hasil,bahan=bahan if final else None,
        susut=bahan-sum(hasil.values()) if final and hasil else None,final=final)


async def _pengiriman(db,d,ids):
    from app.penggilingan.inventory.models import CustomerReturn,CustomerReturnItem
    rows=(await db.execute(select(OutgoingRecord,OutgoingItem).join(OutgoingItem,OutgoingItem.outgoing_record_id==OutgoingRecord.id)
          .where(OutgoingItem.jasa_id.in_(ids)).order_by(OutgoingRecord.id.desc(),OutgoingItem.id))).all()
    grouped={}
    for o,i in rows:
        g=grouped.setdefault(o.id,dict(id=o.id,kode=o.kode,status=o.status,href=f'/barang-keluar/{o.id}',item=[]))
        g['item'].append(dict(jenis=i.item_type,kg=i.berat_kg,pesanan_id=i.jasa_id))
    d['pengiriman']=list(grouped.values())
    rs=(await db.scalars(select(CustomerReturn).join(CustomerReturnItem,CustomerReturnItem.customer_return_id==CustomerReturn.id)
        .where(or_(CustomerReturnItem.jasa_id.in_(ids),CustomerReturn.pelanggan_id==d['id']))
        .distinct().order_by(CustomerReturn.id.desc()))).all()
    for x in rs:
        pemilik=set((await db.scalars(select(CustomerReturnItem.jasa_id).where(CustomerReturnItem.customer_return_id==x.id))).all())
        status='Milik pabrik' if pemilik=={None} else 'Titipan jasa' if pemilik<=set(ids) else 'Kepemilikan per item'
        d['retur'].append(dict(kode=x.kode,href=f'/retur/{x.id}',status='Retur · '+status+' · Pengeluaran asal belum tertaut'))
