"""Barang Masuk dan Pekerjaan: susunan baru atas layanan serta tindakan lama."""

from app.web.portal.scope import is_customer_read
from urllib.parse import urlencode, urlsplit
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, text, bindparam
from app.database import SessionLocal
from app.services import berjalan as svc, barang_masuk as masuk
from app.services.kelompok_kerja import bagi, jenis_kerja, JENIS_KERJA, JENIS_BARANG
from app.web.security import butuh_akun
from app.web.tampilan import render

router = APIRouter(tags=['webapp'])


def konteks_aman(nilai):
    try:
        u = urlsplit(nilai or '')
    except ValueError:
        return ''
    return nilai if not u.netloc and not u.scheme and u.path in ('/barang-masuk', '/pekerjaan', '/kabar') else ''


def saring_pemilik(daftar, pemilik):
    return [x for x in daftar if not pemilik or x.kepemilikan in (pemilik, 'campuran')]


def pilihan(request, nama, sah, bawaan=''):
    nilai = request.query_params.get(nama, bawaan)
    return nilai if nilai in sah else bawaan


def tautan(request, dasar, **nilai):
    q = dict(request.query_params)
    for k in ('buka', 'nilai', 'halaman'):
        q.pop(k, None)
    q.update(nilai)
    return dasar + '?' + urlencode({k:v for k,v in q.items() if v})


async def siapkan_daftar_pekerjaan(request, user):
    """Daftar yang sama untuk isi pekerjaan dan angka pada tab katalog."""
    async with SessionLocal() as db:
        b = await svc.untuk(db, user, read_scope=getattr(request.state,'portal_scope',None))
    k = bagi(b)
    from app.web.stok_navigasi import pelanggan_diminta
    pid=pelanggan_diminta(request)
    pelanggan_saring=''
    if pid:
        from app.services.jasa_pelanggan import saring_kartu
        async with SessionLocal() as db:
            cocok=await saring_kartu(db,k.tindakan+k.berjalan+k.informasi,pid)
            from app.models import Pelanggan
            p=await db.get(Pelanggan,pid)
            pelanggan_saring=p.nama_pelanggan if p else 'Pelanggan tidak ditemukan'
        k.tindakan=[r for r in k.tindakan if r in cocok]
        k.berjalan=[r for r in k.berjalan if r in cocok]
        k.informasi=[r for r in k.informasi if r in cocok]
    return b, k, pelanggan_saring


def daftar_tab_pekerjaan(k, pemilik, gudang, jenis):
    def pilih(xs):
        xs = saring_pemilik(xs, pemilik)
        return [x for x in xs if not gudang or x.gudang == gudang]
    tindakan, berjalan, informasi = map(pilih, (k.tindakan, k.berjalan, k.informasi))
    total_tindakan = sum(not jenis or jenis_kerja(x) == jenis for x in tindakan)
    total_jalan = sum(not jenis or jenis_kerja(x) == jenis for x in berjalan + informasi)
    return tindakan, berjalan, informasi, total_tindakan, total_jalan


