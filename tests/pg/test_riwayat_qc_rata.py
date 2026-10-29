"""Daftar QC membaca rata-rata sumber, tanpa memotong putaran atau menulis data."""
from datetime import timedelta
from pathlib import Path
import os

from bs4 import BeautifulSoup
import pytest
from sqlalchemy import select

from hmu_identitas.peran import ADMIN, SUPERADMIN, OPERATOR
from app.database import now_local
from app.models import (MillingQcLog, MillingProcess, PkPurchaseBatch,
                        PkPurchaseQcLog, PurchaseBatch, PurchaseBatchQc,
                        PurchaseBatchQcSample)
from app.services.mutu_pk import penilaian_dari_log
from tests.pg.test_riwayat_qc_detail import qc  # noqa: F401
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_detail_qc_empat_tab import cuplik
from tests.pg.test_portal_pelanggan import portal, client as portal_client  # noqa: F401

pytestmark = pytest.mark.asyncio


def kartu(html, ref):
    return BeautifulSoup(html, 'html.parser').find('a', attrs={'aria-label': 'Detail QC '+ref})


def hasil(row):
    return {r.b.get_text(): r.get_text(' ', strip=True) for r in row.select('.tabel-standar__hasil')}


@pytest.mark.parametrize('jenis,model,kunci,ref', [
    ('pk-hasil-giling', MillingQcLog, 'milling_process_id', 'LOT-QC-DETAIL'),
    ('pk-luar', PkPurchaseQcLog, 'pk_purchase_batch_id', 'PKB-QC-DETAIL'),
])
async def test_selaras_detail_stok_nol_kosong_kategori_dan_baca_saja(pg,qc,jenis,model,kunci,ref):
    from app.services.stok import riwayat_qc_pk
    from app.penggilingan.gudang2.models import PkGudang2Intake
    async with pg() as db:
        logs = list(await db.scalars(select(model)))
        identitas = getattr(logs[0], kunci)
        # Catatan lama/parsial yang sah tetap tidak menyumbang nol pada kolom kosong.
        db.add(model(**{kunci:identitas}, kadar_air=0, broken_persen=None,
                     susut_persen=None, butir_kuning='parah', gabah=None,
                     merang=None, waktu=now_local()+timedelta(minutes=1), input_by=qc['user']))
        await db.commit()
        logs = list(await db.scalars(select(model)))
        nilai = penilaian_dari_log(logs)
        # Bandingkan juga jalur agregasi SQL kartu Stok, bukan hanya fungsi
        # detail yang dipakai daftar. Ini menjaga pembulatan/kategori/skor.
        from app.services.mutu_pk import ringkasan_banyak
        from app.services.stok import _mutu_dari, _nilai_kualitas, _kelas_kualitas
        from app.penggilingan.gudang1.services.milling import QcRata
        agregat = await ringkasan_banyak(db, model, getattr(model,kunci), [identitas])
        mutu_stok = _mutu_dari(QcRata(**agregat[identitas]))
        skor_stok, n_stok = _nilai_kualitas(mutu_stok)
        assert skor_stok == nilai['nilai'] and n_stok == nilai['n']
        assert _kelas_kualitas(skor_stok) == nilai['kelas']
        assert all(dict(mutu_stok)[r['label']]==r['hasil'] for r in nilai['rows'] if r['n'])
        if jenis == 'pk-luar':
            intake = PkGudang2Intake(pk_purchase_batch_id=identitas, sumber_tipe='beli_luar',
                tujuan='ditumpuk', berat_kg=100, tanggal_masuk=now_local().date(),
                waktu_masuk=now_local(), input_by=qc['user'])
            db.add(intake); await db.commit()
            stok = await riwayat_qc_pk(db, intake_id=intake.id)
        else:
            stok = await riwayat_qc_pk(db, kode=ref)
        assert stok['penilaian']==nilai
    async with await _klien(pg,peran=SUPERADMIN) as c:
        sebelum = await cuplik(pg)
        page = await c.get('/riwayat-qc/'+jenis)
        assert page.status_code==200
        row = kartu(page.text, ref)
        assert 'Rata-rata QC' in row.get_text()
        assert 'Hasil QC terakhir' not in page.text
        assert f"{len(logs)} putaran" in row.get_text()
        fields = hasil(row)
        for r in nilai['rows']:
            assert r['hasil'] in fields[r['label']]
            assert f"{r['n']} pengukuran" in fields[r['label']]
        assert f"{nilai['nilai']:.2f}".replace('.',',') in fields['Nilai kualitas']
        detail = await c.get(f'/riwayat-qc/{jenis}/{ref}?putaran=1&tab_qc=ringkasan')
        assert f"{nilai['nilai']:.2f}".replace('.',',') in detail.text
        assert await cuplik(pg)==sebelum
        if folder := os.environ.get('BUKTI_QC_RATA'):
            Path(folder).mkdir(parents=True,exist_ok=True)
            Path(folder,jenis+'.html').write_text(page.text)


