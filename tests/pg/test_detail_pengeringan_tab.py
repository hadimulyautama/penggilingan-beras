"""Susunan baru mempertahankan sumber bacaan, aturan fase dan gudang efektif."""
import json
import os
from pathlib import Path
from urllib.parse import urlencode

import pytest
import pytest_asyncio
from sqlalchemy import select, func
from tests.pg.test_proses_aktif_detail import pengeringan, dryer_pabrik
from tests.pg.test_riwayat_pengeringan import _batch_basah
from tests.pg.test_riwayat_giling import _klien
from tests.pg.formulir import cap_formulir

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def dryer_tab(pg, pengeringan, dryer_pabrik):
    from app.models import User, PurchaseBatch
    from app.penggilingan.gudang1.services import drying as dr
    from tests.pg.test_bobot_belum_final import _tiket
    tambahan = await _batch_basah(pg, dryer_pabrik, 2000)
    async with pg() as db:
        u = await db.get(User, pengeringan['user'])
        await dr.add_batches_to_lot(db, user=u, kode_lot=pengeringan['kode'], kode_batch_list=[tambahan])
        batch = await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch == tambahan))
        batch.no_polisi_truk = 'B 4321 UJI'
        batch.timbangan_transaksi_id = await _tiket(db, 'TK-DR-TAB', nopol='B 4321 UJI',
                                                   t1=4000, netto=2000, kosong=2000, supplier_id=dryer_pabrik['pemasok'])
        await db.commit()
        for _ in range(20):
            await dr.log_moisture(db, user=u, kode_lot=pengeringan['kode'], sampel=[15, None, 17, 16], indikator=19)
    return {**pengeringan, 'tambahan': tambahan}


@pytest.mark.parametrize('peran', ['operator', 'admin', 'superadmin'])
async def test_tab_bacaan_paginasi_konteks_dan_izin(pg, dryer_tab, peran):
    kode = dryer_tab['kode']
    asal = '/pekerjaan?tab=berjalan&jenis=pengeringan&gudang=g1'
    async with await _klien(pg, peran=peran, gudang='Gudang 1') as c:
        url = '/proses-aktif/pengeringan/' + kode
        for tab in ['ringkasan', 'bahan', 'pengukuran', 'riwayat']:
            r = await c.get(url + '?' + urlencode({'tab_detail': tab, 'kembali_kerja': asal}))
            assert r.status_code == 200
            assert r.text.count('role="tab"') == 4
            assert f'aria-labelledby="tab-{tab}" >' in r.text
            for teks in [kode, dryer_tab['batch'], dryer_tab['tambahan'], 'TK-DR-TAB', 'B 4321 UJI',
                         '10.000 kg', '16,0%', '19,0%', 'Titik 3', 'Sebaran 2.0%', 'Mesin membaca +3.0%',
                         'Durasi efektif', 'Total jeda', 'Catatan pendinginan', 'Titik 1', 'Titik 2', 'Titik 3', 'Titik 4']:
                assert teks in r.text, teks
            assert 'kembali_kerja=' in r.text and 'buka=kadar_air' in r.text
            assert 'Peran contoh' not in r.text
        kedua = await c.get(url+'?halaman_ukur=2')
        assert 'aria-labelledby="tab-pengukuran" >' in kedua.text
        assert '16,0%' in kedua.text and '19,0%' in kedua.text and '21 catatan' in kedua.text
        buka = await c.get(url+'?buka=kadar_air&nilai='+kode)
        assert 'data-buka="kadar_air"' in buka.text and f'data-nilai="{kode}"' in buka.text
        if os.environ.get('UJI_POTRET_PENGERINGAN') and peran == 'admin':
            Path('/tmp/pengeringan-browser-session.json').write_text(json.dumps({
                'url': url, 'id': dryer_tab['id'], 'kode': kode, 'cookies': dict(c.cookies)}))
        from app.web.lihat_sebagai import NAMA_KUKI
        c.cookies.set(NAMA_KUKI, 'operator:g2')
        assert (await c.get(url)).status_code == 403
        from app.web import csrf
        c.headers[csrf.NAMA_HEADER] = cap_formulir(c)
        assert (await c.post('/api/actions/kadar-air', json={'kode_lot':kode, 'tes':[15]})).status_code == 403


