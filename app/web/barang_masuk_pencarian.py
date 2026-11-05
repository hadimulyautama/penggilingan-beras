"""Penyajian pencarian eksplisit; izin dan tindakan tetap dari layanan lama."""
import logging
from urllib.parse import urlencode
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from app.database import SessionLocal
from app.services import barang_masuk_daftar, berjalan
from app.web.tampilan import render

log = logging.getLogger(__name__)


async def halaman(request, akun):
    from app.web.layar_pekerjaan import pilihan, tautan
    from app.web.stok_navigasi import pelanggan_diminta
    from app.services.kelompok_kerja import JENIS_BARANG
    from app.web.api import _is_g1_operator, _is_g2_operator, _is_gabah_operator
    from app.peran import can_see_financials
    from app.models import Pelanggan
    status=pilihan(request,'status',{'belum','diterima'},'belum')
    jenis=pilihan(request,'jenis',dict(JENIS_BARANG))
    pemilik=pilihan(request,'kepemilikan',{'jasa','pabrik'})
    gudang=pilihan(request,'gudang',{'g1','g2'})
    pid=pelanggan_diminta(request)
    cari=request.query_params.get('cari','').strip()
    pemasok=request.query_params.get('pemasok','')
    pelanggan_saring=''
    gagal=False;b=None
    try:
        async with SessionLocal() as db:
            # Lencana umum tetap mengikuti definisi operasional lama. Tidak
            # dipakai untuk menyaring/memotong riwayat atau jumlah hasil.
            b=await berjalan.untuk(db,akun.user)
            if pid:
                pelanggan_saring=await db.scalar(select(Pelanggan.nama_pelanggan).where(Pelanggan.id==pid)) or 'Pelanggan tidak ditemukan'
            d=await barang_masuk_daftar.daftar(db,
                g1=await _is_gabah_operator(akun.user),g2=await _is_g2_operator(akun.user),admin=can_see_financials(akun.user),
                status=status,jenis=jenis,pemilik=pemilik,gudang=gudang,pid=pid,cari=cari,pemasok=pemasok,
                halaman=request.query_params.get('halaman','1'),user=akun.user)
    except SQLAlchemyError:
        log.exception('Pembacaan daftar Barang Masuk gagal')
        gagal=True
        d=dict(menunggu=[],riwayat=[],meta_tiket={},nama_saring=[],jumlah=None,
               total_belum=None,total_diterima=None,halaman=1,halaman_akhir=1)
    q={k:v for k,v in request.query_params.items() if k not in ('buka','nilai')}
    q.update(status=status,cari=cari)
    konteks='/barang-masuk?'+urlencode(q)
    def detail(tid):return '/barang-masuk/'+str(tid)+'?'+urlencode(dict(kembali_kerja=konteks))
    # Satu pembaca/satu template untuk navigasi biasa maupun permintaan Cari.
    return render(request,'barang_masuk_pencarian.html',status_code=503 if gagal else 200,
        layar='barang_masuk',status=status,jenis=jenis,pemilik=pemilik,gudang=gudang,
        jenis_barang=JENIS_BARANG,cari=cari,pemasok=pemasok,gagal=gagal,pelanggan_saring=pelanggan_saring,
        detail_tiket=detail,detail_penerimaan={k:detail(v['id']) for k,v in d['meta_tiket'].items()},
        href=lambda **p:tautan(request,'/barang-masuk',**p),lama=berjalan._lama,buka='',nilai='',
        **d,**(b.lencana() if b else {}))
