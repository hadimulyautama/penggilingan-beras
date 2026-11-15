"""Baseline asli endpoint dan kartu pada fixture bertingkat."""
import dataclasses,hashlib,json,math,os,statistics,time
from pathlib import Path
import pytest
from sqlalchemy import event
from sqlalchemy.engine import Engine
from app import performa
from app.services import berjalan
from tests.pg.test_riwayat_pengeringan import pabrik,_klien
from tests.pg.data_pendinginan_baca import isi,WAKTU

pytestmark=pytest.mark.asyncio

@pytest.mark.parametrize('jumlah',[1,10,40])
async def test_ukur_pendinginan(pg,pabrik,monkeypatch,jumlah):
    await isi(pg,pabrik,jumlah)
    monkeypatch.setattr(berjalan,'now_local',lambda:WAKTU)
    from app.services import detail_pendinginan,proses_aktif
    monkeypatch.setattr(detail_pendinginan,'now_local',lambda:WAKTU)
    monkeypatch.setattr(proses_aktif,'now_local',lambda:WAKTU)
    out=Path(os.environ['BUKTI_OPERASI']);label=os.environ.get('BUKTI_LABEL','baseline')
    stats=[];queries=[]
    def sql(conn,cursor,statement,parameters,context,many):queries.append(statement)
    async with await _klien(pg,peran='admin',gudang='Gudang 1') as c:
        paths=['/pekerjaan?tab=berjalan&cari=OPR','/proses-aktif/pendinginan/OPR-000?kembali_kerja=%2Fpekerjaan%3Ftab%3Dberjalan%26cari%3DOPR']
        for path in paths:
            for _ in range(2):
                performa.lupakan_cache();assert (await c.get(path)).status_code==200
            for mode in ('cold','warm'):
                samples=[]
                event.listen(Engine,'before_cursor_execute',sql)
                try:
                    for _ in range(15):
                        if mode=='cold':performa.lupakan_cache()
                        queries.clear();start=time.perf_counter();r=await c.get(path);ms=(time.perf_counter()-start)*1000
                        assert r.status_code==200 and 'OPR-000' in r.text
                        samples.append(dict(ms=ms,queries=len(queries),bytes=len(r.content)))
                    page='list' if path.startswith('/pekerjaan') else 'detail'
                    (out/f'{label}-{jumlah}-{mode}-{page}.html').write_text(r.text)
                finally:event.remove(Engine,'before_cursor_execute',sql)
                times=sorted(x['ms'] for x in samples)
                stats.append(dict(path=path,mode=mode,samples=15,warmups=2,p50_ms=statistics.median(times),
                    p95_ms=times[math.ceil(.95*len(times))-1],queries=sorted({x['queries'] for x in samples}),
                    html_bytes=sorted({x['bytes'] for x in samples}),raw=samples))
        async with pg() as db:
            from app.models import User
            u=await db.get(User,pabrik['user'])
            b=await berjalan.untuk(db,u)
            rows=[dataclasses.asdict(x) for x in b.berjalan+b.transit if x.kode.startswith('OPR-')]
            (out/f'{label}-{jumlah}-cards.json').write_text(json.dumps(rows,default=str,sort_keys=True,indent=2)+'\n')
    (out/f'{label}-{jumlah}-measure.json').write_text(json.dumps(dict(volume=jumlah,results=stats,
        scope='Dedicated loopback PostgreSQL synthetic fixture; cold invalidates fixture snapshot caches; warm reuses unchanged cache. No production timing claim.'),indent=2)+'\n')


async def test_asal_lot_kosong_tanpa_query(pg):
    queries=[]
    def sql(*args):queries.append(1)
    async with pg() as db:
        event.listen(Engine,'before_cursor_execute',sql)
        try:assert await berjalan._asal_lot_banyak(db,[])=={}
        finally:event.remove(Engine,'before_cursor_execute',sql)
    assert not queries


async def test_asal_lot_sama_termasuk_cermin_jasa_dan_lot_kosong(pg,pabrik):
    from sqlalchemy import select,delete
    from app.models import DryingLot,DryingLotBatch,PurchaseBatch,Pelanggan,Jasa
    from app.penggilingan.gudang1.services.drying import _lot_batches
    rows=await isi(pg,pabrik,3)
    async with pg() as db:
        pelanggan=Pelanggan(nama_pelanggan='Pemilik Uji Asal');db.add(pelanggan);await db.flush()
        jasa=Jasa(kode='JAS-UJI-ASAL',pelanggan_id=pelanggan.id);db.add(jasa);await db.flush()
        batch=await db.scalar(select(PurchaseBatch).where(PurchaseBatch.kode_batch==rows[1]['batch']))
        batch.supplier_id=None;batch.jasa_id=jasa.id
        lot_jasa=await db.get(DryingLot,rows[1]['id']);lot_jasa.jasa_id=jasa.id
        await db.execute(delete(DryingLotBatch).where(DryingLotBatch.drying_lot_id==rows[2]['id']))
        for kode,batal in [('BOP-TAMBAH',False),('BOP-BATAL',True)]:
            batch=PurchaseBatch(kode_batch=kode,supplier_id=pabrik['pemasok'],berat_total_kg=1234.50,
                kondisi_gabah='basah',tanggal_pembelian=WAKTU.date(),waktu_pembelian=WAKTU,
                input_by=pabrik['user'],flag_unverified=False,sumber_berat='timbangan',status_batch='dikeringkan',
                dibatalkan_pada=WAKTU if batal else None)
            db.add(batch);await db.flush();db.add(DryingLotBatch(drying_lot_id=rows[0]['id'],purchase_batch_id=batch.id))
        await db.commit()
        lots=list((await db.scalars(select(DryingLot).order_by(DryingLot.id.desc()))).all())
        expected={lot.id:await berjalan._asal(db,[x.id for x in await _lot_batches(db,lot.id)]) for lot in lots}
        queries=[]
        def sql(conn,cursor,statement,*args):queries.append(statement)
        event.listen(Engine,'before_cursor_execute',sql)
        try:actual=await berjalan._asal_lot_banyak(db,lots)
        finally:event.remove(Engine,'before_cursor_execute',sql)
    assert actual==expected and list(actual)==[lot.id for lot in lots]
    assert actual[rows[2]['id']]==[]
    assert any('Pemilik Uji Asal' in x[0] for x in actual[rows[1]['id']])
    assert all('BOP-BATAL' not in str(x) for x in actual.values())
    assert len(actual[rows[0]['id']])==2
    projection=next(q for q in queries if 'drying_lot_batches' in q and 'JOIN purchase_batches' in q)
    assert 'purchase_batches.dibatalkan_pada IS NULL' in projection
