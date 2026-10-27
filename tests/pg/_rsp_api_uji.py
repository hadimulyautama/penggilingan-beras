"""HTTP internal dan gangguan baca sintetis, hanya dipakai tes dua aplikasi."""
from fastapi import FastAPI,Request
from fastapi.responses import JSONResponse
from app.web.internal import router
app=FastAPI();app.include_router(router)
flags={'baca':False}
@app.post('/uji/gangguan')
async def gangguan(request:Request):
    flags['baca']=bool((await request.json()).get('baca'));return flags
@app.middleware('http')
async def jaringan(request,call_next):
    if request.url.path.startswith('/internal/retur-supplier/') and flags['baca']:
        return JSONResponse({'detail':'Gangguan baca sintetis'},status_code=503)
    return await call_next(request)
