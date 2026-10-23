"""Susunan khusus sosoh tetap memakai sumber, tindakan, dan gerbang lama."""
import html
import json
import os
import re
from pathlib import Path
from urllib.parse import urlencode, urlsplit, parse_qs

import pytest
from tests.pg.test_gudang2_operator_pg import gudang2
from tests.pg.test_riwayat_giling import _klien

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('peran', ['operator', 'admin', 'superadmin'])
async def test_tab_konteks_hasil_penuh_dan_jeda(pg, gudang2, peran):
    from app.penggilingan.gudang2 import polishing as p
    from app.penggilingan.gudang1.services import jeda
    u = gudang2['user']
    async with pg() as db:
        pr = (await p.mulai_penyosohan(db, user=u, nama_silos=['B'])).proc
        for i in range(1, 23):
            await p.catat_output(db, user=u, kode=pr.kode_proses, jenis='medium',
                                 berat_kumulatif=i * 10, spek=f'SPEK-{i}')
    asal = '/pekerjaan?tab=berjalan&jenis=sosoh&gudang=g2&kepemilikan=pabrik'
    url = '/proses-aktif/sosoh/' + pr.kode_proses
    async with await _klien(pg, peran=peran, gudang='Gudang 2') as c:
        for tab in ['ringkasan', 'bahan', 'hasil', 'riwayat']:
            r = await c.get(url + '?' + urlencode({'tab_detail': tab, 'kembali_kerja': asal}))
            assert r.status_code == 200
            assert r.text.count('role="tab"') == 4
            assert f'aria-labelledby="tab-{tab}" class="sosoh-panel" >' in r.text
            assert '220 kg' in r.text and 'Selisih sementara' in r.text
            assert 'Hasil sosoh keluar' in r.text and 'SPEK-22' in r.text
            assert 'MOCKUP' not in r.text and 'Peran contoh' not in r.text
            ids = re.findall(r'\bid="([^"]+)"', r.text)
            assert len(ids) == len(set(ids)), 'ID rincian harus unik di semua panel'
            links = [html.unescape(x) for x in re.findall(r'href="([^"]+)"', r.text)]
            assert asal in links
            for link in links:
                if 'buka=' in link or 'tab_detail=' in link:
                    assert parse_qs(urlsplit(link).query)['kembali_kerja'] == [asal]
            if os.environ.get('UJI_POTRET_SOSOH') and peran == 'operator':
                Path(f'/tmp/sosoh-{tab}.html').write_text(r.text)
        r = await c.get(url + '?halaman_hasil=2')
        assert 'aria-labelledby="tab-hasil" class="sosoh-panel" >' in r.text
        assert '220 kg' in r.text and 'SPEK-1<' in r.text
        assert 'SPEK-22<' not in r.text.split('Riwayat pencatatan hasil sosoh', 1)[1]
        # Tetap menerima tautan lama, parameter borang dan nilai otomatis.
        r = await c.get('/proses-sosoh/' + pr.kode_proses + '?buka=hasil_penyosohan&nilai=' + pr.kode_proses)
        assert r.status_code == 200 and 'data-buka="hasil_penyosohan"' in r.text
        tab_links = re.findall(r'aria-controls="panel-[^"]+"[^>]+href="([^"]+)"', r.text)
        assert len(tab_links) == 4
        assert all('buka=' not in link and 'nilai=' not in link for link in tab_links)
        async with pg() as db:
            await jeda.hentikan(db, user=u, jenis='penyosohan', kode=pr.kode_proses, sebab='Listrik padam')
        r = await c.get(url)
        assert 'Mulai jeda' in r.text and 'Listrik padam' in r.text
        utama = r.text.split('sosoh-aksi-utama', 1)[1].split('</div>', 1)[0]
        assert utama.index('lanjutkan_penyosohan') < utama.index('hasil_penyosohan')
        assert 'ubah_kondisi_penyosohan' in r.text
        if os.environ.get('UJI_POTRET_SOSOH') and peran == 'operator':
            Path('/tmp/sosoh-jeda.html').write_text(r.text)
            Path('/tmp/sosoh-browser-session.json').write_text(json.dumps({
                'url': url, 'cookies': {x.name: x.value for x in c.cookies.jar}, 'kode': pr.kode_proses,
            }))


async def test_operator_gudang_efektif_dan_endpoint_langsung(pg, gudang2):
    from app.models import Warehouse
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    async with pg() as db:
        db.add(Warehouse(nama_gudang='Gudang 1 - Selepan', kode_fungsi='g1'))
        await db.commit()
        pr = (await mulai_penyosohan(db, user=gudang2['user'], nama_silos=['B'])).proc
    async with await _klien(pg, peran='operator', gudang='Gudang 2', lihat='operator:g1') as c:
        from app.web.lihat_sebagai import NAMA_KUKI
        c.cookies.set(NAMA_KUKI, 'operator:g1')
        assert (await c.get('/proses-aktif/sosoh/' + pr.kode_proses)).status_code == 403
        assert (await c.get('/proses-sosoh/' + pr.kode_proses)).status_code == 403
        assert (await c.get('/api/actions/sosoh-berjalan')).status_code == 403


async def test_neraca_aktif_mempertahankan_selisih_negatif(pg, gudang2):
    from app.database import now_local
    from app.models import PolishingOutputLog
    from app.penggilingan.gudang2.polishing import mulai_penyosohan
    async with pg() as db:
        pr = (await mulai_penyosohan(db, user=gudang2['user'], nama_silos=['B'])).proc
        # Simulasikan catatan lama yang timpang; tampilan tidak boleh
        # menormalkan data bermasalah dengan memangkas selisih menjadi nol.
        db.add(PolishingOutputLog(polishing_process_id=pr.id, jenis='medium',
            berat_kg=10000, waktu_update=now_local(), input_by=gudang2['user'].id))
        await db.commit()
    async with await _klien(pg, peran='admin') as c:
        r = await c.get('/proses-aktif/sosoh/' + pr.kode_proses)
    assert r.status_code == 200
    assert 'Jumlah hasil melebihi bahan' in r.text
    assert 'Selisih sementara' in r.text and '-200 kg' in r.text
    assert 'belum berarti susut final' in r.text
