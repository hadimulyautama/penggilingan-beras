"""Pengaturan memakai endpoint/konfigurasi lama melalui navigasi baru."""
import os
import re
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import func, select, update

from app.models import User, ProduksiAkun, Warehouse, Dryer, Silo, SetelanPabrik
from app.services import setelan
from app.web import csrf, security
from hmu_identitas import peran as P
from tests.pg.test_identitas import _orang, _token
from tests.pg.test_qc_berjalan import giling, _catat

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def master(pg):
    from app.services.seed import seed_master
    await seed_master()


async def klien(pg, peran=P.ADMIN, gd=None, nama='Pemeriksa Pengaturan', username='pengaturan_uji'):
    from app.main import app
    aid, uid = await _orang(pg, nama=nama, role=peran, username=username, gudang=gd)
    c = httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji')
    c.cookies.set(security.NAMA_COOKIE,await _token(pg,aid))
    c.cookies.set(csrf.NAMA_COOKIE,csrf.terbitkan_baru())
    return c, aid, uid


async def cap(c,path='/pengaturan'):
    page = await c.get(path)
    assert page.status_code == 200
    return re.search(r'name="_csrf" value="([^"]+)"',page.text)[1]


async def kirim(c,path,data,asal='/pengaturan'):
    return await c.post(path,data={'_csrf':await cap(c,asal),**data})


@pytest.mark.parametrize('peran,gd',[(P.SUPERADMIN,None),(P.ADMIN,None),(P.OPERATOR,'Gudang 1'),(P.OPERATOR,'Gudang 2'),(P.OPERATOR,None)])
async def test_kelompok_dan_endpoint_setiap_peran(pg,master,peran,gd):
    c,_,_=await klien(pg,peran,gd)
    async with c:
        page=await c.get('/pengaturan')
        assert page.status_code==200
        assert 'Akun &amp; perangkat' in page.text and 'Mode terik' in page.text
        assert 'Peran contoh' not in page.text and 'Berdampingan' not in page.text
        assert 'name="nama"' not in page.text and 'name="sandi_lama"' not in page.text
        for bagian in ('akun','peran','sesi','sistem'):
            r=await c.get('/pengaturan/'+bagian)
            assert r.status_code==200 and 'href="/pengaturan"' in r.text
        admin=P.admin_keatas(peran)
        for bagian in ('sebab-berhenti','mutu','kledo'):
            assert (await c.get('/pengaturan/'+bagian)).status_code==(200 if admin else 403)
        if not admin:
            for path,data in [('/pengaturan/nama',{'nama':'x'}),('/pengaturan/fitur-mutu',{'aktif':'0'}),('/pengaturan/sebab-jeda',{'jenis':'giling','tambah':'uji'}),('/pengaturan/kledo-kontak',{})]:
                r=await kirim(c,path,data)
                assert r.status_code==(303 if path.endswith('/nama') else 403)
            assert 'Pencatatan mutu' in page.text and 'List audit' in page.text
            assert 'href="/audit"' not in page.text and 'href="/pengaturan/mutu"' not in page.text


async def test_admin_sementara_tetap_bisa_kelola_lalu_terkunci_setelah_ada_super(pg,master):
    async with pg() as db:
        await db.execute(update(User).where(User.role==P.SUPERADMIN).values(status='nonaktif'))
        await db.commit()
    c,_,_=await klien(pg)
    async with c:
        for path in ('/pengguna','/pengaturan/alat','/pengaturan/gudang'):
            assert (await c.get(path)).status_code==200
        assert 'Belum ada akun Super Admin aktif' in (await c.get('/pengaturan')).text
        superc,_,_=await klien(pg,P.SUPERADMIN,username='super_pengaturan',nama='Super Pemeriksa')
        await superc.aclose()
        home=await c.get('/pengaturan')
        assert 'href="/pengguna"' not in home.text and 'href="/audit"' in home.text
        for path in ('/pengguna','/pengaturan/alat','/pengaturan/gudang'):
            assert (await c.get(path)).status_code==403
        assert (await c.get('/audit')).status_code==200


