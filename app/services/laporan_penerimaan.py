"""Bahan laporan dari catatan penerimaan/tiket/QC; tanpa pembaca saldo baru."""
from sqlalchemy import select
from fastapi import HTTPException
from app.database import now_local
from app.models import Jasa, Pelanggan, Supplier, User, PurchaseBatch, PkPurchaseBatch
from app.services import barang_masuk as masuk


async def baca(db, tiket, jenis, catatan, *, pembuat, scope=None):
    if scope:
        # Seperti dokumen serah terima: dokumen satu tiket tidak boleh
        # dipotong menjadi sebagian pelanggan lalu mengaku seluruh perjalanan.
        semua=await masuk.riwayat(db,g1=True,g2=True,tid=tiket['id'])
        if (tiket['id'] not in scope.resources['timbangan_transaksi'] or
            any(c['jasa_id'] not in scope.jasa_ids for r in semua for c in r['catatan'])):
            raise HTTPException(404,'Penerimaan tidak ditemukan.')
    catatan=[dict(c) for c in catatan]
    people={u.id:u.nama for u in (await db.scalars(select(User).where(
        User.id.in_({c['petugas_id'] for c in catatan})))).all()}
    pesanan={r.id:(r.kode,nama,r.pelanggan_id) for r,nama in (await db.execute(
        select(Jasa,Pelanggan.nama_pelanggan).join(Pelanggan,Pelanggan.id==Jasa.pelanggan_id)
        .where(Jasa.id.in_({c['jasa_id'] for c in catatan if c['jasa_id'] is not None})))).all()}
    pemasok={}
    for model,label in ((PurchaseBatch,'gabah'),(PkPurchaseBatch,'pk')):
        ids={c['id'] for c in catatan if c['model']==label and c['jasa_id'] is None}
        if ids:
            for bid,sid,nama in (await db.execute(select(model.id,Supplier.id,Supplier.nama_supplier)
                .outerjoin(Supplier,Supplier.id==model.supplier_id).where(model.id.in_(ids)))).all():
                pemasok[label,bid]=(sid,nama)
    from app.models import PkRejection, PkPurchaseVerification
    pk_ids={c['id'] for c in catatan if c['model']=='pk'}
    alasan=dict((await db.execute(select(PkPurchaseVerification.pk_purchase_batch_id,
        PkPurchaseVerification.alasan_tolak).where(PkPurchaseVerification.pk_purchase_batch_id.in_(pk_ids)))).all()) if pk_ids else {}
    if pk_ids:
        alasan.update(dict((await db.execute(select(PkRejection.pk_purchase_batch_id,PkRejection.alasan)
            .where(PkRejection.pk_purchase_batch_id.in_(pk_ids)))).all()))
    for c in catatan:
        c['pencatat']=people.get(c['petugas_id']) or 'Tidak tercatat'
        c['alasan_penolakan']=alasan.get(c['id']) if c['model']=='pk' and c['status']=='ditolak' else None
        if c['jasa_id'] is not None:
            order=pesanan.get(c['jasa_id'])
            c['pihak']=order[1] if order else 'Pemilik belum tercatat'
            c['identitas_pihak']=('pelanggan',order[2] if order else c['jasa_id'])
            c['pesanan']=order[0] if order else None
        else:
            sid,nama=pemasok.get((c['model'],c['id']),(tiket.get('supplier_id'),tiket.get('nama_supplier') or tiket.get('pihak_nama')))
            c['pihak']=nama or 'Supplier belum tercatat'
            c['identitas_pihak']=('supplier',sid)
            c['pesanan']=None
    pihak={c['identitas_pihak']:c['pihak'] for c in catatan}
    if not pihak:
        pihak={('pelanggan' if tiket.get('jasa') else 'supplier',None):
            tiket.get('nama_pelanggan') or tiket.get('nama_supplier') or tiket.get('pihak_nama') or 'Belum tercatat'}
    berat,ket=masuk.bobot_diterima(catatan)
    timbang=await masuk.rincian_timbang(db,tiket['id'])
    diterima=[c for c in catatan if c['status']!='ditolak']
    final=bool(timbang and tiket['status_tiket']=='SELESAI' and timbang['status_transaksi']=='AKTIF'
               and berat is not None and not ket
               and (timbang['berat_barang_kg'] is not None or timbang['netto_timbangan_kg'] is not None))
    return dict(tiket=tiket,jenis=jenis,catatan=catatan,pihak=pihak,
        label_pihak='Pemilik barang' if all(k[0]=='pelanggan' for k in pihak) else 'Supplier' if all(k[0]=='supplier' for k in pihak) else 'Pihak penerimaan',
        pesanan=list(dict.fromkeys(c['pesanan'] for c in catatan if c['pesanan'])),
        berat=berat,keterangan_berat=ket if catatan else 'Belum diterima',timbang=timbang,final=final,
        status='Diterima' if diterima else 'Ditolak' if catatan else 'Belum diterima',
        qc=await masuk.hasil_qc(db,catatan),pembuat=pembuat,dibuat=now_local())
