"""Empat tab QC adalah tampilan baca, tidak mengubah penilaian atau transaksi."""
import json
import os
from pathlib import Path

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select, text, delete
from hmu_identitas.peran import ADMIN, SUPERADMIN, OPERATOR
from app.database import now_local
from app.models import MillingQcLog, PurchaseBatch, PurchaseBatchQc, PurchaseBatchQcSample, User, SetelanPabrik
from app.services.mutu_pk import penilaian_dari_log
from tests.pg.test_riwayat_qc_detail import qc  # noqa: F401
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_portal_pelanggan import portal, client as portal_client  # noqa: F401

pytestmark = pytest.mark.asyncio
TAB = ('ringkasan','putaran','perhitungan','asal')
REF = {'gabah-basah':'GB-QC-BASAH','gabah-kering':'GB-QC-KERING',
       'pk-hasil-giling':'LOT-QC-DETAIL','pk-luar':'PKB-QC-DETAIL'}


def bukti(nama, isi):
    if folder := os.environ.get('BUKTI_QC'):
        p=Path(folder);p.mkdir(parents=True,exist_ok=True);(p/nama).write_text(isi)


async def cuplik(pg):
    tables=('purchase_batches','purchase_batch_qc','purchase_batch_qc_samples',
            'milling_process','milling_qc_logs','pk_purchase_batches','pk_purchase_qc_logs',
            'finished_goods_stock','byproduct_stock','internal_transfers','activity_logs','peristiwa')
    async with pg() as db:
        return {t:await db.scalar(text(f"SELECT coalesce(jsonb_agg(to_jsonb(x) ORDER BY id),'[]'::jsonb)::text FROM {t} x")) for t in tables}


async def test_empat_tab_semua_kategori_tetap_membaca_data_yang_sama(pg,qc):
    async with pg() as db:
        logs=(await db.scalars(select(MillingQcLog).order_by(MillingQcLog.waktu,MillingQcLog.id))).all()
        sebelum=penilaian_dari_log(logs)
        putaran_awal=[penilaian_dari_log([l]) for l in logs]
    async with await _klien(pg,peran=SUPERADMIN) as c:
        snap=await cuplik(pg)
        for jenis,ref in REF.items():
            for tab in TAB:
                r=await c.get(f'/riwayat-qc/{jenis}/{ref}?tab_qc={tab}&putaran=1&kembali_qc=%2Fstok%3Ftab%3Dbahan%26gudang%3Dg1')
                assert r.status_code==200,r.text[:500]
                s=BeautifulSoup(r.text,'html.parser')
                assert len(s.select('.qc-tabs a'))==4
                assert s.select_one('.qc-tabs [aria-current=page]')['id']=='qc-tab-'+tab
                assert len(s.select('.qc-detail>div[id^=qc-panel-]:not([hidden]),.qc-detail>section[id^=qc-panel-]:not([hidden])'))==1
                assert all('kembali_qc=' in a['href'] for a in s.select('.qc-tabs a'))
                assert s.select_one('.riwayat-detail__back')['href']=='/stok?tab=bahan&gudang=g1'
                assert not s.select('.qc-detail form[method=post]')
                if jenis.startswith('gabah-'):
                    async with pg() as db:
                        sampel=(await db.scalars(select(PurchaseBatchQcSample)
                            .join(PurchaseBatchQc,PurchaseBatchQc.id==PurchaseBatchQcSample.purchase_batch_qc_id)
                            .join(PurchaseBatch,PurchaseBatch.id==PurchaseBatchQc.purchase_batch_id)
                            .where(PurchaseBatch.kode_batch==ref)
                            .order_by(PurchaseBatchQcSample.created_at,PurchaseBatchQcSample.id))).all()
                    putaran=s.select('.qc-history-round')
                    assert len(putaran)==len(sampel)
                    for kartu,asli in zip(putaran,sampel):
                        fields={x.dt.get_text():x.dd.get_text() for x in kartu.select('.qc-fields>div')}
                        assert fields['Kadar air 1']==str(asli.kadar_air_1).replace('.',',')+'%'
                        assert fields['Kadar air 2']==str(asli.kadar_air_2).replace('.',',')+'%'
                        assert 'Kadar air' not in fields
                if jenis=='gabah-kering': assert 'Lamur' not in r.text and 'berlamur' not in r.text
                if jenis=='pk-hasil-giling':
                    assert s.select_one('.qc-score strong').get_text()==f"{sebelum['nilai']:.2f}".replace('.',',')
                if jenis=='pk-luar':assert '&lt;b&gt;tetap teks&lt;/b&gt;' in r.text
                bukti(jenis+'-'+tab+'.html',r.text)
            assert (await c.get(f'/riwayat-qc/{jenis}/{ref}?putaran=invalid&tab_qc=invalide')).status_code==200
        assert await cuplik(pg)==snap
        bukti('sesi.json',json.dumps({'cookies':{x.name:x.value for x in c.cookies.jar},'refs':REF}))
    async with pg() as db:
        logs_akhir=(await db.scalars(select(MillingQcLog).order_by(MillingQcLog.waktu,MillingQcLog.id))).all()
        apres=penilaian_dari_log(logs_akhir)
        putaran_akhir=[penilaian_dari_log([l]) for l in logs_akhir]
        assert putaran_akhir==putaran_awal
        assert apres==sebelum
        bukti('perbandingan.json',json.dumps({'sebelum':sebelum,'sesudah':apres,'putaran_sebelum':putaran_awal,'putaran_sesudah':putaran_akhir,'snapshot_12_tabel_tetap':True},default=str,indent=2))


