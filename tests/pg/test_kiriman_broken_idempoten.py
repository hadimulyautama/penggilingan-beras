"""Satu kunci yang sama harus menghasilkan satu pemindahan walau dikirim ulang."""
from uuid import uuid4
import pytest
from sqlalchemy import select,func
from app.models import BrokenKeSilo,HasilSampingKeSilo
from tests.pg.test_form_broken_silo import sosoh
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir

async def test_broken_kunci_sama_hanya_satu_pemindahan(pg,sosoh):
    async with await _klien(pg,sosoh['user'],'broken-kunci',mode='admin') as c:
        body=dict(proses='pemilik|pabrik',silo='C',berat_kg=75,kunci_kiriman=uuid4().hex)
        for _ in range(2):
            r=await c.post('/api/actions/masukkan-broken-silo',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
            assert r.status_code==200,r.text
    async with pg() as db:assert await db.scalar(select(func.sum(BrokenKeSilo.berat_kg)))==75


@pytest.mark.parametrize('kunci',[None,'pendek'])
async def test_broken_tanpa_kunci_ditolak(pg,sosoh,kunci):
    async with await _klien(pg,sosoh['user'],'broken-tanpa-kunci',mode='admin') as c:
        body=dict(proses='pemilik|pabrik',silo='C',berat_kg=75,kunci_kiriman=kunci)
        r=await c.post('/api/actions/masukkan-broken-silo',json=body,headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==400 and 'Kunci kiriman' in r.text,r.text
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(BrokenKeSilo))==0

async def test_endpoint_lama_curah_juga_idempoten_dan_tanpa_kunci_ditolak(pg,sosoh):
    from app.models import User,ByproductStock
    from app.penggilingan.inventory.finished_goods import catat_broken
    async with pg() as db:
        await catat_broken(db,user=await db.get(User,sosoh['user']),kode_pol=sosoh['kode_pol'],berat_kg=80)
        row=await db.scalar(select(ByproductStock))
        rid=row.id
    async with await _klien(pg,sosoh['user'],'broken-endpoint-lama',mode='admin') as c:
        payload=dict(broken=str(rid),silo='C')
        r=await c.post('/api/actions/pindah-broken-silo',json=payload,headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==400 and 'Kunci kiriman' in r.text,r.text
        payload['kunci_kiriman']=uuid4().hex
        hasil=[]
        for _ in range(2):
            r=await c.post('/api/actions/pindah-broken-silo',json=payload,headers={'X-CSRF-Token':cap_formulir(c)})
            assert r.status_code==200,r.text
            hasil.append(r.json())
        assert hasil[0]==hasil[1]
    async with pg() as db:assert await db.scalar(select(func.sum(BrokenKeSilo.berat_kg)))==80

async def test_tanda_terima_gagal_membatalkan_bongkar_karung_dan_bahan_proses(pg,sosoh,monkeypatch):
    from app.models import User,FinishedGoodsStock,ByproductStock,BrokenKarungDibongkar,PolishingProcess,PolishingSiloUsage,ActivityLog
    from app.database import now_local
    from app.penggilingan.gudang2 import service as g2
    from app.services import kiriman_samping_silo as ks
    from tests.pg.test_masukkan_broken_silo import _kemas
    from tests.pg.test_form_broken_silo import hasil
    await hasil(pg,sosoh,500)
    await _kemas(pg,sosoh,jumlah_karung=10)
    async with pg() as db:
        proc=PolishingProcess(kode_proses='POL-UJI-TANDA-TERIMA',status='proses',waktu_mulai=now_local(),created_by=sosoh['user'])
        db.add(proc);await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=proc.id,silo_id=sosoh['silo']['C'],berat_awal_kg=100))
        await db.commit()
        pid=proc.id
    async def gagal(*args,**kwargs):raise RuntimeError('tanda terima gagal')
    monkeypatch.setattr(ks.buku,'catat',gagal)
    async with pg() as db:
        u=await db.get(User,sosoh['user'])
        isian=dict(jasa_id=None,nama_silo='C',berat_kg=175)
        with pytest.raises(RuntimeError,match='tanda terima gagal'):
            await ks.simpan(db,user=u,kunci=uuid4().hex,aksi='broken-pemilik',isian=isian,
                kerjakan=lambda:g2.masukkan_stok_broken_pemilik_ke_silo(db,user=u,**isian,commit=False))
        await db.commit()
        assert await db.scalar(select(func.count()).select_from(BrokenKeSilo))==0
        assert await db.scalar(select(func.count()).select_from(BrokenKarungDibongkar))==0
        assert await db.scalar(select(func.count()).select_from(ByproductStock))==0
        assert await db.scalar(select(func.sum(FinishedGoodsStock.jumlah_karung)))==10
        usage=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==pid))
        assert float(usage.berat_masuk_kg or 0)==0
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.table_name=='broken_ke_silo'))==0
