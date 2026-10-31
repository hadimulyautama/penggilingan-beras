"""Transit tanpa kode proses tetap terlihat, seluruh sumbernya wajib milik pelanggan."""
from datetime import date, timedelta

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.database import now_local
from app.models import (Dryer, DryingLot, DryingLotBatch, PkGudang2Intake,
                        PkPurchaseBatch, PolishingProcess, PolishingSiloUsage,
                        PurchaseBatch, SiloStorage, User)
from app.models.portal import PortalAccount
from app.services import berjalan
from app.web import security
from app.web.portal.scope import load_scope
from app.web.portal.security import CustomerReader
from tests.pg.test_gabung_jasa import dunia, _isi_silo_g1
from tests.pg.test_portal_pelanggan import client

pytestmark = pytest.mark.asyncio


async def _akun(pg, dunia):
    async with pg() as db:
        account = PortalAccount(username='uji-transit', pelanggan_id=dunia['catur'],
            password_hash=security.hash_sandi('uji-transit-2026'), active=True, token_version=1)
        db.add(account)
        await db.commit()
        return account


async def _bacaan(pg, dunia):
    scope = await load_scope(CustomerReader(1, dunia['catur'], 'Catur'))
    async with pg() as db:
        return await berjalan.untuk_pelanggan(db, dunia['catur'], scope=scope)


async def _halaman(pg, dunia, expected, forbidden):
    async with client(await _akun(pg, dunia)) as c:
        pages = []
        for tab in ['tindakan', 'berjalan']:
            response = await c.get('/pelanggan/pekerjaan?tab='+tab)
            assert response.status_code == 200, response.text[:250]
            soup = BeautifulSoup(response.text, 'html.parser')
            assert not soup.select('[data-post],[data-aksi],dialog')
            assert all(a['href'].startswith(('/pelanggan/', '#')) for a in soup.select('a[href]'))
            pages.append(soup.get_text(' ', strip=True))
        body = ' '.join(pages)
        assert all(value in body for value in expected), body
        assert all(value not in body for value in forbidden), body
        assert (await c.get('/pelanggan/pekerjaan?pelanggan_id='+str(dunia['budi']))).status_code == 404
        assert (await c.get('/pengaturan')).status_code == 303


async def _batch_dryer(pg, dunia, *, dryer, jid, code):
    async with pg() as db:
        batch = PurchaseBatch(kode_batch=code, jasa_id=jid, berat_total_kg=1500,
            kondisi_gabah='basah', tanggal_pembelian=date.today(), waktu_pembelian=now_local(),
            input_by=dunia['user'], flag_unverified=False, sumber_berat='timbangan',
            status_batch='di_dryer', dryer_id=dryer)
        db.add(batch)
        await db.commit()
        return batch.id


async def _pk(pg, dunia, *, silo, jid, code, lewat_tumpukan=False, waktu=None):
    from app.penggilingan.gudang2.service import _add_intake, pindah_tumpukan_ke_silo
    async with pg() as db:
        batch = PkPurchaseBatch(kode_batch=code, jasa_id=jid, berat_total_kg=2000,
            tanggal_pembelian=date.today(), waktu_pembelian=waktu or now_local(),
            input_by=dunia['user'], status_batch='diterima')
        db.add(batch)
        await db.flush()
        user = await db.get(User, dunia['user'])
        await _add_intake(db, user=user, sumber_tipe='beli_luar',
            tujuan='ditumpuk' if lewat_tumpukan else silo, berat_kg=2000, hpp_per_kg=0,
            tanggal=date.today(), jam=None, pk_purchase_batch_id=batch.id,
            bobot_final=True, jasa_id=jid)
        intake = await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.pk_purchase_batch_id==batch.id))
        if waktu:
            intake.waktu_masuk=waktu
            await db.commit()
        if lewat_tumpukan:
            await pindah_tumpukan_ke_silo(db, user=user, intake_id=intake.id,
                nama_silo=silo, berat=2000)
        return intake.id


async def test_dryer_belum_dinyalakan_tampil_tanpa_kode_lot(pg, dunia):
    async with pg() as db:
        own = await db.get(Dryer, dunia['dryer']); own.nama='Dryer Catur'
        foreign = Dryer(nama='Dryer Rahasia Budi', warehouse_id=dunia['g1'],
                        kapasitas_kg=50000, status='aktif')
        db.add(foreign); await db.commit()
    await _batch_dryer(pg, dunia, dryer=dunia['dryer'], jid=dunia['jasa1'], code='GB-TRANSIT-MESIN')
    await _batch_dryer(pg, dunia, dryer=foreign.id, jid=dunia['jasa3'], code='GB-RAHASIA-MESIN')
    b = await _bacaan(pg, dunia)
    row = next(r for r in b.transit if r.ruang_baca==('dryer',dunia['dryer']))
    assert row.kode == '' and row.utama == ('1.500', 'kg')
    assert all(r.ruang_baca!=('dryer',foreign.id) for r in b.transit)
    await _halaman(pg,dunia,['Dryer Catur','GB-TRANSIT-MESIN'],['Budi','GB-RAHASIA-MESIN'])


