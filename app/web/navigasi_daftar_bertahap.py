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
    jenis = 'pekerjaan' if request.url.path == '/pekerjaan' and q.get('tab') == 'berjalan' else 'stok' if request.url.path == '/stok' else None
    # Halaman lain hanya mendaftarkan navigasi; jangan membaca identitas
    # data B1 atau menambah dependency pada renderer di luar dua alamat.
    konteks = penanda_konteks(request, request.state.akun) if jenis else ''
    if jenis:
        # Hanya schema kolom dan filter, tidak ada angka transaksi dalam adapter.
        nilai = getattr(response, 'context', {})
        nav = nilai.get('STOK_NAV') or {}
        tab = 'pekerjaan' if jenis == 'pekerjaan' else q.get('tab', 'bahan')
        config = dict(
            kind=jenis, columns=kolom_daftar(tab, bool(nilai.get('mutu_aktif', False))),
            scopeFiltered=bool(any(q.get(k) for k in (
                'jenis', 'gudang', 'pemasok', 'pelanggan_id', 'asal', 'kategori',
                'grup', 'informasi', 'kepemilikan')) or nav.get('pemilik', 'semua') != 'semua'),
        )
        data = ' data-daftar="'+escape(json.dumps(config,ensure_ascii=True),quote=True)+'"'
        extra = ('<link rel="stylesheet" href="/static/halaman-bertahap.css?v='+CAP_ASET+'">'
                 '<script src="/static/daftar-kosong-bertahap.js?v='+CAP_ASET+'"></script>')
    script = ('<script src="/static/navigasi-daftar-bertahap.js?v='
              + CAP_ASET + '" data-konteks="' + konteks + '"'+data+'></script>').encode()
    response.body = response.body.replace(marker, extra.encode() + script + marker, 1)
    response.headers["content-length"] = str(len(response.body))
    return response
