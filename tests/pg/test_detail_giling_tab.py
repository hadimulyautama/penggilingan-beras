"""Detail giling bertab tetap membaca kumulatif, semua putaran QC dan izin lama."""
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
import pytest_asyncio
from tests.pg.test_tambah_silo_berjalan import g1, _isi_silo_g1
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_qc_berjalan import giling
from tests.pg.formulir import cap_formulir

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def giling_tab(pg, g1):
    from sqlalchemy import select
    from app.models import User, PurchaseBatch
    from app.services.seed import seed_master
    from tests.pg.test_bobot_belum_final import _tiket
    from app.penggilingan.gudang1.services import milling as m
    await seed_master()
    await _isi_silo_g1(pg, g1, huruf='A', kode='GB-TAB-A', kg=6000)
    await _isi_silo_g1(pg, g1, huruf='B', kode='GB-TAB-B', kg=4000)
    async with pg() as db:
        u = await db.get(User, g1['user'])
        batch = await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch == 'GB-TAB-A'))
        batch.no_polisi_truk = 'B 1234 UJI'
        batch.timbangan_transaksi_id = await _tiket(db, 'TK-TAB-A', nopol='B 1234 UJI',
            t1=8000, netto=6000, kosong=2000, supplier_id=g1['pemasok'])
        await db.commit()
        pr = (await m.start_milling(db, user=u, nama_silo=['A', 'B'])).proc
        for n in range(1, 22):
            await m.log_progress(db, user=u, kode_proses=pr.kode_proses,
                                 berat_kumulatif=n * 150 if n < 21 else 6400)
            await m.log_qc_milling(db, user=u, kode_proses=pr.kode_proses,
                kadar_air=14.4, broken=24, susut=12, kondisi=None,
                butir_kuning='bersih', gabah='sedikit', merang='sedang',
                catatan_lab=f'Catatan putaran {n}')
        return {'kode': pr.kode_proses, 'id': pr.id, 'user': u.id}


@pytest.mark.parametrize('peran', ['operator', 'admin', 'superadmin'])
async def test_tab_kumulatif_qc_semua_putaran_dan_izin(pg, giling_tab, peran):
    from app.web import csrf
    asal = '/pekerjaan?tab=berjalan&jenis=giling&gudang=g1&kepemilikan=pabrik'
    url = '/proses-aktif/giling/' + giling_tab['kode']
    async with await _klien(pg, peran=peran, gudang='Gudang 1') as c:
        c.headers[csrf.NAMA_HEADER] = cap_formulir(c)
        for tab in ['ringkasan', 'bahan', 'hasil', 'riwayat']:
            r = await c.get(url + '?' + urlencode({'tab_detail':tab, 'kembali_kerja':asal}))
            assert r.status_code == 200
            assert r.text.count('role="tab"') == 4
            assert f'aria-labelledby="tab-{tab}" >' in r.text
            assert '6.400 kg' in r.text and '64,0%' in r.text
            assert '88,33' in r.text and 'B1' in r.text and '21 putaran' in r.text
            for kata in ['GB-TAB-A','GB-TAB-B','Silo A','Silo B','KL',
                         'Bahan awal','Butir kuning','Merang','Catatan putaran 21','TK-TAB-A','B 1234 UJI']:
                assert kata in r.text, kata
            assert ('buka=qc_giling' in r.text) == (peran != 'operator')
            ids = re.findall(r'\bid="([^"]+)"', r.text)
            assert len(ids) == len(set(ids))
            for link in re.findall(r'href="([^"]+)"', r.text):
                link = html.unescape(link)
                if 'buka=' in link or 'tab_detail=' in link:
                    assert parse_qs(urlsplit(link).query)['kembali_kerja'] == [asal]
            assert 'Peran contoh' not in r.text and 'MOCKUP' not in r.text
        r = await c.get(url + '?halaman_hasil=2&halaman_qc=2')
        assert 'aria-labelledby="tab-hasil" >' in r.text
        assert 'QC 1 ·' in r.text and 'QC 21 ·' not in r.text
        assert '21 putaran' in r.text and '88,33' in r.text and '6.400 kg' in r.text
        if peran == 'operator':
            denied = await c.post('/api/actions/qc-giling', json={'kode_proses':giling_tab['kode'],
                'kadar_air':13,'butir_kuning':'bersih','gabah':'bersih','merang':'bersih'})
            assert denied.status_code == 403
        # Pilihan lama pembuka borang diterima; tab tidak mengulang buka/nilai.
        r = await c.get(url + '?buka=hasil_giling&nilai=' + giling_tab['kode'])
        assert 'data-buka="hasil_giling"' in r.text
        links = re.findall(r'role="tab"[^>]+href="([^"]+)"', r.text)
        assert len(links) == 4 and all('buka=' not in x and 'nilai=' not in x for x in links)
        if os.environ.get('UJI_POTRET_GILING') and peran == 'admin':
            Path('/tmp/giling-browser-session.json').write_text(json.dumps({
                'url':url, 'cookies':{x.name:x.value for x in c.cookies.jar},
                'kode':giling_tab['kode'], 'id':giling_tab['id']}))


