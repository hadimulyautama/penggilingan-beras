"""Pembaca saldo untuk rencana dan writer Isi Silo, tanpa pembukuan baru."""
from sqlalchemy import select
from app.models import ByproductStock, FinishedGoodsStock, ProductSku, PackageSize
from app.services.cakupan_fasilitas import lokasi


async def curah_bebas(db, row):
    from app.penggilingan.gudang2.service import _sisa_broken_row
    from app.services.transfer_barang_sumber import bebas
    return max(0.0, min(await _sisa_broken_row(db, row.id), float(await bebas(db, row, 'curah'))))


async def karung_bebas(db, row):
    from app.penggilingan.inventory.finished_goods import sisa_karung_per_sumber
    # Pembaca yang sudah dipakai writer: FIFO pengeluaran/lokasi dan retur.
    rows = await sisa_karung_per_sumber(db, row.product_sku_id,
        row.rice_quality_standard_id, jasa_id=row.jasa_id, source_type=None)
    return max(0, min(int(row.jumlah_karung or 0), next((n for r,n,_ in rows if r.id==row.id),0)))


async def proses(db, proc, owner, wid, *, prep=None):
    from app.services.jasa import pemilik_hasil_proses
    from app.services.stok import output_sosoh
    from app.penggilingan.inventory.finished_goods import _broken_dibukukan
    def milik(c):return c.is_(None) if owner is None else c==owner
    curah=[]
    rows=(await db.scalars(select(ByproductStock).where(
        ByproductStock.jenis_produk=='broken',ByproductStock.source_type=='polishing',
        ByproductStock.source_id==proc.id,milik(ByproductStock.jasa_id),lokasi(ByproductStock)==wid)
        .order_by(ByproductStock.waktu,ByproductStock.id))).all()
    for r in rows:
        w=await curah_bebas(db,r)
        if w>0.5:curah.append((r.id,w))
    packs=[]
    rows=(await db.execute(select(FinishedGoodsStock,PackageSize.ukuran_kg)
        .join(ProductSku,ProductSku.id==FinishedGoodsStock.product_sku_id)
        .outerjoin(PackageSize,PackageSize.id==ProductSku.package_size_id)
        .where(ProductSku.kategori=='broken',FinishedGoodsStock.source_type=='polishing',
            FinishedGoodsStock.source_id==proc.id,milik(FinishedGoodsStock.jasa_id),lokasi(FinishedGoodsStock)==wid)
        .order_by(FinishedGoodsStock.waktu,FinishedGoodsStock.id))).all()
    for r,size in rows:
        n=await karung_bebas(db,r)
        # Writer membuka karung utuh berdasarkan ukuran SKU yang sama.
        if n and size:packs.append(dict(id=r.id,n=n,ukuran=float(size),kg=n*float(size)))
    mesin=0.0
    if owner==await pemilik_hasil_proses(db,proc.jasa_id,'broken'):
        mesin=max(0.0,float((await output_sosoh(db,proc.id)).get('broken') or 0)-await _broken_dibukukan(db,proc.id))
    if mesin<=0.5:mesin=0.0
    total_mesin=mesin
    if prep is None:
        prep=await persiapan(db,owner,wid,[proc])
    ditahan=sum(x['kg'] for x in prep['items'] if x['proc_id']==proc.id)
    mesin=max(0.0,mesin-ditahan)
    return dict(curah=curah,packs=packs,mesin=mesin,mesin_total=total_mesin,mesin_persiapan=ditahan,
        total=sum(w for _,w in curah)+sum(p['kg'] for p in packs)+mesin)


