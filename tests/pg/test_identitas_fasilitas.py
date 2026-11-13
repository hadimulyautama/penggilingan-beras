"""Pembanding lokasi tampilan, tanpa perubahan izin, saldo, atau transaksi."""
from dataclasses import FrozenInstanceError
import pytest
from sqlalchemy import select
from app.database import now_local
from app.models import (Warehouse, Silo, LiniProduksi, JenisProsesProduksi,
                        PolishingProcess, PolishingSiloUsage, MillingProcess)
from app.services.fasilitas import identitas_fasilitas, label_fasilitas, simpan_lini
from tests.pg.test_fasilitas import dunia
from tests.pg.test_masuk_detail_timbang import sidik
from tests.pg.test_masukkan_beras_silo import sosoh

pytestmark = [pytest.mark.asyncio, pytest.mark.fondasi_multi]


async def test_dua_line_sejenis_dan_line_berbeda_mempunyai_identitas_sendiri(pg):
    user, _, _ = await dunia(pg)
    async with pg() as db:
        wh = Warehouse(nama_gudang='Sentra Timur', aktif=True)
        db.add(wh); await db.flush()
        types = {r.kode:r.id for r in await db.scalars(select(JenisProsesProduksi))}
        lines = [await simpan_lini(db,user=user,kode=kode,nama=nama,warehouse_id=wh.id,
                  jenis_proses_id=types[kind]) for kode,nama,kind in
                 [('poles-a','Polesan A','penyosohan'),('poles-b','Polesan B','penyosohan'),
                  ('giling-c','Penggilingan C','penggilingan')]]
        silo = Silo(nama_silo='Bahan C',warehouse_id=wh.id,jenis_isi='gabah',aktif=True)
        db.add(silo); await db.flush()
        runs = [PolishingProcess(kode_proses='POL-FONDASI-'+str(i),lini_produksi_id=line.id,
                status='proses',waktu_mulai=now_local(),created_by=user.id) for i,line in enumerate(lines[:2])]
        runs.append(MillingProcess(kode_proses='LOT-FONDASI',lini_produksi_id=lines[2].id,
                    silo_id=silo.id,berat_gabah_masuk_kg=998,waktu_mulai=now_local(),created_by=user.id))
        db.add_all(runs); await db.commit()
        before = await sidik(db)
        identities = [await identitas_fasilitas(db,p) for p in runs]
        assert [i.label for i in identities] == ['Sentra Timur · Polesan A','Sentra Timur · Polesan B','Sentra Timur · Penggilingan C']
        assert {i.warehouse_id for i in identities} == {wh.id}
        assert [i.lini_id for i in identities] == [line.id for line in lines]
        for proc,identity in zip(runs,identities):
            assert await label_fasilitas(db,proc) == identity.label
        with pytest.raises(FrozenInstanceError):
            identities[0].nama_gudang = 'Tidak boleh berubah'
        assert await sidik(db) == before


@pytest.mark.parametrize('case',['satu_gudang','campuran_gudang','tanpa_lokasi'])
async def test_historis_tidak_mengarang_gudang_atau_line_dan_tidak_menulis(pg,sosoh,case):
    async with pg() as db:
        proc = await db.get(PolishingProcess,sosoh['proc_id'])
        usage = await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==proc.id))
        silo = await db.get(Silo,usage.silo_id)
        wh = await db.get(Warehouse,silo.warehouse_id)
        if case == 'campuran_gudang':
            other = Warehouse(nama_gudang='Lokasi tambahan',aktif=True);db.add(other);await db.flush()
            another = Silo(nama_silo='Bahan tambahan',warehouse_id=other.id,jenis_isi='pk',aktif=True)
            db.add(another);await db.flush()
            db.add(PolishingSiloUsage(polishing_process_id=proc.id,silo_id=another.id,berat_awal_kg=10))
        elif case == 'tanpa_lokasi':
            await db.delete(usage)
        await db.commit()
        before = await sidik(db)
        identity = await identitas_fasilitas(db,proc)
        assert identity.lini_id is None and identity.nama_lini is None
        if case == 'satu_gudang':
            assert identity.warehouse_id == wh.id and identity.label == wh.nama_gudang
        else:
            assert identity.warehouse_id is None and identity.label == 'Fasilitas historis belum tercatat'
        assert await sidik(db) == before
