"""Curah tercatat masuk silo tanpa dikemas, tanpa stok ganda, dan bisa dibatalkan."""
import asyncio
from html import unescape
import re

import pytest
from sqlalchemy import func, select

from app.models import ActivityLog, BerasKeSilo, FinishedGoodsStock, Silo, User
from app.penggilingan.gudang2.service import (
    Gudang2Error, hitung_stok_silo, masukkan_beras_ke_silo)
from app.penggilingan.inventory import finished_goods as fg
from app.services import kemas_ulang, stok
from app.services.undo import undo_last
from hmu_identitas.peran import SUPERADMIN
from tests.pg.test_barang_keluar import _klien
from tests.pg.test_hasil_sosoh_curah import siapkan
from tests.pg.test_stok_produk_jasa import sosoh_jasa

pytestmark = pytest.mark.asyncio


async def _curah(pg, g, *, jasa=False, jenis="medsuper"):
    kode = await siapkan(pg, g, jasa=jasa, jenis=jenis, sisa=False)
    async with pg() as db:
        u = await db.get(User, g["user"])
        u.role = SUPERADMIN
        db.add(Silo(nama_silo='Silo Curah Uji', warehouse_id=u.default_warehouse_id,
                    jenis_isi='beras'))
        await db.commit()
        await fg.catat_curah(db, user=u, kode_pol=kode, jenis=jenis)
        row = await db.scalar(select(FinishedGoodsStock).where(
            FinishedGoodsStock.curah_kemas_ulang.is_(True)))
        return row.id


@pytest.mark.parametrize("jasa", [False, True])
@pytest.mark.parametrize("jenis", ["medsuper", "beras_b"])
async def test_tombol_picker_post_dan_undo_curah_tanpa_kemasan(pg, sosoh_jasa, jasa, jenis):
    g = sosoh_jasa
    rid = await _curah(pg, g, jasa=jasa, jenis=jenis)
    owner = g["jasa_id"] if jasa else None
    sumber = f"curah:{rid}|{owner if jasa else 'pabrik'}"
    scope = "jasa" if jasa else "pabrik"
    path = (f'/stok-produk-jasa/detail?jenis={jenis}&pelanggan_id={g["pelanggan_id"]}'
            if jasa else f'/stok-produk/detail?jenis={jenis}')
    async with await _klien(pg, g["user"], "curah-silo") as c:
        page = await c.get(path)
        assert page.status_code == 200
        row_html = next(r for r in page.text.split('</tr>')
                        if 'data-bentuk-stok="Curah tercatat"' in r)
        assert f'data-masuk-silo="{sumber}"' in row_html
        href = unescape(re.search(r'href="([^"]+)" data-masuk-silo=', row_html).group(1))
        form = await c.get(href)
        assert f'data-sumber-stok="{sumber}"' in form.text
        token = re.search(r'id="formulir-sesi"[^>]*data-token="([^"]+)"', form.text).group(1)
        options = (await c.get('/api/actions/beras-sumber-tersedia',
                               params={'induk': f'{jenis}|{scope}'})).json()
        assert any(o['value'] == sumber for o in options)
        for kg in (10.25, 10054.75):
            response = await c.post('/api/actions/masukkan-beras-silo',
                json=dict(jenis=f'{jenis}|{scope}', sumber_stok=sumber, silo='Curah Uji', berat_kg=kg),
                headers={'x-csrf-token': token})
            assert response.status_code == 200, response.text
            async with pg() as db:
                row = await db.get(FinishedGoodsStock, rid)
                card = next(k for k in await stok.stok_produk(db, jasa_id=owner) if k.jenis == jenis)
                assert card.sisa_kg == card.curah_kg == float(row.berat_total_kg)
                assert row.jumlah_karung == 0 and row.curah_kemas_ulang
                assert card.kemasan_stok_kg == 0
                assert not any(b.jenis == jenis for b in await stok.beras_curah(db))
        options = (await c.get('/api/actions/beras-sumber-tersedia',
                               params={'induk': f'{jenis}|{scope}'})).json()
        assert not any(o['value'] == sumber for o in options)
    async with pg() as db:
        moves = (await db.scalars(select(BerasKeSilo))).all()
        assert sum(float(m.berat_kg) for m in moves) == 10065
        assert all(m.jasa_id == owner for m in moves)
        assert await hitung_stok_silo(db, moves[0].silo_id) == 10065
        logs = (await db.scalars(select(ActivityLog).where(
            ActivityLog.aksi == 'beras_masuk_silo').order_by(ActivityLog.id.desc()))).all()
        for log in logs:
            await undo_last(db, actor=await db.get(User, g['user']), cakupan=None, log_id=log.id)
        row = await db.get(FinishedGoodsStock, rid)
        await db.refresh(row)
        assert float(row.berat_total_kg) == 10065 and row.curah_kemas_ulang
        assert row.jumlah_karung == 0 and row.jasa_id == owner
        card = next(k for k in await stok.stok_produk(db, jasa_id=owner) if k.jenis == jenis)
        assert card.sisa_kg == card.curah_kg == 10065
        assert await db.scalar(select(func.count()).select_from(BerasKeSilo)) == 0


