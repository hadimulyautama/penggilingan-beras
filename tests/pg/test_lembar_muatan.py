"""Lembar muatan bersama: transaksi nyata, snapshot, stok lama, audit dan izin."""
import asyncio
import copy
from decimal import Decimal
import pytest
from fastapi import HTTPException
from sqlalchemy import select, func
from app.models import User, OutgoingRecord, OutgoingItem, ActivityLog, FinishedGoodsStock, Warehouse
from app.services import barang_keluar as bk
from app.web import muatan as web
from app.web.selesai_muatan import papan_selesai
from tests.pg.test_barang_keluar import gudang, _stok, _klien
from tests.pg.test_kiriman_pelanggan import _data, _buat
from tests.pg.formulir import cap_formulir

pytestmark=pytest.mark.asyncio

async def setup(pg,g):
    rs=await _buat(pg,g,await _data(pg,g,(40,30)))
    async with pg() as db:u=await db.get(User,g['op'])
    return rs,u

async def body(pg,rs,qty):
    async with pg() as db:k=(await papan_selesai(db,rs[0].rec.id))['kiriman'][0]
    return dict(perintah_id=k['perintah_id'],kiriman_id=k['id'],
        konteks=[dict(perintah_id=p['id'],pelanggan_id=p['pelanggan_id'],dasar=p['dasar']) for p in k['pelanggan']],
        barang=[dict(perintah_id=r.rec.id,item_id=r.baris[idx].id,jumlah=n) for r,idx,n in qty])

async def review(b,u):return await web.periksa_lembar(web.LembarMuatReq(**b),u)
async def save(b,u,plan,close=()):
    return await web.simpan_lembar(web.LembarMuatReq(**b,pemeriksaan=plan['pemeriksaan'],selesaikan=list(close)),u)
async def audit(pg):
    async with pg() as db:return await db.scalar(select(func.count()).select_from(ActivityLog))

async def test_lembar_kumulatif_selisih_bersama_dan_audit_lama(pg,gudang):
    rs,u=await setup(pg,gudang)
    async with pg() as db:await bk.catat_muatan(db,user=u,item_id=rs[0].baris[0].id,jumlah_karung=20)
    b=await body(pg,rs,[(rs[0],0,30),(rs[1],0,10)])
    before=await audit(pg);plan=await review(b,u)
    assert await audit(pg)==before and await _stok(pg,gudang)==9500
    assert plan['rencana']['selisih_kg']==500
    s=plan['rencana']['sumber'][0]
    assert len(s['pelanggan'])==2 and (s['stok_sebelum_kg'],s['stok_sesudah_kg'])==(9500,9000)
    await save(b,u,plan)
    assert await _stok(pg,gudang)==9000
    async with pg() as db:
        for r in rs:assert (await db.get(OutgoingRecord,r.rec.id)).status=='perintah'
        logs=list((await db.scalars(select(ActivityLog).where(ActivityLog.aksi=='barang_keluar_muat_baris').order_by(ActivityLog.id))).all())
        assert len(logs)==3 and any(log.old_value=='500.00|20' for log in logs)
    same=await body(pg,rs,[(rs[0],0,30)]);plan=await review(same,u)
    assert plan['rencana']['baris']==[]
    with pytest.raises(HTTPException):await save(same,u,plan)
    assert await _stok(pg,gudang)==9000 and await audit(pg)==before+2

async def test_koreksi_turun_dahulu_membebaskan_saldo_tanpa_selisih_berulang(pg,gudang):
    rs,u=await setup(pg,gudang)
    async with pg() as db:
        await bk.catat_muatan(db,user=u,item_id=rs[0].baris[0].id,jumlah_karung=30)
        st=await db.scalar(select(FinishedGoodsStock));st.berat_total_kg=750;st.jumlah_karung=30;await db.commit()
    assert await _stok(pg,gudang)==0
    b=await body(pg,rs,[(rs[1],0,10),(rs[0],0,20)])
    plan=await review(b,u);assert plan['rencana']['baris'][0]['selisih_kg']==-250
    await save(b,u,plan);assert await _stok(pg,gudang)==0
    b=await body(pg,rs,[(rs[0],0,15)])
    await save(b,u,await review(b,u));assert await _stok(pg,gudang)==125

