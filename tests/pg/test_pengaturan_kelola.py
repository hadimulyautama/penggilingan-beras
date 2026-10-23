"""Regresi formulir pengelolaan lama dari pintu Pengaturan baru."""
import pytest
from sqlalchemy import select
from app.models import User, ProduksiAkun, Warehouse, Silo
from app.config import settings
from hmu_identitas import peran as P
from tests.pg.test_pengaturan_usulan import master, klien, kirim

pytestmark=pytest.mark.asyncio


async def test_orang_akun_peran_reset_dan_aktif_nonaktif(pg,master):
    c,_,_=await klien(pg,P.SUPERADMIN)
    async with c:
        assert (await kirim(c,'/pengguna/orang-baru',{'nama':'Orang pengelolaan uji','peran':P.OPERATOR,'gudang':'1'})).status_code==200
        async with pg() as db:
            u=await db.scalar(select(User).where(User.nama=='Orang pengelolaan uji'))
            uid=u.id
        assert (await kirim(c,'/pengguna/buat',{'user_id':uid,'username':'kelola_uji'})).status_code==200
        async with pg() as db:
            akun=await db.scalar(select(ProduksiAkun).where(ProduksiAkun.user_id==uid))
            aid,hash_awal=akun.id,akun.password_hash
            assert akun.harus_ganti_sandi
        assert (await c.get(f'/pengguna/{aid}')).status_code==200
        r=await kirim(c,f'/pengguna/{aid}',{'nama':'Orang pengelolaan baru','username':'kelola_baru','peran':P.ADMIN,'mode':'pribadi'})
        assert r.status_code==303
        async with pg() as db:
            assert (await db.get(User,uid)).role==P.ADMIN
            assert (await db.get(ProduksiAkun,aid)).username=='kelola_baru'
        assert (await kirim(c,'/pengguna/reset',{'akun_id':aid})).status_code==200
        async with pg() as db:
            assert (await db.get(ProduksiAkun,aid)).password_hash!=hash_awal
        for aktif in (False,True):
            assert (await kirim(c,'/pengguna/status',{'akun_id':aid})).status_code==200
            async with pg() as db:
                assert ((await db.get(User,uid)).status=='aktif')==aktif
                assert ((await db.get(ProduksiAkun,aid)).status=='aktif')==aktif


async def test_silo_dan_gudang_edit_filter_arsip_serta_perlindungan_dipakai(pg,master):
    c,_,_=await klien(pg,P.SUPERADMIN)
    async with c:
        r=await kirim(c,'/pengaturan/alat/silo',{'nama':'UJI-KELOLA','gudang':'g1'})
        assert 'pesan=alat-ditambah' in r.headers['location']
        async with pg() as db:
            silo=await db.scalar(select(Silo).where(Silo.nama_silo=='Silo UJI-KELOLA'))
            sid=silo.id
            pilihan=silo.komoditas_diizinkan
        r=await kirim(c,'/pengaturan/alat/silo/edit',{'silo_id':sid,'nama':'Silo Uji berubah','komoditas':pilihan})
        assert 'pesan=silo-diubah' in r.headers['location']
        async with pg() as db:
            assert (await db.get(Silo,sid)).nama_silo=='Silo Uji berubah'
        r=await kirim(c,'/pengaturan/alat/silo/hapus',{'silo_id':sid})
        assert 'pesan=silo-dihapus' in r.headers['location']
        async with pg() as db:
            assert not (await db.get(Silo,sid)).aktif
        r=await kirim(c,'/pengaturan/sebab-jeda',{'jenis':'pengeringan','tambah':'Bahan bakar uji habis'})
        assert r.headers['location']=='/pengaturan/alat?pesan=sebab-diubah'
        assert 'Bahan bakar uji habis' in (await c.get('/pengaturan/alat')).text
        await kirim(c,'/pengaturan/gudang/tambah',{'nama':'Gudang tambahan kelola'})
        async with pg() as db:
            wh=await db.scalar(select(Warehouse).where(Warehouse.nama_gudang=='Gudang tambahan kelola'))
            wid=wh.id
            db.add(User(nama='Pemakai gudang tambahan',role=P.OPERATOR,status='aktif',default_warehouse_id=wid))
            await db.commit()
        r=await kirim(c,'/pengaturan/gudang/edit',{'gudang_id':wid,'nama':'Gudang tambahan baru','alamat':'Alamat baru','latitude':'-6,1','longitude':'106,7'})
        assert 'pesan=gudang-diubah' in r.headers['location']
        r=await kirim(c,'/pengaturan/gudang/hapus',{'gudang_id':wid})
        assert 'err_teks' in r.headers['location']
        async with pg() as db:
            assert (await db.get(Warehouse,wid)).aktif


@pytest.mark.parametrize('mode',[False,True])
@pytest.mark.parametrize('peran',[P.OPERATOR,P.ADMIN,P.SUPERADMIN])
async def test_mode_uji_hanya_kondisi_dan_peran_lama_tanpa_menghapus_data(pg,master,monkeypatch,mode,peran):
    monkeypatch.setattr(settings,'mode_uji',mode)
    c,_,_=await klien(pg,peran,'Gudang 1' if P.operator_saja(peran) else None)
    async with c:
        page=await c.get('/pengaturan')
        assert ('href="/pengaturan/mode-uji"' in page.text)==(mode and P.super_saja(peran))
        page=await c.get('/pengaturan/mode-uji')
        assert (page.status_code==200)==(mode and P.super_saja(peran))
