"""Detail baca transfer/permintaan, memakai formulir dan penjaga transaksi lama."""
from urllib.parse import urlsplit

from fastapi import APIRouter, Depends, HTTPException, Request

from app.database import SessionLocal
from app.models import InternalTransfer, MillingProcess, PermintaanPk
from app.services import detail_transfer, transfer
from app.web.security import butuh_akun
from app.web.tampilan import render_laci

router = APIRouter(tags=['webapp'])


def kembali_aman(nilai):
    try:u=urlsplit(nilai or '')
    except ValueError:return ''
    return nilai if not u.scheme and not u.netloc and u.path in (
        '/pekerjaan','/stok','/stok/pk/detail','/stok-pk-jasa','/riwayat-transfer','/kabar') else ''


async def tampilkan(request, akun, *, transfer_id=None, permintaan_id=None):
    from app.web.api import _is_g1_operator, actions_menu
    from app.services.penghalang_koreksi import daftar
    from app.web.portal.scope import is_customer_read
    if not is_customer_read(request) and not await _is_g1_operator(akun.user):
        raise HTTPException(403,'Riwayat Transfer milik Admin ke atas dan operator Gudang 1.')
    async with SessionLocal() as db:
        t=await db.get(InternalTransfer,transfer_id) if transfer_id is not None else None
        p=await db.get(PermintaanPk,permintaan_id) if permintaan_id is not None else None
        if (transfer_id is not None and t is None) or (permintaan_id is not None and p is None):
            raise HTTPException(404,'Catatan transfer atau permintaan tidak ditemukan.')
        # Operator G1 baru memperoleh pekerjaan sebelum transfer pada tahap disetujui.
        # Sesudah ada transfer, hak bacanya sama dengan riwayat G1 lama.
        if p and not akun.is_admin and p.status!='disetujui' and not p.internal_transfer_id:
            raise HTTPException(403,'Permintaan ini belum menjadi pekerjaan Gudang 1.')
        if p and p.internal_transfer_id:t=await db.get(InternalTransfer,p.internal_transfer_id)
        sumber=await db.get(MillingProcess,t.milling_process_id if t else p.milling_process_id)
        if sumber is None:raise HTTPException(404,'Proses penggilingan asal tidak ditemukan.')
        d=await detail_transfer.rincian(db,catatan=t,permintaan=p,params=request.query_params,
            read_scope=getattr(request.state,'portal_scope',None))
        p=d['permintaan']
        penghalang=await transfer.alasan_koreksi_transfer(db,t.id) if akun.is_admin and t else None
        catatan_penghalang=await daftar(db,'transfer',t.id) if penghalang else []
    menu={a['id']:a for a in await actions_menu(akun.user)}
    tindakan=[(id_,menu[id_]['label'],str(p.id)) for id_ in detail_transfer.AKSI.get(p.status,[]) if id_ in menu] if p else []
    gagal=getattr(request.state,'koreksi_gagal',None) or request.query_params.get('koreksi_gagal')
    tab=request.query_params.get('tab_detail')
    if tab is None:tab='riwayat' if gagal or request.query_params.get('koreksi') or 'halaman_transfer' in request.query_params else 'ringkasan'
    if gagal:tab='riwayat'
    if tab not in ('ringkasan','bahan','permintaan','riwayat'):tab='ringkasan'
    konteks_kembali=kembali_aman(request.query_params.get('kembali_kerja') or getattr(request.state,'kembali_koreksi',None))
    kembali=konteks_kembali or ('/riwayat-transfer' if t else '/pekerjaan')
    alamat=f'/riwayat-transfer/{transfer_id}' if transfer_id is not None else f'/permintaan-pk/{permintaan_id}'
    detail_url=request.url.replace(path=alamat)
    if konteks_kembali:detail_url=detail_url.include_query_params(kembali_kerja=konteks_kembali)
    return await render_laci(request,'detail_transfer.html',d=d,tab_transfer=tab,tindakan=tindakan,
        kembali=kembali,layar='riwayat_transfer' if t else 'pekerjaan',breadcrumb_detail=d['kode'],
        boleh_koreksi=akun.is_admin and t is not None,penghalang_koreksi=penghalang,
        catatan_penghalang=catatan_penghalang,hasil_awal=float(t.berat_kg) if t else None,
        hasil_koreksi=request.query_params.get('koreksi')=='berhasil',gagal_koreksi=gagal,
        isian_koreksi=getattr(request.state,'koreksi_form',{}),
        pengganti=request.query_params.get('pengganti'),pengganti_id=request.query_params.get('pengganti_id'),
        buka=request.query_params.get('buka',''),nilai=request.query_params.get('nilai',''),
        alamat=alamat,detail_url=detail_url,konteks_kembali=konteks_kembali)


@router.get('/permintaan-pk/{permintaan_id}')
async def detail_permintaan(permintaan_id:int,request:Request,akun=Depends(butuh_akun)):
    return await tampilkan(request,akun,permintaan_id=permintaan_id)
