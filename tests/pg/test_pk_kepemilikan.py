import copy,uuid
from decimal import Decimal as D
import pytest
from sqlalchemy import select,func
from app.database import now_local
from app.models import (Warehouse,User,Pelanggan,Jasa,Silo,MillingProcess,
                        MillingProcessVerification,PkGudang2Intake,Peristiwa)
from app.services import pk_kepemilikan as pk,pk_persediaan as stok,kepemilikan as umum
from app.domain.gudang import PersediaanError

pytestmark=pytest.mark.asyncio

@pytest.fixture
async def world(pg):
    from app.services.seed import seed_master
    await seed_master()
    async with pg() as db:
        ws=(await db.scalars(select(Warehouse).order_by(Warehouse.id))).all()
        w1=next(w for w in ws if w.kode_fungsi=='g1');w2=next(w for w in ws if w.kode_fungsi=='g2')
        w3=Warehouse(nama_gudang='Cabang baru',kode_fungsi=None,aktif=True)
        user=User(nama='Admin PK',role='admin',status='aktif')
        p=Pelanggan(nama_pelanggan='Pemilik jasa PK');db.add_all([w3,user,p]);await db.flush()
        jasa=Jasa(kode='JAS-PK-001',pelanggan_id=p.id,status='berjalan');db.add(jasa);await db.flush()
        silo=await db.scalar(select(Silo).where(Silo.warehouse_id==w1.id).limit(1))
        now=now_local()
        proc=MillingProcess(kode_proses='LOT-PK-001',warehouse_id=w1.id,silo_id=silo.id,
            jasa_id=None,berat_gabah_masuk_kg=1600,waktu_mulai=now,waktu_selesai=now,
            status='selesai',created_by=user.id)
        db.add(proc);await db.flush()
        db.add(MillingProcessVerification(milling_process_id=proc.id,berat_output_final_kg=1000,
                                          verified_by=user.id))
        rows=[]
        for w in [w2,w3]:
            it=PkGudang2Intake(warehouse_id=w.id,sumber_tipe='beli_luar',tujuan='ditumpuk',
                berat_kg=1000,bobot_final=True,flag_hpp_belum_tersedia=True,
                tanggal_masuk=now.date(),waktu_masuk=now,input_by=user.id,jasa_id=None)
            db.add(it);rows.append(it)
        await db.commit()
        return dict(user=user.id,jasa=jasa.id,warehouses=[w1.id,w2.id,w3.id],
                    sources=['giling:'+str(proc.id)]+['tumpukan:'+str(i.id) for i in rows])

async def initial(db,w,index=0,amount=400,*,dari=None,ke='jasa'):
    user=await db.get(User,w['user'])
    req=dict(sumber=w['sources'][index],warehouse_id=w['warehouses'][index],dari=dari,
             ke=w['jasa'] if ke=='jasa' else ke,quantity=amount,reason='Disepakati pemilik PK',
             key=uuid.uuid4().hex)
    review=await pk.periksa_awal(db,user=user,req=req)
    assert review['plan']['physical_before']==review['plan']['physical_after']
    req.update(review=review['review'],baseline=review['baseline'],confirm=True)
    result=await pk.simpan_awal(db,user=user,req=req);await db.commit()
    return result,req

@pytest.mark.parametrize('index',[0,1,2])
async def test_dua_arah_dan_gudang_baru_tanpa_percabangan(pg,world,index):
    w=world
    async with pg() as db:
        result,_=await initial(db,w,index)
        source=(await stok.baca(db))[w['sources'][index]]
        assert source.bebas(None)==600 and source.bebas(w['jasa'])==400
        assert source.stok.fisik_kg==1000 and source.stok.gudang.id==w['warehouses'][index]
        await initial(db,w,index,150,dari=w['jasa'],ke=None)
        source=(await stok.baca(db))[w['sources'][index]]
        assert source.bebas(None)==750 and source.bebas(w['jasa'])==250
        assert source.stok.fisik_kg==1000
        c=await umum.context(db,user=await db.get(User,w['user']),ident=result['id'])
        assert c['description']['unit']=='kg' and c['state']['kind']=='pk'
        listing=await umum.listing(db,user=await db.get(User,w['user']),kind='pk')
        assert listing['total']==2 and all(x['kind']=='pk' for x in listing['items'])

