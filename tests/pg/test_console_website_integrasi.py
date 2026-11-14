"""Website terpisah memakai HTTP nyata; tidak boleh mengubah transaksi lama."""
import asyncio,json,os,subprocess
from pathlib import Path
from contextlib import asynccontextmanager
import pytest
from pydantic import SecretStr
from hmu_identitas.model import Akun
import uvicorn
from sqlalchemy import select,func
from app.main import app
from app.config import settings
from app.models import ActivityLog,SesiConsole
from hmu_identitas import peran as P
from hmu_identitas.organisasi import konteks_kerja,OrganisasiTidakDiizinkan
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_master_organisasi import organisasi,pilihan
from tests.pg.test_pengaturan_organisasi import fakta
from app.web.security import NAMA_COOKIE

pytestmark=[pytest.mark.asyncio,pytest.mark.dua_aplikasi,pytest.mark.fondasi_multi]


@asynccontextmanager
async def api_http():
    server=uvicorn.Server(uvicorn.Config(app,host='127.0.0.1',port=0,lifespan='off',log_level='error'))
    task=asyncio.create_task(server.serve())
    try:
        for _ in range(500):
            if task.done():task.result()
            if server.started:break
            await asyncio.sleep(.01)
        assert server.started
        yield 'http://127.0.0.1:'+str(server.servers[0].sockets[0].getsockname()[1])
    finally:
        server.should_exit=True;await asyncio.wait_for(task,timeout=10)


async def test_console_website_http_sampai_audit_dan_akses_tanpa_mengubah_transaksi(pg,running,organisasi,monkeypatch):
    root=Path(os.environ['UJI_WEBSITE_ROOT']);python=os.environ['UJI_WEBSITE_PYTHON']
    monkeypatch.setattr(settings,'console_website_url','https://website.uji')
    key='console-login-integrasi-hanya-data-uji-123456789012345'
    monkeypatch.setattr(settings,'console_login_secret',SecretStr(key))
    x=organisasi
    async with await _klien(pg,peran=P.SUPERADMIN) as c:
        before=await fakta(pg)
        cols=[c for c in Akun.__table__.columns if c.name not in ('terakhir_login','updated_at')]
        async with pg() as db:
            akun=await db.scalar(select(Akun).order_by(Akun.id.desc()))
            username=akun.username
            accounts=(await db.execute(select(*cols).order_by(Akun.id))).all()
        async with api_http() as api:
            env={**os.environ,'PYTHONPATH':str(root),'UJI_CONSOLE_API':api,'CONSOLE_LOGIN_SECRET':key,'UJI_PF_COOKIE':NAMA_COOKIE,'UJI_PF_TOKEN':c.cookies.get(NAMA_COOKIE),
                'UJI_CONSOLE_DATA':json.dumps(dict(username=username,company_id=x['c'][0],site_id=x['s'][0],warehouse_id=x['w'][0],user_id=x['luar']))}
            r=await asyncio.to_thread(subprocess.run,[python,'tests/integrasi_console.py'],cwd=root,env=env,capture_output=True,text=True,timeout=90)
            assert r.returncode==0,r.stderr+'\n'+r.stdout
            assert all(json.loads(r.stdout).values())
        after=await fakta(pg);allowed={'hmu_console_sessions','hmu_company_memberships','hmu_membership_sites','hmu_membership_warehouses','activity_logs','produksi_akun'}
        assert {k:v for k,v in after.items() if k not in allowed}=={k:v for k,v in before.items() if k not in allowed}
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='keanggotaan_perusahaan'))==1
            assert all(row.dicabut for row in await db.scalars(select(SesiConsole)))
            assert (await db.execute(select(*cols).order_by(Akun.id))).all()==accounts
            ctx=await konteks_kerja(db,**dict(pilihan(x),user_id=x['luar']));assert ctx.peran==P.OPERATOR
            with pytest.raises(OrganisasiTidakDiizinkan):await konteks_kerja(db,**dict(pilihan(x,gudang=1),user_id=x['luar']))
