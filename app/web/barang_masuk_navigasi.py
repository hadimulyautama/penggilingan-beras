"""Tab penerimaan dan retur supplier memakai posisi kontrol yang sama."""


def siapkan(request, konteks):
    path = request.url.path
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
