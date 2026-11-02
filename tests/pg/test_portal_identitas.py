from datetime import datetime,timedelta
from zoneinfo import ZoneInfo

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import update

from app.models import MillingProcess,MillingProgressLog,MillingQcLog,JedaProses,JedaCatatan,ActivityLog
from tests.pg.test_portal_pelanggan import portal,client  # noqa: F401
from tests.pg.test_riwayat_qc_detail import qc  # noqa: F401

pytestmark=pytest.mark.asyncio


async def test_kartu_dan_detail_memakai_catatan_terbaru_milik_sendiri_serta_status_jeda(pg,portal):
    awal=datetime(2026,10,30,8,0,tzinfo=ZoneInfo('Asia/Jakarta'))
    hasil=datetime(2026,10,31,10,12,tzinfo=ZoneInfo('Asia/Jakarta'))
    async with pg() as db:
        p=await db.get(MillingProcess,portal.process[0]['giling'])
        p.status='proses';p.waktu_mulai=awal;p.waktu_selesai=None;p.updated_at=awal
        await db.execute(update(MillingQcLog).where(MillingQcLog.milling_process_id==p.id).values(waktu=awal))
        await db.execute(update(MillingProgressLog).where(MillingProgressLog.milling_process_id==p.id).values(waktu_update=awal))
        await db.execute(update(ActivityLog).where(ActivityLog.record_id==p.id,
            ActivityLog.table_name.in_(['milling_process','milling_progress_logs','milling_qc_logs']))
            .values(waktu_perubahan=awal,dibatalkan_pada=None))
        db.add(MillingProgressLog(milling_process_id=p.id,berat_kumulatif_kg=2500,waktu_update=hasil,input_by=1))
        db.add(MillingProgressLog(milling_process_id=portal.process[1]['giling'],berat_kumulatif_kg=42,
            waktu_update=hasil+timedelta(hours=8),input_by=1))
        await db.commit();pid=p.id;code=p.kode_proses
    async with client(portal.accounts[0]) as c:
        for path in ['/pelanggan/','/pelanggan/jasa-saya',f'/pelanggan/proses-aktif/giling/{code}']:
            for _ in range(2):
                r=await c.get(path);assert r.status_code==200
                s=BeautifulSoup(r.text,'html.parser')
                card=(s.select_one('.pelanggan-hero-proses') if '/proses-aktif/' in path else
                    next(a for a in s.select('.pelanggan-progres article') if code==a.get('data-kode-proses') or code in a.get_text()))
                assert 'Penggilingan gabah' in card.get_text()
                waktu=card.select_one('.pelanggan-pembaruan time')
                assert waktu.get_text()=='31/10/2026 10:12'
                if path=='/pelanggan/jasa-saya':
                    assert not card.select('.pelanggan-sumber-waktu')
                    assert s.select_one('.pelanggan-proses-petunjuk')
                elif '/proses-aktif/' in path:
                    assert 'Pencatatan hasil giling' in s.select_one('[data-portal-ringkas=catatan]').get_text()
                    assert 'belum perlu bertindak' in card.get_text()
                else:
                    assert 'Pencatatan hasil giling' in card.get_text()
                    assert 'belum perlu bertindak' in card.get_text()
                assert '31/10/2026 18:12' not in s.main.get_text()
                assert 'Rahasia Pelanggan B' not in r.text
        async with pg() as db:
            jeda=JedaProses(jenis='giling',milling_process_id=pid,sebab='Mesin perlu diperiksa',
                mulai=hasil+timedelta(minutes=18),created_at=hasil+timedelta(minutes=18),dicatat_oleh=1)
            db.add(jeda);await db.flush()
            db.add(JedaCatatan(jeda_id=jeda.id,aksi='hentikan',sebab=jeda.sebab,
                waktu_kejadian=jeda.mulai,dicatat_pada=hasil+timedelta(minutes=19),dicatat_oleh=1))
            await db.commit()
        for path in ['/pelanggan/',f'/pelanggan/proses-aktif/giling/{code}']:
            r=await c.get(path);assert r.status_code==200
            s=BeautifulSoup(r.text,'html.parser')
            card=(s.select_one('.pelanggan-hero-proses') if '/proses-aktif/' in path else
                next(a for a in s.select('.pelanggan-progres article') if code==a.get('data-kode-proses') or code in a.get_text()))
            assert 'Dijeda' in card.get_text() and 'menunggu penanganan petugas' in card.get_text()
            assert card.select_one('.pelanggan-pembaruan time').get_text()=='31/10/2026 10:31'
            assert 'Mesin perlu diperiksa' in card.get_text()


async def test_riwayat_proses_tidak_menjanjikan_barang_siap_diambil(pg,portal):
    async with client(portal.accounts[0]) as c:
        r=await c.get('/pelanggan/riwayat-giling/'+str(portal.process[0]['giling']))
        assert r.status_code==200
        s=BeautifulSoup(r.text,'html.parser');hero=s.select_one('.pelanggan-hero-proses')
        assert hero.h1.get_text()=='Hasil penggilingan gabah'
        assert hero.select_one('.pelanggan-penanda').get_text()=='Penggilingan selesai'
        assert 'pengambilan' not in hero.get_text()
        assert 'siap diambil' not in hero.get_text() and hero.select_one('time')


async def test_koreksi_hasil_memakai_waktu_pencatatan_tanpa_bocor_audit_baris_pelanggan_lain(pg,portal):
    from app.models import PolishingProcess,PolishingOutputLog,PolishingSiloUsage,ActivityLog
    from app.web.portal.identitas_proses import baca
    from app.web.portal.scope import load_scope
    from app.web.portal.security import CustomerReader
    awal=datetime(2026,10,30,8,0,tzinfo=ZoneInfo('Asia/Jakarta'))
    koreksi=awal+timedelta(days=1)
    async with pg() as db:
        p=await db.get(PolishingProcess,portal.process[0]['sosoh'])
        p.waktu_mulai=awal;p.waktu_selesai=awal;p.updated_at=awal
        await db.execute(update(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==p.id).values(updated_at=awal))
        own=PolishingOutputLog(polishing_process_id=p.id,jenis='medium',berat_kg=1000,waktu_update=awal,input_by=1)
        other=PolishingOutputLog(polishing_process_id=portal.process[1]['sosoh'],jenis='medium',berat_kg=42,waktu_update=awal,input_by=1)
        db.add_all([own,other]);await db.flush()
        db.add_all([ActivityLog(table_name='polishing_output_logs',record_id=own.id,action='UPDATE',
            waktu_perubahan=koreksi,changed_by=1),
            ActivityLog(table_name='polishing_output_logs',record_id=other.id,action='UPDATE',
            waktu_perubahan=koreksi+timedelta(hours=1),changed_by=1)])
        await db.commit();code=p.kode_proses
    scope=await load_scope(CustomerReader(1,portal.owners[0].id,'Pelanggan A'))
    async with pg() as db:
        result=await baca(db,scope,[('sosoh',code)])
        assert result['sosoh',code]['diperbarui']==koreksi
        assert result['sosoh',code]['sumber_waktu']=='Pencatatan hasil sosoh'
