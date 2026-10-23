"""QC gabah mengikuti sumber asli; GET tidak mengubah hasil, stok, atau QC."""
import json
import os
from pathlib import Path

import pytest
from sqlalchemy import select, func
from tests.pg.test_detail_pengeringan_tab import dryer_tab, pengeringan, dryer_pabrik
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_stok_pk_qc import dunia, dunia_asal
from app.models import User, PurchaseBatch, PurchaseBatchQc, PurchaseBatchQcSample, MillingProcess
from app.services import qc_gabah_asal

pytestmark = pytest.mark.asyncio


async def _qc(db, user, kode, air=24):
    from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah
    return await catat_qc_gabah(db, user=user, kode_batch=kode, kadar_air_1=air,
        kadar_air_2=air+1, biji_hijau='sedikit', densiti='padat', lamur=True, jumlah_sak_lamur=2)


@pytest.mark.parametrize('peran', ['operator','admin','superadmin'])
async def test_dari_gabah_ke_pk_tanpa_mengubah_angka(pg, dryer_tab, peran):
    from app.penggilingan.gudang1.services import drying as dr, milling as mi
    from app.penggilingan.gudang1.services.silo import masuk_silo
    from tests.pg.skenario_silo import pastikan_silo_kosong
    from app.models import SiloStorage, MillingProgressLog
    kode = dryer_tab['kode']
    async with pg() as db:
        u = await db.get(User,dryer_tab['user'])
        await _qc(db,u,dryer_tab['batch'])
        await _qc(db,u,dryer_tab['batch'],26)
    async with await _klien(pg,peran=peran,gudang='Gudang 1') as c:
        for tahap in ['pengeringan','pendinginan','sudah-dingin','silo','giling','pk']:
            if tahap=='pengeringan': url='/proses-aktif/pengeringan/'+kode
            elif tahap=='pendinginan':
                async with pg() as db:
                    await dr.finish_drying(db,user=await db.get(User,dryer_tab['user']),kode_lot=kode,kadar_air_akhir=18)
                url='/proses-aktif/pendinginan/'+kode
            elif tahap=='sudah-dingin':
                async with pg() as db:
                    await dr.finish_cooling(db,user=await db.get(User,dryer_tab['user']),kode_lot=kode)
                url='/riwayat-pengeringan/'+str(dryer_tab['id'])
            elif tahap=='silo':
                async with pg() as db:
                    await masuk_silo(db,user=await db.get(User,dryer_tab['user']),nama_silo='A',kode_lot=kode,kode_batch=None)
                # Detail lot yang sama tetap tersedia sesudah pindah ke silo.
            elif tahap=='giling':
                async with pg() as db:
                    r=await mi.start_milling(db,user=await db.get(User,dryer_tab['user']),nama_silo='A')
                    giling=r.proc.kode_proses; gid=r.proc.id
                url='/proses-aktif/giling/'+giling
            else:
                async with pg() as db:
                    u=await db.get(User,dryer_tab['user'])
                    await pastikan_silo_kosong(db,user=u,kode_proses=giling)
                    await mi.finish_milling(db,user=u,kode_proses=giling,berat_akhir=6400)
                url='/stok/pk/detail?gudang=g1&kode='+giling
            async with pg() as db:
                sebelum=await _potret(db)
            r=await c.get(url+('&' if '?' in url else '?')+'tab_detail=bahan')
            assert r.status_code==200,(tahap,r.text[:200])
            for teks in ['QC gabah asal','QC 1','QC 2','24%','27%','Ya · 2 sak','Padat',dryer_tab['tambahan'],'QC gabah belum tercatat untuk batch ini.']:
                assert teks in r.text,(tahap,teks)
            if tahap in ['pengeringan','pendinginan','sudah-dingin','silo']:
                assert 'Mode dryer belum tercatat' in r.text
            async with pg() as db:
                assert await _potret(db)==sebelum
            if tahap=='pk':
                history=await c.get('/riwayat-giling/'+str(gid))
                assert history.status_code==200 and 'QC gabah asal' in history.text
            if os.environ.get('UJI_POTRET_QC_ASAL') and peran=='admin':
                Path('/tmp/qc-asal-session.json').write_text(json.dumps({'url':url,'cookies':dict(c.cookies),'tahap':tahap}))
                # Simpan HTML tiap tahap untuk pemeriksaan render tanpa mengubah data.
                for tab in (['ringkasan','bahan','hasil','riwayat'] if tahap=='giling' else
                            ['ringkasan','bahan','pengukuran','riwayat'] if tahap!='pk' else ['detail']):
                    potret=await c.get(url+('&' if '?' in url else '?')+'tab_detail='+tab)
                    assert potret.status_code==200
                    Path('/tmp/qc-asal-'+tahap+'-'+tab+'.html').write_text(potret.text)
                if tahap=='pk':
                    Path('/tmp/qc-asal-riwayat-giling-detail.html').write_text(history.text)
        from app.web.lihat_sebagai import NAMA_KUKI
        c.cookies.set(NAMA_KUKI,'operator:g2')
        assert (await c.get('/riwayat-pengeringan/'+str(dryer_tab['id']))).status_code==403
        assert (await c.get('/riwayat-giling/'+str(gid))).status_code==403


