"""Identitas dan waktu catatan pelanggan; tidak menulis keadaan produksi."""
from app.performa import dalam
from zoneinfo import ZoneInfo

from sqlalchemy import and_,func,select

TAHAP={'pengeringan':'Pengeringan','pendinginan':'Pendinginan',
       'giling':'Penggilingan','sosoh':'Penyosohan','transfer':'Pemindahan'}


def identitas(jenis, kartu=None):
    if jenis in ('pengeringan','pendinginan','giling'):
        return dict(judul=TAHAP[jenis]+' gabah',barang='Gabah')
    if jenis=='transfer':
        return dict(judul='Pemindahan beras pecah kulit (PK)',barang='Beras pecah kulit (PK)')
    nama=[]
    labels={'PK':'Beras pecah kulit (PK)','Beras putih':'Beras',
            'Broken':'Beras pecah (broken)','Reject':'Beras sortir',
            'Menir':'Menir','Belum teridentifikasi':'Jenis bahan belum tercatat'}
    # Komposisi asli per pemakaian, bukan jenis_isi silo yang dapat berubah.
    for judul,rows in getattr(kartu,'anak_grup',[]) or []:
        if judul!='Bahan baku masuk per silo':continue
        for r in rows:
            if len(r)>3 and r[3]=='sosoh-bahan':
                label=labels.get(r[0],'Jenis bahan belum tercatat')
                if label not in nama:nama.append(label)
    for grup in getattr(kartu,'pemakaian_silo',[]) or []:
        for bahan in grup.get('bahan',[]):
            label=labels.get(bahan.get('nama'),'Jenis bahan belum tercatat')
            if label not in nama:nama.append(label)
    if len(nama)>1:return dict(judul='Penyosohan bahan campuran',barang=', '.join(nama))
    if nama and nama[0]!='Jenis bahan belum tercatat':
        return dict(judul='Penyosohan '+nama[0][0].lower()+nama[0][1:],barang=nama[0])
    return dict(judul='Penyosohan',barang='Jenis bahan belum tercatat')


def petunjuk(status):
    if status=='Dijeda':
        return 'Proses dijeda dan menunggu penanganan petugas. Anda belum perlu bertindak.'
    if status=='Selesai':
        return 'Proses selesai. Untuk rencana pengambilan barang, konfirmasikan dengan petugas.'
    if status=='Sedang berjalan':
        return 'Proses ditangani petugas. Anda belum perlu bertindak.'
    return 'Status proses belum tersedia. Hubungi petugas untuk memastikan perkembangannya.'


def terbaru(catatan):
    """Tidak menggunakan jam saat halaman dibuka, termasuk sebagai fallback."""
    tersedia=[(w,label) for w,label in catatan if w is not None]
    from app.config import settings
    return max(tersedia,key=lambda r:r[0].replace(tzinfo=r[0].tzinfo or ZoneInfo(settings.app_timezone)).timestamp()) if tersedia else (None,'Pembaruan terakhir')