async def test_gabah_dua_bacaan_total_lamur_dan_satu_putaran(pg,qc):
    from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah
    from app.models import User
    async with pg() as db:
        asal = await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch=='GB-QC-KERING'))
        db.add(PurchaseBatch(kode_batch='GB-SATU',supplier_id=asal.supplier_id,
            berat_total_kg=1000,kondisi_gabah='kering',tanggal_pembelian=now_local().date(),
            waktu_pembelian=now_local(),input_by=qc['user'],status_batch='baru',sumber_berat='manual'))
        await db.commit()
        await catat_qc_gabah(db,user=await db.get(User,qc['user']),kode_batch='GB-SATU',
            kadar_air_1=0,kadar_air_2=10,biji_hijau='sedikit',densiti='padat')
    async with await _klien(pg,peran=SUPERADMIN) as c:
        for jenis in ('gabah-basah','gabah-kering'):
            page = await c.get('/riwayat-qc/'+jenis)
            row = kartu(page.text, 'GB-QC-'+jenis.split('-')[1].upper())
            assert '18,25%' in row.get_text()  # 20/20,5 ... 16/16,5, sepuluh bacaan.
            assert '10 pengukuran' in row.get_text() and '5 putaran' in row.get_text()
            if jenis=='gabah-basah': assert '2 sak' in hasil(row)['Total sak berlamur']
            if folder := os.environ.get('BUKTI_QC_RATA'):
                Path(folder,jenis+'.html').write_text(page.text)
        row = kartu(page.text,'GB-SATU')
        assert '5,00%' in row.get_text() and '1 putaran' in row.get_text()
        assert '2 pengukuran' in row.get_text()


async def test_batas_200_batch_gabah_tidak_memotong_putaran_dan_kueri_tetap(pg,qc,hitung_kueri):
    async with await _klien(pg,peran=SUPERADMIN) as c:
        async with hitung_kueri() as sedikit:
            await c.get('/riwayat-qc/gabah-basah')
        async with pg() as db:
            asal = await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch=='GB-QC-BASAH'))
            for i in range(201):
                batch = PurchaseBatch(kode_batch=f'GB-BATAS-{i:03}',supplier_id=asal.supplier_id,
                    berat_total_kg=1000,kondisi_gabah='basah',tanggal_pembelian=now_local().date(),
                    waktu_pembelian=now_local(),input_by=qc['user'],status_batch='selesai',
                    sumber_berat='manual',kadar_air_awal_persen=5)
                db.add(batch); await db.flush()
                header = PurchaseBatchQc(purchase_batch_id=batch.id,lamur=False,jumlah_sak_lamur=0,
                    biji_hijau='sedikit',densiti='padat',input_by=qc['user'])
                db.add(header); await db.flush()
                for n in range(1,6):
                    db.add(PurchaseBatchQcSample(purchase_batch_qc_id=header.id,nomor_sampel=n,
                        kadar_air_1=0,kadar_air_2=10,lamur=False,jumlah_sak_lamur=0,
                        biji_hijau='sedikit',densiti='padat',input_by=qc['user'],
                        created_at=now_local()+timedelta(minutes=i+1,seconds=n)))
            await db.commit()
        async with hitung_kueri() as banyak:
            page = await c.get('/riwayat-qc/gabah-basah')
        assert banyak.jumlah == sedikit.jumlah
        soup = BeautifulSoup(page.text,'html.parser')
        rows = soup.select('.tabel-standar__baris')
        assert len(rows)==200
        assert all('5 putaran' in r.get_text() and '10 pengukuran' in r.get_text() for r in rows)
        assert 'GB-BATAS-200' in rows[0].get_text()
        assert kartu(page.text,'GB-BATAS-000') is None
        detail = await c.get('/riwayat-qc/gabah-basah/GB-BATAS-000')
        assert detail.status_code==200 and '5 putaran' in detail.text


async def test_pk_lebih_200_putaran_tetap_satu_rata_rata(pg,qc):
    async with pg() as db:
        for n in range(201):
            db.add(MillingQcLog(milling_process_id=qc['proc'],kadar_air=5,broken_persen=0,
                waktu=now_local()-timedelta(days=10,minutes=n),input_by=qc['user']))
        await db.commit()
        nilai = penilaian_dari_log(await db.scalars(select(MillingQcLog)))
    async with await _klien(pg,peran=SUPERADMIN) as c:
        row = kartu((await c.get('/riwayat-qc/pk-hasil-giling')).text,'LOT-QC-DETAIL')
        assert '204 putaran' in row.get_text()
        assert nilai['rows'][0]['hasil'] in hasil(row)['Kadar air']
        assert '204 pengukuran' in hasil(row)['Kadar air']


