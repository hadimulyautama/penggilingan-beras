"""Pintu baru tidak menambah/menghilangkan hak halaman sumber."""
import re
from urllib.parse import parse_qs, urlsplit

import pytest
from tests.pg.test_riwayat_qc_detail import qc
from tests.pg.test_riwayat_giling import _klien

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('role,gudang,proses,qcs,audit',[
    ('superadmin',None,4,5,True),('admin',None,4,5,True),
    ('operator','Gudang 1',3,3,False),('operator','Gudang 2',1,2,False),
])
async def test_tab_menu_jenis_dan_url_lama(pg,qc,role,gudang,proses,qcs,audit):
    from bs4 import BeautifulSoup
    async with await _klien(pg,peran=role,gudang=gudang) as c:
        r=await c.get('/laporan-riwayat')
        assert r.status_code==200
        assert r.url.path==('/riwayat-giling' if gudang=='Gudang 1' else '/riwayat-sosoh')
        tabs=r.text.split('aria-label="Jenis halaman"')[1].split('</nav>')[0]
        aktif=BeautifulSoup(r.text,'html.parser').select_one('nav[aria-label="Jenis halaman"] a[aria-current]')
        assert aktif.get_text(strip=True)=='Riwayat proses'
        sidebar=r.text.split('aria-label="Navigasi utama"')[1]
        assert sidebar.count('>Riwayat<')==1
        assert sidebar.count('>Laporan periode<')==1
        for old in ['>Riwayat Proses<','>Riwayat QC<','>Laporan<','>List audit<']:
            assert old not in sidebar
        assert 'pintu__ikon--laporan_riwayat' in sidebar and '<svg' in sidebar
        for tab,count,label in [('proses',proses,'Jenis proses'),('qc',qcs,'Jenis pemeriksaan QC')]:
            r=await c.get('/laporan-riwayat',params={'tab':tab})
            assert r.status_code==200
            nav=r.text.split(f'aria-label="{label}"')[1].split('</nav>')[0]
            assert nav.count('<a ')==count
            assert 'aria-current="page"' in nav
            from bs4 import BeautifulSoup
            soup=BeautifulSoup(r.text,'html.parser')
            pilihan=soup.select_one('[data-jenis-riwayat]')
            tautan=soup.select('.laporan-nav__jenis a')
            if tab=='proses':
                assert [o.get_text(strip=True).split(' — ')[0] for o in pilihan.select('option')]==['Penyosohan','Penggilingan','Pengeringan','Transfer']
            assert [o['value'] for o in pilihan.select('option[value]:not([disabled])')]==[a['href'] for a in tautan]
            assert pilihan.select_one('option[selected]')['value']==soup.select_one('.laporan-nav__jenis a[aria-current]')['href']
            assert all(not o.has_attr('value') for o in pilihan.select('option[disabled]'))
            assert 'pintu pintu--kini' in r.text
        r=await c.get('/laporan-riwayat?tab=audit&rentang=semua&kelompok=giling&cari=LOT')
        assert r.status_code==(200 if audit else 403)
        direct=await c.get('/audit')
        assert direct.status_code==(200 if audit else 403)
        for kind,allowed in [('pengeringan',gudang!='Gudang 2'),('giling',gudang!='Gudang 2'),('sosoh',gudang!='Gudang 1'),('transfer',gudang!='Gudang 2')]:
            r=await c.get('/riwayat-'+kind+'?sebelum=1')
            assert r.status_code==(200 if allowed else 403)
        r=await c.get('/api/laporan/pembelian_gabah?periode=semua')
        assert r.status_code==404


