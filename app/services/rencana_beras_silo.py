"""Informasi baca saja untuk empat field Masukkan beras ke silo.

Rencana memakai bagian alokasi layanan simpan, tanpa kunci atau mutasi.
Saldo kecil tetap dibaca apa adanya: ambang penawaran daftar bukan alasan
untuk menyatakan saldo yang belum habis sebagai nol setelah penyimpanan.
"""
from sqlalchemy import select
from app.models import (FinishedGoodsStock, ProductSku, PackageSize, Brand,
                        PackagingMaterial, PolishingProcess, PolishingSiloUsage, Jasa)
from app.penggilingan.inventory.finished_goods import get_standard
from app.penggilingan.gudang2.rencana_beras import (
    curah_beras_sumber, rencana_beras, sumber_karung_beras, berat_karung_nyata)
from app.penggilingan.gudang2 import service as g2


def urai(jenis, sumber):
    from app.services.stok import BERAS_JENIS
    grade, _, scope = str(jenis or '').strip().lower().partition('|')
    asal, _, owner = str(sumber or '').strip().partition('|')
    if grade not in BERAS_JENIS or scope not in {'pabrik', 'jasa'}:
        raise ValueError('Pilih jenis beras dan lingkup stok yang sah.')
    if not asal or not owner:
        raise ValueError('Pilih sumber stok beras.')
    if (scope == 'pabrik') != (owner == 'pabrik'):
        raise ValueError('Pemilik sumber tidak sesuai dengan lingkup stok.')
    if owner != 'pabrik' and not owner.isdigit():
        raise ValueError('Pemilik stok jasa tidak sah.')
    return grade, asal, None if owner == 'pabrik' else int(owner)


async def identitas(db, proc_id, source_type, source_id, row_id=None):
    proc = await db.get(PolishingProcess, proc_id) if proc_id is not None else None
    kode = proc.kode_proses if proc else None
    asal = {'polishing': 'Hasil penyosohan', 'timbangan': 'Penerimaan timbang',
            'customer_return': 'Retur pelanggan', 'retur': 'Retur pelanggan'}.get(
                source_type, source_type or 'Asal belum tercatat')
    # Identitas asal mengikuti catatan nyata. Penerimaan/retur tidak diberi
    # proses sintetis ataupun tautan tebakan berdasarkan waktu/pemilik.
    return dict(proses_id=proc_id, source_type=source_type, source_id=source_id,
                stok_id=row_id, kode=kode or (f'{asal} #{source_id}' if source_id is not None else asal),
                asal=asal)


