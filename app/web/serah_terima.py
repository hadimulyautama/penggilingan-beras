"""Rute baca dan PDF serah terima, dipakai bersama portal dan app internal."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from app.database import SessionLocal
from app.services import serah_terima as svc
from app.web.security import butuh_akun
from app.web.portal.scope import is_customer_read
from app.web.tampilan import render_laci

router=APIRouter(tags=['serah-terima'])


async def izin(request,akun):
    from app.web.api import _is_g1_operator,_is_g2_operator
    if is_customer_read(request):return True,True
    return await _is_g1_operator(akun.user),await _is_g2_operator(akun.user)


@router.get('/serah-terima')
async def daftar(request:Request,akun=Depends(butuh_akun)):
    g1,g2=await izin(request,akun)
    if not(g1 or g2):raise HTTPException(403,'Dokumen tidak tersedia untuk peran Anda.')
    try:page=max(1,int(request.query_params.get('halaman','1')))
    except ValueError:raise HTTPException(422,'Halaman tidak valid.')
    async with SessionLocal() as db:
        rows=await svc.daftar(db,scope=getattr(request.state,'portal_scope',None),g1=g1,g2=g2)
    last=max(1,(len(rows)+24)//25);page=min(page,last)
    return await render_laci(request,'serah_terima_daftar.html',layar='laporan',MENU_AKTIF='laporan_riwayat',serah_terima=rows[(page-1)*25:page*25],
        halaman=page,halaman_akhir=last,page_title='Serah Terima')


@router.get('/barang-masuk/{ident:int}/serah-terima')
@router.get('/barang-masuk/{ident:int}/serah-terima.pdf')
@router.get('/barang-keluar/{ident:int}/serah-terima')
@router.get('/barang-keluar/{ident:int}/serah-terima.pdf')
async def detail(ident:int,request:Request,akun=Depends(butuh_akun)):
    masuk='/barang-masuk/' in request.url.path
    g1,g2=await izin(request,akun)
    if not(g1 or g2):raise HTTPException(403,'Dokumen tidak tersedia untuk peran Anda.')
    async with SessionLocal() as db:
        if masuk:
            d=await svc.penerimaan(db,ident,scope=getattr(request.state,'portal_scope',None))
            allowed=g1 if d['jenis'].startswith('gabah') else g2
        else:
            if not g2:raise HTTPException(403,'Dokumen tidak tersedia untuk gudang Anda.')
            d=await svc.pengeluaran(db,ident,scope=getattr(request.state,'portal_scope',None));allowed=g2
    if not allowed:raise HTTPException(403,'Dokumen tidak tersedia untuk gudang Anda.')
    if request.url.path.endswith('.pdf'):
        if not d['siap']:raise HTTPException(409,d['status'])
        from app.web.pdf_serah_terima import buat_pdf
        unduh=request.query_params.get('unduh')=='1'
        return Response(buat_pdf(d),media_type='application/pdf',headers={
            'Content-Disposition':f'{"attachment" if unduh else "inline"}; filename="{d["nomor"]}.pdf"',
            'Cache-Control':'no-store, private','Vary':'Cookie'})
    return await render_laci(request,'serah_terima.html',d=d,layar='laporan',MENU_AKTIF='laporan_riwayat',page_title=d['judul'])
