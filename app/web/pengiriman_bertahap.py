"""Struktur daftar Pengiriman, setelah gate handler native dan sebelum data."""
import re


async def kerangka(request,akun,*,boleh_perintah,boleh_muat,pencarian,status,sejak,navigasi=None):
    from app.web.halaman_bertahap import konteks_kerangka,penanda
    from app.web.tampilan import render
    if navigasi is None:
        navigasi=await konteks_kerangka(request,akun)
    response=render(request,'pengiriman_bertahap.html',**navigasi,
        layar='barang_keluar',tab_pengiriman='keluar',
        SHELL=dict(kind='pengiriman',stamp=penanda(request,akun,'pengiriman'),
            data_url='/api/halaman-bertahap/pengiriman'+('?' +request.url.query if request.url.query else '')),
        BOLEH_PERINTAH=boleh_perintah,BOLEH_MUAT=boleh_muat,
        pencarian=pencarian,status_filter=status,sejak_filter=sejak,
        n_perintah='…',n_dimuat='…',riwayat=[],daftar_keluar=[],
        pengiriman_memuat=True)
    response.body=re.sub(rb'\bdata-bk-cetak(?:="")?(?=[\s>])',
        b'data-bk-cetak="" disabled aria-describedby="shell-cetak-alasan"',response.body)
    response.headers['content-length']=str(len(response.body))
    response.headers['Cache-Control']='private, no-store'
    return response
