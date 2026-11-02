"""Tidak ada tugas ganda atau cache lama ketika web memakai beberapa proses."""
import asyncio
import os
import subprocess
import sys
from types import SimpleNamespace
import httpx
import pytest

pytestmark=pytest.mark.asyncio

async def test_web_tidak_menjalankan_seed_dan_scheduler(monkeypatch):
    from app.main import lifespan,app
    from app.config import settings
    from app.services import proses_latar
    from contextlib import asynccontextmanager
    calls=[]
    @asynccontextmanager
    async def hidup(app):
        calls.append(1)
        yield
    monkeypatch.setattr(proses_latar,'hidup',hidup)
    monkeypatch.setattr(settings,'peran_proses','web')
    async with lifespan(app):pass
    assert calls==[]
    monkeypatch.setattr(settings,'peran_proses','gabungan')
    async with lifespan(app):pass
    assert calls==[1]

async def test_rpc_privat_dua_pemicu_hanya_satu_sinkron(monkeypatch):
    from app.pekerja import app
    from app.services import kledo_sinkron as k
    calls=[];lanjut=asyncio.Event()
    async def fake():
        calls.append(1)
        try:await lanjut.wait()
        finally:k._sedang_berjalan=False
    monkeypatch.setattr(k,'_jalankan',fake)
    monkeypatch.setattr(k,'_sedang_berjalan',False)
    monkeypatch.setenv('HMU_PEKERJA_TOKEN','token-lokal-uji')
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as client:
        assert (await client.get('/kledo/status')).status_code==403
        responses=await asyncio.gather(*(client.post('/kledo/mulai',headers={'X-Pekerja-Token':'token-lokal-uji'}) for _ in range(2)))
        assert sorted(r.json()['dimulai'] for r in responses)==[False,True]
        await asyncio.sleep(0)
        assert calls==[1]
        assert (await client.get('/kledo/status',headers={'X-Pekerja-Token':'token-lokal-uji'})).json()['sedang_berjalan']
        lanjut.set()
        await asyncio.sleep(0)

async def test_commit_proses_lain_menghapus_snapshot(tmp_path,monkeypatch):
    from app import performa as p
    from fastapi import FastAPI
    engine=object()
    db=SimpleNamespace(new=[],dirty=[],deleted=[],get_bind=lambda:engine,connection=lambda:asyncio.sleep(0))
    monkeypatch.setenv('HMU_CACHE_EPOCH',str(tmp_path/'epoch'))
    calls=[]
    @p.tampilan_singkat
    async def nilai(db):
        calls.append(1)
        return len(calls)
    app=FastAPI();app.add_middleware(p.PerformaMiddleware)
    @app.get('/')
    async def baca():return await nilai(db)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as client:
        assert (await client.get('/')).json()==1
        assert (await client.get('/')).json()==1
        process=await asyncio.create_subprocess_exec(sys.executable,'-c',
            'import app.performa; from sqlalchemy.orm import Session; s=Session(); s.commit(); s.close()',
            env={**os.environ},stdout=subprocess.DEVNULL,stderr=subprocess.PIPE)
        _,error=await process.communicate()
        assert process.returncode==0,error.decode()
        assert (await client.get('/')).json()==2


async def test_supervisor_menghentikan_pasangan_bila_satu_proses_gagal(monkeypatch):
    from app import server
    children=[];envs=[]
    class Child:
        def __init__(self,failed=False):self.failed=failed;self.stopped=False
        def poll(self):return 1 if self.failed else 0 if self.stopped else None
        def terminate(self):self.stopped=True
        def wait(self,timeout=None):return 0
    def popen(args,env):
        child=Child(failed=len(children)==1);children.append(child);envs.append(env)
        return child
    class Response:
        status=200
        def __enter__(self):return self
        def __exit__(self,*_):pass
    monkeypatch.setattr(server.subprocess,'Popen',popen)
    monkeypatch.setattr(server.signal,'signal',lambda *_:None)
    monkeypatch.setattr(server.urllib.request,'build_opener',lambda *_:SimpleNamespace(open=lambda *a,**kw:Response()))
    with pytest.raises(RuntimeError,match='restart seluruh kontainer'):server.jalankan()
    assert children[0].stopped
    assert [env['PERAN_PROSES'] for env in envs]==['pekerja','web']
    assert envs[0]['HMU_PEKERJA_TOKEN']==envs[1]['HMU_PEKERJA_TOKEN']
    assert not os.path.exists(os.path.dirname(envs[0]['HMU_CACHE_EPOCH']))


async def test_template_portal_dipakai_ulang_tanpa_membagi_data_atau_csrf():
    from jinja2 import Environment,DictLoader
    from app.web.portal.presentation import _env_pelanggan
    loader=DictLoader({'uji.html':"{% extends 'base.html' %}{% block isi %}{{ nama }} {{ CSRF }}{% endblock %}"})
    base=Environment(loader=loader)
    a=_env_pelanggan(base,loader).get_template('uji.html').render(nama='Pelanggan A',CSRF='tokenA')
    b=_env_pelanggan(base,loader).get_template('uji.html').render(nama='Pelanggan B',CSRF='tokenB')
    assert 'Pelanggan A tokenA' in a and 'tokenA' not in b and 'Pelanggan A' not in b
    assert 'Pelanggan B tokenB' in b
    loader.mapping['uji.html']="{% extends 'base.html' %}{% block isi %}Baru {{ nama }}{% endblock %}"
    assert 'Baru Pelanggan B' in _env_pelanggan(base,loader).get_template('uji.html').render(nama='Pelanggan B')
