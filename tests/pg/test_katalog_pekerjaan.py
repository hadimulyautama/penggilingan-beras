"""Lokasi katalog, URL lama dan gerbang diuji lewat HTTP pada Postgres terisolasi."""
from urllib.parse import parse_qs, urlsplit
import pytest
from tests.pg.test_tiket_antrean_produksi import _klien, pabrik
from tests.pg.formulir import cap_formulir
from app.models import Jasa, Pelanggan
from tests.pg.test_stok_produk_jasa import sosoh_jasa

pytestmark = pytest.mark.asyncio


@pytest.mark.parametrize('role', ['admin', 'superadmin'])
async def test_katalog_dan_konteks(pg, pabrik, role):
    async with await _klien(pg, role=role) as c:
        query='tab=berjalan&jenis=giling&cari=contoh&gudang=g2&kepemilikan=jasa&pelanggan_id=7'
        r=await c.get('/pekerjaan?'+query)
        assert r.status_code==200
        import re
        from html import unescape
        masuk=re.search(r'href="([^"]+)"[^>]*><span class="kerja-tab__nama">Pekerjaan lain</span></a>',r.text)
        assert masuk and '/pekerjaan/catat-lain?' in masuk[1]
        assert not re.search(r'<a[^>]*href="/aksi-lain"',r.text)
        tabs=re.search(r'aria-label="Tab pekerjaan">(.*?)</nav>',r.text,re.S)[1]
        assert tabs.count('<a ')==3
        katalog=await c.get(unescape(masuk[1]))
        assert katalog.status_code==200
        assert '← Kembali ke Pekerjaan' not in katalog.text
        tujuan=re.search(r'href="([^"]+)"[^>]*><span class="kerja-tab__nama">Berjalan</span>',katalog.text)
        assert parse_qs(urlsplit(unescape(tujuan[1])).query)==parse_qs(query)
        menu=(await c.get('/api/actions/menu')).json()
        ada={a['id']:a for a in menu}
        katalog_ids={a['id'] for a in menu if not a.get('kartu')}
        assert katalog_ids=={'beli_kemasan','transfer_pk','rekonsiliasi_timbang','auto_taut_keluar','sesuaikan_stok_pk_lama'}
        for id_ in (('masukkan_beras_silo','tutup_jasa','batalkan_jasa') if role=='superadmin' else ('tutup_jasa','batalkan_jasa')):
            assert ada[id_]['kartu'] and ada[id_]['fields'] and ada[id_]['post']
        for path in ('/aksi-lain','/aksi-lain?buka=beli_kemasan&nilai=25'):
            lama=await c.get(path)
            assert lama.status_code==303 and lama.headers['location'].startswith('/pekerjaan/catat-lain?')
        lama=await c.get('/aksi-lain?buka=beli_kemasan&nilai=25')
        assert parse_qs(urlsplit(lama.headers['location']).query)=={'buka':['beli_kemasan'],'nilai':['25']}
        for id_ in ('masukkan_beras_silo','tutup_jasa','batalkan_jasa'):
            kosong=await c.get('/pekerjaan/catat-lain?buka='+id_+'&nilai=tidak-sah')
            assert kosong.status_code==200 and 'data-buka=""' in kosong.text
            assert 'Konteks' in kosong.text
        assert 'href="/pekerjaan?tab=tindakan"' in (await c.get('/pekerjaan/catat-lain?kembali=https://evil.example')).text


