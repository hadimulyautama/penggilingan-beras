"""Fixture transaksi pra-otomatis; tidak membuka lagi layanan packing manual.

Dipakai hanya untuk menguji pembaca stok, audit, transfer, dan bongkar karung
atas transaksi yang sudah ada sebelum aturan otomatis. Bukan API aplikasi.
"""
from sqlalchemy import select
from app.models import FinishedGoodsStock, PolishingProcess
from app.database import input_time
from app.penggilingan.inventory import finished_goods as fg
from app.services.jasa import pemilik_hasil_proses
from app.services.cakupan_fasilitas import lokasi
from app.services.activity_log import log_activity


async def siapkan_packing_historis(db, *, user, kode_pol, kategori,
                                  material_kode, ukuran, jumlah_karung,
                                  grade=None, brand_nama=None, tanggal=None, jam=None):
    assert kategori in {"broken", "menir", "reject", "bekatul"}
    proc = await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses == kode_pol))
    sku = await fg.find_or_create_sku(db, kategori=kategori, material_kode=material_kode,
                                    ukuran=ukuran, brand_nama=brand_nama)
    berat = jumlah_karung * ukuran
    owner = await pemilik_hasil_proses(db, proc.jasa_id, kategori)
    wid = await db.scalar(select(lokasi(PolishingProcess)).where(PolishingProcess.id == proc.id))
    db.add(FinishedGoodsStock(product_sku_id=sku.id, source_type="polishing", source_id=proc.id,
                             jumlah_karung=jumlah_karung, berat_total_kg=berat,
                             warehouse_id=wid, waktu=input_time(tanggal, jam), input_by=user.id,
                             jasa_id=owner))
    await log_activity(db, table_name="finished_goods_stock", record_id=proc.id,
                       action="INSERT", changed_by=user.id,
                       new_value=f"{kategori}/- x{jumlah_karung} ({berat:.0f}kg)")
    await db.commit()
    return fg.PackingResult(kategori=kategori, grade=grade, jumlah_karung=jumlah_karung,
                            berat_total_kg=berat)
