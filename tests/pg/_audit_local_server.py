import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from urllib.parse import urlsplit
assert urlsplit(os.environ['DATABASE_URL']).hostname in ('127.0.0.1','localhost')
assert urlsplit(os.environ['DATABASE_URL']).path.rsplit('/',1)[-1].startswith('uji_')
import httpx
_async=httpx.AsyncHTTPTransport.handle_async_request
_sync=httpx.HTTPTransport.handle_request
async def guarded_async(self,request):
 if request.url.host not in ('127.0.0.1','localhost','uji'):
  raise RuntimeError('AUDIT_LOKAL: jaringan eksternal diblokir')
 return await _async(self,request)
def guarded_sync(self,request):
 if request.url.host not in ('127.0.0.1','localhost','uji'):
  raise RuntimeError('AUDIT_LOKAL: jaringan eksternal diblokir')
 return _sync(self,request)
httpx.AsyncHTTPTransport.handle_async_request=guarded_async
httpx.HTTPTransport.handle_request=guarded_sync
import uvicorn
from app.main import app
uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('HMU_AUDIT_UI_PORT','8882')),lifespan='off',log_level='warning')