async def test_semua_putaran_pk_catatan_terakhir_dan_fitur_nonaktif(pg,qc):
    from app.penggilingan.gudang1.services.milling import log_qc_milling
    async with pg() as db:
        for n in range(9):
            await log_qc_milling(db,user=await db.get(User,qc['user']),kode_proses='LOT-QC-DETAIL',
                kadar_air=13.2,broken=10,susut=1,kondisi='KS',butir_kuning='bersih',gabah='bersih',merang='bersih',
                catatan_lab='<script>catatan asli</script>' if n==3 else '')
        db.add(SetelanPabrik(kunci='fitur_mutu',nilai='false'));await db.commit()
        nilai=penilaian_dari_log((await db.scalars(select(MillingQcLog))).all())
    async with await _klien(pg,peran=SUPERADMIN) as c:
        snap=await cuplik(pg)
        for tab in TAB:
            r=await c.get('/riwayat-qc/pk-hasil-giling/LOT-QC-DETAIL?tab_qc='+tab+'&putaran=7')
            assert r.status_code==200
            s=BeautifulSoup(r.text,'html.parser')
            assert len(s.select('#qc-putaran option'))==12
            assert s.select_one('#qc-putaran [selected]')['value']=='7'
            assert s.select_one('.qc-score strong').get_text()==f"{nilai['nilai']:.2f}".replace('.',',')
            assert '<script>catatan asli</script>' not in r.text
            assert s.select_one('.qc-note').get_text()=='<script>catatan asli</script>'
            assert 'putaran=7' in s.select_one('.qc-note~a')['href']
            bukti('pk-banyak-'+tab+'.html',r.text)
        for n in (1,12):
            s=BeautifulSoup((await c.get(f'/riwayat-qc/pk-hasil-giling/LOT-QC-DETAIL?tab_qc=putaran&putaran={n}')).text,'html.parser')
            assert s.select_one('.qc-history-round:not([hidden])')['data-posisi']==str(n)
        assert await cuplik(pg)==snap


async def test_pk_sebagian_tidak_mengisi_komponen_kosong(pg,qc):
    async with pg() as db:
        await db.execute(delete(MillingQcLog))
        db.add(MillingQcLog(milling_process_id=qc['proc'],kadar_air=13.2,waktu=now_local(),input_by=qc['user']))
        await db.commit()
    async with await _klien(pg,peran=SUPERADMIN) as c:
        for tab in TAB:
            r=await c.get('/riwayat-qc/pk-hasil-giling/LOT-QC-DETAIL?tab_qc='+tab)
            assert r.status_code==200 and 'Penilaian belum lengkap' in r.text and '1/6' in r.text
            assert 'Belum dinilai' in r.text and '(100) ÷ 1' in r.text
            bukti('pk-sebagian-'+tab+'.html',r.text)


