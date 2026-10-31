"""Customer routes call production read composers after exact ownership checks."""
import re
from collections import OrderedDict
from types import SimpleNamespace
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select, or_, and_, func, false
from starlette.requests import Request as NativeRequest
from app.database import SessionLocal
from .security import require_customer
from .scope import load_scope, own_model, own_ticket, own_order, own_outgoing, missing, MODELS
from .navigation import READS, portal_url
from .presentation import render_customer

router=APIRouter(prefix='/pelanggan',tags=['portal-pelanggan'])


def integer(value):
    try:return int(value) if value else None
    except (ValueError,TypeError):raise HTTPException(422,'Identitas tidak valid.')


def native_request(request,path,scope):
    # Middleware sets the cookie on the original request, not its native view.
    from .auth import csrf_context
    csrf_context(request)
    q=dict(request.query_params)
    if q.get('pelanggan_id') and q['pelanggan_id']!=str(scope.reader.pelanggan_id):missing()
    if any(q.get(k) for k in ('buka','nilai','aksi','koreksi')):
        raise HTTPException(404,'Fungsi ini tidak tersedia di portal pelanggan.')
    q.update(pelanggan_id=str(scope.reader.pelanggan_id),pemilik='jasa',kepemilikan='jasa')
    if path=='/stok/pk/detail':q['jasa']='1'
    clone={**request.scope,'path':path,'raw_path':path.encode(),'query_string':urlencode(q).encode(),
           'state':{**request.scope.get('state',{}),'portal_scope':scope,'view':'pelanggan',
                    'akun':SimpleNamespace(user=scope.reader,is_admin=False,is_superadmin=False,nama=scope.reader.nama)}}
    return NativeRequest(clone)


@router.get('')
@router.get('/')
async def index(request:Request):
    try:reader=await require_customer(request)
    except HTTPException as exc:
        if exc.status_code==401:return RedirectResponse('/pelanggan/masuk',303)
        raise
    return await read(request,'ringkasan',reader)


