"""Metadata baca detail transfer. Saldo, izin aksi dan transaksi tetap layanan lama."""
from math import ceil

from sqlalchemy import select, func, or_

from app.models import (ActivityLog, InternalTransfer, MillingProcess, PermintaanPk,
                        User)
from app.models.peristiwa import Peristiwa
from app.services import transfer
from app.services.bahan_silo import kg_rinci
from app.services.proses_aktif import _waktu

STATUS = {'diminta':'Diminta', 'disetujui':'Disetujui', 'dikirim':'Dikirim',
          'selesai':'Selesai', 'ditolak':'Ditolak', 'gugur':'Gugur'}
AKSI = {'diminta':['acc_permintaan_pk','tolak_permintaan_pk'],
        'disetujui':['kirim_permintaan_pk'], 'dikirim':['tutup_permintaan_pk']}


def bobot(n):
    return kg_rinci(n) if n is not None else 'Belum tercatat'


async def rincian(db, *, catatan=None, permintaan=None, params=None):
    from app.penggilingan.gudang1.services.milling import pk_jenis
    from app.penggilingan.gudang2.service import label_tujuan
    from app.services.jasa import nama_pemilik_banyak
    from app.services.retur_penerimaan import berat_kembali
    params = params or {}
    proc = await db.get(MillingProcess, catatan.milling_process_id if catatan else permintaan.milling_process_id)
    if permintaan is None and catatan:
        permintaan = await db.scalar(select(PermintaanPk).where(
            PermintaanPk.internal_transfer_id == catatan.id).order_by(PermintaanPk.id.desc()))
    jasa = catatan.jasa_id if catatan else proc.jasa_id
    pemilik = (await nama_pemilik_banyak(db, [jasa])).get(jasa, f'Pesanan #{jasa}') if jasa else 'Milik pabrik'
    orang = {u.id:u.nama for u in (await db.scalars(select(User).where(User.id.in_({x for x in
        ([catatan.created_by] if catatan else []) + ([permintaan.diminta_oleh,permintaan.disetujui_oleh,
        permintaan.dikirim_oleh,permintaan.ditutup_oleh] if permintaan else []) if x is not None})))).all()}
    tujuan = await label_tujuan(db, catatan.lokasi_tujuan if catatan else permintaan.tujuan,
                              catatan.silo_id if catatan else permintaan.silo_id) if catatan or permintaan.tujuan else 'Belum ditetapkan'
    aktif = await transfer._transferred_pk(db, proc.id)
    saldo = await transfer.pending_transfer_kg(db, proc.id)
    kode = catatan.kode_transfer if catatan else f'Permintaan PK #{permintaan.id}'
    status_catatan = 'Dibatalkan' if catatan and catatan.status=='dibatalkan' else 'Terkirim' if catatan else 'Belum terbentuk'
    berat = [(label,bobot(getattr(permintaan,field)) if permintaan else 'Tidak ada permintaan') for label,field in
             [('Diminta G2','berat_minta_kg'),('Disetujui Admin','berat_setuju_kg'),
              ('Dimuat G1','berat_kirim_kg'),('Final Admin','berat_final_kg')]]
    langkah = []
    if permintaan:
        for label,waktu,oleh in [('Diminta Gudang 2','waktu_minta','diminta_oleh'),
                                 ('Disetujui Admin','waktu_setuju','disetujui_oleh'),
                                 ('Dikirim Gudang 1','waktu_kirim','dikirim_oleh'),
                                 ('Ditutup / keputusan akhir','waktu_tutup','ditutup_oleh')]:
            if getattr(permintaan,waktu):
                langkah.append(dict(judul=label,waktu=_waktu(getattr(permintaan,waktu)),
                                    oleh=orang.get(getattr(permintaan,oleh),'Pencatat belum tercatat')))
    count = await db.scalar(select(func.count()).select_from(InternalTransfer).where(InternalTransfer.milling_process_id==proc.id))
    pages=max(1,ceil(count/20))
    try: page=min(pages,max(1,int(params.get('halaman_transfer','1'))))
    except (ValueError,TypeError): page=1
    terkait=[]
    for row in (await db.scalars(select(InternalTransfer).where(InternalTransfer.milling_process_id==proc.id)
                .order_by(InternalTransfer.id.desc()).offset((page-1)*20).limit(20))).all():
        terkait.append(dict(id=row.id,kode=row.kode_transfer,berat=bobot(row.berat_kg),status=row.status,
                            waktu=_waktu(row.waktu),tujuan=await label_tujuan(db,row.lokasi_tujuan,row.silo_id)))
    q=[]
    if catatan:q.append((ActivityLog.table_name=='internal_transfers') & (ActivityLog.record_id==catatan.id))
    if permintaan:q.append((ActivityLog.table_name=='permintaan_pk') & (ActivityLog.record_id==permintaan.id))
    logs=(await db.execute(select(ActivityLog,User.nama).outerjoin(User,User.id==ActivityLog.changed_by)
          .where(or_(*q)).order_by(ActivityLog.waktu_perubahan.desc(),ActivityLog.id.desc()))).all() if q else []
    audit=[dict(aksi=l.aksi or l.action,waktu=_waktu(l.waktu_perubahan),oleh=n or 'Sistem / belum tercatat',
                alasan=l.alasan_perubahan,ringkas=l.new_value if l.table_name=='permintaan_pk' else None) for l,n in logs]
    pembatalan=None
    if catatan and catatan.peristiwa_id:
        e=await db.scalar(select(Peristiwa).where(Peristiwa.membatalkan_id==catatan.peristiwa_id))
        if e:
            pembatalan=dict(waktu=_waktu(e.waktu),alasan=(e.muatan or {}).get('alasan') or 'Alasan belum tercatat',
                            oleh=await db.scalar(select(User.nama).where(User.id==e.pelaku_id)) if e.pelaku_id else 'Sistem / belum tercatat')
    selisih=None
    if permintaan and permintaan.berat_final_kg is not None and permintaan.berat_kirim_kg is not None:
        nilai=permintaan.berat_final_kg-permintaan.berat_kirim_kg
        selisih=('+' if nilai>0 else '−' if nilai<0 else '')+bobot(abs(nilai))
    tahap=3 if permintaan and permintaan.status=='selesai' else 2 if permintaan and permintaan.waktu_kirim else 1 if permintaan and permintaan.waktu_setuju else 0
    return dict(kode=kode,catatan=catatan,permintaan=permintaan,proses=proc,pemilik=pemilik,jasa=jasa,
        status_catatan=status_catatan,status_permintaan=STATUS.get(permintaan.status,permintaan.status) if permintaan else 'Tanpa permintaan',
        tujuan=tujuan,jenis_pk=await pk_jenis(db,proc),berat=berat,selisih=selisih,tahap=tahap,
        statistik=[('Berat transfer ini',bobot(catatan.berat_kg) if catatan else 'Belum ada transfer'),
                   ('Sisa PK lot di G1',bobot(saldo)),('Status catatan',status_catatan)],
        saldo=bobot(saldo),aktif=bobot(aktif),komponen=[('Hasil PK lot',bobot(await transfer._produced_pk(db,proc.id))),
            ('Retur PK langsung',bobot(await berat_kembali(db,tipe='pk_langsung',proses_id=proc.id))),
            ('Transfer aktif seluruh lot',bobot(aktif)),('Barang keluar langsung',bobot(await transfer._sold_pk_langsung(db,proc.id))),
            ('PK tersisa di Gudang 1',bobot(saldo))],
        sumber_href=f'/riwayat-giling/{proc.id}' if proc.status=='selesai' else f'/proses-aktif/giling/{proc.kode_proses}',
        pencatat=orang.get(catatan.created_by,'Pencatat belum tercatat') if catatan else 'Belum tercatat',
        peminta=orang.get(permintaan.diminta_oleh,'Pencatat belum tercatat') if permintaan else None,
        langkah=langkah,audit=audit,pembatalan=pembatalan,terkait=terkait,
        halaman=page,halaman_total=pages,jumlah=count)
