"""Server uji API asli dengan gangguan jaringan sintetis; tidak ikut image."""
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from app.web.internal import router
app=FastAPI();app.include_router(router)
flags={'baca':False,'verifikasi':False}
@app.post('/uji/gangguan')
async def gangguan(request:Request):
    flags.update({k:bool(v) for k,v in (await request.json()).items() if k in flags})
    return flags
@app.middleware('http')
async def jaringan(request,call_next):
    if ((request.url.path.endswith('/muatan') and flags['baca']) or
        (request.url.path.endswith('/verifikasi') and flags['verifikasi'])):
        return JSONResponse({'detail':'Jaringan uji terputus'},status_code=503)
    return await call_next(request)