async def persiapan(db, owner, wid, procs):
    """Defisit pool curah existing dan pembukuan raw minimum, tanpa menulis.

    Pending curah tetap pending curah; tidak dibuat reservasi atau hak baru.
    Baris hasil baru disiapkan menurut FIFO proses yang digunakan rencana lama.
    Kasus lintas bentuk yang tidak terbukti ditahan, bukan dibagi proporsional.
    """
    from sqlalchemy import func
    from app.models import OutgoingItem, OutgoingRecord
    from app.penggilingan.gudang2.service import _sisa_broken_row, Gudang2Error
    from app.services.jasa import pemilik_hasil_proses
    from app.services.stok import output_sosoh
    from app.penggilingan.inventory.finished_goods import _broken_dibukukan
    from app.services.retur_supplier_reservasi import terikat

    def milik(c):
        return c.is_(None) if owner is None else c == owner

    rows=(await db.scalars(select(ByproductStock).where(
        ByproductStock.jenis_produk=='broken',milik(ByproductStock.jasa_id),
        lokasi(ByproductStock)==wid))).all()
    physical=0.0
    supplier_held=0.0
    for row in rows:
        physical+=max(0.0,await _sisa_broken_row(db,row.id))
        supplier_held+=float(await terikat(db,sumber=f'broken:{row.id}'))
    scope=(OutgoingItem.item_type=='byproduct_curah',OutgoingItem.jenis_byproduct=='broken',
           milik(OutgoingItem.jasa_id),lokasi(OutgoingItem)==wid)
    used=float(await db.scalar(select(func.coalesce(func.sum(OutgoingItem.berat_kg),0)).where(*scope)))
    pending_rows=(await db.execute(select(OutgoingItem.berat_perintah_kg,OutgoingItem.berat_kg)
        .join(OutgoingRecord).where(*scope,OutgoingRecord.status=='perintah'))).all()
    if any(float(a or 0)<float(b or 0) for a,b in pending_rows):
        raise Gudang2Error('Saldo perintah broken perlu ditinjau; rencana otomatis ditahan. Periksa melalui Admin tanpa mengubah muatan yang benar.')
    pending=sum(float(a or 0)-float(b or 0) for a,b in pending_rows)
    need=max(0.0,used+pending-physical)
    if need<=0.5:
        return dict(defisit_kg=0.0,items=[],belum_tertutup_kg=0.0)
    # Supplier holds are source-bound. A curah debt cannot silently move them
    # onto output logs. Likewise, pending FG retains its SKU/bag contract.
    fg_pending=float(await db.scalar(select(func.coalesce(func.sum(
        OutgoingItem.berat_perintah_kg-OutgoingItem.berat_kg),0))
        .join(OutgoingRecord).join(ProductSku,ProductSku.id==OutgoingItem.product_sku_id)
        .where(OutgoingRecord.status=='perintah',OutgoingItem.item_type=='finished_goods',
            ProductSku.kategori=='broken',milik(OutgoingItem.jasa_id),lokasi(OutgoingItem)==wid)))
    if supplier_held>0.5 or fg_pending>0.5:
        raise Gudang2Error('Rencana hasil mesin ditahan: ada alokasi retur atau perintah kemasan yang perlu ditinjau Admin. Tidak ada pembukuan atau pemindahan tersimpan.')
    items=[];left=need
    for proc in procs:
        if left<=0.5:
            break
        if owner!=await pemilik_hasil_proses(db,proc.jasa_id,'broken'):
            continue
        raw=max(0.0,float((await output_sosoh(db,proc.id)).get('broken') or 0)-await _broken_dibukukan(db,proc.id))
        take=min(raw,left)
        if take>0.5:
            items.append(dict(proc_id=proc.id,kode=proc.kode_proses,kg=take))
            left-=take
    if left>0.5:
        raise Gudang2Error('Hasil mesin belum dibukukan tidak cukup untuk menyiapkan saldo sumber. Rencana otomatis ditahan; Admin perlu meninjau sumber dan perintah terkait. Karung tidak dibuka untuk menutup defisit ini.')
    return dict(defisit_kg=need,items=items,belum_tertutup_kg=max(0.0,left))


async def bukukan_persiapan(db, *, user, owner, wid, plan, tanggal=None, jam=None):
    """Flush sumber/audit saja; transaksi dan commit milik caller.

    Tidak memanggil catat_broken legacy yang melakukan commit internal.
    """
    from app.models import PolishingProcess
    from app.penggilingan.gudang2 import service as g2
    from app.penggilingan.inventory.finished_goods import _broken_dibukukan
    from app.services.jasa import pemilik_hasil_proses
    from app.services.stok import output_sosoh
    from app.services.barang_keluar import _kunci_saldo_keluar
    from app.database import input_time
    from app.services.activity_log import log_activity

    await _kunci_saldo_keluar(db)
    if not g2.is_operator_gudang2(user,wid):
        raise g2.Gudang2Error('Pembukuan sumber hanya melalui petugas Gudang 2 yang berwenang.')
    if plan['belum_tertutup_kg']>0.5:
        raise g2.Gudang2Error('Sumber hasil mesin tidak cukup untuk menutup saldo perintah; transaksi tidak tersimpan.')
    now=input_time(tanggal,jam);created=[]
    for item in plan['items']:
        proc=await db.get(PolishingProcess,item['proc_id'],populate_existing=True,with_for_update=True)
        if proc is None or await db.scalar(select(lokasi(PolishingProcess)).where(PolishingProcess.id==proc.id))!=wid:
            raise g2.Gudang2Error('Lokasi sumber berubah; pembukuan ditahan.')
        if owner!=await pemilik_hasil_proses(db,proc.jasa_id,'broken'):
            raise g2.Gudang2Error('Pemilik hasil sumber berbeda; pembukuan ditahan.')
        raw=max(0.0,float((await output_sosoh(db,proc.id)).get('broken') or 0)-await _broken_dibukukan(db,proc.id))
        kg=float(item['kg'])
        if kg<=0 or kg>raw+0.5:
            raise g2.Gudang2Error('Hasil sumber berubah; transaksi tidak tersimpan.')
        row=ByproductStock(jenis_produk='broken',source_type='polishing',source_id=proc.id,
            berat_kg=kg,jasa_id=owner,warehouse_id=wid,tanggal=now.date(),waktu=now,input_by=user.id)
        db.add(row);await db.flush();created.append(row)
        await log_activity(db,table_name='byproduct_stock',record_id=row.id,action='INSERT',
            changed_by=user.id,aksi='broken_catat_otomatis',field_name='persiapan_silo',
            new_value=f'{proc.kode_proses}: {kg:g} kg dibukukan untuk menyelaraskan saldo sumber dengan pengeluaran/perintah existing; bagian ini tidak masuk silo.')
    # The real existing reader must agree: no newly prepared row is free.
    for row in created:
        if await curah_bebas(db,row)>0.5:
            raise g2.Gudang2Error('Alokasi sumber berubah; pembukuan dan pemindahan dibatalkan.')
    return [row.id for row in created]