async def test_gabah_rata_seluruh_bacaan_dan_status_tutup_dari_header(pg,qc):
    from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah,tutup_qc_gabah,ringkasan_tutup_qc
    async with pg() as db:
        asal=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch=='GB-QC-BASAH'))
        b=PurchaseBatch(kode_batch='GB-TUTUP-QC-TAB',supplier_id=asal.supplier_id,berat_total_kg=1000,
            kondisi_gabah='basah',tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),
            input_by=qc['user'],status_batch='baru',sumber_berat='manual')
        db.add(b);await db.commit()
        for a1,a2,sak in [(14.1,20.5,2),(17.1,18.5,3)]:
            await catat_qc_gabah(db,user=await db.get(User,qc['user']),kode_batch=b.kode_batch,
                kadar_air_1=a1,kadar_air_2=a2,biji_hijau='sedikit',densiti='padat',lamur=True,jumlah_sak_lamur=sak)
            if sak==2: pratinjau_lama=await ringkasan_tutup_qc(db,kode_batch=b.kode_batch)
    async with await _klien(pg,peran=SUPERADMIN) as c:
        path='/riwayat-qc/gabah-basah/GB-TUTUP-QC-TAB'
        r=await c.get(path);assert 'Pemeriksaan masih berjalan' in r.text and '17,55%' in r.text
        async with pg() as db:
            with pytest.raises(ValueError,match='berubah'):
                await tutup_qc_gabah(db,user=await db.get(User,qc['user']),kode_batch=b.kode_batch,
                    alasan='Sampel telah selesai diperiksa.',dasar=pratinjau_lama['dasar'])
            with pytest.raises(ValueError,match='alasan'):
                await tutup_qc_gabah(db,user=await db.get(User,qc['user']),kode_batch=b.kode_batch)
            terbaru=await ringkasan_tutup_qc(db,kode_batch=b.kode_batch)
            await tutup_qc_gabah(db,user=await db.get(User,qc['user']),kode_batch=b.kode_batch,
                alasan='Sampel telah selesai diperiksa.',dasar=terbaru['dasar'])
        snap=await cuplik(pg)
        for tab in TAB:
            r=await c.get(path+'?tab_qc='+tab)
            assert r.status_code==200 and 'Ditutup lebih awal' in r.text and '17,55%' in r.text and '5 sak' in r.text
            assert 'Sampel telah selesai diperiksa.' in r.text and 'Perhitungan nilai gabungan' not in r.text
            bukti('gabah-ditutup-'+tab+'.html',r.text)
        assert await cuplik(pg)==snap


@pytest.mark.parametrize('role,gudang,lihat,allowed',[
    (SUPERADMIN,None,None,{'g1','g2'}),(ADMIN,None,None,{'g1','g2'}),
    (OPERATOR,'Gudang 1',None,{'g1'}),(OPERATOR,'Gudang 2',None,{'g2'}),
    (SUPERADMIN,None,'operator:g2',{'g2'})])
async def test_gerbang_backend_seluruh_tab_dan_gudang_efektif(pg,qc,role,gudang,lihat,allowed):
    async with await _klien(pg,peran=role,gudang=gudang) as c:
        if lihat:
            from tests.pg.formulir import cap_formulir
            r=await c.post('/lihat-sebagai',data={'peran':lihat,'_csrf':cap_formulir(c)},follow_redirects=False)
            assert r.status_code==303
        for jenis,ref in REF.items():
            for tab in TAB:
                r=await c.get(f'/riwayat-qc/{jenis}/{ref}?tab_qc={tab}')
                assert r.status_code==(200 if ('g2' if jenis=='pk-luar' else 'g1') in allowed else 403)


async def test_portal_tab_dan_putaran_baca_saja_scope_tetap(pg,portal):
    async with portal_client(portal.accounts[0]) as c:
        snap=await cuplik(pg)
        for tab in TAB:
            r=await c.get('/pelanggan/riwayat-qc/pk-hasil-giling/LOT-QC-DETAIL?tab_qc='+tab)
            assert r.status_code==200
            s=BeautifulSoup(r.text,'html.parser')
            assert len(s.select('.qc-tabs a'))==4 and not s.select('.qc-detail form[method=post]')
            assert s.select_one('.qc-picker')['action'].startswith('/pelanggan/riwayat-qc/')
            assert not s.select('dialog,[data-post],[data-kirim]')
            assert (await c.get('/pelanggan/riwayat-qc/pk-hasil-giling/LOT-RAHASIA-B?tab_qc='+tab)).status_code==404
            bukti('portal-'+tab+'.html',r.text)
        assert await cuplik(pg)==snap