async def test_stok_bersama_cukup_sendiri_tidak_cukup_gabungan(pg,gudang):
    rs,u=await setup(pg,gudang)
    async with pg() as db:
        st=await db.scalar(select(FinishedGoodsStock));st.berat_total_kg=500;st.jumlah_karung=20;await db.commit()
    b=await body(pg,rs,[(rs[0],0,15),(rs[1],0,15)])
    before=await audit(pg)
    with pytest.raises(HTTPException) as e:await review(b,u)
    assert e.value.status_code==400 and await _stok(pg,gudang)==500 and await audit(pg)==before

async def test_isi_sesuai_dan_pilihan_penyelesaian_tidak_otomatis(pg,gudang):
    rs,u=await setup(pg,gudang)
    b=await body(pg,rs,[(rs[0],0,40),(rs[0],1,2)])
    p=await review(b,u);assert [x['id'] for x in p['rencana']['bisa_selesai']]==[rs[0].rec.id]
    await save(b,u,p)
    async with pg() as db:assert (await db.get(OutgoingRecord,rs[0].rec.id)).status=='perintah'
    empty=await body(pg,rs,[]);p=await review(empty,u);await save(empty,u,p,[rs[0].rec.id])
    assert await _stok(pg,gudang)==8950
    async with pg() as db:
        assert (await db.get(OutgoingRecord,rs[0].rec.id)).status=='dimuat'
        assert (await db.get(OutgoingRecord,rs[1].rec.id)).status=='perintah'
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='barang_keluar_muat'))==1

async def test_sekaligus_selesai_hanya_pilihan_dan_audit_terpisah(pg,gudang):
    rs,u=await setup(pg,gudang)
    b=await body(pg,rs,[(r,i,n) for r,n0 in zip(rs,(40,30)) for i,n in enumerate((n0,2))]);p=await review(b,u)
    await save(b,u,p,[rs[1].rec.id]);assert await _stok(pg,gudang)==8150
    async with pg() as db:
        assert (await db.get(OutgoingRecord,rs[0].rec.id)).status=='perintah'
        assert (await db.get(OutgoingRecord,rs[1].rec.id)).status=='dimuat'
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='barang_keluar_muat_baris'))==4
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.aksi=='barang_keluar_muat'))==1

@pytest.mark.parametrize('fault',['barang','penutupan'])
async def test_gagal_di_tengah_seluruh_item_dan_audit_rollback(pg,gudang,monkeypatch,fault):
    rs,u=await setup(pg,gudang)
    b=await body(pg,rs,[(rs[0],0,40),(rs[0],1,2)]);p=await review(b,u);before=await audit(pg)
    old=bk.catat_muatan;calls=0
    async def gagal(*a,**kw):
        nonlocal calls
        calls+=1
        if calls==2:raise bk.BarangKeluarError('Gagal barang kedua untuk uji atomisitas')
        return await old(*a,**kw)
    async def tutup(*a,**kw):raise bk.BarangKeluarError('Gagal penutupan untuk uji atomisitas')
    if fault=='barang':monkeypatch.setattr(bk,'catat_muatan',gagal)
    else:monkeypatch.setattr(bk,'selesai_muat',tutup)
    with pytest.raises(HTTPException):await save(b,u,p,[rs[0].rec.id] if fault=='penutupan' else [])
    assert await _stok(pg,gudang)==10000 and await audit(pg)==before
    async with pg() as db:assert await db.scalar(select(func.sum(OutgoingItem.berat_kg)))==0

