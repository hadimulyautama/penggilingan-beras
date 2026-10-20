"""Penyajian Stok terpadu; tidak menulis stok atau mengganti layanan hitung.

Alamat lama tetap menjadi alias tampilan. Identitas pelanggan selalu ID,
bukan nama atau label pesanan yang dapat sama untuk dua orang berbeda.
"""
from urllib.parse import urlencode, urlsplit, parse_qs

from fastapi import HTTPException

from app.database import SessionLocal
from app.web.layar import MEJA, POLESAN, gudang2

HALAMAN = {
    'stok.html': ('bahan', 'pabrik'),
    'stok_pk_jasa.html': ('bahan', 'jasa'),
    'stok_produk.html': ('produk', 'pabrik'),
    'stok_produk_jasa.html': ('produk', 'jasa'),
    'stok_karung.html': ('karung', 'pabrik'),
    'stok_karung_jasa.html': ('karung', 'jasa'),
}


def alamat(jenis='bahan', pemilik='pabrik', *, pelanggan_id='', gudang=''):
    params = {'tab': jenis, 'pemilik': pemilik}
    if pemilik == 'jasa' and pelanggan_id:
        params['pelanggan_id'] = pelanggan_id
    if gudang:
        params['gudang'] = gudang
    return '/stok?' + urlencode(params)


def pelanggan_diminta(request):
    nilai = request.query_params.get('pelanggan_id', '')
    if not nilai:
        return None
    try:
        pid = int(nilai)
        if pid > 0:
            return pid
    except ValueError:
        pass
    raise HTTPException(422, 'Pelanggan tidak dikenal. Pilih pelanggan dari daftar.')


def kembali_aman(nilai):
    """Konteks tampilan saja; tidak dapat mengubah izin atau tujuan transaksi."""
    try:
        bagian = urlsplit(nilai or '')
    except ValueError:
        return ''
    if bagian.path != '/stok' or bagian.netloc or bagian.scheme:
        return ''
    q = parse_qs(bagian.query)
    tab, pemilik = q.get('tab', ['bahan'])[0], q.get('pemilik', ['pabrik'])[0]
    pid, gudang = q.get('pelanggan_id', [''])[0], q.get('gudang', [''])[0]
    if tab not in {'bahan', 'produk', 'karung'} or pemilik not in {'pabrik', 'jasa'}:
        return ''
    if gudang not in {'', 'g1', 'g2'} or pid and (not pid.isascii() or not pid.isdigit() or int(pid) <= 0):
        return ''
    return alamat(tab, pemilik, pelanggan_id=pid, gudang=gudang)


