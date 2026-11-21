"""Pembukuan raw eksplisit dan pemindahan satu transaksi, tanpa Packing baru."""
import json,os
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
import pytest
import pytest_asyncio
from sqlalchemy import select,func
from app.models import User,OutgoingRecord,ByproductStock,BrokenKeSilo,ActivityLog,Peristiwa,FinishedGoodsStock
from app.services.barang_keluar import buat_perintah,BarisPerintah,tersedia
from app.services.rencana_broken_silo import rincian
from app.penggilingan.gudang2 import service as g2
from tests.pg.test_broken_silo_saldo_bebas import foto,sosoh,sidik
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir

pytestmark=pytest.mark.asyncio

async def pesan(pg,foto,kg):
    async with pg() as db:
        rec=await db.get(OutgoingRecord,foto['order']);cid=rec.pelanggan_id
        await buat_perintah(db,user=await db.get(User,foto['user']),pelanggan_id=cid,
            baris=[BarisPerintah(tipe='byproduct_curah',jenis='broken',berat_kg=kg)],no_polisi='AD 2345 XY')

@pytest_asyncio.fixture
async def spill(pg,foto):
    await pesan(pg,foto,1000)
    return foto

@pytest.mark.parametrize('decimal_pending',[0,0.2])
async def test_preview_1900_persiapan350_silo1350_replay(pg,spill,monkeypatch,decimal_pending):
    if decimal_pending:await pesan(pg,spill,decimal_pending)
    from app.penggilingan.inventory import finished_goods as fg
    async def forbidden(*a,**k):raise AssertionError('Helper legacy ber-commit tidak boleh dipanggil')
    monkeypatch.setattr(fg,'catat_broken',forbidden)
    async with await _klien(pg,spill['user'],'broken-spill-success') as c:
        before=await sidik(pg)
        async with pg() as db:
            assert await fg.hitung_stok_byproduct_total(db,'broken')==3400
            assert (await tersedia(db,BarisPerintah(tipe='byproduct_curah',jenis='broken')))[0]==pytest.approx(1900-decimal_pending)
        d=(await c.get('/api/actions/rincian-broken-silo',params=dict(proses='pemilik|pabrik',berat_kg=1350,silo='C'))).json()
        assert await sidik(pg)==before # pure reader, tidak menulis lalu rollback
        assert d['saldo']['total']==pytest.approx(1900-decimal_pending) and d['saldo']['karung']==0
        plan=d['rencana'];assert plan['kg']==1350 and plan['pembukuan_kg']==pytest.approx(350+decimal_pending) and plan['total_hasil_dibukukan_kg']==pytest.approx(1700+decimal_pending)
        assert [x['proc_id'] for x in plan['pembukuan_sumber']]==[spill['proc_id'],spill['proc_2150']]
        assert [x['kg'] for x in plan['pembukuan_sumber']]==pytest.approx([100,250+decimal_pending])
        assert plan['sisa']['total']==pytest.approx(550-decimal_pending) and plan['bongkar_kg']==0
        payload=dict(proses='pemilik|pabrik',silo='C',berat_kg=1350,kunci_kiriman=uuid4().hex)
        a=await c.post('/api/actions/masukkan-broken-silo',json=payload,headers={'X-CSRF-Token':cap_formulir(c)})
        assert a.status_code==200,a.text
        after=await sidik(pg)
        replay=await c.post('/api/actions/masukkan-broken-silo',json=payload,headers={'X-CSRF-Token':cap_formulir(c)})
        assert replay.status_code==200 and replay.json()==a.json() and await sidik(pg)==after
        for table in ['outgoing_records','outgoing_items','polishing_output_logs','finished_goods_stock']:
            assert after[table]==before[table]
    async with pg() as db:
        assert await g2.hitung_stok_silo(db,spill['silo']['C'])==1350
        assert (await rincian(db,'pemilik|pabrik'))['saldo']==pytest.approx(plan['sisa'])
        assert await db.scalar(select(func.sum(ByproductStock.berat_kg)))==Decimal('2850')+Decimal(str(decimal_pending))
        assert await fg.hitung_stok_byproduct_total(db,'broken')==pytest.approx(2050)
        assert (await tersedia(db,BarisPerintah(tipe='byproduct_curah',jenis='broken')))[0]==pytest.approx(550-decimal_pending)
        assert await db.scalar(select(func.sum(BrokenKeSilo.berat_kg)).where(BrokenKeSilo.byproduct_stock_id==spill['receipt'])) is None
        audit=(await db.scalars(select(ActivityLog).where(ActivityLog.aksi=='broken_catat_otomatis',ActivityLog.field_name=='persiapan_silo'))).all()
        assert len(audit)==2 and all('tidak masuk silo' in a.new_value for a in audit)
        prepared=(await db.scalars(select(ByproductStock).where(ByproductStock.id.in_([a.record_id for a in audit])))).all()
        assert len(prepared)==2 and all(r.jasa_id is None and r.warehouse_id==spill['warehouse'] for r in prepared)
        assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis=='kiriman_hasil_samping_silo'))==1
    (Path(os.environ['PHASE_OUT'])/f'plan-proof-{decimal_pending}.json').write_text(json.dumps(d,ensure_ascii=False,indent=2))

