"""Pemilik akun menentukan sandi lewat cap sekali pakai di fragment URL."""
import re
from pathlib import Path
from urllib.parse import urlsplit
from fastapi import APIRouter,Request,HTTPException
from fastapi.responses import FileResponse,JSONResponse
from pydantic import BaseModel,ConfigDict,Field,SecretStr
from sqlalchemy import select
from app.database import SessionLocal
from app.config import settings
from app.web.tampilan import render
from app.services import console_bantuan as svc
from hmu_core import Perusahaan

from app.web.console import RuteConsole
router=APIRouter(route_class=RuteConsole)

class Cap(BaseModel):
    model_config=ConfigDict(extra='forbid')
    cap:str=Field(min_length=64,max_length=64)
class Sandi(Cap):
    sandi:SecretStr=Field(min_length=8,max_length=512)
    ulangi:SecretStr=Field(min_length=8,max_length=512)


def privat(response):
    response.headers['Cache-Control']='no-store, private'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Robots-Tag']='noindex, nofollow'
    response.headers['X-Frame-Options']='DENY'
    return response

@router.get('/pemulihan')
async def halaman(request:Request):return privat(render(request,'pemulihan.html'))

@router.get('/monitoring/pemulihan.js')
async def skrip():return FileResponse(Path(__import__('hmu_identitas').__file__).parent/'assets/pemulihan.js',media_type='application/javascript')

@router.post('/pemulihan/periksa')
async def periksa(data:Cap):
    try:
        async with SessionLocal() as db:
            row,a=await svc.periksa_pemulihan(db,data.cap)
            name=await db.scalar(select(Perusahaan.nama).where(Perusahaan.id==row.company_id))
            return privat(JSONResponse(dict(nama=a['nama'],username=a['username'],perusahaan=name,jenis=a['jenis'])))
    except (ValueError,PermissionError,LookupError) as e:raise HTTPException(422,str(e))

@router.post('/pemulihan/simpan')
async def simpan(data:Sandi):
    try:
        async with SessionLocal() as db:
            a=await svc.pulihkan_sandi(db,cap=data.cap,sandi=data.sandi.get_secret_value(),ulangi=data.ulangi.get_secret_value())
            await db.commit()
        tujuan='/pelanggan/masuk' if a['jenis']=='pelanggan' else '/masuk'
        if a['jenis']=='timbangan_lama':
            url=settings.teraflow_web_url.rstrip('/');u=urlsplit(url)
            tujuan=url+'/timbangan/masuk' if u.scheme=='https' and u.netloc and not u.username and not u.password and u.path in ('','/') and not u.query and not u.fragment else None
        return privat(JSONResponse(dict(berhasil=True,tujuan=tujuan,jenis=a['jenis'])))
    except (ValueError,PermissionError,LookupError) as e:raise HTTPException(422,str(e))
