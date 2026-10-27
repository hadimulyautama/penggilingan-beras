"""Integrasi HTTP dua aplikasi dengan DB lokal dan kedua rantai migrasi nyata."""
import os,re,socket,subprocess,sys,time,json
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import urlsplit
from uuid import uuid4
import httpx
import pytest
from sqlalchemy import select,text

from app.models import User,ProductSku,KemasanTara,OutgoingRecord,OutgoingItem
from app.services import barang_keluar as bk
from tests.pg.test_barang_keluar import gudang,_stok,_pelanggan
from hmu_identitas import peran as P
from hmu_identitas.model import Akun
from hmu_identitas.sandi import hash_sandi
from app.models import Pelanggan, CustomerReturn, FinishedGoodsStock
from app.services import retur_pengajuan, retur_penerimaan
from sqlalchemy import func

pytestmark=[pytest.mark.asyncio,pytest.mark.dua_aplikasi]
ROOT=Path(__file__).resolve().parents[2]
TF=Path(os.environ.get('UJI_TF_ROOT',str(ROOT.parent/'timbangan')))
OUT=Path(os.environ.get('UJI_RETUR_OUT',str(ROOT/'output/ci-retur-dua-app')))


def _jaga_url(url):
    # Jangan izinkan parameter query mengganti host koneksi yang sudah
    # diperiksa. Profil lama tetap sah; CI punya database sementara sendiri.
    try:
        parsed=urlsplit(url)
        nama=parsed.path.removeprefix('/')
        sah=(parsed.scheme=='postgresql+asyncpg' and parsed.hostname=='127.0.0.1'
             and parsed.port==int(os.environ.get('UJI_RETUR_PORT','56639')) and not parsed.query and not parsed.fragment
             and (nama=='uji_detail_retur_duaapp' or re.fullmatch(r'uji_tf_retur_[a-z0-9_]+',nama)))
    except ValueError:
        sah=False
    assert sah, 'DB retur dua aplikasi wajib loopback pada port uji (bawaan56639) dan nama uji_tf_retur_* atau uji_detail_retur_duaapp, tanpa query.'
    return url


def _profil_url():
    url=os.environ.get('UJI_PG_URL','')
    if not url:
        pytest.skip('Profil retur dua aplikasi memerlukan UJI_PG_URL lokal tersendiri.')
    return _jaga_url(url)


@pytest.fixture(scope='session')
def _skema_head():
    # Kedua aplikasi berbagi fondasi 0026. Timbangan mengambil alih sesudah
    # fondasi itu, sebelum migrasi PadiFlow menambah kolom kompatibilitas.
    url=_profil_url()
    assert (TF/'app/timbangan/main.py').is_file() and (TF/'.venv/bin/python').is_file(), 'Source/interpreter TeraFlow retur belum disiapkan.'
    OUT.mkdir(parents=True,exist_ok=True)
    env={**os.environ,'DATABASE_URL':url}
    steps=[(ROOT,sys.executable,['upgrade','0063_sebab_selisih_timbang']),
           (TF,str(TF/'.venv/bin/python'),['stamp','0026_timbangan_hapus_pengawas']),
           (TF,str(TF/'.venv/bin/python'),['upgrade','0038_kunci_baris_64']),
           (ROOT,sys.executable,['upgrade','head']),
           (TF,str(TF/'.venv/bin/python'),['upgrade','head'])]
    import asyncio
    from sqlalchemy.ext.asyncio import create_async_engine
    async def versi():
        e=create_async_engine(url)
        async with e.connect() as c:
            ada=await c.scalar(text("SELECT to_regclass('alembic_version_timbangan')"))
            rev=await c.scalar(text('SELECT version_num FROM alembic_version_timbangan')) if ada else None
        await e.dispose();return rev
    rev=asyncio.run(versi())
    if rev=='0047_pengiriman_snapshot':steps=steps[-2:]
    elif rev is not None:raise AssertionError('Database uji harus baru atau sudah di head kedua aplikasi; jangan menstempel ulang skema yang sudah terisi.')
    for i,(cwd,python,args) in enumerate(steps):
        r=subprocess.run([python,'-m','alembic',*args],cwd=cwd,env=env,capture_output=True,text=True,timeout=180)
        (OUT/f'migrasi-dua-app-{i}.log').write_text(r.stdout+r.stderr)
        assert r.returncode==0,r.stderr[-2000:]
    return url


