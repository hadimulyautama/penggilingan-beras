"""PK berkarung boleh diterima dan dipindah sebelum timbang kedua selesai."""
from decimal import Decimal

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from sqlalchemy import select

from app.models import PkPurchaseBatch, Silo, User, Warehouse
from app.penggilingan.gudang2 import service as g2
from app.services.masuk_detail_timbang import baca
from app.web import internal
from hmu_identitas import peran as P
from tests.pg.test_masuk_detail_timbang import contoh, catat, sidik
from tests.pg.test_riwayat_giling import _klien

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def penerimaan(pg, contoh):
    async with pg() as db:
        b = await catat(db, contoh, 'BERAS_PK', berat=None, status='diterima', sumber='menunggu')
        b.jumlah_karung = 125
        b.ukuran_karung_kg = 80
        b.jenis_pk = 'ks'
        wid = await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi == 'g2'))
        silo = await db.scalar(select(Silo).where(Silo.nama_silo == 'Silo B', Silo.warehouse_id == wid))
        if silo is None:
            silo = Silo(nama_silo='Silo B', warehouse_id=wid)
            db.add(silo)
        await db.commit()
        user = await db.get(User, contoh['uid'])
        it = (await g2.masukkan_pk_luar(db, user=user, kode=b.kode_batch)).intake
        move = await g2.pindah_tumpukan_ke_silo(db, user=user, intake_id=it.id,
                                              nama_silo='B', jumlah_karung=125)
        assert move.berat_kg is None
        assert await g2._sisa_tumpukan_intake(db, it.id) == 0
        return {**contoh, 'bid': b.id, 'silo': silo.id, 'kode_pindah': move.kode_pindah}


async def test_api_detail_timbang_menyebut_karung_dan_lokasi_tanpa_kg_palsu(pg, penerimaan, monkeypatch):
    x = penerimaan
    async with pg() as db:
        sebelum = await sidik(db)
        data = await baca(db, x['tid'], await db.get(User, x['uid']))
        assert data['status'] == 'tercatat' and data['berat_diterima_kg'] is None
        assert data['catatan'][0]['sementara']
        assert f"{x['kode_pindah']} · 125 karung · Bobot belum tersedia ke Silo B" in data['catatan'][0]['lokasi']
        assert '10000' not in str(data['catatan'][0]['lokasi'])
    monkeypatch.setattr(internal.settings, 'internal_api_token', 'token-uji')
    app = FastAPI()
    app.include_router(internal.router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://uji') as c:
        r = await c.get(f"/internal/masuk/tiket/{x['tid']}/detail",
                       headers={'X-Internal-Token': 'token-uji', 'X-Operator-Akun': str(x['aid'])})
        assert r.status_code == 200, r.text
        assert r.json() == data
    async with pg() as db:
        assert await sidik(db) == sebelum


@pytest.mark.parametrize('peran,gudang', [(P.OPERATOR, 'Gudang 2'), (P.ADMIN, None), (P.SUPERADMIN, None)])
async def test_daftar_dan_detail_pk_terbuka_untuk_semua_peran_berwenang(pg, penerimaan, peran, gudang):
    x = penerimaan
    async with await _klien(pg, peran=peran, gudang=gudang) as c:
        async with pg() as db:
            sebelum = await sidik(db)
        daftar = await c.get('/barang-masuk?status=diterima')
        assert daftar.status_code == 200, daftar.text[:300]
        r = await c.get(f"/barang-masuk/{x['tid']}")
        assert r.status_code == 200, r.text[:300]
        assert '125 karung' in r.text and 'Bobot belum tersedia' in r.text and 'Silo B' in r.text
        async with pg() as db:
            assert await sidik(db) == sebelum


@pytest.mark.parametrize('berat', [Decimal('9875'), Decimal('0')])
async def test_bobot_terkini_dibaca_tanpa_memakai_nominal_surat_jalan(pg, penerimaan, berat):
    x = penerimaan
    async with pg() as db:
        b = await db.get(PkPurchaseBatch, x['bid'])
        b.berat_total_kg = berat
        b.sumber_berat = 'timbangan'
        await db.commit()
        sebelum = await sidik(db)
        data = await baca(db, x['tid'], await db.get(User, x['uid']))
        assert Decimal(data['berat_diterima_kg']) == berat
        assert any(f'{berat:g} kg ke Silo B' in lokasi for lokasi in data['catatan'][0]['lokasi'])
        assert not any('Bobot belum tersedia' in lokasi for lokasi in data['catatan'][0]['lokasi'])
        assert await g2.hitung_stok_silo(db, x['silo']) == berat
        assert await sidik(db) == sebelum
