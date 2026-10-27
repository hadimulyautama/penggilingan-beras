"""Pintu baru tidak menambah/menghilangkan hak halaman sumber."""
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from tests.pg.test_riwayat_qc_detail import qc
from tests.pg.test_riwayat_giling import _klien

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('role,gudang,proses,qcs,audit',[
    ('superadmin',None,5,5,True),('admin',None,5,5,True),
    ('operator','Gudang 1',4,3,False),('operator','Gudang 2',2,2,False),
])
async def test_tab_menu_jenis_dan_url_lama(pg,qc,role,gudang,proses,qcs,audit):
    async with await _klien(pg,peran=role,gudang=gudang) as c:
        r=await c.get('/laporan-riwayat')
        assert r.status_code==200
        assert r.url.path==('/riwayat-sosoh' if gudang=='Gudang 2' else '/riwayat-pengeringan')
        tabs=r.text.split('aria-label="Bagian Laporan dan Riwayat"')[1].split('</nav>')[0]
        assert 'aria-current="page">Proses</a>' in tabs.split('</a>')[0] + '</a>'
        assert 'Bagian Laporan dan Riwayat' in r.text
        sidebar=r.text.split('aria-label="Navigasi utama"')[1]
        assert sidebar.count('>Laporan &amp; Riwayat<')==1
        for old in ['>Riwayat Proses<','>Riwayat QC<','>Laporan<','>List audit<']:
            assert old not in sidebar
        assert 'pintu__ikon--laporan_riwayat' in sidebar and '<svg' in sidebar
        for tab,count,label in [('proses',proses,'Jenis proses'),('qc',qcs,'Jenis pemeriksaan QC')]:
            r=await c.get('/laporan-riwayat',params={'tab':tab})
            assert r.status_code==200
            nav=r.text.split(f'aria-label="{label}"')[1].split('</nav>')[0]
            assert nav.count('<a ')==count
            assert 'aria-current="page"' in nav
            assert 'pintu pintu--kini' in r.text
        r=await c.get('/laporan-riwayat?tab=audit&rentang=semua&kelompok=giling&cari=LOT')
        assert r.status_code==(200 if audit else 403)
        direct=await c.get('/audit')
        assert direct.status_code==(200 if audit else 403)
        for kind,allowed in [('pengeringan',gudang!='Gudang 2'),('giling',gudang!='Gudang 2'),('sosoh',gudang!='Gudang 1'),('transfer',gudang!='Gudang 2')]:
            r=await c.get('/riwayat-'+kind+'?sebelum=1')
            assert r.status_code==(200 if allowed else 403)
        r=await c.get('/api/laporan/pembelian_gabah?periode=semua')
        assert r.status_code==(403 if role=='operator' else 200)


async def test_gateway_tidak_membuang_query_kursor_atau_audit(pg,qc):
    async with await _klien(pg,peran='superadmin') as c:
        r=await c.get('/laporan-riwayat?tab=proses&jenis=giling&sebelum=7&pesan=Uji',follow_redirects=False)
        assert r.status_code==303
        assert r.headers['location']=='/riwayat-giling?sebelum=7&pesan=Uji'
        r=await c.get('/laporan-riwayat?tab=audit&rentang=semua&kelompok=giling&cari=LOT',follow_redirects=False)
        assert parse_qs(urlsplit(r.headers['location']).query)=={'rentang':['semua'],'kelompok':['giling'],'cari':['LOT']}
        assert (await c.get('/laporan-riwayat?tab=tidak-ada')).status_code==404


@pytest.mark.parametrize('tab,jenis', [('proses','sosoh'),('qc','pk-luar'),('audit','')])
async def test_gateway_operator_tidak_melompati_izin(pg,qc,tab,jenis):
    async with await _klien(pg,peran='operator',gudang='Gudang 1') as c:
        assert (await c.get('/laporan-riwayat',params={'tab':tab,'jenis':jenis})).status_code==403


async def test_lihat_sebagai_operator_menurunkan_tab_dan_api(pg,qc):
    from app.web.lihat_sebagai import NAMA_KUKI
    async with await _klien(pg,peran='superadmin') as c:
        c.cookies.set(NAMA_KUKI,'operator:g2')
        r=await c.get('/laporan-riwayat?tab=proses')
        assert r.status_code==200 and r.url.path=='/riwayat-sosoh'
        nav=r.text.split('aria-label="Bagian Laporan dan Riwayat"')[1].split('</nav>')[0]
        assert '>Audit<' in nav and 'aria-disabled="true"' in nav
        assert 'href="/audit"' not in nav
        assert (await c.get('/audit')).status_code==403
        assert (await c.get('/riwayat-giling')).status_code==403
        assert (await c.get('/api/laporan/pembelian_gabah')).status_code==403


async def test_detail_qc_lama_dan_seluruh_putaran_tetap_terjangkau(pg,qc):
    async with await _klien(pg,peran='superadmin') as c:
        r=await c.get('/riwayat-qc/gabah-kering/GB-QC-KERING')
        assert r.status_code==200
        assert 'Bagian Laporan dan Riwayat' in r.text
        assert 'Pencatat QC' in r.text and 'QC 5' in r.text
        assert 'href="/riwayat-qc/gabah-kering"' in r.text
        assert 'MENU_AKTIF' not in r.text