async def test_nama_validasi_dan_tujuan_baru_tetap_memakai_identitas_lama(pg,master):
    c,_,uid=await klien(pg)
    async with c:
        r=await kirim(c,'/pengaturan/nama',{'nama':'  x ','kembali_pengaturan':'/pengaturan/akun'})
        assert r.headers['location']=='/pengaturan/akun?err=nama-pendek'
        await _orang(pg,nama='Nama Terpakai',role=P.ADMIN,username='nama_terpakai')
        r=await kirim(c,'/pengaturan/nama',{'nama':' NAMA   TERPAKAI ','kembali_pengaturan':'/pengaturan/akun'})
        assert r.headers['location']=='/pengaturan/akun?err=nama-dipakai'
        r=await kirim(c,'/pengaturan/nama',{'nama':' Nama   Baru ','kembali_pengaturan':'/pengaturan/akun'})
        assert r.headers['location']=='/pengaturan/akun?pesan=nama-diganti'
        page=await c.get(r.headers['location'])
        assert 'Nama Baru' in page.text and 'termasuk yang sudah lewat' in page.text
    async with pg() as db:
        assert (await db.get(User,uid)).nama=='Nama Baru'


async def test_sandi_salah_konfirmasi_sesi_lama_dan_kembali(pg,master):
    c,aid,_=await klien(pg)
    old=await _token(pg,aid)
    async with c:
        path='/ganti-sandi?kembali_pengaturan=/pengaturan/akun'
        page=await c.get(path)
        assert 'name="sandi_lama"' in page.text and 'href="/pengaturan/akun"' in page.text
        token=re.search(r'name="_csrf" value="([^"]+)"',page.text)[1]
        data={'_csrf':token,'sandi_lama':'salah','sandi_baru':'rahasia456','ulangi':'rahasia456','kembali_pengaturan':'/pengaturan/akun'}
        r=await c.post('/ganti-sandi',data=data)
        assert r.status_code==200 and 'name="sandi_lama"' in r.text
        data['sandi_lama']='rahasia123';data['ulangi']='berbeda'
        assert 'tidak sama' in (await c.post('/ganti-sandi',data=data)).text
        data['ulangi']='rahasia456'
        r=await c.post('/ganti-sandi',data=data)
        assert r.headers['location']=='/pengaturan/akun?pesan=sandi-diganti'
        assert (await c.get('/api/me')).status_code==200
        from app.main import app
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji',cookies={security.NAMA_COOKIE:old}) as other:
            assert (await other.get('/api/me')).status_code==401


async def test_mode_terik_per_perangkat_dan_keluar_semua_mencabut_sesi(pg,master):
    from app.main import app
    c,aid,_=await klien(pg)
    async with c,httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as other:
        other.cookies.set(security.NAMA_COOKIE,await _token(pg,aid))
        other.cookies.set(csrf.NAMA_COOKIE,csrf.terbitkan_baru())
        r=await kirim(c,'/pengaturan/terik',{'balik':'/pengaturan'})
        assert r.headers['location']=='/pengaturan'
        assert c.cookies.get('produksi_terik')=='0' and other.cookies.get('produksi_terik') is None
        page=await c.get('/pengaturan')
        assert 'aria-pressed="false"' in page.text
        assert 'aria-pressed="true"' in (await other.get('/pengaturan')).text
        assert (await kirim(c,'/keluar-semua',{})).status_code==303
        assert (await other.get('/api/me')).status_code==401
        assert (await c.get('/api/me')).status_code==401


async def test_pilihan_gudang_dan_samaran_tidak_mengubah_profil(pg,master):
    c,_,uid=await klien(pg,P.OPERATOR)
    async with c:
        for choice in ('operator:g1','operator:g2',''):
            r=await kirim(c,'/lihat-sebagai',{'peran':choice,'kembali_pengaturan':'/pengaturan/peran'})
            assert r.headers['location']=='/pengaturan/peran'
            page=await c.get('/pengaturan/peran')
            assert f'value="{choice}" selected' in page.text
            assert (await c.get('/retur')).status_code==403
        await kirim(c,'/lihat-sebagai',{'peran':P.SUPERADMIN,'kembali_pengaturan':'/pengaturan/peran'})
        assert (await c.get('/pengguna')).status_code==403
    async with pg() as db:
        u=await db.get(User,uid)
        assert u.role==P.OPERATOR and u.default_warehouse_id is None