@pytest.mark.parametrize('what',['stok','pelanggan_lain','armada','penerima','perintah','status'])
async def test_snapshot_usang_ditolak(pg,gudang,what):
    rs,u=await setup(pg,gudang);b=await body(pg,rs,[(rs[0],0,20)]);p=await review(b,u)
    async with pg() as db:
        if what=='stok':
            s=await db.scalar(select(FinishedGoodsStock));s.berat_total_kg=9975;s.jumlah_karung=399
        elif what=='pelanggan_lain':
            i=await db.get(OutgoingItem,rs[1].baris[0].id);i.berat_kg=25;i.jumlah_karung=1
        else:
            r=await db.get(OutgoingRecord,rs[0].rec.id)
            if what=='armada':r.no_polisi='UJI-CHANGED'
            elif what=='penerima':r.nama_pembeli='Nama berubah'
            elif what=='status':r.status='dimuat'
            else:
                i=await db.get(OutgoingItem,rs[0].baris[0].id);i.berat_perintah_kg=975;i.jumlah_karung_perintah=39
        await db.commit()
    stok=await _stok(pg,gudang);before=await audit(pg)
    with pytest.raises(HTTPException) as e:await save(b,u,p)
    assert e.value.status_code==409 and await _stok(pg,gudang)==stok and await audit(pg)==before

@pytest.mark.parametrize('what',['item_asing','penerima','konteks_kurang','ganda','karung_pecah','nol','negatif','berlebih','cap','ubah_setelah_preview','selesai_tidak_sah'])
async def test_request_langsung_dan_manipulasi_ditolak(pg,gudang,what):
    rs,u=await setup(pg,gudang);b=await body(pg,rs,[(rs[0],0,20)]);p=await review(b,u);before=await audit(pg)
    if what=='item_asing':b['barang'][0]['item_id']=rs[1].baris[0].id
    elif what=='penerima':b['konteks'][0]['pelanggan_id']=rs[1].rec.pelanggan_id
    elif what=='konteks_kurang':b['konteks'].pop()
    elif what=='ganda':b['barang']*=2
    elif what in ('karung_pecah','nol','negatif','berlebih'):b['barang'][0]['jumlah']={'karung_pecah':1.5,'nol':0,'negatif':-1,'berlebih':41}[what]
    elif what=='cap':p['pemeriksaan']='salah'
    elif what=='ubah_setelah_preview':b['barang'][0]['jumlah']=21
    with pytest.raises(HTTPException):await save(b,u,p,[rs[1].rec.id] if what=='selesai_tidak_sah' else [])
    assert await _stok(pg,gudang)==10000 and await audit(pg)==before

async def test_retry_bersamaan_dan_respons_hilang_tidak_mengurangi_dua_kali(pg,gudang):
    rs,u=await setup(pg,gudang);b=await body(pg,rs,[(rs[0],0,20),(rs[1],0,10)]);p=await review(b,u)
    results=await asyncio.gather(save(b,u,p),save(b,u,p),return_exceptions=True)
    assert sum(isinstance(r,dict) for r in results)==1
    assert sum(isinstance(r,HTTPException) and r.status_code==409 for r in results)==1
    # Jika jawaban pertama hilang, baca terbaru mengungkap jumlah tersimpan.
    async with pg() as db:k=(await papan_selesai(db,rs[0].rec.id))['kiriman'][0]
    assert [x['barang'][0]['dimuat'] for x in k['pelanggan']]==[20,10]
    with pytest.raises(HTTPException) as e:await save(b,u,p)
    assert e.value.status_code==409 and await _stok(pg,gudang)==9250

@pytest.mark.parametrize('role,allowed',[('admin',False),('superadmin',True),('operator',True)])
async def test_izin_endpoint_dan_baca_saja(pg,gudang,role,allowed):
    from hmu_identitas import peran as P
    rs,u=await setup(pg,gudang)
    async with pg() as db:
        u=await db.get(User,u.id);u.role={'admin':P.ADMIN,'superadmin':P.SUPERADMIN,'operator':P.OPERATOR}[role]
        if role=='operator':u.default_warehouse_id=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g1'))
        await db.commit()
    b=await body(pg,rs,[(rs[0],0,20)])
    async with await _klien(pg,u.id,'lembar-http') as client:
        page=await client.get('/muatan?perintah='+str(rs[0].rec.id));assert page.status_code==200
        html=page.text;assert 'Isi total yang sudah dimuat, bukan tambahannya.' in html
        assert ('data-boleh="1"' in html)==allowed
        headers={"X-CSRF-Token":cap_formulir(client)}
        r=await client.post('/api/actions/periksa-lembar-muatan',json=b,headers=headers)
        assert r.status_code==(200 if allowed else 403)
        if allowed:
            b['pemeriksaan']=r.json()['pemeriksaan'];r=await client.post('/api/actions/simpan-lembar-muatan',json=b,headers=headers);assert r.status_code==200,r.text
        else:
            r=await client.post('/api/actions/simpan-lembar-muatan',json=b,headers=headers);assert r.status_code==403
    assert await _stok(pg,gudang)==(9500 if allowed else 10000)

