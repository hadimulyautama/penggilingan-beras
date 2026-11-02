"""Batas cache: satu permintaan, satu pemilik, dan transaksi selalu segar."""
import asyncio
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI

from app import performa as p

pytestmark = pytest.mark.asyncio


async def test_kunci_scope_tetap_memuat_sumber_dan_tidak_dapat_diubah():
    from app.web.portal.scope import ReadScope
    from app.web.portal.security import CustomerReader
    reader=CustomerReader(1,2,'Uji')
    a=ReadScope(reader,frozenset({3}),frozenset({'sama'}),{'milling_process':frozenset({4})})
    b=ReadScope(reader,frozenset({3}),frozenset({'sama'}),{'milling_process':frozenset({5})})
    assert p._kunci_nilai(a)!=p._kunci_nilai(b)
    assert p._kunci_nilai(a) is p._kunci_nilai(a)
    with pytest.raises(TypeError):a.resources['milling_process']=frozenset({5})


async def test_snapshot_tampilan_serentak_tidak_dipakai_post_dan_commit_menghapus():
    from sqlalchemy.orm import Session
    engine=object()
    db=SimpleNamespace(new=[],dirty=[],deleted=[],get_bind=lambda:engine,connection=lambda:asyncio.sleep(0))
    calls=[]
    @p.tampilan_singkat
    async def nilai(db):
        calls.append(1)
        await asyncio.sleep(.01)
        return {'n':len(calls)}
    app=FastAPI();app.add_middleware(p.PerformaMiddleware)
    @app.api_route('/nilai',methods=['GET','POST'])
    async def halaman():return await nilai(db)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        rs=await asyncio.gather(*(c.get('/nilai') for _ in range(20)))
        assert len(calls)==1 and all(r.json()=={'n':1} for r in rs)
        await c.post('/nilai');assert len(calls)==2
        assert (await c.get('/nilai')).json()=={'n':3}
        with Session() as session:session.commit()
        assert (await c.get('/nilai')).json()=={'n':4}


async def test_snapshot_kunci_lain_tidak_terhalang_dan_pemimpin_putus_dibaca_ulang():
    engine=object()
    db=SimpleNamespace(new=[],dirty=[],deleted=[],get_bind=lambda:engine,connection=lambda:asyncio.sleep(0))
    mulai,lanjut=asyncio.Event(),asyncio.Event()
    calls=[]
    @p.tampilan_singkat
    async def nilai(db,key):
        calls.append(key)
        if key=='a' and calls.count('a')==1:
            mulai.set()
            await lanjut.wait()
        return {'key':key,'n':calls.count(key)}
    app=FastAPI();app.add_middleware(p.PerformaMiddleware)
    @app.get('/{key}')
    async def halaman(key:str):return await nilai(db,key)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as c:
        awal=asyncio.create_task(c.get('/a'))
        await mulai.wait()
        assert (await asyncio.wait_for(c.get('/b'),1)).json()=={'key':'b','n':1}
        awal.cancel()
        with pytest.raises(asyncio.CancelledError):await awal
        assert (await asyncio.wait_for(c.get('/a'),1)).json()=={'key':'a','n':2}


async def test_memo_hanya_get_dan_tidak_bocor_antar_permintaan():
    calls = []

    @p.baca_sekali
    async def saldo(db, silo, *, pemilik="pabrik"):
        calls.append((silo, pemilik))
        return {"kg": len(calls)}

    app = FastAPI()
    app.add_middleware(p.PerformaMiddleware)

    @app.api_route("/saldo", methods=["GET", "POST"])
    async def halaman():
        pertama = await saldo(None, 1)
        pertama["kg"] = -1
        return [await saldo(None, 1, pemilik="pabrik"), await saldo(None, 1, pemilik="jasa")]

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://uji") as c:
        a = await c.get("/saldo")
        assert a.json() == [{"kg": 1}, {"kg": 2}]
        assert "app;dur=" in a.headers["server-timing"]
        assert (await c.get("/saldo")).json() == [{"kg": 3}, {"kg": 4}]
        await c.post("/saldo")
    assert len(calls) == 7


