"""Rincian retur milik Produksi; berat jembatan tetap milik Timbangan.

Rincian disimpan setelah bongkar, sebelum truk kosong ditimbang. Belum ada
stok pada tahap ini. Kedua penulis mengunci tiket yang sama agar rincian
kemasan tidak berubah di tengah penyelesaian timbang kedua.
"""
from decimal import Decimal, InvalidOperation

from sqlalchemy import select, text

from app.models import (Brand, PackageSize, PackagingMaterial, ProductSku,
                        RiceQualityStandard)
from app.penggilingan.inventory.models import ReturRincian


def angka(nilai, nama, maksimum, digit):
    try:
        n = Decimal(str(nilai or '0').replace(',', '.'))
        if not n.is_finite() or n < 0 or n > maksimum:
            raise ValueError(f'{nama} di luar batas yang diperbolehkan.')
        if n != n.quantize(Decimal(digit)):
            raise ValueError(f'{nama} memiliki terlalu banyak angka desimal.')
        return n
    except InvalidOperation as exc:
        raise ValueError(f'{nama} bukan angka yang valid.') from exc


async def siapkan_muatan(db, rows):
    hasil = []
    for sku_id, quality_id, count, weight, note, tara in rows:
        if count < 1 or count > 100_000 or weight <= 0:
            raise ValueError('Jumlah karung dan berat barang harus lebih dari nol dan dalam batas wajar.')
        detail = (await db.execute(
            select(ProductSku, Brand.nama, PackagingMaterial.nama, PackageSize.ukuran_kg, PackagingMaterial.kode)
            .outerjoin(Brand, Brand.id == ProductSku.brand_id)
            .join(PackagingMaterial, PackagingMaterial.id == ProductSku.packaging_material_id)
            .join(PackageSize, PackageSize.id == ProductSku.package_size_id)
            .where(ProductSku.id == sku_id, ProductSku.aktif.is_(True))
        )).first()
        if not detail:
            raise ValueError('SKU tidak tersedia. Pilih ulang jenis dan kemasannya.')
        sku, brand, material, size, material_kode = detail
        if material_kode == 'laminasi' and size > 25:
            raise ValueError('Karung laminasi hanya tersedia hingga ukuran 25 kg.')
        if sku.kategori == 'beras_putih' and not quality_id:
            raise ValueError('Pilih mutu beras untuk setiap baris beras putih.')
        if sku.kategori != 'beras_putih' and quality_id:
            raise ValueError('Mutu hanya dipilih untuk beras putih.')
        if quality_id and not await db.get(RiceQualityStandard, quality_id):
            raise ValueError('Mutu beras yang dipilih tidak tersedia.')
        if note and len(note) > 200:
            raise ValueError('Catatan barang maksimal 200 karakter.')
        hasil.append(dict(sku_id=sku_id, quality_id=quality_id,
                          merek_produk_id=sku.brand_id, packaging_material_id=sku.packaging_material_id,
                          package_size_id=sku.package_size_id, jumlah_karung=count,
                          berat_kg=str(weight), tara_per_karung_kg=str(tara),
                          catatan_item=note or '',
                          nama=f"{sku.kategori.replace('_', ' ').title()} · {brand or 'Tanpa merk'} · {material} · {size} kg"))
    if sum(m['jumlah_karung'] for m in hasil) > 100_000:
        raise ValueError('Total jumlah karung melampaui batas satu tiket timbang.')
    return hasil


def identitas_muatan(muatan):
    """Abaikan label master yang bisa berganti; bandingkan fakta kemasannya."""
    return [(m['sku_id'], m.get('quality_id'), int(m['jumlah_karung']),
             Decimal(m['berat_kg']), Decimal(m['tara_per_karung_kg']),
             m.get('catatan_item') or '') for m in muatan]


async def baca_muatan(db, tid):
    tiket = (await db.execute(text('''
        SELECT id, kode, arah, status_tiket, status_transaksi
        FROM timbangan_transaksi WHERE id=:tid
    '''), {'tid': tid})).mappings().first()
    if (not tiket or tiket['arah'] != 'RETUR_MASUK'
            or tiket['status_transaksi'] != 'AKTIF'
            or tiket['status_tiket'] not in ('TERBUKA', 'SELESAI')):
        raise ValueError('Tiket bukan retur pelanggan aktif.')
    rincian = await db.scalar(select(ReturRincian).where(
        ReturRincian.timbangan_transaksi_id == tid))
    if not rincian or not rincian.muatan:
        raise ValueError('Rincian retur belum diisi di Produksi. Isi jumlah karung dan tara setelah bongkar terlebih dahulu.')
    return {'kode_tiket': tiket['kode'], 'muatan': rincian.muatan}