async def test_indikator_penutupan_tidak_menghapus_tes_dan_putaran(pg, dryer_tab):
    from app.models import User, DryingLot, DryingMoistureLog, DryingCoolingLog, SiloStorage
    from app.penggilingan.gudang1.services import drying as dr
    kode = dryer_tab['kode']
    async with pg() as db:
        u = await db.get(User, dryer_tab['user'])
        tes = await db.scalar(select(DryingMoistureLog).where(DryingMoistureLog.drying_lot_id==dryer_tab['id']).order_by(DryingMoistureLog.waktu_update.desc()).limit(1))
        waktu_tes = tes.waktu_update
        # Tidak menambah kewajiban mencapai target13: mesin dimatikan pada18.
        await dr.finish_drying(db, user=u, kode_lot=kode, kadar_air_akhir=18)
        awal_catatan = await db.scalar(select(func.count()).select_from(DryingCoolingLog))
    async with await _klien(pg, peran='operator', gudang='Gudang 1') as c:
        transisi = await c.get('/proses-aktif/pengeringan/'+kode, headers={'X-Pindah':'1'})
        assert 'id="kabar"' in transisi.text and 'window.location.replace' in transisi.text
        r = await c.get('/proses-aktif/pengeringan/'+kode+'?tab_detail=pengukuran')
        assert '/pendinginan/' in r.url.path and 'Pendinginan' in r.text
        assert '16,0%' in r.text and '18,0%' in r.text and '21 catatan' not in r.text
        assert 'buka=kadar_air' not in r.text and 'buka=selesai_pendinginan' in r.text
        from app.services.proses_aktif import _waktu
        assert _waktu(waktu_tes) in r.text
        async with pg() as db:
            u = await db.get(User, dryer_tab['user'])
            await dr.finish_cooling(db, user=u, kode_lot=kode)
        final = await c.get('/proses-aktif/pendinginan/'+kode)
        assert final.url.path == '/riwayat-pengeringan/'+str(dryer_tab['id'])
        tindak_lanjut = await c.get('/pekerjaan')
        assert 'mulai_pendinginan_ulang' in tindak_lanjut.text and 'pindah_silo' in tindak_lanjut.text
        async with pg() as db:
            u = await db.get(User, dryer_tab['user'])
            await dr.mulai_pendinginan_ulang(db, user=u, kode_lot=kode)
            lot = await db.get(DryingLot, dryer_tab['id'])
            assert lot.waktu_selesai_pendinginan is None
            assert await db.scalar(select(func.count()).select_from(SiloStorage)) == 0
            assert await db.scalar(select(func.count()).select_from(DryingCoolingLog)) > awal_catatan
        ulang = await c.get('/proses-aktif/pendinginan/'+kode+'?tab_detail=riwayat')
        assert ulang.status_code == 200 and 'pendinginan ulang dimulai' in ulang.text
        assert 'buka=pindah_silo' not in ulang.text


