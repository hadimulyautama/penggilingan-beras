"""Contoh PK jasa menyediakan detail kedua gudang dan aman diulang."""
import json
from pathlib import Path

import pytest
from sqlalchemy import func,select
from app.config import settings
from app.models import User,SetelanPabrik,MillingQcLog,Silo
from app.services.seed import seed_master
from hmu_identitas.peran import SUPERADMIN
from scripts import isi_tampilan_uji as dasar, isi_pk_jasa_uji as contoh
from tests.pg.test_riwayat_giling import _klien


@pytest.mark.asyncio
async def test_contoh_pk_jasa_berisi_detail_dan_qc_berulang_tanpa_menggandakan_data(pg,monkeypatch):
    monkeypatch.setattr(settings,'mode_uji',True)
    for module in [dasar,contoh]:
        monkeypatch.setattr(module,'SessionLocal',pg)
        monkeypatch.setattr(module,'engine',pg.kw['bind'])
    await seed_master()
    async with pg() as db:
        user=User(nama='Pengisi contoh',role=SUPERADMIN,status='aktif')
        db.add(user);await db.commit()
    p=dasar.Pengisi(user.id,{'langkah':{}})
    await p.master()
    async with pg() as db:
        checkpoint=(await db.get(SetelanPabrik,dasar.KUNCI)).nilai
    assert (await contoh.jalankan(False))['g1']==[]
    async with pg() as db:
        assert await db.get(SetelanPabrik,contoh.KUNCI) is None
        assert await db.scalar(select(Silo.id).where(Silo.nama_silo==contoh.SILO)) is None
    hasil=await contoh.jalankan(True)
    assert len(hasil['g1'])==len(hasil['g2'])==1
    assert hasil['g1'][0]['kg']==5140 and hasil['g2'][0]['kg']==3500
    assert hasil['g1'][0]['nilai']==hasil['g2'][0]['nilai']
    assert await contoh.jalankan(True)==hasil
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(MillingQcLog))==3
        assert (await db.get(SetelanPabrik,dasar.KUNCI)).nilai==checkpoint
    async with await _klien(pg,peran=SUPERADMIN) as c:
        daftar=await c.get('/stok-pk-jasa')
        assert daftar.status_code==200
        Path('/tmp/hmu-pk-jasa-daftar.html').write_text(daftar.text)
        for gudang in ['g1','g2']:
            href=hasil[gudang][0]['detail']
            r=await c.get(href)
            assert r.status_code==200
            for s in ['6/6 komponen dinilai','3 putaran QC','QC 3',hasil[gudang][0]['pemilik']]:
                assert s in r.text
            Path('/tmp/hmu-pk-jasa-'+gudang+'-detail.html').write_text(r.text)


@pytest.mark.asyncio
async def test_contoh_pk_jasa_hanya_mode_uji(monkeypatch):
    monkeypatch.setattr(settings,'mode_uji',False)
    with pytest.raises(ValueError,match='MODE_UJI'):
        await contoh.jalankan(True)
