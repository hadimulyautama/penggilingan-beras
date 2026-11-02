import json
from datetime import datetime,timedelta
from pathlib import Path
from zoneinfo import ZoneInfo
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select
from app.models import DryingLot,DryingMoistureLog
from tests.pg.test_portal_pelanggan import portal,client  # noqa:F401
from tests.pg.test_riwayat_qc_detail import qc  # noqa:F401
from tests.pg.test_portal_alur_hp import alur  # noqa:F401
from tests.pg.test_portal_transaksi_detail import transaksi  # noqa:F401
from tests.pg.test_portal_catatan import catatan  # noqa:F401
from tests.pg.test_gabung_jasa import dunia  # noqa:F401

pytestmark=pytest.mark.asyncio
OUT=Path('output/portal-proses-ringkas-20261102')


async def test_estimasi_tersedia_mengikuti_pembaca_native_tanpa_mengubah_sumber(pg,portal,alur):
    from app.services.estimasi_pengeringan import untuk_lot_banyak
    from app.web.portal.proses_ringkas import angka
    code=alur['pendinginan'].rsplit('/',1)[1]
    async with pg() as db:
        lot=await db.scalar(select(DryingLot).where(DryingLot.kode_lot==code))
        start=datetime(2026,11,1,10,0,tzinfo=ZoneInfo('Asia/Jakarta'))
        lot.waktu_mulai_pengeringan=start;lot.waktu_selesai_pengeringan=start+timedelta(hours=1)
        logs=(await db.scalars(select(DryingMoistureLog).where(DryingMoistureLog.drying_lot_id==lot.id).order_by(DryingMoistureLog.id))).all()
        for i,log in enumerate(logs):log.waktu_update=start+timedelta(minutes=i*10)
        await db.commit()
        before=(await untuk_lot_banyak(db,[lot]))[lot.id];assert before['kering']
    OUT.mkdir(parents=True,exist_ok=True)
    async with client(portal.accounts[0]) as c:
        for path,name in [('/pelanggan/jasa-saya','daftar-estimasi'),(alur['pendinginan'],'detail-estimasi')]:
            response=await c.get(path);assert response.status_code==200
            s=BeautifulSoup(response.text,'html.parser')
            card=s.select_one(f'[data-kode-proses="{code}"]') if name.startswith('daftar') else s.select_one('.pelanggan-hero-proses')
            assert angka(before['kering']) in card.get_text()
            assert card.get_text().count('Perkiraan · belum ditimbang')==1
            assert 'Berat setelah kering' not in [x.get_text() for x in card.select('dt')]
            assert 'Rahasia Pelanggan B' not in response.text
            (OUT/(name+'.html')).write_text(response.text)
    async with pg() as db:
        assert (await untuk_lot_banyak(db,[lot]))[lot.id]==before


async def test_daftar_dan_detail_ringkas_tetap_memuat_tab_catatan_dan_kepemilikan(pg,portal,alur):
    OUT.mkdir(parents=True,exist_ok=True)
    code=alur['pendinginan'].rsplit('/',1)[1]
    async with client(portal.accounts[0]) as c:
        r=await c.get('/pelanggan/jasa-saya');assert r.status_code==200
        s=BeautifulSoup(r.text,'html.parser');card=s.select_one(f'[data-kode-proses="{code}"]')
        assert 'Menunggu dingin' in card.get_text()
        assert code not in card.get_text() and not card.select('.pelanggan-sumber-waktu')
        assert card.get_text().count('Belum tersedia')==1
        assert 'Pasangan indikator' not in card.get_text() and 'Estimasi · belum ditimbang' not in card.get_text()
        assert 'Proses sedang berjalan' not in s.main.get_text()
        assert len(s.select('.pelanggan-proses-petunjuk'))==1
        assert len(card.select('a'))==1
        (OUT/'daftar.html').write_text(r.text)
        for kind in ['pendinginan','pengeringan','giling','sosoh']:
            for tab in ['ringkasan','bahan','pengukuran' if kind in ('pendinginan','pengeringan') else 'hasil','riwayat']:
                r=await c.get(alur[kind]+'?tab_detail='+tab);assert r.status_code==200,(kind,tab)
                s=BeautifulSoup(r.text,'html.parser');hero=s.select_one('.pelanggan-hero-proses')
                assert hero.find_parent('details') is None
                assert len(s.select('main h1'))==1 and len(s.select('[role=tab]'))==4
                assert s.select_one('[data-portal-ringkas=catatan]')
                assert s.select_one('.pelanggan-proses-lanjutan').has_attr('open')==(tab!='ringkasan')
                assert not s.select('[data-post],[data-aksi],dialog')
                assert 'jumlah akhir tersedia setelah proses selesai' not in s.main.get_text()
                assert 'Rahasia Pelanggan B' not in r.text
                if tab=='ringkasan':(OUT/(kind+'.html')).write_text(r.text)
                if kind=='pendinginan':
                    assert 'Menunggu dingin' in hero.get_text() and 'Berat akhir belum ditimbang' in hero.get_text()
                    assert 'Data pengukuran belum lengkap' in s.select_one('[data-portal-ringkas=estimasi]').get_text()
                if kind=='pengeringan':
                    assert float(hero.select_one('progress')['value'])==pytest.approx(.4)
                    assert 'Saat ini 16%' in hero.get_text() and 'Target 13%' in hero.get_text()
        (OUT/'paths.json').write_text(json.dumps(alur))
    async with client(portal.accounts[1]) as c:
        for kind in ['pendinginan','pengeringan','giling','sosoh']:
            assert (await c.get(alur[kind])).status_code==404


async def test_hasil_timbang_sah_dan_tahap_silo_tidak_kembali_disebut_belum_ditimbang(pg,dunia):
    from tests.pg.test_estimasi_pengeringan import buat,sidik
    from tests.pg.test_portal_transit import _akun
    from tests.pg.test_riwayat_pengeringan import _klien
    from tests.pg.test_bobot_hasil_pengeringan import baca,isian
    from tests.pg.test_form_kadar_air import post
    lid,_,_=await buat(pg,dunia)
    account=await _akun(pg,dunia)
    async with await _klien(pg,peran='admin') as c:
        data=await baca(c,lid)
        r=await post(c,'bobot-pengeringan',isian(data));assert r.status_code==200
    before=await sidik(pg)
    async with client(account) as c:
        r=await c.get('/pelanggan/proses-aktif/pendinginan/PGR-UJI-A');assert r.status_code==303
        assert r.headers['location'].startswith('/pelanggan/riwayat-pengeringan/')
        r=await c.get(r.headers['location']);assert r.status_code==200
        s=BeautifulSoup(r.text,'html.parser');hero=s.select_one('.pelanggan-hero-proses')
        assert '26.000,25 kg' in hero.get_text() and 'Hasil timbang' in hero.get_text()
        assert 'belum ditimbang' not in hero.get_text() and 'Sudah di silo' in hero.get_text()
        assert 'Pengering' not in hero.select_one('.pelanggan-proses-lokasi').get_text()
        assert 'Pencatatan hasil timbang' in s.select_one('[data-portal-ringkas=catatan]').get_text()
        OUT.mkdir(parents=True,exist_ok=True);(OUT/'detail-terukur.html').write_text(r.text)
    assert await sidik(pg)==before
