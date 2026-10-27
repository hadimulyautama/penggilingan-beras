"""Server komponen lokal khusus data sintetis. Tidak menjadi paket aplikasi."""
import os
from pathlib import Path
from types import SimpleNamespace
from contextlib import asynccontextmanager
from sqlalchemy import select,text
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse,RedirectResponse
import hmu_tampilan
from app.database import SessionLocal,now_local
from app.models import User,Supplier,Warehouse,ProductSku,PackageSize,PackagingMaterial,FinishedGoodsStock
from app.services.seed import seed_master
from app.web import retur_supplier as web
from app.web.security import butuh_akun
from app.web import csrf
from hmu_identitas import peran as P
from tests.pg.test_retur_supplier import tiket

url=os.environ['DATABASE_URL']
assert '@127.0.0.1:56643/uji_rsp_ui' in url,'Server hanya boleh memakai profil UI sintetis milik tugas ini.'
state={'fault':'','uid':None,'wid':None,'tid':None}
@asynccontextmanager
async def life(app):
    async with SessionLocal() as db:
        # Profil komponen satu aplikasi: padankan lebar arah milik migrasi
        # retur TeraFlow. Uji dua aplikasi memakai migrasi aslinya tersendiri.
        if (await db.scalar(text("SELECT character_maximum_length FROM information_schema.columns WHERE table_name='timbangan_transaksi' AND column_name='arah'")))<16:
            await db.execute(text('ALTER TABLE timbangan_transaksi ALTER COLUMN arah TYPE varchar(16)'));await db.commit()
    await seed_master()
    async with SessionLocal() as db:
        # Isi sekali, tidak mengosongkan ulang saat reload proses.
        u=await db.scalar(select(User).where(User.nama=='Admin Uji Antarmuka Retur'))
        if not u:
            u=User(nama='Admin Uji Antarmuka Retur',role=P.ADMIN,status='aktif');sup=Supplier(nama_supplier='Supplier Sintetis dengan Nama Sangat Panjang untuk Pemeriksaan Tampilan Retur dan Keterbacaan Ponsel',kledo_contact_id=999001)
            db.add_all([u,sup]);await db.flush();wid=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g2'));u.default_warehouse_id=wid
            sku=ProductSku(kategori='beras_putih',aktif=True,packaging_material_id=await db.scalar(select(PackagingMaterial.id)),package_size_id=await db.scalar(select(PackageSize.id)))
            db.add(sku);await db.flush();tid=await tiket(db,sup.id)
            db.add_all([FinishedGoodsStock(product_sku_id=sku.id,source_type='timbangan',source_id=tid,jumlah_karung=20,berat_total_kg=998,warehouse_id=wid,input_by=u.id,waktu=now_local()),FinishedGoodsStock(product_sku_id=sku.id,source_type='timbangan',source_id=tid,jumlah_karung=0,berat_total_kg=123.45,curah_kemas_ulang=True,warehouse_id=wid,input_by=u.id,waktu=now_local())])
            rt=await tiket(db,sup.id,'RETUR_SUPPLIER','RETUR_KELUAR')
            await db.execute(text("UPDATE timbangan_transaksi SET timbang2_kg=5249.5,berat_barang_kg=249.5,status_tiket='SELESAI' WHERE id=:id"),dict(id=rt));await db.commit()
        state['uid']=u.id;state['wid']=u.default_warehouse_id
        state['tid']=await db.scalar(text("SELECT min(id) FROM timbangan_transaksi WHERE arah='MASUK'"))
    yield
app=FastAPI(lifespan=life);app.include_router(web.router)
app.mount('/static',hmu_tampilan.StatisBerlapis(Path(web.__file__).parent/'static'),name='static')
async def akun(request:Request):
    role=request.cookies.get('uji-role',P.ADMIN);wh=request.cookies.get('uji-wh','g2')
    async with SessionLocal() as db:wid=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi==wh))
    u=SimpleNamespace(id=state['uid'],role=role,default_warehouse_id=wid)
    a=SimpleNamespace(user=u,nama='Akun Uji Lokal',peran=role,sesi_pendek=False)
    request.state.akun=a;request.state.view='meja' if role==P.ADMIN else 'polesan'
    return a
app.dependency_overrides[butuh_akun]=akun
@app.middleware('http')
async def uji(request,call_next):
    nonce=request.cookies.get(csrf.NAMA_COOKIE) or csrf.terbitkan_baru();request.state.csrf=nonce
    if request.method=='POST' and not request.url.path.startswith('/_uji/'):
        if not csrf.cocok(csrf.untuk_sesi(nonce,None,''),request.headers.get(csrf.NAMA_HEADER)):return JSONResponse({'detail':'CSRF sintetis tidak cocok'},403)
    response=await call_next(request)
    if request.method=='POST' and state['fault']=='lost-response' and request.url.path.endswith(('/simpan','/keluar')):
        state['fault']='';response=JSONResponse({'detail':'Gangguan respons sintetis setelah commit','tidak_pasti':True},503)
    response.set_cookie(csrf.NAMA_COOKIE,nonce);return response
@app.get('/')
async def awal():return RedirectResponse(f'/barang-masuk/{state["tid"]}/retur-supplier')
@app.get('/_uji/akses')
async def akses(role:str=P.ADMIN,gudang:str='g2'):
    r=RedirectResponse('/');r.set_cookie('uji-role',role);r.set_cookie('uji-wh',gudang);return r
@app.post('/_uji/fault')
async def fault(request:Request):
    state['fault']=(await request.json()).get('mode','');return {'ok':True}

@app.get('/_uji/ponsel')
async def ponsel(path:str='/retur-supplier/1/penyelesaian',lebar:int=390):
    from fastapi.responses import HTMLResponse
    from html import escape
    assert 320<=lebar<=1440 and path.startswith('/') and not path.startswith('//')
    return HTMLResponse(f'<!doctype html><html><head><title>Uji komponen responsif lokal</title></head><body style="margin:0;background:#aaa"><iframe id="rsp-phone" title="PadiFlow uji responsif" src="{escape(path,quote=True)}" style="display:block;border:0;width:{lebar}px;height:844px;margin:auto"></iframe></body></html>')