async def test_sebab_qc_tersimpan_dan_validasi_lama(pg,master):
    c,_,_=await klien(pg)
    async with c:
        r=await kirim(c,'/pengaturan/sebab-jeda',{'jenis':'giling','tambah':'Pemeriksaan terencana','kembali_pengaturan':'/pengaturan/sebab-berhenti'})
        assert r.headers['location']=='/pengaturan/sebab-berhenti?pesan=sebab-diubah'
        assert 'Pemeriksaan terencana' in (await c.get(r.headers['location'])).text
        r=await kirim(c,'/pengaturan/sebab-jeda',{'jenis':'giling','tambah':'Pemeriksaan terencana','kembali_pengaturan':'/pengaturan/sebab-berhenti'})
        assert 'err_teks' in r.headers['location']
        await kirim(c,'/pengaturan/sebab-jeda',{'jenis':'giling','tambah':'X'*121,'kembali_pengaturan':'/pengaturan/sebab-berhenti'})
        async with pg() as db:
            assert 'X'*120 in (await setelan.sebab_jeda(db))['giling']
        async with pg() as db:
            daftar=await setelan.sebab_jeda(db)
        for s in daftar['giling'][:-1]:
            await kirim(c,'/pengaturan/sebab-jeda',{'jenis':'giling','buang':s,'kembali_pengaturan':'/pengaturan/sebab-berhenti'})
        r=await kirim(c,'/pengaturan/sebab-jeda',{'jenis':'giling','buang':daftar['giling'][-1],'kembali_pengaturan':'/pengaturan/sebab-berhenti'})
        assert 'err_teks' in r.headers['location']
        for aktif in ('0','1'):
            r=await kirim(c,'/pengaturan/fitur-mutu',{'aktif':aktif,'kembali_pengaturan':'/pengaturan/mutu'})
            assert r.headers['location'].startswith('/pengaturan/mutu?pesan=')
            page=await c.get('/pengaturan/mutu')
            assert f'aria-checked="{"true" if aktif=="1" else "false"}"' in page.text
            async with pg() as db:
                assert await setelan.fitur_mutu(db)==(aktif=='1')
        # URL lama tetap mengembalikan pesan ke halaman utama; alamat luar ditolak.
        r=await kirim(c,'/pengaturan/fitur-mutu',{'aktif':'1','kembali_pengaturan':'https://invalid.example'})
        assert r.headers['location'].startswith('/pengaturan?pesan=')


@pytest.mark.parametrize('keadaan',['belum','berjalan','selesai','gagal'])
async def test_status_kledo_tanpa_menghubungi_layanan_nyata(pg,master,monkeypatch,keadaan):
    from app.services import kledo_sinkron
    from app.database import now_local
    state=SimpleNamespace(terkonfigurasi=keadaan!='belum',sedang_berjalan=keadaan=='berjalan',
        gagal_terakhir='Gangguan uji' if keadaan=='gagal' else None,
        hasil_terakhir='2 pelanggan diperbarui' if keadaan=='selesai' else None,selesai_pada=now_local())
    monkeypatch.setattr(kledo_sinkron,'status',lambda:state)
    c,_,_=await klien(pg)
    async with c:
        page=await c.get('/pengaturan/kledo')
        assert page.status_code==200
        for key,msg in [('belum','Kledo belum tersambung'),('berjalan','Sedang berjalan'),('selesai','2 pelanggan diperbarui'),('gagal','Gangguan uji')]:
            if key==keadaan: assert msg in page.text