@router.get('/{path:path}')
async def read(request:Request,path:str,reader=Depends(require_customer)):
    path='/'+path
    if not READS.fullmatch(path):missing()
    scope=await load_scope(reader)
    req=native_request(request,path,scope)
    account=req.state.akun
    q=req.query_params
    from app.web import (layar_jasa as jasa,layar_pekerjaan as work,layar_produk as product,
        layar_stok as stock,layar_riwayat as history,layar_sosoh as sosoh,
        layar_berjalan as active,layar_keluar as outgoing,layar_retur as returns,
        layar_retur_asal as applications)
    if path=='/serah-terima' or '/serah-terima' in path:
        from app.web import serah_terima
        if path=='/serah-terima':
            return await serah_terima.daftar(req,account)
        match=re.fullmatch(r'/(barang-masuk|barang-keluar)/(\d+)/serah-terima(?:\.pdf)?',path)
        if not match:missing()
        ident=int(match[2])
        if match[1]=='barang-masuk':await own_ticket(scope,ident)
        else:await own_outgoing(scope,ident)
        result=await serah_terima.detail(ident,req,account)
    elif path in ('/ringkasan','/jasa-saya','/barang-saya','/riwayat-proses','/barang-masuk','/barang-keluar'):
        from .beranda import halaman
        bagian={'/ringkasan':'beranda','/jasa-saya':'jasa','/barang-saya':'barang',
            '/riwayat-proses':'riwayat','/barang-masuk':'masuk','/barang-keluar':'pengambilan'}[path]
        # Tautan tab beranda lama tetap mengarah ke isi yang sesuai.
        if path=='/ringkasan' and q.get('tab') in ('penerimaan','proses','pengambilan','stok'):
            bagian={'penerimaan':'masuk','proses':'jasa','pengambilan':'pengambilan','stok':'barang'}[q['tab']]
            req=native_request(request,{'masuk':'/barang-masuk','pengambilan':'/barang-keluar',
                'barang':'/barang-saya','jasa':'/jasa-saya'}[bagian],scope)
        result=await halaman(req,bagian)
    elif path=='/pekerjaan':result=await work.halaman_pekerjaan(req,account)
    elif m:=re.fullmatch(r'/barang-masuk/(\d+)/laporan\.pdf',path):
        tid=int(m[1]);await own_ticket(scope,tid)
        result=await work.laporan_penerimaan_pdf(tid,req,account,unduh=integer(q.get('unduh')) if q.get('unduh') else 1)
    elif m:=re.fullmatch(r'/barang-masuk/(\d+)',path):
        tid=int(m[1]);await own_ticket(scope,tid)
        result=await work.detail_barang_masuk(tid,req,account)
    elif path in ('/stok','/stok-pk-jasa','/stok-produk-jasa','/stok-produk-jasa/detail','/stok-karung-jasa'):
        tab=q.get('tab','bahan') if path=='/stok' else ('produk' if path.startswith('/stok-produk') else 'karung' if path=='/stok-karung-jasa' else 'bahan')
        if tab=='produk':result=await product.halaman_stok_produk_jasa(req,account,jenis=q.get('jenis'),pelanggan_id=reader.pelanggan_id)
        elif tab=='karung':result=await product.halaman_stok_karung_jasa(req,account)
        elif tab=='bahan':result=await stock.halaman_stok_pk_jasa(req,account)
        else:raise HTTPException(422,'Pilihan stok tidak dikenal.')
    elif path=='/stok/pk/detail':
        from app.models import PkGudang2Intake
        if q.get('gudang')=='g1':await own_model(scope,'giling',q.get('kode'),by_code=True)
        elif integer(q.get('id')) not in scope.ids(PkGudang2Intake):missing()
        result=await stock.halaman_detail_stok_pk(req,account)
    elif m:=re.fullmatch(r'/jasa/pelanggan/(\d+)',path):
        if int(m[1])!=reader.pelanggan_id:missing()
        from .beranda import halaman
        result=await halaman(req,'barang' if q.get('tab') in ('stok','pengambilan') else 'jasa')
    elif m:=re.fullmatch(r'/jasa/(\d+)(/nota(?:\.pdf)?)?',path):
        await own_order(scope,int(m[1]))
        if m[2]=='/nota.pdf':result=await jasa.rekap_pdf(int(m[1]),req,unduh=integer(q.get('unduh')) or 0,akun=account)
        elif m[2]:result=await jasa.nota(int(m[1]),req,account)
        else:result=RedirectResponse(f'/pelanggan/jasa/{m[1]}/nota',303)
    elif m:=re.fullmatch(r'/proses-aktif/([\w-]+)/([\w-]+)',path):
        await own_model(scope,m[1],m[2],by_code=True)
        result=await active.detail_proses_aktif(m[1],m[2],req,account)
    elif m:=re.fullmatch(r'/riwayat-(giling|pengeringan|sosoh|transfer)(?:/(\d+)(/laporan(?:\.pdf)?)?)?',path):
        kind=m[1];ident=int(m[2]) if m[2] else None
        if ident is None:result=await history_list(req,kind)
        else:
            obj=await own_model(scope,kind,ident)
            if m[3]:
                if kind=='transfer':missing()
                if (kind=='pengeringan' and obj.waktu_selesai_pendinginan is None) or (kind!='pengeringan' and obj.status!='selesai'):missing()
                if m[3].endswith('.pdf'):
                    pdf_readers={'pengeringan':history.laporan_pengeringan_pdf,
                                 'giling':history.laporan_giling_pdf,'sosoh':sosoh.laporan_sosoh_pdf}
                    result=await pdf_readers[kind](ident,integer(q.get('unduh')) or 0)
                else:
                    from app.web.tampilan import render_laci
                    code=getattr(obj,'kode_lot',None) or getattr(obj,'kode_proses')
                    result=await render_laci(req,'laporan_'+kind+'.html',kode=code,pdf_url=f'/riwayat-{kind}/{ident}/laporan.pdf')
            else:
                fn={'giling':history.detail_riwayat_giling,'pengeringan':history.detail_riwayat_pengeringan,'sosoh':sosoh.detail_riwayat_sosoh,'transfer':history.detail_riwayat_transfer}[kind]
                result=await fn(ident,req,account)
    elif m:=re.fullmatch(r'/riwayat-qc/([\w-]+)(?:/([\w-]+))?',path):
        kind,ref=m[1],m[2]
        if kind not in history.QC_PAGES:missing()
        obj=await own_model(scope,kind,ref,by_code=True) if ref else None
        try:result=await history.halaman_riwayat_qc(req,kind,account,ref)
        except HTTPException as exc:
            # Batch tanpa putaran mutu tetap punya rincian barang. Daftar
            # dan detail QC native tetap dipakai saat hasilnya tersedia.
            if exc.status_code!=404 or obj is None or kind not in ('gabah-basah','gabah-kering','pk-luar'):raise
            result=await batch_tanpa_qc(req,obj,kind)
    elif path=='/barang-keluar' or (m:=re.fullmatch(r'/barang-keluar/(\d+)',path)):
        oid=int(m[1]) if path!='/barang-keluar' else None
        if oid:await own_outgoing(scope,oid)
        result=await outgoing.halaman_barang_keluar(req,account,transaksi_id=oid,
            sebelum=integer(q.get('sebelum')),q=q.get('q',''),status=q.get('status',''),sejak=q.get('sejak',''))
    elif path=='/retur':
        result=await returns.halaman_retur(req,account,sebelum=integer(q.get('sebelum')),sebelum_pengajuan=integer(q.get('sebelum_pengajuan')))
    elif m:=re.fullmatch(r'/retur/(\d+)',path):
        from app.models import CustomerReturn
        if int(m[1]) not in scope.ids(CustomerReturn):missing()
        result=await returns.detail_retur(int(m[1]),req,account)
    elif m:=re.fullmatch(r'/retur/tiket/(\d+)',path):
        await own_ticket(scope,int(m[1]),retur=True)
        result=await applications.tiket_retur(int(m[1]),req,account)
    elif m:=re.fullmatch(r'/retur/pengajuan/(\d+)',path):
        from app.penggilingan.inventory.models import ReturRincian
        if int(m[1]) not in scope.ids(ReturRincian):missing()
        result=await applications.formulir(req,pengajuan_id=int(m[1]),akun=account)
    elif path=='/laporan':result=await reports(req)
    elif path=='/audit':result=await ownership(req)
    elif path=='/kabar':result=await news(req)
    else:missing()
    if isinstance(result,RedirectResponse):
        target=portal_url(result.headers['location'])
        if not target:missing()
        result=RedirectResponse(target,303)
    result.headers['Cache-Control']='no-store, private'
    result.headers['Vary']='Cookie'
    result.headers['X-Robots-Tag']='noindex, nofollow'
    return result


