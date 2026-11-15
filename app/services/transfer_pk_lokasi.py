"""Permintaan PK dari sumber nyata ke gudang lain dalam satu perusahaan.

Memakai PermintaanPk dan seluruh penulis/koreksi PK yang sudah ada. Hasil
giling tetap berada pada proses asal; hanya PK yang benar-benar dipindahkan.
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from app.models import PermintaanPk
from app.database import now_local
from app.services import transfer_barang_sumber as stok
from app.services.kepemilikan import fingerprint
from app.services.transfer_lokasi import tujuan_sah
from app.peran import can_see_financials


async def minta(db,*,user,id,tujuan_id,jumlah,kunci,commit=True,kabari=True):
    from app.services.pengiriman_pk import kunci_stok
    await kunci_stok(db)
    n=stok.angka(jumlah)
    key=f'transfer-pk:{user.id}:{kunci}'
    signature=fingerprint(dict(sumber_id=str(id),tujuan_id=tujuan_id,jumlah=str(n)))
    old=await db.scalar(select(PermintaanPk).where(PermintaanPk.kunci_transfer==key))
    if old:
        if old.sidik_transfer!=signature:raise stok.TransferBarangError('Kunci permintaan sudah dipakai untuk isian berbeda.')
        return dict(ok=True,id=old.id,ulang=True)
    source=await stok.sumber(db,user=user,jenis='pk_giling',id=id,kunci=True)
    await tujuan_sah(db,source['asal_id'],tujuan_id)
    if not can_see_financials(user) and user.default_warehouse_id not in (source['asal_id'],tujuan_id):
        raise PermissionError('Permintaan harus melibatkan gudang kerja Anda.')
    if n>source['tersedia']:raise stok.TransferBarangError('Jumlah melebihi stok bebas PK sumber.')
    r=PermintaanPk(milling_process_id=source['row'].id,jasa_id=source['pemilik_id'],
        tujuan_warehouse_id=tujuan_id,diminta_oleh=user.id,waktu_minta=now_local(),
        status='diminta',bertahap=True,berat_minta_kg=n,kunci_transfer=key,sidik_transfer=signature)
    db.add(r)
    try:await db.flush()
    except IntegrityError:
        # Komposisi perintah memakai savepoint milik pemanggil: rollback
        # seluruh sesi di sini akan memutus transaksi induknya.
        if commit:await db.rollback()
        raise stok.TransferBarangError('Lot ini sudah mempunyai permintaan aktif. Lanjutkan permintaan yang ada.') from None
    from app.services.permintaan_pk import _jejak,_kabar
    await _jejak(db,r,langkah='minta',oleh=user,ringkas=f"Meminta {n} kg PK dari {source['kode']}; pemilik tetap {source['pemilik']}.")
    if kabari:
        await _kabar(db,r,untuk='admin',pesan=f"Permintaan transfer PK {source['kode']} · {n} kg. Periksa asal dan tujuan di halaman Transfer.")
    if commit:await db.commit()
    else:await db.flush()
    return dict(ok=True,id=r.id,ulang=False)


async def rancang_dokumen_lanjutan(db,chain):
    """Ikuti koreksi bobot hulu pada perpindahan utuh intake yang sama.

    Barang tidak dipindahkan lagi. Ini memperbarui fakta jumlah dokumen
    lokasi yang telah membawa seluruh lot, termasuk beberapa pabrik beruntun.
    """
    import copy
    from decimal import Decimal as D
    from app.models import TransferBarangItem as I,TransferBarang as T,PermintaanTransferBarang as R
    from app.services.peristiwa import bersih
    from app.services.kepemilikan import raw
    result=[]
    for intake in chain.get('intakes',[]):
        before=D(str(intake['before']['berat_kg']))
        after=D(0) if intake['after'].get('dibatalkan_pada') else D(str(intake['after']['berat_kg']))
        if before==after:continue
        rows=(await db.execute(select(I,R,T).join(R,R.id==I.permintaan_id).join(T,T.id==I.transfer_id)
            .where(T.status=='selesai',I.jumlah>0,I.dampak['jenis'].as_string()=='pk_tumpukan',
                   I.dampak['tujuan_id'].as_integer()==intake['id']))).all()
        for item,request,transfer in rows:
            if not item.dampak.get('utuh') or D(item.jumlah)!=before:
                raise stok.TransferBarangError('Jejak transfer lokasi PK lanjutan tidak sama dengan bobot hulu. Periksa catatan lanjutan sebelum mengoreksi sumber.')
            changes=copy.deepcopy(item.dampak);changes.update(jumlah=str(after),berat_kg=str(after))
            result.append(dict(id=item.id,permintaan_id=request.id,transfer_id=transfer.id,
                kode='TRF-'+transfer.waktu.strftime('%Y%m%d')+'-'+str(transfer.id).zfill(4),
                before=bersih(raw(item)),request_before=bersih(raw(request)),
                after=dict(jumlah=str(after),berat_kg=str(after),dampak=changes),
                request_after=dict(jumlah_setuju=str(max(D(request.jumlah_setuju),after)),
                    ditutup=True,status='selesai' if after else 'gugur',
                    alasan='Sisa ditutup mengikuti koreksi bobot sumber PK; tidak ada pemindahan fisik baru.')))
    return result


async def terapkan_dokumen_lanjutan(db,entries,user,event):
    from decimal import Decimal as D
    from sqlalchemy import func
    from app.models import TransferBarangItem as I,TransferBarang as T,PermintaanTransferBarang as R
    from app.services.kepemilikan import raw
    from app.services.peristiwa import bersih
    from app.services.activity_log import log_activity
    for e in entries:
        item=await db.get(I,e['id'],populate_existing=True,with_for_update=True)
        request=await db.get(R,e['permintaan_id'],populate_existing=True,with_for_update=True)
        if bersih(raw(item))!=e['before'] or bersih(raw(request))!=e['request_before']:
            raise stok.TransferBarangError('Transfer lokasi terkait berubah sejak pemeriksaan. Periksa dampak terbaru.')
        item.jumlah=D(e['after']['jumlah']);item.berat_kg=D(e['after']['berat_kg']);item.dampak=e['after']['dampak']
        request.jumlah_setuju=D(e['request_after']['jumlah_setuju'])
        request.ditutup=True;request.status=e['request_after']['status'];request.alasan=e['request_after']['alasan']
        await log_activity(db,table_name='transfer_barang_items',record_id=item.id,action='UPDATE',changed_by=user.id,
            old_value=str(e['before']['jumlah']),new_value=str(item.jumlah),alasan=event.muatan['isian']['alasan'],aksi='koreksi_transfer_pk_lokasi')
    await db.flush()
    for ident in {e['transfer_id'] for e in entries}:
        transfer=await db.get(T,ident,with_for_update=True)
        total=await db.scalar(select(func.coalesce(func.sum(I.jumlah),0)).where(I.transfer_id==ident))
        transfer.status='selesai' if total>0 else 'dibatalkan'
