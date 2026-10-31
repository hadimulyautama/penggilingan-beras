"""Perjalanan pelanggan baru memakai data nyata, pembatasan lama, dan dokumen asli."""
import pytest
from bs4 import BeautifulSoup

from tests.pg.test_portal_pelanggan import portal,client  # noqa: F401
from tests.pg.test_riwayat_qc_detail import qc  # noqa: F401
from tests.pg.test_gabung_jasa import dunia,_isi_silo_g1  # noqa: F401
from tests.pg.test_proses_aktif_detail import pengeringan,dryer_pabrik  # noqa: F401

pytestmark=pytest.mark.asyncio


async def test_beranda_mendahulukan_barang_dan_bukan_tugas_operator(pg,portal):
    async with client(portal.accounts[0]) as c:
        r=await c.get('/pelanggan/')
        assert r.status_code==200
        s=BeautifulSoup(r.text,'html.parser')
        assert s.select_one('main h1').get_text().startswith('Halo, Pemilik Portal A')
        assert s.select_one('.pelanggan-status h2')
        assert 'perlu tindakan' not in s.select_one('main').get_text().lower()
        assert 'Barang di pabrik' in r.text
        assert s.select_one('#komoditas-gabah > summary')
        assert 'Kabar terbaru' not in s.select_one('main').get_text()
        nav=s.select_one('.portal-sidebar nav')
        assert [a.get_text(strip=True) for a in nav.select('a')]==['Beranda','Barang masuk','Barang Saya','Proses Berjalan','Riwayat proses','Pengambilan barang','Dokumen']
        assert nav.select_one('[aria-current=page]').get_text(strip=True)=='Beranda'
        bawah=s.select_one('.portal-bawah')
        assert len(bawah.select('a'))==3 and bawah.select_one('button').get_text(strip=True).endswith('Menu')
        assert 'Rahasia Pelanggan B' not in r.text and 'Kabar rahasia B' not in r.text


async def test_jasa_barang_dan_tautan_lama_tetap_terbaca_tanpa_mutasi(pg,portal):
    async with client(portal.accounts[0]) as c:
        for path in ('/pelanggan/jasa-saya','/pelanggan/barang-saya','/pelanggan/riwayat-proses','/pelanggan/barang-masuk','/pelanggan/barang-keluar',
                     '/pelanggan/ringkasan?tab=stok','/pelanggan/ringkasan?tab=proses',
                     f'/pelanggan/jasa/pelanggan/{portal.owners[0].id}'):
            r=await c.get(path)
            assert r.status_code==200,path
            s=BeautifulSoup(r.text,'html.parser')
            assert not s.select('[data-post],[hx-post],[data-aksi],dialog')
            assert all(a['href'].startswith(('/pelanggan','#')) for a in s.select('a[href]'))
            assert 'LOT-RAHASIA-B' not in r.text and 'Rahasia seluruh pabrik' not in r.text
            assert all(f['action']=='/pelanggan/keluar' for f in s.select('form[method=post]'))
        page=await c.get('/pelanggan/jasa-saya')
        assert '/pelanggan/barang-masuk' in page.text and 'LOT-QC-DETAIL' in page.text
        assert '/pelanggan/laporan' in page.text
        assert (await c.get('/pelanggan/barang-saya?pelanggan_id='+str(portal.owners[1].id))).status_code==404
        assert (await c.get('/pelanggan/jasa-saya?pelanggan_id='+str(portal.owners[1].id))).status_code==404


async def test_pelanggan_tanpa_data_tetap_diberi_petunjuk(pg,portal):
    async with client(portal.accounts[2]) as c:
        for path in ('/pelanggan/','/pelanggan/jasa-saya','/pelanggan/barang-saya'):
            r=await c.get(path)
            assert r.status_code==200
            assert 'Rahasia' not in r.text and 'LOT-QC-DETAIL' not in r.text
        home=(await c.get('/pelanggan/')).text
        assert 'Belum ada barang atau pesanan' in home
        assert 'hubungi petugas' in home


async def test_pendinginan_belum_selesai_tidak_disebut_proses_selesai(pg,portal):
    from app.models import DryingLot
    async with pg() as db:
        dry=await db.get(DryingLot,portal.process[0]['pengeringan'])
        dry.waktu_selesai_pendinginan=None
        await db.commit()
    async with client(portal.accounts[0]) as c:
        home=await c.get('/pelanggan/')
        assert 'Sedang diproses' in home.text and 'Pendinginan' in home.text
        jasa=await c.get('/pelanggan/jasa-saya')
        assert '/pelanggan/proses-aktif/pendinginan/PGR-PORTAL-0' in jasa.text


async def test_transit_tampil_di_beranda_dan_barang_tanpa_data_pelanggan_lain(pg,dunia):
    from app.models.portal import PortalAccount
    await _isi_silo_g1(pg,dunia,huruf='A',kode='GB-UX-SILO',kg=10000,jasa_id=dunia['jasa1'])
    async with pg() as db:
        akun_uji=[PortalAccount(username='ux-transit-'+str(pid),pelanggan_id=pid,
            password_hash='unused-test-hash',active=True,token_version=1)
            for pid in (dunia['catur'],dunia['budi'])]
        db.add_all(akun_uji);await db.commit()
    async with client(akun_uji[0]) as c:
        for path in ('/pelanggan/','/pelanggan/jasa-saya','/pelanggan/barang-saya'):
            r=await c.get(path)
            assert r.status_code==200
            assert 'Silo A' in r.text and '10.000' in r.text
        home=BeautifulSoup((await c.get('/pelanggan/')).text,'html.parser')
        assert 'Menunggu proses' in home.select_one('.pelanggan-status').get_text()
    async with client(akun_uji[1]) as c:
        for path in ('/pelanggan/','/pelanggan/jasa-saya','/pelanggan/barang-saya'):
            r=await c.get(path)
            assert r.status_code==200 and 'GB-UX-SILO' not in r.text and 'Silo A' not in r.text


