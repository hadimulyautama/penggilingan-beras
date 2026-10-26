"""Integrasi HTTP dua aplikasi dengan DB lokal dan kedua rantai migrasi nyata."""
import os,re,socket,subprocess,sys,time,json
from pathlib import Path
from contextlib import contextmanager
from uuid import uuid4
import httpx
import pytest
from sqlalchemy import select,text

from app.models import User,ProductSku,KemasanTara,OutgoingRecord,OutgoingItem
from app.services import barang_keluar as bk
from tests.pg.test_barang_keluar import gudang,_stok,_pelanggan
from tests.pg.test_kiriman_pelanggan import _buat,_muat

pytestmark=pytest.mark.asyncio
ROOT=Path(__file__).resolve().parents[2];TF=Path(os.environ.get('UJI_TF_ROOT',str(ROOT.parent/'timbangan')))
OUT=Path(os.environ.get('UJI_KIRIMAN_OUT',str(ROOT.parent/'output/teraflow-kiriman-gabungan-20261026')))
OUT.mkdir(parents=True,exist_ok=True)


@pytest.fixture(scope='session')
def _skema_head():
    # Kedua aplikasi berbagi fondasi 0026. Timbangan mengambil alih sesudah
    # fondasi itu, sebelum migrasi PadiFlow menambah kolom kompatibilitas.
    url=os.environ['UJI_PG_URL']
    assert '@127.0.0.1:56627/uji_tf_kiriman_' in url
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
    assert '@127.0.0.1:56627/uji_tf_kiriman_' in url
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
        for cwd,python,module,n in [(ROOT,sys.executable,'_teraflow_api_uji:app',p),(TF,str(TF/'.venv/bin/python'),'app.timbangan.main:app',t)]:
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


async def akun(pg,g):
    from hmu_identitas.model import Akun
    from hmu_identitas.sandi import hash_sandi
    async with pg() as db:
        a=Akun(user_id=g['op'],username='uji_lintas',password_hash=hash_sandi('uji-lintas-aman'))
        db.add(a);await db.commit();return a.id


async def benih(pg,g,jumlah_pelanggan):
    from app.penggilingan.gudang2.models import PolishingProcess,PolishingOutputLog
    from app.penggilingan.inventory.finished_goods import catat_packing,catat_bekatul
    from app.database import now_local
    async with pg() as db:
        proc=await db.scalar(select(PolishingProcess))
        db.add_all([PolishingOutputLog(polishing_process_id=proc.id,jenis='medium',berat_kg=2000,waktu_update=now_local(),input_by=g['op']),PolishingOutputLog(polishing_process_id=proc.id,jenis='bekatul',berat_kg=500,waktu_update=now_local(),input_by=g['op'])]);await db.commit()
        await catat_packing(db,user=await db.get(User,g['op']),kode_pol=proc.kode_proses,kategori='beras_putih',grade='medium',material_kode='biasa',ukuran=50,jumlah_karung=40)
        await catat_bekatul(db,user=await db.get(User,g['op']),kode_pol=proc.kode_proses,berat_kg=500)
        from app.models import PackageSize
        sku50=await db.scalar(select(ProductSku).join(PackageSize,ProductSku.package_size_id==PackageSize.id).where(PackageSize.ukuran_kg==50))
        for sid,tara in [(g['sku'],'.1'),(sku50.id,'.25')]:
            sku=await db.get(ProductSku,sid)
            lama=await db.scalar(select(KemasanTara).where(KemasanTara.packaging_material_id==sku.packaging_material_id,KemasanTara.package_size_id==sku.package_size_id))
            if lama:lama.tara_per_karung_kg=tara
            else:db.add(KemasanTara(packaging_material_id=sku.packaging_material_id,package_size_id=sku.package_size_id,tara_per_karung_kg=tara))
        await db.commit();sid50=sku50.id
    data={'kelompok':[],'metode':'diantar','nama_ekspedisi':'Armada Sintetis'}
    for i in range(jumlah_pelanggan):
        pid=await _pelanggan(pg,f'Pelanggan Integrasi {i}')
        data['kelompok'].append(dict(pelanggan=str(pid),barang=[
            dict(pilih=f"bj:{g['sku']}|{g['std']}",jumlah=str(20+i*10)),
            dict(pilih=f"bj:{sid50}|{g['std']}",jumlah='2'),
            dict(pilih='cr:bekatul',jumlah='100')]))
    return await _buat(pg,g,data)


