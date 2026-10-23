"""Jumlah, isi alat, pemetaan tungku, dan batas gudang pada Beranda nyata."""
from datetime import date
from pathlib import Path
import pytest
from sqlalchemy import select
from app.models import Dryer, Silo, Warehouse, User, PurchaseBatch, SiloStorage
from app.database import now_local
from app.services import alur_beranda as svc
from tests.pg.test_proses_aktif_detail import pengeringan, dryer_pabrik
from tests.pg.test_riwayat_pengeringan import _batch_basah
from tests.pg.test_riwayat_giling import _klien

pytestmark = pytest.mark.asyncio


async def test_dryer_kosong_menunggu_mengering_pendinginan_dan_dingin(pg, dryer_pabrik):
    from app.penggilingan.gudang1.services import drying
    async with pg() as db:
        dryers = await svc.daftar_dryer(db)
        assert len(dryers) == 1 and not dryers[0]['dryers'][0]['terisi']
    kode = await _batch_basah(pg, dryer_pabrik, 8000)
    async with pg() as db:
        u = await db.get(User, dryer_pabrik['user'])
        await drying.masuk_dryer(db, user=u, kode_batch_list=[kode])
        d = (await svc.daftar_dryer(db))[0]['dryers'][0]
        assert d['terisi'] and d['proses'] == 'Menunggu mulai'
        lot = (await drying.start_drying(db, user=u, target_kadar_air=13)).lot
        d = (await svc.daftar_dryer(db))[0]['dryers'][0]
        assert d['terisi'] and d['mode'] == 'mengeringkan'
        await drying.finish_drying(db, user=u, kode_lot=lot.kode_lot, kadar_air_akhir=13)
        d = (await svc.daftar_dryer(db))[0]['dryers'][0]
        assert d['terisi'] and d['mode'] == 'pendinginan'
        await drying.finish_cooling(db, user=u, kode_lot=lot.kode_lot)
        d = (await svc.daftar_dryer(db))[0]['dryers'][0]
        assert d['terisi'] and d['proses'] == 'Dingin · menunggu keluar'
        # Baru setelah dipindah ke silo, dryer benar-benar kosong.
        from app.penggilingan.gudang1.services import silo
        s = (await silo.silos_g1(db))[0]
        await silo.masuk_silo(db, user=u, kode_lot=lot.kode_lot, kode_batch=None, nama_silo=s.nama_silo)
        d = (await svc.daftar_dryer(db))[0]['dryers'][0]
        assert not d['terisi']


@pytest.mark.parametrize('jumlah', [1, 2, 4])
async def test_jumlah_silo_dan_dryer_tidak_ditanam_di_kode(pg, pemakai, jumlah):
    async with pg() as db:
        w1 = Warehouse(nama_gudang='Gudang 1', kode_fungsi='g1', aktif=True)
        w2 = Warehouse(nama_gudang='Gudang 2', kode_fungsi='g2', aktif=True)
        db.add_all([w1, w2]); await db.flush()
        for i in range(jumlah):
            db.add_all([Silo(warehouse_id=w1.id, nama_silo=f'Silo {i}', aktif=True),
                        Silo(warehouse_id=w2.id, nama_silo=f'Silo {i}', aktif=True),
                        Dryer(warehouse_id=w1.id, nama=f'Dryer {i}', kapasitas_kg=30000)])
        db.add(Silo(warehouse_id=w2.id, nama_silo='Arsip', aktif=False))
        await db.commit()
        assert len(await svc.daftar_silo(db,'g1')) == jumlah
        assert len(await svc.daftar_silo(db,'g2')) == jumlah
        assert sum(len(g['dryers']) for g in await svc.daftar_dryer(db)) == jumlah
        from app.web.layar import _petak_g2
        assert (await _petak_g2(db))[2]['sat'] == f' / {jumlah}'


async def test_tungku_satu_bisa_memiliki_beberapa_dryer_dan_bisa_diubah(pg, dryer_pabrik):
    async with pg() as db:
        d1 = (await drying_daftarnya(db))[0]
        d2 = Dryer(warehouse_id=d1.warehouse_id,nama='Pengering kedua',kapasitas_kg=30000)
        db.add(d2);await db.flush()
        u = await db.get(User,dryer_pabrik['user'])
        await svc.simpan_tungku(db,d1.id,'Tungku Utara',user=u)
        await svc.simpan_tungku(db,d2.id,'Tungku Utara',user=u)
        await db.commit()
        grup=await svc.daftar_dryer(db)
        assert len(grup)==1 and len(grup[0]['dryers'])==2
        await svc.simpan_tungku(db,d2.id,'Tungku Selatan',user=u);await db.commit()
        assert len(await svc.daftar_dryer(db))==2


