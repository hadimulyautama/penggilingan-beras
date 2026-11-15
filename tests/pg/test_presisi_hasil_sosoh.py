"""Presisi hasil mengikuti Numeric(12,2), termasuk lembar tambahan lama."""
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.models import User, PolishingOutputLog
from app.penggilingan.gudang2 import polishing as p
from tests.pg.test_form_selesai_penyosohan import proses, gudang2, fakta
from tests.pg.test_riwayat_giling import _klien
from tests.pg.test_sosoh_ringkas import url, post, preview


@pytest.mark.parametrize('value', ['1.23', '1.230', 0, 0.01, '7000.24'])
def test_satuan_hasil_sah(value):
    assert p.angka_hasil(value)==Decimal(str(value))


@pytest.mark.parametrize('value', ['1.231', '0.001', '0.009', '1e-10', 'NaN', 'Infinity', 'salah'])
def test_pecahan_yang_akan_berubah_ditolak(value):
    with pytest.raises(p.PresisiHasilError,match='2 desimal'):
        p.angka_hasil(value)


@pytest.mark.asyncio
@pytest.mark.parametrize('peran',['operator','admin','superadmin'])
async def test_lembar_campuran_ditolak_sebelum_pratinjau_atau_simpan(pg,proses,peran):
    async with await _klien(pg,peran=peran,gudang='Gudang 2') as c:
        state=(await c.get(url(proses))).json()
        body=dict(dasar=state['dasar'],hasil=[dict(jenis='medium',total=100.12),dict(jenis='premium',total=3000.123)])
        before=await fakta(pg)
        for action,step in [('hasil','periksa'),('neraca','pratinjau'),('hasil','simpan')]:
            r=await post(c,proses,action,step,body)
            assert r.status_code==400,r.text
            assert '2 desimal' in r.json()['detail']
            assert await fakta(pg)==before
        # Draf yang diperbaiki tetap memakai sidik yang sama; tidak perlu baca ulang.
        body['hasil'][1]['total']=3000.12
        r=await post(c,proses,'hasil','periksa',body)
        assert r.status_code==200,r.text
        body.update(pemeriksaan=r.json()['pemeriksaan'],konfirmasi=True)
        assert (await post(c,proses,'hasil','simpan',body)).status_code==200
        async with pg() as db:
            assert await p._output_map(db,proses['pid'])==dict(medium=100.12,premium=3000.12)


@pytest.mark.asyncio
async def test_selisih_desimal_dan_kompatibilitas_tambahan(pg,proses):
    async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
        for target,delta in [(0.1,0.1),(0.3,0.2)]:
            body=await preview(c,proses,'hasil',hasil=[dict(jenis='medium',total=target)])
            plan=(await post(c,proses,'hasil','periksa',body)).json()['rencana']['hasil'][0]
            assert plan['tambahan']==delta
            assert (await post(c,proses,'hasil','simpan',body)).status_code==200
    async with pg() as db:
        user=await db.get(User,proses['user'].id)
        with pytest.raises(p.PresisiHasilError):
            await p.catat_output(db,user=user,kode=proses['kode'],jenis='medium',berat_kg=0.001)
        await db.rollback()
        user=await db.get(User,proses['user'].id)
        r=await p.catat_output(db,user=user,kode=proses['kode'],jenis='medium',berat_kg=0.23)
        assert r.berat_kumulatif==0.53 and r.berat_kg==0.23
        logs=(await db.scalars(select(PolishingOutputLog.berat_kg).order_by(PolishingOutputLog.id))).all()
        assert logs==[Decimal('0.10'),Decimal('0.20'),Decimal('0.23')]
