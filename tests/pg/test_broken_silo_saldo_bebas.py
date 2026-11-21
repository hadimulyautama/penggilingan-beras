"""Saldo satu penerimaan tidak sama dengan agregat; satu kiriman tetap atomik."""
from uuid import uuid4
from datetime import timedelta
import hashlib,json
import pytest
import pytest_asyncio
from sqlalchemy import select,func,text
from app.database import now_local
from app.models import User,ByproductStock,PolishingProcess,PolishingOutputLog,BrokenKeSilo,Peristiwa,Warehouse,Jasa
from app.services.rencana_broken_silo import rincian
from app.penggilingan.gudang2 import service as g2
from tests.pg.test_form_broken_silo import sosoh,hasil
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir
from tests.pg.kontak import pelanggan_kledo

pytestmark=pytest.mark.asyncio

async def sidik(pg):
    async with pg() as db:
        names=(await db.scalars(text("SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY tablename"))).all();out={}
        for n in names:
            q='"'+n.replace('"','""')+'"';rows=(await db.scalars(text('SELECT row_to_json(x)::text FROM '+q+' x ORDER BY row_to_json(x)::text'))).all()
            out[n]=hashlib.sha256(json.dumps(rows).encode()).hexdigest()
        return out

@pytest_asyncio.fixture
async def foto(pg,sosoh):
    await hasil(pg,sosoh,100)
    from app.services.barang_keluar import buat_perintah,BarisPerintah
    async with pg() as db:
        u=await db.get(User,sosoh['user']);wid=u.default_warehouse_id
        receipt=ByproductStock(jenis_produk='broken',source_type='timbangan',source_id=123,
            warehouse_id=wid,berat_kg=1150,tanggal=now_local().date(),waktu=now_local()-timedelta(days=1),input_by=u.id)
        db.add(receipt)
        p=PolishingProcess(kode_proses='POL-BF-2150',status='selesai',
            waktu_mulai=now_local(),waktu_selesai=now_local(),created_by=u.id)
        db.add(p);await db.flush()
        db.add(PolishingOutputLog(polishing_process_id=p.id,jenis='broken',berat_kg=2150,waktu_update=now_local(),input_by=u.id))
        customer=pelanggan_kledo(nama_pelanggan='Penerima perintah sintetis');db.add(customer);await db.commit()
        rid,pid,customer_id=receipt.id,p.id,customer.id
        # Perintah500 menahan fisik yang masih tercatat1150; bukan foto transaksi nyata.
        order=await buat_perintah(db,user=u,pelanggan_id=customer_id,
            baris=[BarisPerintah(tipe='byproduct_curah',jenis='broken',berat_kg=500)],no_polisi='AD 1234 XY')
        order_id=order.rec.id
    return {**sosoh,'receipt':rid,'proc_2150':pid,'warehouse':wid,'order':order_id}

async def test_rencana_650_bukan_1150_dan_simpan_lintas_sumber_replay(pg,foto):
    from app.services.saldo_broken_silo import curah_bebas
    async with pg() as db:
        row=await db.get(ByproductStock,foto['receipt'])
        assert await g2._sisa_broken_row(db,row.id)==1150
        assert await curah_bebas(db,row)==650
        direct,procs,left=await g2.rencana_broken_pemilik(db,jasa_id=None,berat_kg=1350)
        assert direct==[(row.id,650)] and left==0
        assert [kg for _,kg in procs]==[100,600]
        d=await rincian(db,'pemilik|pabrik',1350,'C')
        assert d['saldo']['total']==2900 and d['saldo']['curah']==650 and d['saldo']['karung']==0
        assert [x['kg'] for x in d['rencana']['urutan']]==[650,100,600]
    async with await _klien(pg,foto['user'],'broken-foto-rencana') as c:
        opts=(await c.get('/api/actions/broken-proses-tersedia')).json()
        assert len(opts)==1 and '2.900' in opts[0]['label']
        payload=dict(proses='pemilik|pabrik',silo='C',berat_kg=1350,kunci_kiriman=uuid4().hex)
        a=await c.post('/api/actions/masukkan-broken-silo',json=payload,headers={'X-CSRF-Token':cap_formulir(c)})
        assert a.status_code==200,a.text
        fp=await sidik(pg)
        b=await c.post('/api/actions/masukkan-broken-silo',json=payload,headers={'X-CSRF-Token':cap_formulir(c)})
        assert b.status_code==200 and b.json()==a.json(),b.text
        assert await sidik(pg)==fp
    async with pg() as db:
        assert await g2.hitung_stok_silo(db,foto['silo']['C'])==1350
        assert await db.scalar(select(func.sum(BrokenKeSilo.berat_kg)).where(BrokenKeSilo.byproduct_stock_id==foto['receipt']))==650
        assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis=='kiriman_hasil_samping_silo'))==1

