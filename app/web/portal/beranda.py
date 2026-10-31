"""Bahasa dan pengelompokan pelanggan atas pembaca produksi yang sudah dibatasi.

Tidak membuat saldo, prediksi selesai, atau izin pengambilan baru. Transit
tetap berasal dari berjalan.untuk(..., read_scope=scope), termasuk perbaikan
pemeriksaan sumber silo/mesin milik portal.
"""
from copy import deepcopy

from app.database import SessionLocal
from .navigation import portal_url
from .presentation import render_customer

NAMA_PROSES = {'pengeringan':'Pengeringan', 'pendinginan':'Pendinginan',
               'giling':'Penggilingan', 'sosoh':'Penyosohan', 'transfer':'Pemindahan antargudang'}
STATUS = {'proses':'Sedang diproses', 'selesai':'Selesai',
          'berjalan':'Masih berlangsung', 'dibatalkan':'Dibatalkan',
          'digabung':'Digabung ke jasa lain', 'pending':'Menunggu petugas',
          'baru':'Menunggu petugas', 'dimuat':'Sudah dimuat',
          'menunggu_timbang':'Menunggu penimbangan', 'terverifikasi':'Sudah diverifikasi'}


def bahasa_status(nilai):
    return STATUS.get(nilai, (nilai or 'Belum tersedia').replace('_',' ').capitalize())


def status_penerimaan(nilai):
    return {'selesai':'Sudah diterima','belum diterima':'Menunggu penerimaan',
        'tautan tiket belum tersedia':'Penerimaan lama'}.get((nilai or '').lower(),bahasa_status(nilai))


def penerimaan_diterima(rows):
    hasil=[]
    for asli in rows:
        catatan=[]
        for c in asli.get('catatan',[]):
            if c.get('status')=='ditolak':continue
            # Gabah "baru" sudah diterima dan menunggu penempatan. PK
            # "baru" belum diterima; PK diterima lahir berstatus diterima.
            pk=c.get('model')=='pk' or asli['jenis'].upper().startswith('PK')
            if pk and c.get('status')=='baru':continue
            catatan.append(c)
        if catatan:hasil.append({**asli,'catatan':catatan,'status':'Sudah diterima'})
    return hasil


def kelompok_barang(d):
    """Tetap per catatan; bobot berbeda tahap tidak dijumlahkan."""
    bahan, hasil = [], []
    for asli in d.get('stok',[]):
        r=dict(asli)
        if r['kg'] == 0 and r.get('final'):
            continue
        r['nama_pelanggan']='Beras pecah kulit (PK)' if r['nama']=='PK' else r['nama']
        r['href']=portal_url(r.get('href','')) if r.get('href') else None
        # Produk ditandai oleh pembaca stok. PK bisa berasal dari pelanggan
        # sebagai bahan masuk; jangan menyebut seluruh PK sebagai hasil jasa.
        (hasil if 'kemasan_kg' in r else bahan).append(r)
    return bahan, hasil