async def test_format_lama_target_terpisah_audit_dan_data_kosong(pg, pengeringan):
    from app.models import DryingLot, DryingMoistureLog, ActivityLog, PurchaseBatch
    from app.services.setelan import target_kadar_air
    from app.penggilingan.gudang1.services.drying import kemajuan
    from sqlalchemy import delete
    async with await _klien(pg, peran='admin', gudang='Gudang 1') as c:
        from app.web import csrf
        c.headers[csrf.NAMA_HEADER] = cap_formulir(c)
        async with pg() as db:
            global_awal = await target_kadar_air(db)
            jumlah = await db.scalar(select(func.count()).select_from(DryingMoistureLog))
        r = await c.post('/api/actions/ubah-target', json={'kode_lot':pengeringan['kode'], 'target':14})
        assert r.status_code == 200
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(DryingMoistureLog)) == jumlah
            assert await target_kadar_air(db) == global_awal
            audit = await db.scalar(select(ActivityLog).where(ActivityLog.aksi=='ubah_target'))
            assert float(audit.old_value)==13 and float(audit.new_value)==14 and audit.changed_by
        # Kompatibilitas empat kolom serta bacaan mesin legacy tetap berjalan.
        r = await c.post('/api/actions/kadar-air', json={'kode_lot':pengeringan['kode'], 'tes_1':15, 'tes_3':17, 'indikator':19})
        assert r.status_code == 200
        r = await c.post('/api/actions/kadar-air', json={'kode_lot':pengeringan['kode'], 'kadar_air':18})
        assert r.status_code == 200
        async with pg() as db:
            logs = list((await db.scalars(select(DryingMoistureLog).order_by(DryingMoistureLog.id))).all())
            assert float(logs[-2].kadar_air_tes_manual)==16 and logs[-2].kadar_air_tes_2 is None
            assert logs[-1].kadar_air_tes_manual is None and float(logs[-1].kadar_air_indikator)==18
            lot = await db.get(DryingLot, pengeringan['id'])
            assert lot.status=='proses' and float(lot.target_kadar_air)==14
            # Kemajuan masih memakai helper lama; catatan mesin saja tidak mengubah alat tes terakhir.
            assert kemajuan(18,18,14)==0
            await db.execute(delete(DryingMoistureLog))
            b = await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch==pengeringan['batch']))
            b.berat_total_kg=None
            await db.commit()
        kosong = await c.get('/proses-aktif/pengeringan/'+pengeringan['kode'])
        assert 'Belum diukur' in kosong.text and 'Belum dapat dihitung' in kosong.text
        from app.penggilingan.gudang1.services.bobot import dari_batch
        async with pg() as db:
            b = await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch==pengeringan['batch']))
            assert dari_batch(b).teks() in kosong.text


async def test_jeda_pengeringan_aktual_pengukuran_dan_durasi(pg, pengeringan):
    from datetime import timedelta
    from app.database import now_local
    from app.models import User, DryingLot, JedaCatatan
    from app.penggilingan.gudang1.services import drying as dr, jeda as j
    from app.services.proses_aktif import rincian
    from app.services.berjalan import untuk_gudang1
    t = now_local()-timedelta(hours=4)
    async with pg() as db:
        u = await db.get(User, pengeringan['user'])
        lot = await db.get(DryingLot, pengeringan['id'])
        lot.waktu_mulai_pengeringan=t
        await db.commit()
        await j.hentikan(db,user=u,jenis='pengeringan',kode=lot.kode_lot,sebab='Listrik padam',
                        waktu_kejadian=t+timedelta(hours=1),alasan_terlambat='HP tidak terisi')
        await j.perbarui_kondisi(db,user=u,jenis='pengeringan',kode=lot.kode_lot,sebab='Mesin dryer rusak',
                               waktu_kejadian=t+timedelta(hours=2),alasan_terlambat='Sedang diperiksa',catatan='Motor diperiksa')
        await dr.log_moisture(db,user=u,kode_lot=lot.kode_lot,sampel=[14],indikator=17)
        assert await j.jeda_terbuka(db,'pengeringan',lot.id)
        await j.lanjutkan(db,user=u,jenis='pengeringan',kode=lot.kode_lot,
                         waktu_kejadian=t+timedelta(hours=3),alasan_terlambat='Baru tersambung')
        assert await j.tertahan_detik(db,'pengeringan',lot.id)==7200
        kartu=next(x for x in (await untuk_gudang1(db)).berjalan if x.kode==lot.kode_lot)
        detail=await rincian(db,jenis='pengeringan',model=lot,kartu=kartu,params={})
        assert any(k=='Total jeda' and '2 jam' in v for k,v in detail['fakta'])
        assert any(k=='Durasi efektif' and '2 jam' in v for k,v in detail['fakta'])
        logs=list((await db.scalars(select(JedaCatatan).order_by(JedaCatatan.id))).all())
        assert logs[0].dicatat_pada>logs[0].waktu_kejadian and logs[0].alasan_terlambat=='HP tidak terisi'
