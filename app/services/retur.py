"""Rincian retur milik Produksi; berat jembatan tetap milik Timbangan.

Rincian boleh disimpan setelah bongkar atau setelah tiket selesai ditimbang. Belum ada
stok pada tahap ini. Retur tidak dipotong tara kemasan; bobotnya langsung dari selisih jembatan.
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
        if sku.kategori not in JENIS_RETUR:
            raise ValueError('Jenis retur harus Beras Putih, Broken, Menir, atau Reject.')
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
                          berat_kg=str(weight), tara_per_karung_kg='0',
                          catatan_item=note or '',
                          nama=f"{sku.kategori.replace('_', ' ').title()} · {brand or 'Tanpa merk'} · {material} · {size} kg"))
    if sum(m['jumlah_karung'] for m in hasil) > 100_000:
        raise ValueError('Total jumlah karung melampaui batas satu tiket timbang.')
    return hasil


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
        raise ValueError('Rincian retur belum diisi di Produksi. Isi rincian barang yang diterima di Produksi.')
    return {'kode_tiket': tiket['kode'], 'muatan': [dict(m, tara_per_karung_kg='0') for m in rincian.muatan]}


JENIS_RETUR = {'beras_putih': 'Beras Putih', 'broken': 'Broken',
               'menir': 'Menir', 'reject': 'Reject'}


async def katalog(db):
    """Pilihan berasal dari master, bukan hanya SKU yang pernah dipakai."""
    from app.web.aksi_inventory import kombinasi_kemasan
    materials = {m.kode: m for m in (await db.scalars(select(PackagingMaterial).where(
        PackagingMaterial.aktif.is_(True)))).all()}
    sizes = {s.ukuran_kg: s for s in (await db.scalars(select(PackageSize).where(
        PackageSize.aktif.is_(True)))).all()}
    brands = (await db.scalars(select(Brand).where(
        Brand.aktif.is_(True), Brand.deleted_at.is_(None)).order_by(Brand.nama))).all()
    kemasan = {k: [] for k in JENIS_RETUR}
    for jenis, material, ukuran in kombinasi_kemasan():
        if jenis in kemasan and material in materials and ukuran in sizes:
            kemasan[jenis].append({'nilai': f'{material}:{ukuran}',
                'nama': f'{materials[material].nama} · {ukuran} kg'})
    existing = (await db.execute(select(ProductSku.id, ProductSku.kategori,
        ProductSku.brand_id, PackagingMaterial.kode, PackageSize.ukuran_kg)
        .select_from(ProductSku)
        .join(PackagingMaterial, PackagingMaterial.id == ProductSku.packaging_material_id)
        .join(PackageSize, PackageSize.id == ProductSku.package_size_id)
        .where(ProductSku.kategori.in_(JENIS_RETUR), ProductSku.aktif.is_(True)))).all()
    return {'jenis': JENIS_RETUR, 'kemasan': kemasan,
            'merek': [{'id': b.id, 'nama': b.nama} for b in brands],
            'sku': {str(sid): {'jenis_barang': jenis, 'kemasan': f'{mat}:{size}',
                              'brand_id': brand} for sid,jenis,brand,mat,size in existing}}


async def pilih_sku(db, jenis, kemasan, brand_raw):
    """Validasi pilihan bertahap; SKU internal dibuat hanya ketika disimpan."""
    from app.penggilingan.inventory import packaging
    if jenis not in JENIS_RETUR:
        raise ValueError('Pilih jenis barang: Beras Putih, Broken, Menir, atau Reject.')
    try:
        material_kode, ukuran_raw = kemasan.split(':')
        ukuran = int(ukuran_raw)
    except (ValueError, AttributeError):
        raise ValueError('Pilih kemasan barang retur.')
    material = await packaging.get_material(db, material_kode)
    size = await packaging.get_size(db, ukuran)
    if not material or not material.aktif or not size or not size.aktif:
        raise ValueError('Kemasan tidak tersedia. Pilih ulang jenis karung dan ukurannya.')
    brand = None
    if jenis == 'beras_putih':
        if not brand_raw or not str(brand_raw).isdigit():
            raise ValueError('Pilih merek untuk Beras Putih.')
        brand = await db.get(Brand, int(brand_raw))
        if not brand or not brand.aktif or brand.deleted_at is not None:
            raise ValueError('Merek tidak tersedia. Pilih ulang mereknya.')
    elif brand_raw:
        raise ValueError('Merek hanya dipilih untuk Beras Putih.')
    try:
        sku = await packaging.find_or_create_sku(db, kategori=jenis,
            material_kode=material_kode, ukuran=ukuran,
            brand_nama=brand.nama if brand else None)
    except packaging.InventoryError as exc:
        raise ValueError(str(exc)) from exc
    if not sku.aktif:
        raise ValueError('Kombinasi produk ini sudah dinonaktifkan.')
    return sku.id
