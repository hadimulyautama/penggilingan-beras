"""Pemulihan Console memutus sesi bersama dan lama di TeraFlow nyata."""
import asyncio,json,os,subprocess
from pathlib import Path
import pytest
from sqlalchemy import text
from hmu_core import KeanggotaanPerusahaan
from hmu_identitas.sandi import hash_sandi
from tests.pg.test_console_monitoring import orang,action
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_teraflow_kiriman import _skema_head
from app.services import console_bantuan as help
pytestmark=[pytest.mark.asyncio,pytest.mark.dua_aplikasi,pytest.mark.fondasi_multi]
async def test_pemulihan_sandi_dan_csrf_dua_interpreter(pg,orang):
    x=orang
    async with pg() as db:
        # Uji pemulihan sandi dimulai dari sesi yang memang diizinkan.
        # Pencabutan keanggotaan diuji terpisah dan tidak boleh dilewati.
        (await db.get(KeanggotaanPerusahaan,x['mid'])).aktif=True
        linked=await db.scalar(text("INSERT INTO timbangan_akun(username,nama,role,akun_id,status,perangkat_kode,token_version) VALUES ('operator-aktif','Operator uji','PETUGAS',:aid,'aktif','UT',1) RETURNING id"),{'aid':x['aid']})
        legacy=await db.scalar(text("INSERT INTO timbangan_akun(username,nama,role,password_hash,status,perangkat_kode,token_version) VALUES ('legacy-monitor','Petugas lama uji','PETUGAS',:h,'aktif','LG',1) RETURNING id"),{'h':hash_sandi('sandi-lama-uji-123')});await db.commit()
    async def helper(phase):
        root=Path(os.environ['UJI_TF_ROOT'])
        env={**os.environ,'PYTHONPATH':str(root),'UJI_MONITOR_DATA':json.dumps(dict(phase=phase,aid=x['aid'],linked=linked,legacy=legacy))}
        r=await asyncio.to_thread(subprocess.run,[os.environ['UJI_TF_PYTHON'],'tests/integrasi_monitoring_console.py'],cwd=root,env=env,capture_output=True,text=True,timeout=45)
        assert r.returncode==0,r.stdout+'\n'+r.stderr
        assert json.loads(r.stdout)['berhasil']
    await helper('before')
    for kind,aid,pw in [('staf',x['aid'],'sandi-pulih-staf-123'),('timbangan_lama',legacy,'sandi-pulih-lama-123')]:
        result,_=await action(pg,x,'tautan_sandi',kind,aid)
        async with pg() as db:await help.pulihkan_sandi(db,cap=result['cap'],sandi=pw,ulangi=pw);await db.commit()
    await helper('after')
    async with pg() as db:
        rows=(await db.execute(text('SELECT perangkat_kode,token_version FROM timbangan_akun ORDER BY id'))).all()
        assert rows==[('UT',2),('LG',2)]


async def test_aktivasi_pengguna_lama_memutus_semua_sesi_tanpa_mengubah_izin(pg,orang):
    from hmu_core import User
    from hmu_identitas.model import Akun
    from sqlalchemy import select
    x=orang
    async with pg() as db:
        linked=await db.scalar(text("INSERT INTO timbangan_akun(username,nama,role,akun_id,status,perangkat_kode,token_version) VALUES ('aktifkan-linked','Akun bersama','PETUGAS',:aid,'aktif','AL',1) RETURNING id"),{'aid':x['aid']})
        legacy=await db.scalar(text("INSERT INTO timbangan_akun(user_id,username,nama,role,password_hash,status,perangkat_kode,token_version) VALUES (:uid,'aktifkan-legacy','Akun lama','PETUGAS',:h,'aktif','AG',1) RETURNING id"),{'uid':x['uid'],'h':hash_sandi('sandi-lama-uji-123')})
        (await db.get(User,x['uid'])).status='nonaktif';await db.commit()
    await action(pg,x,'aktifkan_akun','timbangan_lama',legacy)
    async with pg() as db:
        a=await db.get(Akun,x['aid']);assert a.aktif and a.token_version==2 and a.user.role=='operator'
        rows=(await db.execute(text('SELECT id,token_version FROM timbangan_akun ORDER BY id'))).all()
        assert rows==[(linked,2),(legacy,2)]
        assert not (await db.get(KeanggotaanPerusahaan,x['mid'])).aktif


