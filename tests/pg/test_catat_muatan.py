"""UI muatan baru memakai stok, konversi, token, audit, dan izin lama."""
import asyncio
import json
import re
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select, func, text
from app.models import OutgoingRecord,OutgoingItem,User,ActivityLog,ByproductStock,Warehouse
from app.database import now_local
from app.services import barang_keluar as bk
from app.web import muatan as layar
from app.web.aksi_inventory import MuatBarisReq,MuatReq,act_muat_barang,act_muat_semua
from tests.pg.test_barang_keluar import gudang,_stok,_klien
from tests.pg.test_kiriman_pelanggan import _data,_buat,_tiket_armada

pytestmark=pytest.mark.asyncio

async def _u(pg,g,key='op'):
    async with pg() as db:return await db.get(User,g[key])

async def _setup(pg,g):
    return await _buat(pg,g,await _data(pg,g,(40,30)))

async def _body(pg,r,i=0,n=30):
    async with pg() as db:
        rec=await db.get(OutgoingRecord,r.rec.id)
        snap=await bk.ringkasan_muat(db,rec)
        return dict(perintah=str(rec.id),baris=str(r.baris[i].id),jumlah=n,dasar=snap['dasar'],
            pelanggan_id=rec.pelanggan_id,kiriman_id=rec.kiriman_id)

async def _preview(pg,g,body,semua=False):
    return await layar.periksa(layar.PeriksaMuatReq(**body,semua=semua),await _u(pg,g))

async def test_papan_pelanggan_sama_barang_tidak_tertukar_dan_total_kg(pg,gudang):
    rs=await _setup(pg,gudang)
    async with pg() as db:
        awal=await layar.papan(db,rs[0].rec.id)
    k=awal['kiriman'][0]
    assert len(k['pelanggan'])==2
    assert [p['nama'] for p in k['pelanggan']]==['Penerima A','Penerima B']
    assert k['total_perintah_kg']==1850 and k['total_dimuat_kg']==0
    assert [p['total_perintah_kg'] for p in k['pelanggan']]==[1050,800]
    for p,r in zip(k['pelanggan'],rs):
        assert p['id']==r.rec.id and p['pelanggan_id']==r.rec.pelanggan_id
        assert {i['id'] for i in p['barang']}=={i.id for i in r.baris}
        assert all(i['satuan']=='karung' and i['kg_per_unit']==25 for i in p['barang'])
    assert await _stok(pg,gudang)==10000

async def test_20_ke30_total_sama_dan_koreksi_penurunan_memakai_selisih(pg,gudang):
    rs=await _setup(pg,gudang);u=await _u(pg,gudang)
    async with pg() as db:await bk.catat_muatan(db,user=u,item_id=rs[0].baris[0].id,jumlah_karung=20)
    assert await _stok(pg,gudang)==9500
    body=await _body(pg,rs[0],n=30);plan=await _preview(pg,gudang,body)
    d=plan['baris'][0];assert (d['sebelumnya'],d['jumlah'],d['selisih'],d['selisih_kg'])==(20,30,10,250)
    assert plan['total_armada_sesudah_kg']==750
    await act_muat_barang(MuatBarisReq(**body),u);assert await _stok(pg,gudang)==9250
    await act_muat_barang(MuatBarisReq(**await _body(pg,rs[0],n=30)),u)
    assert await _stok(pg,gudang)==9250
    body=await _body(pg,rs[0],n=20);plan=await _preview(pg,gudang,body)
    assert plan['baris'][0]['selisih_kg']==-250
    await act_muat_barang(MuatBarisReq(**body),u);assert await _stok(pg,gudang)==9500
    async with pg() as db:
        assert (await db.get(OutgoingRecord,rs[0].rec.id)).status=='perintah'
        assert (await db.get(OutgoingRecord,rs[1].rec.id)).status=='perintah'
        assert (await db.get(OutgoingItem,rs[1].baris[0].id)).berat_kg==0
        logs=(await db.scalars(select(ActivityLog).where(ActivityLog.aksi=='barang_keluar_muat_baris').order_by(ActivityLog.id))).all()
        assert logs[-1].old_value.startswith('750.00|30')
        await bk.balik_muat_baris(db,rec_id=rs[0].rec.id,item_id=rs[0].baris[0].id,berat_lama=750,karung_lama=30);await db.commit()
    assert await _stok(pg,gudang)==9250

