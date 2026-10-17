"""Skor kartu mengikuti enam komponen dan skala klasifikasi 0–4."""
from pathlib import Path

import pytest
from sqlalchemy import select
from app.models import User,PkPurchaseVerification,MillingProcess
from app.penggilingan.gudang1.services.milling import log_qc_milling,qc_rata
from app.penggilingan.gudang2.service import log_pk_qc
from app.services import stok
from hmu_identitas.peran import SUPERADMIN
from tests.pg.test_stok_pk_qc import dunia,dunia_asal
from tests.pg.test_riwayat_giling import _klien

pytestmark=pytest.mark.asyncio


async def test_nilai_enam_komponen_di_giling_transfer_dan_pk_luar(pg,dunia):
    async with pg() as db:
        awal=(await stok.pk_gudang1(db))[0]
        assert awal.nilai_kualitas==100 and awal.komponen_kualitas==6
        luar=next(x for x in await stok.pk_gudang2(db) if x.intake_id==dunia['beli_intake_id'])
        assert luar.nilai_kualitas==pytest.approx(550/6)
        assert luar.komponen_kualitas==6 and luar.kelas_kualitas=='A2'
        user=await db.get(User,dunia['user'].id)
        await log_qc_milling(db,user=user,kode_proses='LOT-KODE-01',kadar_air=13.2,
                             broken=4,susut=1.5,kondisi=None,
                             butir_kuning='parah',gabah='parah',merang='parah')
        # Bersih(0) + Parah(4) -> Sedang(2), lalu skor 70, bukan rata-rata
        # skor 100 dan 10. Kedua skala sengaja tidak dicampur.
        rata=await qc_rata(db,await db.scalar(select(MillingProcess.id)))
        assert (rata.butir_kuning,rata.gabah,rata.merang)==('sedang','sedang','sedang')
        g1=(await stok.pk_gudang1(db))[0]
        transfer=next(x for x in await stok.pk_gudang2(db) if x.intake_id==dunia['giling_intake_id'])
        assert g1.nilai_kualitas==85 and g1.komponen_kualitas==6
        assert transfer.nilai_kualitas==g1.nilai_kualitas
        assert g1.kelas_kualitas==transfer.kelas_kualitas=='B2'
        await log_pk_qc(db,user=user,kode='PKB-KODE-01',kadar_air=13.8,broken=3.5,
                        penyusutan_persen=1.9,butir_kuning='parah',gabah='parah',merang='parah')
        v=await db.scalar(select(PkPurchaseVerification))
        assert (v.butir_kuning,v.gabah,v.merang)==('banyak','sedang','banyak')
        luar=next(x for x in await stok.pk_gudang2(db) if x.intake_id==dunia['beli_intake_id'])
        assert luar.nilai_kualitas==pytest.approx(490/6)
        assert luar.komponen_kualitas==6 and luar.kelas_kualitas=='B2'
    async with await _klien(pg,peran=SUPERADMIN) as c:
        for nama,path in [('g1','/stok/pk/detail?gudang=g1&kode=LOT-KODE-01'),
                          ('transfer',f'/stok/pk/detail?gudang=g2&id={dunia["giling_intake_id"]}'),
                          ('luar',f'/stok/pk/detail?gudang=g2&id={dunia["beli_intake_id"]}')]:
            r=await c.get(path)
            assert r.status_code==200 and 'Skor dari 6/6 komponen QC' in r.text
            assert 'Parah' in r.text
            Path('/tmp/hmu-stok-qc-'+nama+'.html').write_text(r.text)
        daftar=await c.get('/stok')
        assert '6/6 komponen' in daftar.text and '6/3 komponen' not in daftar.text
        menu=(await c.get('/api/actions/menu')).json()
        for aksi in menu:
            if aksi['id'] in ('qc_giling','qc_pk_luar'):
                for field in aksi['fields']:
                    if field['name'] in ('butir_kuning','gabah','merang'):
                        assert ['parah','Parah (4)'] in field['options']
