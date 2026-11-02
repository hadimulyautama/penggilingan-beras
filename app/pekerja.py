"""RPC privat loopback untuk satu pekerja latar dalam kontainer aplikasi."""
import hmac
import os
from dataclasses import asdict
from fastapi import FastAPI,Header,HTTPException,Depends
from app.services.proses_latar import hidup

async def sah(x_pekerja_token:str|None=Header(default=None)):
    token=os.environ.get('HMU_PEKERJA_TOKEN','')
    if not token or not hmac.compare_digest(x_pekerja_token or '',token):
        raise HTTPException(403,'Pekerja privat.')

app=FastAPI(lifespan=hidup,docs_url=None,redoc_url=None,openapi_url=None,dependencies=[Depends(sah)])

@app.get('/health')
async def health():return {'status':'ok'}

@app.get('/kledo/status')
async def kledo_status():
    from app.services.kledo_sinkron import status
    return asdict(status())

@app.post('/kledo/mulai')
async def kledo_mulai():
    from app.services.kledo_sinkron import mulai
    return {'dimulai':mulai()}
