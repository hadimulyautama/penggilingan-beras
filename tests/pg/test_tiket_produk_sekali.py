"""Penerimaan satu kali tetap berlaku setelah baris stok habis atau hilang."""
import asyncio
import pytest
from sqlalchemy import select,text,func,delete
from app.models import ActivityLog,FinishedGoodsStock,ByproductStock,Jasa,User,Pelanggan
from app.web import api
from app.penggilingan.gudang1.services import timbang_link
from tests.pg.test_masukkan_beras_silo import sosoh
from tests.pg.test_tiket_antrean_produksi import _tiket
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir

pytestmark=pytest.mark.asyncio
POST='/api/actions/catat-produk-timbang-masuk'

async def tiket(pg,kind='BERAS_MASUK',*,kode='MSK-SEKALI-01',jasa=False):
    async with pg() as db:
        tid=await _tiket(db,kode,kind)
        values={'id':tid}
        extra=''
        if jasa:
            p=Pelanggan(nama_pelanggan='Pemilik tiket satu kali');db.add(p);await db.flush()
            extra=',jasa=true,pelanggan_id=:pid';values['pid']=p.id
        await db.execute(text('UPDATE timbangan_transaksi SET netto_timbangan_kg=1000,berat_barang_kg=998'+extra+' WHERE id=:id'),values)
        await db.commit()
        return tid

async def masuk(c,tid):
    return await c.post(POST,json={'timbangan_transaksi_id':tid},headers={'X-CSRF-Token':cap_formulir(c)})

async def hilangkan_stok(pg,tid,kind):
    model=FinishedGoodsStock if kind=='BERAS_MASUK' else ByproductStock
    async with pg() as db:
        await db.execute(delete(model).where(model.source_type=='timbangan',model.source_id==tid));await db.commit()

async def tertolak(c,tid,kind):
    r=await masuk(c,tid)
    assert r.status_code==409,r.text
    assert 'sudah pernah diterima' in r.text and 'tidak dapat dicatat ulang' in r.text
    opts=(await c.get('/api/actions/produk-timbang-masuk-aktif',params={'jenis':kind})).json()
    assert tid not in [o['value'] for o in opts]
    detail=await c.get(f'/barang-masuk/{tid}')
    assert detail.status_code==200,detail.text
    assert 'buka=catat_produk_timbang_masuk' not in detail.text

