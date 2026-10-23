"""Customer portal: native reads/PDFs with server-side tenant boundaries."""
from io import BytesIO
from types import SimpleNamespace
import httpx
import pytest
import pytest_asyncio
from bs4 import BeautifulSoup
from pypdf import PdfReader
from sqlalchemy import select
from app.database import now_local
from app.models import (Pelanggan,Jasa,User,PurchaseBatch,PkPurchaseBatch,MillingProcess,
    PolishingProcess,PolishingSiloUsage,DryingLot,InternalTransfer,Silo,Notification,Warehouse)
from app.models.portal import PortalAccount,PortalNotificationRead
from app.web import csrf,security
from app.web.portal.security import issue,COOKIE,require_customer
from app.main import app
from tests.pg.test_riwayat_qc_detail import qc

pytestmark=pytest.mark.asyncio


@pytest_asyncio.fixture
async def portal(pg,qc):
    async with pg() as db:
        owners=[Pelanggan(nama_pelanggan=n) for n in ('Pemilik Portal A','Rahasia Pelanggan B','Pelanggan Tanpa Data')]
        db.add_all(owners);await db.flush()
        orders=[Jasa(kode='JAS-PORTAL-'+str(i),pelanggan_id=p.id) for i,p in enumerate(owners[:2])]
        db.add_all(orders);await db.flush()
        for model in (PurchaseBatch,PkPurchaseBatch,MillingProcess):
            for row in (await db.scalars(select(model))).all():
                row.jasa_id=orders[0].id
                if hasattr(row,'supplier_id'):row.supplier_id=None
        mill=await db.get(MillingProcess,qc['proc']);mill.status='selesai';mill.waktu_selesai=now_local();mill.berat_gabah_masuk_kg=10000;mill.berat_output_final_kg=6500
        silo=await db.scalar(select(Silo).order_by(Silo.id))
        othermill=MillingProcess(kode_proses='LOT-RAHASIA-B',silo_id=silo.id,waktu_mulai=now_local(),waktu_selesai=now_local(),status='selesai',created_by=qc['user'],jasa_id=orders[1].id)
        db.add(othermill);await db.flush()
        g2=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=="g2"))
        process={}
        for index,(owner,order,pmill) in enumerate(zip(owners,orders,[mill,othermill])):
            dry=DryingLot(kode_lot='PGR-PORTAL-'+str(index),created_by=qc['user'],jasa_id=order.id,status='selesai',waktu_mulai_pengeringan=now_local(),waktu_selesai_pendinginan=now_local())
            polish=PolishingProcess(kode_proses='POL-PORTAL-'+str(index),created_by=qc['user'],jasa_id=order.id,status='selesai',waktu_mulai=now_local(),waktu_selesai=now_local())
            transfer=InternalTransfer(kode_transfer='TRF-PORTAL-'+str(index),milling_process_id=pmill.id,berat_kg=500,lokasi_tujuan='ditumpuk',waktu=now_local(),created_by=qc['user'],jasa_id=order.id)
            db.add_all([dry,polish,transfer]);await db.flush()
            used_silo=Silo(nama_silo='Portal Silo '+str(index),warehouse_id=g2.id,jenis_isi='pk',status='kosong')
            db.add(used_silo);await db.flush()
            db.add(PolishingSiloUsage(polishing_process_id=polish.id,silo_id=used_silo.id,berat_awal_kg=1000,berat_masuk_kg=0,berat_akhir_kg=0))
            process[index]={'giling':pmill.id,'pengeringan':dry.id,'sosoh':polish.id,'transfer':transfer.id}
        accounts=[PortalAccount(username='portal-'+str(i),pelanggan_id=p.id,password_hash=security.hash_sandi('rahasia123'),active=True,token_version=1) for i,p in enumerate(owners)]
        db.add_all(accounts);await db.flush()
        notices=[Notification(tipe='hasil_proses',table_name='milling_process',record_id=m.id,pesan=msg,prioritas='hijau',status='baru',target_role='admin') for m,msg in [(mill,'Hasil milik A'),(othermill,'Kabar rahasia B')]]
        notices.append(Notification(tipe='umum',pesan='Rahasia seluruh pabrik',prioritas='hijau',status='baru',target_role='admin'))
        db.add_all(notices);await db.commit()
        return SimpleNamespace(accounts=accounts,owners=owners,orders=orders,process=process,notices=notices)