async def test_tab_dan_tindakan_punya_satu_lokasi_di_daftar_detail_dan_laporan(pg,qc):
    from bs4 import BeautifulSoup
    async with await _klien(pg,peran='superadmin') as c:
        for path,panduan in [('/riwayat-giling','rpd-panduan'),('/riwayat-qc/gabah-basah','rqd-panduan'),
                             ('/riwayat-qc/gabah-kering/GB-QC-KERING','rqd-panduan'),('/laporan','lk-panduan'),('/audit','lk-panduan')]:
            r=await c.get(path);assert r.status_code==200
            soup=BeautifulSoup(r.text,'html.parser')
            bar=soup.select_one('.laporan-riwayat>.laporan-nav>.laporan-nav__bar')
            assert bar is not None
            assert [x.get_text(strip=True) for x in bar.select('.laporan-nav__tabs>a')]==([] if path=='/laporan' else ['Riwayat proses','Riwayat QC','Audit'])
            assert not bar.select('a[href="/laporan"]')
            assert len(bar.select(f'[data-lk-buka="{panduan}"]'))==1
            assert len(soup.select('button[data-lk-cetak]'))==1
            # Kembali desktop mengikuti induk breadcrumb, termasuk laporan.
            back=soup.select_one('.desktop-back')
            assert back is not None
            assert back['href']==soup.select('.desktop-breadcrumb nav a,.desktop-breadcrumb a')[-1]['href']
            assert not soup.select('[data-rpd-nav-open],[data-rqd-nav-open],[data-rhs-nav-open],#lk-menu')
            assert 'Laporan &amp; Riwayat' not in r.text
            if path=='/riwayat-giling':
                assert soup.select_one('.rpd-header h1,.rpd-header .rhs-meta,.rpd-description,.rpd-intro h2') is None
                assert 'Giling yang sudah ditutup' in soup.select_one('#rpd-panduan').get_text()
            if path=='/riwayat-qc/gabah-basah':
                assert soup.select_one('.rqd-list>.rhs-header') is None
                assert 'Pilih batch atau proses' in soup.select_one('#rqd-panduan').get_text()
            for menu in soup.select('.rhs-menu'):
                assert not any('Panduan' in b.get_text() or 'Cetak' in b.get_text() for b in menu.select('button'))
        r=await c.get('/laporan')
        soup=BeautifulSoup(r.text,'html.parser')
        assert soup.select_one('.laporan-nav h1') is None
        assert 'Laporan periode' in soup.title.get_text()
        assert soup.select_one('[data-jenis-riwayat]') is None
        assert not soup.select('.laporan-nav a[href="/laporan"]:not([data-tab-riwayat])')
        r=await c.get('/riwayat',follow_redirects=False)
        assert r.status_code==303 and r.headers['location']=='/riwayat-sosoh'


async def test_gateway_tidak_membuang_query_kursor_atau_audit(pg,qc):
    async with await _klien(pg,peran='superadmin') as c:
        r=await c.get('/laporan-riwayat?tab=proses&jenis=giling&sebelum=7&pesan=Uji',follow_redirects=False)
        assert r.status_code==303
        assert r.headers['location']=='/riwayat-giling?sebelum=7&pesan=Uji'
        r=await c.get('/laporan-riwayat?tab=audit&rentang=semua&kelompok=giling&cari=LOT',follow_redirects=False)
        assert parse_qs(urlsplit(r.headers['location']).query)=={'rentang':['semua'],'kelompok':['giling'],'cari':['LOT']}
        assert (await c.get('/laporan-riwayat?tab=tidak-ada')).status_code==404
        lama=await c.get('/laporan-riwayat?tab=proses&jenis=retur-supplier&supplier=2',follow_redirects=False)
        assert lama.status_code==303 and lama.headers['location']=='/riwayat-retur-supplier?supplier=2'


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
        nav=r.text.split('aria-label="Jenis halaman"')[1].split('</nav>')[0]
        assert '>Audit<' in nav and 'aria-disabled="true"' in nav
        assert 'href="/audit"' not in nav
        assert (await c.get('/audit')).status_code==403
        assert (await c.get('/riwayat-giling')).status_code==403
        assert (await c.get('/api/laporan/pembelian_gabah')).status_code==404


async def test_detail_qc_lama_dan_seluruh_putaran_tetap_terjangkau(pg,qc):
    async with await _klien(pg,peran='superadmin') as c:
        r=await c.get('/riwayat-qc/gabah-kering/GB-QC-KERING')
        assert r.status_code==200
        assert 'Jenis halaman' in r.text
        assert 'Pencatat QC' in r.text and 'QC 5' in r.text
        assert 'href="/riwayat-qc/gabah-kering"' in r.text
        assert 'MENU_AKTIF' not in r.text