async def test_muat_semua_parsial_hanya_pelanggan_dipilih(pg,gudang):
    rs=await _setup(pg,gudang);u=await _u(pg,gudang)
    async with pg() as db:await bk.catat_muatan(db,user=u,item_id=rs[0].baris[0].id,jumlah_karung=20)
    body=await _body(pg,rs[0]);plan=await _preview(pg,gudang,body,True)
    assert len(plan['baris'])==2 and plan['selisih_kg']==550
    await act_muat_semua(MuatReq(**body),u)
    assert await _stok(pg,gudang)==8950
    async with pg() as db:
        assert (await db.get(OutgoingRecord,rs[0].rec.id)).status=='dimuat'
        assert (await db.get(OutgoingRecord,rs[1].rec.id)).status=='perintah'
        assert (await db.get(OutgoingItem,rs[1].baris[0].id)).berat_kg==0
        k=(await layar.papan(db,rs[1].rec.id))['kiriman'][0]
        assert k['status']=='Sedang dimuat' and k['total_dimuat_kg']==1050

@pytest.mark.parametrize('ubah',['pelanggan_lain','perintah','armada','stok','penerima','tiket','status'])
async def test_token_kedaluwarsa_ditolak_tanpa_mengubah_isian_atau_stok(pg,gudang,ubah):
    rs=await _setup(pg,gudang);u=await _u(pg,gudang)
    tid=await _tiket_armada(pg,gudang,rs,1850) if ubah=='tiket' else None
    body=await _body(pg,rs[0]);await _preview(pg,gudang,body)
    async with pg() as db:
        if ubah=='pelanggan_lain':await bk.catat_muatan(db,user=u,item_id=rs[1].baris[0].id,jumlah_karung=1)
        elif ubah=='perintah':await bk.ubah_baris_perintah(db,user=await db.get(User,gudang['adm']),rec_id=rs[0].rec.id,item_id=rs[0].baris[0].id,jumlah=39,dasar=body['dasar'],alasan='Ubah target')
        elif ubah=='armada':await bk.koreksi_plat(db,user=await db.get(User,gudang['adm']),rec_id=rs[0].rec.id,no_polisi='AD 4455 ZZ',alasan='Armada berubah')
        elif ubah=='stok':
            from app.models import FinishedGoodsStock
            stok=await db.scalar(select(FinishedGoodsStock));stok.jumlah_karung=399;stok.berat_total_kg=9975;await db.commit()
        elif ubah=='penerima':
            rec=await db.get(OutgoingRecord,rs[0].rec.id);rec.nama_pembeli='Nama cuplikan dikoreksi';await db.commit()
        elif ubah=='status':await bk.muat_semua(db,user=u,rec_id=rs[0].rec.id)
        elif ubah=='tiket':
            await db.execute(text("UPDATE timbangan_transaksi SET status_tiket='TERBUKA' WHERE id=:id"),{'id':tid});await db.commit()
    stok=await _stok(pg,gudang)
    async with pg() as db:aktual=(await db.get(OutgoingItem,rs[0].baris[0].id)).berat_kg
    if ubah=='status':
        with pytest.raises(HTTPException) as e:await _preview(pg,gudang,body)
        assert e.value.status_code==409
    with pytest.raises(HTTPException) as e:await act_muat_barang(MuatBarisReq(**body),u)
    assert e.value.status_code==409
    assert await _stok(pg,gudang)==stok
    async with pg() as db:assert (await db.get(OutgoingItem,rs[0].baris[0].id)).berat_kg==aktual