async def batch_tanpa_qc(request,batch,kind):
    from app.services.barang_masuk import hasil_qc
    from app.services.jasa_pelanggan import kg_rinci
    pk=kind=='pk-luar'
    async with SessionLocal() as db:
        mutu=await hasil_qc(db,[dict(model='pk' if pk else 'gabah',id=batch.id,kode=batch.kode_batch)])
    return render_customer(request,'portal/batch.html',batch=batch,mutu=mutu,kg=kg_rinci,
        jenis='Beras pecah kulit (PK)' if pk else 'Gabah '+batch.kondisi_gabah,page_title='Rincian batch')


async def history_list(request,kind):
    from app.web.tampilan import render_laci
    from app.penggilingan.gudang1.services.milling import riwayat_giling
    from app.penggilingan.gudang1.services.drying import riwayat_pengeringan
    from app.penggilingan.gudang2.polishing import riwayat_sosoh,SAMPING_DISEBUT
    from app.services.transfer import riwayat_transfer
    model=MODELS[kind][0]
    async with SessionLocal() as db:
        cards,more=await {'giling':riwayat_giling,'pengeringan':riwayat_pengeringan,'sosoh':riwayat_sosoh,'transfer':riwayat_transfer}[kind](db,
            batas=30,sebelum=integer(request.query_params.get('sebelum')),allowed_ids=request.state.portal_scope.ids(model))
    return await render_laci(request,'riwayat_'+kind+'.html',kartu=cards,lagi=more,SEKALI=30,
        sesudah=cards[-1].id if cards and more else None,dari_awal=bool(request.query_params.get('sebelum')),SAMPING_DISEBUT=SAMPING_DISEBUT)


