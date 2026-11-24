"""Kerangka detail internal; data, pilihan dan tindakan tetap pembaca native.

Tidak menerbitkan izin, draf, versi simpan atau kunci penerimaan. Varian
arsip/portal tetap renderer lama; GET data memeriksa sumber kembali.
"""
from urllib.parse import urlencode

from fastapi import Request
from fastapi.responses import JSONResponse

TAB = (('ringkasan', 'Ringkasan'), ('tiket', 'Tiket & bobot'),
       ('qc', 'QC'), ('riwayat', 'Lokasi & riwayat'))


def memakai(request):
    from app.web.portal.scope import is_customer_read
    return (not is_customer_read(request)
            and not getattr(request.state, 'isi_detail_bertahap', False)
            and (request.headers.get('X-Kerangka-Halaman') == '1'
                 or request.headers.get('X-Pindah') != '1'
                 and request.headers.get('Sec-Fetch-Mode') == 'navigate'
                 and request.headers.get('Sec-Fetch-Dest') in {'document', 'empty'}))


def alamat(request):
    # Tab lokal boleh berganti saat GET berlangsung. Semua filter/konteks
    # lain tetap bagian identitas pembacaan; ini bukan otorisasi.
    q = [(k, v) for k, v in request.query_params.multi_items() if k != 'tab_detail']
    return request.url.path + ('?' + urlencode(q) if q else '')


def penanda(request, akun):
    from app.web.halaman_bertahap import penanda_konteks
    return penanda_konteks(request, akun) + '|' + alamat(request)


async def kerangka(tid, request, akun, *, navigasi=None):
    from app.web.halaman_bertahap import konteks_kerangka
    from app.web.layar_pekerjaan import pilihan, konteks_aman
    from app.web.tampilan import render
    tab = pilihan(request, 'tab_detail', dict(TAB), 'ringkasan')
    def tab_href(key):
        return request.url.path + '?' + urlencode({**dict(request.query_params), 'tab_detail': key})
    response = render(request, 'barang_masuk_detail_bertahap.html',
        layar='barang_masuk', tid=tid, tab_detail=tab, tabs=TAB, tab_href=tab_href,
        kembali=konteks_aman(request.query_params.get('kembali_kerja')) or '/barang-masuk',
        detail_stamp=penanda(request, akun),
        detail_data_url='/api/halaman-bertahap/barang-masuk-detail/' + str(tid)
                        + ('?' + request.url.query if request.url.query else ''),
        **(await konteks_kerangka(request, akun) if navigasi is None else navigasi))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


async def isi(tid, request, akun):
    from app.web.portal.scope import is_customer_read
    from fastapi import HTTPException
    from app.web.layar_pekerjaan import detail_barang_masuk
    if is_customer_read(request):
        raise HTTPException(403, 'Gunakan detail penerimaan pada portal pelanggan.')
    path = '/barang-masuk/' + str(tid)
    native = Request({**request.scope, 'path': path, 'raw_path': path.encode(),
                      'state': {**request.scope.get('state', {}), 'isi_detail_bertahap': True}})
    response = await detail_barang_masuk(tid, native, akun)
    if response.status_code != 200:
        raise HTTPException(409, 'Tujuan penerimaan berubah. Buka kembali dari Barang Masuk.')
    return JSONResponse(dict(stamp=penanda(native, akun), html=response.body.decode('utf-8')),
                        headers={'Cache-Control': 'private, no-store'})


async def katalog(request, akun, targets, *, navigasi):
    """Satu prototype, hanya untuk link aktif pada halaman daftar yang terbaca.

    Bukan matcher semua ID dan bukan cache transaksi. Arsip/portal tidak
    terdaftar. Kegagalan tambahan ini tidak membuang registry empat menu.
    """
    import logging
    from fastapi import HTTPException
    from hmu_tampilan import CAP_ASET
    from app.web.halaman_bertahap import penanda_konteks
    from urllib.parse import urlsplit
    if not targets:
        return None
    try:
        entries = []
        for target in dict.fromkeys(targets):
            url = urlsplit(target)
            native = Request({**request.scope, 'path': url.path, 'raw_path': url.path.encode(),
                              'query_string': url.query.encode(), 'state': dict(request.scope.get('state', {}))})
            entries.append(dict(alamat=target, stamp=penanda(native, akun)))
        assert 0 < len(entries) <= 25
        path = '/barang-masuk/0'
        native = Request({**request.scope, 'path': path, 'raw_path': path.encode(), 'query_string': b'',
                          'state': {**request.scope.get('state', {}), 'frame_kerangka_langsung': True,
                                    'menyusun_kerangka_langsung': True}})
        response = await kerangka(0, native, akun, navigasi=navigasi)
        if response.status_code != 200:
            return None
        # Chrome/menu yang sama sudah ada dalam registry empat tujuan.
        # Kirim hanya wilayah isi native: jangan menggandakannya per daftar.
        start, end = b'<!-- isi-halaman:mulai -->', b'<!-- isi-halaman:akhir -->'
        body = response.body
        if body.count(start) != 1 or body.count(end) != 1:
            return None
        content = body.split(start, 1)[1].split(end, 1)[0]
        return dict(versi=1, konteks=penanda_konteks(request, akun), cap=CAP_ASET,
                    penyandian='isi-1', targets=entries, html=content.decode('utf-8'))
    except HTTPException as e:
        # Sesi tidak sah bukan kegagalan descriptor opsional.
        if e.status_code not in {403, 404}:
            raise
        return None
    except Exception as e:
        logging.getLogger(__name__).warning('Kerangka detail opsional belum tersedia (%s)', type(e).__name__)
        return None
