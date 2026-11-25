"""Private, document-bound native active Sosoh schema; never a process grant."""
from functools import lru_cache
import hashlib
import json
from pathlib import Path


@lru_cache(maxsize=1)
def aset():
    folder = Path(__file__).parent / 'static'
    meta = json.loads((folder / 'kerangka-sosoh-ui.meta.json').read_text())
    if (meta.get('versi') != 1 or meta.get('variants') != ['admin', 'operator']
            or hashlib.sha256((folder / 'kerangka-sosoh-ui.js').read_bytes()).hexdigest() != meta.get('aset_sha256')):
        raise ValueError('Native Sosoh structure package mismatch')
    return meta


def descriptor(schema, *, layout, source, registry):
    """Bounded reference metadata only; reject values, IDs and unknown fields."""
    if (not isinstance(registry, dict) or layout not in ('admin', 'operator') or not isinstance(schema, (tuple, list))
            or not 0 < len(schema) <= 64
            or not all(type(v) is str and 0 < len(v) <= 512
                       for v in (registry.get('cap'), registry.get('konteks'), registry.get('sesi')))
            or type(source) is not str or len(source) != 64
            or any(c not in '0123456789abcdef' for c in source)):
        return None
    for row in schema:
        if (not isinstance(row, dict) or set(row) != {'jenis', 'nama', 'beras'}
                or type(row['jenis']) is not str or not 0 < len(row['jenis']) <= 128
                or type(row['nama']) is not str or not 0 < len(row['nama']) <= 256
                or type(row['beras']) is not bool):
            return None
    if len({row['jenis'] for row in schema}) != len(schema):
        return None
    data = dict(versi=1, sumber=source, cap=registry['cap'], konteks=registry['konteks'],
                sesi=registry['sesi'], layout=layout, hasil=list(schema))
    from jinja2.utils import htmlsafe_json_dumps
    return data if len(htmlsafe_json_dumps(data).encode()) <= 32768 else None


async def susun(request, akun, *, registry):
    from app.web.portal.scope import is_customer_read
    if (is_customer_read(request) or getattr(request.state, 'portal_scope', None) is not None
            or getattr(akun, 'harus_ganti_sandi', None) is not False):
        return None
    from app.web.api import _is_jenis_operator
    if not await _is_jenis_operator(akun.user, 'penyosohan'):
        return None
    from app.database import SessionLocal
    from app.web.sosoh_native_html import baca_schema_aktif
    async with SessionLocal() as db:
        schema = await baca_schema_aktif(db)
    from hmu_identitas import peran as P
    return descriptor(schema, layout='operator' if P.operator_saja(akun.user.role) else 'admin',
                      source=aset()['sumber'], registry=registry)