def status_utama(d, transit):
    aktif=[r for r in d.get('proses',[]) if r['status']=='proses']
    bahan,hasil=kelompok_barang(d)
    if aktif:
        jenis=list(dict.fromkeys(NAMA_PROSES.get(r['jenis'],r['jenis']) for r in aktif))
        return dict(label='Sedang diproses',judul='Ada proses yang sedang berjalan.',
                    isi='Tahap yang sedang berjalan: '+', '.join(jenis)+'.',jenis='proses')
    if transit:
        return dict(label='Menunggu proses',judul='Barang Anda masih di pabrik.',
                    isi='Bahan di silo atau mesin sedang menunggu tahap berikutnya. Proses belum dimulai.',jenis='transit')
    if bahan:
        return dict(label='Barang di pabrik',judul='Barang Anda masih tercatat di pabrik.',
                    isi='Lihat lokasi dan perkembangan setiap barang di bawah. Hubungi petugas untuk memastikan pengambilan.',jenis='bahan')
    if hasil:
        return dict(label='Hasil tercatat',judul='Ada hasil yang masih tercatat di pabrik.',
                    isi='Lihat berat dan kondisi hasilnya. Hubungi petugas untuk memastikan pengambilan.',jenis='hasil')
    if d.get('penerimaan'):
        if all(r.get('status')=='Belum diterima' for r in d['penerimaan']):
            return dict(label='Menunggu penerimaan',judul='Tiket barang Anda sudah tercatat.',
                        isi='Petugas belum mencatat penerimaan barang di produksi. Perkembangannya akan tampil setelah penerimaan dicatat.',jenis='penerimaan')
        return dict(label='Penerimaan tercatat',judul='Penerimaan barang Anda sudah tercatat.',
                    isi='Buka Riwayat proses atau Pengambilan barang untuk melihat catatan sebelumnya.',jenis='riwayat')
    if d.get('pesanan'):
        return dict(label='Riwayat jasa',judul='Catatan jasa Anda tetap tersedia.',
                    isi='Belum ada saldo barang yang tercatat saat ini. Riwayat proses dan dokumen tetap dapat dibuka.',jenis='riwayat')
    return dict(label='Belum ada catatan',judul='Belum ada barang atau pesanan.',
                isi='Barang Anda akan tampil setelah penerimaannya dicatat petugas. Jika sudah menyerahkan barang, hubungi petugas untuk memeriksa pencatatannya.',jenis='kosong')


def baris_transit(rows):
    # Hanya proyeksikan bidang baca. Aksi/tombol operator tidak ikut dikirim.
    return [dict(nama=r.judul or r.kode, kode=r.kode, isi=r.isi,
                 berat=' '.join(map(str,r.utama)) if r.utama else None,
                 sejak=r.sejak, lokasi={'g1':'Gudang 1','g2':'Gudang 2'}.get(r.gudang,''),
                 status='Menunggu proses', rincian=r.anak)
            for r in rows]


def progres_berjalan(rows,scope):
    """Angka kemajuan/hasil dari pembaca produksi; rendemen bukan persen selesai."""
    from app.services.proses_aktif import alamat_detail
    hasil=[]
    for r in rows:
        href=alamat_detail(r)
        if r.kode not in scope.codes or not href:
            continue
        jenis=href.split('/')[2]
        neraca=[]
        if r.neraca:
            neraca=[dict(nama=x.nama,kg=x.kg) for x in [r.neraca.beras,*r.neraca.samping]]
        hasil.append(dict(kode=r.kode,judul=NAMA_PROSES.get(jenis,jenis),
            href=portal_url(href),mulai=r.sejak,status='Dijeda' if r.nota_jenis=='hati' else 'Sedang berjalan',
            catatan=r.nota if r.nota_jenis=='hati' else None,
            maju=r.maju if jenis=='pengeringan' else None,
            fakta=[({'Alat tes':'Kadar air','Mesin':'Bacaan mesin','Target':'Target kadar air',
                'Bahan':'Bahan masuk','Hasil':'Hasil sementara','Mutu':'Pemeriksaan mutu'}.get(k,k),
                v.replace('rendemen','rasio hasil')) for k,v in r.fakta if k!='Mode'],neraca=neraca,
            ringkas=r.ringkas,rendemen=r.rendemen_sementara))
    return hasil