async def test_silo_gabah_beberapa_pesanan_sepemilik_memakai_data_produksi(pg, dunia):
    for code, jid in [('GB-TRANSIT-A1',dunia['jasa1']),('GB-TRANSIT-A2',dunia['jasa2'])]:
        await _isi_silo_g1(pg,dunia,huruf='A',kode=code,kg=1500,jasa_id=jid)
    await _isi_silo_g1(pg,dunia,huruf='B',kode='GB-RAHASIA-SILO',kg=3500,jasa_id=dunia['jasa3'])
    b = await _bacaan(pg, dunia)
    row = next(r for r in b.transit if r.ruang_baca==('silo_gabah',dunia['silo']['A']))
    async with pg() as db:
        native = next(r for r in (await berjalan.untuk_gudang1(db)).transit if r.kode=='Silo A')
    assert (row.kode,row.utama,row.anak,row.keadaan)==(native.kode,native.utama,native.anak,native.keadaan)
    assert len(row.anak)==2
    assert all(r.ruang_baca!=('silo_gabah',dunia['silo']['B']) for r in b.transit)
    await _halaman(pg,dunia,['Silo A','GB-TRANSIT-A1','GB-TRANSIT-A2'],['Budi','GB-RAHASIA-SILO'])


@pytest.mark.parametrize('lewat_tumpukan',[False,True],ids=['langsung','dari-tumpukan'])
async def test_silo_pk_menunggu_sosoh_tampil(pg, dunia, lewat_tumpukan):
    await _pk(pg,dunia,silo='C',jid=dunia['jasa1'],code='PKB-TRANSIT-C',lewat_tumpukan=lewat_tumpukan)
    await _pk(pg,dunia,silo='D',jid=dunia['jasa3'],code='PKB-RAHASIA-D')
    b=await _bacaan(pg,dunia)
    assert any(r.ruang_baca==('silo_pk',dunia['silo']['C']) for r in b.transit)
    assert all(r.ruang_baca!=('silo_pk',dunia['silo']['D']) for r in b.transit)
    await _halaman(pg,dunia,['Silo C','PKB-TRANSIT-C'],['Budi','PKB-RAHASIA-D'])


async def test_silo_menunggu_mesin_tidak_mengumumkan_proses_pelanggan_lain(pg, dunia):
    await _pk(pg,dunia,silo='C',jid=dunia['jasa1'],code='PKB-TRANSIT-C')
    await _pk(pg,dunia,silo='D',jid=dunia['jasa3'],code='PKB-RAHASIA-D')
    async with pg() as db:
        proc=PolishingProcess(kode_proses='POL-RAHASIA-BUDI',jasa_id=dunia['jasa3'],
            waktu_mulai=now_local(),status='proses',created_by=dunia['user'])
        db.add(proc);await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=proc.id,silo_id=dunia['silo']['D'],
            berat_awal_kg=2000,berat_masuk_kg=0))
        await db.commit()
        native=next(r for r in (await berjalan.untuk_gudang2(db)).transit if r.kode=='Silo C')
        assert 'POL-RAHASIA-BUDI' in native.keadaan
    b=await _bacaan(pg,dunia)
    row=next(r for r in b.transit if r.kode=='Silo C')
    assert 'mesin sosoh sedang dipakai' in row.keadaan
    assert 'POL-RAHASIA-BUDI' not in str(row)
    await _halaman(pg,dunia,['Silo C','PKB-TRANSIT-C'],['Budi','POL-RAHASIA-BUDI','PKB-RAHASIA-D'])


async def test_silo_label_pelanggan_sendiri_sumber_asing_tetap_ditolak(pg, dunia):
    await _isi_silo_g1(pg,dunia,huruf='A',kode='GB-SUMBER-RAHASIA',kg=4000,jasa_id=dunia['jasa3'])
    async with pg() as db:
        row=await db.scalar(select(SiloStorage).where(SiloStorage.silo_id==dunia['silo']['A']))
        row.jasa_id=dunia['jasa1'];await db.commit()
    b=await _bacaan(pg,dunia)
    assert all(r.ruang_baca!=('silo_gabah',dunia['silo']['A']) for r in b.transit)
    await _halaman(pg,dunia,[],['Budi','GB-SUMBER-RAHASIA'])


