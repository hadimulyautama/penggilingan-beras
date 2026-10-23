"""Super Admin manages customer accounts without assigning a staff role."""
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Form, Path, HTTPException, Request
from fastapi.responses import JSONResponse
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


def contact_terms(q=''):
    valid=(Pelanggan.status=='aktif',Pelanggan.deleted_at.is_(None),Pelanggan.kledo_contact_id>0)
    unique_contacts=select(Pelanggan.kledo_contact_id).where(*valid).group_by(Pelanggan.kledo_contact_id).having(func.count()==1)
    terms=[*valid,Pelanggan.kledo_contact_id.in_(unique_contacts)]
    if q:
        terms.append(or_(Pelanggan.nama_pelanggan.icontains(q,autoescape=True),
                         Pelanggan.no_telfon.icontains(q,autoescape=True),
                         Pelanggan.kledo_contact_id==int(q) if q.isdecimal() and len(q)<18 else False))
    return terms


def contact_option(row):
    return dict(value=f'{row.kledo_contact_id}:{row.id}',name=row.nama_pelanggan,
                label=f'{row.nama_pelanggan} · Kledo #{row.kledo_contact_id}',phone=row.no_telfon or '')


async def page(request,*,message='',error='',selected=None,status=200,contact_value='',username=''):
    try:account_page=max(1,int(request.query_params.get('halaman_akun','1')))
    except ValueError:account_page=1
    account_search=request.query_params.get('cari_akun','').strip()[:100]
    size=20
    selected_contact=None
    async with SessionLocal() as db:
        try:
            kid,pid=map(int,contact_value.split(':'))
            if 0<pid<2**31 and 0<kid<2**63:
                row=await db.scalar(select(Pelanggan).where(*contact_terms(),Pelanggan.id==pid,Pelanggan.kledo_contact_id==kid))
                if row:selected_contact=contact_option(row)
        except (ValueError,TypeError):pass
        # Customer list is separate from staff users; never join users.role.
        account_terms=[]
        if account_search:
            account_terms.append(or_(PortalAccount.username.icontains(account_search,autoescape=True),
                                     Pelanggan.nama_pelanggan.icontains(account_search,autoescape=True)))
        account_query=select(PortalAccount,Pelanggan).join(Pelanggan,Pelanggan.id==PortalAccount.pelanggan_id)
        account_total=await db.scalar(select(func.count()).select_from(PortalAccount)
            .join(Pelanggan,Pelanggan.id==PortalAccount.pelanggan_id).where(*account_terms))
        account_page=min(account_page,max(1,(account_total+size-1)//size))
        rows=(await db.execute(account_query.where(*account_terms).order_by(PortalAccount.username)
            .offset((account_page-1)*size).limit(size))).all()
        chosen=(await db.execute(account_query.where(PortalAccount.id==selected))).first() if selected is not None else None
        if selected is not None and chosen is None:raise HTTPException(404,'Akun pelanggan tidak ditemukan.')
    return render(request,'pengguna_pelanggan.html',layar='pengaturan',kembali='/pengaturan',
        accounts=rows,chosen=chosen,selected_contact=selected_contact,username=username,
        account_total=account_total,account_search=account_search,account_page=account_page,
        account_previous='?'+urlencode({'cari_akun':account_search,'halaman_akun':account_page-1}) if account_page>1 else '',
        account_following='?'+urlencode({'cari_akun':account_search,'halaman_akun':account_page+1}) if account_page*size<account_total else '',
        pesan_ok=message,pesan_err=error,status_code=status)


@router.get('')
async def index(request:Request,actor=Depends(super_only)):
    return await page(request,message={'dibuat':'Akun pelanggan berhasil dibuat.','diubah':'Perubahan akun tersimpan.','status':'Status akun tersimpan.'}.get(request.query_params.get('ok'),''))


@router.get('/kontak')
async def contacts(request:Request,actor=Depends(super_only)):
    q=request.query_params.get('q','').strip()[:100]
    async with SessionLocal() as db:
        rows=(await db.scalars(select(Pelanggan).where(*contact_terms(q))
            .order_by(Pelanggan.nama_pelanggan,Pelanggan.id).limit(21))).all()
    return JSONResponse({'items':[contact_option(row) for row in rows[:20]],'more':len(rows)>20},
                        headers={'Cache-Control':'no-store'})


# Password length is validated in the service. FastAPI's default validation
# response includes the rejected input, which must never echo a password.
@router.post('/buat')
async def create(request:Request,kontak:str=Form(...),username:str=Form(...,max_length=80),
                 sandi:str=Form(...),konfirmasi:str=Form(...),actor=Depends(super_only)):
    try:
        try:kledo_id,pelanggan_id=map(int,kontak.split(':'))
        except (ValueError,TypeError):raise ValueError('Pilih pelanggan dari kontak Kledo.')
        async with SessionLocal() as db:
            await service.create(db,actor=actor,pelanggan_id=pelanggan_id,kledo_id=kledo_id,
                                 name=username,password=sandi,confirmation=konfirmasi)
            await db.commit()
    except ValueError as e:return await page(request,error=str(e),status=422,contact_value=kontak,username=username)
    except IntegrityError:return await page(request,error='Username sudah digunakan. Pilih username lain.',status=409,contact_value=kontak,username=username)
    return redirect('/pengguna/pelanggan?ok=dibuat')


@router.get('/{account_id}')
async def detail(request:Request,account_id:int=Path(...,ge=1,le=2**31-1),actor=Depends(super_only)):
    return await page(request,selected=account_id)


@router.post('/{account_id}')
async def edit(request:Request,account_id:int=Path(...,ge=1,le=2**31-1),username:str=Form(...,max_length=80),
               sandi:str=Form(''),konfirmasi:str=Form(''),actor=Depends(super_only)):
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