async def reports(request):
    scope=request.state.portal_scope
    async with SessionLocal() as db:
        from app.models import Jasa
        # Pesanan asal yang digabung bukan dokumen tambahan. Tampilkan rekap
        # utama sekali; URL rekap lama tetap dilayani oleh pembaca produksi.
        orders=(await db.scalars(select(Jasa).where(Jasa.id.in_(scope.jasa_ids),
            Jasa.status!='digabung').order_by(Jasa.id.desc()))).all()
        from app.services.serah_terima import daftar as daftar_serah
        serah=await daftar_serah(db,scope=scope)
        rows=[]
        for kind in ('pengeringan','giling','sosoh'):
            model,col=MODELS[kind]
            for row in (await db.scalars(select(model).where(model.id.in_(scope.ids(model))).order_by(model.id.desc()))).all():
                finished=(row.waktu_selesai_pendinginan is not None if kind=='pengeringan' else row.status=='selesai')
                if finished:rows.append(dict(kind=kind,code=getattr(row,col),id=row.id))
    from .beranda import bahasa_status
    return render_customer(request,'portal/reports.html',reports=rows,orders=orders,
        serah_terima=serah[:10],status_pelanggan=bahasa_status,page_title='Dokumen')


async def ownership(request):
    from app.services import audit
    from app.models.portal import PortalOwnershipEvent
    from app.models import ActivityLog
    from app.web.tampilan import render_laci
    q=request.query_params;scope=request.state.portal_scope
    predicate=ActivityLog.id.in_(select(PortalOwnershipEvent.audit_id).where(PortalOwnershipEvent.pelanggan_id==scope.reader.pelanggan_id))
    async with SessionLocal() as db:
        rows,total=await audit.daftar(db,rentang=q.get('rentang','semua'),kelompok=q.get('kelompok','semua'),cari=q.get('cari','')[:200],customer_predicate=predicate)
    for row in rows:row.bisa_batal=False
    return await render_laci(request,'audit.html',catatan=rows,semua=total,pratinjau=None,
        rentang=q.get('rentang','semua'),kelompok=q.get('kelompok','semua'),cari=q.get('cari',''),RENTANG=audit.RENTANG,KELOMPOK=audit.KELOMPOK,JAM_BATAS=48,pesan='',err='',LAPORAN_NAV=True,
        portal_scope_note='Riwayat perubahan barang Anda. Sebagian catatan lama mungkin belum tersedia.')


def notice_predicate(scope):
    from app.models import Notification
    return or_(false(),*(and_(Notification.table_name==table,Notification.record_id.in_(ids))
                 for table,ids in scope.resources.items() if ids))


async def notice_rows(db,scope):
    from app.models import Notification
    from app.models.portal import PortalNotificationRead
    from app.services.kabar import Kabar,lengkapi
    read=PortalNotificationRead
    q=select(Notification,func.coalesce(read.dibaca,False)).outerjoin(read,
        and_(read.notification_id==Notification.id,read.account_id==scope.reader.account_id)).where(notice_predicate(scope)).order_by(Notification.created_at.desc(),Notification.id.desc())
    rows=(await db.execute(q)).all()
    result=[Kabar(n.id,n.tipe,n.pesan,n.prioritas,not seen,n.created_at,n.table_name,n.record_id) for n,seen in rows]
    await lengkapi(db,result)
    return result


