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


def alamat(jenis='bahan', pemilik=None, *, pelanggan_id='', gudang='', cari=''):
    pemilik = pemilik or 'semua'
    params = {'tab': jenis, 'pemilik': pemilik}
    if pemilik == 'jasa' and pelanggan_id:
        params['pelanggan_id'] = pelanggan_id
    if gudang:
        params['gudang'] = gudang
    if cari:
        params['cari'] = cari[:200]
    return '/stok?' + urlencode(params)


def pelanggan_diminta(request):
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request):
        return request.state.portal_scope.reader.pelanggan_id
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
    tab = q.get('tab', ['bahan'])[0]
    pemilik = q.get('pemilik', ['semua'])[0]
    pid, gudang = q.get('pelanggan_id', [''])[0], q.get('gudang', [''])[0]
    if tab not in {'bahan', 'produk', 'karung'} or pemilik not in {'semua', 'pabrik', 'jasa'}:
        return ''
    if (gudang not in {'','g1','g2'} and not (gudang.startswith('wh:') and gudang[3:].isascii() and gudang[3:].isdigit() and 0<int(gudang[3:])<=2147483647)) or pid and (not pid.isascii() or not pid.isdigit() or int(pid) <= 0):
        return ''
    return alamat(tab, pemilik, pelanggan_id=pid, gudang=gudang, cari=q.get('cari',[''])[0][:200])


async def siapkan(request, nama, konteks, *, metadata_navigasi=None):
    # Pembungkus kepemilikan tetap memakai kontrol template Stok asal.
    nama = (konteks.get("template_stok_asal")
            or konteks.get("template_kepemilikan_asal") or nama)
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
    from app.web.portal.scope import is_customer_read
    portal=is_customer_read(request)
    if konteks.get('semua_kepemilikan'):
        pemilik = 'semua'
    from app.peran import can_see_financials
    akun = getattr(request.state, "akun", None)
    konteks.setdefault("BOLEH_KEPEMILIKAN", bool(akun and can_see_financials(akun.user)))
    view = getattr(request.state, 'view', 'tamu')
    pid = pelanggan_diminta(request) if pemilik == 'jasa' else None
    gudang = request.query_params.get('gudang', '')
    if gudang not in {'g1','g2'} and not (gudang.startswith('wh:') and gudang[3:].isdigit()):gudang=''
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

    if jenis == 'karung':
        def saring(baris):
            rows=[b for b in baris if b.get('kode')!='bekas']
            if not gudang:return rows
            if gudang.startswith('wh:'):return [b for b in rows if str(b.get('warehouse_id',''))==gudang[3:]]
            return [b for b in rows if b['gudang']==('Gudang 1' if gudang=='g1' else 'Gudang 2')]
        if pemilik == 'jasa':
            konteks['daftar'] = [{**p, 'karung': saring(p['karung'])} for p in konteks['daftar']]
            konteks['daftar'] = [p for p in konteks['daftar'] if p['karung']]
        else:
            konteks['karung'] = saring(konteks['karung'])

    cari = request.query_params.get('cari', '')[:200]
    label = dict(bahan='Bahan & PK', produk='Produk', karung='Karung')[jenis]
    nama_pemilik = {'semua':'Semua kepemilikan', 'pabrik':'Pabrik', 'jasa':'Titipan jasa'}[pemilik]
    nama_pelanggan = dict(pelanggan).get(pid, 'Semua pelanggan')
    def href(tab=jenis, milik=pemilik, lokasi=gudang):
        return alamat(tab, milik, pelanggan_id=pid or '', gudang=lokasi, cari=cari)
    from app.services.cakupan_fasilitas import pilihan_filter_stok,pilihan_gudang
    from app.services.transfer_lokasi import daftar as daftar_lokasi
    choices=();metadata={}
    if akun:
        if metadata_navigasi is not None:
            choices,metadata=metadata_navigasi
        else:
            async with SessionLocal() as db:
                choices=await pilihan_filter_stok(db,akun.user) if jenis=='bahan' else tuple((w.kode_fungsi or 'wh:'+str(w.id),w.nama_gudang,'') for w in await pilihan_gudang(db,akun.user))
                metadata=await daftar_lokasi(db)
    by_code={m.get('kode_fungsi') or 'wh:'+str(wid):m for wid,m in metadata.items()}
    if len({by_code.get(code,{}).get('pabrik_id') for code,_,_ in choices}-{None})>1:
        choices=tuple((code,(by_code.get(code,{}).get('pabrik_nama') or 'Pabrik belum ditetapkan')+' → '+name,kind) for code,name,kind in choices)
    location_names={code:name for code,name,_ in choices}
    konteks['STOK_NAV'] = dict(
        url=alamat(jenis, pemilik, pelanggan_id=pid or '', gudang=gudang, cari=cari),
        jenis=jenis, pemilik=pemilik, pelanggan_id=pid or '', pelanggan=pelanggan,
        gudang=gudang, label=label, nama_pemilik=nama_pemilik,
        cakupan=nama_pemilik + (' · ' + nama_pelanggan if pemilik == 'jasa' else ''),
        lokasi=location_names.get(gudang,'Semua gudang'),
        tab=[dict(nama=n, kunci=k, href=href(k), boleh=portal or k == 'bahan' or bool(akun and (can_see_financials(akun.user) or getattr(akun.user,'default_warehouse_id',None))))
             for k, n in [('bahan', 'Bahan & PK'), ('produk', 'Produk'), ('karung', 'Karung')]],
        milik=[dict(nama=n, kunci=k, href=href(milik=k))
               for k, n in [('semua','Semua kepemilikan')] + [('pabrik', 'Pabrik'), ('jasa', 'Titipan jasa')]],
        lokasi_pil=[dict(nama=n, kunci=k, href=href(lokasi=k))
                    for k, n in [('', 'Semua gudang'),*[(code,name) for code,name,_ in choices]]],
    )
