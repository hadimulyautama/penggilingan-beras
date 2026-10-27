"""Uji terarah dua aplikasi; tidak dipanggil otomatis tanpa profil lokal."""
import os,re,socket,subprocess,sys,time
from pathlib import Path
from contextlib import contextmanager
from urllib.parse import urlsplit
import pytest,httpx
from sqlalchemy import text,select
from hmu_identitas.model import Akun
from hmu_identitas.sandi import hash_sandi
from app.models import User,ReturSupplierItem
from app.services import retur_supplier as s,retur_supplier_selesai as f
from tests.pg.test_retur_supplier import asal,user,jumlah

pytestmark=[pytest.mark.asyncio,pytest.mark.dua_aplikasi]
ROOT=Path(__file__).resolve().parents[2]
TF=Path(os.environ.get('UJI_TF_ROOT',str(ROOT.parent/'timbangan')))
OUT=Path(os.environ.get('UJI_RSP_OUT',str(ROOT/'output/uji-retur-supplier-dua-app')))


def aman():
    if os.environ.get('UJI_RSP_DUA_APP')!='1':pytest.skip('Uji dua aplikasi supplier memerlukan opt-in UJI_RSP_DUA_APP=1 dan database khusus, bukan profil CI lain.')
    url=os.environ.get('UJI_PG_URL','');u=urlsplit(url)
    if not url:pytest.skip('Profil UJI_PG_URL dan UJI_TF_ROOT diperlukan untuk uji lokal dua aplikasi.')
    assert u.hostname in ('127.0.0.1','localhost') and u.path.startswith('/uji_rsp_') and not u.query and not u.fragment,'Gunakan database loopback uji_rsp_* tanpa parameter pengganti host.'
    assert (TF/'.venv/bin/python').is_file() and (TF/'app/timbangan/main.py').is_file()
    return url


@pytest.fixture(scope='session')
def _skema_head():
    url=aman();OUT.mkdir(parents=True,exist_ok=True)
    from sqlalchemy.ext.asyncio import create_async_engine
    import asyncio
    async def versi():
        e=create_async_engine(url)
        async with e.connect() as c:
            ada=await c.scalar(text("SELECT to_regclass('alembic_version_timbangan')"))
            rev=await c.scalar(text('SELECT version_num FROM alembic_version_timbangan')) if ada else None
        await e.dispose();return rev
    rev=asyncio.run(versi())
    if rev is None:
        steps=[(ROOT,sys.executable,['upgrade','0063_sebab_selisih_timbang']),
            (TF,str(TF/'.venv/bin/python'),['stamp','0026_timbangan_hapus_pengawas']),
            (TF,str(TF/'.venv/bin/python'),['upgrade','0038_kunci_baris_64']),
            (ROOT,sys.executable,['upgrade','head']),(TF,str(TF/'.venv/bin/python'),['upgrade','head'])]
    else:
        assert rev=='0048_lintasan_transfer','Profil harus baru atau di head kompatibel; tidak menstempel ulang data.'
        steps=[(ROOT,sys.executable,['upgrade','head']),(TF,str(TF/'.venv/bin/python'),['upgrade','head'])]
    for n,(cwd,python,args) in enumerate(steps):
        r=subprocess.run([python,'-m','alembic',*args],cwd=cwd,env={**os.environ,'DATABASE_URL':url},capture_output=True,text=True,timeout=180)
        (OUT/f'migrasi-{n}.log').write_text(r.stdout+r.stderr);assert r.returncode==0,r.stderr[-2000:]
    return url


def port():
    with socket.socket() as s:s.bind(('127.0.0.1',0));return s.getsockname()[1]