async def baca(db,scope,permintaan):
    from app.models import (DryingLot,DryingMoistureLog,DryingCoolingLog,
        MillingProcess,MillingProgressLog,MillingQcLog,PolishingProcess,
        PolishingOutputLog,PolishingSiloUsage,JedaProses,JedaCatatan,InternalTransfer,ActivityLog)
    from .scope import MODELS
    permintaan=set(permintaan);hasil={}
    for jenis in TAHAP:
        codes={kode for tipe,kode in permintaan if tipe==jenis}
        if not codes:continue
        model,col=MODELS[jenis]
        rows=(await db.scalars(select(model).where(dalam(db, model.id, scope.ids(model)),
            getattr(model,col).in_(codes)))).all()
        ids=[r.id for r in rows]
        events={i:[] for i in ids}
        async def audit_parent(tables,label):
            # Log pengeringan/giling memakai ID proses sebagai record_id.
            for ident,catat,batal in (await db.execute(select(ActivityLog.record_id,
                func.max(ActivityLog.waktu_perubahan),func.max(ActivityLog.dibatalkan_pada))
                .where(ActivityLog.table_name.in_(tables),dalam(db, ActivityLog.record_id, ids))
                .group_by(ActivityLog.record_id))).all():
                events[ident].extend((w,label) for w in (catat,batal))
        async def log(table,fk,waktu,label):
            for ident,saat in (await db.execute(select(fk,func.max(waktu)).where(
                fk.in_(ids)).group_by(fk))).all():
                events[ident].append((saat,label))
            if table in (PolishingOutputLog,PolishingSiloUsage):
                # Audit sosoh memakai ID baris anak. Hubungkan melalui FK
                # agar catatan pelanggan lain tidak cocok hanya karena ID.
                for ident,catat,batal in (await db.execute(select(fk,
                    func.max(ActivityLog.waktu_perubahan),func.max(ActivityLog.dibatalkan_pada))
                    .select_from(table).join(ActivityLog,and_(ActivityLog.table_name==table.__tablename__,
                        ActivityLog.record_id==table.id)).where(fk.in_(ids)).group_by(fk))).all():
                    events[ident].extend((w,label) for w in (catat,batal))
        await audit_parent([model.__tablename__],'Catatan proses')
        if model is DryingLot:
            await log(DryingMoistureLog,DryingMoistureLog.drying_lot_id,DryingMoistureLog.waktu_update,'Pengukuran kadar air')
            await log(DryingCoolingLog,DryingCoolingLog.drying_lot_id,DryingCoolingLog.waktu,'Catatan pendinginan')
            await audit_parent(['drying_moisture_logs'],'Pengukuran kadar air')
            await audit_parent(['drying_cooling_logs'],'Catatan pendinginan')
            jeda_fk=JedaProses.drying_lot_id
        elif model is MillingProcess:
            await log(MillingProgressLog,MillingProgressLog.milling_process_id,MillingProgressLog.waktu_update,'Pencatatan hasil giling')
            await log(MillingQcLog,MillingQcLog.milling_process_id,MillingQcLog.waktu,'Pemeriksaan mutu')
            await audit_parent(['milling_progress_logs'],'Pencatatan hasil giling')
            await audit_parent(['milling_qc_logs'],'Pemeriksaan mutu')
            jeda_fk=JedaProses.milling_process_id
        elif model is PolishingProcess:
            await log(PolishingOutputLog,PolishingOutputLog.polishing_process_id,PolishingOutputLog.waktu_update,'Pencatatan hasil sosoh')
            await log(PolishingSiloUsage,PolishingSiloUsage.polishing_process_id,PolishingSiloUsage.updated_at,'Pencatatan bahan proses')
            jeda_fk=JedaProses.polishing_process_id
        else:jeda_fk=None
        dijeda=set()
        if jeda_fk is not None:
            jedas=(await db.scalars(select(JedaProses).where(jeda_fk.in_(ids)))).all()
            pemilik={j.id:getattr(j,jeda_fk.key) for j in jedas}
            for j in jedas:
                ident=pemilik[j.id]
                events[ident].extend((w,'Catatan jeda proses') for w in
                    (j.created_at,j.mulai,j.selesai,j.dibatalkan_pada))
                if j.selesai is None and j.dibatalkan_pada is None:dijeda.add(ident)
            for jid,catat,batal in (await db.execute(select(JedaCatatan.jeda_id,
                func.max(JedaCatatan.dicatat_pada),func.max(JedaCatatan.dibatalkan_pada))
                .where(JedaCatatan.jeda_id.in_(pemilik)).group_by(JedaCatatan.jeda_id))).all():
                events[pemilik[jid]].extend((w,'Catatan jeda proses') for w in (catat,batal))
        for r in rows:
            if model is DryingLot:
                mulai=r.waktu_mulai_pendinginan if jenis=='pendinginan' else r.waktu_mulai_pengeringan
                selesai=r.waktu_selesai_pendinginan
                status='Selesai' if selesai else 'Sedang berjalan' if r.status in ('proses','selesai') else None
                events[r.id].extend((w,'Perubahan tahap proses') for w in
                    (r.waktu_selesai_pengeringan,r.waktu_mulai_pendinginan,selesai))
            elif model is InternalTransfer:
                mulai=r.waktu
                status='Selesai' if r.status=='terkirim' else None
            else:
                mulai=r.waktu_mulai
                status='Selesai' if r.status=='selesai' else 'Sedang berjalan' if r.status=='proses' else None
                events[r.id].append((r.waktu_selesai,'Proses selesai'))
            if status=='Sedang berjalan' and r.id in dijeda and jenis!='pendinginan':status='Dijeda'
            waktu,sumber=terbaru([(mulai,'Mulai proses'),(r.updated_at,'Catatan proses'),*events[r.id]])
            hasil[jenis,getattr(r,col)]=dict(status=status or 'Belum tersedia',
                diperbarui=waktu,sumber_waktu=sumber,petunjuk=petunjuk(status))
    return hasil


