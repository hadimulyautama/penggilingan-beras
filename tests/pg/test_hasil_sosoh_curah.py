"""Sisa 15 kg dan seluruh hasil boleh curah tanpa menggandakan stok/karung."""
import asyncio
import re

import pytest
from sqlalchemy import func, select

from app.database import now_local
from app.models import FinishedGoodsStock, PolishingOutputLog, PolishingProcess, User
from app.penggilingan.inventory import finished_goods as fg
from app.penggilingan.inventory.packaging import InventoryError, hitung_stok_kemasan
from app.services import berjalan, kemas_ulang, stok
from tests.pg.test_stok_produk_jasa import sosoh_jasa

pytestmark = pytest.mark.asyncio


async def siapkan(pg, g, *, jasa=False, jenis="medsuper", sisa=True):
    kode = g["kode_jasa"] if jasa else g["kode_pabrik"]
    async with pg() as db:
        proc = await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses == kode))
        log = await db.scalar(select(PolishingOutputLog).where(PolishingOutputLog.polishing_process_id == proc.id))
        log.jenis, log.berat_kg = jenis, 10065
        await db.commit()
        if sisa:
            kategori, mutu = stok.kategori_dan_mutu(jenis)
            await fg.catat_packing(db, user=await db.get(User, g["user"]), kode_pol=kode,
                kategori=kategori, grade=mutu, material_kode="biasa", ukuran=50, jumlah_karung=201)
    return kode


@pytest.mark.parametrize("jasa", [False, True])
@pytest.mark.parametrize("sisa", [False, True])
@pytest.mark.parametrize("jenis", ["medsuper", "beras_b"])
async def test_curah_menutup_pekerjaan_stok_dan_pemilik_utuh(pg, sosoh_jasa, jasa, sisa, jenis):
    g = sosoh_jasa
    kode = await siapkan(pg, g, jasa=jasa, sisa=sisa, jenis=jenis)
    owner = g["jasa_id"] if jasa else None
    async with pg() as db:
        kartu = next(b for b in await berjalan._kartu_beras_curah(db) if b.kode == kode)
        assert any(a[0] == "catat_curah" and a[3] == f"{kode}|{jenis}" for a in kartu.pilihan)
        sebelum = next(k for k in await stok.stok_produk(db, jasa_id=owner) if k.jenis == jenis)
        berat = await fg.catat_curah(db, user=await db.get(User, g["user"]), kode_pol=kode, jenis=jenis)
        assert berat == (15 if sisa else 10065)
        assert not any(b.kode == kode for b in await berjalan._kartu_beras_curah(db))
        sesudah = next(k for k in await stok.stok_produk(db, jasa_id=owner) if k.jenis == jenis)
        assert sesudah.sisa_kg == sebelum.sisa_kg == 10065
        assert sesudah.curah_kg == berat
        assert sesudah.kemasan_stok_kg == (10050 if sisa else 0)
        batch = await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.curah_kemas_ulang.is_(True)))
        assert batch.jasa_id == owner and batch.jumlah_karung == 0
        assert not batch.kemasan_mengurangi_stok
        assert (await fg.hitung_stok_finished_goods(db, batch.product_sku_id, batch.rice_quality_standard_id, jasa_id=owner))["kg"] == 0
        pilihan = await kemas_ulang.pilihan(db, batch.product_sku_id, batch.rice_quality_standard_id, owner, g["user"])
        assert pilihan[0]["curah"] and pilihan[0]["jumlah"] == berat
        lain = next((k for k in await stok.stok_produk(db, jasa_id=None if jasa else g["jasa_id"]) if k.jenis == jenis), None)
        assert lain is None or lain.sisa_kg == 0
        sku = await db.get(fg.ProductSku, batch.product_sku_id)
        assert await hitung_stok_kemasan(db, sku.packaging_material_id, sku.package_size_id) == 0


async def test_curah_bisa_dikemas_kemudian_tanpa_pekerjaan_ulang(pg, sosoh_jasa):
    kode = await siapkan(pg, sosoh_jasa)
    async with pg() as db:
        u = await db.get(User, sosoh_jasa["user"])
        await fg.catat_curah(db, user=u, kode_pol=kode, jenis="medsuper")
        batch = await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.curah_kemas_ulang.is_(True)))
        pilihan = (await kemas_ulang.pilihan(db, batch.product_sku_id, batch.rice_quality_standard_id, None, u.id))[0]
        from app.models import PackagingPurchase
        baru = await fg.find_or_create_sku(db, kategori="beras_putih", material_kode="biasa", ukuran=5)
        db.add(PackagingPurchase(kode="PKP-CURAH-UJI", packaging_material_id=baru.packaging_material_id,
            package_size_id=baru.package_size_id, jumlah_lembar=2, tanggal=now_local().date(), waktu=now_local(), input_by=u.id))
        await db.commit()
        await kemas_ulang.simpan(db, user=u, sumber_id=batch.id, kunci=pilihan["kunci"], jumlah_asal=10,
            material="biasa", ukuran=5, merk="", jumlah_baru=2)
        k = next(k for k in await stok.stok_produk(db) if k.jenis == "medsuper")
        assert (k.sisa_kg, k.curah_kg, k.kemasan_stok_kg) == (10065, 5, 10060)
        assert not any(b.kode == kode for b in await berjalan._kartu_beras_curah(db))


async def test_dua_operator_tidak_menggandakan_curah(pg, sosoh_jasa):
    kode = await siapkan(pg, sosoh_jasa)
    async def kirim():
        async with pg() as db:
            return await fg.catat_curah(db, user=await db.get(User, sosoh_jasa["user"]), kode_pol=kode, jenis="medsuper")
    hasil = await asyncio.gather(kirim(), kirim(), return_exceptions=True)
    assert sum(isinstance(r, InventoryError) for r in hasil) == 1
    assert 15 in hasil
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock).where(FinishedGoodsStock.curah_kemas_ulang.is_(True))) == 1