@contextmanager
def servers():
    url=aman();p,t=port(),port()
    env={**os.environ,'DATABASE_URL':url,'INTERNAL_API_TOKEN':'uji-rsp','PRODUKSI_API_TOKEN':'uji-rsp',
        'TIMBANGAN_SECRET_KEY':'kunci-sesi-sintetis-lokal-rsp','PRODUKSI_API_URL':f'http://127.0.0.1:{p}',
        'PYTHONPATH':str(ROOT/'tests/pg')}
    procs=[];logs=[]
    try:
        for cwd,python,module,n in [(ROOT,sys.executable,'_rsp_api_uji:app',p),(TF,str(TF/'.venv/bin/python'),'app.timbangan.main:app',t)]:
            log=(OUT/f'http-{n}.log').open('w');logs.append(log)
            procs.append(subprocess.Popen([python,'-m','uvicorn',module,'--host','127.0.0.1','--port',str(n),'--log-level','warning'],cwd=cwd,env=env,stdout=log,stderr=log))
            for _ in range(150):
                try:
                    with socket.create_connection(('127.0.0.1',n),timeout=.1):break
                except OSError:time.sleep(.1)
            else:raise AssertionError('Server uji tidak hidup; baca log lokal.')
        yield f'http://127.0.0.1:{t}',f'http://127.0.0.1:{p}'
    finally:
        for proc in procs:proc.terminate()
        for proc in procs:
            try:proc.wait(timeout=4)
            except subprocess.TimeoutExpired:proc.kill();proc.wait()
        for log in logs:log.close()


