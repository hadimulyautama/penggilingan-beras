"""Reproduksi picker → simpan → proses, dengan saldo pemilik yang sama."""
from decimal import Decimal
import pytest
from sqlalchemy import select
from app.models import User,Silo,PkGudang2Intake
from app.penggilingan.gudang2 import service as g2,polishing
from app.services.masukkan_silo import sumber
from app.services import pk_persediaan
from tests.pg.test_pk_kepemilikan import world,initial
from tests.pg.test_pk_karung import dunia,batch_baru

@pytest.mark.parametrize('dialihkan,masuk',[(1000,100),(800,500),(400,100)])
async def test_pk_pemilik_baru_kg_masuk_silo_lalu_bisa_disosoh(pg,world,dialihkan,masuk):
    w=world
    async with pg() as db:
        await initial(db,w,1,amount=dialihkan)
        u=await db.get(User,w['user'])
        it=await db.get(PkGudang2Intake,int(w['sources'][1].split(':')[1]))
        rows=await sumber(db,it,pemilik_id=w['jasa'])
        assert rows[0]['saldo_kg']==dialihkan and rows[0]['bentuk']=='lama'
        silo=await db.scalar(select(Silo).where(Silo.warehouse_id==w['warehouses'][1]).order_by(Silo.id))
        r=await g2.pindah_tumpukan_ke_silo(db,user=u,intake_id=it.id,nama_silo=silo.nama_silo,
            bentuk_sumber='lama',berat=masuk,pemilik_id=w['jasa'])
        assert r.berat_kg==masuk and r.sisa_tumpukan_intake==dialihkan-masuk
        assert await g2.hitung_stok_silo(db,silo.id)==masuk
        p=await polishing.mulai_penyosohan(db,user=u,nama_silos=[silo.nama_silo])
        assert p.berat_awal_total==masuk and p.proc.jasa_id==w['jasa']
        src=(await pk_persediaan.baca(db))[w['sources'][1]]
        assert src.bebas(w['jasa'])==Decimal(dialihkan-masuk)

async def test_lengkapi_karung_tidak_mengembalikan_saldo_yang_sudah_berkurang(pg,dunia):
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,n=None,w=1000)
        # Skenario pembaca per pemilik/alokasi: hanya 600 kg yang bebas.
        rows=await sumber(db,it,jumlah_partai=20,pemilik_id=None,saldo_pemilik=600)
        assert rows[0]['saldo_kg']==600 and rows[0]['karung']==12

@pytest.mark.parametrize('profil',['g1','g2',None])
@pytest.mark.parametrize('ke_pabrik',[False,True])
async def test_operator_gudang_aktif_dari_pilihan_sampai_mulai_sosoh(pg,world,profil,ke_pabrik):
    from app.models import PolishingProcess,PkTumpukanToSilo
    from sqlalchemy import func
    from tests.pg.test_operator_ganti_gudang import _orang,_token,_klien,_gudang_di_db
    w=world
    iid=int(w['sources'][1].split(':')[1])
    owner=None if ke_pabrik else w['jasa']
    async with pg() as db:
        it=await db.get(PkGudang2Intake,iid)
        if ke_pabrik:
            it.jasa_id=w['jasa'];await db.commit()
        await initial(db,w,1,amount=1000,dari=w['jasa'] if ke_pabrik else None,
                      ke=None if ke_pabrik else 'jasa')
    stored={'g1':w['warehouses'][0],'g2':w['warehouses'][1]}.get(profil)
    aid,uid=await _orang(pg,nama='Operator lintas shift',role='operator',username='uji-rantai',gudang_id=stored)
    async with _klien(await _token(pg,aid),gudang='g2') as c:
        options=await c.get('/api/actions/sumber-masukkan-silo');assert options.status_code==200,options.text
        token=next(x['value'] for x in options.json() if x['intake_id']==iid)
        assert token.endswith('|pemilik='+('pabrik' if owner is None else str(owner)))
        dest=await c.get('/api/actions/silo-g2',params={'induk':token});assert dest.status_code==200,dest.text
        silo=dest.json()[0]['value']
        params=dict(tumpukan=token,silo=silo,berat_kg='1000')
        preview=await c.get('/api/actions/rincian-masukkan-silo',params=params)
        assert preview.status_code==200,preview.text
        assert preview.json()['siap'] and preview.json()['berat_masuk']==1000
        payload=dict(tumpukan=token,silo=silo,berat_kg=1000,kunci_kiriman='rantai-pk-owner')
        for _ in range(2):
            r=await c.post('/api/actions/pindah-tumpukan-silo',json=payload);assert r.status_code==200,r.text
        r=await c.post('/api/actions/mulai-penyosohan',json={'silo':[silo]});assert r.status_code==200,r.text
        kode=r.json()['kode_proses']
    async with pg() as db:
        proc=await db.scalar(select(PolishingProcess).where(PolishingProcess.kode_proses==kode))
        assert proc.jasa_id==owner
        assert await db.scalar(select(func.count()).select_from(PkTumpukanToSilo))==1
        assert await g2._sisa_tumpukan_intake(db,iid,pemilik_id=owner)==0
    assert await _gudang_di_db(pg,uid)==stored