async def test_duplikat_menuju_konteks_asli(pg, pabrik, sosoh_jasa):
    async with pg() as db:
        pel=Pelanggan(nama_pelanggan='Pemilik Uji');db.add(pel);await db.flush()
        j=Jasa(kode='JAS-UJI',pelanggan_id=pel.id,status='berjalan');db.add(j);await db.commit()
        jid,pid=j.id,pel.id
    async with await _klien(pg,role='superadmin') as c:
        for id_ in ('tutup_jasa','batalkan_jasa'):
            r=await c.get(f'/aksi-lain?buka={id_}&nilai={jid}')
            assert r.status_code==303
            assert r.headers['location'].startswith(f'/jasa/pelanggan/{pid}?')
            assert parse_qs(urlsplit(r.headers['location']).query)['nilai']==[str(jid)]
            detail=await c.get(r.headers['location'])
            assert detail.status_code==200 and f'data-buka="{id_}"' in detail.text
        r=await c.get('/aksi-lain?buka=masukkan_beras_silo&nilai=medium%7Cpabrik&sumber_stok=curah%7Cpabrik')
        assert r.status_code==303 and r.headers['location'].startswith('/stok-produk/detail?')
        h=await c.get(r.headers['location'])
        assert h.status_code==200 and 'data-buka="masukkan_beras_silo"' in h.text

        r=await c.get('/aksi-lain',params={'buka':'masukkan_beras_silo','nilai':'medium|jasa',
                                          'sumber_stok':f"curah|{sosoh_jasa['jasa_id']}"})
        assert r.status_code==303 and r.headers['location'].startswith('/stok-produk-jasa/detail?')
        assert parse_qs(urlsplit(r.headers['location']).query)['pelanggan_id']==[str(sosoh_jasa['pelanggan_id'])]
        assert (await c.get(r.headers['location'])).status_code==200


@pytest.mark.parametrize('gudang', ['g1','g2'])
async def test_operator_tetap_berpintu_lama(pg, gudang):
    from app.models import Warehouse
    async with pg() as db:
        w=Warehouse(nama_gudang='Uji '+gudang,kode_fungsi=gudang);db.add(w);await db.commit();wid=w.id
    async with await _klien(pg,role='operator',gudang_id=wid) as c:
        r=await c.get('/pekerjaan')
        assert r.status_code==200 and 'Catat pekerjaan lain</a>' not in r.text
        assert 'buka=undo' in r.text
        if gudang=='g2':
            assert 'buka=catat_packing' in r.text and 'buka=catat_bekatul' in r.text
        for path in ('/aksi-lain?buka=tutup_jasa&nilai=1','/pekerjaan/catat-lain'):
            r=await c.get(path);assert r.status_code==303 and urlsplit(r.headers['location']).path=='/aksi'
        for path,data in [('/api/actions/tutup-jasa',{'jasa_id':1}),('/api/actions/batalkan-jasa',{'jasa_id':1,'sebab':'uji'}),('/api/actions/beli-kemasan',{'karung':'woven|25','jumlah':1})]:
            r=await c.post(path,json=data,headers={'X-CSRF-Token':cap_formulir(c)})
            assert r.status_code==403,(path,r.status_code,r.text)


async def test_beli_karung_lewat_endpoint_stok_dan_csrf(pg,pabrik):
    from app.services.seed import seed_master
    await seed_master()
    async with await _klien(pg,role='admin') as c:
        choices=(await c.get('/api/actions/kemasan-jenis')).json()
        karung=choices[0]['value']
        # Merek adalah aturan lama; gunakan pilihan server, bukan nama tebakan.
        merek=(await c.get('/api/actions/merk')).json()
        data={'karung':karung,'jumlah':13,'merk':merek[0]['value'] if merek else None}
        assert (await c.post('/api/actions/beli-kemasan',json=data)).status_code==403
        r=await c.post('/api/actions/beli-kemasan',json=data,headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200 and r.json()['ok'],r.text
        assert 'Stok kini: 13 lembar' in r.json()['pesan']
        from sqlalchemy import select
        from app.models import PackagingPurchase
        async with pg() as db:
            pembelian=(await db.scalars(select(PackagingPurchase))).all()
            assert len(pembelian)==1 and pembelian[0].jumlah_lembar==13
            assert pembelian[0].pelanggan_id is None
        data['jumlah']=0
        assert (await c.post('/api/actions/beli-kemasan',json=data,headers={'X-CSRF-Token':cap_formulir(c)})).status_code==400


async def test_pintasan_mengikuti_gudang_efektif(pg,pabrik):
    async with await _klien(pg,role='operator',gudang_id=pabrik['g1']) as c:
        r=await c.post('/lihat-sebagai',data={'peran':'operator:g2','_csrf':cap_formulir(c)})
        assert r.status_code==303,r.text
        kerja=await c.get('/pekerjaan')
        assert 'buka=catat_packing' in kerja.text and 'buka=catat_bekatul' in kerja.text
        assert 'buka=undo' in kerja.text
        assert 'Catat pekerjaan lain</a>' not in kerja.text
