"""History layout choices for the current document; never HTML or records.

Public structure lives in versioned program assets. Fresh native GET still
authorizes each destination and reads its real data. No transaction cache.
"""
from functools import lru_cache
import hashlib
import json
from pathlib import Path

MAX_JSON_BYTES = 8192
GROUPS={
    'proses':{'/riwayat-giling','/riwayat-sosoh','/riwayat-pengeringan'},
    'qc':{'/riwayat-qc/'+kind for kind in ('gabah-basah','gabah-kering','pk-hasil-giling','pk-luar','beras-hasil-sosoh')},
    'laporan':{'/laporan'},'audit':{'/audit'},
}


def paths():
    from app.web.riwayat_daftar_metadata import PROCESS, QC
    return (*PROCESS, *('/riwayat-qc/'+kind for kind in sorted(QC)))


@lru_cache(maxsize=1)
def aset():
    folder=Path(__file__).parent/'static'
    data=json.loads((folder/'kerangka-riwayat-ui.meta.json').read_text())
    if (data.get('versi')!=1 or set(data.get('variants',()))!=set(paths())
            or hashlib.sha256((folder/'kerangka-riwayat-ui.js').read_bytes()).hexdigest()!=data.get('aset_sha256')):
        raise ValueError('Native history program package mismatch')
    return data


def valid(data):
    from jinja2.utils import htmlsafe_json_dumps
    allowed=set(paths())
    if (not isinstance(data,dict)
            or set(data)!={'versi','cap','konteks','sesi','sumber','targets','menu'}
            or data['versi']!=1
            or not all(type(data[key]) is str and 0<len(data[key])<=512 for key in ('cap','konteks','sesi'))
            or type(data['sumber']) is not str or len(data['sumber'])!=64
            or any(c not in '0123456789abcdef' for c in data['sumber'])
            or not isinstance(data['targets'],list) or not data['targets'] or len(data['targets'])>7
            or not all(type(path) is str and path in allowed for path in data['targets'])
            or len(set(data['targets']))!=len(data['targets'])):
        return False
    menu=data['menu'];destinations=allowed|{'/laporan','/audit','/riwayat-qc/beras-hasil-sosoh'}
    if (not isinstance(menu,dict) or set(menu)!={'default','tabs'}
            or type(menu['default']) is not str or menu['default'] not in destinations
            or not isinstance(menu['tabs'],dict) or not menu['tabs']
            or not set(menu['tabs']) <= {'proses','qc','laporan','audit'}):
        return False
    for key,tab in menu['tabs'].items():
        if (not isinstance(tab,dict) or set(tab)!={'first','allowed'}
                or not isinstance(tab['allowed'],list) or not tab['allowed']
                or len(tab['allowed'])>5
                or not all(type(path) is str and path in GROUPS[key] for path in tab['allowed'])
                or len(set(tab['allowed']))!=len(tab['allowed'])
                or tab['first']!=tab['allowed'][0]):
            return False
    first=next(key for key in GROUPS if key in menu['tabs'])
    if menu['default']!=menu['tabs'][first]['first']:
        return False
    for path in data['targets']:
        family='proses' if path in GROUPS['proses'] else 'qc'
        if path not in menu['tabs'].get(family,{}).get('allowed',()):
            return False
    return len(htmlsafe_json_dumps(data).encode())<=MAX_JSON_BYTES


async def susun(request,akun,*,navigasi,registry):
    from app.web.portal.scope import is_customer_read
    if is_customer_read(request) or getattr(request.state,'portal_scope',None) is not None:
        return None
    from app.web.laporan_navigasi import TAB, pilihan
    from app.web.riwayat_daftar_bertahap import _boleh
    from app.web.riwayat_daftar_metadata import PROCESS
    options=await pilihan(akun)
    tabs={key:dict(first=options[key][0][2],allowed=[row[2] for row in options[key]])
          for key,_ in TAB if options[key]}
    targets=[]
    for path in paths():
        family='proses' if path in PROCESS else 'qc'
        if path not in tabs.get(family,{}).get('allowed',()) or not await _boleh(akun.user,path):
            continue
        targets.append(path)
    if not targets:return None
    data=dict(versi=1,cap=registry['cap'],konteks=registry['konteks'],sesi=registry['sesi'],
              sumber=aset()['sumber'],targets=targets,
              menu=dict(default=next(tabs[key]['first'] for key,_ in TAB if key in tabs),tabs=tabs))
    return data if valid(data) else None
