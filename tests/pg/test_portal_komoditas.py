"""Jumlah per komoditas memakai saldo lokasi; batch asal bukan tambahan stok."""
from datetime import date
from decimal import Decimal

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

from app.database import now_local
from app.models import PurchaseBatch,PkPurchaseBatch,PkGudang2Intake,User
from app.services import jasa_pelanggan
from app.web.portal.barang import baca
from app.web.portal.scope import load_scope
from app.web.portal.security import CustomerReader
from tests.pg.test_gabung_jasa import dunia,_isi_silo_g1  # noqa: F401
from tests.pg.test_portal_transit import _pk,_batch_dryer,_akun
from tests.pg.test_portal_pelanggan import client

pytestmark=pytest.mark.asyncio


async def ringkasan(pg,dunia):
    scope=await load_scope(CustomerReader(1,dunia['catur'],'Catur'))
    async with pg() as db:
        d=await jasa_pelanggan.pelanggan(db,dunia['catur'],rinci=False,read_scope=scope)
        return await baca(db,scope,d)


async def test_total_gabah_lintas_lokasi_bisa_dibuka_per_batch(pg,dunia):
    for kode,kg,jid in [('GB-RINGKAS-A',6000,dunia['jasa1']),('GB-RINGKAS-B',4000,dunia['jasa2'])]:
        await _isi_silo_g1(pg,dunia,huruf='A',kode=kode,kg=kg,jasa_id=jid)
    await _isi_silo_g1(pg,dunia,huruf='B',kode='GB-RAHASIA-LAIN',kg=7000,jasa_id=dunia['jasa3'])
    await _batch_dryer(pg,dunia,dryer=dunia['dryer'],jid=dunia['jasa1'],code='GB-RINGKAS-DRYER')
    async with pg() as db:
        db.add(PurchaseBatch(kode_batch='GB-RINGKAS-TUNGGU',jasa_id=dunia['jasa1'],berat_total_kg=2000,
            kondisi_gabah='basah',tanggal_pembelian=date.today(),waktu_pembelian=now_local(),
            input_by=dunia['user'],flag_unverified=False,sumber_berat='timbangan',status_batch='baru'))
        await db.commit()
    g=await ringkasan(pg,dunia)
    assert len(g)==1 and g[0]['kunci']=='gabah' and g[0]['kg']==Decimal('13500')
    assert len(g[0]['rincian'])==4
    assert {b['kode'] for r in g[0]['rincian'] for b in r['asal']}=={
        'GB-RINGKAS-A','GB-RINGKAS-B','GB-RINGKAS-DRYER','GB-RINGKAS-TUNGGU'}
    async with client(await _akun(pg,dunia)) as c:
        for path in ('/pelanggan/','/pelanggan/barang-saya'):
            response=await c.get(path);assert response.status_code==200
            s=BeautifulSoup(response.text,'html.parser')
            assert '13.500 kg' in s.select_one('#komoditas-gabah>summary').get_text()
            assert len(s.select('#komoditas-gabah .pelanggan-batch'))==4
            assert 'GB-RAHASIA-LAIN' not in response.text and 'Kabar terbaru' not in s.main.get_text()
            assert s.select_one('#komoditas-gabah .pelanggan-asal a')['href'].startswith('/pelanggan/')


async def test_pk_tumpukan_dan_silo_dijumlah_setelah_pemindahan_parsial(pg,dunia):
    from app.penggilingan.gudang2.service import _add_intake,pindah_tumpukan_ke_silo
    async with pg() as db:
        pk=PkPurchaseBatch(kode_batch='PKB-RINGKAS',jasa_id=dunia['jasa1'],berat_total_kg=2000,
            tanggal_pembelian=date.today(),waktu_pembelian=now_local(),input_by=dunia['user'],
            status_batch='diterima',sumber_berat='timbangan')
        db.add(pk);await db.flush();user=await db.get(User,dunia['user'])
        await _add_intake(db,user=user,sumber_tipe='beli_luar',tujuan='ditumpuk',berat_kg=2000,
            hpp_per_kg=0,tanggal=date.today(),jam=None,pk_purchase_batch_id=pk.id,
            bobot_final=True,jasa_id=dunia['jasa1'])
        intake=await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.pk_purchase_batch_id==pk.id))
        await pindah_tumpukan_ke_silo(db,user=user,intake_id=intake.id,nama_silo='C',berat=750)
    await _pk(pg,dunia,silo='D',jid=dunia['jasa3'],code='PKB-RAHASIA-D')
    g=await ringkasan(pg,dunia)
    pk=next(r for r in g if r['kunci']=='pk')
    assert pk['kg']==2000 and len(pk['rincian'])==2
    assert sorted(Decimal(str(r['kg'])) for r in pk['rincian'])==[750,1250]
    async with client(await _akun(pg,dunia)) as c:
        page=await c.get('/pelanggan/')
        assert page.status_code==200
        assert 'PKB-RAHASIA-D' not in page.text
        assert '2.000 kg' in BeautifulSoup(page.text,'html.parser').select_one('#komoditas-pk>summary').get_text()


