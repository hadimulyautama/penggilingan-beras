"""Detail QC menjaga seluruh putaran, identitas sumber dan batas gudang."""
from datetime import timedelta
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from hmu_identitas.peran import SUPERADMIN, OPERATOR
from app.database import now_local
from app.models import (User, Supplier, PurchaseBatch, Silo, MillingProcess,
                        MillingQcLog, PkPurchaseBatch)
from app.penggilingan.gudang1.services.qc_gabah import catat_qc_gabah
from app.penggilingan.gudang1.services.milling import log_qc_milling
from app.penggilingan.gudang2.service import log_pk_qc
from app.services.seed import seed_master
from tests.pg.test_riwayat_giling import _klien

pytestmark=pytest.mark.asyncio


@pytest_asyncio.fixture
async def qc(pg):
    await seed_master()
    async with pg() as db:
        user=User(nama='Pencatat QC',role=SUPERADMIN,status='aktif')
        supplier=Supplier(nama_supplier='(UJI) Kelompok Tani Sumber Makmur Cabang Karanganyar')
        db.add_all([user,supplier]);await db.flush()
        for kondisi in ['basah','kering']:
            db.add(PurchaseBatch(kode_batch='GB-QC-'+kondisi.upper(),supplier_id=supplier.id,
                                 berat_total_kg=10000,kondisi_gabah=kondisi,tanggal_pembelian=now_local().date(),
                                 waktu_pembelian=now_local(),input_by=user.id,status_batch='baru',
                                 no_polisi_truk='AD 1234 UJ',sumber_berat='manual'))
        silo=await db.scalar(select(Silo).order_by(Silo.id))
        proc=MillingProcess(kode_proses='LOT-QC-DETAIL',silo_id=silo.id,
                            waktu_mulai=now_local(),status='proses',created_by=user.id)
        pk=PkPurchaseBatch(kode_batch='PKB-QC-DETAIL',supplier_id=supplier.id,berat_total_kg=12000,
                           tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),
                           input_by=user.id,status_batch='diterima',sumber_berat='manual',no_polisi_truk='AD 4321 UJ')
        db.add_all([proc,pk]);await db.commit()
        uid,pid=user.id,proc.id
    for kondisi in ['basah','kering']:
        for i in range(5):
            async with pg() as db:
                await catat_qc_gabah(db,user=await db.get(User,uid),kode_batch='GB-QC-'+kondisi.upper(),
                                     kadar_air_1=20-i,kadar_air_2=20.5-i,biji_hijau='sedikit',densiti='padat',
                                     lamur=(i==0) if kondisi=='basah' else None,
                                     jumlah_sak_lamur=(2 if i==0 else 0) if kondisi=='basah' else None)
    for i in range(3):
        async with pg() as db:
            await log_qc_milling(db,user=await db.get(User,uid),kode_proses='LOT-QC-DETAIL',
                                 kadar_air=13+i,broken=20-i,susut=1,kondisi='KS',
                                 butir_kuning='sedikit',gabah='bersih',merang='bersih')
    async with pg() as db:
        await log_pk_qc(db,user=await db.get(User,uid),kode='PKB-QC-DETAIL',kadar_air=14,broken=20,
                        penyusutan_persen=2,butir_kuning='sedikit',gabah='bersih',merang='bersih',
                        catatan_lab='Contoh catatan laboratorium <b>tetap teks</b>')
    return {'user':uid,'proc':pid}


async def test_daftar_menaut_ke_detail_dan_semua_hasil_tersimpan(pg,qc):
    async with await _klien(pg,peran=SUPERADMIN) as c:
        for jenis,ref,n in [('gabah-basah','GB-QC-BASAH',5),('gabah-kering','GB-QC-KERING',5),
                             ('pk-hasil-giling','LOT-QC-DETAIL',3),('pk-luar','PKB-QC-DETAIL',1)]:
            daftar=await c.get('/riwayat-qc/'+jenis)
            path=f'/riwayat-qc/{jenis}/{ref}'
            assert daftar.status_code==200
            assert f'href="{path}"' in daftar.text
            assert 'class="qc-history-round"' not in daftar.text
            detail=await c.get(path)
            assert detail.status_code==200
            assert ref in detail.text
            assert detail.text.count('class="qc-history-round"')==n
            assert 'Kembali ke Riwayat QC' in detail.text
            if jenis=='gabah-basah':
                # Format tampilan Indonesia; dua bacaan asli kini terpisah.
                assert 'Lamur' in detail.text and '2 sak' in detail.text and '16,00%' in detail.text
            if jenis=='gabah-kering': assert 'Lamur' not in detail.text
            if jenis=='pk-luar':
                assert 'QC 1' in detail.text
                assert '&lt;b&gt;tetap teks&lt;/b&gt;' in detail.text
            if jenis in ['gabah-basah','pk-luar']:
                assert 'Karanganyar' in detail.text and ('AD 1234 UJ' if jenis=='gabah-basah' else 'AD 4321 UJ') in detail.text
            Path('/tmp/hmu-qc-'+jenis+'-daftar.html').write_text(daftar.text)
            Path('/tmp/hmu-qc-'+jenis+'-detail.html').write_text(detail.text)
        for path in ['/riwayat-qc/gabah-basah/GB-QC-KERING','/riwayat-qc/pk-luar/TIDAK-ADA',
                     '/riwayat-qc/beras-hasil-sosoh/POL-01','/riwayat-qc/tidak-ada/GB-QC-BASAH']:
            assert (await c.get(path)).status_code==404


@pytest.mark.parametrize('gudang,boleh,ditolak',[
    ('Gudang 1','gabah-basah/GB-QC-BASAH','pk-luar/PKB-QC-DETAIL'),
    ('Gudang 2','pk-luar/PKB-QC-DETAIL','gabah-basah/GB-QC-BASAH')])
async def test_detail_tetap_dibatasi_gudang(pg,qc,gudang,boleh,ditolak):
    async with await _klien(pg,peran=OPERATOR,gudang=gudang) as c:
        assert (await c.get('/riwayat-qc/'+boleh)).status_code==200
        assert (await c.get('/riwayat-qc/'+ditolak)).status_code==403


async def test_detail_tidak_memotong_putaran_atau_lot_lama_di_luar_batas_daftar(pg,qc):
    async with pg() as db:
        for i in range(201):
            db.add(MillingQcLog(milling_process_id=qc['proc'],kadar_air=5,broken_persen=1,
                               waktu=now_local()-timedelta(days=10,minutes=i),input_by=qc['user']))
        await db.commit()
    async with await _klien(pg,peran=SUPERADMIN) as c:
        assert '204 putaran' in (await c.get('/riwayat-qc/pk-hasil-giling')).text
        r=await c.get('/riwayat-qc/pk-hasil-giling/LOT-QC-DETAIL')
        assert r.status_code==200
        assert r.text.count('class="qc-history-round"')==204
        assert '5,00%' in r.text