async def test_packing_dan_curah_bersamaan_memakai_saldo_sama(pg, sosoh_jasa):
    kode = await siapkan(pg, sosoh_jasa)
    async def curah():
        async with pg() as db:
            return await fg.catat_curah(db, user=await db.get(User, sosoh_jasa["user"]), kode_pol=kode, jenis="medsuper")
    async def packing():
        async with pg() as db:
            return await fg.catat_packing(db, user=await db.get(User, sosoh_jasa["user"]), kode_pol=kode,
                kategori="beras_putih", grade="medsuper", material_kode="biasa", ukuran=5, jumlah_karung=2)
    hasil = await asyncio.gather(curah(), packing(), return_exceptions=True)
    assert not any(isinstance(r, Exception) and not isinstance(r, InventoryError) for r in hasil)
    async with pg() as db:
        assert float(await db.scalar(select(func.sum(FinishedGoodsStock.berat_total_kg)))) == 10065
        assert not any(b.kode == kode for b in await berjalan._kartu_beras_curah(db))


async def test_hasil_baru_setelah_curah_tetap_menjadi_pekerjaan(pg, sosoh_jasa):
    kode = await siapkan(pg, sosoh_jasa)
    async with pg() as db:
        u = await db.get(User, sosoh_jasa["user"])
        p = await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses == kode))
        p.status, p.waktu_selesai = "proses", None
        await db.commit()
        await fg.catat_curah(db, user=u, kode_pol=kode, jenis="medsuper")
        db.add(PolishingOutputLog(polishing_process_id=p.id, jenis="medsuper", berat_kg=25,
            waktu_update=now_local(), input_by=u.id))
        await db.commit()
        sisa = next(b for b in await stok.beras_curah(db) if b.kode_proses == kode)
        assert sisa.sisa_kg == 25 and sisa.berjalan
        with pytest.raises(InventoryError):
            await fg.catat_packing(db, user=u, kode_pol=kode, kategori="beras_putih", grade="medsuper",
                material_kode="biasa", ukuran=50, jumlah_karung=1)


async def test_tombol_halaman_formulir_dan_post(pg, sosoh_jasa):
    from tests.pg.test_barang_keluar import _klien
    from hmu_identitas.peran import SUPERADMIN
    kode = await siapkan(pg, sosoh_jasa)
    async with pg() as db:
        u = await db.get(User, sosoh_jasa["user"])
        u.role = SUPERADMIN
        await db.commit()
    c = await _klien(pg, sosoh_jasa["user"], "curah-sosoh")
    async with c:
        halaman = await c.get("/pekerjaan")
        assert halaman.status_code == 200
        assert "Jadikan curah" in halaman.text and "buka=catat_curah" in halaman.text
        token = re.search(r'id="formulir-sesi"[^>]*data-token="([^"]+)"', halaman.text).group(1)
        menu = await c.get("/api/actions/menu")
        assert menu.status_code == 200
        # Katalog memuat spesifikasi untuk lembar yang dibuka dari kartu.
        assert '"id":"catat_curah"' in menu.text
        opsi = next(a for a in menu.json() if a["id"] == "catat_curah")
        pilihan = await c.get(opsi["fields"][0]["source"])
        sumber = next(b for b in pilihan.json() if b["value"] == f"{kode}|medsuper")
        assert sumber["berat_kg"] == 15
        assert opsi.get("kartu") is True
        respons = await c.post("/api/actions/catat-curah", json={"sumber": f"{kode}|medsuper"}, headers={"x-csrf-token": token})
        assert respons.status_code == 200, respons.text
        assert "15 kg" in respons.json()["pesan"]
        assert kode not in (await c.get("/pekerjaan")).text
        detail = await c.get("/stok-produk/detail?jenis=medsuper")
        assert detail.status_code == 200 and "Curah tercatat" in detail.text
        assert "Kemas ulang" in detail.text


@pytest.mark.parametrize("gudang", ["g1", "g2"])
async def test_izin_operator_dijaga_di_post(pg, sosoh_jasa, gudang):
    from app.models import Warehouse
    from tests.pg.test_barang_keluar import _klien
    kode = await siapkan(pg, sosoh_jasa)
    async with pg() as db:
        u = await db.get(User, sosoh_jasa["user"])
        u.default_warehouse_id = await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi == gudang))
        await db.commit()
    c = await _klien(pg, sosoh_jasa["user"], "curah-operator", mode="operator")
    async with c:
        halaman = await c.get("/pekerjaan")
        assert halaman.status_code == 200
        token = re.search(r'id="formulir-sesi"[^>]*data-token="([^"]+)"', halaman.text).group(1)
        respons = await c.post("/api/actions/catat-curah", json={"sumber": f"{kode}|medsuper"}, headers={"x-csrf-token": token})
        assert respons.status_code == (200 if gudang == "g2" else 403), respons.text[-500:]
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock).where(FinishedGoodsStock.curah_kemas_ulang.is_(True))) == (1 if gudang == "g2" else 0)


@pytest.mark.parametrize("jenis", ["broken", "bekatul", "asing", "premium"])
async def test_jenis_tanpa_saldo_ditolak_tanpa_menulis(pg, sosoh_jasa, jenis):
    async with pg() as db:
        with pytest.raises(InventoryError):
            await fg.catat_curah(db, user=await db.get(User, sosoh_jasa["user"]), kode_pol=sosoh_jasa["kode_pabrik"], jenis=jenis)
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock)) == 0