async def rincian(db, jenis, sumber, berat=None, silo=''):
    from app.services.jasa import nama_pemilik
    from app.services.stok import nama_produk
    from app.services.angka import angka_wajar
    grade, asal, owner = urai(jenis, sumber)
    if owner is not None and await db.get(Jasa, owner) is None:
        raise ValueError('Pemilik stok jasa tidak ditemukan.')
    std = await get_standard(db, grade)
    std_id = std.id if std else None
    kategori = 'beras_b' if grade == 'beras_b' else 'beras_putih'
    rows = []; ukuran = None; karung = None; merek = None; bahan = None
    if asal == 'curah':
        async for proc, kg in curah_beras_sumber(db, grade, owner):
            if kg > 0:
                rows.append(dict(**await identitas(db, proc.id, 'polishing', proc.id), kg=kg, karung=None))
        saldo = sum(r['kg'] for r in rows)
    elif asal.startswith('curah:'):
        try: rid = int(asal.partition(':')[2])
        except ValueError: raise ValueError('Sumber curah tidak sah.') from None
        row = await db.get(FinishedGoodsStock, rid)
        sku = await db.get(ProductSku, row.product_sku_id) if row else None
        if (row is None or not row.curah_kemas_ulang or row.jumlah_karung != 0
                or row.jasa_id != owner or sku is None or sku.kategori != kategori
                or row.rice_quality_standard_id != std_id):
            raise ValueError('Sumber curah tidak cocok dengan jenis dan pemilik stok.')
        saldo = float(row.berat_total_kg)
        rows.append(dict(**await identitas(db, row.source_id if row.source_type == 'polishing' else None,
                                          row.source_type, row.source_id, row.id), kg=saldo, karung=None))
    elif asal.startswith('sku:'):
        try: sku_id = int(asal.partition(':')[2])
        except ValueError: raise ValueError('Sumber kemasan tidak sah.') from None
        sku = await db.get(ProductSku, sku_id)
        if sku is None or sku.kategori != kategori:
            raise ValueError('Kemasan tidak sesuai dengan jenis beras.')
        size = await db.get(PackageSize, sku.package_size_id)
        if not size or not size.ukuran_kg or float(size.ukuran_kg) <= 0:
            raise ValueError('Ukuran kemasan tidak sah.')
        ukuran = float(size.ukuran_kg)
        brand = await db.get(Brand, sku.brand_id) if sku.brand_id else None
        material = await db.get(PackagingMaterial, sku.packaging_material_id)
        merek = brand.nama if brand else 'Tanpa merek'
        bahan = material.nama if material else 'Bahan kemasan belum tercatat'
        stock_rows, saldo_nyata = await sumber_karung_beras(db, sku.id, std_id, owner)
        for row, n, _ in stock_rows:
            rows.append(dict(**await identitas(db, row.source_id if row.source_type == 'polishing' else None,
                                              row.source_type, row.source_id, row.id), kg=float(berat_karung_nyata(row,n)), karung=n))
        karung = sum(r['karung'] for r in rows)
        saldo = float(saldo_nyata)
    else:
        raise ValueError('Pilih curah atau merek dan ukuran kemasan yang sah.')
    out = dict(jenis=grade, jenis_label=nama_produk(grade), pemilik=await nama_pemilik(db, owner) if owner else 'Milik pabrik',
               jasa_id=owner, sumber=sumber, bentuk='kemasan' if ukuran else 'curah',
               merek=merek, bahan=bahan, ukuran=ukuran, saldo_kg=saldo, karung=karung,
               fifo=rows, rencana=None, pesan='', peringatan_tujuan='', proses_penerima=[])
    if silo:
        dest = await g2.get_g2_silo(db, silo)
        if dest:
            procs = (await db.execute(select(PolishingProcess.id, PolishingProcess.kode_proses)
                .join(PolishingSiloUsage).where(PolishingSiloUsage.silo_id == dest.id,
                    PolishingSiloUsage.berat_akhir_kg.is_(None), PolishingProcess.status == 'proses'))).all()
            out['proses_penerima'] = [dict(id=i,kode=k) for i,k in procs]
    if berat is None or str(berat).strip() == '': return out
    try:
        kg = angka_wajar(berat, 'Berat yang masuk silo')
        p = await rencana_beras(db, jenis=grade, sumber_stok=asal, berat_kg=kg, jasa_id=owner, kunci=False)
    except (ValueError, g2.Gudang2Error) as e:
        out['pesan'] = str(e);return out
    used = []
    stocks = [r for r,_,_ in p['baris_karung']] or [r for r,_ in p['baris_curah']]
    for i, (pid,st,sid,sku_id,w) in enumerate(p['rencana_pindah']):
        row_id = stocks[i].id if i < len(stocks) else None
        used.append(dict(**await identitas(db,pid,st,sid,row_id),kg=w,
                         karung=p['baris_karung'][i][1] if ukuran else None))
    if silo and dest:
        aktif = set((await db.scalars(select(PolishingSiloUsage.polishing_process_id)
            .where(PolishingSiloUsage.silo_id==dest.id,
                   PolishingSiloUsage.berat_akhir_kg.is_(None)))).all())
        konflik = aktif.intersection(p['alokasi'])
        if konflik:
            codes = list((await db.scalars(select(PolishingProcess.kode_proses)
                .where(PolishingProcess.id.in_(list(konflik))))).all())
            out['peringatan_tujuan']='Beras berasal dari '+', '.join(codes)+', yang masih memakai silo tujuan. Pilih silo lain.'
    n = sum(v['karung'] for v in used) if ukuran else None
    out['rencana'] = dict(kg=kg, karung=n, silo=silo,
                         sisa_kg=max(0.0,saldo-kg),
                         sisa_karung=karung-n if ukuran else None, fifo=used)
    return out
