"""Data-free parent facility shapes; an internal native guard result is required.

The descriptor passed by the registry owner is NOT accepted from HTTP/DOM.
A URL or a presentation descriptor is never authorization. Every fresh target
GET retains its original Depends(butuh_super), reader, forms and controllers.
"""
from functools import lru_cache
import hashlib
import json
from pathlib import Path

TARGETS=('/pengaturan/gudang','/pengaturan/silo','/pengaturan/mesin','/pengaturan/jenis-proses')
TITLES=('Pengaturan gudang','Silo','Mesin & line produksi','Jenis proses')
HOST='padi-fasilitas-parent-kerangka'


def blueprint(address):
    if address not in TARGETS:return None
    return dict(alamat=address,title=TITLES[TARGETS.index(address)],variant=address.rsplit('/',1)[-1],stamp='__PADI_STAMP__')


@lru_cache(maxsize=1)
def aset():
    folder=Path(__file__).parent/'static'
    meta=json.loads((folder/'kerangka-fasilitas-parent-ui.meta.json').read_text())
    if (meta.get('versi')!=1 or meta.get('variants')!=list(TARGETS)
            or hashlib.sha256((folder/'kerangka-fasilitas-parent-ui.js').read_bytes()).hexdigest()!=meta.get('aset_sha256')):
        raise ValueError('Facility parent public package mismatch')
    return meta


def susun(request,akun,*,registry,guarded_alat):
    """Reuse the SAME request's completed native Alat guard, never re-query it.

    Root must pass the actual local return from pengaturan_alat_kerangka.susun,
    not reconstruct this argument from client flags. Unknown input declines.
    This only compiles private presentation targets, not an access decision.
    """
    if (request.method!='GET' or akun is None or getattr(request.state,'akun',None) is not akun
            or getattr(request.state,'portal_scope',None) is not None
            or getattr(akun,'harus_ganti_sandi',None) is not False):return None
    if not isinstance(registry,dict) or not all(isinstance(registry.get(k),str) and 0<len(registry[k])<=2048 for k in ('cap','konteks','sesi')):return None
    if not isinstance(guarded_alat,dict) or set(guarded_alat)!={'versi','cap','konteks','sesi','sumber','targets'}:return None
    from app.web.pengaturan_alat_kerangka import ALAMAT,aset as aset_alat
    if (type(guarded_alat['versi']) is not int or guarded_alat['versi']!=1
            or guarded_alat['targets']!=[ALAMAT]
            or any(guarded_alat[k]!=registry[k] for k in ('cap','konteks','sesi'))
            or guarded_alat['sumber']!=aset_alat()['sumber']):return None
    return dict(versi=1,cap=registry['cap'],konteks=registry['konteks'],sesi=registry['sesi'],sumber=aset()['sumber'],targets=list(TARGETS))
