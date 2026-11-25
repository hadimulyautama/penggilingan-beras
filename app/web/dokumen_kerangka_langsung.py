"""Report structure choices and native date defaults, never report contents."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path

@lru_cache(maxsize=1)
def aset():
    folder=Path(__file__).parent/'static'
    meta=json.loads((folder/'kerangka-dokumen-ui.meta.json').read_text())
    if meta.get('versi')!=1 or hashlib.sha256((folder/'kerangka-dokumen-ui.js').read_bytes()).hexdigest()!=meta.get('aset_sha256'):
        raise ValueError('Native document structure package mismatch')
    return meta

async def susun(request,akun,*,registry):
    if getattr(request.state,'portal_scope',None) is not None or getattr(akun,'harus_ganti_sandi',None) is not False:return None
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request):return None
    from app.web.laporan import _daftar,boleh_lihat,PERIODE,_rentang
    meta=aset();supported=set(meta['variants'])
    choices=[l.kode.removeprefix('tahap_') for l in _daftar() if boleh_lihat(akun.user,l)]
    targets=[code for code in choices if '/laporan/'+code in supported]
    if not targets:return None
    ranges={}
    for key,_ in PERIODE:
        if key=='khusus':continue
        start,end=_rentang(key);ranges[key]=dict(dari=start.isoformat(),sampai=end.isoformat())
    return dict(versi=1,sumber=meta['sumber'],cap=registry['cap'],konteks=registry['konteks'],sesi=registry['sesi'],laporan=dict(targets=targets,choices=choices,rentang=ranges),kabar=True)
