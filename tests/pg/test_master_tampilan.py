"""Izin dan tampilan diuji melalui sesi HTTP serta PostgreSQL lokal."""
from pathlib import Path

import pytest
from sqlalchemy import select
from hmu_identitas import peran as P

from app.models import User, PermintaanPk, Notification
from app.services import kabar
from tests.pg.test_permintaan_pk import pabrik
from tests.pg.test_tiket_antrean_produksi import _klien
from tests.pg.formulir import cap_formulir

pytestmark = pytest.mark.asyncio


async def test_katalog_g2_tanpa_gudang1_aktif_tetap_tersedia_dan_tulis_dijaga(pg, pabrik):
    from app.models import Warehouse
    from app.penggilingan.gudang1.services.silo import silos_g1,_g1_warehouse_id,SiloError
    async with pg() as db:
        wh=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g1'))
        wh.aktif=False
        await db.commit()
        assert await silos_g1(db)==[]
        with pytest.raises(SiloError,match='Data gudang 1 belum ada'):
            await _g1_warehouse_id(db)
        g2=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g2'))
    async with await _klien(pg,role=P.OPERATOR,gudang_id=g2) as c:
        r=await c.get('/api/actions/menu')
        assert r.status_code==200
        menu={a['id']:a for a in r.json()}
        assert menu['pindah_silo']['boleh'] is False
        assert menu['mulai_penyosohan']['boleh'] is True
        assert (await c.get('/api/actions/silo-g1')).status_code==403


async def test_superadmin_minta_lot_dari_http(pg, pabrik):
    async with await _klien(pg, role=P.SUPERADMIN) as c:
        menu = (await c.get('/api/actions/menu')).json()
        assert next(a['boleh'] for a in menu if a['id']=='minta_pk_g1')
        r = await c.get('/stok/pk/detail', params={'gudang':'g1','kode':pabrik['lot']})
        assert r.status_code == 200
        assert 'buka=minta_pk_g1' in r.text
        r = await c.post('/api/actions/minta-pk-g1',
            json={'kode_proses':pabrik['lot'],'berat':1000},
            headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code == 200, r.text
    async with pg() as db:
        permintaan = await db.scalar(select(PermintaanPk))
        assert permintaan and permintaan.status == 'diminta'


async def test_kabar_super_gabungan_dan_status_baca_pribadi(pg, pabrik):
    async with pg() as db:
        super_ = User(nama='Super Kabar', role=P.SUPERADMIN, status='aktif')
        db.add(super_)
        rows=[Notification(tipe='permintaan_pk',pesan='Untuk admin',target_role='admin'),
              Notification(tipe='pengeringan_telat',pesan='Untuk operator G1',target_role='operator',table_name='drying_lots'),
              Notification(tipe='stok',pesan='Untuk operator G2',target_role='operator',table_name='polishing_process'),
              Notification(tipe='umum',pesan='Untuk semua',target_role=None)]
        db.add_all(rows)
        await db.commit()
        op1=await db.get(User,pabrik['op1'])
        op2=await db.get(User,pabrik['op2'])
        assert len(await kabar.daftar(db,super_)) == 4
        assert await kabar.jumlah_baru(db,super_) == 4
        op1_ids={n.id for n in await kabar.daftar(db,op1)}
        op2_ids={n.id for n in await kabar.daftar(db,op2)}
        assert rows[1].id in op1_ids and rows[2].id not in op1_ids
        assert rows[2].id in op2_ids and rows[1].id not in op2_ids
        await kabar.tandai(db,super_,dibaca=True,id_=rows[1].id)
        assert await kabar.jumlah_baru(db,super_) == 3
        assert await kabar.jumlah_baru(db,op1) == len(op1_ids)


async def test_kerangka_menu_dan_pengaturan_sama_bagi_semua_peran(pg, pabrik):
    from bs4 import BeautifulSoup
    hasil=[]
    out=Path("/tmp/hmu-master-tampilan-preview");out.mkdir(exist_ok=True)
    async with pg() as db:
        op=await db.get(User,pabrik['op1']);g1=op.default_warehouse_id
        op=await db.get(User,pabrik['op2']);g2=op.default_warehouse_id
    for role,gudang in ((P.SUPERADMIN,None),(P.ADMIN,None),(P.OPERATOR,g1),(P.OPERATOR,g2)):
        async with await _klien(pg,role=role,gudang_id=gudang) as c:
            r=await c.get('/pengaturan')
            assert r.status_code==200,r.text[-2000:]
            label=role+('-g'+str(1 if gudang==g1 else 2) if gudang else '')
            (out/(label+'-pengaturan.html')).write_text(r.text)
            (out/(label+'-menu.json')).write_text((await c.get('/api/actions/menu')).text)
            (out/(label+'-lain.html')).write_text((await c.get('/pekerjaan/catat-lain')).text)
            soup=BeautifulSoup(r.text,'html.parser')
            assert soup.find(id='daftar-akses')
            hasil.append([n.get_text(' ',strip=True) for n in soup.select('.laci-seksi .pintu__nama')])
            assert 'Kabar' in hasil[-1]
            assert 'Super Admin' in r.text and 'Operator G1' in r.text
            akses=await c.get('/pengaturan/akses')
            assert akses.status_code==200 and 'id="daftar-akses"' in akses.text
            assert (await c.get('/pekerjaan/catat-lain')).status_code==200
            # Halaman data terbatas tetap menolak operator walaupun pintunya terlihat.
            if role==P.OPERATOR:
                assert soup.select('[aria-disabled="true"]')
                assert 'KLEDO_API_KEY' not in r.text
                assert (await c.get('/audit')).status_code==403
                assert (await c.get('/pengguna')).status_code==403
            r=await c.get('/')
            (out/(label+'-beranda.html')).write_text(r.text)
            soup=BeautifulSoup(r.text,'html.parser')
            assert len(soup.select('.alur-gudang'))==2
    assert all(nama==hasil[0] for nama in hasil)


@pytest.mark.parametrize('role', [P.SUPERADMIN, P.OPERATOR])
async def test_mode_uji_memiliki_tempat_yang_sama_dengan_izin_berbeda(pg, pabrik, monkeypatch, role):
    from app.web import pengaturan
    from bs4 import BeautifulSoup
    monkeypatch.setattr(pengaturan.settings, 'mode_uji', True)
    async with pg() as db:
        op=await db.get(User,pabrik['op2'])
        gudang=op.default_warehouse_id
    async with await _klien(pg,role=role,gudang_id=gudang) as c:
        r=await c.get('/pengaturan')
        assert r.status_code==200
        soup=BeautifulSoup(r.text,'html.parser')
        assert 'Hapus data uji' in soup.get_text()
        assert bool(soup.select('a[href="/pengaturan/mode-uji"]')) == (role==P.SUPERADMIN)
        if role==P.OPERATOR:
            assert (await c.get('/pengaturan/mode-uji')).status_code==403