async def drying_daftarnya(db):
    from app.penggilingan.gudang1.services.drying import dryers_g1
    return await dryers_g1(db)


async def test_gabah_belum_ditimbang_tetap_terisi_dan_bukan_nol(pg, dryer_pabrik):
    async with pg() as db:
        d = (await drying_daftarnya(db))[0]
        db.add(PurchaseBatch(kode_batch='GB-BELUM',supplier_id=dryer_pabrik['pemasok'],
            kondisi_gabah='basah',status_batch='di_dryer',dryer_id=d.id,
            tanggal_pembelian=date.today(),waktu_pembelian=now_local(),
            berat_total_kg=None,sumber_berat='menunggu',input_by=dryer_pabrik['user']))
        await db.commit()
        alat=(await svc.daftar_dryer(db))[0]['dryers'][0]
        assert alat['terisi'] and 'menunggu timbang' in alat['bobot']


async def test_beranda_akses_status_dan_foto(pg, pengeringan):
    for role in ['operator','admin','superadmin']:
        async with await _klien(pg,peran=role,gudang='Gudang 1') as c:
            r=await c.get('/')
            assert r.status_code==200 and 'data-alur-gudang="g1"' in r.text
            assert ('data-alur-gudang="g2"' in r.text)==(role!='operator')
            assert 'data-dryer-id=' in r.text and 'Mengeringkan' in r.text
            assert 'alur-dryer alur-alat--terisi' in r.text
            assert 'Simulasi tampilan' not in r.text
            if role=='superadmin':
                Path('/tmp/hmu-alur-beranda.html').write_text(r.text)


async def test_isi_silo_g1_dihitung_dari_bahan_bukan_status_master(pg, dryer_pabrik):
    async with pg() as db:
        s=(await db.execute(select(Silo).where(Silo.warehouse_id==dryer_pabrik['g1']))).scalars().first()
        b=PurchaseBatch(kode_batch='GB-SILO-ISI',supplier_id=dryer_pabrik['pemasok'],
            berat_total_kg=5000,sumber_berat='manual',kondisi_gabah='kering',status_batch='di_silo',
            tanggal_pembelian=date.today(),waktu_pembelian=now_local(),input_by=dryer_pabrik['user'])
        db.add(b);await db.flush()
        db.add(SiloStorage(silo_id=s.id,purchase_batch_id=b.id,tipe_masuk='langsung_kering',
            tanggal_masuk=now_local(),input_by=dryer_pabrik['user'],status='terisi'))
        s.status='kosong';await db.commit()
        isi=next(x for x in await svc.daftar_silo(db,'g1') if x['id']==s.id)
        assert isi['terisi'] and isi['kg']==5000


async def test_form_pemetaan_tungku_superadmin_saja(pg, pengeringan):
    async with pg() as db:
        d=(await drying_daftarnya(db))[0];did=d.id;nama=d.nama
    async with await _klien(pg,peran='superadmin') as c:
        r=await c.get('/pengaturan/alat')
        assert 'name="tungku"' in r.text
        from tests.pg.formulir import cap_formulir
        token=cap_formulir(c)
        r=await c.post('/pengaturan/alat/dryer/edit',data={'_csrf':token,'dryer_id':did,'nama':nama,
            'kapasitas_kg':'30000','target_kadar_air':'14','tungku':'Tungku Bersama'})
        assert r.status_code==200
        async with pg() as db:assert (await svc.peta_tungku(db))[did]=='Tungku Bersama'
        r=await c.post('/pengaturan/alat/dryer/edit',data={'_csrf':cap_formulir(c),'dryer_id':did,'nama':nama,
            'kapasitas_kg':'30000','target_kadar_air':'14','tungku':''})
        assert r.status_code==200
        async with pg() as db:assert did not in await svc.peta_tungku(db)
    async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
        assert (await c.get('/pengaturan/alat')).status_code==403