async def halaman(request, bagian='beranda'):
    from app.models import OutgoingRecord,CustomerReturn,DryingLot
    from sqlalchemy import select
    from app.services import jasa_pelanggan,berjalan
    from .barang import baca as baca_barang
    scope=request.state.portal_scope
    async with SessionLocal() as db:
        d=await jasa_pelanggan.pelanggan(db,scope.reader.pelanggan_id,
            rinci=bagian!='beranda',read_scope=scope)
        d=deepcopy(d) if d else dict(id=scope.reader.pelanggan_id,
            pesanan=[],penerimaan=[],proses=[],stok=[],pengiriman=[],retur=[])
        b=await berjalan.untuk(db,scope.reader,read_scope=scope)
        # Barang masuk berarti penerimaan aktual, bukan tiket antrean.
        # Catatan penolakan tidak menjadi riwayat barang yang diterima.
        d['penerimaan']=penerimaan_diterima(d['penerimaan'])
        daftar_masuk={}
        if bagian=='masuk':
            from .masuk import daftar
            daftar_masuk=await daftar(db,scope,d['penerimaan'],request)
        komoditas=await baca_barang(db,scope,d) if bagian in ('beranda','barang') else []
        # Status "selesai" pada pengeringan hanya menutup fase kering.
        # Pendinginan masih berjalan sampai waktunya benar-benar dicatat.
        pendinginan={r.kode_lot for r in (await db.scalars(select(DryingLot).where(
            DryingLot.id.in_(scope.ids(DryingLot)),DryingLot.status=='selesai',
            DryingLot.waktu_selesai_pendinginan.is_(None)))).all()}
        if bagian=='riwayat':
            from .scope import MODELS
            for jenis in NAMA_PROSES:
                if jenis=='pendinginan':continue
                model,col=MODELS[jenis]
                rows=(await db.scalars(select(model).where(model.id.in_(scope.ids(model))))).all()
                dates={getattr(r,col):(getattr(r,'waktu_selesai_pendinginan',None)
                    if jenis=='pengeringan' else getattr(r,'waktu',None)
                    if jenis=='transfer' else getattr(r,'waktu_selesai',None)) for r in rows}
                for r in d['proses']:
                    if r['jenis']==jenis:r['selesai']=dates.get(r['kode'])
    d['proses']=[r for r in d['proses'] if r['kode'] in scope.codes]
    for r in d['proses']:
        if r['jenis']=='pengeringan' and r['kode'] in pendinginan:
            r.update(jenis='pendinginan',status='proses',href=f"/proses-aktif/pendinginan/{r['kode']}")
    d['pengiriman']=[r for r in d['pengiriman'] if r['id'] in scope.ids(OutgoingRecord)]
    d['retur']=[r for r in d['retur'] if r.get('href') in {f'/retur/{i}' for i in scope.ids(CustomerReturn)}]
    for r in d['retur']:
        r['asal']=[a for a in r.get('asal',[]) if a['id'] in scope.ids(OutgoingRecord)]
    for t in d['penerimaan']:
        t['proses']=[(code,href) for code,href in t.get('proses',[]) if code in scope.codes]
    bahan,hasil=kelompok_barang(d)
    transit=baris_transit(b.transit)
    progres=progres_berjalan(b.berjalan,scope)
    # Data proses lama dapat belum memiliki ikatan mesin yang dibutuhkan
    # kartu native. Status aktif tetap terlihat tanpa mengarang kemajuan.
    ada={r['kode'] for r in progres}
    for r in d['proses']:
        if r['status']=='proses' and r['kode'] not in ada:
            progres.append(dict(kode=r['kode'],judul=NAMA_PROSES.get(r['jenis'],r['jenis']),
                href=portal_url(r['href']),mulai=None,status='Sedang berjalan',catatan=None,
                maju=None,fakta=[],neraca=[],ringkas='Rincian kemajuan belum tersedia.',rendemen=None))
    riwayat=sorted((r for r in d['proses'] if r['status']=='selesai'
        or (r['jenis']=='transfer' and r['status']=='terkirim')),
        key=lambda r:r['selesai'].timestamp() if r.get('selesai') else 0,reverse=True)
    jenis=request.query_params.get('jenis','')
    if jenis not in NAMA_PROSES:jenis=''
    if jenis:riwayat=[r for r in riwayat if r['jenis']==jenis]
    judul_halaman={'beranda':'Beranda','jasa':'Proses Berjalan','barang':'Barang Saya',
        'riwayat':'Riwayat proses','masuk':'Barang masuk','pengambilan':'Pengambilan barang'}
    return render_customer(request,f'portal/{bagian}.html',d=d,bahan=bahan,hasil=hasil,
        transit=transit,progres=progres,utama=status_utama(d,transit),komoditas=komoditas,
        nama_proses=NAMA_PROSES,status_pelanggan=bahasa_status,status_penerimaan=status_penerimaan,kg=jasa_pelanggan.kg_rinci,
        riwayat=riwayat,jenis_riwayat=jenis,daftar_masuk=daftar_masuk,page_title=judul_halaman[bagian])
