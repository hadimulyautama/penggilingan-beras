"""Dua proses aplikasi nyata: HTTP internal bertoken, dua perjalanan, satu stok."""
import asyncio,json,os,socket,subprocess,tempfile
from pathlib import Path
import pytest,httpx
from sqlalchemy import select,func
from app.models import User,PermintaanPk,InternalTransfer
from hmu_identitas.model import Akun
from tests.pg.test_permintaan_empat_langkah import pabrik
from tests.pg.test_pengiriman_pk_bertahap import siap,buat
from tests.pg.test_teraflow_kiriman import _skema_head
pytestmark=[pytest.mark.asyncio,pytest.mark.dua_aplikasi]

@pytest.mark.fondasi_multi
async def test_http_dua_aplikasi_dan_stok_tidak_ganda(pg,siap):
 tera=os.environ.get('UJI_TF_ROOT');python=os.environ.get('UJI_TF_PYTHON')
 if not tera or not python:pytest.skip('Uji dua aplikasi memerlukan source dan interpreter TeraFlow lokal.')
 w=siap;j1=await buat(pg,w,'2000');j2=await buat(pg,w,'4000')
 async with pg() as db:
  a=Akun(user_id=w['op1'],username='uji-transfer-sumber',password_hash='x',status='aktif');db.add(a);await db.commit();aid=a.id
 with socket.socket() as sock:sock.bind(('127.0.0.1',0));port=sock.getsockname()[1]
 root=Path(__file__).resolve().parents[2];url=os.environ['UJI_PG_URL'];token='uji-internal-transfer-token-local-only'
 tmp=Path(tempfile.mkdtemp(prefix='uji-transfer-http-'))
 (tmp/'uji_transfer_server.py').write_text('from fastapi import FastAPI\nfrom app.web.pengiriman_pk import router\napp=FastAPI();app.include_router(router)\n')
 env={**os.environ,'DATABASE_URL':url,'INTERNAL_API_TOKEN':token,'PYTHONPATH':str(tmp)+os.pathsep+str(root)}
 log=(tmp/'server.log').open('w')
 server=subprocess.Popen([os.sys.executable,'-m','uvicorn','uji_transfer_server:app','--host','127.0.0.1','--port',str(port)],cwd=root,env=env,stdout=log,stderr=subprocess.STDOUT)
 try:
  ready=False
  async with httpx.AsyncClient() as client:
   for _ in range(100):
    if server.poll() is not None:break
    try:
     r=await client.get(f'http://127.0.0.1:{port}/internal/pk/pengiriman/{j1["id"]}',headers={'X-Internal-Token':token,'X-Operator-Akun':str(aid)})
     if r.status_code==200:ready=True;break
    except httpx.HTTPError:pass
    await asyncio.sleep(.1)
  assert ready,(tmp/'server.log').read_text()
  payload=dict(akun_id=aid,journeys=[[j1['id'],2000],[j2['id'],4000]])
  result=await asyncio.to_thread(subprocess.run,[python,'tests/integrasi_pk_operator.py',json.dumps(payload)],cwd=tera,env={**env,'PYTHONPATH':tera,'PRODUKSI_API_URL':f'http://127.0.0.1:{port}','PRODUKSI_API_TOKEN':token},capture_output=True,text=True,timeout=45)
  assert result.returncode==0,result.stderr+'\n'+(tmp/'server.log').read_text()
  async with pg() as db:
   r=await db.get(PermintaanPk,w['rid']);assert r.status=='selesai' and r.berat_final_kg==6000
   assert await db.scalar(select(func.sum(InternalTransfer.berat_kg)))==6000
   assert await db.scalar(select(func.count()).select_from(InternalTransfer))==2
 finally:
  server.terminate();await asyncio.to_thread(server.wait,timeout=10);log.close()
