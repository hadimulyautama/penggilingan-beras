"""Kemas ulang atomik dari satu batch: asal, hasil, sisa, dan pemilik seimbang."""
from decimal import Decimal
import hashlib
import json
from sqlalchemy import select
from app.models import FinishedGoodsStock, KemasUlang, Jasa, ProductSku
from app.database import now_local
from app.penggilingan.inventory.packaging import InventoryError, find_or_create_sku, hitung_stok_kemasan
from app.penggilingan.inventory.finished_goods import sisa_karung_per_sumber, hitung_stok_finished_goods
from app.services.barang_keluar import _kunci_saldo_keluar, _sudah_dipesan
from app.services.activity_log import log_activity

D=lambda n: Decimal(str(n))

def sidik(*data):
    return hashlib.sha256(json.dumps(data,sort_keys=True,default=str).encode()).hexdigest()

async def pilihan(db, sku_id, std_id, jasa_id, user_id):
    sumber=await sisa_karung_per_sumber(db,sku_id,std_id,jasa_id=jasa_id,source_type=None)
    pesan=await _sudah_dipesan(db,sku_id=sku_id,std_id=std_id,jasa_id=jasa_id)
    stok=await hitung_stok_finished_goods(db,sku_id,std_id,jasa_id=jasa_id)
    bebas=max(0,stok['kg']-pesan)
    hasil=[]
    for row,jumlah,berat in sumber:
        from app.services.retur_supplier_reservasi import karung_terikat
        jumlah=max(0,jumlah-await karung_terikat(db,f'beras:{row.id}'))
        sisa_n=row.jumlah_karung-int(row.retur_supplier_keluar_karung)
        per=(D(row.berat_total_kg)-D(row.retur_supplier_keluar_kg))/D(sisa_n) if sisa_n else D(0)
        if per<=0:continue
        jumlah=min(jumlah,int(D(bebas)//per))
        if jumlah<=0:continue
        hasil.append(dict(id=row.id,jumlah=jumlah,unit=float(per),curah=False,
            kunci=sidik(user_id,row.id,row.jasa_id,row.product_sku_id,row.rice_quality_standard_id,row.kemasan_mengurangi_stok,row.jumlah_karung,str(row.berat_total_kg),jumlah,pesan),
            label=f'Batch #{row.id} · {jumlah} karung tersedia · {float(per):g} kg/karung'))
    rows=(await db.execute(select(FinishedGoodsStock).where(
        FinishedGoodsStock.product_sku_id==sku_id,
        FinishedGoodsStock.rice_quality_standard_id.is_(None) if std_id is None else FinishedGoodsStock.rice_quality_standard_id==std_id,
        FinishedGoodsStock.jasa_id.is_(None) if jasa_id is None else FinishedGoodsStock.jasa_id==jasa_id,
        FinishedGoodsStock.curah_kemas_ulang.is_(True),FinishedGoodsStock.berat_total_kg>0)
        .order_by(FinishedGoodsStock.id))).scalars().all()
    for row in rows:
        from app.services.retur_supplier_reservasi import terikat
        bebas_curah=max(D(0),D(row.berat_total_kg)-D(row.retur_supplier_keluar_kg)-await terikat(db,sumber=f'beras:{row.id}'))
        if bebas_curah<=0:continue
        hasil.append(dict(id=row.id,jumlah=float(bebas_curah),unit=1,curah=True,
            kunci=sidik(user_id,row.id,row.jasa_id,row.product_sku_id,row.rice_quality_standard_id,str(row.berat_total_kg)),
            label=f'Sisa curah #{row.id} · {float(row.berat_total_kg):g} kg tersedia'))
    return hasil

async def simpan(db, *, user, sumber_id, kunci, jumlah_asal, material, ukuran, merk, jumlah_baru):
    await _kunci_saldo_keluar(db)
    payload=sidik(user.id,sumber_id,str(D(jumlah_asal)),material,ukuran,merk,jumlah_baru)
    lama=await db.scalar(select(KemasUlang).where(KemasUlang.kunci==kunci))
    if lama:
        if lama.sidik!=payload:raise InventoryError('Kiriman ini sudah dipakai dengan isian berbeda. Muat ulang dan periksa kembali.')
        return lama
    row=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.id==sumber_id).with_for_update().execution_options(populate_existing=True))
    if not row:raise InventoryError('Batch asal tidak ditemukan.')
    opsi=next((x for x in await pilihan(db,row.product_sku_id,row.rice_quality_standard_id,row.jasa_id,user.id) if x['id']==row.id),None)
    if not opsi or opsi['kunci']!=kunci:raise InventoryError('Stok berubah sejak formulir dibuka. Muat ulang, lalu periksa kembali. Isian Anda belum disimpan.')
    asal=D(jumlah_asal)
    if not asal.is_finite() or asal<=0 or asal>D(opsi['jumlah']):raise InventoryError('Jumlah asal melebihi stok yang tersedia atau tidak valid.')
    if not row.curah_kemas_ulang and asal!=asal.to_integral_value():raise InventoryError('Jumlah karung asal wajib bilangan bulat.')
    if D(jumlah_baru)!=D(jumlah_baru).to_integral_value() or jumlah_baru<=0:raise InventoryError('Jumlah kemasan baru wajib bilangan bulat lebih dari nol.')
    if asal.as_tuple().exponent < -2:raise InventoryError('Berat asal paling banyak dua angka desimal.')
    if merk:
        from app.models import Brand
        if not await db.scalar(select(Brand.id).where(Brand.nama==merk,Brand.aktif.is_(True),Brand.deleted_at.is_(None))):
            raise InventoryError('Merek baru tidak aktif atau tidak ditemukan.')
    sku=await db.get(ProductSku,row.product_sku_id)
    baru=await find_or_create_sku(db,kategori=sku.kategori,material_kode=material,ukuran=ukuran,brand_nama=merk or None)
    total=(asal*D(opsi['unit'])).quantize(D('.01'))
    berat_baru=D(jumlah_baru)*D(ukuran)
    if berat_baru>total:raise InventoryError(f'Berat kemasan baru {berat_baru:g} kg melebihi berat asal {total:g} kg.')
    pelanggan=None
    if row.jasa_id:
        jasa=await db.get(Jasa,row.jasa_id);pelanggan=jasa.pelanggan_id
    karung=await hitung_stok_kemasan(db,baru.packaging_material_id,baru.package_size_id,baru.brand_id,pelanggan_id=pelanggan)
    if jumlah_baru>karung:raise InventoryError(f'Stok kemasan baru milik pemilik ini tinggal {karung} lembar; diperlukan {jumlah_baru}.')
    dibuka=0 if row.curah_kemas_ulang else int(asal)
    now=now_local();sisa=total-berat_baru
    cat=KemasUlang(kunci=kunci,sidik=payload,sumber_id=row.id,sku_asal_id=sku.id,sku_baru_id=baru.id,jasa_id=row.jasa_id,
        karung_dibuka=dibuka,karung_lama_dihitung=dibuka if row.kemasan_mengurangi_stok else 0,
        berat_asal_kg=total,karung_baru=jumlah_baru,berat_baru_kg=berat_baru,sisa_kg=sisa,petugas_id=user.id,waktu=now)
    row.jumlah_karung-=dibuka;row.berat_total_kg=D(row.berat_total_kg)-total
    def masuk(sku_id,kg,jumlah,curah):
        db.add(FinishedGoodsStock(product_sku_id=sku_id,rice_quality_standard_id=row.rice_quality_standard_id,
            source_type=row.source_type,source_id=row.source_id,jumlah_karung=jumlah,berat_total_kg=kg,
            warehouse_id=row.warehouse_id,waktu=now,input_by=user.id,jasa_id=row.jasa_id,hpp_per_kg=row.hpp_per_kg,
            curah_kemas_ulang=curah,kemasan_mengurangi_stok=not curah))
    masuk(baru.id,berat_baru,jumlah_baru,False)
    if sisa:masuk(sku.id,sisa,0,True)
    db.add(cat);await db.flush()
    await log_activity(db,table_name='kemas_ulang',record_id=cat.id,action='INSERT',changed_by=user.id,
        new_value=f'Batch #{row.id}: {total} kg → {jumlah_baru} karung / {berat_baru} kg; sisa curah {sisa} kg; jasa_id={row.jasa_id}',gudang='g2')
    await db.commit()
    return cat

