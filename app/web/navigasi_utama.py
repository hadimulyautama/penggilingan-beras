"""Tab halaman utama memakai posisi kontrol yang sama."""


def siapkan(request, konteks):
    path = request.url.path
    if path in ('/pekerjaan', '/pekerjaan/catat-lain'):
        from urllib.parse import urlencode
        katalog = path.endswith('/catat-lain')
        href = konteks.get('href')
        tabs = []
        for k, n, total in [('tindakan', 'Perlu tindakan', 'total_tindakan'), ('berjalan', 'Berjalan', 'total_jalan')]:
            url = konteks.get('tab_' + k) if katalog else href(tab=k, asal='', kategori='', grup='', informasi='')
            tabs.append(dict(kunci=k, nama=n, href=url, jumlah=konteks.get(total, 0), boleh=True, alamat=[]))
        tujuan = '/pekerjaan/catat-lain?' + urlencode({'kembali': href()}) if href else path + ('?' + request.url.query if request.url.query else '')
        tabs.append(dict(kunci='lain', nama='Pekerjaan lain', href=tujuan, boleh=True, alamat=[]))
        konteks['MENU_AKTIF'] = 'pekerjaan'
        konteks['LAPORAN_NAV'] = dict(aktif='lain' if katalog else konteks.get('tab','tindakan'), kelompok_nama='Pekerjaan',
            tab_label='Tab pekerjaan', tab=tabs, pilihan=[], boleh_alamat=[], detail=False, panduan='pk-panduan')
        return
    retur = path == '/riwayat-retur-supplier' or path.startswith('/riwayat-retur-supplier/')
    if path != '/barang-masuk' and not retur:
        return
    detail = retur and path != '/riwayat-retur-supplier'
    aktif = 'retur-supplier' if retur else ('diterima' if konteks.get('status') == 'diterima' else 'belum')
    tautan = konteks.get('href') if not retur else None
    tabs = []
    for kunci, nama in [('belum', 'Belum diterima'), ('diterima', 'Diterima')]:
        url = tautan(status=kunci, halaman='') if tautan else '/barang-masuk?status=' + kunci
        t = dict(kunci=kunci, nama=nama, href=url, boleh=True, alamat=[])
        if not retur:
            t['jumlah'] = konteks.get('total_' + kunci, 0)
        tabs.append(t)
    tabs.append(dict(kunci='retur-supplier', nama='Retur ke Supplier', href='/riwayat-retur-supplier', boleh=True, alamat=[]))
    konteks['MENU_AKTIF'] = 'barang_masuk'
    konteks['LAPORAN_NAV'] = dict(aktif=aktif, kelompok_nama='Barang Masuk', tab_label='Bagian Barang Masuk',
        tab=tabs, pilihan=[], boleh_alamat=[], detail=detail,
        panduan=('rsd-panduan' if detail else 'rpd-panduan') if retur else 'bm-panduan')
    if detail:
        konteks.setdefault('breadcrumb_induk', dict(nama='Retur ke Supplier', alamat='/riwayat-retur-supplier'))
