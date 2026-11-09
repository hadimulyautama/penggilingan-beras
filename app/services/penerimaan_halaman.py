"""Pilih catatan penerimaan di SQL sebelum membangun rincian halaman.

Riwayat tiket dan batch warisan tetap memakai pembaca/rumus asli. Query ini
hanya memilih identitas yang ditampilkan dan menghitung seluruh hasil cari.
"""
from sqlalchemy import select, union_all, literal, null, func, table, column, case, or_, Integer
from app.models import Jasa, PurchaseBatch, PkPurchaseBatch, FinishedGoodsStock, ByproductStock
from app.performa import dalam


def kandidat(db,pid, *, portal=False, scope=None):
    own=select(Jasa.id).where(Jasa.pelanggan_id==pid)
    specs=[(PurchaseBatch,PurchaseBatch.timbangan_transaksi_id,'gabah','waktu_pembelian'),
        (PkPurchaseBatch,PkPurchaseBatch.timbangan_transaksi_id,'pk','waktu_pembelian'),
        (FinishedGoodsStock,FinishedGoodsStock.source_id,'beras','waktu'),
        (ByproductStock,ByproductStock.source_id,'broken','waktu')]
    notes=[]
    for model,fk,jenis,datecol in specs:
        q=select(fk.label('tid'),getattr(model,datecol).label('waktu')).where(model.jasa_id.in_(own),fk.is_not(None))
        if jenis in ('beras','broken'):q=q.where(model.source_type=='timbangan')
        if portal and jenis in ('gabah','pk'):
            q=q.where(model.status_batch.not_in(('baru','ditolak')) if jenis=='pk' else model.status_batch!='ditolak')
        notes.append(q)
    ns=union_all(*notes).subquery()
    linked=select(ns.c.tid,func.max(ns.c.waktu).label('waktu')).group_by(ns.c.tid).subquery()
    t=table('timbangan_transaksi',*(column(c,Integer) if c in ('id','jasa_id') else column(c) for c in ('id','kode','jenis_kode','status_tiket','jasa_id','arah','nomor_polisi')))
    jt=table('timbangan_jenis',column('kode'),column('nama'))
    jenis=case((t.c.jenis_kode=='GABAH_BASAH','gabah_basah'),(t.c.jenis_kode=='GABAH_KERING','gabah_kering'),
        (t.c.jenis_kode=='BERAS_PK','pk'),(t.c.jenis_kode=='BERAS_MASUK','beras'),(t.c.jenis_kode=='BROKEN_MASUK','broken'),(or_(t.c.jenis_kode.like('HS_%_MASUK'),t.c.jenis_kode.in_(('MENIR_MASUK','REJECT_MASUK','BEKATUL_MASUK'))),'broken'),else_='lain')
    q=select(literal('tiket').label('sumber'),t.c.id.label('id'),t.c.kode.label('kode'),
        jenis.label('jenis'),t.c.status_tiket.label('status'),linked.c.waktu.label('waktu'),
        t.c.nomor_polisi.label('plat'),Jasa.kode.label('pesanan'),literal(0).label('urut'),(-t.c.id).label('pos'),func.coalesce(jt.c.nama,t.c.jenis_kode).label('jenis_cari'))\
        .select_from(t.join(linked,linked.c.tid==t.c.id).outerjoin(Jasa,Jasa.id==t.c.jasa_id).outerjoin(jt,jt.c.kode==t.c.jenis_kode)).where(t.c.arah=='MASUK')
    if portal:q=q.where(dalam(db,t.c.id,scope.resources.get('timbangan_transaksi',())))
    queries=[q]
    for i,(model,jenis_nama) in enumerate(((PurchaseBatch,'gabah'),(PkPurchaseBatch,'pk')),1):
        jenis=literal('pk') if jenis_nama=='pk' else literal('gabah_')+model.kondisi_gabah
        q=select(literal(jenis_nama),model.id,model.kode_batch,jenis,model.status_batch,model.waktu_pembelian,
            model.no_polisi_truk,Jasa.kode,literal(i),model.id,
            literal('PK') if jenis_nama=='pk' else literal('Gabah ')+model.kondisi_gabah).join(Jasa,Jasa.id==model.jasa_id)\
            .where(Jasa.pelanggan_id==pid,model.timbangan_transaksi_id.is_(None))
        if portal:
            q=q.where(dalam(db,model.id,scope.ids(model)))
            q=q.where(model.status_batch.not_in(('baru','ditolak')) if jenis_nama=='pk' else model.status_batch!='ditolak')
        queries.append(q)
    return union_all(*queries).subquery()


