"""Angka detail tetap native; struktur dan tindakan khusus pelanggan."""
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select
from app.models import PkPurchaseBatch,User,MillingProcess,MillingProgressLog,PolishingProcess,PolishingSiloUsage,PolishingOutputLog
from app.database import now_local
from tests.pg.test_portal_pelanggan import portal,client  # noqa: F401
from tests.pg.test_riwayat_qc_detail import qc  # noqa: F401

pytestmark=pytest.mark.asyncio


async def test_detail_stok_pk_dan_produk_satu_judul_tanpa_navigasi_ganda(pg,portal):
    from app.penggilingan.gudang2.service import _add_intake
    async with pg() as db:
        pk=await db.scalar(select(PkPurchaseBatch).where(PkPurchaseBatch.kode_batch=='PKB-QC-DETAIL'))
        intake=await _add_intake(db,user=await db.get(User,1),sumber_tipe='beli_luar',tujuan='ditumpuk',
            berat_kg=12000,hpp_per_kg=0,tanggal=now_local().date(),jam=None,
            pk_purchase_batch_id=pk.id,bobot_final=True,jasa_id=portal.orders[0].id)
        db.add(PolishingOutputLog(polishing_process_id=portal.process[0]['sosoh'],jenis='medium',
            berat_kg=1000,waktu_update=now_local(),input_by=1))
        db.add(MillingProgressLog(milling_process_id=portal.process[0]['giling'],berat_kumulatif_kg=6500,
            waktu_update=now_local(),input_by=1));await db.commit()
        ident=intake.intake.id
    async with client(portal.accounts[0]) as c:
        for path,amount in [('/pelanggan/stok/pk/detail?gudang=g1&kode=LOT-QC-DETAIL','6.000'),
            (f'/pelanggan/stok/pk/detail?gudang=g2&id={ident}','12.000'),
            ('/pelanggan/stok-produk-jasa/detail?jenis=medium','1.000')]:
            r=await c.get(path);assert r.status_code==200,(path,r.text[:200])
            s=BeautifulSoup(r.text,'html.parser');assert len(s.select('main h1'))==1
            assert amount in s.select_one('.pk-detail__weight').get_text()
            assert not s.select('.pk-detail__owner,.pk-detail__actions,nav[aria-label="Jenis barang"]')
            assert len(s.select('main a.pk-detail__back'))==1
            assert 'Rahasia Pelanggan B' not in r.text and 'JAS-PORTAL-0' not in s.main.get_text()
            assert not s.select('[data-post],[data-aksi],dialog')


async def test_detail_giling_dan_sosoh_tab_tetap_terbaca_tanpa_tombol_operator(pg,portal):
    async with pg() as db:
        mill=await db.get(MillingProcess,portal.process[0]['giling']);mill.status='proses';mill.waktu_selesai=None
        pol=await db.get(PolishingProcess,portal.process[0]['sosoh']);pol.status='proses';pol.waktu_selesai=None
        usage=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==pol.id));usage.berat_akhir_kg=None
        await db.commit()
    async with client(portal.accounts[0]) as c:
        for kind,code in [('giling','LOT-QC-DETAIL'),('sosoh','POL-PORTAL-0')]:
            for tab in ('ringkasan','bahan','hasil','riwayat'):
                r=await c.get(f'/pelanggan/proses-aktif/{kind}/{code}?tab_detail={tab}')
                assert r.status_code==200,(kind,tab)
                s=BeautifulSoup(r.text,'html.parser')
                assert s.select_one('main h1').get_text() in ('Penggilingan','Penyosohan')
                assert code in s.main.get_text() and len(s.select('[role=tab]'))==4
                assert not s.select('#tindakan-proses,.identitas-barang,[data-post],[data-aksi]')
                assert not any(a.get_text(strip=True).startswith('Lihat') for a in s.select('main a.btn[href*="tab_detail="]'))
                assert 'Rahasia Pelanggan B' not in r.text