def client(account=None):
    c=httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji')
    if account:c.cookies.set(COOKIE,issue(account))
    return c


def token(response):
    return BeautifulSoup(response.text,'html.parser').select_one('[name=_csrf]')['value']


async def test_login_csrf_is_separate_from_staff_and_session_revocation(pg,portal):
    async with client() as c:
        assert (await c.get('/pelanggan')).status_code==303
        assert (await c.get('/pelanggan/laporan')).status_code==401
        page=await c.get('/pelanggan/masuk')
        assert (await c.post('/pelanggan/masuk',data={'username':'portal-0','sandi':'rahasia123'})).status_code==403
        r=await c.post('/pelanggan/masuk',data={'username':'PORTAL-0','sandi':'rahasia123','_csrf':token(page)})
        assert r.status_code==303 and COOKIE in c.cookies
        assert 'HttpOnly' in r.headers.get_list('set-cookie')[0]
        assert (await c.get('/pelanggan')).status_code==200
        # Renaming the portal cookie never converts it into a staff session.
        c.cookies.set(security.NAMA_COOKIE,c.cookies.get(COOKIE))
        assert (await c.get('/riwayat-giling')).status_code==303
        async with pg() as db:
            a=await db.get(PortalAccount,portal.accounts[0].id);a.token_version+=1;await db.commit()
        assert (await c.get('/pelanggan/laporan')).status_code==401


async def test_all_menus_are_scoped_reads_with_native_get_filters(pg,portal):
    paths=['ringkasan','pekerjaan','pekerjaan?tab=berjalan','stok','stok?tab=produk','stok?tab=karung',
           'barang-masuk','barang-masuk?status=diterima','barang-keluar','retur','riwayat-giling',
           'riwayat-pengeringan','riwayat-sosoh','riwayat-transfer','riwayat-qc/gabah-basah',
           'riwayat-qc/gabah-kering','riwayat-qc/pk-luar','riwayat-qc/pk-hasil-giling','laporan','kabar','audit']
    async with client(portal.accounts[0]) as c:
        for path in paths:
            r=await c.get('/pelanggan/'+path)
            assert r.status_code==200,(path,r.text[:300])
            assert all(x not in r.text for x in ('Rahasia Pelanggan B','LOT-RAHASIA-B','Kabar rahasia B','Rahasia seluruh pabrik'))
            assert 'no-store' in r.headers['cache-control']
            soup=BeautifulSoup(r.text,'html.parser')
            for f in soup.select('form[method=post]'):
                assert f['action']=='/pelanggan/keluar' or f['action'].startswith('/pelanggan/kabar/')
            assert not soup.select('[data-post],[hx-post],[data-aksi],dialog')
            for a in soup.select('a[href]'):
                assert a['href'].startswith(('/pelanggan','#')),(path,a)
        qcpage=await c.get('/pelanggan/riwayat-qc/pk-luar/PKB-QC-DETAIL')
        assert 'Contoh catatan laboratorium' in qcpage.text
        assert 'Pemilik Portal A' in qcpage.text


