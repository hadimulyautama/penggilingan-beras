"""Descriptor baca daftar; layanan/filter dan writer tetap milik jalur native."""

KOLOM = {
    'belum': ['Nama / tiket', 'Status', 'Komoditas', 'Nopol / Supir', 'Berat', 'Tindakan'],
    'diterima': ['Nama / tiket', 'Status', 'Barang', 'Armada', 'Bobot diterima', 'Penerimaan', 'Tindakan'],
}


def parameter(request):
    from app.web.layar_pekerjaan import pilihan
    from app.web.stok_navigasi import pelanggan_diminta
    from app.services.kelompok_kerja import JENIS_BARANG

    return dict(status=pilihan(request, 'status', {'belum', 'diterima'}, 'belum'),
                jenis=pilihan(request, 'jenis', dict(JENIS_BARANG)),
                pemilik=pilihan(request, 'kepemilikan', {'jasa', 'pabrik'}),
                gudang=pilihan(request, 'gudang', {'g1', 'g2'}),
                pid=pelanggan_diminta(request),
                cari=request.query_params.get('cari', '').strip(),
                pemasok=request.query_params.get('pemasok', ''))


def metadata(request, akun):
    from hmu_tampilan import CAP_ASET
    from app.web.halaman_bertahap import penanda_konteks

    return dict(BM_CONTEXT=penanda_konteks(request, akun), BM_CAP=CAP_ASET,
                BM_SCHEMAS=KOLOM)


def selesai(response, unavailable=False):
    if unavailable:
        response.body = response.body.replace(
            b'data-lk-cetak=""',
            b'data-lk-cetak="" disabled aria-describedby="bm-cetak-alasan"')
        response.headers['content-length'] = str(len(response.body))
    response.headers['Cache-Control'] = 'private, no-store'
    return response


async def kerangka(request, akun, konteks):
    from app.services.kelompok_kerja import JENIS_BARANG
    from app.web.halaman_bertahap import penanda
    from app.web.layar_pekerjaan import tautan
    from app.web.tampilan import render

    p = parameter(request)
    # Nilai pid/pemasok hanya mempertahankan query. Identitas pilihan dan
    # jumlah tidak direka atau dibaca dari koleksi sebelum GET data selesai.
    response = render(request, 'barang_masuk_pencarian.html',
        layar='barang_masuk', **{k: v for k, v in p.items() if k != 'pid'},
        jenis_barang=JENIS_BARANG, gagal=False, bm_loading=True,
        jumlah=None, total_belum=None, total_diterima=None,
        menunggu=[], riwayat=[], meta_tiket={}, nama_saring=[],
        pelanggan_saring='', halaman=1, halaman_akhir=1,
        href=lambda **q: tautan(request, '/barang-masuk', **q),
        buka='', nilai='', BM_STAMP=penanda(request, akun, 'barang-masuk'),
        BM_DATA_URL='/api/halaman-bertahap/barang-masuk' +
                    ('?' + request.url.query if request.url.query else ''),
        **metadata(request, akun),
        **{k: v for k, v in konteks.items() if k not in {'layar', 'SHELL'}})
    return selesai(response, True)