async def siapkan(request, nama, konteks):
    if konteks.get('detail') or nama == 'stok_produk_detail.html':
        balik = kembali_aman(request.query_params.get('kembali_stok', ''))
        if balik:
            konteks['kembali'] = balik
            tambahan = urlencode({'kembali_stok': balik})
            if konteks.get('detail_href'):
                konteks['detail_href'] += '&' + tambahan
            # Tautan aksi dalam baris kemasan dibuat sebelum render.
            for baris in konteks.get('baris_kemasan', []):
                for kunci in ('href', 'kemas_baru', 'kemas'):
                    if baris.get(kunci):
                        baris[kunci] += ('&' if '?' in baris[kunci] else '?') + tambahan
            if konteks.get('halaman_aksi'):
                konteks['halaman_aksi'] += ('&' if '?' in konteks['halaman_aksi'] else '?') + tambahan
        return
    if nama not in HALAMAN:
        return
    jenis, pemilik = HALAMAN[nama]
    view = getattr(request.state, 'view', 'tamu')
    pid = pelanggan_diminta(request) if pemilik == 'jasa' else None
    gudang = request.query_params.get('gudang', '')
    if view not in MEJA or gudang not in {'g1', 'g2'}:
        gudang = ''
    pelanggan = []
    kelompok = []
    if pemilik == 'jasa':
        if jenis == 'bahan':
            from sqlalchemy import select
            from app.models import Jasa, Pelanggan
            barang = konteks['lot'] + konteks['tempat']
            ids = {b.jasa_id for b in barang if b.jasa_id is not None}
            async with SessionLocal() as db:
                rows = (await db.execute(
                    select(Jasa.id, Jasa.pelanggan_id, Pelanggan.nama_pelanggan)
                    .join(Pelanggan, Pelanggan.id == Jasa.pelanggan_id)
                    .where(Jasa.id.in_(ids))
                )).all()
            peta = {jid: (p, n) for jid, p, n in rows}
            # Nama pada kartu masih memuat kode pesanan; judul kelompok hanya
            # nama pelanggan. Tidak mengubah batas saldo/reservasi per pesanan.
            for pelanggan_id, nama_pelanggan in sorted(
                    set(peta.values()), key=lambda x: (x[1].casefold(), x[0])):
                lot = [b for b in konteks['lot'] if peta.get(b.jasa_id, (None,))[0] == pelanggan_id]
                tempat = [b for b in konteks['tempat'] if peta.get(b.jasa_id, (None,))[0] == pelanggan_id]
                kelompok.append(dict(pelanggan_id=pelanggan_id, pemilik=nama_pelanggan,
                                     lot=lot, tempat=tempat, total=sum(b.tersedia for b in lot)))
        else:
            kelompok = konteks['daftar']
        pelanggan = [(p['pelanggan_id'], p['pemilik']) for p in kelompok]
        if pid:
            # Filter yang tidak mempunyai saldo menghasilkan keadaan kosong,
            # bukan diam-diam menampilkan stok semua pelanggan.
            kelompok = [p for p in kelompok if p['pelanggan_id'] == pid]
            if pid not in {p for p, _ in pelanggan}:
                from sqlalchemy import select
                from app.models import Pelanggan
                async with SessionLocal() as db:
                    nama_pelanggan = (await db.execute(select(Pelanggan.nama_pelanggan)
                                                      .where(Pelanggan.id == pid))).scalar_one_or_none()
                if nama_pelanggan is None:
                    raise HTTPException(404, 'Pelanggan tidak ditemukan.')
                pelanggan.append((pid, nama_pelanggan))
        if jenis == 'bahan':
            konteks['kelompok_pk'] = kelompok
            konteks['lot'] = [b for p in kelompok for b in p['lot']]
            konteks['tempat'] = [b for p in kelompok for b in p['tempat']]
            konteks['total'] = sum(b.tersedia for b in konteks['lot'])
        else:
            konteks['daftar'] = kelompok

    # Produk lahir di G2; memilih G1 tidak boleh tetap menampilkan angka G2.
    if jenis == 'produk' and gudang == 'g1':
        if pemilik == 'jasa':
            konteks['daftar'] = []
        else:
            konteks.update(kartu=[], beras=[], samping=[], kemasan={},
                          sisa_beras=0, sisa_samping=0, curah_beras=0, curah_samping=0)
    if jenis == 'karung':
        def saring(baris):
            return [b for b in baris if b.get('kode') != 'bekas'
                    and (b['gudang'] != 'Gudang 1' or view in MEJA or pemilik == 'jasa')
                    and (not gudang or b['gudang'] == ('Gudang 1' if gudang == 'g1' else 'Gudang 2'))]
        if pemilik == 'jasa':
            konteks['daftar'] = [{**p, 'karung': saring(p['karung'])} for p in konteks['daftar']]
            konteks['daftar'] = [p for p in konteks['daftar'] if p['karung']]
        else:
            konteks['karung'] = saring(konteks['karung'])

    label = dict(bahan='Bahan & PK', produk='Produk', karung='Karung')[jenis]
    nama_pemilik = 'Pabrik' if pemilik == 'pabrik' else 'Titipan jasa'
    nama_pelanggan = dict(pelanggan).get(pid, 'Semua pelanggan')
    def href(tab=jenis, milik=pemilik, lokasi=gudang):
        return alamat(tab, milik, pelanggan_id=pid or '', gudang=lokasi)
    konteks['STOK_NAV'] = dict(
        url=alamat(jenis, pemilik, pelanggan_id=pid or '', gudang=gudang),
        jenis=jenis, pemilik=pemilik, pelanggan_id=pid or '', pelanggan=pelanggan,
        gudang=gudang, label=label, nama_pemilik=nama_pemilik,
        cakupan=nama_pemilik + (' · ' + nama_pelanggan if pemilik == 'jasa' else ''),
        lokasi=('Gudang 1' if gudang == 'g1' else 'Gudang 2') if gudang else
               ('Gudang 2' if jenis == 'produk' or view == POLESAN and jenis == 'karung' and pemilik == 'pabrik'
                else 'Gudang 1' if not gudang2(view) else 'Semua gudang'),
        tab=[dict(nama=n, kunci=k, href=href(k), boleh=k == 'bahan' or gudang2(view))
             for k, n in [('bahan', 'Bahan & PK'), ('produk', 'Produk'), ('karung', 'Karung')]],
        milik=[dict(nama=n, kunci=k, href=href(milik=k))
               for k, n in [('pabrik', 'Pabrik'), ('jasa', 'Titipan jasa')]],
        lokasi_pil=[dict(nama=n, kunci=k, href=href(lokasi=k))
                    for k, n in [('', 'Semua gudang'), ('g1', 'Gudang 1'), ('g2', 'Gudang 2')]]
                   if view in MEJA else [],
    )