@pytest.mark.parametrize('kind',['giling','pengeringan','sosoh','transfer'])
async def test_native_detail_and_foreign_id_pdf_guards(pg,portal,kind):
    own=portal.process[0][kind];foreign=portal.process[1][kind]
    async with client(portal.accounts[0]) as c:
        assert (await c.get(f'/pelanggan/riwayat-{kind}/{own}')).status_code==200
        for suffix in ('','/laporan','/laporan.pdf','/laporan.pdf?unduh=1'):
            assert (await c.get(f'/pelanggan/riwayat-{kind}/{foreign}{suffix}')).status_code==404
        assert (await c.get(f'/pelanggan/jasa/pelanggan/{portal.owners[1].id}')).status_code==404
        assert (await c.get('/pelanggan/stok?pelanggan_id='+str(portal.owners[1].id))).status_code==404
        assert (await c.get('/pelanggan/stok?pelanggan_id=9&pelanggan_id='+str(portal.owners[1].id))).status_code==404
        assert (await c.get('/pelanggan/riwayat-qc/pk-hasil-giling/LOT-RAHASIA-B')).status_code==404
        assert (await c.get('/pelanggan/stok/pk/detail?gudang=g1&kode=LOT-RAHASIA-B')).status_code==404
        assert (await c.get('/pelanggan/proses-aktif/giling/LOT-RAHASIA-B')).status_code==404


@pytest.mark.parametrize('kind',['giling','pengeringan','sosoh'])
async def test_pdf_uses_exact_production_composer_and_page_content(pg,portal,kind,monkeypatch):
    from app.web import layar_riwayat as h,laporan_sosoh
    from app import database
    # Both renderings represent the same export instant; crossing a minute
    # boundary must not turn the production's print timestamp into a flaky diff.
    frozen=now_local()
    from datetime import datetime
    class ExportClock(datetime):
        @classmethod
        def now(cls,tz=None):return frozen.astimezone(tz) if tz else frozen.replace(tzinfo=None)
    monkeypatch.setattr(h,'datetime',ExportClock)
    monkeypatch.setattr(laporan_sosoh,'datetime',ExportClock)
    ident=portal.process[0][kind]
    if kind=='giling':expected=h._pdf_laporan_giling(await h._ambil_data_laporan_giling(ident))
    elif kind=='sosoh':expected=laporan_sosoh.buat_pdf(await laporan_sosoh.ambil_data(ident))
    else:expected=(await h.laporan_pengeringan_pdf(ident)).body
    async with client(portal.accounts[0]) as c:
        result=await c.get(f'/pelanggan/riwayat-{kind}/{ident}/laporan.pdf')
        assert result.status_code==200 and result.headers['content-type']=='application/pdf'
        a,b=PdfReader(BytesIO(expected)),PdfReader(BytesIO(result.content))
        assert len(a.pages)==len(b.pages)
        for x,y in zip(a.pages,b.pages):
            assert x.extract_text()==y.extract_text()
            assert x.get_contents().get_data()==y.get_contents().get_data()
        downloaded=await c.get(f'/pelanggan/riwayat-{kind}/{ident}/laporan.pdf?unduh=1')
        assert downloaded.headers['content-disposition'].startswith('attachment;')


async def test_mutations_and_arbitrary_forwarding_are_never_authorized(pg,portal):
    async with client(portal.accounts[0]) as c:
        page=await c.get('/pelanggan/laporan');stamp=token(page)
        for path in ('/pelanggan/pekerjaan','/pelanggan/api/aksi/giling','/pelanggan/riwayat-giling/1/koreksi',
                     '/api/aksi/giling','/riwayat-giling/1/koreksi','/audit/batalkan','/barang-keluar/baru'):
            r=await c.post(path,data={'_csrf':stamp,'berat':1})
            assert r.status_code in (303,401,403,404,405)
        # A valid staff CSRF nonce still cannot authorize a customer cookie.
        blocked=await c.post('/audit/batalkan',data={'_csrf':c.cookies.get(csrf.NAMA_COOKIE)})
        assert blocked.status_code in (303,401,403)
        for path in ('/pelanggan/pengguna','/pelanggan/api/laporan/produksi','/pelanggan/../pengaturan','/pelanggan/stok?buka=ambil_jasa'):
            assert (await c.get(path)).status_code in (303,401,403,404)