async def _potret(db):
    from app.models import MillingProgressLog, SiloStorage
    from app.services.stok import pk_gudang1
    stok = await pk_gudang1(db)
    return (
        [(x.kode,x.dihasilkan,x.tersedia,x.rendemen,x.bahan_kg) for x in stok],
        await db.scalar(select(func.count()).select_from(PurchaseBatchQcSample)),
        [(x.id,x.kadar_air_awal_persen,x.berat_total_kg) for x in (await db.scalars(select(PurchaseBatch).order_by(PurchaseBatch.id))).all()],
        [(x.id,x.berat_kumulatif_kg) for x in (await db.scalars(select(MillingProgressLog).order_by(MillingProgressLog.id))).all()],
        [(x.id,x.status,x.drying_lot_id,x.purchase_batch_id) for x in (await db.scalars(select(SiloStorage).order_by(SiloStorage.id))).all()])


async def test_qc_gabah_pk_transfer_kering_legacy_dan_fitur(pg,dunia):
    from app.services.setelan import set_fitur_mutu
    async with pg() as db:
        u=await db.get(User,dunia['user'].id)
        b=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch=='GB-KODE-01'))
        b.kondisi_gabah='kering'
        db.add(PurchaseBatchQc(purchase_batch_id=b.id,biji_hijau='banyak',densiti='empuk',input_by=u.id))
        await db.commit()
        a=await qc_gabah_asal.dari_pk(db,kode='LOT-KODE-01')
        assert a==await qc_gabah_asal.dari_pk(db,intake_id=dunia['giling_intake_id'])
        assert a[0]['catatan'][0]['air1']=='Belum tercatat'
        assert a[0]['catatan'][0]['lamur']=='Tidak berlaku untuk gabah kering'
        assert await qc_gabah_asal.dari_pk(db,intake_id=dunia['beli_intake_id'])==[]
    async with await _klien(pg,peran='superadmin') as c:
        for url in ['/stok/pk/detail?gudang=g1&kode=LOT-KODE-01','/stok/pk/detail?gudang=g2&id='+str(dunia['giling_intake_id'])]:
            r=await c.get(url)
            assert r.status_code==200 and 'QC data lama' in r.text and 'Empuk' in r.text
        async with pg() as db:
            await set_fitur_mutu(db,False,user=await db.get(User,dunia['user'].id))
        r=await c.get('/stok/pk/detail?gudang=g1&kode=LOT-KODE-01')
        assert r.status_code==200 and 'QC gabah asal' not in r.text


async def test_gabah_kering_bacaan_asli_dan_sumber_berulang(pg,dunia):
    from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah
    from app.models import MillingProcessSource, SiloStorage
    async with pg() as db:
        b=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch=='GB-KODE-01'))
        b.kondisi_gabah='kering'
        u=await db.get(User,dunia['user'].id)
        await catat_qc_gabah(db,user=u,kode_batch=b.kode_batch,kadar_air_1=13.25,kadar_air_2=14.75,
                            biji_hijau='hampir_tidak_ada',densiti='sedang')
        proc=await db.scalar(select(MillingProcess).where(MillingProcess.kode_proses=='LOT-KODE-01'))
        # Dua pemakaian dari batch sama tetap satu kartu QC; sumber lama tetap terbaca.
        for _ in range(2):
            st=SiloStorage(silo_id=proc.silo_id,purchase_batch_id=b.id,tipe_masuk='langsung_kering',
                           tanggal_masuk=b.waktu_pembelian,input_by=u.id,status='kosong')
            db.add(st); await db.flush()
            db.add(MillingProcessSource(milling_process_id=proc.id,silo_storage_id=st.id,
                                       purchase_batch_id=b.id,berat_kg=5000))
        await db.commit()
        qc=await qc_gabah_asal.dari_giling(db,proc)
        assert len(qc)==1 and len(qc[0]['catatan'])==1
        assert qc[0]['catatan'][0]['air1']=='13,25%'
        assert qc[0]['catatan'][0]['air2']=='14,75%'
    async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
        r=await c.get('/stok/pk/detail?gudang=g2&id='+str(dunia['giling_intake_id']))
        assert r.status_code==200 and '13,25%' in r.text and 'Hampir tidak ada' in r.text
        assert (await c.get('/riwayat-giling/'+str(proc.id))).status_code==403
        if os.environ.get('UJI_POTRET_QC_ASAL'):
            Path('/tmp/qc-asal-pk-kering-detail.html').write_text(r.text)