async def pilih(db,pid,*,pilihan=None,portal=False,scope=None,nama='',hanya_jumlah=False):
    choices=pilihan or {}
    sumber=kandidat(db,pid,portal=portal,scope=scope)
    q=select(sumber)
    cari=str(choices.get('cari') or '').strip()[:200]
    jenis=str(choices.get('jenis') or '')
    if jenis:q=q.where(sumber.c.jenis==jenis)
    if cari:
        pola='%'+cari.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        fields=('kode','plat') if portal else ('kode','pesanan','jenis_cari','status')
        if not (portal and cari.casefold() in nama.casefold()):
            q=q.where(or_(*(getattr(sumber.c,k).ilike(pola,escape='\\') for k in fields)))
    jumlah=await db.scalar(select(func.count()).select_from(q.subquery()))
    akhir=max(1,(jumlah+24)//25)
    try:halaman=min(akhir,max(1,int(choices.get('halaman') or 1)))
    except (ValueError,TypeError):halaman=1
    if portal:q=q.order_by(sumber.c.waktu.desc().nullslast(),sumber.c.kode.desc(),sumber.c.id.desc())
    else:q=q.order_by(sumber.c.urut,sumber.c.pos)
    rows=[] if hanya_jumlah else (await db.execute(q.offset((halaman-1)*25).limit(25))).mappings().all()
    total=jumlah if not cari and not jenis else await db.scalar(select(func.count()).select_from(sumber))
    return rows,dict(halaman=halaman,akhir=akhir,jumlah=jumlah,cari=cari,jenis=jenis),total


async def detail(db,selected,*,jasa_ids,kode):
    """DTO native yang sama, hanya untuk tiket/batch halaman terpilih."""
    from .barang_masuk import riwayat
    tids=[r['id'] for r in selected if r['sumber']=='tiket']
    tickets={t['id']:t for t in await riwayat(db,g1=True,g2=True,jasa_ids=jasa_ids,ids_tiket=tids)} if tids else {}
    batches={}
    for kind,model in (('gabah',PurchaseBatch),('pk',PkPurchaseBatch)):
        ids=[r['id'] for r in selected if r['sumber']==kind]
        if ids:
            batches.update({(kind,b.id):b for b in (await db.scalars(select(model).where(model.id.in_(ids)))).all()})
    result=[]
    for r in selected:
        if r['sumber']=='tiket':
            t=tickets.get(r['id'])
            if t is None:continue
            cat=[c for c in t['catatan'] if c['jasa_id'] in jasa_ids]
            result.append(dict(id=t['id'],kode=t['kode'],jenis=t['jenis_nama'] or t['jenis_kode'],catatan=cat,
                pesanan=kode.get(t['jasa_id'],'Pesanan asal belum tersedia'),status=t['status_tiket'],href=f"/barang-masuk/{t['id']}"))
        else:
            model=PurchaseBatch if r['sumber']=='gabah' else PkPurchaseBatch
            b=batches[r['sumber'],r['id']]
            result.append(dict(id=None,kode=b.kode_batch,jenis='Gabah '+b.kondisi_gabah if r['sumber']=='gabah' else 'PK',
                catatan=[dict(berat=b.berat_total_kg,sumber_berat=b.sumber_berat,waktu=b.waktu_pembelian,status=b.status_batch)],
                pesanan=kode[b.jasa_id],status='Tautan tiket belum tersedia',href=''))
    return result
