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


async def _siapkan(db, sebelum: int | None = None):
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
    katalog = await layanan_retur.katalog(db)
    mutu = (await db.scalars(select(RiceQualityStandard).where(
        RiceQualityStandard.aktif.is_(True)).order_by(RiceQualityStandard.urutan))).all()
    recent = (await db.execute(text("""
        SELECT r.id, r.kode, r.kode_tiket, r.nama_pelanggan, r.nomor_polisi,
               r.berat_tiket_kg, r.berat_rincian_kg,
               (r.berat_tiket_kg - r.berat_rincian_kg) AS selisih_kg, r.waktu,
               COUNT(i.id) AS jumlah_jenis
        FROM customer_returns r LEFT JOIN customer_return_items i
          ON i.customer_return_id = r.id
        WHERE (CAST(:sebelum AS INTEGER) IS NULL OR r.id < :sebelum)
        GROUP BY r.id ORDER BY r.id DESC LIMIT 51
    """), {"sebelum": sebelum})).mappings().all()
    return tickets, katalog, mutu, recent


@router.get("/retur")
async def halaman_retur(request: Request, akun=Depends(butuh_akun),
                         sebelum: int | None = None):
    if not _boleh(akun):
        raise HTTPException(403, "Penerimaan retur hanya tersedia untuk Admin.")
    async with SessionLocal() as db:
        tickets, katalog, mutu, recent = await _siapkan(db, sebelum)
    return await render_laci(request, "retur.html", layar="retur",
                              tickets=tickets, katalog=katalog, mutu=mutu,
                              recent=recent[:50],
                              sebelum_berikut=recent[49]["id"] if len(recent) > 50 else None,
                              pesan=request.query_params.get("pesan"),
                              gagal=request.query_params.get("gagal"),
                              tiket_terpilih=request.query_params.get("tiket", ""))


@router.get("/retur/{retur_id}")
async def detail_retur(retur_id: int, request: Request, akun=Depends(butuh_akun)):
    if not _boleh(akun):
        raise HTTPException(403, "Penerimaan retur hanya tersedia untuk Admin.")
    from app.models import User, Warehouse

    async with SessionLocal() as db:
        retur = await db.get(CustomerReturn, retur_id)
        if retur is None:
            raise HTTPException(404, "Penerimaan retur tidak ditemukan.")
        penerima = await db.get(User, retur.input_by)
        gudang = await db.get(Warehouse, retur.warehouse_id) if retur.warehouse_id else None
        items = (await db.execute(text("""
            SELECT i.*, s.kategori, m.nama AS kemasan, z.ukuran_kg,
                   b.nama AS merek, q.kode AS mutu
            FROM customer_return_items i
            JOIN product_skus s ON s.id=i.product_sku_id
            JOIN packaging_materials m ON m.id=s.packaging_material_id
            JOIN package_sizes z ON z.id=s.package_size_id
            LEFT JOIN brands b ON b.id=s.brand_id
            LEFT JOIN rice_quality_standards q ON q.id=i.rice_quality_standard_id
            WHERE i.customer_return_id=:id ORDER BY i.id
        """), {"id": retur.id})).mappings().all()
        tiket = (await db.execute(text("""
            SELECT kode,arah,status_tiket,status_transaksi,nomor_polisi,nama_sopir,
                   timbang1_kg,timbang2_kg,timbang1_waktu,timbang2_waktu,
                   netto_timbangan_kg,berat_barang_kg
            FROM timbangan_transaksi WHERE id=:id
        """), {"id": retur.timbangan_transaksi_id})).mappings().first()
        # Nama saat barang diterima tetap dipakai jika master produk berganti.
        rincian = await db.scalar(select(ReturRincian).where(
            ReturRincian.timbangan_transaksi_id == retur.timbangan_transaksi_id))
        nama_snapshot = {(m.get("sku_id"), m.get("quality_id")): m.get("nama")
                         for m in ((rincian.muatan or []) if rincian else [])}
        items = [dict(i, nama=nama_snapshot.get((i["product_sku_id"],
                                               i["rice_quality_standard_id"]))) for i in items]
    return await render_laci(request, "retur_detail.html", layar="retur",
                             retur=retur, items=items, tiket=tiket,
                             penerima=penerima.nama if penerima else "—",
                             gudang=gudang.nama_gudang if gudang else "—")


@router.post("/retur/terima")
async def terima_retur(request: Request, akun=Depends(butuh_akun)):
    if not _boleh(akun):
        raise HTTPException(403, "Penerimaan retur hanya tersedia untuk Admin.")
    form = await request.form()
    try:
        ticket_id = int(form.get("timbangan_transaksi_id", ""))
        sku_ids = form.getlist("sku_id")  # Halaman lama tetap diterima.
        jenis = form.getlist('jenis_barang')
        kemasan = form.getlist('kemasan')
        brands = form.getlist('brand_id')
        baru = bool(jenis)
        if baru:
            if not len(jenis) == len(kemasan) == len(brands):
                raise ValueError('Pilihan jenis, kemasan, dan merek belum lengkap.')
            sku_ids = list(zip(jenis, kemasan, brands))
        quality_ids = form.getlist("quality_id")
        bag_counts = form.getlist("jumlah_karung")
        notes = form.getlist("catatan_item")
        aksi = form.get("aksi", "terima")
        if aksi not in ("rincian", "terima"):
            raise ValueError("Aksi retur tidak dikenal.")
        if not (len(sku_ids) == len(quality_ids) == len(bag_counts) == len(notes)):
            raise ValueError("Rincian barang tidak lengkap. Muat ulang halaman dan isi kembali.")
        rows = []
        for idx, sku_raw in enumerate(sku_ids):
            if not sku_raw:
                continue
            sku_id = sku_raw if baru else int(sku_raw)
            count = int(bag_counts[idx] or 0)
            weight = Decimal('0')  # Dihitung dari ukuran SKU di server setelah validasi pilihan.
            tara = Decimal('0')  # Retur tidak dipotong tara, termasuk kiriman halaman lama.
            quality_id = int(quality_ids[idx]) if quality_ids[idx] else None
            if count < 1:
                raise ValueError("Setiap baris harus memiliki jumlah karung lebih dari nol.")
            rows.append((sku_id, quality_id, count, weight, (notes[idx] or "").strip() or None, tara))
        if not rows:
            raise ValueError("Tambahkan minimal satu jenis barang retur.")
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

            if baru:
                rows = [(await layanan_retur.pilih_sku(db, *spec), quality, count, weight, note, tara)
                        for spec, quality, count, weight, note, tara in rows]
            muatan = await layanan_retur.siapkan_muatan(db, rows)
            # Nilai kiriman peramban tidak menjadi otoritas berat nominal.
            # Stok, snapshot rincian, dan pembanding memakai hasil yang sama.
            rows = [(m['sku_id'], m['quality_id'], m['jumlah_karung'],
                     Decimal(m['berat_kg']), m['catatan_item'] or None, Decimal('0')) for m in muatan]
            total = sum((row[3] for row in rows), Decimal('0'))
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
            difference = ticket_weight - total
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
