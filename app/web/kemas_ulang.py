"""Halaman kemas ulang; seluruh perubahan hanya melalui POST terjaga sesi."""
from fastapi import APIRouter,Depends,Request,HTTPException
from pydantic import BaseModel,Field,StrictInt,ConfigDict
from sqlalchemy import select
from app.database import SessionLocal
from app.models import FinishedGoodsStock,User,ProductSku,PackageSize,PackagingMaterial,Brand,RiceQualityStandard,KemasUlang
from app.web.security import butuh_akun
from app.web.api import _is_g2_operator
from app.web.deps import pengguna_aksi
from app.web.tampilan import render_laci
from app.peran import can_see_financials
from app.services import kemas_ulang as svc
from app.penggilingan.inventory.packaging import InventoryError
router=APIRouter()

async def izin(user):
    if not (await _is_g2_operator(user) or can_see_financials(user)):
        raise HTTPException(403,'Kemas ulang hanya untuk Gudang 2 dan admin.')

@router.get('/stok-produk/kemas-ulang')
async def halaman(request:Request,sku_id:int,std_id:int|None=None,jasa_id:int|None=None,akun=Depends(butuh_akun)):
    await izin(akun.user)
    from app.web.aksi_inventory import kombinasi_kemasan
    from app.services.jasa import nama_pemilik_banyak
    async with SessionLocal() as db:
        sku=await db.get(ProductSku,sku_id)
        if not sku:raise HTTPException(404,'Produk tidak ditemukan.')
        mat=await db.get(PackagingMaterial,sku.packaging_material_id);size=await db.get(PackageSize,sku.package_size_id)
        brand=await db.get(Brand,sku.brand_id) if sku.brand_id else None
        std=await db.get(RiceQualityStandard,std_id) if std_id else None
        pemilik=(await nama_pemilik_banyak(db,[jasa_id])).get(jasa_id) if jasa_id else 'Milik pabrik'
        opsi=await svc.pilihan(db,sku_id,std_id,jasa_id,akun.user.id)
        materials={m.kode:m.nama for m in (await db.execute(select(PackagingMaterial))).scalars()}
        kemasan=[dict(value=f'{m}|{u}',label=f'{materials.get(m,m)} · {u} kg',ukuran=u) for _,m,u in kombinasi_kemasan(sku.kategori)]
        merek=list((await db.execute(select(Brand).where(Brand.aktif.is_(True),Brand.deleted_at.is_(None)))).scalars()) if sku.kategori in ('beras_putih','beras_b') else []
        hist=(await db.execute(select(KemasUlang,User.nama,PackagingMaterial.nama,PackageSize.ukuran_kg,Brand.nama).join(User,User.id==KemasUlang.petugas_id)
            .join(FinishedGoodsStock,FinishedGoodsStock.id==KemasUlang.sumber_id)
            .join(ProductSku,ProductSku.id==KemasUlang.sku_baru_id)
            .join(PackagingMaterial,PackagingMaterial.id==ProductSku.packaging_material_id)
            .join(PackageSize,PackageSize.id==ProductSku.package_size_id)
            .outerjoin(Brand,Brand.id==ProductSku.brand_id).where(
            KemasUlang.sku_asal_id==sku_id,
            FinishedGoodsStock.rice_quality_standard_id.is_(None) if std_id is None else FinishedGoodsStock.rice_quality_standard_id==std_id,
            KemasUlang.jasa_id.is_(None) if jasa_id is None else KemasUlang.jasa_id==jasa_id)
            .order_by(KemasUlang.id.desc()).limit(20))).all()
    nama=f'{std.nama if std else sku.kategori.replace("_"," ").title()} · {brand.nama if brand else "Tanpa merek"} · {mat.nama} {size.ukuran_kg} kg'
    return await render_laci(request,'kemas_ulang.html',layar='stok_produk_jasa' if jasa_id else 'stok_produk',nama_produk=nama,pemilik=pemilik,
        opsi=opsi,kemasan=kemasan,merek=merek,riwayat=hist)

class KemasReq(BaseModel):
    model_config=ConfigDict(extra="forbid")
    sumber_id:StrictInt
    kunci:str=Field(min_length=64,max_length=64)
    jumlah_asal:float=Field(gt=0,allow_inf_nan=False)
    material:str=Field(max_length=40)
    ukuran:StrictInt
    merk:str=Field(default='',max_length=200)
    jumlah_baru:StrictInt
    setuju:bool=False

@router.post('/api/kemas-ulang')
async def simpan(req:KemasReq,user=Depends(pengguna_aksi)):
    await izin(user)
    if not req.setuju:raise HTTPException(400,'Periksa berat asal, hasil, dan sisa sebelum konfirmasi.')
    async with SessionLocal() as db:
        try:
            r=await svc.simpan(db,user=await db.get(User,user.id),**req.model_dump(exclude={'setuju'}))
        except InventoryError as e:
            raise HTTPException(409,str(e))
    return dict(ok=True,id=r.id,berat_asal_kg=float(r.berat_asal_kg),berat_baru_kg=float(r.berat_baru_kg),sisa_kg=float(r.sisa_kg))

@router.get('/api/kemas-ulang/pilihan')
async def periksa(sumber_id:int,user=Depends(pengguna_aksi)):
    from app.models import FinishedGoodsStock
    await izin(user)
    async with SessionLocal() as db:
        row=await db.get(FinishedGoodsStock,sumber_id)
        if not row:raise HTTPException(404,'Batch asal tidak ditemukan.')
        return await svc.pilihan(db,row.product_sku_id,row.rice_quality_standard_id,row.jasa_id,user.id)

@router.get('/api/kemas-ulang/kemasan')
async def saldo(sumber_id:int,material:str,ukuran:int,merk:str='',user=Depends(pengguna_aksi)):
    await izin(user)
    async with SessionLocal() as db:
        try:
            return await svc.saldo_kemasan(db,sumber_id,material,ukuran,merk)
        except InventoryError as e:
            raise HTTPException(400,str(e))