def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


@contextmanager
def servers(url):
    _jaga_url(url)
    import shlex
    alat=OUT/'bin';alat.mkdir(exist_ok=True)
    shim=alat/'alembic';shim.write_text('#!/bin/sh\nexec '+shlex.quote(str(TF/'.venv/bin/python'))+' -m alembic "$@"\n');shim.chmod(0o755)
    env={**os.environ,'DATABASE_URL':url,'INTERNAL_API_TOKEN':'uji-lintas-kiriman',
         'PATH':str(alat)+os.pathsep+os.environ.get('PATH',''),'TIMBANGAN_SECRET_KEY':'uji-lintas-timbangan-secret','PRODUKSI_API_TOKEN':'uji-lintas-kiriman'}
    # Skema produksi dibangun fixture pg melalui Alembic; skema Timbangan
    # menyusul dengan runner deployment yang sama, bukan create_all.
    r=subprocess.run([str(TF/'.venv/bin/python'),'-m','scripts.siapkan_skema'],cwd=TF,env=env,capture_output=True,text=True,timeout=90)
    (OUT/'migrasi-timbangan.log').write_text(r.stdout+r.stderr)
    assert r.returncode==0,r.stderr[-2000:]
    p,t=port(),port();env['PRODUKSI_API_URL']=f'http://127.0.0.1:{p}'
    env['PYTHONPATH']=str(ROOT/'tests/pg')
    handles=[];procs=[]
    try:
        for cwd,python,module,n in [(ROOT,sys.executable,'_retur_api_uji:app',p),(TF,str(TF/'.venv/bin/python'),'app.timbangan.main:app',t)]:
            log=(OUT/f'server-lintas-{n}.log').open('w');handles.append(log)
            procs.append(subprocess.Popen([python,'-m','uvicorn',module,'--host','127.0.0.1','--port',str(n),'--log-level','warning'],cwd=cwd,env=env,stdout=log,stderr=log))
            for _ in range(150):
                try:
                    with socket.create_connection(('127.0.0.1',n),timeout=.1):break
                except OSError:time.sleep(.1)
            else:raise AssertionError('Server uji lintas aplikasi tidak hidup')
        yield f'http://127.0.0.1:{t}',f'http://127.0.0.1:{p}'
    finally:
        for p in procs:p.terminate()
        for p in procs:
            try:p.wait(timeout=4)
            except subprocess.TimeoutExpired:p.kill();p.wait()
        for log in handles:log.close()