async def siapkan_detail(request,name,ctx):
    from app.database import SessionLocal
    d=ctx.get('d') if name in ('detail_pengeringan.html','detail_pendinginan.html',
        'detail_giling.html','detail_sosoh.html','proses_aktif_detail.html') else None
    if d:
        jenis,kode=d['jenis'],d['kode'];kartu=ctx.get('proses')
        lokasi=d.get('dryer') if jenis in ('pengeringan','pendinginan') else None
        if not lokasi:
            silos=d.get('silo_aktif') or []
            lokasi=('Gudang 2' if jenis=='sosoh' else 'Gudang 1')+(' · '+', '.join(silos) if silos else '')
        angka=next(iter(d.get('statistik',[])),None)
        if angka:angka=('Jumlah bahan',angka[1])
    elif name=='riwayat_detail.html' and ctx.get('jenis') in TAHAP:
        jenis=ctx['jenis'];kartu=ctx['k']
        kode=getattr(kartu,'kode_lot',None) or getattr(kartu,'kode',None)
        lokasi=None;angka=None
    else:
        if ctx.get('detail_kartu') or name=='stok_produk_detail.html':ctx['portal_pembaruan_stok']=True
        return
    async with SessionLocal() as db:
        metadata=(await baca(db,request.state.portal_scope,[(jenis,kode)])).get((jenis,kode))
    if metadata is None:return
    ctx['portal_inti_proses']=dict(**metadata,**identitas(jenis,kartu),
        kode=kode,lokasi=lokasi,angka=angka,catatan=getattr(kartu,'nota',None))


def tampilkan_detail(content,ctx,env):
    from bs4 import BeautifulSoup
    inti=ctx.get('portal_inti_proses');stok=ctx.get('portal_pembaruan_stok')
    if not inti and not stok:return content
    s=BeautifulSoup(content,'html.parser')
    if inti:
        root=s.select_one('.pelanggan-detail')
        hero=root.select_one('.riwayat-detail__hero') if root else None
        if hero:
            baru=BeautifulSoup(env.get_template('portal/_inti_proses.html').render(r=inti),'html.parser').header
            hero.replace_with(baru)
            if inti['angka']:
                # Satu angka utama di header; tidak diulang pada kartu statistik.
                for grid in root.select('.proses-detail__statistik'):
                    card=grid.find('article',recursive=False)
                    if card:card.decompose()
                    for card in list(grid.find_all('article',recursive=False)):
                        label=card.find('span',recursive=False)
                        text=label.get_text(' ',strip=True) if label else ''
                        if text=='Total hasil giling':label.string='Hasil giling sementara'
                        if text.startswith(('Rasio hasil','Rendemen')):
                            wrapper=s.new_tag('details',attrs={'class':'pelanggan-detail-lipat pelanggan-rasio-hasil'})
                            summary=s.new_tag('summary');summary.string='Perbandingan bahan dan hasil'
                            card.wrap(wrapper);wrapper.insert(0,summary)
                            label.string='Persentase hasil sementara'
                            note=s.new_tag('p',attrs={'class':'pelanggan-redup'})
                            note.string='Persentase hasil terhadap bahan, bukan persentase proses selesai.'
                            wrapper.append(note)
    elif stok:
        hero=s.select_one('.pk-detail__hero')
        if hero:
            for code in hero.select('.pelanggan-detail-kode'):
                code.string=code.get_text(' ',strip=True).removeprefix('? · ')
    return str(s)