@pytest.mark.parametrize('jasa',[False,True])
async def test_998_diterima_sekali_setelah_seluruhnya_masuk_silo(pg,sosoh,jasa):
    tid=await tiket(pg,jasa=jasa)
    async with await _klien(pg,sosoh['user'],'satu-silo',mode='admin') as c:
        assert (await masuk(c,tid)).status_code==200
        async with pg() as db:
            row=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.source_id==tid))
            source=f"sku:{row.product_sku_id}|{row.jasa_id if jasa else 'pabrik'}"
            n_jasa=await db.scalar(select(func.count()).select_from(Jasa))
        r=await c.post('/api/actions/masukkan-beras-silo',json={'jenis':'medium|'+('jasa' if jasa else 'pabrik'),'sumber_stok':source,'berat_kg':998,'silo':'C'},headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200,r.text
        async with pg() as db:
            assert not await db.scalar(select(FinishedGoodsStock.id).where(FinishedGoodsStock.source_type=='timbangan',FinishedGoodsStock.source_id==tid))
        await tertolak(c,tid,'BERAS_MASUK')
        async with pg() as db:
            assert await db.scalar(select(func.count()).select_from(Jasa))==n_jasa

@pytest.mark.parametrize('kind',['BERAS_MASUK','BROKEN_MASUK'])
async def test_stok_hilang_dan_kode_tiket_diubah_tetap_terikat_id(pg,sosoh,kind):
    tid=await tiket(pg,kind)
    async with await _klien(pg,sosoh['user'],'satu-identitas',mode='admin') as c:
        assert (await masuk(c,tid)).status_code==200
        async with pg() as db:
            log=await db.scalar(select(ActivityLog).where(ActivityLog.aksi=='produk_timbang_masuk'))
            assert log.field_name=='timbangan_transaksi_id' and log.old_value==str(tid)
            await db.execute(text("UPDATE timbangan_transaksi SET kode='MSK-KODE-DIKOREKSI' WHERE id=:id"),{'id':tid});await db.commit()
        await hilangkan_stok(pg,tid,kind)
        await tertolak(c,tid,kind)

@pytest.mark.parametrize('kind',['BERAS_MASUK','BROKEN_MASUK'])
@pytest.mark.parametrize('batal',[False,True])
async def test_riwayat_lama_tidak_memakai_nomor_record_sebagai_identitas(pg,sosoh,kind,batal):
    from app.database import now_local
    tid=await tiket(pg,kind,kode='MSK-SEKALI-1')
    async with await _klien(pg,sosoh['user'],'satu-lama',mode='admin') as c:
        assert (await masuk(c,tid)).status_code==200
        async with pg() as db:
            log=await db.scalar(select(ActivityLog).where(ActivityLog.aksi=='produk_timbang_masuk'))
            # Format sebelum perbaikan: hanya teks kode tiket, tanpa ID.
            log.aksi=None;log.field_name=None;log.old_value=None
            if batal:log.dibatalkan_pada=now_local()
            # Nomor record audit bukan otoritas identitas tiket.
            log.record_id=99999;await db.commit()
        await hilangkan_stok(pg,tid,kind)
        await tertolak(c,tid,kind)
        baru=await tiket(pg,kind,kode='MSK-SEKALI-10')
        assert (await masuk(c,baru)).status_code==200

async def test_jejak_silo_lama_tanpa_audit_penerimaan_tetap_menolak(pg,sosoh):
    from app.models import BerasKeSilo
    from app.database import now_local
    tid=await tiket(pg)
    async with pg() as db:
        db.add(BerasKeSilo(kode_pindah='BRS-LAMA-SEKALI',source_type='timbangan',source_id=tid,jenis='medium',silo_id=sosoh['silo_beras'],berat_kg=998,tanggal=now_local().date(),waktu=now_local(),input_by=sosoh['user']))
        await db.commit()
    async with await _klien(pg,sosoh['user'],'satu-bukti-silo',mode='admin') as c:
        await tertolak(c,tid,'BERAS_MASUK')

@pytest.mark.parametrize('kind',['BERAS_MASUK','BROKEN_MASUK'])
async def test_saldo_nol_tidak_dianggap_penerimaan_baru(pg,sosoh,kind):
    tid=await tiket(pg,kind)
    model=FinishedGoodsStock if kind=='BERAS_MASUK' else ByproductStock
    async with await _klien(pg,sosoh['user'],'satu-nol',mode='admin') as c:
        assert (await masuk(c,tid)).status_code==200
        async with pg() as db:
            row=await db.scalar(select(model).where(model.source_type=='timbangan',model.source_id==tid))
            if kind=='BERAS_MASUK':row.jumlah_karung=0;row.berat_total_kg=0
            else:row.berat_kg=0
            await db.commit()
        await tertolak(c,tid,kind)

@pytest.mark.parametrize('kind',['BERAS_MASUK','BROKEN_MASUK'])
async def test_dua_operator_menerima_satu_tiket_hanya_sekali(pg,sosoh,kind):
    tid=await tiket(pg,kind,jasa=True)
    async with pg() as db:
        pertama=await db.get(User,sosoh['user'])
        kedua=User(nama='Penerima kedua',role=pertama.role,status='aktif',
                   default_warehouse_id=pertama.default_warehouse_id)
        db.add(kedua);await db.commit();uid_kedua=kedua.id
    async with await _klien(pg,sosoh['user'],'satu-balapan-a',mode='admin') as a:
        async with await _klien(pg,uid_kedua,'satu-balapan-b',mode='admin') as b:
            responses=await asyncio.gather(masuk(a,tid),masuk(b,tid))
    assert sorted(r.status_code for r in responses)==[200,409]
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='produk_timbang_masuk',ActivityLog.old_value==str(tid)))==1
        assert await db.scalar(select(func.count()).select_from(Jasa))==1

async def test_audit_gagal_membatalkan_stok_dan_pesanan_lalu_boleh_dicoba_ulang(pg,sosoh,monkeypatch):
    from app.services import activity_log
    tid=await tiket(pg,jasa=True)
    async def gagal(*a,**kw):raise RuntimeError('audit penerimaan gagal')
    async with pg() as db:user=await db.get(User,sosoh['user'])
    with monkeypatch.context() as m:
        m.setattr(activity_log,'log_activity',gagal)
        with pytest.raises(RuntimeError,match='audit penerimaan gagal'):
            await api.act_catat_produk_timbang_masuk(api.CatatProdukTimbangMasukReq(timbangan_transaksi_id=tid),user=user)
    async with pg() as db:
        assert not await db.scalar(select(FinishedGoodsStock.id).where(FinishedGoodsStock.source_id==tid))
        assert await db.scalar(select(func.count()).select_from(Jasa))==0
    async with await _klien(pg,sosoh['user'],'satu-ulang-gagal',mode='admin') as c:
        assert (await masuk(c,tid)).status_code==200

async def test_penjaga_bersama_menolak_meski_jenis_tiket_diubah(pg,sosoh):
    tid=await tiket(pg)
    async with await _klien(pg,sosoh['user'],'satu-lintas-jenis',mode='admin') as c:
        assert (await masuk(c,tid)).status_code==200
        await hilangkan_stok(pg,tid,'BERAS_MASUK')
        async with pg() as db:
            await db.execute(text("UPDATE timbangan_transaksi SET jenis_kode='BERAS_PK' WHERE id=:id"),{'id':tid});await db.commit()
        async with pg() as db:
            with pytest.raises(timbang_link.TiketSudahDipakai,match='sudah pernah diterima'):
                await timbang_link.kunci_tiket_untuk_ditaut(db,tid)
