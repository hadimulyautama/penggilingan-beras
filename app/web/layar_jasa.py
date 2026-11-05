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

from app.web.pdf_dokumen import buat_pdf_terkini
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
        tindakan_ids={id(x) for x in k.tindakan}
        masuk_ids={id(x) for x in k.masuk}
        for d in data['kartu']:
            cocok=await svc.saring_kartu(db,k.tindakan+k.masuk,d['id'])
            d['pekerjaan']=sum(id(x) in tindakan_ids for x in cocok)
            _tambah_tiket(d,[x for x in cocok if id(x) in masuk_ids])
    return await render_laci(
        request,"jasa.html",layar='jasa',**data,tapis=tapis,cari=cari,
        STATUS_PILIHAN=svc.STATUS,kg=svc.kg_rinci)


def _tambah_tiket(d,rows):
    kode_ada={x['kode'] for x in d['penerimaan']}
    for r in rows:
        if r.kode in kode_ada:
            continue
        kode_ada.add(r.kode)
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
    pilihan = dict(halaman=request.query_params.get('pesanan_halaman','1'),
                   cari=request.query_params.get('pesanan_cari',''),
                   status=request.query_params.get('pesanan_status',''),
                   fokus=request.query_params.get('pesanan_id') or
                         (request.query_params.get('nilai') if request.query_params.get('buka') in ('tutup_jasa','batalkan_jasa') else ''))
    async with SessionLocal() as db:
        d=await svc.pelanggan(db,pelanggan_id,read_scope=getattr(request.state,'portal_scope',None),
                              ringkasan_pesanan=pilihan if tab=='ringkasan' else None,
                              rincian=dict(tab=tab,halaman=request.query_params.get('rincian_halaman','1'),
                                           cari=request.query_params.get('rincian_cari','')))
        if d is None:
            raise HTTPException(404,'Pelanggan jasa tidak ditemukan.')
        b=await berjalan.untuk(db,akun.user,read_scope=getattr(request.state,'portal_scope',None))
        k=bagi(b)
        cocok=await svc.saring_kartu(db,k.tindakan+k.berjalan+k.informasi+k.masuk,pelanggan_id)
        tindakan_ids={id(x) for x in k.tindakan}
        masuk_ids={id(x) for x in k.masuk}
        d['pekerjaan']=sum(id(x) in tindakan_ids for x in cocok)
        _tambah_tiket(d,[x for x in cocok if id(x) in masuk_ids])
    params={k:v for k,v in request.query_params.items() if k in ('status','cari','halaman','pesanan_halaman','pesanan_cari','pesanan_status','rincian_halaman','rincian_cari')}
    pag=d.get('pesanan_paginasi')
    if pag and (pag['akhir']>1 or any(k.startswith('pesanan_') for k in request.query_params)):
        params.update(pesanan_halaman=str(pag['halaman']),pesanan_cari=pag['cari'],pesanan_status=pag['status'])
    konteks=f'/jasa/pelanggan/{pelanggan_id}?'+urlencode({'tab':tab,**params})
    kembali='/jasa?'+urlencode({k:v for k,v in request.query_params.items() if k in ('status','cari','halaman')})
    return await render_laci(request,'jasa_pelanggan_detail.html',layar='jasa',d=d,tab=tab,
        kembali=kembali,konteks=konteks,kg=svc.kg_rinci,ke=lambda h:svc.ke(h,konteks),
        stok_href=lambda t:'/stok?'+urlencode(dict(tab=t,pemilik='jasa',pelanggan_id=pelanggan_id)),
        kerja_href='/pekerjaan?'+urlencode(dict(pelanggan_id=pelanggan_id)),
        masuk_href='/barang-masuk?'+urlencode(dict(pelanggan_id=pelanggan_id)),
        pesanan_href=lambda halaman:'?'+urlencode({'tab':'ringkasan',**params,'pesanan_halaman':halaman}),
        rincian_href=lambda halaman:'?'+urlencode({'tab':tab,**params,'rincian_halaman':halaman}),
        pesanan_query={k:v for k,v in params.items() if k.startswith('pesanan_')},
        PESANAN_STATUS=svc.STATUS,
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
        return RedirectResponse(f'/jasa/pelanggan/{j.pelanggan_id}?tab=ringkasan&pesanan_id={j.id}#pesanan-{j.id}',303)


@router.get("/jasa/{jasa_id:int}/nota")
async def nota(jasa_id: int, request: Request, akun=Depends(butuh_akun)):
    """Rekap bersama untuk app produksi dan portal pelanggan."""
    from app.peran import can_see_financials
    from app.services.jasa import JUDUL_REKAP, JasaError, rekap_barang_jasa
    from app.services.bahan_silo import kg_rinci
    if not is_customer_read(request) and not can_see_financials(akun.user):
        raise HTTPException(403, "Layar Jasa milik Admin ke atas.")
    async with SessionLocal() as db:
        try:
            data = await rekap_barang_jasa(db, jasa_id)
        except JasaError as e:
            raise HTTPException(404, str(e))
    return await render_laci(request, "jasa_nota.html", d=data, kg=kg_rinci,
                            page_title=JUDUL_REKAP)


@router.get("/jasa/{jasa_id:int}/nota.pdf")
async def rekap_pdf(jasa_id: int, request: Request, unduh: int = 0,
                    akun=Depends(butuh_akun)):
    """PDF memakai penyusun data yang sama dengan halaman rekap."""
    from fastapi.responses import Response, RedirectResponse
    from app.peran import can_see_financials
    from app.services.jasa import JasaError, rekap_barang_jasa
    from app.web.rekap_jasa import buat_pdf
    if not is_customer_read(request) and not can_see_financials(akun.user):
        raise HTTPException(403, "Layar Jasa milik Admin ke atas.")
    async with SessionLocal() as db:
        try:
            data = await rekap_barang_jasa(db, jasa_id)
        except JasaError as e:
            raise HTTPException(404, str(e))
    if data['digabung']:
        suffix = "?unduh=1" if unduh else ""
        return RedirectResponse(f"/jasa/{data['digabung']['id']}/nota.pdf{suffix}", 303)
    return Response(await buat_pdf_terkini(buat_pdf,data), media_type="application/pdf", headers={
        "Content-Disposition": f'{"attachment" if unduh else "inline"}; filename="rekap-barang-jasa-{data["kode"]}.pdf"',
        "Cache-Control": "no-store, private", "Vary": "Cookie"})
