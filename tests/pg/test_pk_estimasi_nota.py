"""Nota PK dipakai sementara; W dan bobot per karung aktual dari timbang kedua."""
from decimal import Decimal
from functools import partial

import pytest
from sqlalchemy import select, text

from app.models import User, PkPurchaseBatch, PkTumpukanToSilo
from app.penggilingan.gudang1.services.bobot import dari_batch
from app.penggilingan.gudang1.services.timbang_link import (
    sinkron_perkiraan, sinkron_bobot_menunggu, resinkron_bobot_berubah)
from app.penggilingan.gudang2 import service as g2
from app.penggilingan.gudang2.karung import bobot_per_karung
from app.services import berjalan
from app.services.masuk_detail_timbang import baca
from tests.pg.test_masuk_detail_timbang import contoh, sidik
from tests.pg.test_penerimaan_pk_belum_bobot import penerimaan

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('nota,harapan', [(0, 10000), (Decimal('9900'), 9900)])
async def test_penerimaan_baru_memakai_estimasi_nota_lalu_bobot_real(pg, contoh, nota, harapan):
    x = contoh
    async with pg() as db:
        await db.execute(text("UPDATE timbangan_transaksi SET jenis_kode='BERAS_PK', berat_acuan_kg=:nota WHERE id=:id"), dict(nota=nota, id=x['tid']))
        await db.commit()
        u = await db.get(User, x['uid'])
        b = (await g2.create_pk_purchase_dari_timbang(db, user=u,
            timbangan_transaksi_id=x['tid'], jenis_pk='ks', jumlah_karung=125,
            ukuran_karung_kg=Decimal('80'))).batch
        assert b.berat_total_kg == harapan and b.sumber_berat == 'perkiraan'
        assert b.berat_perkiraan_kg == harapan and not dari_batch(b).pasti
        assert 'estimasi nota' in dari_batch(b).teks()
        it = (await g2.masukkan_pk_luar(db, user=u, kode=b.kode_batch)).intake
        move = await g2.pindah_tumpukan_ke_silo(db, user=u, intake_id=it.id,
                                              nama_silo='B', jumlah_karung=125)
        assert not move.bobot_final and move.berat_kg == harapan
        assert await g2._sisa_tumpukan_intake(db, it.id) == 0
        sila = await g2.get_g2_silo(db, 'B')
        cards = await berjalan._kartu_silo_g2(db, partial(berjalan._isian_silo, db))
        card = next(c for c in cards if c.kode == 'Silo B')
        assert card.utama[0].startswith('± ')
        assert 'Bobot estimasi' in card.nota and 'timbang kedua' in card.nota
        data = await baca(db, x['tid'], u)
        assert data['catatan'][0]['sementara']
        assert any('estimasi, menunggu timbang kedua' in s for s in data['catatan'][0]['lokasi'])
        events = await db.scalar(text('SELECT count(*) FROM peristiwa'))
        # Nota 10.000 tidak boleh menggantikan barang nyata 9.875, termasuk
        # ketika selisihnya kecil. Netto tidak mencakup pengurangan tara lain.
        await db.execute(text("""UPDATE timbangan_transaksi SET timbang2_kg=5000,
            timbang2_waktu=NOW(),netto_timbangan_kg=10000,berat_barang_kg=9875,
            status_tiket='SELESAI' WHERE id=:id"""), dict(id=x['tid']))
        await db.commit()
        await sinkron_perkiraan(db)
        await sinkron_bobot_menunggu(db)
        await g2.resinkron_intake_g2(db)
        await db.refresh(b)
        await db.refresh(it)
        assert b.berat_total_kg == 9875 and b.sumber_berat == 'timbangan'
        assert dari_batch(b).pasti and it.bobot_final
        assert bobot_per_karung(b) == 79
        m = await db.scalar(select(PkTumpukanToSilo).where(PkTumpukanToSilo.pk_gudang2_intake_id == it.id))
        assert m.jumlah_karung == 125 and m.berat_kg == 9875 and m.berat_timbang_kg is None
        assert await g2.hitung_stok_silo(db, sila.id) == 9875
        assert await g2._sisa_tumpukan_intake(db, it.id) == 0
        assert await db.scalar(text('SELECT count(*) FROM peristiwa')) == events
        cards = await berjalan._kartu_silo_g2(db, partial(berjalan._isian_silo, db))
        card = next(c for c in cards if c.kode == 'Silo B')
        assert not card.utama[0].startswith('± ') and 'Bobot estimasi' not in (card.nota or '')
        await db.execute(text('UPDATE timbangan_transaksi SET berat_barang_kg=9750 WHERE id=:id'), dict(id=x['tid']))
        await db.commit()
        await resinkron_bobot_berubah(db)
        await db.refresh(b)
        assert b.berat_total_kg == 9750 and bobot_per_karung(b) == 78
        assert await g2.hitung_stok_silo(db, sila.id) == 9750


async def test_sinkron_penerimaan_sudah_ada_dan_sudah_ke_silo_tidak_menduplikasi(pg, penerimaan):
    x = penerimaan
    async with pg() as db:
        old_events = await db.scalar(text('SELECT count(*) FROM peristiwa'))
        old_moves = await db.scalar(select(text('count(*)')).select_from(PkTumpukanToSilo))
        assert await sinkron_perkiraan(db) == 1
        b = await db.get(PkPurchaseBatch, x['bid'])
        assert b.berat_total_kg == 10000 and b.sumber_berat == 'perkiraan'
        assert not dari_batch(b).pasti
        assert await g2.hitung_stok_silo(db, x['silo']) == 10000
        assert await sinkron_perkiraan(db) == 0
        assert await db.scalar(text('SELECT count(*) FROM peristiwa')) == old_events
        assert await db.scalar(select(text('count(*)')).select_from(PkTumpukanToSilo)) == old_moves


@pytest.mark.parametrize('tiket_status,batch_status', [('BATAL', 'menunggu'), ('TERBUKA', 'manual')])
async def test_estimasi_tidak_menimpa_tiket_batal_atau_bobot_pasti(pg, penerimaan, tiket_status, batch_status):
    x = penerimaan
    async with pg() as db:
        await db.execute(text('UPDATE timbangan_transaksi SET status_tiket=:s WHERE id=:id'), dict(s=tiket_status,id=x['tid']))
        if tiket_status == 'BATAL':
            await db.execute(text("UPDATE timbangan_transaksi SET status_transaksi='BATAL' WHERE id=:id"), dict(id=x['tid']))
        b = await db.get(PkPurchaseBatch, x['bid'])
        b.sumber_berat = batch_status
        if batch_status == 'manual':
            b.berat_total_kg = 9600
        await db.commit()
        sebelum = await sidik(db)
        assert await sinkron_perkiraan(db) == 0
        assert await sidik(db) == sebelum
