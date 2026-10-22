"""Kabar pribadi: membaca peristiwa tidak mengerjakan transaksi asal."""
from urllib.parse import urlencode, urlsplit
from collections import OrderedDict
from fastapi import APIRouter, Depends, Request, HTTPException, Query
from fastapi.responses import RedirectResponse, JSONResponse
from app.database import SessionLocal, tanggal_lokal, now_local
from app.services import kabar as svc
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter(tags=["webapp"])


def kembali_aman(nilai):
    try:
        u = urlsplit(nilai or '')
    except ValueError:
        return '/kabar'
    return nilai if u.path == '/kabar' and not u.netloc and not u.scheme else '/kabar'


@router.get('/kabar')
async def halaman_kabar(request: Request, akun=Depends(butuh_akun),
                        tab: str = '', jenis: str = '', batas: int = Query(30, ge=1, le=100),
                        sampai: int | None = Query(None, ge=0),
                        sebelum: int | None = Query(None, ge=1)):
    async with SessionLocal() as db:
        jenis_semua = await svc.jenis_tersedia(db, akun.user)
        jenis = jenis if jenis in jenis_semua else ''
        tab = 'belum' if tab == 'belum' else ''
        if sampai is None:
            sampai = await svc.batas_histori(db, akun.user)
        baris = await svc.daftar(db, akun.user, jenis=jenis, belum=tab == 'belum',
                                 batas=batas + 1, sampai=sampai, sebelum=sebelum)
        await svc.lengkapi(db, baris[:batas])
        baru = await svc.jumlah_baru(db, akun.user)
    lagi = len(baris) > batas
    konteks = '/kabar?' + urlencode({k:v for k,v in dict(tab=tab, jenis=jenis, batas=batas, sampai=sampai, sebelum=sebelum).items() if v is not None})
    def href(**q):
        return '/kabar?' + urlencode({k:v for k,v in (dict(tab=tab, jenis=jenis, batas=batas, sampai=sampai, sebelum=sebelum) | q).items() if v is not None})
    grup = OrderedDict()
    for k in baris[:batas]:
        tanggal = tanggal_lokal(k.waktu)
        selisih = (now_local().date() - tanggal).days
        awalan = 'Hari ini · ' if selisih == 0 else 'Kemarin · ' if selisih == 1 else ''
        grup.setdefault(awalan + tanggal.strftime('%d/%m/%Y'), []).append(k)
    return await render_laci(request, "kabar.html", layar='kabar', grup=grup,
        baru=baru, KABAR=baru, tab=tab, jenis=jenis, jenis_semua=jenis_semua, href_kabar=href,
        lagi=lagi, batas=batas, konteks=konteks, sampai=sampai, sebelum=sebelum,
        berikut=baris[batas-1].id if lagi else None)


@router.get('/api/kabar/jumlah')
async def jumlah(akun=Depends(butuh_akun)):
    async with SessionLocal() as db:
        return JSONResponse({'belum': await svc.jumlah_baru(db, akun.user),
                             'merah': await svc.ada_merah(db, akun.user),
                             'terakhir': await svc.batas_histori(db, akun.user)},
                            headers={'Cache-Control': 'no-store'})


@router.post('/kabar/status')
async def status(request: Request, akun=Depends(butuh_akun)):
    data = await request.form()
    if data.get('status') not in ('dibaca', 'belum'):
        raise HTTPException(422, 'Status baca tidak valid.')
    try:
        id_ = int(data['id']) if data.get('id') else None
    except ValueError:
        raise HTTPException(422, 'Identitas kabar tidak valid.')
    if id_ is None and data['status'] != 'dibaca':
        raise HTTPException(422, 'Pilih satu kabar untuk ditandai belum dibaca.')
    async with SessionLocal() as db:
        await svc.tandai(db, akun.user, dibaca=data['status'] == 'dibaca', id_=id_)
    return RedirectResponse(kembali_aman(data.get('kembali')), 303)


@router.post('/kabar/{id_:int}/buka')
async def buka(id_: int, request: Request, akun=Depends(butuh_akun)):
    data = await request.form()
    kembali = kembali_aman(data.get('kembali'))
    async with SessionLocal() as db:
        n = await svc.ambil(db, akun.user, id_)
        tujuan = await svc.tujuan(db, akun.user, n)
        # Hanya status pribadi disimpan; target tidak pernah menerima POST ini.
        await svc.tandai(db, akun.user, dibaca=True, id_=id_)
    if not tujuan:
        return await render_laci(request, 'kabar_asal.html', layar='kabar', kembali=kembali)
    return RedirectResponse(tujuan + ('&' if '?' in tujuan else '?') +
                            urlencode({'kembali_kabar': kembali, 'kembali_kerja': kembali}), 303)