async def test_negatif_rencana_usang_1150_tetap_ditolak_atomik(pg,foto,monkeypatch):
    original=g2.rencana_broken_pemilik
    async def usang(db,*,jasa_id,berat_kg):
        direct,procs,left=await original(db,jasa_id=jasa_id,berat_kg=berat_kg)
        if berat_kg==1350:return [(foto['receipt'],1150)],procs,0
        return direct,procs,left
    monkeypatch.setattr(g2,'rencana_broken_pemilik',usang)
    async with await _klien(pg,foto['user'],'broken-foto-negatif') as c:
        fp=await sidik(pg)
        r=await c.post('/api/actions/masukkan-broken-silo',json=dict(proses='pemilik|pabrik',silo='C',berat_kg=1350,kunci_kiriman=uuid4().hex),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==400 and '1150' in r.text and '650' in r.text,r.text
        assert 'Transaksi ini tidak tersimpan' in r.text and 'Kosongkan' not in r.text
        assert await sidik(pg)==fp

async def test_saldo_berubah_sesudah_preview_tidak_menyimpan_lagi(pg,foto):
    async with await _klien(pg,foto['user'],'broken-foto-berubah') as c:
        d=(await c.get('/api/actions/rincian-broken-silo',params=dict(proses='pemilik|pabrik',berat_kg=1350,silo='C'))).json()
        assert d['rencana']['kg']==1350
        async with pg() as db:
            await g2.masukkan_stok_broken_pemilik_ke_silo(db,user=await db.get(User,foto['user']),jasa_id=None,nama_silo='D',berat_kg=2000)
        fp=await sidik(pg)
        r=await c.post('/api/actions/masukkan-broken-silo',json=dict(proses='pemilik|pabrik',silo='C',berat_kg=1350,kunci_kiriman=uuid4().hex),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==400 and 'Transaksi ini tidak tersimpan' in r.text and '900' in r.text,r.text
        assert await sidik(pg)==fp
        d=(await c.get('/api/actions/rincian-broken-silo',params=dict(proses='pemilik|pabrik',berat_kg=1350,silo='C'))).json()
        assert d['saldo']['total']==900 and d['rencana'] is None
    async with pg() as db:assert await g2.hitung_stok_silo(db,foto['silo']['C'])==0

async def test_lokasi_dan_pemilik_lain_tidak_menambah_saldo(pg,foto):
    async with pg() as db:
        other=Warehouse(nama_gudang='Lokasi pembanding');db.add(other)
        customer=pelanggan_kledo(nama_pelanggan='Titipan pembanding');db.add(customer);await db.flush()
        owner=Jasa(kode='JAS-BROKEN-OTHER',pelanggan_id=customer.id);db.add(owner);await db.flush()
        for wid,jid in [(other.id,None),(foto['warehouse'],owner.id)]:
            db.add(ByproductStock(jenis_produk='broken',source_type='timbangan',source_id=999,warehouse_id=wid,jasa_id=jid,berat_kg=9000,tanggal=now_local().date(),waktu=now_local(),input_by=foto['user']))
        await db.commit()
        assert (await rincian(db,'pemilik|pabrik'))['saldo']['total']==2900

async def test_audit_gagal_setelah_sumber_dipakai_menggulung_semua(pg,foto,monkeypatch):
    from app.services import kiriman_samping_silo as ks
    fp=await sidik(pg)
    async def gagal(*a,**k):raise RuntimeError('Audit tanda terima sintetis gagal')
    monkeypatch.setattr(ks.buku,'catat',gagal)
    async with pg() as db:
        u=await db.get(User,foto['user']);isian=dict(jasa_id=None,nama_silo='C',berat_kg=1350)
        with pytest.raises(RuntimeError,match='Audit tanda'):
            await ks.simpan(db,user=u,kunci=uuid4().hex,aksi='broken-pemilik',isian=isian,
                kerjakan=lambda:g2.masukkan_stok_broken_pemilik_ke_silo(db,user=u,**isian,commit=False))
        await db.commit()
    assert await sidik(pg)==fp
