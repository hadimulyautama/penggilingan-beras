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
    from app.web.layar_pekerjaan import tautan
    from app.services.kelompok_kerja import JENIS_BARANG
    from app.web.api import _is_g1_operator, _is_g2_operator, _is_gabah_operator
    from app.peran import can_see_financials
    from app.models import Pelanggan
    from app.web.barang_masuk_bertahap import parameter, metadata, selesai
    p = parameter(request)
    status,jenis,pemilik,gudang,pid,cari,pemasok = (p[k] for k in ('status','jenis','pemilik','gudang','pid','cari','pemasok'))
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
    from app.web.barang_masuk_detail_bertahap import katalog
    # Gunakan hanya hasil halaman yang telah digate reader native. Tiket
    # produk tanpa sumber aktif bisa beralih menjadi arsip: jangan ditebak.
    targets = ([detail(v['id']) for v in d['meta_tiket'].values()
                if v.get('jenis') in {'gabah_basah', 'gabah_kering', 'pk'}]
               if status == 'belum' else
               [detail(t['id']) for t in d['riwayat'] if not t.get('historis')])
    catalog = await katalog(request, akun, targets, navigasi=b.lencana()) if b and not gagal else None
    # Satu pembaca/satu template untuk navigasi biasa maupun permintaan Cari.
    response = render(request,'barang_masuk_pencarian.html',status_code=503 if gagal else 200,
        layar='barang_masuk',status=status,jenis=jenis,pemilik=pemilik,gudang=gudang,
        jenis_barang=JENIS_BARANG,cari=cari,pemasok=pemasok,gagal=gagal,pelanggan_saring=pelanggan_saring,
        detail_tiket=detail,detail_penerimaan={k:detail(v['id']) for k,v in d['meta_tiket'].items()},
        href=lambda **p:tautan(request,'/barang-masuk',**p),lama=berjalan._lama,buka='',nilai='',
        detail_catalog=catalog,**d,**metadata(request,akun),**(b.lencana() if b else {}))
    return selesai(response,gagal)