async def test_retry_koreksi_pembatalan_dan_riwayat(pg,world):
    w=world
    async with pg() as db:
        result,original=await initial(db,w,1)
        user=await db.get(User,w['user'])
        retry=await pk.simpan_awal(db,user=user,req=original)
        assert retry['id']==result['id']
        ident=result['id']
        for mode,quantity in [('ubah',250),('batal',None)]:
            ctx=await umum.context(db,user=user,ident=ident)
            req=dict(mode=mode,quantity=quantity,customer=None,source_ids=[],
                     reason='Perbaiki sesuai kesepakatan',baseline=ctx['baseline'],key=uuid.uuid4().hex)
            inspect=await umum.inspect(db,user=user,ident=ident,req=req)
            req.update(review=inspect['review'],confirm=True)
            saved=await umum.save(db,user=user,ident=ident,req=req);await db.commit()
            assert (await umum.save(db,user=user,ident=ident,req=req))['event_id']==saved['event_id']
        ctx=await umum.context(db,user=user,ident=ident)
        assert ctx['state']['status']=='dibatalkan' and len(ctx['history'])==2
        source=(await stok.baca(db))[w['sources'][1]]
        assert source.bebas(None)==1000 and source.bebas(w['jasa'])==0
        assert source.stok.fisik_kg==1000

async def test_izin_gudang_sumber_dan_stale_review(pg,world):
    w=world
    async with pg() as db:
        user=await db.get(User,w['user'])
        req=dict(sumber=w['sources'][0],warehouse_id=w['warehouses'][2],dari=None,
                 ke=w['jasa'],quantity=100,reason='Uji identitas gudang',key=uuid.uuid4().hex)
        with pytest.raises(umum.InventoryError):await pk.periksa_awal(db,user=user,req=req)
        req['warehouse_id']=w['warehouses'][0]
        review=await pk.periksa_awal(db,user=user,req=req)
        await initial(db,w,0,950)
        req.update(review=review['review'],baseline=review['baseline'],confirm=True)
        with pytest.raises((umum.InventoryError,PersediaanError)):
            await pk.simpan_awal(db,user=user,req=req)
        user.role='operator'
        with pytest.raises(PermissionError):await pk.pilihan(db,user=user)


async def test_pk_g1_yang_dialihkan_dapat_dikirim_dengan_pemilik_baru(pg,world):
    from app.services.transfer import create_internal_transfer,pending_transfer_kg
    from app.services.stok import pk_gudang1
    w=world
    async with pg() as db:
        result,_=await initial(db,w,0)
        user=await db.get(User,w['user'])
        assert await pending_transfer_kg(db,1,pemilik_id=None)==600
        assert await pending_transfer_kg(db,1,pemilik_id=w['jasa'])==400
        moved=await create_internal_transfer(db,user=user,
            kode_proses='LOT-PK-001|pemilik='+str(w['jasa']),lokasi_tujuan='ditumpuk',berat=200)
        assert moved.transfer.jasa_id==w['jasa']
        source=(await stok.baca(db))[w['sources'][0]]
        assert source.bebas(None)==600 and source.bebas(w['jasa'])==200
        cards=await pk_gudang1(db)
        assert {(c.jasa_id,c.tersedia) for c in cards}=={(None,600),(w['jasa'],200)}
        ctx=await umum.context(db,user=user,ident=result['id'])
        req=dict(mode='batal',quantity=None,customer=None,source_ids=[],reason='Sudah dipakai',
                 baseline=ctx['baseline'],key=uuid.uuid4().hex)
        with pytest.raises((umum.InventoryError,PersediaanError)):
            await umum.inspect(db,user=user,ident=result['id'],req=req)


async def test_pk_tumpukan_pemilik_baru_masuk_silo_dan_bagian_terpakai_dijaga(pg,world):
    from app.penggilingan.gudang2.service import pindah_tumpukan_ke_silo,hitung_stok_silo
    from app.services.jasa import pemilik_silo_g2
    w=world
    async with pg() as db:
        result,_=await initial(db,w,1)
        user=await db.get(User,w['user'])
        silo=await db.scalar(select(Silo).where(Silo.warehouse_id==w['warehouses'][1],Silo.nama_silo.in_(['A','Silo A'])))
        iid=int(w['sources'][1].split(':')[1])
        await pindah_tumpukan_ke_silo(db,user=user,intake_id=iid,nama_silo=silo.nama_silo,
                                     berat=100,hasil_timbang=True,pemilik_id=w['jasa'])
        source=(await stok.baca(db))[w['sources'][1]]
        assert source.bebas(None)==600 and source.bebas(w['jasa'])==300
        assert await pemilik_silo_g2(db,silo.id)=={w['jasa']}
        assert await hitung_stok_silo(db,silo.id,pemilik='jasa')==100
        assert await hitung_stok_silo(db,silo.id,pemilik='pabrik')==0
        ctx=await umum.context(db,user=user,ident=result['id'])
        req=dict(mode='batal',quantity=None,customer=None,source_ids=[],reason='Sudah dipakai',
                 baseline=ctx['baseline'],key=uuid.uuid4().hex)
        with pytest.raises((umum.InventoryError,PersediaanError)):
            await umum.inspect(db,user=user,ident=result['id'],req=req)