@pytest.mark.parametrize('stage',['after_preparation','receipt_audit'])
async def test_gagal_menggulung_persiapan_dan_retry_satu_commit(pg,spill,monkeypatch,stage):
    from app.services import kiriman_samping_silo as ks
    key=uuid4().hex;isian=dict(jasa_id=None,nama_silo='C',berat_kg=1350)
    before=await sidik(pg)
    async def fail(db,*a,**k):
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='broken_catat_otomatis',ActivityLog.field_name=='persiapan_silo'))==2
        expected=0 if stage=='after_preparation' else 1350
        assert float(await db.scalar(select(func.coalesce(func.sum(BrokenKeSilo.berat_kg),0))))==expected
        raise RuntimeError('Kegagalan sintetis sesudah pembukuan')
    async with pg() as db:
        user=await db.get(User,spill['user']);native_commit=db.commit;commits=[]
        async def count_commit():commits.append(1);await native_commit()
        monkeypatch.setattr(db,'commit',count_commit)
        with monkeypatch.context() as patch:
            patch.setattr(g2 if stage=='after_preparation' else ks.buku,'masukkan_broken_ke_silo' if stage=='after_preparation' else 'catat',fail)
            with pytest.raises(RuntimeError,match='Kegagalan sintetis'):
                await ks.simpan(db,user=user,kunci=key,aksi='broken-pemilik',isian=isian,
                    kerjakan=lambda:g2.masukkan_stok_broken_pemilik_ke_silo(db,user=user,**isian,commit=False))
        assert commits==[]
        await native_commit() # caller boleh commit; potongan savepoint tetap batal
    assert await sidik(pg)==before
    async with pg() as db:
        user=await db.get(User,spill['user']);native_commit=db.commit;commits=[]
        async def count_retry_commit():commits.append(1);await native_commit()
        monkeypatch.setattr(db,'commit',count_retry_commit)
        a=await ks.simpan(db,user=user,kunci=key,aksi='broken-pemilik',isian=isian,
            kerjakan=lambda:g2.masukkan_stok_broken_pemilik_ke_silo(db,user=user,**isian,commit=False))
        assert commits==[1]
        after=await sidik(pg)
        b=await ks.simpan(db,user=user,kunci=key,aksi='broken-pemilik',isian=isian,
            kerjakan=lambda:g2.masukkan_stok_broken_pemilik_ke_silo(db,user=user,**isian,commit=False))
        assert b==a and commits==[1] and await sidik(pg)==after