@pytest.mark.parametrize('pemilik_baru',[False,True])
async def test_n_dilengkapi_saldo_ledger_dan_http_simpan_tetap_sama(pg,dunia,pemilik_baru):
    from app.models import Pelanggan,Jasa,PkPurchaseBatch,PkTumpukanToSilo
    from sqlalchemy import func
    from tests.pg.test_barang_keluar import _klien
    from tests.pg.formulir import cap_formulir
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,n=None,w=1000)
        pel=Pelanggan(nama_pelanggan='Pemilik PK N baru');db.add(pel);await db.flush()
        j=Jasa(kode='JAS-PK-N',pelanggan_id=pel.id,status='berjalan');db.add(j);await db.flush()
        u.role='admin';await db.commit()
        w=dict(user=u.id,jasa=j.id,sources=['tumpukan:'+str(it.id)],warehouses=[it.warehouse_id])
        await initial(db,w,0,amount=400)
        u.role='operator';await db.commit()
        uid,bid,iid,jid=u.id,b.id,it.id,j.id
    owner=jid if pemilik_baru else None
    free=400 if pemilik_baru else 600
    token=f'{iid}:lama|pemilik='+('pabrik' if owner is None else str(owner))
    async with await _klien(pg,uid,'n-saldo-owner',mode='operator') as c:
        params=dict(tumpukan=token,silo='A',jumlah_karung_partai=20,jumlah_karung=free//50)
        d=await c.get('/api/actions/rincian-masukkan-silo',params=params);assert d.status_code==200,d.text
        assert d.json()['sumber']['saldo_kg']==free and d.json()['sumber']['karung']==free//50
        payload=dict(params,kunci_kiriman='n-owner')
        r=await c.post('/api/actions/pindah-tumpukan-silo',json=dict(payload,jumlah_karung=20),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==400,r.text
        async with pg() as db:
            assert (await db.get(PkPurchaseBatch,bid)).jumlah_karung is None
            assert await db.scalar(select(func.count()).select_from(PkTumpukanToSilo))==0
        r=await c.post('/api/actions/pindah-tumpukan-silo',json=payload,headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200,r.text
    async with pg() as db:
        assert (await db.get(PkPurchaseBatch,bid)).jumlah_karung==20
        assert await g2._sisa_tumpukan_intake(db,iid,pemilik_id=owner)==0
        silo=await g2.get_g2_silo(db,'A')
        assert await g2.hitung_stok_silo(db,silo.id)==free
        row=await db.scalar(select(PkTumpukanToSilo));assert row.jasa_id==owner

async def test_lengkapi_n_tetap_mengurangi_reservasi_retur(pg,asal):
    from uuid import uuid4
    from tests.pg.test_retur_supplier import buat_sumber,user
    from app.services import retur_supplier as retur
    async with pg() as db:
        tid,b,key=await buat_sumber(db,asal,'pk',kg='1000',bags=None)
        from sqlalchemy import text
        await db.execute(text("UPDATE timbangan_transaksi SET timbang2_kg=4000,berat_barang_kg=1000,netto_timbangan_kg=1000,status_tiket='SELESAI' WHERE id=:id"),{'id':tid})
        payload=[dict(kunci=key,jumlah='400')]
        check=await retur.periksa(db,tid,user(asal),payload,'Mutu tidak sesuai','')
        await retur.simpan(db,user=user(asal),tid=tid,jumlah=payload,alasan='Mutu tidak sesuai',catatan='',kunci=uuid4().hex,dasar=check['dasar']);await db.commit()
        it=await db.scalar(select(PkGudang2Intake).where(PkGudang2Intake.pk_purchase_batch_id==b.id))
        rows=await sumber(db,it,jumlah_partai=20)
        assert rows[0]['saldo_kg']==600 and rows[0]['karung']==12
        assert b.jumlah_karung is None

@pytest.mark.parametrize('berat_lama',[None,1000])
async def test_nota_baru_saat_lengkapi_n_memperbarui_acuan_pratinjau_tanpa_menulis(pg,dunia,berat_lama):
    from tests.pg.test_retur_supplier import tiket
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,n=None,w=berat_lama,sumber='menunggu' if berat_lama is None else 'timbangan')
        b.timbangan_transaksi_id=await tiket(db,dunia[1],'BERAS_PK');await db.commit()
        rows=await sumber(db,it,jumlah_partai=20)
        assert rows[0]['saldo_kg']==1600 and rows[0]['karung']==20
        assert not rows[0]['bobot_final']
        assert b.jumlah_karung is None and b.berat_total_kg==berat_lama

from tests.pg.test_retur_supplier import asal,skema_retur_timbang

@pytest.mark.parametrize('bagian,lama',[(25,False),(998,True)])
async def test_pk_pembelian_bagian_karung_pemilik_baru_dan_payload_kg_lama(pg,dunia,bagian,lama):
    from app.models import Pelanggan,Jasa
    from tests.pg.test_barang_keluar import _klien
    from tests.pg.formulir import cap_formulir
    async with pg() as db:
        u,b,it=await batch_baru(db,dunia,n=20,w=998)
        pel=Pelanggan(nama_pelanggan='Pemilik bagian karung PK');db.add(pel);await db.flush()
        j=Jasa(kode='JAS-PK-BAGIAN',pelanggan_id=pel.id,status='berjalan');db.add(j);await db.flush()
        u.role='admin';await db.commit()
        await initial(db,dict(user=u.id,jasa=j.id,sources=['tumpukan:'+str(it.id)],warehouses=[it.warehouse_id]),0,amount=bagian)
        u.role='operator';await db.commit()
        uid,iid,jid=u.id,it.id,j.id
    async with await _klien(pg,uid,'pk-bagian-owner',mode='operator') as c:
        token=f'{iid}'+('' if lama else ':lama')+f'|pemilik={jid}'
        if not lama:
            options=(await c.get('/api/actions/sumber-masukkan-silo')).json()
            assert any(o['value']==token for o in options)
            d=await c.get('/api/actions/rincian-masukkan-silo',params=dict(tumpukan=token,silo='A',berat_kg=25))
            assert d.status_code==200 and d.json()['siap'],d.text
            assert d.json()['sumber']['karung']==0
        r=await c.post('/api/actions/pindah-tumpukan-silo',json=dict(tumpukan=token,silo='A',berat_kg=bagian,hasil_timbang='ya'),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200,r.text
    async with pg() as db:
        assert await g2._sisa_tumpukan_intake(db,iid,pemilik_id=jid)==0
        assert await g2._sisa_tumpukan_intake(db,iid,pemilik_id=None)==998-bagian
        silo=await g2.get_g2_silo(db,'A')
        assert await g2.hitung_stok_silo(db,silo.id)==bagian
