"""Two settings structures; native caller owns presentation flags and access."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path
from urllib.parse import urlsplit

PATHS=('/pengaturan','/pengaturan/sesi')

@lru_cache(maxsize=1)
def aset():
    folder=Path(__file__).parent/'static'
    data=json.loads((folder/'kerangka-pengaturan-ui.meta.json').read_text())
    if (data.get('versi')!=1 or data.get('variants')!=list(PATHS)
            or hashlib.sha256((folder/'kerangka-pengaturan-ui.js').read_bytes()).hexdigest()!=data.get('aset_sha256')):
        raise ValueError('Settings public package mismatch')
    return data

def valid_console(value):
    if not isinstance(value,str) or len(value)>2048:return False
    try:u=urlsplit(value)
    except ValueError:return False
    return u.scheme=='https' and bool(u.hostname) and not (u.username or u.password or u.query or u.fragment)

async def susun(request,akun,*,registry):
    if (getattr(request.state,'portal_scope',None) is not None
            or getattr(akun,'harus_ganti_sandi',None) is not False):return None
    from app.web.pengaturan import _metadata_menu_native, view_untuk, PERAN_ADMIN_KEATAS
    from app.web.security import pemulihan_lama_diizinkan
    from app.web.pengaturan_menu_kerangka import spesifikasi
    flags=await _metadata_menu_native(view=await view_untuk(akun.user),
        peran_asli=getattr(request.state,'peran_asli',None) or akun.peran,
        tuan=akun.peran in PERAN_ADMIN_KEATAS,is_super=akun.is_super,
        sesi_pendek=akun.sesi_pendek,pemulihan=pemulihan_lama_diizinkan)
    console=flags['console_url'] if flags['blok_perusahaan'] else ''
    if console and not valid_console(console):return None
    index=spesifikasi('/pengaturan',flags=flags,console_url=console)
    groups={g['id']:[d['allowed'] for d in g['doors']] for g in index['groups']}
    return dict(versi=1,cap=registry['cap'],konteks=registry['konteks'],sesi=registry['sesi'],
        sumber=aset()['sumber'],groups=groups,advanced=index['advanced'],recovery=index['recovery'],
        short=flags['sesi_pendek'],console=console)