async def news(request):
    from app.web.tampilan import render_laci
    scope=request.state.portal_scope;q=request.query_params
    async with SessionLocal() as db:rows=await notice_rows(db,scope)
    kinds=sorted({r.tipe for r in rows});unread=sum(r.baru for r in rows)
    selected=[r for r in rows if (q.get('tab')!='belum' or r.baru) and (not q.get('jenis') or r.tipe==q['jenis'])]
    cursor=integer(q.get('sebelum'))
    if cursor:selected=[r for r in selected if r.id<cursor]
    more=len(selected)>30;selected=selected[:30]
    group=OrderedDict()
    for r in selected:group.setdefault(r.waktu.strftime('%d/%m/%Y'),[]).append(r)
    return await render_laci(request,'kabar.html',grup=group,baru=unread,KABAR=unread,tab=q.get('tab',''),jenis=q.get('jenis',''),jenis_semua=kinds,
        href_kabar=lambda **params:'/kabar?'+urlencode({**dict(q),**params}),lagi=more,batas=30,konteks='/kabar',sampai=max((r.id for r in rows),default=0),sebelum=cursor,berikut=selected[-1].id if more else None)


@router.post('/kabar/status')
@router.post('/kabar/{notice_id:int}/buka')
async def notice_status(request:Request,notice_id:int|None=None,reader=Depends(require_customer)):
    from app.models import Notification
    from app.models.portal import PortalNotificationRead
    from sqlalchemy.dialects.postgresql import insert
    scope=await load_scope(reader);data=await request.form()
    ident=notice_id or integer(data.get('id'))
    state='dibaca' if notice_id else data.get('status')
    if state not in ('dibaca','belum') or (ident is None and state!='dibaca'):raise HTTPException(422,'Status baca tidak valid.')
    if ident is not None and ident<1:raise HTTPException(422,'Identitas kabar tidak valid.')
    target=None
    async with SessionLocal() as db:
        q=select(Notification).where(notice_predicate(scope))
        if ident:q=q.where(Notification.id==ident)
        notices=(await db.scalars(q)).all()
        if ident and not notices:missing()
        for n in notices:
            stmt=insert(PortalNotificationRead).values(account_id=reader.account_id,notification_id=n.id,dibaca=state=='dibaca')
            await db.execute(stmt.on_conflict_do_update(index_elements=['account_id','notification_id'],set_={'dibaca':state=='dibaca'}))
        if notice_id and notices:target=await notice_target(db,scope,notices[0])
        await db.commit()
    return RedirectResponse(portal_url(target) if target and portal_url(target) else '/pelanggan/kabar',303)


async def notice_target(db,scope,n):
    from app.models import (DryingLot,MillingProcess,PolishingProcess,PurchaseBatch,
                            PkPurchaseBatch,PkGudang2Intake)
    table=n.table_name;rid=n.record_id
    names={'drying_lots':('pengeringan',DryingLot),'milling_process':('giling',MillingProcess),
           'polishing_process':('sosoh',PolishingProcess)}
    if table in names:
        kind,model=names[table];row=await db.get(model,rid)
        if not row:return None
        if model is DryingLot:
            if row.waktu_selesai_pendinginan is not None:return f'/riwayat-pengeringan/{rid}'
            phase='pengeringan' if row.status=='proses' else 'pendinginan'
            return f'/proses-aktif/{phase}/{row.kode_lot}'
        if row.status=='proses':return f'/proses-aktif/{kind}/{row.kode_proses}'
        return f'/riwayat-{kind}/{rid}'
    for model in (PurchaseBatch,PkPurchaseBatch):
        if table==model.__tablename__:
            row=await db.get(model,rid)
            if row and row.timbangan_transaksi_id in scope.resources['timbangan_transaksi']:
                return f'/barang-masuk/{row.timbangan_transaksi_id}'
            return f'/jasa/pelanggan/{scope.reader.pelanggan_id}?tab=penerimaan'
    if table=='pk_gudang2_intakes':return f'/stok/pk/detail?gudang=g2&id={rid}'
    return {'internal_transfers':f'/riwayat-transfer/{rid}',
            'outgoing_records':f'/barang-keluar/{rid}','customer_returns':f'/retur/{rid}'}.get(table)
