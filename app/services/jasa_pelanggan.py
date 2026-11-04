"""Pengelompokan baca-saja. Saldo tetap milik pembaca Stok, bukan buku baru.

ID pelanggan adalah batas pengelompokan; nama, nomor urut dan status pesanan
tidak pernah dipakai untuk menebak kepemilikan atau alokasi hasil campuran.
"""
from app.performa import dalam
from urllib.parse import urlencode

from app.performa import baca_sekali

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
    """Pilih sepuluh pelanggan di SQL sebelum membaca saldo per pelanggan."""
    from sqlalchemy import func
    ada_jasa = select(Jasa.id).where(Jasa.pelanggan_id==Pelanggan.id).exists()
    ada_tiket = text("EXISTS (SELECT 1 FROM timbangan_transaksi t WHERE t.pelanggan_id=pelanggan.id AND t.arah='MASUK' AND t.jasa=TRUE)")
    q = select(Pelanggan.id).where(or_(ada_jasa,ada_tiket))
    if status:
        q=q.where(select(Jasa.id).where(Jasa.pelanggan_id==Pelanggan.id,Jasa.status==status).exists())
    if cari:
        pola='%'+cari.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        q=q.where(or_(Pelanggan.nama_pelanggan.ilike(pola,escape='\\'),
            select(Jasa.id).where(Jasa.pelanggan_id==Pelanggan.id,Jasa.kode.ilike(pola,escape='\\')).exists()))
    jumlah=await db.scalar(select(func.count()).select_from(q.subquery()))
    akhir=max(1,(jumlah+9)//10)
    halaman=min(max(halaman,1),akhir)
    ids=list((await db.scalars(q.order_by(Pelanggan.nama_pelanggan,Pelanggan.id)
        .offset((halaman-1)*10).limit(10))).all())
    g1,g2 = (await stok.pk_gudang1(db),await stok.pk_gudang2(db)) if ids else ([],[])
    kartu=[await pelanggan(db,pid,rinci=False,pk=(g1,g2),rincian={'tab':'daftar'}) for pid in ids]
    return dict(kartu=kartu,jumlah=jumlah,halaman=halaman,akhir=akhir)


def halaman_pesanan(rows, pilihan):
    """Batas penyajian saja; seluruh pesanan tetap membentuk saldo pelanggan."""
    cari = str(pilihan.get('cari') or '').strip()[:200]
    status = pilihan.get('status') if pilihan.get('status') in dict(STATUS) else ''
    def angka(value):
        try:
            return max(1, int(value))
        except (ValueError, TypeError):
            return 1
    fokus = str(pilihan.get('fokus') or '')
    cocok = [r for r in rows if (not status or r['status']==status)
             and (not cari or cari.casefold() in (r['kode']+' '+(r['catatan'] or '')).casefold())]
    di_luar_filter = False
    if fokus and any(str(r['id'])==fokus for r in rows) and not any(str(r['id'])==fokus for r in cocok):
        cocok, cari, status, di_luar_filter = rows, '', '', True
    jumlah, ukuran = len(cocok), 20
    akhir = max(1, (jumlah+ukuran-1)//ukuran)
    halaman = min(angka(pilihan.get('halaman')), akhir)
    if fokus:
        index = next((i for i,r in enumerate(cocok) if str(r['id'])==fokus), None)
        if index is not None:
            halaman = index//ukuran+1
    mulai = (halaman-1)*ukuran
    return dict(baris=cocok[mulai:mulai+ukuran], halaman=halaman, akhir=akhir,
                jumlah=jumlah, dari=mulai+1 if jumlah else 0, sampai=min(mulai+ukuran,jumlah),
                cari=cari, status=status, fokus_di_luar_filter=di_luar_filter)


async def _pesanan_sql(db,q,pilihan):
    """Filter dan fokus tautan lama dipenuhi sebelum LIMIT 20."""
    from sqlalchemy import func
    cari=str(pilihan.get('cari') or '').strip()[:200]
    status=pilihan.get('status') if pilihan.get('status') in dict(STATUS) else ''
    fokus=str(pilihan.get('fokus') or '')
    fid=int(fokus) if fokus.isascii() and fokus.isdigit() and len(fokus)<11 and str(int(fokus))==fokus and int(fokus)<=2147483647 else None
    def saring(q):
        if status:q=q.where(Jasa.status==status)
        if cari:
            pola='%'+cari.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
            q=q.where((Jasa.kode+' '+func.coalesce(Jasa.catatan,'')).ilike(pola,escape='\\'))
        return q
    selected=saring(q)
    luar=False
    if fid is not None and await db.scalar(select(q.where(Jasa.id==fid).exists())):
        if not await db.scalar(select(selected.where(Jasa.id==fid).exists())):
            selected=q;cari='';status='';luar=True
    count=await db.scalar(select(func.count()).select_from(selected.subquery()))
    akhir=max(1,(count+19)//20)
    try:page=min(akhir,max(1,int(pilihan.get('halaman') or 1)))
    except (ValueError,TypeError):page=1
    if fid is not None and await db.scalar(select(selected.where(Jasa.id==fid).exists())):
        before=await db.scalar(select(func.count()).select_from(selected.where(Jasa.id>fid).subquery()))
        page=before//20+1
    rows=(await db.execute(selected.order_by(Jasa.id.desc()).offset((page-1)*20).limit(20))).all()
    return rows,dict(halaman=page,akhir=akhir,jumlah=count,dari=(page-1)*20+1 if count else 0,
        sampai=min(page*20,count),cari=cari,status=status,fokus_di_luar_filter=luar)


async def pelanggan(db, pid, *, rinci=True, pk=None, read_scope=None, ringkasan_pesanan=None, kebutuhan=None, rincian=None):
    args=dict(rinci=rinci,pk=pk,read_scope=read_scope,ringkasan_pesanan=ringkasan_pesanan,kebutuhan=kebutuhan,rincian=rincian)
    if kebutuhan is not None or rincian is not None:
        return await _pelanggan_halaman(db,pid,**args)
    return await _pelanggan(db,pid,**args)


from app.performa import tampilan_singkat

@tampilan_singkat
async def _pelanggan_halaman(db,pid,**kwargs):
    return await _pelanggan(db,pid,**kwargs)


async def _pelanggan(db,pid,*,rinci=True,pk=None,read_scope=None,ringkasan_pesanan=None,kebutuhan=None,rincian=None):
    p=await db.get(Pelanggan,pid)
    cepat=kebutuhan is not None or rincian is not None
    q=select(Jasa.id,Jasa.kode,Jasa.status,Jasa.catatan,Jasa.created_at,Jasa.digabung_ke_id).where(Jasa.pelanggan_id==pid)
    meta=(await db.execute(select(Jasa.id,Jasa.kode,Jasa.status).where(Jasa.pelanggan_id==pid))).all() if cepat else None
    orders=(await db.execute(q.order_by(Jasa.id.desc()))).all() if not cepat else []
    semua=meta if cepat else orders
    ada_tiket=await db.scalar(text("SELECT EXISTS(SELECT 1 FROM timbangan_transaksi WHERE arah='MASUK' AND jasa=TRUE AND pelanggan_id=:pid)"),{'pid':pid}) if not semua else True
    if p is None or not ada_tiket:return None
    ids={j.id for j in semua}
    kode={j.id:j.kode for j in semua}
    pag=None
    if cepat:
        if ringkasan_pesanan is not None:
            orders,pag=await _pesanan_sql(db,q,ringkasan_pesanan)
        elif kebutuhan:
            # Portal hanya membutuhkan tanda bahwa pelanggan punya pesanan.
            orders=(await db.execute(q.order_by(Jasa.id.desc()).limit(1))).all() if semua else []
    d=dict(id=pid,nama=p.nama_pelanggan,pesanan=[pesanan_baris(j) for j in orders],
        pesanan_jumlah=len(semua),pesanan_berjalan=sum(j.status=='berjalan' for j in semua),
        penerimaan=[],proses=[],stok=[],pengiriman=[],retur=[],kondisi=[],
        pk_kg=0,beras_kg=0,samping_kg=0,pekerjaan=0,berjalan=0)
    if ringkasan_pesanan is not None:
        if pag is None:d['pesanan_paginasi']=halaman_pesanan(d['pesanan'],ringkasan_pesanan)
        else:
            pag['baris']=d['pesanan']
            d['pesanan_paginasi']=pag
    # Per pelanggan SATU panggilan dengan semua pesanan; hasil campuran tidak
    # pernah disalin sebagai saldo penuh ke setiap pesanan asal.
    baca_stok = kebutuhan in (None,'beranda','barang')
    baca_masuk = kebutuhan in (None,'beranda','masuk')
    baca_proses = kebutuhan in (None,'beranda','jasa')
    if baca_stok:
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
                kemasan_kg=(k.dikemas_otomatis_kg if k.ukuran_kemasan_otomatis else k.dikemas_kg),
                curah_kg=(k.curah_otomatis_kg if k.ukuran_kemasan_otomatis else k.curah_kg),
                kemasan_otomatis=bool(k.ukuran_kemasan_otomatis),
                karung_otomatis=k.jumlah_karung_otomatis,ukuran_otomatis=k.ukuran_kemasan_otomatis))
    from app.penggilingan.gudang1.services.bobot import dari_batch
    from app.penggilingan.gudang1.services.silo import _row_bobot
    q_batches=select(PurchaseBatch.id,PurchaseBatch.jasa_id,PurchaseBatch.status_batch,
        PurchaseBatch.kode_batch,PurchaseBatch.kondisi_gabah,PurchaseBatch.berat_total_kg,
        PurchaseBatch.sumber_berat,PurchaseBatch.berat_perkiraan_kg,PurchaseBatch.retur_supplier_keluar_kg,
        PurchaseBatch.timbangan_transaksi_id,PurchaseBatch.waktu_pembelian).where(dalam(db, PurchaseBatch.jasa_id, ids))
    if not baca_masuk or rincian is not None:q_batches=q_batches.where(PurchaseBatch.status_batch.in_(('baru','ditumpuk','di_dryer','dikeringkan')))
    elif kebutuhan=='beranda':
        # Beranda hanya membutuhkan tanda penerimaan, bukan daftar lengkap.
        terakhir=select(PurchaseBatch.id).where(dalam(db,PurchaseBatch.jasa_id,ids),
            PurchaseBatch.timbangan_transaksi_id.is_(None),PurchaseBatch.status_batch!='ditolak').order_by(PurchaseBatch.id.desc()).limit(1)
        q_batches=q_batches.where(or_(PurchaseBatch.status_batch.in_(('baru','ditumpuk','di_dryer','dikeringkan')),PurchaseBatch.id.in_(terakhir)))
    batches = (await db.execute(q_batches)).all() if baca_stok or baca_masuk else []
    if baca_stok:
        for b in batches:
            if b.status_batch in ('baru','ditumpuk','di_dryer','dikeringkan'):
                bobot = dari_batch(b)
                d['stok'].append(dict(nama='Gabah '+b.kondisi_gabah,kode=b.kode_batch,
                    kg=bobot.kg if bobot.diketahui else None,final=bobot.pasti,
                    lokasi=('Pengering · Gudang 1' if b.status_batch in ('di_dryer','dikeringkan') else 'Menunggu penempatan · Gudang 1' if b.status_batch=='baru' else 'Tumpukan · Gudang 1'),
                    pesanan=kode[b.jasa_id],href='/barang-masuk/'+str(b.timbangan_transaksi_id) if b.timbangan_transaksi_id else '',rincian=[]))
        for r,nama in (await db.execute(select(SiloStorage,Silo.nama_silo).join(Silo,Silo.id==SiloStorage.silo_id)
                .where(dalam(db, SiloStorage.jasa_id, ids),SiloStorage.status=='terisi'))).all():
            b = await _row_bobot(db,r)
            d['stok'].append(dict(nama='Gabah · bahan proses',kode=nama,kg=b.kg if b.diketahui else None,
                final=b.pasti, lokasi='Silo · Gudang 1',pesanan=kode[r.jasa_id],href='',rincian=[]))
        from app.models import GabahKeringLot
        from app.penggilingan.gudang1.services.gabah_kering import pending_gabah_kering_kg
        for lot in (await db.scalars(select(GabahKeringLot).where(dalam(db, GabahKeringLot.jasa_id, ids)))).all():
            kg = await pending_gabah_kering_kg(db,lot.id)
            if kg>0:
                d['stok'].append(dict(nama='Gabah kering ditimbang',kode=lot.kode_lot,kg=kg,final=True,
                    lokasi='Tumpukan · Gudang 1',pesanan=kode[lot.jasa_id],href='',rincian=[]))
    # Riwayat penerimaan yang sudah dicatat tetap memakai pembaca Barang
    # Masuk; tiket asal terpisah dari pesanan pemilik catatan saat ini.
    penerimaan_sql = rincian is not None
    if baca_masuk and penerimaan_sql:
        from .penerimaan_halaman import pilih,detail
        tab_masuk=rincian.get('tab')=='penerimaan'
        selected,pag,jumlah=await pilih(db,pid,pilihan=rincian if tab_masuk else None,hanya_jumlah=not tab_masuk)
        d['penerimaan_jumlah']=jumlah
        if tab_masuk:
            d['penerimaan']=await detail(db,selected,jasa_ids=ids,kode=kode)
            d['rincian_paginasi']=pag
    elif baca_masuk:
        from app.services.barang_masuk import riwayat
        diterima = await riwayat(db,g1=True,g2=True,jasa_ids=ids,batas_per_jenis=1 if kebutuhan=='beranda' else None)
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
        for pkl in (await db.scalars(select(PkPurchaseBatch).where(dalam(db, PkPurchaseBatch.jasa_id, ids),PkPurchaseBatch.timbangan_transaksi_id.is_(None)).limit(1) if kebutuhan=='beranda' else
                select(PkPurchaseBatch).where(dalam(db,PkPurchaseBatch.jasa_id,ids),PkPurchaseBatch.timbangan_transaksi_id.is_(None)))).all():
            d['penerimaan'].append(dict(id=None,kode=pkl.kode_batch,jenis='PK',
                catatan=[dict(berat=pkl.berat_total_kg,sumber_berat=pkl.sumber_berat,waktu=pkl.waktu_pembelian,status=pkl.status_batch)],
                pesanan=kode[pkl.jasa_id],status='Tautan tiket belum tersedia',href=''))
    # Pending diambil dari kartu operasional di rute pemanggil; pembaca ini
    # tidak menawarkan penerimaan yang tidak ditawarkan sumber lama.
    proses_sql = kebutuhan is None and rincian is not None
    if proses_sql:
        d['proses'],d['proses_jumlah'],d['berjalan'],pag = await _proses_halaman(db,pid,rincian)
        if pag is not None:d['rincian_paginasi']=pag
    else:
        pols = list((await db.execute(select(PolishingProcess.id,PolishingProcess.jasa_id,PolishingProcess.status,PolishingProcess.kode_proses).where(dalam(db, PolishingProcess.jasa_id, ids),
            PolishingProcess.status=='proses' if kebutuhan else True).order_by(PolishingProcess.id.desc()))).all()) if baca_proses else []
        dryers = list((await db.execute(select(DryingLot.id,DryingLot.jasa_id,DryingLot.status,DryingLot.kode_lot).where(dalam(db, DryingLot.jasa_id, ids),
            or_(DryingLot.status=='proses', (DryingLot.status=='selesai') & DryingLot.waktu_selesai_pendinginan.is_(None)) if kebutuhan else True))).all()) if baca_proses else []
        mills = list((await db.execute(select(MillingProcess.id,MillingProcess.jasa_id,MillingProcess.status,MillingProcess.kode_proses).where(dalam(db, MillingProcess.jasa_id, ids),
            MillingProcess.status=='proses' if kebutuhan else True))).all()) if baca_proses else []
        transfers = list((await db.execute(select(InternalTransfer.id,InternalTransfer.jasa_id,InternalTransfer.status,InternalTransfer.kode_transfer).where(dalam(db, InternalTransfer.jasa_id, ids)))).all()) if kebutuhan is None else []
        for jenis,rows,attr,prefix in [('pengeringan',dryers,'kode_lot','riwayat-pengeringan'),('giling',mills,'kode_proses','riwayat-giling'),('transfer',transfers,'kode_transfer','riwayat-transfer'),('sosoh',pols,'kode_proses','riwayat-sosoh')]:
            for r in rows:
                aktif = jenis!='transfer' and r.status=='proses'
                if aktif:
                    d['berjalan'] += 1
                kode_r = getattr(r,attr)
                d['proses'].append(dict(id=r.id,jenis=jenis,kode=kode_r,status=r.status,
                    pesanan=kode.get(r.jasa_id),href=f'/proses-aktif/{jenis}/{kode_r}' if aktif else f'/{prefix}/{r.id}',
                    sumber=[],hasil=None))
    d.setdefault('penerimaan_jumlah',len(d['penerimaan']))
    d.setdefault('proses_jumlah',len(d['proses']))
    tab_rinci=rincian.get('tab') if rincian is not None else None
    if (tab_rinci=='penerimaan' and not penerimaan_sql) or (tab_rinci=='proses' and not proses_sql):
        key=tab_rinci
        cari=str(rincian.get('cari') or '').strip()[:200]
        rows=[r for r in d[key] if not cari or cari.casefold() in
            ' '.join(str(r.get(k) or '') for k in ('kode','pesanan','jenis','status')).casefold()]
        akhir=max(1,(len(rows)+24)//25)
        try:halaman=min(akhir,max(1,int(rincian.get('halaman') or 1)))
        except ValueError:halaman=1
        d['rincian_paginasi']=dict(halaman=halaman,akhir=akhir,jumlah=len(rows),cari=cari)
        d[key]=rows[(halaman-1)*25:halaman*25]
    if rinci:
        from app.services.barang_masuk import rincian_lokasi
        # Ringkasan hanya memakai jumlah penerimaan/proses. Rincian tetap
        # dibaca lengkap oleh tab masing-masing dan pemanggil lama.
        for t in d['penerimaan'] if ringkasan_pesanan is None and tab_rinci in (None,'penerimaan') else []:
            if t['id'] is not None:
                t['lokasi'],t['proses'],_=await rincian_lokasi(db,t['catatan'])
        from app.services.jasa import boleh_ditutup,pernah_ada_barang
        ditampilkan = {r['id'] for r in d['pesanan_paginasi']['baris']} if ringkasan_pesanan is not None else None
        for j,r in zip(orders,d['pesanan']):
            if read_scope is not None or tab_rinci not in (None,'ringkasan'):
                # Proyeksi pelanggan tidak menawarkan aksi tutup/batal.
                continue
            if ditampilkan is not None and (j.id not in ditampilkan or j.status!='berjalan'):
                continue
            r['boleh_tutup'],r['sebab'] = await boleh_ditutup(db,j.id)
            r['boleh_batal'] = j.status=='berjalan' and not await pernah_ada_barang(db,j.id)
        if ringkasan_pesanan is None and tab_rinci in (None,'proses'):
            await _sumber_proses_banyak(db,d['proses'],ids)
        if tab_rinci in (None,'ringkasan','pengambilan'):
            await _pengiriman(db,d,ids,read_scope=read_scope)
    if d['pk_kg']>0:
        d['kondisi'].append('PK tersisa')
    if d['beras_kg']>0 or d['samping_kg']>0:
        d['kondisi'].append('Hasil belum diambil')
    if d['berjalan']:
        d['kondisi'].append('Proses berjalan')
    if any(r['nama'].startswith('Gabah') for r in d['stok']):
        d['kondisi'].append('Bahan masih di pabrik')
    return d


async def _proses_halaman(db, pid, rincian):
    """Hitung riwayat di database; hanya 25 proses yang perlu diperkaya."""
    from sqlalchemy import func,literal,union_all
    specs=[('pengeringan',DryingLot,'kode_lot'),('giling',MillingProcess,'kode_proses'),
           ('transfer',InternalTransfer,'kode_transfer'),('sosoh',PolishingProcess,'kode_proses')]
    queries=[]
    for urut,(jenis,model,col) in enumerate(specs):
        queries.append(select(model.id.label('id'),literal(jenis).label('jenis'),
            literal(urut).label('urut'),getattr(model,col).label('kode'),model.status.label('status'),
            Jasa.kode.label('pesanan')).join(Jasa,Jasa.id==model.jasa_id).where(Jasa.pelanggan_id==pid))
    semua=union_all(*queries).subquery()
    jumlah,aktif=(await db.execute(select(func.count(),func.count().filter(
        semua.c.jenis!='transfer',semua.c.status=='proses')).select_from(semua))).one()
    if rincian is None or rincian.get('tab')!='proses':return [],jumlah,aktif,None
    cari=str(rincian.get('cari') or '').strip()[:200]
    q=select(semua)
    if cari:
        pola='%'+cari.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        q=q.where(or_(*(getattr(semua.c,k).ilike(pola,escape='\\') for k in ('kode','pesanan','jenis','status'))))
    total=await db.scalar(select(func.count()).select_from(q.subquery())) if cari else jumlah
    akhir=max(1,(total+24)//25)
    try:halaman=min(akhir,max(1,int(rincian.get('halaman') or 1)))
    except ValueError:halaman=1
    rows=(await db.execute(q.order_by(semua.c.urut,semua.c.id.desc()).offset((halaman-1)*25).limit(25))).mappings()
    hasil=[]
    for r in rows:
        aktif_r=r['jenis']!='transfer' and r['status']=='proses'
        prefix={'pengeringan':'pengeringan','giling':'giling','transfer':'transfer','sosoh':'sosoh'}[r['jenis']]
        href=f"/proses-aktif/{r['jenis']}/{r['kode']}" if aktif_r else f"/riwayat-{prefix}/{r['id']}"
        hasil.append(dict(id=r['id'],jenis=r['jenis'],kode=r['kode'],status=r['status'],
            pesanan=r['pesanan'],href=href,sumber=[],hasil=None))
    return hasil,jumlah,aktif,dict(halaman=halaman,akhir=akhir,jumlah=total,cari=cari)


@baca_sekali
async def _pemilik_kartu(db, pid):
    from sqlalchemy import text
    ids=frozenset((await db.scalars(select(Jasa.id).where(Jasa.pelanggan_id==pid))).all())
    kode=frozenset((await db.scalars(text("SELECT kode FROM timbangan_transaksi WHERE arah='MASUK' AND jasa=TRUE AND pelanggan_id=:pid"),{'pid':pid})).all())
    return ids, kode


async def saring_kartu(db, rows, pid):
    """Batas pelanggan dibaca sekali dalam permintaan yang sama."""
    ids,kode=await _pemilik_kartu(db,pid)
    return [r for r in rows if r.kode in kode or
            bool(({r.jasa_id} | set(r.pemilik_ids or ())) & ids)]


async def _sumber_proses_banyak(db,rows,ids):
    """Sumber halaman terpilih dibaca berkelompok, bukan satu kueri per kartu."""
    mills=[r['id'] for r in rows if r['jenis']=='giling']
    per_mill={}
    sources=(await db.scalars(select(MillingProcessSource).where(
        dalam(db,MillingProcessSource.milling_process_id,mills)).order_by(MillingProcessSource.id))).all() if mills else []
    dry_ids={r.drying_lot_id for r in sources if r.drying_lot_id}
    batch_ids={r.purchase_batch_id for r in sources if r.purchase_batch_id}
    dries={r.id:r for r in (await db.scalars(select(DryingLot).where(dalam(db,DryingLot.id,dry_ids)))).all()} if dry_ids else {}
    batches={r.id:r for r in (await db.scalars(select(PurchaseBatch).where(dalam(db,PurchaseBatch.id,batch_ids)))).all()} if batch_ids else {}
    for source in sources:
        href,kode='','Asal belum tersedia'
        if source.drying_lot_id:
            b=dries.get(source.drying_lot_id)
            if b and b.jasa_id in ids:kode,href=b.kode_lot,f'/riwayat-pengeringan/{b.id}'
        elif source.purchase_batch_id:
            b=batches.get(source.purchase_batch_id)
            if b and b.jasa_id in ids:kode,href=b.kode_batch,f'/barang-masuk/{b.timbangan_transaksi_id}' if b.timbangan_transaksi_id else ''
        per_mill.setdefault(source.milling_process_id,[]).append(dict(kode=kode,kg=source.berat_terpakai_kg,
            ket='Terpakai' if source.berat_terpakai_kg is not None else 'Pemakaian belum final',href=href))
    drying=[r['id'] for r in rows if r['jenis']=='pengeringan']
    per_dry={}
    if drying:
        for lid,b in (await db.execute(select(DryingLotBatch.drying_lot_id,PurchaseBatch)
            .join(PurchaseBatch,PurchaseBatch.id==DryingLotBatch.purchase_batch_id)
            .where(dalam(db,DryingLotBatch.drying_lot_id,drying),dalam(db,PurchaseBatch.jasa_id,ids)))).all():
            per_dry.setdefault(lid,[]).append(dict(kode=b.kode_batch,kg=None,
                ket='Bobot masuk pada penerimaan; bukan berat setelah kering',href=f'/barang-masuk/{b.timbangan_transaksi_id}' if b.timbangan_transaksi_id else ''))
    transfers=[r['id'] for r in rows if r['jenis']=='transfer']
    per_transfer={}
    if transfers:
        for t,m in (await db.execute(select(InternalTransfer,MillingProcess).outerjoin(
            MillingProcess,MillingProcess.id==InternalTransfer.milling_process_id)
            .where(dalam(db,InternalTransfer.id,transfers)))).all():
            if m and m.jasa_id in ids:
                per_transfer[t.id]=[dict(kode=m.kode_proses,kg=t.berat_kg,ket='PK ditransfer',href=f'/riwayat-giling/{m.id}')]
    maps={'giling':per_mill,'pengeringan':per_dry,'transfer':per_transfer}
    for r in rows:
        if r['jenis'] not in maps:
            await _sumber_proses(db,r,ids)
            continue
        r['sumber']=maps[r['jenis']].get(r['id'],[])
        if not r['sumber']:
            r['sumber']=[dict(kode='Keterkaitan sumber belum tersedia',kg=None,
                ket='Tidak dibuat berdasarkan nama, tanggal atau berat',href='')]


async def _sumber_proses(db,r,ids):
    if r['jenis']=='pengeringan':
        for b in (await db.scalars(select(PurchaseBatch).join(DryingLotBatch,DryingLotBatch.purchase_batch_id==PurchaseBatch.id).where(DryingLotBatch.drying_lot_id==r['id'],dalam(db, PurchaseBatch.jasa_id, ids)))).all():
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


async def _pengiriman(db,d,ids,*,read_scope=None):
    from app.penggilingan.inventory.models import CustomerReturn,CustomerReturnItem
    rows=(await db.execute(select(OutgoingRecord,OutgoingItem).join(OutgoingItem,OutgoingItem.outgoing_record_id==OutgoingRecord.id)
          .where(dalam(db, OutgoingItem.jasa_id, ids),
                 dalam(db, OutgoingRecord.id, read_scope.ids(OutgoingRecord)) if read_scope is not None else True).order_by(OutgoingRecord.id.desc(),OutgoingItem.id))).all()
    grouped={}
    for o,i in rows:
        g=grouped.setdefault(o.id,dict(id=o.id,kode=o.kode,status=o.status,href=f'/barang-keluar/{o.id}',item=[]))
        g['item'].append(dict(jenis=i.item_type,kg=i.berat_kg,pesanan_id=i.jasa_id))
    d['pengiriman']=list(grouped.values())
    rs=(await db.scalars(select(CustomerReturn).join(CustomerReturnItem,CustomerReturnItem.customer_return_id==CustomerReturn.id)
        .where(or_(dalam(db, CustomerReturnItem.jasa_id, ids),CustomerReturn.pelanggan_id==d['id']),
               dalam(db, CustomerReturn.id, read_scope.ids(CustomerReturn)) if read_scope is not None else True)
        .distinct().order_by(CustomerReturn.id.desc()))).all()
    # Relasi item adalah bukti asal; nama pelanggan/tanggal/bobot bukan.
    # Dibaca sekaligus agar banyak retur tidak menambah satu query per asal.
    asal_per_retur={}
    if rs:
        asal_rows=(await db.execute(select(CustomerReturnItem.customer_return_id,
            OutgoingRecord.id,OutgoingRecord.kode)
            .join(OutgoingItem,OutgoingItem.id==CustomerReturnItem.outgoing_item_id)
            .join(OutgoingRecord,OutgoingRecord.id==OutgoingItem.outgoing_record_id)
            .where(CustomerReturnItem.customer_return_id.in_([x.id for x in rs]))
            .distinct().order_by(CustomerReturnItem.customer_return_id,OutgoingRecord.id))).all()
        for rid,oid,kode_asal in asal_rows:
            asal_per_retur.setdefault(rid,[]).append(dict(id=oid,kode=kode_asal,href=f'/barang-keluar/{oid}'))
    pemilik_per_retur={}
    if rs:
        for rid,jid in (await db.execute(select(CustomerReturnItem.customer_return_id,CustomerReturnItem.jasa_id)
                .where(CustomerReturnItem.customer_return_id.in_([x.id for x in rs])))).all():
            pemilik_per_retur.setdefault(rid,set()).add(jid)
    for x in rs:
        pemilik=pemilik_per_retur.get(x.id,set())
        status='Milik pabrik' if pemilik=={None} else 'Titipan jasa' if pemilik<=set(ids) else 'Kepemilikan per item'
        d['retur'].append(dict(id=x.id,kode=x.kode,href=f'/retur/{x.id}',asal=asal_per_retur.get(x.id,[]),
            status='Retur · '+status+('' if asal_per_retur.get(x.id) else ' · Pengeluaran asal belum tertaut')))
