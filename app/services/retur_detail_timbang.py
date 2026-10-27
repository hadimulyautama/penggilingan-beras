"""Proyeksi operasional retur untuk Pos Timbang; tidak memeriksa ulang atau menerima stok.

Hasil pemeriksaan merupakan cuplikan layanan retur. Membaca halaman tidak boleh
memanggil `periksa` yang menulis audit maupun pekerja penerimaan. Tara toleransi
diambil dari cuplikan tersebut, bukan tara potongan nol dari kontrak muatan lama.
"""
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, text

from app.models import (CustomerReturn, CustomerReturnItem, OutgoingRecord,
                        OutgoingItem, ProductSku, PackagingMaterial, PackageSize,
                        Brand, RiceQualityStandard, Warehouse)
from app.penggilingan.inventory.models import ReturRincian


def _angka_sama(a, b):
    if a in (None, 'None') or b is None:
        return a in (None, 'None') and b is None
    try:
        return Decimal(str(a)) == Decimal(str(b))
    except InvalidOperation:
        return False


async def baca(db, tid):
    tiket = (await db.execute(text('''SELECT id,kode,arah,pelanggan_id,
        timbang1_kg,timbang2_kg,berat_barang_kg,status_tiket,status_transaksi
        FROM timbangan_transaksi WHERE id=:id'''), {'id': tid})).mappings().first()
    if not tiket or tiket['arah'] != 'RETUR_MASUK':
        raise ValueError('Tiket retur masuk tidak tersedia.')
    rincian = await db.scalar(select(ReturRincian).where(ReturRincian.timbangan_transaksi_id == tid))
    terima = await db.scalar(select(CustomerReturn).where(CustomerReturn.timbangan_transaksi_id == tid))
    asal = await db.get(OutgoingRecord, rincian.outgoing_record_id) if rincian and rincian.outgoing_record_id else None
    if ((asal and asal.pelanggan_id != tiket['pelanggan_id'])
            or (terima and terima.pelanggan_id != tiket['pelanggan_id'])
            or (rincian and rincian.customer_return_id and
                (not terima or rincian.customer_return_id != terima.id))):
        raise ValueError('Hubungan pelanggan dan retur perlu diperiksa di PadiFlow.')
    asal_data = None
    if asal:
        # Kiriman bersama menyimpan tiket pada armada; jangan mengambil tiket
        # pelanggan lain hanya karena nomor polisi atau tanggal kebetulan sama.
        asal_tid = asal.timbangan_transaksi_id
        if asal.kiriman_id:
            from app.models import KirimanKeluar
            kiriman = await db.get(KirimanKeluar, asal.kiriman_id)
            asal_tid = kiriman.timbangan_transaksi_id if kiriman else asal_tid
        kode = await db.scalar(text('SELECT kode FROM timbangan_transaksi WHERE id=:id'), {'id': asal_tid}) if asal_tid else None
        asal_data = dict(id=asal.id, kode=asal.kode, pelanggan_id=asal.pelanggan_id,
                         tiket_id=asal_tid, tiket_kode=kode, kiriman_id=asal.kiriman_id)
    hasil = (rincian.hasil_pemeriksaan or {}) if rincian else {}
    status = rincian.status_pemeriksaan if rincian else None
    if terima:
        status = status if status in ('diterima_manual', 'diterima_otomatis') else 'diterima'
    elif not rincian:
        status = 'belum'
    elif status != 'dibatalkan' and (tiket['status_transaksi'] != 'AKTIF'
            or tiket['status_tiket'] not in ('TERBUKA', 'SELESAI')):
        status = 'tiket_tidak_aktif'
    elif status != 'dibatalkan' and any(
            k in hasil and not _angka_sama(hasil[k], tiket[t])
            for k, t in [('timbang1_kg', 'timbang1_kg'), ('timbang2_kg', 'timbang2_kg'),
                         ('berat_tiket_kg', 'berat_barang_kg')]):
        status = 'berubah'
    muatan = (rincian.muatan or []) if rincian else []
    baris = []
    for m in muatan:
        item = await db.get(OutgoingItem, m.get('outgoing_item_id')) if m.get('outgoing_item_id') else None
        if asal and (not item or item.outgoing_record_id != asal.id):
            raise ValueError('Identitas barang tidak sesuai pengiriman asal.')
        if m.get('outgoing_item_id'):
            sumber = await db.get(OutgoingRecord, item.outgoing_record_id) if item else None
            if not sumber or sumber.pelanggan_id != tiket['pelanggan_id']:
                raise ValueError('Pelanggan item retur tidak sesuai tiket historis.')
        if item and any(m.get(k) != getattr(item, attr) for k, attr in (
                ('sku_id', 'product_sku_id'), ('quality_id', 'rice_quality_standard_id'), ('jasa_id', 'jasa_id'))):
            raise ValueError('Identitas produk atau pemilik retur tidak sesuai item asal.')
        sku = await db.get(ProductSku, m.get('sku_id')) if m.get('sku_id') else None
        material = await db.get(PackagingMaterial, m.get('packaging_material_id')) if m.get('packaging_material_id') else None
        size = await db.get(PackageSize, m.get('package_size_id')) if m.get('package_size_id') else None
        brand = await db.get(Brand, sku.brand_id) if sku and sku.brand_id else None
        mutu = await db.get(RiceQualityStandard, m.get('quality_id')) if m.get('quality_id') else None
        # Hanya daftar field operasional; JSON sumber dapat menyimpan metadata
        # lain yang tidak diperuntukkan bagi aplikasi Timbangan.
        baris.append(dict(outgoing_item_id=m.get('outgoing_item_id'),
            nama=m.get('nama') or (sku.kategori if sku else (item.jenis_byproduct or item.item_type) if item else 'Barang historis'),
            merek=brand.nama if brand else None, mutu=mutu.kode if mutu else None,
            kemasan=material.nama if material else None, ukuran_kg=str(size.ukuran_kg) if size else None,
            jumlah_karung=m.get('jumlah_karung'), berat_kg=m.get('berat_kg'),
            satuan='karung' if (item and item.item_type == 'finished_goods') or sku else 'kg',
            tara_toleransi_kg=m.get('tara_toleransi_kg'), jasa_id=m.get('jasa_id'),
            catatan=m.get('catatan_item'), gudang=None))
    from app.services.jasa import nama_pemilik_banyak
    pemilik = await nama_pemilik_banyak(db, {m['jasa_id'] for m in baris if m['jasa_id']})
    for m in baris:
        m['pemilik'] = pemilik.get(m['jasa_id'], 'Pemilik belum tersedia') if m['jasa_id'] else 'Milik pabrik'
    if terima:
        items = (await db.scalars(select(CustomerReturnItem).where(CustomerReturnItem.customer_return_id == terima.id))).all()
        # Receipt adalah fakta stok tersendiri. Adanya rincian pengajuan tidak
        # menggantikan pemeriksaan identitas pada item yang benar-benar diterima.
        for i in items:
            if i.outgoing_item_id:
                item = await db.get(OutgoingItem, i.outgoing_item_id)
                sumber = await db.get(OutgoingRecord, item.outgoing_record_id) if item else None
                if not sumber or sumber.pelanggan_id != tiket['pelanggan_id'] or (asal and sumber.id != asal.id):
                    raise ValueError('Identitas item penerimaan historis perlu diperiksa di PadiFlow.')
        gudang = await db.get(Warehouse, terima.warehouse_id) if terima.warehouse_id else None
        from app.models import FinishedGoodsStock
        gudang_item = dict((await db.execute(select(CustomerReturnItem.outgoing_item_id, Warehouse.nama_gudang)
            .join(FinishedGoodsStock, FinishedGoodsStock.id == CustomerReturnItem.finished_goods_stock_id)
            .join(Warehouse, Warehouse.id == FinishedGoodsStock.warehouse_id)
            .where(CustomerReturnItem.customer_return_id == terima.id))).all())
        for m in baris:
            m['gudang'] = gudang_item.get(m['outgoing_item_id']) or (gudang.nama_gudang if gudang else None)
        # Tiket historis dapat hanya memiliki penerimaan, tanpa rincian asal.
        if not baris:
            baris = [dict(nama='Barang historis', outgoing_item_id=i.outgoing_item_id,
                          jumlah_karung=i.jumlah_karung, berat_kg=str(i.berat_total_kg),
                          gudang=gudang.nama_gudang if gudang else None) for i in items]
    total = str(sum((Decimal(str(m['berat_kg'])) for m in baris), Decimal(0))) if baris else None
    return dict(tiket_id=tid, kode_tiket=tiket['kode'], pelanggan_id=tiket['pelanggan_id'],
        status=status or 'tidak_pasti', pengajuan_id=rincian.id if rincian else None,
        asal=asal_data, muatan=baris, total_rincian_kg=total,
        pemeriksaan={k: hasil.get(k) for k in ('status', 'alasan', 'berat_tiket_kg', 'berat_rincian_kg', 'selisih_kg', 'toleransi_kg')},
        wajib_manual=bool(rincian and rincian.wajib_manual),
        penerimaan=dict(id=terima.id, kode=terima.kode, berat_stok_kg=str(terima.berat_rincian_kg),
                       waktu=terima.waktu.isoformat()) if terima else None)