@pytest.mark.parametrize('mode,allowed',[('admin',False),('operator:g1',True),('operator:g2',True)])
async def test_lihat_sebagai_dan_endpoint_lama_tidak_menaikkan_hak(pg,gudang,mode,allowed):
    from hmu_identitas import peran as P
    from app.web.aksi_inventory import MuatReq, MuatBarisReq, SelesaiMuatReq,act_muat_barang,act_muat_semua,act_selesai_muat
    rs,u=await setup(pg,gudang)
    async with pg() as db:
        u=await db.get(User,gudang['adm']);u.role=P.SUPERADMIN;await db.commit()
    b=await body(pg,rs,[(rs[0],0,20)])
    async with await _klien(pg,u.id,'lembar-view') as c:
        c.cookies.set('produksi_lihat',mode)
        r=await c.get('/muatan',params={'perintah':rs[0].rec.id});assert r.status_code==200
        assert ('data-boleh="1"' in r.text)==allowed
        h={'X-CSRF-Token':cap_formulir(c)}
        r=await c.post('/api/actions/periksa-lembar-muatan',json=b,headers=h)
        assert r.status_code==(200 if allowed else 403)
        if not allowed:
            old=dict(perintah=str(rs[0].rec.id),baris=str(rs[0].baris[0].id),jumlah=20,dasar=b['konteks'][0]['dasar'])
            for url in ('muat-barang','muat-semua','selesai-muat','simpan-lembar-muatan'):
                r=await c.post('/api/actions/'+url,json=b if url=='simpan-lembar-muatan' else old,headers=h)
                assert r.status_code==403,r.text
        else:
            for action,target in [('muat_semua','muatan'),('muat_barang','muatan'),('selesai_muat','selesai-muat')]:
                r=await c.get(f'/barang-keluar/{rs[0].rec.id}',params={'buka':action})
                # Detail G1/G2 scope remains the old restriction; the worksheet
                # itself still supports substituting operators.
                if mode=='operator:g2':assert r.status_code==303 and r.headers['location']==f'/{target}?perintah={rs[0].rec.id}'
    assert await _stok(pg,gudang)==10000
    async with pg() as db:assert (await db.get(User,u.id)).role==P.SUPERADMIN

async def test_kg_dan_barang_jasa_tidak_mengurangi_pabrik(pg,gudang):
    from app.database import now_local
    from app.models import ByproductStock,Jasa
    from app.penggilingan.inventory.finished_goods import hitung_stok_finished_goods
    rs,u=await setup(pg,gudang)
    async with pg() as db:
        j=Jasa(kode='JAS-LEMBAR',pelanggan_id=rs[0].rec.pelanggan_id,status='berjalan');db.add(j);await db.flush()
        db.add(FinishedGoodsStock(product_sku_id=gudang['sku'],rice_quality_standard_id=gudang['std'],source_type='retur',jumlah_karung=10,berat_total_kg=250,input_by=u.id,waktu=now_local(),jasa_id=j.id))
        db.add(ByproductStock(jenis_produk='bekatul',source_type='retur',berat_kg=1000,tanggal=now_local().date(),waktu=now_local(),input_by=u.id,jasa_id=j.id));await db.commit()
        r=await bk.buat_perintah(db,user=await db.get(User,gudang['adm']),jasa_id=j.id,baris=[bk.BarisPerintah(tipe='finished_goods',sku_id=gudang['sku'],std_id=gudang['std'],jumlah_karung=5),bk.BarisPerintah(tipe='byproduct_curah',jenis='bekatul',berat_kg=200)])
    b=await body(pg,[r],[(r,0,3),(r,1,125.25)]);plan=await review(b,u);await save(b,u,plan)
    assert await _stok(pg,gudang)==10000
    async with pg() as db:
        assert (await db.get(OutgoingItem,r.baris[1].id)).berat_kg==Decimal('125.25')
        assert (await hitung_stok_finished_goods(db,gudang['sku'],gudang['std'],jasa_id=j.id))['kg']==175
        k=(await papan_selesai(db,r.rec.id))['kiriman'][0]
        assert all(x['jasa_id']==j.id for x in k['pelanggan'][0]['barang'])

