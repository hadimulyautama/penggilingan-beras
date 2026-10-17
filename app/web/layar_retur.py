"""Penerimaan barang retur: tiket timbang → rincian → stok Gudang 2."""
from __future__ import annotations

from decimal import Decimal, InvalidOperation
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, text

from app.database import SessionLocal, now_local
from app.models import (Brand, CustomerReturn, CustomerReturnItem, FinishedGoodsStock,
                        PackageSize, PackagingMaterial, ProductSku, RiceQualityStandard)
from app.penggilingan.inventory.models import ReturRincian
from app.services import retur as layanan_retur
from app.web.security import butuh_akun
from app.web.tampilan import redirect, render_laci

router = APIRouter(tags=["webapp"])


def _pesan_url(jalur: str, nama: str, isi: str) -> str:
    return f"{jalur}{'&' if '?' in jalur else '?'}{nama}={quote(isi, safe='')}"


def _boleh(akun) -> bool:
    from app.peran import can_see_financials
    return can_see_financials(akun.user)


async def _siapkan(db):
    """Data layar: tiket retur belum dicatat, SKU valid, dan penerimaan terakhir."""
    tickets = (await db.execute(text("""
        SELECT t.id, t.kode, t.tanggal, t.pelanggan_id,
               COALESCE(p.nama_pelanggan, t.pihak_nama, 'Pelanggan tidak tercatat') AS pelanggan,
               t.nomor_polisi, t.nama_sopir, t.timbang1_kg, t.timbang2_kg,
               t.berat_barang_kg, t.jumlah_karung, t.status_tiket
        FROM timbangan_transaksi t
        LEFT JOIN pelanggan p ON p.id = t.pelanggan_id
        LEFT JOIN customer_returns r ON r.timbangan_transaksi_id = t.id
        WHERE t.arah = 'RETUR_MASUK' AND t.status_tiket IN ('TERBUKA', 'SELESAI')
          AND t.status_transaksi = 'AKTIF' AND r.id IS NULL
        ORDER BY t.tanggal DESC, t.id DESC LIMIT 60
    """))).mappings().all()

    tickets = [dict(t) for t in tickets]
    rincian = (await db.scalars(select(ReturRincian).where(
        ReturRincian.timbangan_transaksi_id.in_([t['id'] for t in tickets])))).all()
    per_tiket = {r.timbangan_transaksi_id: r.muatan for r in rincian}
    for t in tickets:
        t['rincian'] = per_tiket.get(t['id'], [])
    result = await db.execute(
        select(ProductSku, Brand.nama, PackagingMaterial.nama, PackageSize.ukuran_kg)
        .join(Brand, Brand.id == ProductSku.brand_id, isouter=True)
        .join(PackagingMaterial, PackagingMaterial.id == ProductSku.packaging_material_id)
        .join(PackageSize, PackageSize.id == ProductSku.package_size_id)
        .where(ProductSku.aktif.is_(True),
               (PackagingMaterial.kode != 'laminasi') | (PackageSize.ukuran_kg <= 25))
        .order_by(ProductSku.kategori, PackageSize.ukuran_kg, Brand.nama)
    )
    skus = [{"id": sku.id, "kategori": sku.kategori,
             "label": f"{sku.kategori.replace('_', ' ').title()} · {brand or 'Tanpa merk'} · {material} · {size} kg"}
            for sku, brand, material, size in result.all()]
    mutu = (await db.scalars(select(RiceQualityStandard).where(
        RiceQualityStandard.aktif.is_(True)).order_by(RiceQualityStandard.urutan))).all()
    recent = (await db.execute(text("""
        SELECT r.id, r.kode, r.kode_tiket, r.nama_pelanggan, r.nomor_polisi,
               r.berat_tiket_kg, r.berat_rincian_kg, r.selisih_kg, r.waktu,
               COUNT(i.id) AS jumlah_jenis
        FROM customer_returns r LEFT JOIN customer_return_items i
          ON i.customer_return_id = r.id
        GROUP BY r.id ORDER BY r.waktu DESC LIMIT 12
    """))).mappings().all()
    return tickets, skus, mutu, recent


