"""Tolok ukur lokal yang dapat diulang, hanya memakai data sintetis fixture."""
import hashlib
import json
import os
import time
from pathlib import Path
import pytest
from bs4 import BeautifulSoup
from sqlalchemy import event
from tests.pg.test_portal_pelanggan import portal, qc, client
from tests.pg.test_papan_beranda_http import _klien

pytestmark = [pytest.mark.asyncio, pytest.mark.skipif(not os.environ.get('HMU_BENCH_OUTPUT'), reason='Tolok ukur dijalankan eksplisit')]


async def test_halaman_sintetis(pg, portal):
    engine=pg.kw['bind']
    samples=[]
    def before(conn,cursor,statement,params,ctx,many):ctx._ukur=time.perf_counter()
    def after(conn,cursor,statement,params,ctx,many):samples.append((time.perf_counter()-ctx._ukur)*1000)
    event.listen(engine.sync_engine,'before_cursor_execute',before)
    event.listen(engine.sync_engine,'after_cursor_execute',after)
    rows=[]
    async def ukur(c,role,paths):
        for cycle in range(2):
            for path in paths:
                samples.clear();start=time.perf_counter();r=await c.get(path)
                elapsed=(time.perf_counter()-start)*1000
                soup=BeautifulSoup(r.text,'html.parser')
                for el in soup.select('script,style,footer,.versi,#segar'):el.decompose()
                main=soup.select_one('main') or soup
                rows.append(dict(role=role,path=path,cycle=cycle,status=r.status_code,
                    ms=round(elapsed,1),sql=len(samples),sql_ms=round(sum(samples),1),
                    text_sha=hashlib.sha256(main.get_text(' ',strip=True).encode()).hexdigest()))
                assert r.status_code==200,(role,path,r.status_code)
    try:
        async with await _klien(pg,role='superadmin') as c:
            await ukur(c,'staf',['/','/pekerjaan','/stok','/stok?tab=produk','/barang-keluar','/laporan','/pengaturan',
                '/jasa/pelanggan/'+str(portal.owners[0].id),
                '/riwayat-giling/'+str(portal.process[0]['giling']),
                '/riwayat-pengeringan/'+str(portal.process[0]['pengeringan']),
                '/riwayat-sosoh/'+str(portal.process[0]['sosoh'])])
        async with client(portal.accounts[0]) as c:
            await ukur(c,'pelanggan',['/pelanggan/','/pelanggan/ringkasan','/pelanggan/barang-saya','/pelanggan/jasa-saya','/pelanggan/riwayat-proses','/pelanggan/pekerjaan','/pelanggan/stok',
                '/pelanggan/stok?tab=produk','/pelanggan/barang-masuk','/pelanggan/barang-keluar',
                '/pelanggan/laporan','/pelanggan/jasa/pelanggan/'+str(portal.owners[0].id),
                '/pelanggan/riwayat-giling/'+str(portal.process[0]['giling'])])
        Path(os.environ['HMU_BENCH_OUTPUT']).write_text(json.dumps(rows,indent=2))
    finally:
        event.remove(engine.sync_engine,'before_cursor_execute',before)
        event.remove(engine.sync_engine,'after_cursor_execute',after)
