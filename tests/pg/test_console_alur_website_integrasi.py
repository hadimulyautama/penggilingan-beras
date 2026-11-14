"""Semua alur utama Console melalui dua server HTTP; hanya data PostgreSQL uji."""
import asyncio,json,os,subprocess
from pathlib import Path
import pytest
from pydantic import SecretStr
from sqlalchemy import select
from hmu_core import User,KeanggotaanPerusahaan,Perusahaan
from hmu_identitas import peran as P
from hmu_identitas.model import Akun
from hmu_identitas.sandi import cek_sandi
from app.config import settings
from app.models import SesiConsole
from tests.pg.test_console_monitoring import orang
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_console_website_integrasi import api_http
from tests.pg.test_pengaturan_organisasi import fakta
pytestmark=[pytest.mark.asyncio,pytest.mark.dua_aplikasi,pytest.mark.fondasi_multi]

async def test_monitoring_perusahaan_dan_pemulihan_dari_browser_http(pg,orang,monkeypatch):
    root=Path(os.environ['UJI_WEBSITE_ROOT']);python=os.environ['UJI_WEBSITE_PYTHON'];x=orang
    key='hanya-kunci-integrasi-console-data-uji-1234567890123456'
    monkeypatch.setattr(settings,'console_website_url','https://console.uji')
    monkeypatch.setattr(settings,'console_login_secret',SecretStr(key))
    before=await fakta(pg)
    async with pg() as db:
        akun=await db.scalar(select(Akun).where(Akun.user_id==x['root']));root_hash=akun.password_hash
    async with api_http() as api:
        env={**os.environ,'PYTHONPATH':str(root),'UJI_CONSOLE_API':api,'CONSOLE_LOGIN_SECRET':key,'UJI_CONSOLE_DATA':json.dumps(x)}
        r=await asyncio.to_thread(subprocess.run,[python,'tests/integrasi_console_alur.py'],cwd=root,env=env,capture_output=True,text=True,timeout=90)
        assert r.returncode==0,r.stderr+'\n'+r.stdout
        assert all(json.loads(r.stdout).values())
    after=await fakta(pg)
    allowed={'hmu_console_sessions','hmu_support_plans','hmu_account_recoveries','hmu_login_unlocks','produksi_akun','activity_logs',
        'hmu_companies','hmu_factory_sites','hmu_company_memberships','hmu_membership_sites','hmu_membership_warehouses'}
    assert {k:v for k,v in before.items() if k not in allowed}=={k:v for k,v in after.items() if k not in allowed}
    async with pg() as db:
        operator=await db.get(Akun,x['aid']);assert operator.token_version==2 and cek_sandi('baru-aman-console-123',operator.password_hash)
        assert (await db.get(User,x['uid'])).role==P.OPERATOR
        assert (await db.get(KeanggotaanPerusahaan,x['mid'])).aktif
        company=await db.scalar(select(Perusahaan).where(Perusahaan.kode=='uji-alur-console'))
        member=await db.scalar(select(KeanggotaanPerusahaan).where(KeanggotaanPerusahaan.company_id==company.id,KeanggotaanPerusahaan.user_id==x['uid']))
        assert member.aktif and member.peran==P.ADMIN
        assert (await db.scalar(select(Akun).where(Akun.user_id==x['root']))).password_hash==root_hash
        assert all(s.dicabut for s in await db.scalars(select(SesiConsole)))