@pytest.mark.parametrize('peran,gudang,lihat,jenis,status',[
    (SUPERADMIN,None,None,'pk-luar',200), (ADMIN,None,None,'pk-hasil-giling',200),
    (OPERATOR,'Gudang 1','operator:g1','pk-hasil-giling',200),
    (OPERATOR,'Gudang 1','operator:g1','pk-luar',403),
    (OPERATOR,'Gudang 2','operator:g2','pk-luar',200),
    (OPERATOR,'Gudang 2','operator:g2','gabah-basah',403),
    (SUPERADMIN,None,'operator:g1','pk-luar',403),
])
async def test_akses_daftar_tetap_peran_efektif(pg,qc,peran,gudang,lihat,jenis,status):
    async with await _klien(pg,peran=peran,gudang=gudang,lihat=lihat) as c:
        if lihat:
            from tests.pg.formulir import cap_formulir
            r = await c.post('/lihat-sebagai',data={'peran':lihat,'_csrf':cap_formulir(c)},follow_redirects=False)
            assert r.status_code==303
        assert (await c.get('/riwayat-qc/'+jenis)).status_code==status


async def test_portal_daftar_tidak_mencampur_pelanggan(pg,portal):
    async with portal_client(portal.accounts[0]) as c:
        sebelum = await cuplik(pg)
        page = await c.get('/pelanggan/riwayat-qc/pk-hasil-giling')
        assert page.status_code==200 and 'LOT-QC-DETAIL' in page.text
        assert 'LOT-RAHASIA-B' not in page.text
        assert (await c.get('/pelanggan/riwayat-qc/pk-hasil-giling/LOT-RAHASIA-B')).status_code==404
        assert await cuplik(pg)==sebelum


async def test_satu_putaran_kolom_kosong_dan_pembatalan_putaran(pg,qc):
    from app.models import User
    from app.penggilingan.gudang2.service import log_pk_qc
    from app.services.undo import _undo_pk_qc
    async with pg() as db:
        batch = await db.scalar(select(PkPurchaseBatch))
        pertama = await db.scalar(select(PkPurchaseQcLog))
        # Meniru catatan historis parsial: nilai kosong sah, bukan nol.
        pertama.susut_persen = None
        pertama.merang = None
        await db.commit()
    async with await _klien(pg,peran=SUPERADMIN) as c:
        path='/riwayat-qc/pk-luar'
        awal=kartu((await c.get(path)).text,batch.kode_batch)
        assert '1 putaran' in awal.get_text()
        assert 'Belum dinilai' in hasil(awal)['Susut'] and '0 pengukuran' in hasil(awal)['Susut']
        async with pg() as db:
            await log_pk_qc(db,user=await db.get(User,qc['user']),kode=batch.kode_batch,
                kadar_air=18,broken=0,penyusutan_persen=0,
                butir_kuning='parah',gabah='parah',merang='parah')
            terakhir=await db.scalar(select(PkPurchaseQcLog.id).order_by(PkPurchaseQcLog.id.desc()))
        kedua=kartu((await c.get(path)).text,batch.kode_batch)
        assert '2 putaran' in kedua.get_text()
        assert '16,0%' in hasil(kedua)['Kadar air']
        async with pg() as db:
            await _undo_pk_qc(db,terakhir)
            await db.commit()
        akhir=kartu((await c.get(path)).text,batch.kode_batch)
        assert akhir.get_text(' ',strip=True)==awal.get_text(' ',strip=True)


async def test_rata_rata_antarproses_tidak_bercampur_dan_sosoh_bukan_qc(pg,qc):
    async with pg() as db:
        pertama=await db.get(MillingProcess,qc['proc'])
        kedua=MillingProcess(kode_proses='LOT-QC-TERPISAH',silo_id=pertama.silo_id,
            waktu_mulai=now_local(),status='selesai',created_by=qc['user'])
        db.add(kedua); await db.flush()
        for n in range(2):
            db.add(MillingQcLog(milling_process_id=kedua.id,kadar_air=30+n*2,broken_persen=0,
                waktu=now_local()+timedelta(minutes=n+1),input_by=qc['user']))
        await db.commit()
    async with await _klien(pg,peran=SUPERADMIN) as c:
        page=await c.get('/riwayat-qc/pk-hasil-giling')
        assert '31,0%' in hasil(kartu(page.text,'LOT-QC-TERPISAH'))['Kadar air']
        assert '14,0%' in hasil(kartu(page.text,'LOT-QC-DETAIL'))['Kadar air']
        rows=BeautifulSoup(page.text,'html.parser').select('.tabel-standar__baris')
        assert 'LOT-QC-TERPISAH' in rows[0].get_text()
        for r in rows:
            stamp=r.select_one('.tabel-standar__sekunder')
            assert stamp and ':' in stamp.get_text()
        kosong=await c.get('/riwayat-qc/beras-hasil-sosoh')
        assert kosong.status_code==200 and 'bukan hasil pengukuran QC' in kosong.text
        assert not BeautifulSoup(kosong.text,'html.parser').select('.tabel-standar__baris')
