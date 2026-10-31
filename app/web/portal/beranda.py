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
STATUS = {'proses':'Sedang diproses', 'selesai':'Selesai dicatat',
          'berjalan':'Masih berlangsung', 'dibatalkan':'Dibatalkan',
          'digabung':'Digabung ke jasa lain', 'pending':'Menunggu petugas',
          'baru':'Menunggu petugas', 'dimuat':'Sudah dimuat',
          'menunggu_timbang':'Menunggu penimbangan', 'terverifikasi':'Sudah diverifikasi'}


def bahasa_status(nilai):
    return STATUS.get(nilai, (nilai or 'Belum tersedia').replace('_',' ').capitalize())


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
        return dict(label='Sedang diproses',judul='Barang Anda sedang diproses.',
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
                    isi='Periksa perjalanan jasa untuk melihat proses dan pengeluaran yang sudah dicatat.',jenis='riwayat')
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
            fakta=[(k,v) for k,v in r.fakta if k!='Mode'],neraca=neraca,
            ringkas=r.ringkas,rendemen=r.rendemen_sementara))
    return hasil


async def halaman(request, bagian='beranda'):
    from app.models import OutgoingRecord,CustomerReturn,DryingLot
    from sqlalchemy import select
    from app.services import jasa_pelanggan,berjalan
    from app.services.kelompok_kerja import bagi
    from app.web.layar_jasa import _tambah_tiket
    from .routes import notice_rows
    scope=request.state.portal_scope
    async with SessionLocal() as db:
        d=await jasa_pelanggan.pelanggan(db,scope.reader.pelanggan_id,
            rinci=bagian!='beranda',read_scope=scope)
        d=deepcopy(d) if d else dict(id=scope.reader.pelanggan_id,
            pesanan=[],penerimaan=[],proses=[],stok=[],pengiriman=[],retur=[])
        b=await berjalan.untuk(db,scope.reader,read_scope=scope)
        _tambah_tiket(d,bagi(b).masuk)
        kabar=await notice_rows(db,scope)
        # Status "selesai" pada pengeringan hanya menutup fase kering.
        # Pendinginan masih berjalan sampai waktunya benar-benar dicatat.
        pendinginan={r.kode_lot for r in (await db.scalars(select(DryingLot).where(
            DryingLot.id.in_(scope.ids(DryingLot)),DryingLot.status=='selesai',
            DryingLot.waktu_selesai_pendinginan.is_(None)))).all()}
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
    judul_halaman={'beranda':'Beranda','jasa':'Jasa Saya','barang':'Barang Saya'}
    return render_customer(request,f'portal/{bagian}.html',d=d,bahan=bahan,hasil=hasil,
        transit=transit,progres=progres,utama=status_utama(d,transit),kabar_terbaru=kabar[:3],
        nama_proses=NAMA_PROSES,status_pelanggan=bahasa_status,kg=jasa_pelanggan.kg_rinci,
        page_title=judul_halaman[bagian])