async def test_http_retur_selesai_tanpa_padi_lalu_penerimaan_baca_saja(pg):
    async with pg() as db:
        u=User(nama='Admin Retur Uji',role=P.ADMIN,status='aktif');db.add(u);await db.flush()
        a=Akun(user_id=u.id,username='uji_retur',password_hash=hash_sandi('uji-retur-aman'));db.add(a)
        pelanggan=Pelanggan(nama_pelanggan='Pelanggan Retur Uji',kledo_contact_id=900001);db.add(pelanggan);await db.flush()
        await db.execute(text("INSERT INTO timbangan_akun(username,nama,role,akun_id,status,perangkat_kode,token_version) VALUES ('uji_retur','Admin Retur Uji','ADMIN',:aid,'aktif','UR',1)"),{'aid':a.id})
        await db.commit();pid=pelanggan.id;uid=u.id;aid=a.id
    with servers(os.environ['UJI_PG_URL']) as (tf,pf):
        async with httpx.AsyncClient(base_url=tf,timeout=30,follow_redirects=False) as c:
            r=await c.post('/timbangan/masuk',data={'username':'uji_retur','sandi':'uji-retur-aman','perangkat':'UR'});assert r.status_code==303
            r=await c.get('/timbangan/timbang/RETUR_PELANGGAN');assert r.status_code==200
            kunci=re.search(r'name="kunci" value="([^"]+)"',r.text).group(1)
            r=await c.post('/timbangan/timbang/RETUR_PELANGGAN',data={'kunci':kunci,'berat_kg':'9250','supplier_id':str(pid),'nomor_polisi':'B 1 UJI','nama_sopir':'Sopir uji'})
            assert r.status_code==303 and 'err=' not in r.headers['location'],r.headers.get('location')
            async with pg() as db:tid=await db.scalar(text('SELECT id FROM timbangan_transaksi'))
            # Putus sumber baca sebelum timbang kedua; tidak menjadi syarat baru.
            async with httpx.AsyncClient(base_url=pf) as pc:
                await pc.post('/uji/gangguan',json={'baca':True})
            r=await c.post(f'/timbangan/tiket/{tid}',data={'berat_kg':'9000','jumlah_karung':'10','aksi':'selesai'})
            assert r.status_code==303 and 'err=' not in r.headers['location'],r.headers.get('location')
            r=await c.get(f'/timbangan/transaksi/{tid}');assert r.status_code==200 and 'Status penerimaan belum dapat dipastikan' in r.text
            assert '250,00 kg' in r.text
            async with httpx.AsyncClient(base_url=pf) as pc:
                await pc.post('/uji/gangguan',json={'baca':False})
            r=await c.get(f'/timbangan/transaksi/{tid}');assert r.status_code==200 and 'Belum ada pengajuan terhubung' in r.text
            async with pg() as db:
                t=(await db.execute(text('SELECT berat_barang_kg,total_tara_kg,status_tiket FROM timbangan_transaksi WHERE id=:id'),{'id':tid})).one()
                assert float(t.berat_barang_kg)==250 and t.total_tara_kg==0 and t.status_tiket=='SELESAI'
                # Data uji sumber memiliki identitas eksplisit, tidak menebak plat.
                from app.database import now_local
                from app.models import PackagingMaterial, PackageSize, Warehouse
                mat=PackagingMaterial(kode='retur-uji',nama='Karung uji',aktif=True);size=PackageSize(ukuran_kg=25,aktif=True)
                db.add_all([mat,size,Warehouse(nama_gudang='Gudang uji',kode_fungsi='g2',aktif=True)]);await db.flush()
                sku=ProductSku(kategori='menir',packaging_material_id=mat.id,package_size_id=size.id,aktif=True);db.add(sku);await db.flush()
                db.add(KemasanTara(packaging_material_id=mat.id,package_size_id=size.id,tara_per_karung_kg=.1))
                now=now_local();o=OutgoingRecord(kode='OUT-RETUR-UJI',pelanggan_id=pid,tanggal=now.date(),waktu=now,input_by=uid,status='selesai');db.add(o);await db.flush()
                i=OutgoingItem(outgoing_record_id=o.id,item_type='finished_goods',product_sku_id=sku.id,jumlah_karung=20,berat_kg=500);db.add(i);await db.flush()
                rr=await retur_pengajuan.simpan(db,pengiriman_id=o.id,tiket_id=tid,jumlah={i.id:'10'},pelaku_id=uid)
                await db.commit();rid=rr.id
            # GET status sesuai belum boleh menjadi diterima atau menambah stok.
            for _ in range(2):
                r=await c.get(f'/timbangan/transaksi/{tid}');assert r.status_code==200 and 'Pencocokan sesuai · belum diterima' in r.text
            async with pg() as db:
                assert await db.scalar(select(func.count()).select_from(CustomerReturn))==0
                rec=await retur_penerimaan.periksa_dan_terima(db,rid);await db.commit();assert rec
            for _ in range(2):
                r=await c.get(f'/timbangan/transaksi/{tid}');assert r.status_code==200 and 'Diterima otomatis' in r.text
            for fmt in ('80mm','ncr','epos'):
                r=await c.get(f'/timbangan/transaksi/{tid}/cetak/{fmt}');assert r.status_code==200
            async with pg() as db:
                assert await db.scalar(select(func.count()).select_from(CustomerReturn))==1
                assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock))==1
                assert await db.scalar(text('SELECT count(*) FROM timbangan_transaksi'))==1
                assert await db.scalar(text('SELECT count(*) FROM timbangan_cetak'))==0

            # Identitas sama, izin baca berubah menurut mode; tiket dan stok utuh.
            async with pg() as db:
                u=await db.get(User,uid);u.role=P.SUPERADMIN;await db.commit()
            for mode in ('operator:g1','operator:g2','admin'):
                c.cookies.set('produksi_lihat',mode)
                r=await c.get(f'/timbangan/transaksi/{tid}')
                assert r.status_code==200
                if mode.startswith('operator:'):
                    assert 'Rincian PadiFlow dibatasi oleh izin akun' in r.text
                    assert 'OUT-RETUR-UJI' not in r.text and '250,00 kg' in r.text
                else:assert 'Diterima otomatis' in r.text and 'OUT-RETUR-UJI' in r.text
                async with httpx.AsyncClient(base_url=pf) as pc:
                    response=await pc.get(f'/internal/retur/tiket/{tid}/detail',headers={'X-Internal-Token':'uji-lintas-kiriman','X-Operator-Akun':str(aid),'X-Produksi-Lihat':mode})
                    assert response.status_code==(403 if mode.startswith('operator:') else 200)
            # Browser nyata membaca dua app lokal; jaringan selain loopback diblokir.
            if os.environ.get('UJI_RETUR_BROWSER')=='1':
                from playwright.async_api import async_playwright
                async with async_playwright() as browser_api:
                    browser=await browser_api.chromium.launch()
                    for mode,width in [('operator:g2',390),('admin',1280)]:
                        ctx=await browser.new_context(viewport={'width':width,'height':900})
                        async def jaringan(route):
                            if route.request.url.startswith((tf,pf)):await route.continue_()
                            else:await route.abort()
                        await ctx.route('**/*',jaringan)
                        cookies=[{'name':k.name,'value':k.value,'url':tf} for k in c.cookies.jar if k.name!='produksi_lihat']
                        cookies.append({'name':'produksi_lihat','value':mode,'url':tf})
                        await ctx.add_cookies(cookies)
                        page=await ctx.new_page();await page.goto(f'{tf}/timbangan/transaksi/{tid}')
                        await page.get_by_text('Rincian PadiFlow dibatasi oleh izin akun' if mode.startswith('operator:') else 'Diterima otomatis',exact=False).first.wait_for()
                        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
                        await page.locator('#pembuka').wait_for(state='hidden')
                        await page.screenshot(path=str(OUT/f'lihat-{width}.png'),full_page=True)
                        await ctx.close()
                    await browser.close()
            async with pg() as db:
                assert (await db.get(User,uid)).role==P.SUPERADMIN
                assert await db.scalar(select(func.count()).select_from(CustomerReturn))==1
                assert await db.scalar(select(func.count()).select_from(FinishedGoodsStock))==1
                assert await db.scalar(text('SELECT count(*) FROM timbangan_transaksi'))==1
                assert await db.scalar(text('SELECT count(*) FROM timbangan_cetak'))==0
            (OUT/'mode-live.json').write_text(json.dumps(dict(super_ke_operator_g1_dibatasi=True,super_ke_operator_g2_dibatasi=True,super_ke_admin_tersedia=True,stok_tidak_berubah=True,akun_asli_tetap_super=True,browser=[390,1280] if os.environ.get('UJI_RETUR_BROWSER')=='1' else []),indent=2))