async def profil(pg,aid):
    async with pg() as db:
        await db.execute(text("INSERT INTO timbangan_akun(username,nama,role,akun_id,status,perangkat_kode,token_version) VALUES ('uji_lintas','Petugas Sintetis','PETUGAS',:aid,'aktif','UT',1)"),{'aid':aid});await db.commit()


@pytest.mark.parametrize('pelanggan,luring',[(1,False),(2,False),(2,True)])
async def test_http_satu_tiket_muatan_aktual_dan_verifikasi_bersama(pg,gudang,pelanggan,luring):
    rs=await benih(pg,gudang,pelanggan);aid=await akun(pg,gudang)
    with servers(os.environ['UJI_PG_URL']) as (tf,pf):
        await profil(pg,aid)
        async with httpx.AsyncClient(base_url=tf,follow_redirects=False,timeout=30) as c:
            r=await c.post('/timbangan/masuk',data={'username':'uji_lintas','sandi':'uji-lintas-aman','perangkat':'UT'})
            assert r.status_code==303,r.text
            from datetime import datetime,timedelta
            from zoneinfo import ZoneInfo
            key=str(uuid4());body=dict(kunci=key,berat_kg='5000',nomor_polisi='B 1234 XY',nama_sopir='Sopir Integrasi')
            body['waktu']=(datetime.now(ZoneInfo('Asia/Jakarta'))-timedelta(minutes=3)).strftime('%Y-%m-%dT%H:%M')
            r=await c.post('/timbangan/timbang/PENGIRIMAN',data=body);assert r.status_code==303,r.text
            assert '/transaksi/' in r.headers['location'],r.headers
            tid=int(re.search(r'/transaksi/(\d+)',r.headers['location'])[1])
            async with pg() as db:
                await bk.pilih_tiket_armada(db,user=await db.get(User,gudang['adm']),rec_id=rs[-1].rec.id,tiket_id=tid)
            # Muatan aktual kurang dua karung dari rencana pada pelanggan pertama.
            for i,r0 in enumerate(rs):
                async with pg() as db:
                    for n,item in enumerate(r0.baris):
                        if item.item_type=='finished_goods':
                            await bk.catat_muatan(db,user=await db.get(User,gudang['op']),item_id=item.id,jumlah_karung=int(item.jumlah_karung_perintah)-(2 if i==0 and n==0 else 0))
                        else:await bk.catat_muatan(db,user=await db.get(User,gudang['op']),item_id=item.id,berat_kg=100)
                    await bk.selesai_muat(db,user=await db.get(User,gudang['op']),rec_id=r0.rec.id,sebab='Dua karung tidak dimuat' if i==0 else '')
            stok=await _stok(pg,gudang)
            async with pg() as db:
                identitas=(await db.execute(text('SELECT pelanggan_id,pihak_nama FROM timbangan_transaksi WHERE id=:id'),{'id':tid})).first()
            async with httpx.AsyncClient(base_url=pf,timeout=30) as pc:
                payload=(await pc.get(f'/internal/pengiriman/tiket/{tid}/muatan',headers={'X-Internal-Token':'uji-lintas-kiriman'})).json()
            assert len(payload['muatan'])==3*pelanggan,payload
            expected=sum(float(x['berat_kg']) for x in payload['muatan']);assert expected==sum(float(it.berat_perintah_kg) for r0 in rs for it in r0.baris)-50
            tara=sum(x['jumlah_karung']*float(x['tara_per_karung_kg']) for x in payload['muatan'])
            assert {str(x['tara_per_karung_kg']) for x in payload['muatan']} >= {'0','0.1000','0.2500'}
            antrean=await c.get('/timbangan/tiket',params={'q':'Pelanggan Integrasi '+str(pelanggan-1)})
            assert antrean.status_code==200 and '1 dari 1 truk' in antrean.text,antrean.text[:500]
            html=await c.get(f'/timbangan/tiket/{tid}');assert html.status_code==200
            assert 'Pelanggan Integrasi 0' in html.text
            if pelanggan==2:assert 'Pelanggan Integrasi 1' in html.text
            kg=5000+expected+tara
            if luring:
                await kirim_pwa(c,tf,tid,kg)
            else:
                async with httpx.AsyncClient(base_url=pf,timeout=30) as pc:
                    await pc.post('/uji/gangguan',json={'baca':True})
                    preview=await c.post(f'/timbangan/tiket/{tid}/pratinjau',data={'berat_kg':str(kg)})
                    assert preview.status_code==422 and not preview.json()['tersedia']
                    sementara=await c.post(f'/timbangan/tiket/{tid}',data={'berat_kg':str(kg),'aksi':'sementara'})
                    assert 'err=' not in sementara.headers['location']
                    gagal=await c.post(f'/timbangan/tiket/{tid}',data={'berat_kg':str(kg),'aksi':'selesai'})
                    assert 'err=' in gagal.headers['location']
                    async with pg() as db:
                        keadaan=(await db.execute(text('SELECT timbang2_kg,status_tiket,pengiriman_snapshot FROM timbangan_transaksi WHERE id=:id'),{'id':tid})).one()
                        assert float(keadaan.timbang2_kg)==kg and keadaan.status_tiket=='TERBUKA' and keadaan.pengiriman_snapshot is None
                    await pc.post('/uji/gangguan',json={'baca':False,'verifikasi':True})
                    gagal_callback=await c.post(f'/timbangan/tiket/{tid}',data={'berat_kg':str(kg),'aksi':'selesai'})
                    assert 'err=' in gagal_callback.headers['location']
                    async with pg() as db:
                        for r0 in rs:assert (await db.get(OutgoingRecord,r0.rec.id)).status=='dimuat'
                    await pc.post('/uji/gangguan',json={'verifikasi':False})
                # Kirim ulang bacaan yang sama memulihkan callback, bukan tiket baru.
                r=await c.post(f'/timbangan/tiket/{tid}',data={'berat_kg':str(kg),'aksi':'selesai'})
                assert r.status_code==303 and 'err=' not in r.headers['location'],r.headers
            async with pg() as db:
                t=(await db.execute(text('SELECT pelanggan_id,pihak_nama,berat_barang_kg,pengiriman_snapshot FROM timbangan_transaksi WHERE id=:id'),{'id':tid})).mappings().one()
                assert (t['pelanggan_id'],t['pihak_nama'])==tuple(identitas) and float(t['berat_barang_kg'])==expected
                if pelanggan==2:assert t['pelanggan_id'] is None and t['pihak_nama'] is None
                snapshot=t['pengiriman_snapshot'];snapshot=json.loads(snapshot) if isinstance(snapshot,str) else snapshot
                assert len(snapshot['muatan'])==3*pelanggan
                for r0 in rs:assert (await db.get(OutgoingRecord,r0.rec.id)).status=='selesai'
                assert await db.scalar(text('SELECT count(*) FROM timbangan_transaksi'))==1
            assert await _stok(pg,gudang)==stok
            # Replay dan pembacaan/cetak tidak membuat stok/tiket kedua.
            async with httpx.AsyncClient(base_url=pf,timeout=30) as pc:
                r=await pc.post(f'/internal/pengiriman/tiket/{tid}/verifikasi',headers={'X-Internal-Token':'uji-lintas-kiriman','X-Operator-Akun':str(aid)},json={'sidik_sumber':payload['sidik_sumber']})
                assert r.status_code==200 and r.json()['selesai'],r.text
            for path in [f'/timbangan/transaksi/{tid}',f'/timbangan/transaksi/{tid}/cetak/80mm',f'/timbangan/transaksi/{tid}/cetak/ncr']:
                r=await c.get(path);assert r.status_code==200,(path,r.text[:100])
                if 'cetak' in path:(OUT/f'lintas-{pelanggan}-{path.rsplit("/",1)[-1]}.pdf').write_bytes(r.content)
            assert await _stok(pg,gudang)==stok
            (OUT/(f'lintas-{pelanggan}'+('-luring' if luring else '')+'.json')).write_text(json.dumps({'status':'Lulus','pelanggan':pelanggan,'baris':3*pelanggan,'tiket':1,'aktual_kg':expected,'tara_kg':tara,'stok_tidak_berubah_saat_verifikasi':True,'identitas_tiket_tidak_ditimpa':True},indent=2))


