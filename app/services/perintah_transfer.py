"""Perintah Admin menggabungkan permintaan dan persetujuan yang sudah sah.

Keduanya tetap memakai penjaga, audit dan notifikasi penulis lama. Satu
transaksi hanya menghasilkan dokumen disetujui; stok baru bergerak ketika
operator asal mencatat pelaksanaannya melalui penulis transfer lama.
"""
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from sqlalchemy import select
from app.models import PermintaanTransferBarang, PermintaanPk
from app.services import transfer_barang as barang, transfer_barang_sumber as stok
from app.services.kepemilikan import fingerprint

AWALAN_KUNCI = 'transfer-perintah:'


def jenis_dokumen(kunci):
    """Bukti asal dokumen tanpa menebak dari kesamaan peminta/penyetuju."""
    return 'perintah' if (kunci or '').startswith(AWALAN_KUNCI) else 'permintaan'


@asynccontextmanager
async def _transaksi_perintah(db):
    from app.penggilingan.gudang2.service import Gudang2Error
    from app.services.transfer import TransferError
    from app.services.kepemilikan import InventoryError
    try:
        async with db.begin_nested():
            yield
    except (Gudang2Error,TransferError,InventoryError) as e:
        # Penulis lama mempunyai keluarga galat berbeda. Setelah savepoint
        # dibatalkan, seluruh penolakan domain memakai kontrak HTTP transfer
        # barang yang sama; izin tetap PermissionError agar menjadi 403.
        raise stok.TransferBarangError(str(e)) from None


async def buat(db, *, user, jenis, sumber_id, jumlah, asal_id, tujuan_id,
               kunci, tujuan=None):
    await stok.izin(user)
    barang.admin(user)
    await barang.kunci(db)
    n=stok.angka(jumlah,bulat=jenis in stok.INTEGER)
    pilihan=tujuan if tujuan is not None else 'gudang:'+str(tujuan_id)
    if not any(pilihan.startswith(a) and pilihan[len(a):].isdigit()
               and 0<int(pilihan[len(a):])<=2147483647 for a in ('gudang:','silo:')):
        raise stok.TransferBarangError('Pilih lokasi tujuan dari daftar transfer.')
    if jenis!='pk_giling' and pilihan!='gudang:'+str(tujuan_id):
        raise stok.TransferBarangError('Barang ini hanya dapat ditransfer ke area stok gudang tujuan.')
    body=dict(jenis=jenis,sumber_id=str(sumber_id),jumlah=format(n.normalize(),'f'),
              asal_id=asal_id,tujuan_id=tujuan_id,tujuan=pilihan)
    key=AWALAN_KUNCI+str(user.id)+':'+kunci
    signature=fingerprint(body)
    # Satu nonce mencakup kedua jenis dokumen. Mengganti tipe atau asal
    # tidak boleh lolos hanya karena penyimpanan PK memakai tabel lain.
    for model,kolom,sidik,arah in ((PermintaanTransferBarang,PermintaanTransferBarang.kunci,'sidik',-1),
                                  (PermintaanPk,PermintaanPk.kunci_transfer,'sidik_transfer',1)):
        old=await db.scalar(select(model).where(kolom==key))
        if old:
            if getattr(old,sidik)!=signature:
                raise stok.TransferBarangError('Kunci perintah sudah dipakai untuk isian berbeda.')
            return dict(ok=True,id=arah*old.id,ulang=True,jenis_dokumen='perintah')
    # Savepoint membuang permintaan, persetujuan dan audit sekaligus bila
    # satu penjaga menolak, termasuk bila pemanggil menangkap galat lalu
    # tetap melanjutkan/commit sesi yang sama.
    async with _transaksi_perintah(db):
        source=await stok.sumber(db,user=user,jenis=jenis,id=sumber_id,kunci=True)
        if source['asal_id']!=asal_id:
            raise stok.TransferBarangError('Gudang asal tidak cocok dengan sumber stok. Pilih kembali sumbernya.')
        await barang.tujuan(db,source['asal_id'],tujuan_id)
        if jenis=='pk_giling':
            from app.services import pengiriman_pk as pk
            rute=SimpleNamespace(milling_process_id=source['row'].id,tujuan_warehouse_id=tujuan_id)
            _,_,wid=await pk.pilihan_tujuan(db,rute,pilihan)
            if wid!=tujuan_id:
                raise stok.TransferBarangError('Lokasi tujuan tidak berada di gudang tujuan yang dipilih.')
        # Namespace sementara tidak bertabrakan dengan nonce /permintaan.
        # Sebelum commit, kunci/sidik diganti bukti perintah lengkap di atas.
        result=await barang.minta(db,user=user,jenis=jenis,id=sumber_id,tujuan_id=tujuan_id,
                                  jumlah=n,kunci_kiriman='perintah:'+kunci,commit=False,kabari=False)
        if jenis=='pk_giling':
            r=await db.get(PermintaanPk,result['id'])
            r.kunci_transfer=key;r.sidik_transfer=signature
            await pk.setujui_banyak(db,user=user,items=[dict(permintaan_id=r.id,berat_kg=str(n),tujuan=pilihan)],commit=False)
            table='permintaan_pk'
        else:
            r=await db.get(PermintaanTransferBarang,-result['id'])
            r.kunci=key;r.sidik=signature
            await barang.setujui_banyak(db,user=user,items=[dict(permintaan_id=r.id,berat_kg=str(n),tujuan=pilihan)],commit=False)
            table='permintaan_transfer_barang'
            # Persetujuan barang umum lama tidak mengirim kabar operator.
            # Notifikasi belum mempunyai cakupan gudang untuk tabel ini;
            # perintah dibaca melalui daftar transfer yang sudah bercakupan.
        from app.services.activity_log import log_activity
        await log_activity(db,table_name=table,record_id=r.id,action='UPDATE',changed_by=user.id,
                           aksi='transfer_perintah',field_name='jenis_dokumen',
                           new_value=json.dumps(dict(jenis_dokumen='perintah',**body,
                               company_id=source['company_id'],pemilik_kunci=source['pemilik_kunci']),ensure_ascii=False))
        await db.flush()
    await db.commit()
    return dict(ok=True,id=result['id'],ulang=False,jenis_dokumen='perintah')