async def test_konteks_asal_aman_dan_tetap_ada_saat_memilih_putaran(pg,qc):
    path='/riwayat-qc/pk-hasil-giling/LOT-QC-DETAIL'
    async with await _klien(pg,peran=SUPERADMIN) as c:
        r=await c.get(path,headers={'referer':'http://uji/stok?tab=bahan&gudang=g1'})
        s=BeautifulSoup(r.text,'html.parser')
        assert s.select_one('.riwayat-detail__back')['href']=='/stok?tab=bahan&gudang=g1'
        link=s.select_one('#qc-tab-putaran')['href']
        r=await c.get(link);s=BeautifulSoup(r.text,'html.parser')
        assert s.select_one('input[name=kembali_qc]')['value']=='/stok?tab=bahan&gudang=g1'
        for external in ('https://contoh.invalid/stok','//contoh.invalid/stok'):
            r=await c.get(path,params={'kembali_qc':external},headers={'referer':'https://contoh.invalid/stok'})
            s=BeautifulSoup(r.text,'html.parser')
            assert s.select_one('.riwayat-detail__back')['href']=='/riwayat-qc/pk-hasil-giling'


async def test_pk_lama_mempertahankan_asal_dan_pencatat_tidak_diketahui(pg,qc):
    from app.models import PkPurchaseQcLog
    async with pg() as db:
        row=await db.scalar(select(PkPurchaseQcLog));row.asal_lama=True;row.input_by=None
        await db.commit();waktu=row.waktu
    async with await _klien(pg,peran=SUPERADMIN) as c:
        snap=await cuplik(pg)
        for tab in TAB:
            r=await c.get('/riwayat-qc/pk-luar/PKB-QC-DETAIL?tab_qc='+tab)
            assert r.status_code==200 and 'Hasil QC lama yang masih tersimpan' in r.text
            s=BeautifulSoup(r.text,'html.parser')
            rows=[d for d in s.select('.qc-history-round .qc-fields>div') if d.dt.get_text()=='Pencatat']
            assert rows[0].dd.get_text()=='Tidak tercatat'
            bukti('pk-lama-'+tab+'.html',r.text)
        assert await cuplik(pg)==snap
    async with pg() as db:assert (await db.scalar(select(PkPurchaseQcLog))).waktu==waktu


async def test_armada_dan_asal_banyak_sumber_dari_relasi_asli(pg,qc):
    from app.models import MillingProcess,MillingProcessSource,SiloStorage,DryingLot,DryingLotBatch
    async with pg() as db:
        process=await db.get(MillingProcess,qc['proc'])
        batches=(await db.scalars(select(PurchaseBatch).order_by(PurchaseBatch.id))).all()
        for i,b in enumerate(batches):
            b.no_polisi_truk=f'AD {7001+i} QC'
            if b.kondisi_gabah=='basah':
                lot=DryingLot(kode_lot='PGR-QC-ASAL',created_by=qc['user'],status='selesai',
                    waktu_mulai_pengeringan=now_local(),waktu_selesai_pengeringan=now_local(),waktu_selesai_pendinginan=now_local())
                db.add(lot);await db.flush();db.add(DryingLotBatch(drying_lot_id=lot.id,purchase_batch_id=b.id))
                sumber={'drying_lot_id':lot.id};tipe='dari_pengeringan'
            else:
                sumber={'purchase_batch_id':b.id};tipe='langsung_kering'
            row=SiloStorage(silo_id=process.silo_id,**sumber,tipe_masuk=tipe,
                tanggal_masuk=now_local(),status='kosong',input_by=qc['user'])
            db.add(row);await db.flush()
            db.add(MillingProcessSource(milling_process_id=process.id,silo_storage_id=row.id,**sumber,berat_kg=1000))
        await db.commit()
    async with await _klien(pg,peran=SUPERADMIN) as c:
        r=await c.get('/riwayat-qc/pk-hasil-giling/LOT-QC-DETAIL?tab_qc=asal')
        assert r.status_code==200 and 'AD 7001 QC' in r.text and 'AD 7002 QC' in r.text
        assert 'Kelompok Tani Sumber Makmur' in r.text
