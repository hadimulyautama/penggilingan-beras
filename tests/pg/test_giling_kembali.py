"""Kursor navigasi tidak menyaring detail, mengubah hasil, atau menerima URL asing."""
import pytest
from starlette.requests import Request
from sqlalchemy import select
from app.models import MillingProcess
from app.web.layar_riwayat import _query_giling
from tests.pg.test_riwayat_giling import pabrik,_giling_selesai,_klien
from tests.pg.formulir import cap_formulir

@pytest.mark.parametrize('query,want',[(b'', ''),(b'sebelum=36','?sebelum=36'),(b'sebelum=nope',''),(b'sebelum=https%3A%2F%2Fevil.invalid',''),(b'sebelum=36%26role%3Dsuperadmin',''),(b'sebelum=0','')])
def test_hanya_kursor_integer(query,want):
    r=Request(dict(type='http',query_string=query,headers=[]))
    assert _query_giling(r)==want

@pytest.mark.asyncio
async def test_koreksi_giling_tetap_membawa_kursor(pg,pabrik):
    kode=await _giling_selesai(pg,pabrik)
    async with pg() as db:pid=await db.scalar(select(MillingProcess.id).where(MillingProcess.kode_proses==kode))
    async with await _klien(pg,peran='admin',gudang='Gudang 1') as c:
        r=await c.get(f'/riwayat-giling/{pid}?sebelum=36')
        assert r.status_code==200
        assert f'action="/riwayat-giling/{pid}/koreksi?sebelum=36"' in r.text
        assert f'href="/riwayat-giling?sebelum=36#giling-{pid}"' in r.text
        r=await c.post(f'/riwayat-giling/{pid}/koreksi?sebelum=36',data=dict(hasil_pk='6400',dasar_pk='6500',alasan='Koreksi sintetis navigasi',_csrf=cap_formulir(c)),follow_redirects=False)
        assert r.status_code==303,r.text
        assert r.headers['location']==f'/riwayat-giling/{pid}?koreksi=berhasil&sebelum=36'
        r=await c.get(r.headers['location']);assert r.status_code==200
        assert f'href="/riwayat-giling?sebelum=36#giling-{pid}"' in r.text
