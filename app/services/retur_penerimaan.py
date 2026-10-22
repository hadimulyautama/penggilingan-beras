"""Penerimaan retur tepat sekali di transaksi pengajuan yang sudah dikunci."""
from decimal import Decimal
from uuid import uuid4

from sqlalchemy import func, select

from app.database import now_local
from app.models import (ByproductStock, CustomerReturn, CustomerReturnItem,
                        FinishedGoodsStock, OutgoingItem, User, Warehouse)
from app.penggilingan.inventory.models import ReturPemeriksaanLog, ReturRincian
from app.services import retur_pengajuan as pengajuan


async def berat_kembali(db, *, tipe, proses_id=None, lot_id=None):
    """Suku masuk terpisah untuk saldo bahan; angka keluar historis tetap utuh."""
    q = (select(func.coalesce(func.sum(CustomerReturnItem.berat_total_kg), 0))
         .join(OutgoingItem, OutgoingItem.id == CustomerReturnItem.outgoing_item_id)
         .where(OutgoingItem.item_type == tipe))
    if proses_id is not None:
        q = q.where(OutgoingItem.milling_process_id == proses_id)
    if lot_id is not None:
        q = q.where(OutgoingItem.gabah_kering_lot_id == lot_id)
    return float(await db.scalar(q))


async def _koreksi_terbukti(db, rincian):
    logs = (await db.scalars(select(ReturPemeriksaanLog).where(
        ReturPemeriksaanLog.retur_rincian_id == rincian.id).order_by(
        ReturPemeriksaanLog.id))).all()
    tertahan = None
    for log in logs:
        if log.sesudah.get('hasil', {}).get('status') == 'perlu_koreksi':
            tertahan = log.sesudah
    if tertahan is None:
        return False
    sekarang = pengajuan.cuplikan(rincian)
    if tertahan['tiket_id'] != sekarang['tiket_id']:
        return True
    if tertahan['muatan'] != sekarang['muatan']:
        return True
    kunci = ('timbang1_kg', 'timbang2_kg', 'berat_tiket_kg')
    berubah = any(tertahan['hasil'].get(k) != sekarang['hasil'].get(k) for k in kunci)
    koreksi = sekarang['hasil'].get('koreksi_timbang')
    return bool(berubah and koreksi and koreksi != tertahan['hasil'].get('koreksi_timbang'))