async def test_csrf_pengelolaan_koordinat_dan_perlindungan_gudang(pg,master):
    c,_,_=await klien(pg,P.SUPERADMIN)
    async with c:
        assert (await c.post('/pengaturan/nama',data={'nama':'Nama Tanpa CSRF'})).status_code==403
        for lat,lon in [('salah','0'),('91','0'),('0','181')]:
            r=await kirim(c,'/pengaturan/gudang/tambah',{'nama':'Gudang Uji','latitude':lat,'longitude':lon})
            assert 'err_teks' in r.headers['location']
        r=await kirim(c,'/pengaturan/gudang/tambah',{'nama':'Gudang Uji','alamat':'Alamat uji','latitude':'-6,2','longitude':'106,8'})
        assert 'pesan=gudang-ditambah' in r.headers['location']
        async with pg() as db:
            wh=await db.scalar(select(Warehouse).where(Warehouse.nama_gudang=='Gudang Uji'))
            assert float(wh.latitude)==-6.2 and float(wh.longitude)==106.8
            g1=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g1'))
        r=await kirim(c,'/pengaturan/gudang/hapus',{'gudang_id':g1.id})
        assert 'err_teks' in r.headers['location']
        r=await kirim(c,'/pengaturan/alat/dryer',{'nama':'Pengering uji','kapasitas_kg':'30000'})
        assert 'pesan=alat-ditambah' in r.headers['location']
        async with pg() as db:
            dryer=await db.scalar(select(Dryer).where(Dryer.nama=='Pengering uji'))
        r=await kirim(c,'/pengaturan/alat/dryer/edit',{'dryer_id':dryer.id,'nama':'Pengering uji baru','kapasitas_kg':'28000','target_kadar_air':'13,5'})
        assert 'pesan=alat-diubah' in r.headers['location']
        async with pg() as db:
            dryer=await db.get(Dryer,dryer.id)
            assert dryer.nama=='Pengering uji baru' and float(dryer.target_kadar_air)==13.5


async def test_mematikan_qc_tidak_menghapus_catatan_dan_kembali_membaca_data_lama(pg,giling):
    from app.models import MillingQcLog
    from app.penggilingan.gudang1.services.milling import qc_rata
    await _catat(pg,giling,kadar_air=13,broken=5,susut=1)
    c,_,_=await klien(pg)
    async with c:
        for aktif in ('0','1'):
            assert (await kirim(c,'/pengaturan/fitur-mutu',{'aktif':aktif,'kembali_pengaturan':'/pengaturan/mutu'})).status_code==303
            async with pg() as db:
                assert await db.scalar(select(func.count()).select_from(MillingQcLog))==1
                rata=await qc_rata(db,giling['id'])
                assert rata.n==1 and rata.kadar_air==13


async def test_sandi_awal_tetap_wajib_dan_logout_satu_perangkat_tidak_memutus_yang_lain(pg,master):
    from app.main import app
    c,aid,_=await klien(pg,P.OPERATOR,'Gudang 1')
    async with pg() as db:
        akun=await db.get(ProduksiAkun,aid);akun.harus_ganti_sandi=True
        await db.commit()
    async with c:
        r=await kirim(c,'/pengaturan/nama',{'nama':'Belum boleh berubah'})
        assert r.status_code==403
        page=await c.get('/ganti-sandi')
        assert 'name="sandi_lama"' not in page.text
        token=re.search(r'name="_csrf" value="([^"]+)"',page.text)[1]
        r=await c.post('/ganti-sandi',data={'_csrf':token,'sandi_baru':'rahasia456','ulangi':'rahasia456'})
        assert r.status_code==303
        async with pg() as db:
            assert not (await db.get(ProduksiAkun,aid)).harus_ganti_sandi
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji',cookies={security.NAMA_COOKIE:await _token(pg,aid)}) as other:
            assert (await kirim(c,'/keluar',{})).status_code==303
            assert (await c.get('/api/me')).status_code==401
            assert (await other.get('/api/me')).status_code==200


async def test_bukti_html_pengaturan_dari_endpoint_asli(pg,master):
    out=os.environ.get('BUKTI_PENGATURAN_DIR')
    if not out: return
    root=Path(out);root.mkdir(parents=True,exist_ok=True)
    for peran,gd,label in [(P.SUPERADMIN,None,'super'),(P.ADMIN,None,'admin'),(P.OPERATOR,'Gudang 1','g1'),(P.OPERATOR,'Gudang 2','g2')]:
        c,_,_=await klien(pg,peran,gd,nama='Pemeriksa '+label,username='potret_'+label)
        async with c:
            for terik in ('0','1'):
                c.cookies.set('produksi_terik',terik)
                for bagian in ('','akun','peran','sesi','sebab-berhenti','mutu','kledo','sistem'):
                    page=await c.get('/pengaturan'+('/'+bagian if bagian else ''))
                    if page.status_code==200:
                        (root/f'{label}-{terik}-{bagian or "utama"}.html').write_text(page.text)