@router.get("/retur")
async def halaman_retur(request: Request, akun=Depends(butuh_akun)):
    if not _boleh(akun):
        raise HTTPException(403, "Penerimaan retur hanya tersedia untuk Admin.")
    async with SessionLocal() as db:
        tickets, skus, mutu, recent = await _siapkan(db)
    return await render_laci(request, "retur.html", layar="retur",
                              tickets=tickets, skus=skus, mutu=mutu,
                              recent=recent, pesan=request.query_params.get("pesan"),
                              gagal=request.query_params.get("gagal"),
                              tiket_terpilih=request.query_params.get("tiket", ""))


@router.post("/retur/terima")
async def terima_retur(request: Request, akun=Depends(butuh_akun)):
    if not _boleh(akun):
        raise HTTPException(403, "Penerimaan retur hanya tersedia untuk Admin.")
    form = await request.form()
    try:
        ticket_id = int(form.get("timbangan_transaksi_id", ""))
        sku_ids = form.getlist("sku_id")
        quality_ids = form.getlist("quality_id")
        bag_counts = form.getlist("jumlah_karung")
        weights = form.getlist("berat_kg")
        notes = form.getlist("catatan_item")
        aksi = form.get("aksi", "terima")
        if aksi not in ("rincian", "terima"):
            raise ValueError("Aksi retur tidak dikenal.")
        if not (len(sku_ids) == len(quality_ids) == len(bag_counts) == len(weights) == len(notes)):
            raise ValueError("Rincian barang tidak lengkap. Muat ulang halaman dan isi kembali.")
        rows = []
        for idx, sku_raw in enumerate(sku_ids):
            if not sku_raw:
                continue
            sku_id = int(sku_raw)
            count = int(bag_counts[idx] or 0)
            weight = layanan_retur.angka(weights[idx], 'Berat barang', 1_000_000, '.01')
            tara = Decimal('0')  # Retur tidak dipotong tara, termasuk kiriman halaman lama.
            quality_id = int(quality_ids[idx]) if quality_ids[idx] else None
            if count < 1 or weight <= 0:
                raise ValueError("Setiap baris harus memiliki jumlah karung dan berat lebih dari nol.")
            rows.append((sku_id, quality_id, count, weight, (notes[idx] or "").strip() or None, tara))
        if not rows:
            raise ValueError("Tambahkan minimal satu jenis barang retur.")
        total = sum((row[3] for row in rows), Decimal("0"))
        reason = (form.get("alasan_selisih") or "").strip() or None
        note = (form.get("catatan") or "").strip() or None
        if note and len(note) > 500:
            raise ValueError("Catatan maksimal 500 karakter.")
    except (ValueError, InvalidOperation) as exc:
        return redirect(_pesan_url("/retur", "gagal", str(exc)))

    async with SessionLocal() as db:
        try:
            ticket = (await db.execute(text("""
                SELECT t.id, t.kode, t.pelanggan_id,
                       COALESCE(p.nama_pelanggan, t.pihak_nama) AS pelanggan,
                       t.nomor_polisi, t.timbang1_kg, t.timbang2_kg,
                       t.berat_barang_kg, t.status_tiket, t.jumlah_karung, t.total_tara_kg
                FROM timbangan_transaksi t LEFT JOIN pelanggan p ON p.id=t.pelanggan_id
                WHERE t.id=:id AND t.arah='RETUR_MASUK'
                  AND t.status_tiket IN ('TERBUKA', 'SELESAI') AND t.status_transaksi='AKTIF'
                FOR UPDATE OF t
            """), {"id": ticket_id})).mappings().first()
            if not ticket:
                raise ValueError("Tiket retur tidak ditemukan atau belum selesai ditimbang.")
            already = await db.scalar(select(CustomerReturn.id).where(
                CustomerReturn.timbangan_transaksi_id == ticket_id))
            if already:
                raise ValueError("Tiket ini sudah dicatat sebagai barang retur.")

            muatan = await layanan_retur.siapkan_muatan(db, rows)
            rincian = await db.scalar(select(ReturRincian).where(
                ReturRincian.timbangan_transaksi_id == ticket_id))
            if aksi == 'rincian':
                if ticket['status_tiket'] != 'TERBUKA':
                    raise ValueError('Timbang sudah selesai. Rincian kemasan tidak dapat diubah lagi.')
                if rincian is None:
                    rincian = ReturRincian(timbangan_transaksi_id=ticket_id,
                                           input_by=akun.user.id, muatan=muatan)
                    db.add(rincian)
                else:
                    rincian.muatan = muatan
                    rincian.input_by = akun.user.id
                await db.commit()
                return redirect(_pesan_url(f'/retur?tiket={ticket_id}', 'pesan',
                    'Rincian tersimpan. Lanjutkan timbang truk kosong, lalu verifikasi penerimaan stok.'))
            if ticket['status_tiket'] != 'SELESAI':
                raise ValueError('Selesaikan timbang truk kosong di Pos Timbang terlebih dahulu.')
            ticket_weight = Decimal(str(ticket["berat_barang_kg"]))
            difference = total - ticket_weight
            threshold = max(Decimal("2"), ticket_weight * Decimal("0.002"))
            if abs(difference) > threshold and not reason:
                raise ValueError(f"Selisih {difference:+.2f} kg melewati batas {threshold:.2f} kg. Isi alasan selisih.")
            if reason and len(reason) > 300:
                raise ValueError("Alasan selisih maksimal 300 karakter.")

            from app.models import Warehouse
            warehouse = await db.scalar(select(Warehouse).where(
                Warehouse.kode_fungsi == "g2", Warehouse.aktif.is_(True)))
            now = now_local()
            receipt = CustomerReturn(
                kode="PENDING", timbangan_transaksi_id=ticket_id,
                kode_tiket=ticket["kode"], pelanggan_id=ticket["pelanggan_id"],
                nama_pelanggan=ticket["pelanggan"], nomor_polisi=ticket["nomor_polisi"],
                timbang1_kg=ticket["timbang1_kg"], timbang2_kg=ticket["timbang2_kg"],
                berat_tiket_kg=ticket_weight, berat_rincian_kg=total,
                selisih_kg=difference, alasan_selisih=reason, catatan=note,
                warehouse_id=warehouse.id if warehouse else None,
                input_by=akun.user.id, waktu=now,
            )
            db.add(receipt)
            await db.flush()
            receipt.kode = f"RET-{now:%Y%m%d}-{receipt.id:04d}"
            for sku_id, quality_id, count, weight, item_note, tara in rows:
                item = CustomerReturnItem(
                    customer_return_id=receipt.id, product_sku_id=sku_id,
                    rice_quality_standard_id=quality_id, jumlah_karung=count,
                    berat_total_kg=weight, jasa_id=None, catatan=item_note,
                )
                db.add(item)
                await db.flush()
                stock = FinishedGoodsStock(
                    product_sku_id=sku_id, rice_quality_standard_id=quality_id,
                    source_type="retur", source_id=receipt.id,
                    jumlah_karung=count, berat_total_kg=weight,
                    warehouse_id=receipt.warehouse_id, waktu=now,
                    input_by=akun.user.id, jasa_id=None,
                    kemasan_mengurangi_stok=False,
                )
                db.add(stock)
                await db.flush()
                item.finished_goods_stock_id = stock.id
            await db.commit()
        except ValueError as exc:
            await db.rollback()
            return redirect(_pesan_url("/retur", "gagal", str(exc)))
        except Exception:
            await db.rollback()
            raise
    return redirect(_pesan_url("/retur", "pesan",
                               f"Retur {receipt.kode} sudah masuk stok."))