async def test_notice_read_state_is_owned_and_empty_scope_never_reads_global_messages(pg,portal):
    async with client(portal.accounts[2]) as c:
        r=await c.get('/pelanggan/kabar')
        assert r.status_code==200 and 'Tidak ada kabar' in r.text
        assert 'Hasil milik A' not in r.text and 'Rahasia seluruh pabrik' not in r.text
    async with client(portal.accounts[0]) as c:
        r=await c.get('/pelanggan/kabar');stamp=token(r)
        assert (await c.post('/pelanggan/kabar/status',data={'_csrf':stamp,'id':portal.notices[1].id,'status':'dibaca'})).status_code==404
        assert (await c.post('/pelanggan/kabar/status',data={'_csrf':stamp,'id':portal.notices[0].id,'status':'dibaca'})).status_code==303
    async with pg() as db:
        records=(await db.scalars(select(PortalNotificationRead))).all()
        assert len(records)==1 and records[0].notification_id==portal.notices[0].id
        account=await db.get(PortalAccount,portal.accounts[0].id);account.pelanggan_id=portal.owners[1].id;await db.commit()
    async with client(portal.accounts[0]) as c:
        # Old object issues the OLD customer binding in the signed token.
        assert (await c.get('/pelanggan/laporan')).status_code==401


async def test_mixed_source_is_denied_before_native_detail_or_pdf(pg,portal):
    from app.models import DryingLotBatch
    async with pg() as db:
        other=PurchaseBatch(kode_batch='GB-MIX-OTHER',supplier_id=None,jasa_id=portal.orders[1].id,
            berat_total_kg=500,kondisi_gabah='basah',tanggal_pembelian=now_local().date(),
            waktu_pembelian=now_local(),input_by=1,status_batch='baru',sumber_berat='manual')
        db.add(other);await db.flush()
        db.add(DryingLotBatch(drying_lot_id=portal.process[0]['pengeringan'],purchase_batch_id=other.id))
        await db.commit()
    async with client(portal.accounts[0]) as c:
        own=portal.process[0]['pengeringan']
        for suffix in ('','/laporan','/laporan.pdf'):
            assert (await c.get(f'/pelanggan/riwayat-pengeringan/{own}'+suffix)).status_code==404
        assert 'PGR-PORTAL-0' not in (await c.get('/pelanggan/riwayat-pengeringan')).text
        assert 'GB-MIX-OTHER' not in (await c.get('/pelanggan')).text


async def test_own_history_does_not_disappear_behind_foreign_pagination(pg,portal):
    from app.models import MillingQcLog
    async with pg() as db:
        silo=await db.scalar(select(Silo).order_by(Silo.id))
        # Native lists show thirty rows; insert more than a page of newer foreign rows.
        for n in range(35):
            db.add(MillingProcess(kode_proses=f'LOT-FOREIGN-{n:02}',silo_id=silo.id,
                created_by=1,jasa_id=portal.orders[1].id,status='selesai',
                waktu_mulai=now_local(),waktu_selesai=now_local()))
        await db.commit()
    async with client(portal.accounts[0]) as c:
        r=await c.get('/pelanggan/riwayat-giling')
        assert 'LOT-QC-DETAIL' in r.text and 'LOT-FOREIGN' not in r.text


async def test_empty_customer_and_disabled_account(pg,portal):
    async with client(portal.accounts[2]) as c:
        assert (await c.get('/pelanggan')).status_code==200
        assert 'Belum ada barang atau pesanan' in (await c.get('/pelanggan')).text
        for path in ('stok','pekerjaan','laporan','retur','barang-masuk','kabar'):
            r=await c.get('/pelanggan/'+path)
            assert r.status_code==200 and 'Pemilik Portal A' not in r.text
        async with pg() as db:
            account=await db.get(PortalAccount,portal.accounts[2].id);account.active=False;await db.commit()
        assert (await c.get('/pelanggan/laporan')).status_code==401