@pytest.mark.parametrize('ubah', [{'jasa_id': 999999}, {'jenis': 'medium'}, {'berat_kg': 10066}])
async def test_sumber_curah_salah_pemilik_mutu_atau_melebihi_saldo_ditolak(pg, sosoh_jasa, ubah):
    rid = await _curah(pg, sosoh_jasa)
    async with pg() as db:
        with pytest.raises(Gudang2Error):
            await masukkan_beras_ke_silo(db, user=await db.get(User, sosoh_jasa['user']),
                **(dict(jenis='medsuper', sumber_stok=f'curah:{rid}', nama_silo='Curah Uji',
                        berat_kg=10) | ubah))
        await db.rollback()
        assert float((await db.get(FinishedGoodsStock, rid)).berat_total_kg) == 10065
        assert await db.scalar(select(func.count()).select_from(BerasKeSilo)) == 0


async def test_sisa_kemas_ulang_bisa_langsung_ke_silo_tanpa_mengusik_karung(pg, sosoh_jasa):
    from tests.pg.test_kemas_ulang import awal
    req, _, _ = await awal(pg, sosoh_jasa)
    async with pg() as db:
        u = await db.get(User, sosoh_jasa['user'])
        await kemas_ulang.simpan(db, user=u, **req)
        row = await db.scalar(select(FinishedGoodsStock).where(
            FinishedGoodsStock.curah_kemas_ulang.is_(True)))
        assert float(row.berat_total_kg) == 20
        result = await masukkan_beras_ke_silo(db, user=u, jenis='medium',
            sumber_stok=f'curah:{row.id}', nama_silo='A', berat_kg=15)
        assert result.dibongkar_dari_karung_kg == 0
        card = next(k for k in await stok.stok_produk(db) if k.jenis == 'medium')
        assert (card.sisa_kg, card.kemasan_stok_kg, card.curah_kg) == (8985, 180, 8805)
        assert float(row.berat_total_kg) == 5
        assert sum(b.sisa_kg for b in await stok.beras_curah(db) if b.jenis == 'medium'
                   and b.jasa_id is None) == 8800


async def test_dua_operator_tidak_memindah_curah_yang_sama_dua_kali(pg, sosoh_jasa):
    rid = await _curah(pg, sosoh_jasa)
    async def kirim():
        async with pg() as db:
            return await masukkan_beras_ke_silo(db, user=await db.get(User, sosoh_jasa['user']),
                jenis='medsuper', sumber_stok=f'curah:{rid}', nama_silo='Curah Uji', berat_kg=6000)
    hasil = await asyncio.gather(kirim(), kirim(), return_exceptions=True)
    assert sum(isinstance(r, Gudang2Error) for r in hasil) == 1, hasil
    async with pg() as db:
        assert float((await db.get(FinishedGoodsStock, rid)).berat_total_kg) == 4065
        assert await db.scalar(select(func.sum(BerasKeSilo.berat_kg))) == 6000


async def test_kemas_dan_silo_bersamaan_tidak_memakai_curah_yang_sama(pg, sosoh_jasa):
    from app.penggilingan.inventory.packaging import InventoryError
    from tests.pg.test_kemas_ulang import awal
    req, _, _ = await awal(pg, sosoh_jasa)
    async with pg() as db:
        u = await db.get(User, sosoh_jasa['user'])
        await kemas_ulang.simpan(db, user=u, **req)
        row = await db.scalar(select(FinishedGoodsStock).where(
            FinishedGoodsStock.curah_kemas_ulang.is_(True)))
        rid = row.id
        opsi = next(o for o in await kemas_ulang.pilihan(db, row.product_sku_id,
            row.rice_quality_standard_id, None, u.id) if o['id'] == rid)
    async def pindah():
        async with pg() as db:
            return await masukkan_beras_ke_silo(db, user=await db.get(User, sosoh_jasa['user']),
                jenis='medium', sumber_stok=f'curah:{rid}', nama_silo='A', berat_kg=15)
    async def kemas():
        async with pg() as db:
            return await kemas_ulang.simpan(db, user=await db.get(User, sosoh_jasa['user']),
                **(req | dict(sumber_id=rid, kunci=opsi['kunci'], jumlah_asal=15,
                              ukuran=5, jumlah_baru=3)))
    hasil = await asyncio.gather(pindah(), kemas(), return_exceptions=True)
    assert sum(isinstance(r, (Gudang2Error, InventoryError)) for r in hasil) == 1, hasil
    async with pg() as db:
        assert float((await db.get(FinishedGoodsStock, rid)).berat_total_kg) == 5
        fg_kg = await db.scalar(select(func.sum(FinishedGoodsStock.berat_total_kg)))
        silo_kg = await db.scalar(select(func.coalesce(func.sum(BerasKeSilo.berat_kg), 0)))
        assert fg_kg + silo_kg == 200