async def periksa_dan_terima(db, identitas, *, manual=False, pelaku=None):
    """Tidak commit. Kunci tetap dipegang sampai stok dan audit tersimpan.

    Pekerja sistem hanya membaca pengajuan yang sebelumnya sudah dibuat sah.
    Penerimaan manual tetap memakai izin lama, termasuk bila endpoint dipanggil
    langsung. Memuat ulang halaman tidak memanggil fungsi ini.
    """
    awal = await db.get(ReturRincian, identitas)
    if not awal or not awal.outgoing_record_id:
        raise ValueError('Pengajuan retur beridentitas asal tidak ditemukan.')
    asal = await pengajuan.kunci_asal(db, awal.outgoing_record_id)
    rincian = await db.scalar(select(ReturRincian).where(
        ReturRincian.id == identitas).with_for_update().execution_options(populate_existing=True))
    if rincian.customer_return_id:
        return await db.get(CustomerReturn, rincian.customer_return_id)
    if rincian.status_pemeriksaan == 'dibatalkan':
        raise ValueError('Pengajuan telah dibatalkan.')
    if manual:
        from app.peran import can_see_financials
        if not pelaku or not can_see_financials(pelaku):
            raise ValueError('Verifikasi manual hanya tersedia bagi pemeriksa berwenang.')
    try:
        tiket = await pengajuan.kunci_tiket(db, rincian.timbangan_transaksi_id, asal.pelanggan_id)
    except ValueError as exc:
        sebelum = pengajuan.cuplikan(rincian)
        rincian.status_pemeriksaan = 'tertahan'
        rincian.hasil_pemeriksaan = dict(status='tertahan', alasan=str(exc))
        sesudah = pengajuan.cuplikan(rincian)
        if sebelum != sesudah:
            db.add(ReturPemeriksaanLog(retur_rincian_id=rincian.id,
                pelaku_id=pelaku.id if pelaku else None, waktu=now_local(),
                aksi='pemeriksaan', sebelum=sebelum, sesudah=sesudah))
        return None
    items, terpakai = await pengajuan.sisa_asal(db, asal.id, kecuali=rincian.id)
    # Validasi ulang terhadap aktual pengiriman, bukan percaya snapshot JSON.
    jumlah = {m['outgoing_item_id']: str(m['jumlah_karung'] if m['item_type'] == 'finished_goods'
                                       else m['berat_kg']) for m in rincian.muatan}
    sebelum = pengajuan.cuplikan(rincian)
    notes = {m['outgoing_item_id']: m.get('catatan_item', '') for m in rincian.muatan}
    kemasan = {m['outgoing_item_id']: m.get('packaging_material_id') for m in rincian.muatan}
    karung = {m['outgoing_item_id']: m['jumlah_karung'] for m in rincian.muatan}
    rincian.muatan = [dict(m, catatan_item=notes.get(m['outgoing_item_id'], ''))
        for m in await pengajuan.susun_muatan(db, items, terpakai, jumlah, kemasan, karung)]
    hasil = await pengajuan.periksa(db, rincian, tiket=tiket,
        pelaku_id=pelaku.id if pelaku else None, sebelum=sebelum)
    await db.flush()
    if hasil.status not in ('sesuai', 'calon_manual'):
        return None
    if hasil.wajib_manual:
        if not manual or not await _koreksi_terbukti(db, rincian):
            return None
    # Pengajuan yang tidak pernah berselisih besar boleh diterima sistem.
    # Pelaku pencatatan tetap akun pengaju; audit membedakan tindakan sistem.
    penerima_id = pelaku.id if manual else rincian.input_by
    penerima = await db.get(User, penerima_id)
    if not penerima:
        raise ValueError('Identitas pengaju tidak tersedia untuk audit penerimaan.')
    from app.services.barang_keluar import GUDANG_ITEM
    lokasi = {GUDANG_ITEM[m['item_type']] for m in rincian.muatan}
    gudang = {w.kode_fungsi: w for w in (await db.scalars(select(Warehouse).where(
        Warehouse.kode_fungsi.in_(lokasi), Warehouse.aktif.is_(True)))).all()}
    if lokasi - gudang.keys():
        raise ValueError('Gudang penerimaan belum tersedia.')
    gudang_header = gudang[next(iter(lokasi))].id if len(lokasi) == 1 else None
    now = now_local()
    receipt = CustomerReturn(kode=f'RET-{uuid4().hex[:16]}', timbangan_transaksi_id=tiket['id'],
        kode_tiket=tiket['kode'], pelanggan_id=tiket['pelanggan_id'],
        nama_pelanggan=tiket['nama_pelanggan'], nomor_polisi=tiket['nomor_polisi'],
        timbang1_kg=tiket['timbang1_kg'], timbang2_kg=tiket['timbang2_kg'],
        berat_tiket_kg=Decimal(str(tiket['berat_barang_kg'])),
        berat_rincian_kg=hasil.berat_rincian_kg, selisih_kg=hasil.selisih_kg,
        catatan=rincian.catatan, warehouse_id=gudang_header, input_by=penerima_id, waktu=now)
    db.add(receipt); await db.flush()
    receipt.kode = f'RET-{now:%Y%m%d}-{receipt.id:04d}'
    per_id = {i.id: i for i in items}
    for m in rincian.muatan:
        asal_item = per_id[m['outgoing_item_id']]
        berat = Decimal(m['berat_kg'])
        item = CustomerReturnItem(customer_return_id=receipt.id,
            outgoing_item_id=asal_item.id, product_sku_id=asal_item.product_sku_id,
            rice_quality_standard_id=asal_item.rice_quality_standard_id,
            jumlah_karung=m['jumlah_karung'], berat_total_kg=berat, jasa_id=asal_item.jasa_id,
            catatan=m.get('catatan_item') or None)
        db.add(item); await db.flush()
        if asal_item.item_type == 'finished_goods':
            stock = FinishedGoodsStock(product_sku_id=asal_item.product_sku_id,
                rice_quality_standard_id=asal_item.rice_quality_standard_id,
                source_type='retur', source_id=receipt.id, jumlah_karung=m['jumlah_karung'],
                berat_total_kg=berat, warehouse_id=gudang['g2'].id, waktu=now,
                input_by=penerima_id, jasa_id=asal_item.jasa_id,
                kemasan_mengurangi_stok=False)
            db.add(stock); await db.flush()
            item.finished_goods_stock_id = stock.id
        elif asal_item.item_type == 'byproduct_curah':
            db.add(ByproductStock(jenis_produk=asal_item.jenis_byproduct,
                source_type='retur', source_id=receipt.id, berat_kg=berat,
                tanggal=now.date(), waktu=now, input_by=penerima_id,
                jasa_id=asal_item.jasa_id))
        elif asal_item.item_type == 'pk_g2':
            from app.penggilingan.gudang2.service import _add_intake
            await _add_intake(db, user=penerima, sumber_tipe='retur', tujuan='ditumpuk',
                berat_kg=float(berat), hpp_per_kg=None, tanggal=now.date(), jam=now.time(),
                jasa_id=asal_item.jasa_id, kunci_kiriman=f'retur:item:{item.id}', commit=False)
        # PK G1/gabah dibaca sebagai suku masuk dari CustomerReturnItem oleh
        # pembaca saldo pusat. Tidak mengubah produksi atau keluar historis.
    rincian.customer_return_id = receipt.id
    rincian.status_pemeriksaan = 'diterima_manual' if manual else 'diterima_otomatis'
    db.add(ReturPemeriksaanLog(retur_rincian_id=rincian.id, pelaku_id=pelaku.id if manual else None,
        waktu=now, aksi=rincian.status_pemeriksaan, sebelum=pengajuan.cuplikan(rincian),
        sesudah=dict(receipt_id=receipt.id, kode=receipt.kode)))
    await db.flush()
    return receipt