@pytest.mark.parametrize('role,allowed',[('admin',True),('operator',False)])
async def test_http_pk_formulir_csrf_dan_tab_riwayat(pg,world,role,allowed):
    from tests.pg.test_riwayat_giling import _klien
    from tests.pg.formulir import cap_formulir
    w=world
    async with await _klien(pg,peran=role,gudang='Gudang 2') as client:
        for path in ['/kepemilikan/pk/baru','/api/pk-kepemilikan/pilihan','/api/pk-kepemilikan/pemilik']:
            r=await client.get(path)
            assert r.status_code==(200 if allowed else 403),(path,r.text[:300])
        req=dict(sumber=w['sources'][2],warehouse_id=w['warehouses'][2],dari=None,
                 ke=w['jasa'],quantity=100,reason='Cabang baru',key=uuid.uuid4().hex)
        assert (await client.post('/api/pk-kepemilikan/periksa',json=req)).status_code==403
        r=await client.post('/api/pk-kepemilikan/periksa',json=req,headers={'X-CSRF-Token':cap_formulir(client)})
        assert r.status_code==(200 if allowed else 403),r.text
        if not allowed:return
        req.update(review=r.json()['review'],baseline=r.json()['baseline'],confirm=True)
        r=await client.post('/api/pk-kepemilikan/simpan',json=req,headers={'X-CSRF-Token':cap_formulir(client)})
        assert r.status_code==200,r.text
        ident=r.json()['id']
        for path in ['/kepemilikan/'+str(ident),'/api/kepemilikan/'+str(ident),
                     '/api/kepemilikan/'+str(ident)+'/sumber','/api/kepemilikan?kind=pk']:
            r=await client.get(path)
            assert r.status_code==200,(path,r.text[:400])
        assert (await client.get('/api/pk-kepemilikan/status/'+req['key'])).json()['recorded']


async def test_dua_pengalihan_serentak_tidak_menghabiskan_bagian_yang_sama(pg,world):
    import asyncio
    w=world
    async def send():
        async with pg() as db:
            try:
                result,_=await initial(db,w,1,700)
                return result['recorded']
            except (umum.InventoryError,PersediaanError):
                await db.rollback()
                return False
    assert sorted(await asyncio.gather(send(),send()))==[False,True]
    async with pg() as db:
        source=(await stok.baca(db))[w['sources'][1]]
        assert source.stok.fisik_kg==1000 and source.bebas(w['jasa'])==700


@pytest.mark.parametrize('index',[0,1,2])
async def test_pk_asalnya_jasa_dan_penutupan_jasa_mengikuti_hak_baru(pg,world,index):
    from app.services.jasa import sisa_jasa,pernah_ada_barang
    w=world
    async with pg() as db:
        model=MillingProcess if index==0 else PkGudang2Intake
        row=await db.get(model,int(w['sources'][index].split(':')[1]))
        row.jasa_id=w['jasa'];await db.commit()
        await initial(db,w,index,400,dari=w['jasa'],ke=None)
        source=(await stok.baca(db))[w['sources'][index]]
        assert source.bebas(None)==400 and source.bebas(w['jasa'])==600
        sisa=await sisa_jasa(db,w['jasa'])
        assert (sisa.pk_g1_kg if index==0 else sisa.pk_g2_kg)==600
        assert await pernah_ada_barang(db,w['jasa'])
        await initial(db,w,index,150,dari=None,ke='jasa')
        source=(await stok.baca(db))[w['sources'][index]]
        assert source.bebas(None)==250 and source.bebas(w['jasa'])==750


async def test_alokasi_perintah_menahan_pengalihan_dan_sumber_tidak_dibatalkan(pg,world):
    from app.models import OutgoingRecord,OutgoingItem
    from app.services.undo import _undo_verify_output,UndoError
    w=world
    async with pg() as db:
        now=now_local()
        r=OutgoingRecord(kode='OUT-PK-ALOK',warehouse_id=w['warehouses'][0],status='perintah',
                         tanggal=now.date(),waktu=now,input_by=w['user'])
        db.add(r);await db.flush()
        db.add(OutgoingItem(outgoing_record_id=r.id,item_type='pk_langsung',milling_process_id=1,
                            jasa_id=None,berat_perintah_kg=800,berat_kg=0,jumlah_karung=0))
        await db.commit()
        source=(await stok.baca(db))[w['sources'][0]]
        assert source.bebas(None)==200 and source.stok.fisik_kg==1000
        with pytest.raises((PersediaanError,umum.InventoryError)):await initial(db,w,0,300)
        result,_=await initial(db,w,0,100)
        with pytest.raises(UndoError,match='pengalihan'):await _undo_verify_output(db,1)
        ctx=await umum.context(db,user=await db.get(User,w['user']),ident=result['id'])
        assert ctx['state']['quantity']=='100'
