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
    script = ('<script src="/static/navigasi-daftar-bertahap.js?v='
              + CAP_ASET + '" data-konteks="' + konteks + '"'+data+'></script>').encode()
    response.body = response.body.replace(marker, extra.encode() + script + marker, 1)
    # Tautan katalog yang baru tampak sudah harus memakai navigator pada
    # klik pertama, sebelum script async pada panel tujuan sempat berjalan.
    # Hanya tujuan baca ini; tautan ?buka= dan penjaga editor tetap native.
    import re
    from html import unescape
    from urllib.parse import urlsplit, parse_qs
    def tab_katalog(match):
        tag = match.group(0)
        href = re.search(rb'\bhref="([^"]+)"', tag)
        if not href:
            return tag
        u = urlsplit(unescape(href[1].decode()))
        if (u.scheme or u.netloc or u.fragment or u.path != '/pekerjaan/catat-lain'
                or set(parse_qs(u.query, keep_blank_values=True)) - {'kembali'}):
            return tag
        return re.sub(rb'\sdata-utuh(?=[\s>])', b'', tag, count=1)
    response.body = re.sub(rb'<a\b[^>]*\bdata-tab-riwayat="lain"[^>]*>', tab_katalog, response.body)
    def tautan_muatan(match):
        tag = match.group(0)
        if b' data-utuh' not in tag:
            return tag
        href = re.search(rb'\bhref="([^"]+)"', tag)
        from app.web.muatan_kerangka import alamat_kerangka
        from app.web.pengambilan_kerangka import alamat_kerangka as alamat_pengambilan
        from app.web.perbaikan_kerangka import alamat_kerangka as alamat_perbaikan
        if href and any(check(unescape(href[1].decode())) for check in (alamat_kerangka, alamat_pengambilan, alamat_perbaikan)):
            return re.sub(rb'\sdata-utuh(?=[\s>])', b'', tag, count=1)
        return tag
    response.body = re.sub(rb'<a\b[^>]*>', tautan_muatan, response.body)
    # Tabel aktif secara eksplisit menuju varian native Rincian perintah.
    # Riwayat perjalanan/portal tetap memakai URL dan dokumen aslinya.
    from app.web.portal.scope import is_customer_read
    if not is_customer_read(request):
        def rincian_baris(match):
            row = match.group(0)
            target = re.search(rb'\bdata-detail-keluar="([^"]+)"', row)
            if not target:
                return row
            raw = unescape(target[1].decode())
            u = urlsplit(raw)
            q = parse_qs(u.query, keep_blank_values=True)
            if (u.scheme or u.netloc or u.fragment or not re.fullmatch(r'/barang-keluar/[1-9]\d*', u.path)
                    or set(q) - {'q','status','sejak','sebelum'} or any(len(v) != 1 for v in q.values())):
                return row
            declared = escape(raw + ('&' if '?' in raw else '?') + 'rincian_perintah=1', quote=True).encode()
            return row.replace(b'data-detail-keluar="'+target[1]+b'"', b'data-detail-keluar="'+declared+b'"',1).replace(b'href="'+target[1]+b'"',b'href="'+declared+b'"')
        response.body = re.sub(rb'<tr\b[^>]*class="keluar-baris"[^>]*>.*?</tr>', rincian_baris, response.body, flags=re.S)
    response.headers["content-length"] = str(len(response.body))
    return response