@router.get('/pekerjaan')
async def halaman_pekerjaan(request: Request, akun=Depends(butuh_akun), *, awal=None):
    b, k, pelanggan_saring = await siapkan_daftar_pekerjaan(request, akun.user)
    tab = pilihan(request, 'tab', {'tindakan', 'berjalan'}, awal or 'tindakan')
    pemilik = pilihan(request, 'kepemilikan', {'jasa','pabrik'})
    gudang = pilihan(request, 'gudang', {'g1','g2'})
    jenis = pilihan(request, 'jenis', dict(JENIS_KERJA))
    # Alias kategori keputusan/grup tetap dapat ditautkan. Tidak dipakai
    # sebagai izin; daftar sudah dibatasi untuk pengguna efektif oleh svc.
    grup = request.query_params.get('grup','')
    if grup == 'packing_jasa':
        grup = 'packing'
    kategori = pilihan(request,'kategori',dict(svc.GRUP_KEPUTUSAN))
    asal = request.query_params.get('asal','')
    tindakan, berjalan, informasi, total_tindakan, total_jalan = daftar_tab_pekerjaan(k, pemilik, gudang, jenis)
    if request.url.path=='/aksi' and 'tab' not in request.query_params and grup and not any(svc.grup_baris(x)==grup for x in tindakan) and any(svc.grup_baris(x)==grup for x in informasi):
        tab='berjalan'
    dasar = tindakan if tab == 'tindakan' else berjalan+informasi
    if tab == 'berjalan' and request.query_params.get('informasi') == '1':
        dasar = informasi
    if asal == 'mutu':
        from app.services.keputusan import golongan_mutu
        dasar = [x for x in dasar if golongan_mutu(x.aksi)]
    elif asal == 'keputusan':
        from app.services.keputusan import golongan_mutu
        dasar = [x for x in dasar if x in b.meja and not golongan_mutu(x.aksi)]
    if kategori:
        dasar = [x for x in dasar if svc.grup_keputusan(x) == kategori]
    if grup and grup in dict(svc.GRUP_ANTREAN):
        dasar = [x for x in dasar if svc.grup_baris(x) == grup]
    per_jenis = [(key,nama,sum(jenis_kerja(x)==key for x in dasar)) for key,nama in JENIS_KERJA]
    daftar = [x for x in dasar if not jenis or jenis_kerja(x)==jenis]
    from app.services.proses_aktif import alamat_detail
    konteks = '/pekerjaan?' + urlencode({q:v for q,v in request.query_params.items() if q not in ('buka','nilai')})
    def detail(x):
        a = alamat_detail(x)
        return a+'?'+urlencode({'kembali_kerja':konteks}) if a else ''
    # Hanya kartu tindakan permintaan yang memang disediakan bagi pembaca ini.
    detail_transfer_pk = [dict(id=x.nilai,kode=x.kode,href='/permintaan-pk/'+x.nilai+'?'+urlencode({'kembali_kerja':konteks}))
                          for x in daftar if x.fase=='pindah_pk' and (x.nilai or '').isdigit()
                          and x.aksi in ('acc_permintaan_pk','kirim_permintaan_pk','tutup_permintaan_pk')]
    from app.main import _pintasan_aksi
    from app.web.layar import view_untuk
    konteks_tampilan = dict(detail_transfer_pk=detail_transfer_pk,layar='pekerjaan',tab=tab,jenis=jenis,
        daftar=daftar,proses=[x for x in daftar if x in berjalan],
        informasi=[x for x in daftar if x not in berjalan],
        kelompok=[(key,nama,[x for x in daftar if jenis_kerja(x)==key]) for key,nama in JENIS_KERJA],
        total_tindakan=total_tindakan,total_jalan=total_jalan,per_jenis=per_jenis,pelanggan_saring=pelanggan_saring,
        href=lambda **p:tautan(request,'/pekerjaan',**p),alamat_detail_proses=detail,
        lama=svc._lama,PINTASAN=_pintasan_aksi(await view_untuk(akun.user)),
        buka=request.query_params.get('buka',''),nilai=request.query_params.get('nilai',''),
        gudang=gudang,nama_saring=sorted({x.judul for x in daftar if x.judul}))
    if detail_transfer_pk:
        return render(request, "pekerjaan_dengan_transfer.html", **konteks_tampilan, **b.lencana())
    return render(request, "pekerjaan.html", **konteks_tampilan, **b.lencana())