async def test_jeda_dan_fitur_qc_tidak_membuka_tindakan_baru(pg, giling_tab):
    from app.models import User
    from app.services.setelan import set_fitur_mutu
    from app.penggilingan.gudang1.services import jeda as j
    from app.penggilingan.gudang1.services.milling import log_progress
    from app.web import csrf
    url = '/proses-aktif/giling/' + giling_tab['kode']
    async with pg() as db:
        u = await db.get(User, giling_tab['user'])
        await j.hentikan(db,user=u,jenis='giling',kode=giling_tab['kode'],sebab='Listrik padam')
        interval = await j.jeda_terbuka(db,'giling',giling_tab['id'])
        awal = interval.mulai
        await log_progress(db,user=u,kode_proses=giling_tab['kode'],berat_kumulatif=6500)
        assert interval.selesai is None and interval.mulai == awal
    async with await _klien(pg, peran='admin') as c:
        c.headers[csrf.NAMA_HEADER] = cap_formulir(c)
        r = await c.get(url + '?tab_detail=hasil')
        assert 'Mulai jeda' in r.text and 'Listrik padam' in r.text
        assert 'buka=qc_giling' not in r.text and 'buka=tambah_silo_giling' not in r.text
        assert 'buka=hasil_giling' in r.text and 'buka=ubah_kondisi_proses' in r.text
        async with pg() as db:
            u = await db.get(User, giling_tab['user'])
            await j.lanjutkan(db,user=u,jenis='giling',kode=giling_tab['kode'])
            await set_fitur_mutu(db,False,user=u)
        r = await c.get(url)
        assert 'buka=qc_giling' not in r.text
        assert (await c.post('/api/actions/qc-giling',json={'kode_proses':giling_tab['kode'],'kadar_air':13})).status_code == 400


async def test_gudang_efektif_samaran_dan_endpoint_langsung(pg, giling_tab):
    from sqlalchemy import select
    from app.models import Warehouse
    from app.web.lihat_sebagai import NAMA_KUKI
    from app.web import csrf
    async with pg() as db:
        if not await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi == 'g2')):
            db.add(Warehouse(nama_gudang='Gudang 2 - Polesan',kode_fungsi='g2'))
        await db.commit()
    for peran in ['operator','admin','superadmin']:
        async with await _klien(pg,peran=peran,gudang='Gudang 1') as c:
            c.cookies.set(NAMA_KUKI,'operator:g2')
            c.headers[csrf.NAMA_HEADER] = cap_formulir(c)
            assert (await c.get('/proses-aktif/giling/'+giling_tab['kode'])).status_code == 403
            assert (await c.post('/api/actions/hasil-giling',json={'kode_proses':giling_tab['kode'],'berat_kumulatif':6600})).status_code == 403
        if peran != 'operator':
            async with await _klien(pg,peran=peran) as c:
                c.cookies.set(NAMA_KUKI,'operator:g1')
                r = await c.get('/proses-aktif/giling/'+giling_tab['kode'])
                assert r.status_code == 200 and 'buka=qc_giling' not in r.text


async def test_bobot_dan_sumber_warisan_belum_diketahui_tidak_dijadikan_nol(pg, giling):
    from app.models import MillingProcess
    async with pg() as db:
        p = await db.get(MillingProcess, giling['id'])
        p.berat_gabah_masuk_kg = None
        p.bobot_masuk_final = False
        await db.commit()
    async with await _klien(pg,peran='admin') as c:
        r = await c.get('/proses-aktif/giling/'+giling['kode'])
    assert r.status_code == 200
    stat = r.text.split('aria-label="Ringkasan angka penggilingan"',1)[1].split('</section>',1)[0]
    assert 'Belum diketahui' in stat and 'Belum dicatat' in stat and 'Belum dapat dihitung' in stat
    assert '0 kg' not in stat and 'Data proses lama' in r.text
    assert 'Penilaian belum lengkap' in r.text and 'Tidak ikut perhitungan' in r.text
