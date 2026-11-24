"""Pilihan struktur UI per dokumen; asetnya tidak berisi sesi atau data."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path


@lru_cache(maxsize=1)
def aset():
    # Cache hanya metadata berkas program yang tetap untuk proses rilis ini.
    folder=Path(__file__).parent/'static'
    data=json.loads((folder/'kerangka-ui.meta.json').read_text())
    if (data.get('versi')!=1 or data.get('variants')!=['pengiriman-admin','pengiriman-operator','jasa-admin']
            or hashlib.sha256((folder/'kerangka-ui.js').read_bytes()).hexdigest()!=data.get('aset_sha256')):
        raise ValueError('Paket kerangka UI tidak cocok')
    return data


async def susun(request,akun,registry):
    from app.web.pengiriman_bertahap import boleh_baca
    from app.peran import can_see_financials
    varians={}
    if await boleh_baca(akun.user):
        varians['pengiriman']='pengiriman-admin' if can_see_financials(akun.user) else 'pengiriman-operator'
    if can_see_financials(akun.user):
        varians['jasa']='jasa-admin'
    if not varians:
        return None
    data=aset()
    return dict(versi=1,sumber=data['sumber'],
        konteks=registry['konteks'],cap=registry['cap'],sesi=registry['sesi'],
        varians=varians)
