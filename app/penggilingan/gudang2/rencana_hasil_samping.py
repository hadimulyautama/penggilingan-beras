"""Pembacaan dan alokasi Menir/Reject yang dipakai layanan pemindahan.

Urutan proses ID, pengurangan pengiriman sebelum alokasi, dan toleransi
0,005 kg berasal dari layanan lama. Pembaca tidak menulis atau mengunci;
layanan penyimpanan tetap bertanggung jawab atas transaksi dan izin.
"""
from sqlalchemy import select, func, or_
from app.models import (PolishingProcess, HasilSampingKeSilo, FinishedGoodsStock,
                        ProductSku, OutgoingItem, ByproductStock)
from app.services.stok import output_sosoh


async def saldo_sumber(db, jenis, jasa_id, *, user=None):
    from app.services.cakupan_fasilitas import batas,lokasi
    scope=batas(user,PolishingProcess)
    local_packed=select(FinishedGoodsStock.source_id).join(ProductSku).where(FinishedGoodsStock.source_type=='polishing',ProductSku.kategori==jenis,FinishedGoodsStock.jasa_id==jasa_id,batas(user,FinishedGoodsStock))
    local_proc=set((await db.scalars(select(PolishingProcess.id).where(scope))).all())
    procs = (await db.execute(
        select(PolishingProcess).where(PolishingProcess.status.in_(("proses", "selesai")),or_(scope,PolishingProcess.id.in_(local_packed)))
        .order_by(PolishingProcess.id)
    )).scalars().all()
    from app.penggilingan.inventory.finished_goods import _packed_kg
    candidates: list[list] = []
    rincian = []
    for proc in procs:
        hasil = float((await output_sosoh(db, proc.id)).get(jenis) or 0)
        if hasil <= 0:
            continue
        packed_all = await _packed_kg(db, proc.id, jenis, None)
        packed_owner_q = (select(func.coalesce(func.sum(FinishedGoodsStock.berat_total_kg), 0))
                          .join(ProductSku, ProductSku.id == FinishedGoodsStock.product_sku_id)
                          .where(FinishedGoodsStock.source_type == "polishing",
                                 FinishedGoodsStock.source_id == proc.id,
                                 ProductSku.kategori == jenis,
                                 (FinishedGoodsStock.jasa_id.is_(None) if jasa_id is None
                                  else FinishedGoodsStock.jasa_id == jasa_id),batas(user,FinishedGoodsStock))
                          )
        packed_owner = float((await db.execute(packed_owner_q)).scalar_one())
        from app.services.jasa import pemilik_hasil_proses
        owner = await pemilik_hasil_proses(db,proc.jasa_id,jenis)
        # Pembukuan di gudang lain tetap mengurangi hasil yang belum punya
        # rumah, tetapi bukan stok fisik yang dapat dipakai di gudang ini.
        booked_bulk=float(await db.scalar(select(func.coalesce(func.sum(ByproductStock.berat_kg),0)).where(ByproductStock.source_type=='polishing',ByproductStock.source_id==proc.id,ByproductStock.jenis_produk==jenis)))
        curah_owner = max(0.0, hasil - packed_all-booked_bulk) if owner == jasa_id and proc.id in local_proc else 0.0
        moved = float((await db.execute(
            select(func.coalesce(func.sum(HasilSampingKeSilo.berat_kg), 0))
            .where(HasilSampingKeSilo.polishing_process_id == proc.id,
                   HasilSampingKeSilo.jenis == jenis,batas(user,HasilSampingKeSilo),
                   (HasilSampingKeSilo.jasa_id.is_(None) if jasa_id is None
                    else HasilSampingKeSilo.jasa_id == jasa_id))
        )).scalar_one())
        candidates.append([proc, max(0.0, curah_owner + packed_owner - moved)])
        rincian.append(dict(proses_id=proc.id, kode=proc.kode_proses, status=proc.status,
                            hasil=hasil, kemasan_pemilik=packed_owner, curah_pemilik=curah_owner,
                            dipindah=moved, sebelum_keluar=candidates[-1][1]))

    from types import SimpleNamespace
    from app.services.retur_supplier_stok import keluar as keluar_supplier
    raw = (await db.scalars(select(ByproductStock).where(
        ByproductStock.jenis_produk == jenis,
        ByproductStock.jasa_id.is_(None) if jasa_id is None else ByproductStock.jasa_id == jasa_id, batas(user,ByproductStock)
    ).order_by(ByproductStock.waktu, ByproductStock.id))).all()
    for row in raw:
        moved = float(await db.scalar(select(func.coalesce(func.sum(HasilSampingKeSilo.berat_kg),0)).where(
            HasilSampingKeSilo.byproduct_stock_id == row.id)))
        retur = float((await keluar_supplier(db, sumber=f'broken:{row.id}'))[0])
        kg = max(0,float(row.berat_kg)-moved-retur)
        src = SimpleNamespace(id=row.source_id if row.source_type=='polishing' else None,
            byproduct_stock_id=row.id, kode_proses=f'Stok #{row.id}', status='selesai')
        candidates.append([src,kg])
        rincian.append(dict(proses_id=src.id,stok_id=row.id,kode=src.kode_proses,status='selesai',
            hasil=float(row.berat_kg),kemasan_pemilik=0,curah_pemilik=float(row.berat_kg),
            dipindah=moved+retur,sebelum_keluar=kg))

    milik_keluar = (OutgoingItem.jasa_id.is_(None) if jasa_id is None
                    else OutgoingItem.jasa_id == jasa_id)
    keluar_curah = float((await db.execute(
        select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
        .where(OutgoingItem.item_type == "byproduct_curah",
               OutgoingItem.jenis_byproduct == jenis, milik_keluar,batas(user,OutgoingItem))
    )).scalar_one())
    keluar_karung = float((await db.execute(
        select(func.coalesce(func.sum(OutgoingItem.berat_kg), 0))
        .join(ProductSku, ProductSku.id == OutgoingItem.product_sku_id)
        .where(OutgoingItem.item_type == "finished_goods",
               ProductSku.kategori == jenis, milik_keluar,batas(user,OutgoingItem))
    )).scalar_one())
    sisa_keluar = keluar_curah + keluar_karung
    # Stok dikeluarkan FIFO; terapkan pengeluaran lama sebelum merencanakan
    # perpindahan baru agar aksi tidak menghabiskan kg yang sudah dikirim.
    for candidate, baris in zip(candidates, rincian):
        consumed = min(candidate[1], sisa_keluar)
        candidate[1] -= consumed
        sisa_keluar -= consumed
        baris.update(keluar=consumed, tersedia=candidate[1], saldo_fisik=candidate[1])

    # Perintah dan retur yang masih dialokasikan juga mengikat saldo.
    from app.services.barang_keluar import tersedia, BarisPerintah
    bebas,_ = await tersedia(db, BarisPerintah(tipe='byproduct_curah',jenis=jenis,jasa_id=jasa_id),warehouse_id=getattr(user,'stock_warehouse_filter',None))
    terikat = max(0,sum(c[1] for c in candidates)-max(float(bebas),0))
    for candidate, baris in zip(candidates,rincian):
        kurang = min(candidate[1],terikat);candidate[1]-=kurang;terikat-=kurang
        baris['keluar'] += kurang;baris['tersedia']=candidate[1]

    return dict(candidates=candidates, sumber=rincian,
                keluar_curah=keluar_curah, keluar_kemasan=keluar_karung,
                saldo_kg=sum(c[1] for c in candidates))


def alokasikan(data, jenis, berat_kg):
    from app.penggilingan.gudang2.service import Gudang2Error
    candidates = data['candidates']
    sisa_diminta = float(berat_kg)
    rencana: list[tuple[PolishingProcess, float]] = []
    for proc, tersedia in candidates:
        ambil = min(tersedia, sisa_diminta)
        if ambil > 0.005:
            rencana.append((proc, ambil))
            sisa_diminta -= ambil
        if sisa_diminta <= 0.005:
            break
    if sisa_diminta > 0.005:
        raise Gudang2Error(
            f"Stok {jenis.title()} yang masih tersedia hanya "
            f"{float(berat_kg)-sisa_diminta:,.2f} kg.".replace(",", "."))

    return rencana
