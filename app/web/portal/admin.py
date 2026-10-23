"""Super Admin manages customer accounts without assigning a staff role."""
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Form, Path, HTTPException, Request
from sqlalchemy import select, func, or_
from sqlalchemy.exc import IntegrityError
from app.database import SessionLocal
from app.models import Pelanggan
from app.models.portal import PortalAccount
from app.services import portal_accounts as service
from app.web.security import butuh_akun
from app.web.tampilan import render,redirect

router=APIRouter(prefix='/pengguna/pelanggan',tags=['pengguna-pelanggan'])


async def super_only(akun=Depends(butuh_akun)):
    # No emergency Admin fallback: customer credentials are Super Admin only.
    if not akun.is_super:raise HTTPException(403,'Kelola akun pelanggan hanya untuk Super Admin.')
    return akun


async def page(request,*,message='',error='',selected=None,status=200):
    q=request.query_params.get('q','').strip()[:100]
    try:page_no=max(1,int(request.query_params.get('halaman','1')))
    except ValueError:page_no=1
    size=20
    valid=(Pelanggan.status=='aktif',Pelanggan.deleted_at.is_(None),Pelanggan.kledo_contact_id>0)
    unique_contacts=select(Pelanggan.kledo_contact_id).where(*valid).group_by(Pelanggan.kledo_contact_id).having(func.count()==1)
    terms=[*valid,Pelanggan.kledo_contact_id.in_(unique_contacts)]
    if q:
        terms.append(or_(Pelanggan.nama_pelanggan.icontains(q,autoescape=True),
                         Pelanggan.no_telfon.icontains(q,autoescape=True),
                         Pelanggan.kledo_contact_id==int(q) if q.isdecimal() and len(q)<18 else False))
    async with SessionLocal() as db:
        total=await db.scalar(select(func.count()).select_from(Pelanggan).where(*terms))
        contacts=(await db.scalars(select(Pelanggan).where(*terms).order_by(Pelanggan.nama_pelanggan,Pelanggan.id)
            .offset((page_no-1)*size).limit(size))).all()
        # Customer list is separate from staff users; never join users.role.
        rows=(await db.execute(select(PortalAccount,Pelanggan).join(Pelanggan,Pelanggan.id==PortalAccount.pelanggan_id)
            .order_by(PortalAccount.username))).all()
        chosen=next(((a,p) for a,p in rows if a.id==selected),None)
        if selected is not None and chosen is None:raise HTTPException(404,'Akun pelanggan tidak ditemukan.')
    return render(request,'pengguna_pelanggan.html',layar='pengaturan',kembali='/pengaturan',
        contacts=contacts,accounts=rows,chosen=chosen,q=q,page_no=page_no,total=total,
        previous='?'+urlencode({'q':q,'halaman':page_no-1}) if page_no>1 else '',
        following='?'+urlencode({'q':q,'halaman':page_no+1}) if page_no*size<total else '',
        pesan_ok=message,pesan_err=error,status_code=status)


@router.get('')
async def index(request:Request,actor=Depends(super_only)):
    return await page(request,message={'dibuat':'Akun pelanggan berhasil dibuat.','diubah':'Perubahan akun tersimpan.','status':'Status akun tersimpan.'}.get(request.query_params.get('ok'),''))


@router.post('/buat')
async def create(request:Request,kontak:str=Form(...),username:str=Form(...,max_length=80),
                 sandi:str=Form(...,max_length=512),konfirmasi:str=Form(...,max_length=512),actor=Depends(super_only)):
    try:
        try:kledo_id,pelanggan_id=map(int,kontak.split(':'))
        except (ValueError,TypeError):raise ValueError('Pilih pelanggan dari kontak Kledo.')
        async with SessionLocal() as db:
            await service.create(db,actor=actor,pelanggan_id=pelanggan_id,kledo_id=kledo_id,
                                 name=username,password=sandi,confirmation=konfirmasi)
            await db.commit()
    except ValueError as e:return await page(request,error=str(e),status=422)
    except IntegrityError:return await page(request,error='Username sudah digunakan. Muat ulang dan pilih username lain.',status=409)
    return redirect('/pengguna/pelanggan?ok=dibuat')


@router.get('/{account_id}')
async def detail(request:Request,account_id:int=Path(...,ge=1,le=2**31-1),actor=Depends(super_only)):
    return await page(request,selected=account_id)


@router.post('/{account_id}')
async def edit(request:Request,account_id:int=Path(...,ge=1,le=2**31-1),username:str=Form(...,max_length=80),
               sandi:str=Form('',max_length=512),konfirmasi:str=Form('',max_length=512),actor=Depends(super_only)):
    try:
        async with SessionLocal() as db:
            await service.edit(db,actor=actor,account_id=account_id,name=username,password=sandi,confirmation=konfirmasi)
            await db.commit()
    except ValueError as e:return await page(request,error=str(e),selected=account_id,status=422)
    except IntegrityError:return await page(request,error='Username sudah digunakan. Pilih username lain.',selected=account_id,status=409)
    return redirect('/pengguna/pelanggan?ok=diubah')


@router.post('/{account_id}/status')
async def status(request:Request,account_id:int=Path(...,ge=1,le=2**31-1),aktif:str=Form(...),actor=Depends(super_only)):
    if aktif not in ('0','1'):raise HTTPException(422,'Status tidak dikenal.')
    try:
        async with SessionLocal() as db:
            await service.set_active(db,actor=actor,account_id=account_id,active=aktif=='1');await db.commit()
    except ValueError as e:return await page(request,error=str(e),status=422)
    return redirect('/pengguna/pelanggan?ok=status')
