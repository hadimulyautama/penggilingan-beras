"""The native /pengaturan/alat link hub, separate from Admin master pages."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path

ALAMAT='/pengaturan/alat'


def permintaan_kerangka(request):
    return (request.method=='GET' and request.url.path==ALAMAT and not request.url.query
        and request.headers.get('X-Pindah')!='1'
        and (request.headers.get('X-Kerangka-Halaman')=='1'
             or request.headers.get('Sec-Fetch-Mode')=='navigate'
             and request.headers.get('Sec-Fetch-Dest') in {'document','empty'}))


async def guard_native(request,akun):
    """Reuse exact butuh_super, including its narrow existing recovery rule.

    Never derive this from master-page Admin metadata, a URL or a new role
    list. The caller's native dependency is still mandatory and unchanged.
    """
    if (request.method!='GET' or akun is None or getattr(request.state,'akun',None) is not akun
            or getattr(request.state,'portal_scope',None) is not None
            or getattr(akun,'harus_ganti_sandi',None) is not False):return False
    from app.web.security import butuh_super,AksesDitolak
    try:return await butuh_super(akun) is akun
    except AksesDitolak:return False


async def kerangka(request,akun,konteks):
    if not permintaan_kerangka(request) or not await guard_native(request,akun):return None
    shell=konteks.get('SHELL',{})
    if shell.get('data_url')!=ALAMAT or not isinstance(shell.get('stamp'),str) or not shell['stamp']:return None
    from app.web.tampilan import render
    response=render(request,'pengaturan_alat_kerangka.html',
        **{**konteks,'layar':'pengaturan','kembali':'/pengaturan','ALAT_SHELL':{'alamat':ALAMAT,'stamp':shell['stamp']}})
    response.headers['Cache-Control']='private, no-store';response.headers['Vary']='Cookie'
    return response


@lru_cache(maxsize=1)
def aset():
    folder=Path(__file__).parent/'static'
    meta=json.loads((folder/'kerangka-pengaturan-alat-ui.meta.json').read_text())
    if (meta.get('versi')!=1 or meta.get('variants')!=[ALAMAT]
            or hashlib.sha256((folder/'kerangka-pengaturan-alat-ui.js').read_bytes()).hexdigest()!=meta.get('aset_sha256')):
        raise ValueError('Alat hub public package mismatch')
    return meta


async def susun(request,akun,*,registry):
    if not isinstance(registry,dict) or not all(isinstance(registry.get(k),str) and registry[k] for k in ('cap','konteks','sesi')):return None
    if not await guard_native(request,akun):return None
    return dict(versi=1,cap=registry['cap'],konteks=registry['konteks'],sesi=registry['sesi'],sumber=aset()['sumber'],targets=[ALAMAT])