async def test_hasil_giling_berjalan_tampil_sementara_tanpa_persen_selesai(pg,portal):
    from app.models import MillingProcess,MillingProgressLog
    from app.database import now_local
    async with pg() as db:
        mill=await db.get(MillingProcess,portal.process[0]['giling'])
        mill.status='proses';mill.waktu_selesai=None
        db.add(MillingProgressLog(milling_process_id=mill.id,berat_kumulatif_kg=2500,
            waktu_update=now_local(),input_by=mill.created_by))
        await db.commit()
    async with client(portal.accounts[0]) as c:
        for path in ('/pelanggan/','/pelanggan/jasa-saya'):
            r=await c.get(path)
            assert r.status_code==200
            s=BeautifulSoup(r.text,'html.parser').select_one('.pelanggan-progres')
            assert s and '2.500' in s.get_text() and 'Hasil sementara' in s.get_text()
            assert 'bukan persentase selesai' in s.get_text()
            assert not s.select('progress')


async def test_kemajuan_pengeringan_sama_dengan_perhitungan_produksi(pg,pengeringan):
    from sqlalchemy import select
    from app.models import Pelanggan,Jasa,DryingLot,PurchaseBatch,User
    from app.models.portal import PortalAccount
    from app.penggilingan.gudang1.services import drying
    async with pg() as db:
        owner=Pelanggan(nama_pelanggan='Pemilik Pengeringan UX');db.add(owner);await db.flush()
        order=Jasa(kode='JAS-UX-PGR',pelanggan_id=owner.id);db.add(order);await db.flush()
        dry=await db.get(DryingLot,pengeringan['id']);dry.jasa_id=order.id
        batch=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch==pengeringan['batch']))
        batch.jasa_id=order.id;batch.supplier_id=None
        account=PortalAccount(username='ux-pengeringan',pelanggan_id=owner.id,
            password_hash='unused-test-hash',active=True,token_version=1)
        db.add(account);await db.commit()
        await drying.log_moisture(db,user=await db.get(User,pengeringan['user']),
            kode_lot=pengeringan['kode'],sampel=[15.5]*4,indikator=16)
    async with client(account) as c:
        for path in ('/pelanggan/','/pelanggan/jasa-saya'):
            r=await c.get(path)
            assert r.status_code==200
            s=BeautifulSoup(r.text,'html.parser').select_one('.pelanggan-progres')
            assert s and 'Kemajuan menuju target kadar air' in s.get_text()
            assert s.select_one('progress')['value']=='0.5'
            assert '50%' in s.get_text() and '15.5%' in s.get_text() and '13%' in s.get_text()


async def test_dokumen_hanya_menampilkan_rekap_utama_pada_rantai_gabungan(pg,dunia):
    from app.models import Jasa,User
    from app.models.portal import PortalAccount
    from app.services.jasa import gabung_jasa
    async with pg() as db:
        tujuan=Jasa(kode='JAS-UX-GABUNGAN',pelanggan_id=dunia['catur'])
        terpisah=Jasa(kode='JAS-UX-TERPISAH',pelanggan_id=dunia['catur'])
        akun=PortalAccount(username='ux-rekap-gabungan',pelanggan_id=dunia['catur'],
            password_hash='unused-test-hash',active=True,token_version=1)
        db.add_all([tujuan,terpisah,akun]);await db.flush()
        user=await db.get(User,dunia['user'])
        await gabung_jasa(db,user=user,dari_id=dunia['jasa1'],ke_id=dunia['jasa2'])
        await gabung_jasa(db,user=user,dari_id=dunia['jasa2'],ke_id=tujuan.id)
        await db.commit()
    async with client(akun) as c:
        response=await c.get('/pelanggan/laporan')
        assert response.status_code==200
        s=BeautifulSoup(response.text,'html.parser')
        rekap=s.find('h2',string='Rekap barang jasa').find_parent('section')
        assert [h.get_text(strip=True) for h in rekap.select('h3')]==['JAS-UX-TERPISAH','JAS-UX-GABUNGAN']
        assert len(rekap.select(f'a[href="/pelanggan/jasa/{tujuan.id}/nota"]'))==1
        assert 'JAS-2610-301' not in rekap.get_text() and 'JAS-2610-302' not in rekap.get_text()
        assert 'JAS-2610-303' not in response.text  # milik pelanggan lain
        perjalanan=await c.get('/pelanggan/jasa-saya')
        assert perjalanan.status_code==200
        assert 'Referensi jasa' not in perjalanan.text and 'JAS-2610-301' not in perjalanan.text
        # Nomor asal masih sah sebagai jejak dokumen lama, bukan kartu tambahan.
        assert (await c.get(f'/pelanggan/jasa/{dunia["jasa1"]}/nota')).status_code==200
        pintasan=await c.get(f'/pelanggan/jasa/{tujuan.id}')
        assert pintasan.status_code==303
        assert pintasan.headers['location']==f'/pelanggan/jasa/{tujuan.id}/nota'
    async with pg() as db:
        assert (await db.get(Jasa,dunia['jasa1'])).status=='digabung'
        assert (await db.get(Jasa,dunia['jasa2'])).digabung_ke_id==tujuan.id