async def test_catat_dan_baca_pelanggan_selesai_tidak_membuka_ulang(pg,gudang):
    rs,u=await setup(pg,gudang)
    async with pg() as db:await bk.muat_semua(db,user=u,rec_id=rs[0].rec.id)
    b=await body(pg,rs,[(rs[0],0,39)]);before=await audit(pg)
    with pytest.raises(HTTPException):await review(b,u)
    async with pg() as db:
        a=await papan_selesai(db,rs[0].rec.id)
        p=a['kiriman'][0]['pelanggan'][0]
        assert p['status']=='dimuat' and p['penutupan']['petugas']
        assert a['kiriman'][0]['kesiapan']=='menunggu_pelanggan'
    assert await audit(pg)==before and await _stok(pg,gudang)==8950

async def test_pk_gudang1_lewat_lembar_dan_stok_proses_lama(pg,gudang):
    from app.database import now_local
    from app.models import MillingProcess,MillingProgressLog
    from app.services.transfer import pending_transfer_kg
    from tests.pg.test_barang_keluar import _pelanggan
    async with pg() as db:
        proc=MillingProcess(kode_proses='G1-LEMBAR',status='selesai',silo_id=gudang['silo'],berat_gabah_masuk_kg=10000,waktu_mulai=now_local(),waktu_selesai=now_local(),created_by=gudang['op'])
        db.add(proc);await db.flush();db.add(MillingProgressLog(milling_process_id=proc.id,berat_kumulatif_kg=6000,waktu_update=now_local(),input_by=gudang['op']));await db.commit();pid=proc.id
    pel=await _pelanggan(pg,'Uji bahan Gudang 1')
    async with pg() as db:
        r=await bk.buat_perintah(db,user=await db.get(User,gudang['adm']),pelanggan_id=pel,baris=[bk.BarisPerintah(tipe='pk_langsung',milling_process_id=pid,berat_kg=2000)])
        u=await db.get(User,gudang['op'])
    b=await body(pg,[r],[(r,0,1250.25)]);p=await review(b,u);await save(b,u,p)
    async with pg() as db:
        assert float(await pending_transfer_kg(db,pid))==4749.75
        k=(await papan_selesai(db,r.rec.id))['kiriman'][0]
        assert k['pelanggan'][0]['barang'][0]['satuan']=='kg'
    assert await _stok(pg,gudang)==10000

async def test_portal_tidak_bisa_membaca_lembar_gabungan_atau_menulis(pg,gudang):
    from app.models.portal import PortalAccount
    from tests.pg.test_riwayat_nonjasa_akses_pelanggan import client
    from app.web.security import hash_sandi
    rs,u=await setup(pg,gudang)
    async with pg() as db:
        account=PortalAccount(username='lembar-portal',pelanggan_id=rs[0].rec.pelanggan_id,password_hash=hash_sandi('rahasia123'),active=True,token_version=1)
        db.add(account);await db.commit()
    b=await body(pg,rs,[(rs[0],0,20)]);before=await audit(pg)
    async with client(account,portal=True) as c:
        for path in ('/muatan','/selesai-muat','/api/actions/papan-muatan','/api/actions/papan-selesai-muat'):
            r=await c.get(path,params={'perintah':rs[0].rec.id});assert r.status_code in (401,403,404,303),r.text
            if r.status_code==303:assert r.headers['location'].startswith(('/masuk','/portal'))
            assert 'Penerima B' not in r.text
        for action in ('periksa-lembar-muatan','simpan-lembar-muatan'):
            r=await c.post('/api/actions/'+action,json=b);assert r.status_code in (401,403,404)
    assert await audit(pg)==before and await _stok(pg,gudang)==10000