async def test_pending_berubah_sebelum_simpan_tidak_menulis_persiapan(pg,spill):
    async with await _klien(pg,spill['user'],'broken-spill-stale') as c:
        initial=(await c.get('/api/actions/rincian-broken-silo',params=dict(proses='pemilik|pabrik',berat_kg=1350,silo='C'))).json()
        assert initial['saldo']['total']==1900
        await pesan(pg,spill,1000)
        before=await sidik(pg)
        r=await c.post('/api/actions/masukkan-broken-silo',json=dict(proses='pemilik|pabrik',silo='C',berat_kg=1350,kunci_kiriman=uuid4().hex),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==400 and '900' in r.text and 'Transaksi ini tidak tersimpan' in r.text,r.text
        assert await sidik(pg)==before
        d=(await c.get('/api/actions/rincian-broken-silo',params=dict(proses='pemilik|pabrik',berat_kg=1350,silo='C'))).json()
        assert d['saldo']['total']==900 and d['rencana'] is None

async def test_lokasi_dan_hak_lain_tidak_menutup_defisit(pg,spill):
    from app.models import Warehouse,Jasa
    from tests.pg.kontak import pelanggan_kledo
    from app.database import now_local
    async with pg() as db:
        other=Warehouse(nama_gudang='Pembanding persiapan');db.add(other)
        customer=pelanggan_kledo(nama_pelanggan='Titipan persiapan');db.add(customer);await db.flush()
        jasa=Jasa(kode='JAS-PREP-OTHER',pelanggan_id=customer.id);db.add(jasa);await db.flush()
        for wid,owner in [(other.id,None),(spill['warehouse'],jasa.id)]:
            db.add(ByproductStock(jenis_produk='broken',source_type='timbangan',source_id=999,warehouse_id=wid,jasa_id=owner,berat_kg=9000,tanggal=now_local().date(),waktu=now_local(),input_by=spill['user']))
        await db.commit()
        d=await rincian(db,'pemilik|pabrik',1350,'C')
        assert d['saldo']['total']==1900 and d['rencana']['pembukuan_kg']==350
        assert {x['proc_id'] for x in d['rencana']['pembukuan_sumber']}=={spill['proc_id'],spill['proc_2150']}

async def test_perintah_kemasan_campuran_ditahan_tanpa_membuka_karung(pg,spill):
    from tests.pg.test_masukkan_broken_silo import _kemas
    await _kemas(pg,spill,jumlah_karung=1)
    async with pg() as db:
        sku=await db.scalar(select(FinishedGoodsStock));rec=await db.get(OutgoingRecord,spill['order'])
        await buat_perintah(db,user=await db.get(User,spill['user']),pelanggan_id=rec.pelanggan_id,
            baris=[BarisPerintah(tipe='finished_goods',sku_id=sku.product_sku_id,std_id=sku.rice_quality_standard_id,jumlah_karung=1)],no_polisi='AD 3456 XY')
    async with await _klien(pg,spill['user'],'broken-spill-pack-held') as c:
        before=await sidik(pg)
        r=await c.post('/api/actions/masukkan-broken-silo',json=dict(proses='pemilik|pabrik',silo='C',berat_kg=1350,kunci_kiriman=uuid4().hex),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==400 and 'perintah kemasan' in r.text,r.text
        assert await sidik(pg)==before

async def test_sumber_legacy_tidak_meminjam_hasil_proses_lain(pg,spill):
    async with await _klien(pg,spill['user'],'broken-spill-legacy') as c:
        d=(await c.get('/api/actions/rincian-broken-silo',params=dict(proses='POL-BF-2150|',berat_kg=1350,silo='C'))).json()
        assert d['saldo']['total']==1800
        assert [(x['proc_id'],x['kg']) for x in d['rencana']['pembukuan_sumber']]==[(spill['proc_2150'],350)]
        r=await c.post('/api/actions/masukkan-broken-silo',json=dict(proses='POL-BF-2150|',silo='C',berat_kg=1350,kunci_kiriman=uuid4().hex),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200,r.text
    async with pg() as db:
        assert await db.scalar(select(func.sum(ByproductStock.berat_kg)).where(ByproductStock.source_type=='polishing',ByproductStock.source_id==spill['proc_id'])) is None
        assert await g2.hitung_stok_silo(db,spill['silo']['C'])==1350


async def test_raw_tidak_cukup_tidak_membuka_karung_untuk_menutup_defisit(pg,spill):
    from tests.pg.test_masukkan_broken_silo import _kemas
    await _kemas(pg,spill,jumlah_karung=1)
    await _kemas(pg,{**spill,'kode_pol':'POL-BF-2150'},jumlah_karung=40)
    # Curah1150 + kemasan2050 + raw200 tetap3400; pending1500.
    # Defisit350 tidak boleh diam-diam ditutup dengan membongkar kemasan.
    async with await _klien(pg,spill['user'],'broken-spill-pack-scope') as c:
        before=await sidik(pg)
        choices=await c.get('/api/actions/broken-proses-tersedia')
        assert choices.status_code==200,choices.text
        option=next(x for x in choices.json() if x['value']=='pemilik|pabrik')
        assert option['disabled'] and 'Admin perlu meninjau' in option['label']
        for method,path,payload in [
            ('GET','/api/actions/rincian-broken-silo',dict(proses='pemilik|pabrik',berat_kg=1350,silo='C')),
            ('POST','/api/actions/masukkan-broken-silo',dict(proses='pemilik|pabrik',berat_kg=1350,silo='C',kunci_kiriman=uuid4().hex))]:
            response=await c.request(method,path,**({'params':payload} if method=='GET' else {'json':payload,'headers':{'X-CSRF-Token':cap_formulir(c)}}))
            assert response.status_code==400 and 'Admin perlu meninjau' in response.text,response.text
            assert await sidik(pg)==before
