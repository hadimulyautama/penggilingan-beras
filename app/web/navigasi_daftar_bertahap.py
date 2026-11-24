"""Pemasangan adapter aplikasi; tidak menyalin atau menyunting base paket.

Script berada di wilayah isi agar dokumen lama yang memakai PINDAH juga
memasangnya. Efeknya dibatasi ke dua alamat daftar, bukan navigasi global.
"""
def pasang(response, request):
    if response.status_code != 200 or not getattr(request.state, "akun", None):
        return response
    marker = b"<!-- isi-halaman:akhir -->"
    if marker not in response.body:
        return response
    from hmu_tampilan import CAP_ASET
    if request.url.path in {'/pekerjaan','/berjalan'} and b'proses-aktif-list__row' in response.body:
        # Exact visible native links only; no per-row DB lookup or data cache.
        try:
            from app.web.portal.scope import is_customer_read
            if not is_customer_read(request):
                from app.web.giling_work_catalog import catalog
                from app.web.halaman_bertahap import penanda_konteks
                from app.web.csrf import untuk_sesi
                from app.web.security import baca_token,NAMA_COOKIE
                from app.web import csrf
                import json
                from html import escape
                address=request.url.path+('?' +request.url.query if request.url.query else '')
                nonce=request.cookies.get(csrf.NAMA_COOKIE) or getattr(request.state,'csrf',None)
                context=penanda_konteks(request,request.state.akun)
                token=untuk_sesi(nonce,baca_token(request.cookies.get(NAMA_COOKIE)),request.cookies.get('produksi_lihat',''))
                targets=catalog(response.body.decode('utf-8'),source_address=address,
                    cap=CAP_ASET,context=context,session=token)
                if targets and targets['entries']:
                    from jinja2.utils import htmlsafe_json_dumps
                    payload=htmlsafe_json_dumps(targets).encode()
                    if len(payload)<=262144:
                        tag=('<script type="application/json" data-giling-native-catalog '
                             'data-source-address="'+escape(address,quote=True)+'" '
                             'data-source-sha="'+targets['sumber_sha256']+'">').encode()+payload+b'</script>'
                        response.body=response.body.replace(marker,tag+marker,1)
        except Exception as error:
            import logging
            logging.getLogger(__name__).warning('Katalog struktur Giling belum tersedia (%s)',type(error).__name__)
    # Struktur publik stabil siap sebelum DOM interaktif. Tidak berisi akun,
    # pilihan hak, saldo, draf atau token; pilihan per dokumen tetap no-store.
    asset=('<script src="/static/kerangka-ui.js?v='+CAP_ASET+'"></script>'
           '<script src="/static/kerangka-riwayat-ui.js?v='+CAP_ASET+'"></script>').encode()
    if response.body.count(b'</head>')==1:
        response.body=response.body.replace(b'</head>',asset+b'\n</head>',1)
    from app.web.halaman_bertahap import penanda_konteks
    from app.web.halaman_bertahap import kolom_daftar
    from html import escape
    import json
    data = ''
    extra = ''
    q = request.query_params
    jenis = 'pekerjaan' if request.url.path == '/pekerjaan' else 'stok' if request.url.path == '/stok' else None
    # Halaman lain hanya mendaftarkan navigasi; jangan membaca identitas
    # data B1 atau menambah dependency pada renderer di luar dua alamat.
    konteks = penanda_konteks(request, request.state.akun) if jenis else ''
    if jenis:
        # Hanya schema kolom dan filter, tidak ada angka transaksi dalam adapter.
        nilai = getattr(response, 'context', {})
        nav = nilai.get('STOK_NAV') or {}
        tab = ('pekerjaan' if nilai.get('tab') == 'berjalan' else 'tindakan') if jenis == 'pekerjaan' else q.get('tab', 'bahan')
        config = dict(
            kind=jenis, tab=nilai.get('tab', ''), columns=kolom_daftar(tab, bool(nilai.get('mutu_aktif', False))),
            scopeFiltered=bool(any(q.get(k) for k in (
                'jenis', 'gudang', 'pemasok', 'pelanggan_id', 'asal', 'kategori',
                'grup', 'informasi', 'kepemilikan')) or nav.get('pemilik', 'semua') != 'semua'),
        )
        data = ' data-daftar="'+escape(json.dumps(config,ensure_ascii=True),quote=True)+'"'
        extra = ('<link rel="stylesheet" href="/static/halaman-bertahap.css?v='+CAP_ASET+'">'
                 '<script src="/static/daftar-kosong-bertahap.js?v='+CAP_ASET+'"></script>')
    extra += '<script src="/static/kerangka-langsung.js?v='+CAP_ASET+'" defer></script>'
    extra += '<script src="/static/riwayat-navigasi-native.js?v='+CAP_ASET+'" defer></script>'
    script = ('<script src="/static/navigasi-daftar-bertahap.js?v='
              + CAP_ASET + '" data-konteks="' + konteks + '"'+data+'></script>').encode()
    response.body = response.body.replace(marker, extra.encode() + script + marker, 1)
    response.headers["content-length"] = str(len(response.body))
    return response