@router.get('/barang-masuk')
async def halaman_barang_masuk(request: Request, akun=Depends(butuh_akun)):
    from app.web.api import _is_g1_operator, _is_g2_operator
    from app.services.kelompok_kerja import dapat_ditindak
    async with SessionLocal() as db:
        b = await svc.untuk(db, akun.user, read_scope=getattr(request.state,'portal_scope',None))
        pending = bagi(b).masuk
        meta = {}
        if pending:
            ids = [x.kode for x in pending]
            q = text('SELECT kode,id,jenis_kode FROM timbangan_transaksi WHERE kode IN :ids').bindparams(bindparam('ids',expanding=True))
            meta = {r.kode:dict(r._mapping) for r in (await db.execute(q,{'ids':ids})).all()}
        riwayat = await masuk.riwayat(db,
            g1=True if is_customer_read(request) else await _is_g1_operator(akun.user),
            g2=True if is_customer_read(request) else await _is_g2_operator(akun.user),
            jasa_ids=request.state.portal_scope.jasa_ids if is_customer_read(request) else None)
        from app.web.stok_navigasi import pelanggan_diminta
        pid=pelanggan_diminta(request)
        pelanggan_saring=''
        if pid:
            from app.services.jasa_pelanggan import saring_kartu
            from app.models import Jasa,Pelanggan
            p=await db.get(Pelanggan,pid)
            pelanggan_saring=p.nama_pelanggan if p else 'Pelanggan tidak ditemukan'
            ids=set((await db.scalars(select(Jasa.id).where(Jasa.pelanggan_id==pid))).all())
            pending=await saring_kartu(db,pending,pid)
            riwayat=[t for t in riwayat if any(c['jasa_id'] in ids for c in t['catatan'])]
    status = pilihan(request,'status',{'belum','diterima'},'belum')
    jenis = pilihan(request,'jenis',dict(JENIS_BARANG))
    pemilik = pilihan(request,'kepemilikan',{'jasa','pabrik'})
    gudang = pilihan(request,'gudang',{'g1','g2'})
    pending = saring_pemilik(pending,pemilik)
    pending = [x for x in pending if not gudang or x.gudang==gudang]
    riwayat = [x for x in riwayat if (not pemilik or x['kepemilikan'] in (pemilik,'campuran')) and
               (not gudang or ('g1' if x['jenis'].startswith('gabah') else 'g2')==gudang)]
    total_belum,total_diterima = len(pending),len(riwayat)
    pending = [x for x in pending if not jenis or masuk.jenis_tiket(meta.get(x.kode,{}).get('jenis_kode'))==jenis]
    riwayat = [x for x in riwayat if not jenis or x['jenis']==jenis]
    try:
        halaman = max(1,int(request.query_params.get('halaman','1')))
    except ValueError:
        halaman = 1
    total_belum,total_diterima = len(pending),len(riwayat)
    jumlah = len(riwayat)
    halaman = min(halaman,max(1,(jumlah+24)//25))
    konteks = '/barang-masuk?' + urlencode({q:v for q,v in request.query_params.items() if q not in ('buka','nilai')})
    def detail(tid):
        return f'/barang-masuk/{tid}?'+urlencode({'kembali_kerja':konteks})
    return render(request, "barang_masuk.html",layar='barang_masuk',status=status,jenis=jenis,
        menunggu=pending,riwayat=riwayat[(halaman-1)*25:halaman*25],
        total_belum=total_belum,total_diterima=total_diterima,jenis_barang=JENIS_BARANG,pelanggan_saring=pelanggan_saring,
        meta_tiket=meta,detail_tiket=detail,
        detail_penerimaan={x.kode:detail(meta[x.kode]['id']) for x in pending if x.kode in meta},halaman=halaman,halaman_akhir=max(1,(jumlah+24)//25),
        jumlah=jumlah,href=lambda **p:tautan(request,'/barang-masuk',**p),lama=svc._lama,
        buka=request.query_params.get('buka',''),nilai=request.query_params.get('nilai',''),
        gudang=gudang,nama_saring=sorted({x.judul or x.kode for x in pending} if status=='belum' else {x['nama'] for x in riwayat}),**b.lencana())


@router.get('/barang-masuk/{tid:int}')
async def detail_barang_masuk(tid:int,request:Request,akun=Depends(butuh_akun)):
    from app.penggilingan.gudang1.services.timbang_link import ambil_tiket
    from app.web.api import _is_g1_operator,_is_g2_operator
    async with SessionLocal() as db:
        g1,g2 = (True,True) if is_customer_read(request) else (await _is_g1_operator(akun.user),await _is_g2_operator(akun.user))
        data = await masuk.riwayat(db,g1=g1,g2=g2,tid=tid,
            jasa_ids=request.state.portal_scope.jasa_ids if is_customer_read(request) else None)
        t = await ambil_tiket(db,tid)
        if t is None and data:
            t = await masuk.tiket_riwayat(db,tid)
        if not t or t.get('arah')!='MASUK':
            raise HTTPException(404,'Tiket masuk tidak ditemukan.')
        jenis = masuk.jenis_tiket(t['jenis_kode'])
        from app.peran import can_see_financials
        boleh = g1 if jenis.startswith('gabah') else g2 if jenis!='lain' else can_see_financials(akun.user)
        if not is_customer_read(request) and not boleh:
            raise HTTPException(403,'Tiket ini berada di gudang lain.')
        b = await svc.untuk(db,akun.user,read_scope=getattr(request.state,'portal_scope',None))
        pending = [x for x in bagi(b).masuk if x.kode==t['kode']]
        catatan = data[0]['catatan'] if data else []
        lokasi,proses,petugas = await masuk.rincian_lokasi(db,catatan)
        timbang = await masuk.rincian_timbang(db,tid)
        berat_diterima,keterangan_berat = masuk.bobot_diterima(catatan)
        qc_penerimaan = await masuk.hasil_qc(db,catatan)
        from app.models.retur_supplier import ReturSupplier
        retur_supplier_terkait=[] if is_customer_read(request) else (await db.scalars(
            select(ReturSupplier).where(ReturSupplier.penerimaan_tiket_id==tid).order_by(ReturSupplier.id.desc()))).all()
    kembali = konteks_aman(request.query_params.get('kembali_kerja')) or '/barang-masuk'
    proses = [(kode, url + ('&' if '?' in url else '?') + urlencode({'kembali_kerja':kembali})) for kode,url in proses]
    # Tab hanya memilih penyajian. Parameter pembuka formulir dan konteks asal
    # tetap dibawa agar refresh/tautan lama tidak kehilangan tujuan.
    tab_detail = pilihan(request, 'tab_detail', ('ringkasan','tiket','qc','riwayat'), 'ringkasan')
    def tab_href(tab):
        return request.url.path + '?' + urlencode({**dict(request.query_params), 'tab_detail':tab})
    return render(request, "barang_masuk_detail.html",tab_detail=tab_detail,tab_href=tab_href,layar='barang_masuk',kembali=kembali,
        tiket=t,jenis=jenis,menunggu=pending,catatan=catatan,lokasi=lokasi,proses=proses,petugas=petugas,
        timbang=timbang,berat_diterima=berat_diterima,keterangan_berat=keterangan_berat,
        qc_penerimaan=qc_penerimaan,
        akses_retur_supplier=not is_customer_read(request) and bool(t.get('supplier_id')) and any(c['status']!='ditolak' and c['jasa_id'] is None for c in catatan),
        boleh_retur_supplier=can_see_financials(akun.user),
        retur_supplier_terkait=retur_supplier_terkait,
        pemilik_penerimaan=' · '.join(dict.fromkeys(c['pemilik'] for c in catatan)),
        kepemilikan_penerimaan=data[0]['kepemilikan'] if data else '',
        lama=svc._lama,buka=request.query_params.get('buka',''),nilai=request.query_params.get('nilai',''),**b.lencana())


async def alias_keputusan(request, akun, asal):
    q = dict(request.query_params)
    q.update(asal=asal,tab='tindakan')
    scope = dict(request.scope)
    scope['query_string'] = urlencode(q).encode()
    return await halaman_pekerjaan(Request(scope),akun)


@router.get('/pekerjaan/permintaan/{permintaan_id:int}')
async def detail_permintaan(permintaan_id: int, request: Request,
                           akun=Depends(butuh_akun)):
    """Catatan permintaan saat ini; tidak menjalankan tindakan persetujuan.

    Jalur baca ini juga tersedia setelah permintaan keluar dari antrean,
    sehingga kabar historis tetap dapat membuka objek yang sama.
    """
    from app.models import PermintaanPk, MillingProcess
    from app.web.api import _is_g1_operator, _is_g2_operator
    from app.web.layar_kabar import kembali_aman
    from app.web.tampilan import render_laci
    if not (await _is_g1_operator(akun.user) or await _is_g2_operator(akun.user)):
        raise HTTPException(403, 'Permintaan ini tidak tersedia dalam cakupan Anda.')
    async with SessionLocal() as db:
        p = await db.get(PermintaanPk, permintaan_id)
        lot = await db.get(MillingProcess, p.milling_process_id) if p else None
    if p is None or lot is None:
        raise HTTPException(404, 'Catatan permintaan tidak ditemukan.')
    kembali = (kembali_aman(request.query_params.get('kembali_kabar'))
               if request.query_params.get('kembali_kabar') else '/pekerjaan')
    return await render_laci(request, 'permintaan_detail.html', layar='pekerjaan',
                             permintaan=p, lot=lot, kembali=kembali)