async def kirim_pwa(c,tf,tid,kg):
    import importlib.util
    if importlib.util.find_spec('playwright') is None:
        sys.path.append(str(TF/'.venv/lib/python3.11/site-packages'))
    from playwright.async_api import async_playwright
    async def tunggu_async(js):
        # wait_for_function tidak mempoll hasil false dari Promise.
        # Tunggu hasil IndexedDB sebenarnya sebelum navigasi berikutnya.
        import asyncio
        akhir=time.monotonic()+30
        while time.monotonic()<akhir:
            try:
                if await page.evaluate(js):return
            except Exception as e:
                if 'Execution context was destroyed' not in str(e):raise
            await asyncio.sleep(.1)
        raise AssertionError('Antrean belum mencapai keadaan yang diharapkan: '+js)
    async with async_playwright() as pw:
        browser=await pw.chromium.launch()
        ctx=await browser.new_context(viewport={'width':320,'height':850},reduced_motion='reduce')
        await ctx.add_cookies([{'name':k,'value':v,'url':tf} for k,v in c.cookies.items()])
        await ctx.add_init_script("localStorage.setItem('pd.tema.timbang','dark')")
        page=await ctx.new_page();errors=[];page.on('pageerror',lambda e:errors.append(str(e)))
        await page.goto(tf+f'/timbangan/tiket/{tid}')
        await page.wait_for_function('window.timbanganLuring && window.timbanganLuring.siap()')
        assert await page.locator('.kg-penerima').count()==2
        assert await page.locator('.kg-barang').count()==6
        await page.locator('[name=berat_kg]').fill(str(kg))
        await ctx.set_offline(True)
        await page.locator('[name=aksi][value=sementara]').click()
        await tunggu_async("window.timbanganLuring.antrean().then(x=>x.length===1 && x[0].status!=='terkirim')")
        assert await page.locator('[name=berat_kg]').input_value()==str(kg)
        await page.screenshot(path=str(OUT/'pwa-kiriman-320-luring.png'),full_page=True)
        await ctx.set_offline(False);await page.evaluate('window.timbanganLuring.sinkronkan()')
        await tunggu_async("window.timbanganLuring && window.timbanganLuring.antrean().then(x=>x.filter(r=>r.status==='terkirim').length===1)")
        html_server=await c.get(f'/timbangan/tiket/{tid}')
        import re
        nilai_server=re.search(r'name="berat_kg"[\s\S]*?value="([^"]*)"',html_server.text).group(1)
        if not nilai_server:
            (OUT/'pwa-server-diagnostik.html').write_text(html_server.text)
            (OUT/'pwa-antrean-diagnostik.json').write_text(json.dumps(await page.evaluate('window.timbanganLuring.antrean()'),indent=2))
        assert nilai_server, 'Bacaan sementara kosong pada HTML server'
        await page.goto(tf+f'/timbangan/tiket/{tid}')
        await page.wait_for_function('window.timbanganLuring && window.timbanganLuring.siap()')
        await page.wait_for_function("document.querySelector('[data-simpan-luring]') && !document.querySelector('[data-simpan-luring]').inert")
        tersimpan=await page.locator('[name=berat_kg]').input_value()
        if not tersimpan:
            (OUT/'pwa-prefill-diagnostik.json').write_text(json.dumps({'server':nilai_server,'input':await page.locator('[name=berat_kg]').evaluate('(e)=>({value:e.value,asli:e.defaultValue})'),'antrean':await page.evaluate('window.timbanganLuring.antrean()'),'draf':await page.evaluate('window.timbanganLuring.draf()')},indent=2))
        nilai=float(tersimpan.replace('.','').replace(',','.')) if ',' in tersimpan else float(tersimpan)
        assert nilai==kg
        await page.locator('[name=aksi][value=selesai]').click()
        await tunggu_async("window.timbanganLuring && window.timbanganLuring.antrean().then(x=>x.filter(r=>r.status==='terkirim').length===2)")
        await page.wait_for_url('**/transaksi/**')
        await page.evaluate('window.timbanganLuring.sinkronkan()')
        assert await page.evaluate('document.documentElement.scrollWidth<=innerWidth')
        await page.screenshot(path=str(OUT/'pwa-kiriman-320-selesai.png'),full_page=True)
        assert not errors
        await browser.close()