@pytest.mark.parametrize('cacat',['item','pelanggan','kiriman','pecahan','nol','lebih_perintah','nonfinite'])
async def test_konteks_dan_jumlah_server_tidak_mempercayai_browser(pg,gudang,cacat):
    rs=await _setup(pg,gudang);body=await _body(pg,rs[0]);u=await _u(pg,gudang)
    if cacat=='item':body['baris']=str(rs[1].baris[0].id)
    elif cacat=='pelanggan':body['pelanggan_id']=rs[1].rec.pelanggan_id
    elif cacat=='kiriman':body['kiriman_id']+=99
    elif cacat=='pecahan':body['jumlah']=1.5
    elif cacat=='nol':body['jumlah']=0
    elif cacat=='lebih_perintah':body['jumlah']=41
    else:body['jumlah']=float('nan')
    with pytest.raises(HTTPException):await act_muat_barang(MuatBarisReq(**body),u)
    assert await _stok(pg,gudang)==10000

async def test_stok_kurang_dan_muat_semua_tidak_menyimpan_sebagian(pg,gudang,monkeypatch):
    rs=await _setup(pg,gudang);u=await _u(pg,gudang)
    async with pg() as db:
        from app.models import FinishedGoodsStock
        stok=await db.scalar(select(FinishedGoodsStock));stok.jumlah_karung=41;stok.berat_total_kg=1025;await db.commit()
        with pytest.raises(bk.BarangKeluarError,match='tinggal'):
            await bk.muat_semua(db,user=u,rec_id=rs[0].rec.id)
        await db.commit()
    async with pg() as db:
        assert all(i.berat_kg==0 for i in (await db.scalars(select(OutgoingItem))).all())
        assert (await db.get(OutgoingRecord,rs[0].rec.id)).status=='perintah'
    assert await _stok(pg,gudang)==1025

async def test_gagal_audit_muat_semua_rollback_seluruh_item(pg,gudang,monkeypatch):
    rs=await _setup(pg,gudang);u=await _u(pg,gudang)
    async def gagal(*args,**kw):raise RuntimeError('Audit tidak tersedia')
    monkeypatch.setattr(bk,'_jejak',gagal)
    async with pg() as db:
        with pytest.raises(RuntimeError):await bk.muat_semua(db,user=u,rec_id=rs[0].rec.id)
        await db.commit()
    async with pg() as db:
        assert all(i.berat_kg==0 for i in (await db.scalars(select(OutgoingItem))).all())
        assert (await db.get(OutgoingRecord,rs[0].rec.id)).status=='perintah'
    assert await _stok(pg,gudang)==10000

async def test_muat_semua_tidak_menurunkan_aktual_melebihi_perintah(pg,gudang):
    rs=await _setup(pg,gudang)
    async with pg() as db:
        it=await db.get(OutgoingItem,rs[0].baris[0].id);it.berat_kg=1100;it.jumlah_karung=44;await db.commit()
    body=await _body(pg,rs[0]);u=await _u(pg,gudang)
    with pytest.raises(HTTPException):await _preview(pg,gudang,body,True)
    with pytest.raises(HTTPException):await act_muat_semua(MuatReq(**body),u)
    assert await _stok(pg,gudang)==8900

async def test_dua_pencatatan_bersamaan_memakai_token_yang_sama_hanya_satu_lolos(pg,gudang):
    rs=await _setup(pg,gudang);body=await _body(pg,rs[0]);u=await _u(pg,gudang)
    a,b=await asyncio.gather(act_muat_barang(MuatBarisReq(**body),u),act_muat_barang(MuatBarisReq(**body),u),return_exceptions=True)
    assert sum(isinstance(x,HTTPException) and x.status_code==409 for x in (a,b))==1
    assert await _stok(pg,gudang)==9250