async def test_silo_pk_campuran_impor_tidak_lolos_hanya_karena_pemilik_terbaru(pg, dunia):
    # Fixture korup: produksi normal menolak mencampur dua pelanggan.
    await _pk(pg,dunia,silo='C',jid=dunia['jasa3'],code='PKB-CAMPUR-RAHASIA',waktu=now_local()-timedelta(minutes=2))
    async with pg() as db:
        batch=PkPurchaseBatch(kode_batch='PKB-LABEL-SENDIRI',jasa_id=dunia['jasa1'],
            berat_total_kg=1000,tanggal_pembelian=date.today(),waktu_pembelian=now_local(),input_by=dunia['user'])
        db.add(batch);await db.flush()
        db.add(PkGudang2Intake(sumber_tipe='beli_luar',pk_purchase_batch_id=batch.id,
            tujuan='silo',silo_id=dunia['silo']['C'],berat_kg=1000,hpp_per_kg=0,
            tanggal_masuk=date.today(),waktu_masuk=now_local(),input_by=dunia['user'],jasa_id=dunia['jasa1']))
        await db.commit()
    b=await _bacaan(pg,dunia)
    assert all(r.ruang_baca!=('silo_pk',dunia['silo']['C']) for r in b.transit)
    await _halaman(pg,dunia,[],['Budi','PKB-CAMPUR-RAHASIA'])


async def test_silo_dipakai_ulang_riwayat_asing_yang_sudah_habis_tidak_menghalangi(pg,dunia):
    dahulu=now_local()-timedelta(days=1)
    await _pk(pg,dunia,silo='C',jid=dunia['jasa3'],code='PKB-RIWAYAT-RAHASIA',waktu=dahulu)
    async with pg() as db:
        proc=PolishingProcess(kode_proses='POL-RIWAYAT-RAHASIA',jasa_id=dunia['jasa3'],
            waktu_mulai=dahulu+timedelta(minutes=1),waktu_selesai=dahulu+timedelta(hours=1),
            status='selesai',created_by=dunia['user'])
        db.add(proc);await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=proc.id,silo_id=dunia['silo']['C'],
            berat_awal_kg=2000,berat_masuk_kg=0,berat_akhir_kg=0,berat_terpakai_kg=2000))
        await db.commit()
    await _pk(pg,dunia,silo='C',jid=dunia['jasa1'],code='PKB-ISI-BARU-SENDIRI')
    b=await _bacaan(pg,dunia)
    assert any(r.ruang_baca==('silo_pk',dunia['silo']['C']) for r in b.transit)
    await _halaman(pg,dunia,['Silo C','PKB-ISI-BARU-SENDIRI'],['Budi','PKB-RIWAYAT-RAHASIA','POL-RIWAYAT-RAHASIA'])


async def test_transit_silo_tampil_di_pekerjaan_pelanggan(pg, dunia):
    # Regresi dari halaman HTTP: tidak mengandalkan atribut internal kartu.
    await _isi_silo_g1(pg,dunia,huruf='A',kode='GB-TRANSIT-TERLIHAT',kg=3000,jasa_id=dunia['jasa1'])
    await _halaman(pg,dunia,['Silo A','GB-TRANSIT-TERLIHAT'],['Budi'])


@pytest.mark.parametrize('jenis',['broken','beras','menir'])
@pytest.mark.parametrize('asing',[False,True],ids=['sumber-sendiri','label-sendiri-sumber-asing'])
async def test_bahan_sosoh_ulang_memeriksa_sumber_asli(pg,dunia,jenis,asing):
    from app.models import BerasKeSilo, BrokenKeSilo, ByproductStock, HasilSampingKeSilo
    async with pg() as db:
        proses=[]
        for code,jid in [('POL-SUMBER-SENDIRI',dunia['jasa1']),('POL-SUMBER-RAHASIA',dunia['jasa3'])]:
            proc=PolishingProcess(kode_proses=code,jasa_id=jid,waktu_mulai=now_local(),
                waktu_selesai=now_local(),status='selesai',created_by=dunia['user'])
            db.add(proc);await db.flush();proses.append(proc.id)
        source=proses[1 if asing else 0]
        common=dict(kode_pindah='PINDAH-BAHAN-UJI',silo_id=dunia['silo']['C'],berat_kg=500,
            tanggal=date.today(),waktu=now_local(),input_by=dunia['user'],jasa_id=dunia['jasa1'])
        if jenis=='broken':
            stock=ByproductStock(jenis_produk='broken',source_type='polishing',source_id=source,
                berat_kg=500,tanggal=date.today(),waktu=now_local(),input_by=dunia['user'],jasa_id=dunia['jasa1'])
            db.add(stock);await db.flush()
            db.add(BrokenKeSilo(byproduct_stock_id=stock.id,**common))
        elif jenis=='beras':
            db.add(BerasKeSilo(polishing_process_id=source,source_type='polishing',source_id=source,
                jenis='beras_putih',**common))
        else:
            db.add(HasilSampingKeSilo(polishing_process_id=source,jenis='menir',**common))
        await db.commit()
    b=await _bacaan(pg,dunia)
    assert any(r.ruang_baca==('silo_pk',dunia['silo']['C']) for r in b.transit) is not asing
    await _halaman(pg,dunia,[] if asing else ['Silo C','500'],['Budi','POL-SUMBER-RAHASIA'])