async def test_http_timbang_koreksi_referensi_dan_keluar_sekali(pg,asal):
    async with pg() as db:
        await db.execute(text('UPDATE suppliers SET kledo_contact_id=900001 WHERE id=:id'),dict(id=asal['sid']))
        u=await db.get(User,asal['uid']);u.default_warehouse_id=asal['wh']
        a=Akun(user_id=u.id,username='uji_rsp',password_hash=hash_sandi('uji-rsp-lokal'));db.add(a);await db.flush()
        await db.execute(text("INSERT INTO timbangan_akun(username,nama,role,akun_id,status,perangkat_kode,token_version) VALUES ('uji_rsp','Admin Supplier Uji','ADMIN',:aid,'aktif','US',1)"),dict(aid=a.id))
        check=await s.periksa(db,asal['tid'],user(asal),jumlah(asal),'Mutu tidak sesuai','')
        r=await s.simpan(db,user=user(asal),tid=asal['tid'],jumlah=jumlah(asal),alasan=check['alasan'],catatan='',kunci='uji-rsp-duaapp-001',dasar=check['dasar']);await db.commit()
    with servers() as (tf,pf):
        async with httpx.AsyncClient(base_url=tf,timeout=30,follow_redirects=False) as c:
            res=await c.post('/timbangan/masuk',data={'username':'uji_rsp','sandi':'uji-rsp-lokal','perangkat':'US'});assert res.status_code==303,res.text
            res=await c.get('/timbangan/timbang/RETUR_SUPPLIER');assert res.status_code==200,res.text
            key=re.search(r'name="kunci" value="([^"]+)"',res.text).group(1)
            res=await c.post('/timbangan/timbang/RETUR_SUPPLIER',data=dict(kunci=key,berat_kg='5000',supplier_id=str(asal['sid']),nomor_polisi='B 1234 US',nama_sopir='Sopir sintetis'))
            assert res.status_code==303 and 'err=' not in res.headers['location'],res.headers.get('location')
            async with pg() as db:
                tid=await db.scalar(text("SELECT id FROM timbangan_transaksi WHERE arah='RETUR_KELUAR'"))
                await s.hubungkan(db,user=user(asal),identitas=r.id,tiket_id=tid);await db.commit()
            res=await c.get(f'/timbangan/transaksi/{tid}');assert res.status_code==200 and r.kode in res.text
            res=await c.post(f'/timbangan/tiket/{tid}',data={'berat_kg':'5280','jumlah_karung':'5','aksi':'selesai'})
            assert res.status_code==303 and 'err=' not in res.headers['location'],res.headers.get('location')
            async with pg() as db:
                t=(await db.execute(text('SELECT timbang1_kg,timbang2_kg,berat_barang_kg,total_tara_kg,tara_lain_kg FROM timbangan_transaksi WHERE id=:id'),dict(id=tid))).first()
                assert t.berat_barang_kg==280 and t.total_tara_kg==0 and t.tara_lain_kg==0
                i=await db.scalar(select(ReturSupplierItem).where(ReturSupplierItem.retur_supplier_id==r.id))
                check=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')]);await db.commit()
                assert check['status']=='perlu_koreksi'
                assert await db.scalar(text('SELECT count(*) FROM retur_supplier_keluar'))==0
            res=await c.get(f'/timbangan/transaksi/{tid}/koreksi');assert res.status_code==200
            versi=re.search(r'name="versi" value="([^"]+)"',res.text).group(1)
            res=await c.post(f'/timbangan/transaksi/{tid}/koreksi',data=dict(versi=versi,asli_timbang2_kg='5280',timbang2_kg='5249.5',alasan='Koreksi bacaan timbang setelah pemeriksaan fisik sintetis'))
            assert res.status_code==303 and 'err=' not in res.headers['location'],res.headers.get('location')
            async with pg() as db:
                check=await f.periksa(db,identitas=r.id,user=user(asal),jumlah=[dict(item_id=i.id,jumlah='5')]);await db.commit()
                assert check['status']=='siap_manual',check
                from app.services import riwayat_retur_supplier as history
                assert (await history.detail(db,r.id,user(asal)))['status']=='manual'
                await f.manual(db,identitas=r.id,user=user(asal),dasar=check['dasar'],catatan='Koreksi tiket resmi dan hasil terkini sudah diperiksa',konfirmasi=True);await db.commit()
                await f.catat_keluar(db,identitas=r.id,user=user(asal),dasar=check['dasar'],konfirmasi=True);await db.commit()
            for _ in range(2):
                res=await c.get(f'/timbangan/transaksi/{tid}');assert res.status_code==200 and 'Selesai di gudang' in res.text and r.kode in res.text
            async with httpx.AsyncClient(base_url=pf) as pc:await pc.post('/uji/gangguan',json={'baca':True})
            res=await c.get(f'/timbangan/transaksi/{tid}');assert res.status_code==200 and 'belum dapat dipastikan' in res.text
            for fmt in ('80mm','ncr','epos'):
                res=await c.get(f'/timbangan/transaksi/{tid}/cetak/{fmt}');assert res.status_code==200
            async with pg() as db:
                assert await db.scalar(text('SELECT count(*) FROM retur_supplier_keluar'))==1
                assert await db.scalar(text('SELECT count(*) FROM outgoing_items'))==0
                assert await db.scalar(text('SELECT count(*) FROM timbangan_cetak'))==0
                from hmu_identitas import peran as P
                view=await history.detail(db,r.id,user(asal))
                assert view['akses_koreksi']=='dibatasi' and view['koreksi_tiket']==[]
                u=await db.get(User,asal['uid']);u.role=P.SUPERADMIN;await db.commit()
                # Baca audit hanya setelah identitas Super + profil TF aktif
                # sah. Mode lihat sebagai Admin kembali menutup audit TF.
                view=await history.detail(db,r.id,user(asal,P.SUPERADMIN))
                assert view['akses_koreksi']=='tersedia' and len(view['koreksi_tiket'])==1
                changes=view['koreksi_tiket'][0]['nilai']
                assert any(x['field']=='timbang2_kg' and float(x['sebelum'])==5280 and float(x['sesudah'])==5249.5 for x in changes)
                assert all(x['field'] in ('timbang1_kg','timbang2_kg','berat_barang_kg','total_tara_kg','tara_lain_kg') for x in changes)
                assert (await history.detail(db,r.id,user(asal)))['akses_koreksi']=='dibatasi'
                await db.rollback()
                await db.execute(text('SET TRANSACTION READ ONLY'))
                view=await history.detail(db,r.id,user(asal,P.SUPERADMIN))
                recap=await history.daftar(db,user(asal,P.SUPERADMIN))
                assert view['status']=='done' and recap['total_keluar']==249.5
                import json
                (OUT/'bukti-native.json').write_text(json.dumps(dict(
                    migrasi_padiflow='0116_retur_supplier_keluar',migrasi_teraflow='0048_lintasan_transfer',
                    timbang1_kg=5000,timbang2_awal_kg=5280,timbang2_koreksi_kg=5249.5,
                    hasil_tiket_kg=249.5,manual_setelah_koreksi=True,ledger_keluar=1,outgoing_items=0,cetak_fisik=0,
                    riwayat_transaksi_read_only=True,rekap_keluar_kg=str(recap['total_keluar']),
                    audit_koreksi_tf_super_saja=True,field_koreksi_terbatas=True,
                    panel_selesai=True,gangguan_integrasi_tidak_palsu_sukses=True),indent=2))