async def test_kg_presisi_dan_kepemilikan_jasa_tetap_lewat_layanan_lama(pg,gudang):
    from app.models import Jasa,FinishedGoodsStock
    data=await _data(pg,gudang,(40,30))
    async with pg() as db:
        now=now_local();db.add(ByproductStock(jenis_produk='bekatul',source_type='retur',berat_kg=1000,tanggal=now.date(),waktu=now,input_by=gudang['op']))
        await db.commit()
    data['kelompok'][0]['barang'][1]={'pilih':'cr:bekatul','jumlah':'200'}
    rs=await _buat(pg,gudang,data);u=await _u(pg,gudang)
    body=await _body(pg,rs[0],1,125.25);plan=await _preview(pg,gudang,body)
    assert plan['baris'][0]['satuan']=='kg' and plan['selisih_kg']==125.25
    await act_muat_barang(MuatBarisReq(**body),u)
    async with pg() as db:assert (await db.get(OutgoingItem,rs[0].baris[1].id)).berat_kg==Decimal('125.25')
    # Barang titipan tetap mengurangi saldo pesanan yang sama, bukan pabrik.
    async with pg() as db:
        j=Jasa(kode='JAS-MUAT-UJI',pelanggan_id=rs[0].rec.pelanggan_id,status='berjalan');db.add(j);await db.flush()
        db.add(FinishedGoodsStock(product_sku_id=gudang['sku'],rice_quality_standard_id=gudang['std'],source_type='retur',jumlah_karung=10,berat_total_kg=250,input_by=gudang['op'],waktu=now_local(),jasa_id=j.id))
        await db.commit()
        r=await bk.buat_perintah(db,user=await db.get(User,gudang['adm']),jasa_id=j.id,baris=[bk.BarisPerintah(tipe='finished_goods',sku_id=gudang['sku'],std_id=gudang['std'],jumlah_karung=5)])
    body=await _body(pg,r,0,3);plan=await _preview(pg,gudang,body)
    assert plan['pelanggan_id']==rs[0].rec.pelanggan_id
    await act_muat_barang(MuatBarisReq(**body),u)
    assert await _stok(pg,gudang)==10000

async def test_http_formulir_endpoint_dan_peran_g1_g2_tetap_saling_menggantikan(pg,gudang):
    rs=await _setup(pg,gudang)
    c=await _klien(pg,gudang['op'],'muat-lintas')
    async with c:
        for gid in ('g1','g2'):
            async with pg() as db:
                wid=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi==gid))
                op=await db.get(User,gudang['op']);op.default_warehouse_id=wid;await db.commit()
            page=await c.get(f'/muatan?perintah={rs[0].rec.id}');assert page.status_code==200,page.text
            assert 'data-catat-muatan' in page.text and 'data-boleh="1"' in page.text
            token=re.search(r'name="formulir-sesi" content="([^\"]+)"',page.text).group(1)
            if gid=='g2':
                detail=await c.get(f'/barang-keluar/{rs[0].rec.id}')
                assert detail.status_code==200,detail.text
                assert f'/muatan?perintah={rs[0].rec.id}&amp;item={rs[0].baris[0].id}' in detail.text
                assert 'Penerima A' in detail.text and 'Penerima B' in detail.text
            body=await _body(pg,rs[0],n=2)
            preview=await c.post('/api/actions/periksa-catat-muatan',json=body,headers={'X-CSRF-Token':token})
            assert preview.status_code==200,preview.text
            fail=await c.post('/api/actions/muat-barang',json=body);assert fail.status_code==403
            ok=await c.post('/api/actions/muat-barang',json=body,headers={'X-CSRF-Token':token})
            assert ok.status_code==200,ok.text
    assert await _stok(pg,gudang)==9950
    async with pg() as db:
        op=await db.get(User,gudang['op']);op.default_warehouse_id=None;await db.commit()
    u=await _u(pg,gudang)
    with pytest.raises(HTTPException):await layar.periksa(layar.PeriksaMuatReq(**await _body(pg,rs[0])),u)
