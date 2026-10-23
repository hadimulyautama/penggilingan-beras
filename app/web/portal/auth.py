"""Portal login reuses password hashing, login throttling, CSRF and token format."""
from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from app.database import SessionLocal
from app.models.portal import PortalAccount
from app.web import csrf, gerbang_masuk
from app.web.security import HASH_TIRUAN, cek_sandi_async
from app.web.tampilan import templates
from .security import COOKIE, SESSION_SECONDS, issue, key, require_customer, secure_cookie
from hmu_identitas.token import baca_token
from hmu_tampilan import VERSI

router=APIRouter(prefix='/pelanggan')


def csrf_context(request):
    nonce=request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state,'csrf',None) or csrf.terbitkan_baru()
    request.state.csrf=nonce
    session=baca_token(key(),request.cookies.get(COOKIE))
    identity=(session['akun_id'],session['versi']) if session else None
    return csrf.untuk_sesi(nonce,identity,'portal-pelanggan')


def login_page(request, error='', status=200):
    return templates.TemplateResponse(request=request,name='portal/login.html',
        context={'csrf':csrf_context(request),'error':error,
                 'light':request.cookies.get('produksi_terik','1')=='1',
                 'VERSI':VERSI},status_code=status,
        headers={'Cache-Control':'no-store','Vary':'Cookie'})


@router.get('/masuk')
async def login_form(request:Request):
    return login_page(request)


@router.post('/masuk')
async def login(request:Request, username:str=Form(...,min_length=1,max_length=80), sandi:str=Form(...,min_length=1,max_length=512)):
    name=username.strip().casefold()
    limiter='portal:'+name;ip=request.client.host if request.client else ''
    if gerbang_masuk.boleh_coba(limiter,ip):return login_page(request,'Terlalu banyak percobaan. Coba lagi nanti.',429)
    async with SessionLocal() as db:
        account=await db.scalar(select(PortalAccount).where(PortalAccount.username==name))
        correct=await cek_sandi_async(sandi, account.password_hash if account else HASH_TIRUAN)
        if not correct or account is None or not account.active:
            gerbang_masuk.catat_gagal(limiter,ip)
            return login_page(request,'Nama pengguna atau kata sandi tidak sesuai.',401)
        value=issue(account)
    gerbang_masuk.catat_berhasil(limiter,ip)
    response=RedirectResponse('/pelanggan',303)
    response.set_cookie(COOKIE,value,max_age=SESSION_SECONDS,httponly=True,
                        secure=secure_cookie(request),samesite='lax',path='/pelanggan')
    response.set_cookie(csrf.NAMA_COOKIE,csrf.terbitkan_baru(),httponly=False,
                        secure=secure_cookie(request),samesite='lax',path='/')
    return response


@router.post('/keluar')
async def logout(request:Request, reader=Depends(require_customer)):
    response=RedirectResponse('/pelanggan/masuk',303)
    response.delete_cookie(COOKIE,path='/pelanggan')
    response.set_cookie(csrf.NAMA_COOKIE,csrf.terbitkan_baru(),httponly=False,
                        secure=secure_cookie(request),samesite='lax',path='/')
    return response
