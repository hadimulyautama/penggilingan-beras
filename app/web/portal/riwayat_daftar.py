"""Halaman riwayat dipilih di SQL; scope sumber tetap diperiksa sebelumnya."""
from app.performa import dalam
from sqlalchemy import select, union_all, literal, func, or_
from app.models import DryingLot, MillingProcess, PolishingProcess, InternalTransfer
from .beranda import NAMA_PROSES
from .daftar_catatan import daftar


async def baca(db, scope, request):
    queries=[]
    for jenis,model,col,datecol in [
        ('pengeringan',DryingLot,'kode_lot','waktu_selesai_pendinginan'),
        ('giling',MillingProcess,'kode_proses','waktu_selesai'),
        ('sosoh',PolishingProcess,'kode_proses','waktu_selesai'),
        ('transfer',InternalTransfer,'kode_transfer','waktu')]:
        where=[dalam(db, model.id, scope.ids(model))]
        if jenis=='transfer':where.append(model.status.in_(('selesai','terkirim')))
        else:where.append(model.status=='selesai')
        if jenis=='pengeringan':where.append(model.waktu_selesai_pendinginan.is_not(None))
        queries.append(select(model.id.label('id'),literal(jenis).label('jenis'),
            literal(NAMA_PROSES[jenis]).label('judul'),getattr(model,col).label('kode'),
            getattr(model,datecol).label('tanggal')).where(*where))
    semua=union_all(*queries).subquery()
    pilihan=[('','Semua proses')]+[(k,v) for k,v in NAMA_PROSES.items() if k!='pendinginan']
    jenis=request.query_params.get('jenis','')
    q=request.query_params.get('q','').strip()[:120]
    query=select(semua)
    if jenis in dict(pilihan) and jenis:query=query.where(semua.c.jenis==jenis)
    if q:
        pola='%'+q.replace('\\','\\\\').replace('%','\\%').replace('_','\\_')+'%'
        query=query.where(or_(semua.c.kode.ilike(pola,escape='\\'),semua.c.judul.ilike(pola,escape='\\')))
    total=await db.scalar(select(func.count()).select_from(query.subquery()))
    try:page=max(1,int(request.query_params.get('halaman','1')))
    except ValueError:page=1
    page=min(page,max(1,(total+24)//25))
    rows=(await db.execute(query.order_by(semua.c.tanggal.desc().nullslast(),semua.c.kode.desc())
        .offset((page-1)*25).limit(25))).mappings().all()
    dry_ids=[r['id'] for r in rows if r['jenis']=='pengeringan']
    bobot={}
    if dry_ids:
        from app.services.estimasi_pengeringan import untuk_lot_banyak
        lots=(await db.scalars(select(DryingLot).where(DryingLot.id.in_(dry_ids),DryingLot.waktu_selesai_pengeringan.is_not(None)))).all()
        bobot={x['kode']:x for x in (await untuk_lot_banyak(db,lots)).values()}
    hasil=[dict(jenis=r['jenis'],judul=r['judul'],kode=r['kode'],tanggal=r['tanggal'],
        label_tanggal='Selesai',href=f"/riwayat-{r['jenis']}/{r['id']}",aksi='Lihat hasil',
        catatan='',bobot_pengeringan=bobot.get(r['kode'])) for r in rows]
    return daftar(hasil,request,base='/pelanggan/riwayat-proses',pilihan=pilihan,
        judul='Riwayat proses',pengantar='Proses yang sudah selesai. Buka untuk melihat bahan dan hasilnya.',
        label_jenis='Jenis proses',satuan='proses',total_sql=total)
