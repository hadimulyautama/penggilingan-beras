"""Pemulihan Console memutus sesi bersama dan lama di TeraFlow nyata."""
import asyncio,json,os,subprocess
from pathlib import Path
import pytest
from sqlalchemy import text
from hmu_identitas.sandi import hash_sandi
from tests.pg.test_console_monitoring import orang,action
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_teraflow_kiriman import _skema_head
from app.services import console_bantuan as help
pytestmark=[pytest.mark.asyncio,pytest.mark.dua_aplikasi,pytest.mark.fondasi_multi]
async def test_pemulihan_sandi_dan_csrf_dua_interpreter(pg,orang):
    x=orang
    async with pg() as db:
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