async def test_penanda_serentak_satu_baca_dan_satu_klien_putus_tetap_aman():
    cache = p.NilaiSingkat()
    siap, lanjut = asyncio.Event(), asyncio.Event()
    calls = 0

    async def baca():
        nonlocal calls
        calls += 1
        siap.set()
        await lanjut.wait()
        return {"n": calls}

    awal = asyncio.create_task(cache.ambil("a", baca))
    await siap.wait()
    awal.cancel()
    with pytest.raises(asyncio.CancelledError):
        await awal
    lain = [asyncio.create_task(cache.ambil("a", baca)) for _ in range(20)]
    lanjut.set()
    hasil = await asyncio.gather(*lain)
    assert calls == 1 and all(x == {"n": 1} for x in hasil)
    hasil[0]["n"] = -1
    assert await cache.ambil("a", baca) == {"n": 1}
    cache.hapus()
    assert await cache.ambil("a", baca) == {"n": 2}


async def test_cache_kedaluwarsa_dan_kegagalan_dibaca_ulang(monkeypatch):
    jam = [0.0]
    monkeypatch.setattr(p.time, "monotonic", lambda: jam[0])
    cache = p.NilaiSingkat(detik=1)
    calls = 0

    async def baca():
        nonlocal calls
        calls += 1
        if calls == 1:
            raise ValueError("Gangguan sementara")
        return calls

    with pytest.raises(ValueError):
        await cache.ambil("a", baca)
    assert await cache.ambil("a", baca) == 2
    assert await cache.ambil("a", baca) == 2
    jam[0] = 1.1
    assert await cache.ambil("a", baca) == 3


async def test_lencana_dipisah_per_orang_peran_dan_gudang():
    from app.services.navigasi_cache import kunci
    a = SimpleNamespace(id=1, role="peran-a", default_warehouse_id=1)
    assert len({kunci(a), kunci(SimpleNamespace(**{**vars(a), "id": 2})),
                kunci(SimpleNamespace(**{**vars(a), "role": "peran-b"})),
                kunci(SimpleNamespace(**{**vars(a), "default_warehouse_id": 2}))}) == 4


async def test_stream_dikirim_langsung_tanpa_memo_dan_tanpa_buffer():
    chunks = []

    async def stream(scope, receive, send):
        assert p._konteks.get() is None
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"data: 1\n\n", "more_body": True})
        assert len(chunks) == 2
        await send({"type": "http.response.body", "body": b"", "more_body": False})

    async def send(message):
        chunks.append(message)

    await p.PerformaMiddleware(stream)({"type": "http", "method": "GET", "path": "/api/aliran"}, None, send)
    assert len(chunks) == 3 and p._konteks.get() is None


async def test_salin_kartu_cepat_tetap_memisahkan_semua_isian_mutable():
    import copy
    from app.services.berjalan import Baris,Tombol
    source=Baris(kode='uji',isi='uji',keadaan='',fakta=[('Jumlah','10 kg')],anak=[('Asal','10 kg','Hari ini')],
        tombol=[Tombol('Buka','Uji','/uji',{'ids':[1,2]})],bobot_pengeringan=[{'rincian':[1,2]}])
    source.tambahan={'rows':[['asli']]}
    a=copy.deepcopy(source);b=copy.deepcopy(source)
    a.fakta.append(('Baru','20 kg'));a.anak[0]=('Lain','20 kg','Besok')
    a.tombol[0].data['ids'].append(3);a.bobot_pengeringan[0]['rincian'].append(3)
    a.tambahan['rows'][0].append('berubah');a.isi='berubah'
    assert b==source and b.tambahan==source.tambahan and b.isi=='uji'
    assert b.tombol[0].data['ids']==[1,2]


async def test_snapshot_kedaluwarsa_dua_detik_dan_objek_tidak_dibagi(monkeypatch):
    clock=[0.0];monkeypatch.setattr(p.time,'monotonic',lambda:clock[0])
    engine=object();calls=[]
    db=SimpleNamespace(new=[],dirty=[],deleted=[],get_bind=lambda:engine,connection=lambda:asyncio.sleep(0))
    @p.tampilan_singkat
    async def nilai(db):
        calls.append(1)
        return {'n':len(calls)}
    token=p._konteks.set({'boleh_memo':True,'memo':{}})
    try:
        first=await nilai(db);first['n']=-1
        clock[0]=1.9;assert (await nilai(db))['n']==1
        clock[0]=2.1;assert (await nilai(db))['n']==2
    finally:p._konteks.reset(token)
