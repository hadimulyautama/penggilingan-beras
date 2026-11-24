"""Two declared master read layouts; native guard and writers remain owners.

An address/blueprint is presentation, never permission. No master value,
record identity, default, usage flag or account is fabricated for this shape.
"""
from functools import lru_cache
import hashlib
import json
from pathlib import Path

PATHS=('/pengaturan/spesifikasi-beras','/pengaturan/hasil-samping')


def spesifikasi(path,query=''):
    if query or path not in PATHS:return None
    beras=path==PATHS[0]
    return dict(alamat=path,kembali='/pengaturan',jenis='beras' if beras else 'samping',
        title='Jenis / Spesifikasi Beras' if beras else 'Jenis Hasil Samping',
        description=('Atur pilihan jenis beras dan nilai acuannya. Nilai acuan tidak mengubah hasil pengukuran QC.'
                     if beras else 'Atur jenis hasil samping dan pengemasan otomatisnya. Karung penuh serta sisa curah dihitung otomatis.'),
        add_summary='+ Tambah spesifikasi beras' if beras else '+ Tambah jenis hasil samping',
        add_button='Tambah spesifikasi' if beras else 'Tambah jenis hasil samping',
        list_title='Daftar spesifikasi' if beras else 'Daftar jenis hasil samping')


def permintaan_kerangka(request):
    """X-Pindah:1 always reads native data, including inherited shell headers."""
    return (request.method=='GET' and spesifikasi(request.url.path,request.url.query) is not None
        and request.headers.get('X-Pindah')!='1'
        and (request.headers.get('X-Kerangka-Halaman')=='1'
             or request.headers.get('Sec-Fetch-Mode')=='navigate'
             and request.headers.get('Sec-Fetch-Dest') in {'document','empty'}))


def akun_native(request,akun):
    """Only assertions after actual Depends(butuh_admin), not a new role map."""
    return (akun is not None and getattr(request.state,'akun',None) is akun
        and getattr(request.state,'portal_scope',None) is None
        and getattr(akun,'harus_ganti_sandi',None) is False
        and getattr(akun,'is_admin',None) is True)


async def kerangka(request,akun,konteks):
    if not permintaan_kerangka(request) or not akun_native(request,akun):return None
    spec=spesifikasi(request.url.path,request.url.query)
    shell=konteks.get('SHELL',{})
    if (shell.get('data_url')!=spec['alamat'] or not isinstance(shell.get('stamp'),str)
            or not shell['stamp']):return None
    from app.web.tampilan import render
    response=render(request,'pengaturan_master_kerangka.html',
        **{**konteks,'layar':'pengaturan','kembali':'/pengaturan',
           'PG_MASTER_SHELL':{**spec,'stamp':shell['stamp']}})
    response.headers['Cache-Control']='private, no-store';response.headers['Vary']='Cookie'
    return response


@lru_cache(maxsize=1)
def aset():
    folder=Path(__file__).parent/'static'
    meta=json.loads((folder/'kerangka-pengaturan-master-ui.meta.json').read_text())
    if (meta.get('versi')!=1 or meta.get('variants')!=list(PATHS)
            or hashlib.sha256((folder/'kerangka-pengaturan-master-ui.js').read_bytes()).hexdigest()!=meta.get('aset_sha256')):
        raise ValueError('Master Settings public package mismatch')
    return meta


async def susun(request,akun,*,registry):
    """Optional Root metadata: actual current account only; no DB/master read."""
    if request.method!='GET' or not akun_native(request,akun):return None
    if not isinstance(registry,dict) or not all(isinstance(registry.get(k),str) and registry[k] for k in ('cap','konteks','sesi')):return None
    return dict(versi=1,cap=registry['cap'],konteks=registry['konteks'],sesi=registry['sesi'],
                sumber=aset()['sumber'],allowed=True)
