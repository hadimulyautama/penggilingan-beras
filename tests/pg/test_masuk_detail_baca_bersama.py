"""Satu tiket penerimaan beras dapat memiliki beberapa catatan/kemasan."""
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import statistics
from time import perf_counter

import pytest
from sqlalchemy import event, update
from hmu_identitas import peran as P
from app.models import User, FinishedGoodsStock
from app.services.masuk_detail_timbang import baca
from tests.pg.test_masuk_detail_timbang import contoh, catat, sidik


@pytest.mark.parametrize('jumlah', [1, 20, 100])
async def test_detail_multicatatan_hasil_tetap_dan_bacaan_terbatas(pg, contoh, jumlah):
    waktu = datetime(2026, 11, 15, 8, tzinfo=timezone.utc)
    async with pg() as db:
        for i in range(jumlah):
            await catat(db, contoh, jenis='BERAS_MASUK', berat=100, suffix=str(i))
        await db.execute(update(FinishedGoodsStock).values(waktu=waktu))
        await db.commit()
        awal = await sidik(db)
    counts, times, result = [], [], None
    for i in range(22):
        async with pg() as db:
            user = await db.get(User, contoh['uid'])
            statements = []
            def hitung(conn, cursor, statement, parameters, context, executemany):
                assert statement.lstrip().upper().startswith('SELECT'), 'Pembaca mencoba menulis'
                statements.append(statement)
            engine = db.bind.sync_engine
            event.listen(engine, 'before_cursor_execute', hitung)
            try:
                start = perf_counter()
                actual = await baca(db, contoh['tid'], user)
                elapsed = (perf_counter()-start)*1000
            finally:
                event.remove(engine, 'before_cursor_execute', hitung)
            if result is None: result = actual
            assert actual == result
            if i >= 2: counts.append(len(statements)); times.append(elapsed)
    async with pg() as db: assert await sidik(db) == awal
    assert len(result['catatan']) == jumlah
    assert float(result['berat_diterima_kg']) == 100*jumlah
    assert all(c['petugas']=='Penerima Uji' and c['model']=='beras' for c in result['catatan'])
    root = os.getenv('HASIL_PERFORMA_DETAIL')
    phase = os.getenv('FASE_PERFORMA_DETAIL', 'sesudah')
    if root:
        path = Path(root); path.mkdir(exist_ok=True)
        canonical = json.dumps(result, ensure_ascii=False, sort_keys=True)
        expected = path/f'baseline-api-{jumlah}.json'
        if phase == 'sebelum': expected.write_text(canonical)
        else: assert canonical == expected.read_text(), 'Hasil detail berubah'
        ordered = sorted(times)
        data = {'fase':phase,'catatan_satu_tiket':jumlah,'query_per_call':sorted(set(counts)),
            'samples':len(times),'p50_ms':round(statistics.median(times),3),
            'p95_ms':round(ordered[math.ceil(.95*len(ordered))-1],3),
            'result_sha256':hashlib.sha256(canonical.encode()).hexdigest(),
            'batas':'Pembaca API penerimaan asli pada PostgreSQL loopback uji_*; tidak memakai stub layanan, bukan performa produksi'}
        (path/f'{phase}-api-{jumlah}.json').write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n')
    assert max(counts) <= 20, f'Query bertambah menurut catatan tiket: {counts[0]}'


async def test_nama_tiap_pencatat_tetap_sesuai_catatan(pg, contoh):
    async with pg() as db:
        pertama = await catat(db, contoh, jenis='BERAS_MASUK', suffix='A')
        kedua = await catat(db, contoh, jenis='BERAS_MASUK', suffix='B')
        operator = User(nama='Pencatat Kedua Fiktif', role=P.OPERATOR, status='aktif')
        db.add(operator); await db.flush(); kedua.input_by = operator.id
        await db.commit(); awal = await sidik(db)
        detail = await baca(db, contoh['tid'], await db.get(User, contoh['uid']))
        assert {c['id']:c['petugas'] for c in detail['catatan']} == {
            pertama.id:'Penerima Uji', kedua.id:'Pencatat Kedua Fiktif'}
        assert await sidik(db) == awal
