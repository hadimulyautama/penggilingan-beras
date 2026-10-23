"""Layar Jasa — barang titipan pelanggan, dan apa yang masih ada di pabrik.

Tempat MENAMPILKAN, bukan tempat menerima. Pesanan jasa lahir di Pos Timbang
(pelanggan + pesanannya) lalu diterima operator lewat kartu Antrian tunggu;
halaman ini tak punya tombol "buat pesanan" sama sekali, dan itu disengaja —
pesanan yang bisa dibuat di dua tempat akan dibuat dua kali.

⚠ KENAPA HALAMAN INI HARUS ADA. Saringan `jasa_id IS NULL` membuang barang
pelanggan dari SETIAP layar stok — dan itu benar: ia bukan stok pabrik. Tetapi
akibatnya barang orang lain tak punya satu pun layar: ia ada di gudang,
memakan silo dan lantai, dan tak terbaca di mana pun. Halaman ini yang
menutup lubang yang dibuat saringan itu.
"""
from __future__ import annotations

from app.web.portal.scope import is_customer_read
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import SessionLocal
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter()


@router.get("/jasa")
async def halaman_jasa(request: Request, akun=Depends(butuh_akun)):
    """Satu pelanggan, seluruh pesanan dan saldo aslinya."""
    from app.peran import can_see_financials
    from app.services import jasa_pelanggan as svc, berjalan
    from app.services.kelompok_kerja import bagi
    if not can_see_financials(akun.user):
        raise HTTPException(403, "Layar Jasa milik Admin ke atas.")
    tapis = request.query_params.get('status','')
    if tapis not in dict(svc.STATUS):
        tapis=''
    cari=request.query_params.get('cari','').strip()[:200]
    try:
        halaman=max(1,int(request.query_params.get('halaman','1')))
    except ValueError:
        halaman=1
    async with SessionLocal() as db:
        data=await svc.daftar(db,cari=cari,status=tapis,halaman=halaman)
        b=await berjalan.untuk(db,akun.user,read_scope=getattr(request.state,'portal_scope',None))
        k=bagi(b)
        for d in data['kartu']:
            cocok=await svc.saring_kartu(db,k.tindakan+k.masuk,d['id'])
            d['pekerjaan']=sum(x in k.tindakan for x in cocok)
            _tambah_tiket(d,[x for x in cocok if x in k.masuk])
    return await render_laci(
        request,"jasa.html",layar='jasa',**data,tapis=tapis,cari=cari,
        STATUS_PILIHAN=svc.STATUS,kg=svc.kg_rinci)


def _tambah_tiket(d,rows):
    for r in rows:
        if any(x['kode']==r.kode for x in d['penerimaan']):
            continue
        d['penerimaan'].append(dict(id=None,kode=r.kode,jenis=r.judul or r.isi,
            catatan=[],pesanan='Mengikuti tiket asal',status='Belum diterima',
            href='/barang-masuk?'+urlencode(
                {'pelanggan_id':d['id'],'cari':r.kode})))


@router.get('/jasa/pelanggan/{pelanggan_id:int}')
async def detail_pelanggan(pelanggan_id:int,request:Request,akun=Depends(butuh_akun)):
    from app.peran import can_see_financials
    from app.services import jasa_pelanggan as svc,berjalan
    from app.services.kelompok_kerja import bagi
    from urllib.parse import urlencode
    if not is_customer_read(request) and not can_see_financials(akun.user):
        raise HTTPException(403,'Layar Jasa milik Admin ke atas.')
    tab=request.query_params.get('tab','ringkasan')
    if tab not in {'ringkasan','penerimaan','proses','stok','pengambilan'}:
        raise HTTPException(422,'Tab pelanggan tidak dikenal.')
    async with SessionLocal() as db:
        d=await svc.pelanggan(db,pelanggan_id,read_scope=getattr(request.state,'portal_scope',None))
        if d is None:
            raise HTTPException(404,'Pelanggan jasa tidak ditemukan.')
        b=await berjalan.untuk(db,akun.user,read_scope=getattr(request.state,'portal_scope',None))
        k=bagi(b)
        cocok=await svc.saring_kartu(db,k.tindakan+k.berjalan+k.informasi+k.masuk,pelanggan_id)
        d['pekerjaan']=sum(x in k.tindakan for x in cocok)
        _tambah_tiket(d,[x for x in cocok if x in k.masuk])
    konteks=f'/jasa/pelanggan/{pelanggan_id}?'+urlencode({'tab':tab,**{k:v for k,v in request.query_params.items() if k in ('status','cari','halaman')}})
    kembali='/jasa?'+urlencode({k:v for k,v in request.query_params.items() if k in ('status','cari','halaman')})
    return await render_laci(request,'jasa_pelanggan_detail.html',layar='jasa',d=d,tab=tab,
        kembali=kembali,konteks=konteks,kg=svc.kg_rinci,ke=lambda h:svc.ke(h,konteks),
        stok_href=lambda t:'/stok?'+urlencode(dict(tab=t,pemilik='jasa',pelanggan_id=pelanggan_id)),
        kerja_href='/pekerjaan?'+urlencode(dict(pelanggan_id=pelanggan_id)),
        masuk_href='/barang-masuk?'+urlencode(dict(pelanggan_id=pelanggan_id)),
        buka=request.query_params.get('buka',''),nilai=request.query_params.get('nilai',''))


@router.get('/jasa/{jasa_id:int}')
async def referensi_pesanan(jasa_id:int,request:Request,akun=Depends(butuh_akun)):
    from app.models import Jasa
    from app.peran import can_see_financials
    from fastapi.responses import RedirectResponse
    if not can_see_financials(akun.user):
        raise HTTPException(403,'Layar Jasa milik Admin ke atas.')
    async with SessionLocal() as db:
        j=await db.get(Jasa,jasa_id)
        if not j:
            raise HTTPException(404,'Pesanan tidak ditemukan.')
        return RedirectResponse(f'/jasa/pelanggan/{j.pelanggan_id}?tab=ringkasan#pesanan-{j.id}',303)


@router.get("/jasa/{jasa_id:int}/nota")
async def nota(jasa_id: int, request: Request, akun=Depends(butuh_akun)):
    """Nota satu pesanan — bobot & milik saja, tanpa satu pun angka uang."""
    from app.peran import can_see_financials
    from app.services.jasa import JasaError, nota_jasa

    if not is_customer_read(request) and not can_see_financials(akun.user):
        raise HTTPException(403, "Layar Jasa milik Admin ke atas.")
    async with SessionLocal() as db:
        try:
            teks = await nota_jasa(db, jasa_id)
        except JasaError as e:
            raise HTTPException(404, e.args[0] if e.args else "Tidak ditemukan.")
    return await render_laci(request, "jasa_nota.html", teks=teks,
                             jasa_id=jasa_id)