from tests.pg.test_pindah_kepemilikan_produk import titipan


async def test_ownership_audit_stays_bound_after_entire_stock_changes_owner(pg,titipan):
    from app.penggilingan.inventory.finished_goods import pindah_kepemilikan_barang_jadi
    from app.models.portal import PortalOwnershipEvent
    async with pg() as db:
        u=await db.get(User,titipan['user'])
        await pindah_kepemilikan_barang_jadi(db,user=u,sku_id=titipan['sku_id'],
            standard_id=titipan['std_id'],jasa_id=titipan['jasa1'],karung=20)
        records=(await db.scalars(select(PortalOwnershipEvent))).all()
        assert len(records)==1 and records[0].pelanggan_id==titipan['pelanggan_id']
        account=PortalAccount(username='bu-sri',pelanggan_id=titipan['pelanggan_id'],password_hash=security.hash_sandi('rahasia123'))
        other=Pelanggan(nama_pelanggan='Orang berbeda');db.add(other);await db.flush()
        second=PortalAccount(username='lain',pelanggan_id=other.id,password_hash=security.hash_sandi('rahasia123'))
        db.add_all([account,second]);await db.commit()
    async with client(account) as c:
        r=await c.get('/pelanggan/audit?rentang=semua')
        assert '20 karung (500kg)' in r.text and 'pabrik' in r.text
    async with client(second) as c:
        assert '20 karung (500kg)' not in (await c.get('/pelanggan/audit?rentang=semua')).text


async def test_shipping_uses_item_ownership_and_rejects_mixed_headers(pg,portal):
    from app.models import OutgoingRecord,OutgoingItem
    async with pg() as db:
        records=[]
        for n in range(3):
            r=OutgoingRecord(kode='OUT-PORTAL-'+str(n),pelanggan_id=None if n==0 else portal.owners[0].id,
                tanggal=now_local().date(),waktu=now_local(),input_by=1,status='selesai')
            db.add(r);await db.flush();records.append(r)
            for jid in ([portal.orders[0].id] if n==0 else [portal.orders[1].id] if n==1 else [portal.orders[0].id,portal.orders[1].id]):
                db.add(OutgoingItem(outgoing_record_id=r.id,item_type='byproduct',jasa_id=jid,berat_kg=10))
        await db.commit()
    async with client(portal.accounts[0]) as c:
        assert (await c.get('/pelanggan/barang-keluar/'+str(records[0].id))).status_code==200
        for r in records[1:]:assert (await c.get('/pelanggan/barang-keluar/'+str(r.id))).status_code==404
        page=await c.get('/pelanggan/barang-keluar')
        assert 'OUT-PORTAL-0' in page.text and 'OUT-PORTAL-1' not in page.text and 'OUT-PORTAL-2' not in page.text


async def test_native_transfer_related_history_is_scoped_before_pagination(pg,portal):
    async with pg() as db:
        own=await db.get(InternalTransfer,portal.process[0]['transfer'])
        db.add(InternalTransfer(kode_transfer='TRF-FOREIGN-SAME-LOT',milling_process_id=own.milling_process_id,
            berat_kg=40,lokasi_tujuan='ditumpuk',waktu=now_local(),created_by=own.created_by,jasa_id=portal.orders[1].id))
        await db.commit()
    async with client(portal.accounts[0]) as c:
        for tab in ('ringkasan','bahan','permintaan','riwayat'):
            r=await c.get(f"/pelanggan/riwayat-transfer/{portal.process[0]['transfer']}?tab_detail={tab}")
            assert r.status_code==200
            assert 'TRF-FOREIGN-SAME-LOT' not in r.text
            assert not BeautifulSoup(r.text,'html.parser').select('[data-post],dialog')