async def saldo_kemasan(db, sumber_id, material, ukuran, merk):
    """Pratinjau baca-saja; pemilik selalu diturunkan dari batch asal."""
    from app.models import Brand
    from app.penggilingan.inventory.packaging import _validate_kemasan, get_material, get_size
    row = await db.get(FinishedGoodsStock, sumber_id)
    if row is None:
        raise InventoryError('Batch asal tidak ditemukan.')
    sku = await db.get(ProductSku, row.product_sku_id)
    _validate_kemasan(sku.kategori, material, ukuran)
    mat, size = await get_material(db, material), await get_size(db, ukuran)
    if mat is None or size is None:
        raise InventoryError('Jenis atau ukuran kemasan tidak terdaftar.')
    brand_id = None
    if merk:
        brand_id = await db.scalar(select(Brand.id).where(Brand.nama == merk, Brand.aktif.is_(True), Brand.deleted_at.is_(None)))
        if brand_id is None:
            raise InventoryError('Merek baru tidak aktif atau tidak ditemukan.')
    pelanggan_id = None
    if row.jasa_id:
        jasa = await db.get(Jasa, row.jasa_id)
        if jasa is None:
            raise InventoryError('Pemilik batch asal tidak ditemukan.')
        pelanggan_id = jasa.pelanggan_id
    jumlah = await hitung_stok_kemasan(db, mat.id, size.id, brand_id, pelanggan_id=pelanggan_id)
    return dict(tersedia=max(0, jumlah), pemilik='pelanggan jasa' if row.jasa_id else 'pabrik')

async def kemasan_tersedia(db, kategori, jasa_id):
    """Pilihan jenis/ukuran/merek dari saldo positif milik pemilik produk."""
    from app.models import Brand
    from app.penggilingan.inventory.packaging import stok_kemasan_rinci, _validate_kemasan
    pelanggan_id = None
    if jasa_id is not None:
        jasa = await db.get(Jasa, jasa_id)
        if jasa is None:
            raise InventoryError('Pemilik produk tidak ditemukan.')
        pelanggan_id = jasa.pelanggan_id
    aktif = set((await db.execute(select(Brand.nama).where(Brand.aktif.is_(True), Brand.deleted_at.is_(None)))).scalars())
    pilihan = {}
    for b in await stok_kemasan_rinci(db, pelanggan_id=pelanggan_id):
        if b['lembar'] <= 0 or (b['merk'] and b['merk'] not in aktif):
            continue
        if b['merk'] and kategori not in ('beras_putih', 'beras_b'):
            continue  # SKU hasil samping tidak memakai merek.
        try:
            _validate_kemasan(kategori, b['kode'], b['ukuran'])
        except InventoryError:
            continue
        key = f"{b['kode']}|{b['ukuran']}"
        p = pilihan.setdefault(key, dict(value=key, label=f"{b['nama']} · {b['ukuran']} kg", ukuran=b['ukuran'], merek=[]))
        p['merek'].append(dict(value=b['merk'] or '', label=b['merk'] or 'Tanpa merek', tersedia=b['lembar']))
    return list(pilihan.values())