async def test_bobot_gabah_belum_diukur_tidak_dijadikan_nol(pg,dunia):
    async with pg() as db:
        db.add(PurchaseBatch(kode_batch='GB-BELUM-DITIMBANG',jasa_id=dunia['jasa1'],berat_total_kg=None,
            kondisi_gabah='basah',tanggal_pembelian=date.today(),waktu_pembelian=now_local(),
            input_by=dunia['user'],flag_unverified=False,sumber_berat='menunggu',status_batch='baru'))
        await db.commit()
    g=await ringkasan(pg,dunia)
    assert g[0]['kg'] is None and g[0]['belum_diukur']==1
    async with client(await _akun(pg,dunia)) as c:
        page=await c.get('/pelanggan/')
        s=BeautifulSoup(page.text,'html.parser')
        assert 'Belum ditimbang' in s.select_one('#komoditas-gabah>summary').get_text()


@pytest.mark.parametrize('asing',[False,True],ids=['milik-pelanggan','sumber-pelanggan-lain'])
async def test_silo_campuran_pk_dan_beras_mengikuti_komposisi_dan_scope(pg,dunia,asing):
    from app.models import BerasKeSilo,PolishingProcess,PolishingOutputLog
    await _pk(pg,dunia,silo='C',jid=dunia['jasa1'],code='PKB-CAMPUR-SENDIRI')
    async with pg() as db:
        p=PolishingProcess(kode_proses='POL-ASAL-BERAS',jasa_id=dunia['jasa3'] if asing else dunia['jasa1'],
            status='selesai',waktu_mulai=now_local(),waktu_selesai=now_local(),created_by=dunia['user'])
        db.add(p);await db.flush()
        db.add(PolishingOutputLog(polishing_process_id=p.id,jenis='medium',berat_kg=1000,
            waktu_update=now_local(),input_by=dunia['user']))
        db.add(BerasKeSilo(kode_pindah='BKS-RINGKAS',silo_id=dunia['silo']['C'],berat_kg=500,
            tanggal=date.today(),waktu=now_local(),input_by=dunia['user'],jasa_id=dunia['jasa1'],
            polishing_process_id=p.id,source_type='polishing',source_id=p.id,jenis='medium'))
        await db.commit()
    g=await ringkasan(pg,dunia)
    silo=[(k['kunci'],r) for k in g for r in k['rincian'] if r['identitas'][0]=='silo-g2']
    if asing:
        assert not silo
    else:
        assert {(k,Decimal(str(r['kg']))) for k,r in silo}=={('pk',Decimal(2000)),('beras',Decimal(500))}
        beras=next(k for k in g if k['kunci']=='beras')
        assert beras['kg']==1000  # 500 masih di luar silo + 500 di silo
        assert any(b['kode']=='POL-ASAL-BERAS' for _,r in silo for b in r['asal'])
    async with client(await _akun(pg,dunia)) as c:
        home=await c.get('/pelanggan/')
        assert home.status_code==200
        if asing:assert 'POL-ASAL-BERAS' not in home.text


async def test_silo_dipakai_ulang_hanya_menampilkan_asal_isian_sekarang(pg,dunia):
    from tests.pg.test_portal_transit import test_silo_dipakai_ulang_riwayat_asing_yang_sudah_habis_tidak_menghalangi as siapkan
    await siapkan(pg,dunia)
    g=await ringkasan(pg,dunia)
    pk=next(k for k in g if k['kunci']=='pk')
    assert pk['kg']==2000
    assert {b['kode'] for r in pk['rincian'] for b in r['asal']}=={'PKB-ISI-BARU-SENDIRI'}


async def test_pk_di_silo_belum_diukur_tidak_hilang_dari_ringkasan(pg,dunia):
    from app.penggilingan.gudang2.service import _add_intake
    async with pg() as db:
        pk=PkPurchaseBatch(kode_batch='PKB-BELUM-DIUKUR',jasa_id=dunia['jasa1'],berat_total_kg=None,
            tanggal_pembelian=date.today(),waktu_pembelian=now_local(),input_by=dunia['user'],
            status_batch='diterima',sumber_berat='menunggu')
        db.add(pk);await db.flush()
        await _add_intake(db,user=await db.get(User,dunia['user']),sumber_tipe='beli_luar',
            tujuan='C',berat_kg=None,hpp_per_kg=0,tanggal=date.today(),jam=None,
            pk_purchase_batch_id=pk.id,bobot_final=False,jasa_id=dunia['jasa1'])
    g=await ringkasan(pg,dunia)
    pk=next(k for k in g if k['kunci']=='pk')
    assert pk['kg'] is None and pk['belum_diukur']==1
