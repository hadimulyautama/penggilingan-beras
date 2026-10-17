"""QC PK berulang menjaga putaran, rata-rata klasifikasi dan pembatalannya."""
import asyncio
from pathlib import Path

import pytest
from sqlalchemy import select,func

from app.database import now_local
from app.models import PkPurchaseBatch,PkPurchaseQcLog,PkPurchaseVerification,User
from app.penggilingan.gudang2.service import log_pk_qc
from app.services import stok
from hmu_identitas.peran import SUPERADMIN
from tests.pg.test_stok_pk_qc import dunia,dunia_asal
from tests.pg.test_riwayat_giling import _klien

pytestmark=pytest.mark.asyncio


async def catat(pg,dunia,ka,kuning,gabah,merang):
    async with pg() as db:
        return await log_pk_qc(db,user=await db.get(User,dunia['user'].id),
                               kode='PKB-KODE-01',kadar_air=ka,
                               butir_kuning=kuning,gabah=gabah,merang=merang)


async def test_klasifikasi_dirata_sendiri_dan_tengah_ke_kategori_lebih_kotor(pg,dunia):
    # Awal: kuning=Sedang(2), gabah=Bersih(0), merang=Sedikit(1).
    await catat(pg,dunia,12,'sedikit','sedikit','banyak')
    async with pg() as db:
        v=await db.scalar(select(PkPurchaseVerification))
        assert float(v.kadar_air)==12.9
        assert (v.butir_kuning,v.gabah,v.merang)==('sedang','sedikit','sedang')
        # 1,5 -> Sedang; 0,5 -> Sedikit; 2 -> Sedang. Bukan hasil terakhir.
        h=await stok.riwayat_qc_pk(db,intake_id=dunia['beli_intake_id'])
        assert [x['nomor'] for x in h['rows']]==[2,1]
        assert [x['ka'] for x in h['rows']]==['12,0%','13,8%']
    async with await _klien(pg,peran=SUPERADMIN) as c:
        daftar=(await c.get('/api/actions/pk-luar-qc')).json()
        assert next(x for x in daftar if x['value']=='PKB-KODE-01')
        r=await c.get(f'/stok/pk/detail?gudang=g2&id={dunia["beli_intake_id"]}')
        assert r.status_code==200
        assert 'Catat QC berikutnya' in r.text
        assert 'QC 2' in r.text and 'QC 1' in r.text
        Path('/tmp/hmu-stok-qc-luar.html').write_text(r.text)
        r=await c.get('/riwayat-qc/pk-luar/PKB-KODE-01')
        assert r.status_code==200 and r.text.count('class="qc-history-round"')==2
        assert 'Pencatat' in r.text


async def test_dua_pencatat_bersamaan_tidak_menghilangkan_putaran_atau_rata_rata(pg,dunia):
    await asyncio.gather(catat(pg,dunia,12,'bersih','bersih','bersih'),
                         catat(pg,dunia,18,'banyak','banyak','banyak'))
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(PkPurchaseQcLog))==3
        v=await db.scalar(select(PkPurchaseVerification))
        assert float(v.kadar_air)==14.6
        assert (v.butir_kuning,v.gabah,v.merang)==('sedang','sedikit','sedikit')


async def test_batalkan_satu_putaran_mengembalikan_rata_rata(pg,dunia):
    from app.services.undo import _undo_pk_qc
    from app.models import ActivityLog
    await catat(pg,dunia,12,'bersih','bersih','bersih')
    async with pg() as db:
        audit=await db.scalar(select(ActivityLog).where(ActivityLog.table_name=='pk_purchase_qc_logs').order_by(ActivityLog.id.desc()))
        assert audit.gudang=='g2' and audit.action=='INSERT'
        terakhir=await db.scalar(select(PkPurchaseQcLog.id).order_by(PkPurchaseQcLog.id.desc()))
        await _undo_pk_qc(db,terakhir)
        await db.commit()
        v=await db.scalar(select(PkPurchaseVerification))
        assert float(v.kadar_air)==13.8
        assert (v.butir_kuning,v.gabah,v.merang)==('sedang','bersih','sedikit')
        assert await db.scalar(select(func.count()).select_from(PkPurchaseQcLog))==1


async def test_detail_membaca_lebih_dari_200_putaran_dan_picker_tetap_memuat_batch_lama(pg,dunia):
    async with pg() as db:
        b=await db.scalar(select(PkPurchaseBatch))
        for i in range(204):
            db.add(PkPurchaseQcLog(pk_purchase_batch_id=b.id,kadar_air=12,
                                  butir_kuning='bersih',gabah='bersih',merang='bersih',
                                  waktu=now_local(),input_by=dunia['user'].id))
        for i in range(35):
            db.add(PkPurchaseBatch(kode_batch=f'PKB-LAIN-{i}',supplier_id=b.supplier_id,
                                  tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),
                                  input_by=dunia['user'].id,status_batch='diterima',sumber_berat='manual'))
        await db.commit()
    r=await catat(pg,dunia,14,'sedikit','sedikit','sedikit')
    assert r.qc_count==206
    async with await _klien(pg,peran=SUPERADMIN) as c:
        assert 'PKB-KODE-01' in [x['value'] for x in (await c.get('/api/actions/pk-luar-qc')).json()]
        daftar=await c.get('/riwayat-qc/pk-luar')
        assert '206 putaran' in daftar.text
        r=await c.get('/riwayat-qc/pk-luar/PKB-KODE-01')
        assert r.status_code==200
        assert r.text.count('class="qc-history-round"')==206
        r=await c.get(f'/stok/pk/detail?gudang=g2&id={dunia["beli_intake_id"]}')
        assert r.text.count('data-label="Merang"')==206
