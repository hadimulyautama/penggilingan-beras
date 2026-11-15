"""Gabungkan catatan lama tanpa menyalin transaksi atau menghitung lot dua kali."""
from sqlalchemy import select

from app.models import InternalTransfer, MillingProcess, PengirimanPkItem, Silo, Warehouse, Jasa, Pelanggan
from app.peran import can_see_financials
from app.services.cakupan_fasilitas import lokasi
from app.services.jasa import nama_pemilik_banyak


async def nama_pelanggan(db, ids):
    return dict((await db.execute(select(Jasa.id, Pelanggan.nama_pelanggan)
        .join(Pelanggan, Pelanggan.id == Jasa.pelanggan_id).where(Jasa.id.in_(ids)))).all())


async def lengkapi_pengiriman(db, journeys):
    """Metadata daftar per lot dibaca borongan; tidak membuat transaksi baru."""
    items = [i for j in journeys for i in j['items']]
    transfers = {t.id:t for t in (await db.scalars(select(InternalTransfer).where(
        InternalTransfer.id.in_({i['transfer_id'] for i in items if i.get('transfer_id')})))).all()}
    owners = await nama_pelanggan(db, {i['jasa_id'] for i in items if i.get('jasa_id')})
    for i in items:
        t = transfers.get(i.get('transfer_id'))
        i.update(nomor=t.kode_transfer if t else None,
                 waktu=t.waktu.isoformat() if t else None,
                 jasa=i.get('jasa_id') is not None,
                 nama_pemilik=owners.get(i.get('jasa_id'), 'Pabrik'))


async def catatan_lama(db, *, user, batas=100):
    # Satu pencatatan baru dapat memuat beberapa InternalTransfer. Hanya lot
    # yang TIDAK memiliki kelompok baru ditampilkan sebagai catatan mandiri.
    asal = lokasi(MillingProcess)
    tujuan = lokasi(InternalTransfer)
    q = (select(InternalTransfer, MillingProcess.kode_proses, asal, tujuan)
         .join(MillingProcess, MillingProcess.id == InternalTransfer.milling_process_id)
         .where(~select(PengirimanPkItem.id).where(
             PengirimanPkItem.internal_transfer_id == InternalTransfer.id).exists())
         .order_by(InternalTransfer.waktu.desc(), InternalTransfer.id.desc()).limit(batas))
    if not can_see_financials(user):
        wid = user.default_warehouse_id
        # Hak baca asal/tujuan mengikuti halaman Transfer. Barang pelanggan
        # dari gudang lain tidak dibuka kepada operator tujuan.
        q = q.where((asal == wid) | ((tujuan == wid) & InternalTransfer.jasa_id.is_(None)))
    rows = (await db.execute(q)).all()
    gudang = dict((await db.execute(select(Warehouse.id, Warehouse.nama_gudang))).all())
    silos = dict((await db.execute(select(Silo.id, Silo.nama_silo).where(
        Silo.id.in_({t.silo_id for t, *_ in rows if t.silo_id})))).all())
    owners = await nama_pemilik_banyak(db, {t.jasa_id for t, *_ in rows if t.jasa_id})
    names = await nama_pelanggan(db, {t.jasa_id for t, *_ in rows if t.jasa_id})
    result = []
    for t, lot, a, b in rows:
        weight = str(t.berat_kg)
        nama_tujuan = silos.get(t.silo_id, 'Silo tidak tersedia') if t.silo_id else 'Tumpukan'
        result.append(dict(
            id='lama:' + str(t.id), nomor=t.kode_transfer, lama=True,
            detail_url='/riwayat-transfer/' + str(t.id),
            waktu=t.waktu.isoformat(), status='selesai' if t.status == 'terkirim' else 'dibatalkan',
            total=weight, total_efektif=weight if t.status == 'terkirim' else '0',
            pakai_kendaraan=False, items=[dict(lot=lot, berat_kg=weight, nomor=t.kode_transfer,
                jasa=t.jasa_id is not None, nama_pemilik=names.get(t.jasa_id, 'Pabrik'),
                pemilik=owners.get(t.jasa_id, 'Milik pabrik'))],
            lintasan=dict(asal=dict(gudang_id=a, nama=gudang.get(a, 'Gudang asal')),
                tujuan=dict(gudang_id=b, silo_id=t.silo_id,
                    nama=nama_tujuan + ' · ' + gudang.get(b, 'Gudang tujuan')))))
    return result