async def test_peta_dan_gangguan_membaca_profil_dan_tanda_terima_nyata_tanpa_mutasi(pg,orang):
    from app.services import console_operasi as ops
    from tests.pg.test_pengaturan_organisasi import fakta
    import uuid
    x=orang
    async with pg() as db:
        (await db.get(KeanggotaanPerusahaan,x['mid'])).aktif=True
        linked=await db.scalar(text("INSERT INTO timbangan_akun(username,nama,role,akun_id,status,perangkat_kode,token_version) VALUES ('operator-aktif','Operator uji','PETUGAS',:aid,'nonaktif','UT',1) RETURNING id"),{'aid':x['aid']})
        legacy=await db.scalar(text("INSERT INTO timbangan_akun(username,nama,role,password_hash,status,perangkat_kode,token_version) VALUES ('peta-legacy','Profil peta lama','PETUGAS',:h,'aktif','LP',1) RETURNING id"),{'h':hash_sandi('sandi-lama-uji-123')})
        for raw in (json.dumps(dict(peringatan=True,pesan='RAHASIA TIDAK BOLEH TAMPIL')),json.dumps(dict(berhasil=True)),'rusak'):
            await db.execute(text("INSERT INTO timbangan_kiriman(kunci,akun_id,jalur,sidik,jawaban,created_at) VALUES (:key,:aid,'masuk',:sidik,:raw,now())"),dict(key=str(uuid.uuid4()),aid=linked,sidik='a'*64,raw=raw))
        await db.commit()
    before=await fakta(pg)
    async with pg() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        d=await ops.peta_akses(db,user_id=x['uid'],produk='teraflow');p=d['perusahaan'][0]['produk'][0]
        assert p['operasional']=='ditolak' and p['sebab_kode']=='profil'
        legacy_map=await ops.peta_akun_lokal(db,jenis='timbangan_lama',akun_id=legacy)
        assert legacy_map['user_id'] is None and legacy_map['akun_id']==legacy
        assert legacy_map['perusahaan'][0]['produk'][0]['operasional']=='diizinkan'
        d=await ops.gangguan(db);i=d['integrasi']
        assert i['peringatan']==1 and i['tanda_terima']==3 and i['tidak_terbaca']==1
        assert 'RAHASIA' not in json.dumps(d)
        await db.commit()
    assert await fakta(pg)==before


async def test_diagnosis_dan_peta_sepakat_menolak_profil_timbang_tertaut_nonaktif(pg,orang):
    from app.services import console_operasi as ops
    x=orang
    async with pg() as db:
        (await db.get(KeanggotaanPerusahaan,x['mid'])).aktif=True
        await db.execute(text("INSERT INTO timbangan_akun(username,nama,role,akun_id,status,perangkat_kode,token_version) VALUES ('operator-aktif','Profil dinonaktifkan','PETUGAS',:aid,'nonaktif','PA',1)"),{'aid':x['aid']});await db.commit()
        d=await help.diagnosis(db,cid=x['cid'],jenis='staf',aid=x['aid'])
        p=await ops.peta_akses(db,user_id=x['uid'],company_id=x['cid'],produk='teraflow')
        assert not next(a for a in d['aplikasi'] if a['aplikasi']=='teraflow')['boleh']
        assert p['perusahaan'][0]['produk'][0]['operasional']=='ditolak'
        assert next(a for a in d['aplikasi'] if a['aplikasi']=='padiflow')['boleh']

async def test_peta_tidak_menolak_adopsi_profil_lama_yang_login_bersama_sinkronkan(pg,orang):
    from app.services import console_operasi as ops
    from tests.pg.test_pengaturan_organisasi import fakta
    x=orang
    async with pg() as db:
        (await db.get(KeanggotaanPerusahaan,x['mid'])).aktif=True
        await db.execute(text("INSERT INTO timbangan_akun(username,nama,role,password_hash,status,perangkat_kode,token_version) VALUES ('operator-aktif','Profil belum tertaut','PETUGAS',:h,'nonaktif','BA',1)"),{'h':hash_sandi('sandi-lama-uji-123')});await db.commit()
    before=await fakta(pg)
    async with pg() as db:
        d=await ops.peta_akses(db,user_id=x['uid'],company_id=x['cid'],produk='teraflow')
        assert d['perusahaan'][0]['produk'][0]['operasional']=='diizinkan'
    assert await fakta(pg)==before
    root=Path(os.environ['UJI_TF_ROOT'])
    code="""import asyncio
import os
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from app.timbangan.service import masuk_bersama
from app import database
async def run():
 url=os.environ['UJI_PG_URL'];u=make_url(url)
 assert u.host in ('127.0.0.1','localhost') and u.database.startswith('uji_')
 engine=create_async_engine(url);database.SessionLocal=async_sessionmaker(engine,expire_on_commit=False)
 async with database.SessionLocal() as db:
  common,profile=await masuk_bersama(db,'operator-aktif','sandi-uji-12345')
  assert profile.akun_id==common.id and profile.status=='aktif'
 await engine.dispose()
asyncio.run(run())
"""
    result=await asyncio.to_thread(subprocess.run,[os.environ['UJI_TF_PYTHON'],'-c',code],cwd=root,env={**os.environ,'PYTHONPATH':str(root)},capture_output=True,text=True,timeout=45)
    assert result.returncode==0,result.stdout+result.stderr
    after=await fakta(pg)
    assert {k:v for k,v in before.items() if k!='timbangan_akun'}=={k:v for k,v in after.items() if k!='timbangan_akun'}
