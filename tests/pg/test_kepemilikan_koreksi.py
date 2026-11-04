"""Konservasi, sumber, transaksi berulang, konflik dan izin per transaksi."""
import copy,asyncio,uuid
from decimal import Decimal as D
import pytest
from sqlalchemy import select,func
from app.models import (User,Warehouse,Pelanggan,Jasa,ProductSku,FinishedGoodsStock,ByproductStock,PackagingPurchase,Peristiwa,OutgoingRecord,OutgoingItem,BrokenKeSilo,Silo)
from app.database import now_local
from app.services import kepemilikan as s
pytestmark=pytest.mark.asyncio

@pytest.fixture
async def world(pg):
    from app.services.seed import seed_master
    from hmu_core import PackagingMaterial,PackageSize
    await seed_master()
    async with pg() as db:
        wh=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g2'))
        u=User(nama='Admin koreksi',role='admin',status='aktif',default_warehouse_id=wh.id);db.add(u)
        p=Pelanggan(nama_pelanggan='Pelanggan A');p2=Pelanggan(nama_pelanggan='Pelanggan B');db.add_all([p,p2]);await db.flush()
        js=[Jasa(kode='JAS-KOREKSI-'+str(i),pelanggan_id=x.id,status='berjalan') for i,x in enumerate([p,p,p2])];db.add_all(js)
        mat=await db.scalar(select(PackagingMaterial).where(PackagingMaterial.kode=='biasa'))
        size=await db.scalar(select(PackageSize).where(PackageSize.ukuran_kg==50))
        sku=ProductSku(kategori='beras_putih',packaging_material_id=mat.id,package_size_id=size.id);db.add(sku);await db.flush()
        now=now_local()
        def fg(n,w,j):return FinishedGoodsStock(product_sku_id=sku.id,rice_quality_standard_id=None,source_type='retur',source_id=None,jumlah_karung=n,berat_total_kg=w,warehouse_id=wh.id,waktu=now,input_by=u.id,jasa_id=j,kemasan_mengurangi_stok=False)
        a=fg(100,5000,js[0].id);factory=fg(20,1000,None);other=fg(80,3920,js[2].id);db.add_all([a,factory,other]);await db.flush()
        pack=PackagingPurchase(kode='PKP-KOR-01',packaging_material_id=mat.id,package_size_id=size.id,jumlah_lembar=1200,tanggal=now.date(),waktu=now,input_by=u.id)
        bp=ByproductStock(jenis_produk='broken',source_type='retur',berat_kg=D('5000.55'),tanggal=now.date(),waktu=now,input_by=u.id,jasa_id=js[0].id)
        bek=ByproductStock(jenis_produk='bekatul',source_type='retur',berat_kg=D('5000.55'),tanggal=now.date(),waktu=now,input_by=u.id,jasa_id=js[0].id)
        db.add_all([pack,bp,bek]);await db.commit()
        return dict(user=u.id,wh=wh.id,owners=[j.id for j in js],customers=[p.id,p2.id],sku=sku.id,source=a.id,other=other.id,pack=pack.id,broken=bp.id,bekatul=bek.id,material=mat.id,size=size.id)

async def create(pg,w,kind='barang',amount=40,owners=None):
    identity={'sku':w['sku'],'std':None} if kind=='barang' else {'jenis':kind} if kind in ('broken','bekatul') else {'material':w['material'],'size':w['size'],'brand':None}
    pool='curah' if kind in ('broken','bekatul') else kind
    async with pg() as db:
        user=await db.get(User,w['user']);await s.initial(db,user=user,kind=pool,identity=identity,owners=owners or ([None] if pool=='karung' else [w['owners'][0]]),customer=w['customers'][0] if pool=='karung' else None,amount=amount)
        event=await db.scalar(select(Peristiwa).where(Peristiwa.jenis==s.AWAL).order_by(Peristiwa.id.desc()));return event.id

async def body(pg,w,ident,amount=30,**kw):
    async with pg() as db:
        ctx=await s.context(db,user=await db.get(User,w['user']),ident=ident)
    return dict(mode='ubah',quantity=amount,customer=None,source_ids=[],reason='Salah catat, sudah diperiksa',baseline=ctx['baseline'],key=uuid.uuid4().hex,**kw)

async def change(pg,w,ident,amount=30,**kw):
    req=await body(pg,w,ident,amount)
    req.update(kw)
    async with pg() as db:
        pre=await s.inspect(db,user=await db.get(User,w['user']),ident=ident,req=req);await db.rollback()
    req.update(review=pre['review'],confirm=True)
    async with pg() as db:
        result=await s.save(db,user=await db.get(User,w['user']),ident=ident,req=req);await db.commit()
    return result,req

async def test_contoh_barang_40_30_batal_riwayat_tetap(pg,world):
    w=world;i=await create(pg,w);r,_=await change(pg,w,i)
    assert r['plan']['balances_after'][str(w['owners'][0])]=={'karung':70,'kg':3500}
    assert r['plan']['balances_after']['None']=={'karung':50,'kg':2500}
    assert r['plan']['mutations'][0]['restored']['jumlah_karung']==10
    r,_=await change(pg,w,i,mode='batal',quantity=None)
    assert r['plan']['after']['quantity']=='0'
    assert r['plan']['balances_after'][str(w['owners'][0])]=={'karung':100,'kg':5000}
    assert r['plan']['balances_after']['None']=={'karung':20,'kg':1000}
    async with pg() as db:
        ctx=await s.context(db,user=await db.get(User,w['user']),ident=i)
        assert ctx['original']['quantity']=='40' and len(ctx['history'])==2
        assert ctx['state']['status']=='dibatalkan'

async def test_contoh_karung_400_300_batal(pg,world):
    w=world;i=await create(pg,w,'karung',400);r,_=await change(pg,w,i,300)
    assert r['plan']['balances_after']['None']=={'lembar':900}
    assert r['plan']['balances_after'][str(w['customers'][0])]=={'lembar':300}
    r,_=await change(pg,w,i,mode='batal',quantity=None)
    assert r['plan']['balances_after']['None']=={'lembar':1200}
    assert r['plan']['balances_after'][str(w['customers'][0])]=={'lembar':0}
    assert r['plan']['after']['kg'] is None

@pytest.mark.parametrize('kind',['broken','bekatul'])
async def test_curah_pecahan_dan_koreksi_berulang(pg,world,kind):
    w=world;i=await create(pg,w,kind,D('2000.25'))
    for amount in [D('1900.11'),D('2100.39'),D('1800.01')]:
        r,_=await change(pg,w,i,amount)
        assert D(r['plan']['after']['kg'])==amount
        assert r['plan']['physical']==['5000.55']
    r,_=await change(pg,w,i,mode='batal',quantity=None)
    assert D(str(r['plan']['balances_after'][str(w['owners'][0])]['kg']))==D('5000.55')

async def test_berat_nyata_bukan_nominal_dan_semua_baris(pg,world):
    w=world
    async with pg() as db:
        src=await db.get(FinishedGoodsStock,w['source']);src.jumlah_karung=20;src.berat_total_kg=998
        clone=FinishedGoodsStock(**{k:v for k,v in {c.name:getattr(src,c.name) for c in src.__table__.columns}.items() if k not in ('id','created_at','updated_at')});clone.jumlah_karung=20;clone.berat_total_kg=1002;db.add(clone);await db.commit()
    i=await create(pg,w,amount=30)
    async with pg() as db:
        e=await db.get(Peristiwa,i);assert len(e.muatan['lines'])==2 and D(e.muatan['kg'])==D('1499')
        assert all('source_before' in x and 'source_after' in x for x in e.muatan['lines'])
    r,_=await change(pg,w,i,20)
    assert D(r['plan']['after']['kg'])==998

async def test_transaksi_lama_bukan_input_terakhir(pg,world):
    w=world;i=await create(pg,w,amount=40);await create(pg,w,amount=10)
    r,_=await change(pg,w,i,30);assert r['plan']['after']['quantity']=='30'

async def test_idempoten_dan_kunci_tidak_dipakai_ulang(pg,world):
    w=world;i=await create(pg,w);r,b=await change(pg,w,i)
    async with pg() as db:
        again=await s.save(db,user=await db.get(User,w['user']),ident=i,req=b);await db.commit();assert again['event_id']==r['event_id']
        b['quantity']=29
        with pytest.raises(s.InventoryError,match='Kunci'):await s.save(db,user=await db.get(User,w['user']),ident=i,req=b)

@pytest.mark.parametrize('value',[-1,0,1.5,1000])
async def test_jumlah_barang_tidak_sah(pg,world,value):
    i=await create(pg,world)
    with pytest.raises(s.InventoryError):await change(pg,world,i,value)

@pytest.mark.parametrize('role',['operator','operator_g1','operator_g2','pelanggan'])
async def test_operator_tidak_diberi_hak_koreksi(pg,world,role):
    w=world;i=await create(pg,w)
    async with pg() as db:
        user=await db.get(User,w['user']);user.role=role
        with pytest.raises(PermissionError):await s.context(db,user=user,ident=i)

async def test_periksa_rollback_tanpa_perubahan(pg,world):
    w=world;i=await create(pg,w);b=await body(pg,w,i)
    async with pg() as db:
        user=await db.get(User,w['user']);before=await s.context(db,user=user,ident=i);count=await db.scalar(select(func.count()).select_from(Peristiwa));await s.inspect(db,user=user,ident=i,req=b);await db.commit()
    async with pg() as db:
        after=await s.context(db,user=await db.get(User,w['user']),ident=i)
        assert before['baseline']==after['baseline'] and count==await db.scalar(select(func.count()).select_from(Peristiwa))

async def test_sumber_ganti_harus_pesanan_partai_tepat(pg,world):
    w=world;i=await create(pg,w)
    r,_=await change(pg,w,i,30,source_ids=[w['other']])
    assert r['plan']['after']['owners']==[w['owners'][2]]
    assert r['plan']['balances_after'][str(w['owners'][0])]['karung']==100
    assert r['plan']['balances_after'][str(w['owners'][2])]['karung']==50
    assert D(r['plan']['after']['kg'])==1470

async def test_ganti_pelanggan_karung(pg,world):
    w=world;i=await create(pg,w,'karung',400)
    r,_=await change(pg,w,i,300,customer=w['customers'][1])
    assert r['plan']['balances_after'][str(w['customers'][0])]['lembar']==0
    assert r['plan']['balances_after'][str(w['customers'][1])]['lembar']==300

async def test_konflik_setelah_preview_menahan_save(pg,world):
    w=world;i=await create(pg,w);b=await body(pg,w,i)
    async with pg() as db:
        pre=await s.inspect(db,user=await db.get(User,w['user']),ident=i,req=b);await db.rollback()
    await change(pg,w,i,35)
    b.update(review=pre['review'],confirm=True)
    async with pg() as db:
        with pytest.raises(s.InventoryError,match='berubah'):await s.save(db,user=await db.get(User,w['user']),ident=i,req=b)

async def test_batal_kedua_tidak_membalik_lagi(pg,world):
    w=world;i=await create(pg,w);await change(pg,w,i,mode='batal',quantity=None)
    with pytest.raises(s.InventoryError,match='sudah dibatalkan'):await change(pg,w,i,mode='batal',quantity=None)

async def test_sebagian_terpakai_bisa_kurangi_yang_bebas_tidak_batal_penuh(pg,world):
    w=world;i=await create(pg,w)
    # Factory's original 20 bags precede the transferred 40. FIFO output 35
    # consumes the original 20 and exactly 15 of this transfer's bags.
    async with pg() as db:
        now=now_local();o=OutgoingRecord(kode='OUT-DEPEND',tanggal=now.date(),waktu=now,input_by=w['user'],status='selesai');db.add(o);await db.flush();db.add(OutgoingItem(outgoing_record_id=o.id,item_type='finished_goods',product_sku_id=w['sku'],jumlah_karung=35,berat_kg=1750,jasa_id=None));await db.commit()
    r,_=await change(pg,w,i,30);assert r['plan']['after']['quantity']=='30'
    with pytest.raises(s.InventoryError,match='OUT-DEPEND'):await change(pg,w,i,mode='batal',quantity=None)

async def test_saldo_lain_tidak_membuktikan_sumber_aman(pg,world):
    w=world;i=await create(pg,w)
    async with pg() as db:
        e=await db.get(Peristiwa,i);r=await db.get(FinishedGoodsStock,e.muatan['lines'][0]['target_id']);r.jumlah_karung=1;r.berat_total_kg=50
        original=await db.get(FinishedGoodsStock,w['source']);original.jumlah_karung=1000;original.berat_total_kg=50000;await db.commit()
    with pytest.raises(s.InventoryError,match='telah berubah'):await change(pg,w,i,mode='batal',quantity=None)

async def test_daftar_pagination_status_efektif_dan_histori(pg,world):
    w=world;i=await create(pg,w);await change(pg,w,i,30)
    async with pg() as db:
        user=await db.get(User,w['user']);rows=await s.listing(db,user=user,status='terkoreksi');assert rows['total']==1 and rows['items'][0]['quantity']=='30'
        empty=await s.listing(db,user=user,status='dibatalkan');assert empty['total']==0

async def test_koreksi_serentak_satu_saja_versi_yang_sah(pg,world):
    w=world;i=await create(pg,w);b=await body(pg,w,i)
    async with pg() as db:
        pre=await s.inspect(db,user=await db.get(User,w['user']),ident=i,req=b);await db.rollback()
    b.update(review=pre['review'],confirm=True)
    async def worker(key):
        async with pg() as db:
            try:r=await s.save(db,user=await db.get(User,w['user']),ident=i,req={**b,'key':key});await db.commit();return r
            except s.InventoryError as e:await db.rollback();return e
    result=await asyncio.gather(worker(uuid.uuid4().hex),worker(uuid.uuid4().hex))
    assert sum(isinstance(x,dict) for x in result)==1
    async with pg() as db:
        ctx=await s.context(db,user=await db.get(User,w['user']),ident=i);assert len(ctx['history'])==1 and ctx['state']['quantity']=='30'

async def test_retry_serentak_kunci_sama_satu_peristiwa(pg,world):
    w=world;i=await create(pg,w);b=await body(pg,w,i)
    async with pg() as db:
        pre=await s.inspect(db,user=await db.get(User,w['user']),ident=i,req=b);await db.rollback()
    b.update(review=pre['review'],confirm=True)
    async def worker():
        async with pg() as db:
            r=await s.save(db,user=await db.get(User,w['user']),ident=i,req=b);await db.commit();return r['event_id']
    a,c=await asyncio.gather(worker(),worker());assert a==c

async def test_audit_gagal_seluruh_stok_rollback(pg,world,monkeypatch):
    w=world;i=await create(pg,w);b=await body(pg,w,i)
    async with pg() as db:
        pre=await s.inspect(db,user=await db.get(User,w['user']),ident=i,req=b);await db.rollback()
    b.update(review=pre['review'],confirm=True)
    async def fail(*a,**kw):raise RuntimeError('Uji audit gagal sebelum commit')
    monkeypatch.setattr(s,'audit',fail)
    async with pg() as db:
        with pytest.raises(RuntimeError):await s.save(db,user=await db.get(User,w['user']),ident=i,req=b)
        await db.rollback()
    async with pg() as db:
        ctx=await s.context(db,user=await db.get(User,w['user']),ident=i);assert ctx['state']['quantity']=='40' and not ctx['history']
        assert ctx['balances']['None']['karung']==60

async def test_koreksi_karung_ditahan_jika_sumber_pemakaian_tidak_terbukti(pg,world):
    w=world;i=await create(pg,w,'karung',400)
    async with pg() as db:
        now=now_local();db.add(FinishedGoodsStock(product_sku_id=w['sku'],source_type='retur',source_id=None,jumlah_karung=100,berat_total_kg=5000,warehouse_id=w['wh'],waktu=now,input_by=w['user'],jasa_id=w['owners'][0],kemasan_mengurangi_stok=True));await db.commit()
    # The customer's pooled balance is 300 but the old packaging ledger
    # cannot prove which purchase was consumed. It must not invent a mapping.
    with pytest.raises(s.InventoryError,match='rekonsiliasi'):await change(pg,w,i,300)

async def test_karung_baru_tetap_dapat_dipindah_dari_sisa_pabrik(pg,world):
    w=world
    async with pg() as db:
        now=now_local();db.add(FinishedGoodsStock(product_sku_id=w['sku'],source_type='retur',source_id=None,jumlah_karung=100,berat_total_kg=5000,warehouse_id=w['wh'],waktu=now,input_by=w['user'],jasa_id=None,kemasan_mengurangi_stok=True));await db.commit()
    i=await create(pg,w,'karung',400)
    async with pg() as db:
        ctx=await s.context(db,user=await db.get(User,w['user']),ident=i);assert ctx['balances']['None']['lembar']==700 and ctx['state']['quantity']=='400'

async def test_tiket_timbang_dan_proses_tidak_disentuh(pg,world):
    from app.models import PolishingProcess,PolishingOutputLog,MillingProcess
    w=world;i=await create(pg,w)
    async with pg() as db:
        before={M.__tablename__:await db.scalar(select(func.count()).select_from(M)) for M in (PolishingProcess,PolishingOutputLog,MillingProcess)}
    await change(pg,w,i,30)
    async with pg() as db:
        assert before=={M.__tablename__:await db.scalar(select(func.count()).select_from(M)) for M in (PolishingProcess,PolishingOutputLog,MillingProcess)}

@pytest.mark.parametrize('mode,reason,confirm',[('ubah','   ',True),('batal','',True),('ubah','Valid',False)])
async def test_alasan_dan_konfirmasi_wajib(pg,world,mode,reason,confirm):
    w=world;i=await create(pg,w);b=await body(pg,w,i);b.update(mode=mode,reason=reason)
    async with pg() as db:
        user=await db.get(User,w['user'])
        if not reason.strip():
            with pytest.raises(s.InventoryError,match='Alasan'):await s.inspect(db,user=user,ident=i,req=b)
        else:
            pre=await s.inspect(db,user=user,ident=i,req=b);await db.rollback()
            b.update(review=pre['review'],confirm=confirm)
    if reason.strip():
        async with pg() as db:
            with pytest.raises(s.InventoryError,match='Konfirmasi'):await s.save(db,user=await db.get(User,w['user']),ident=i,req=b)

async def test_data_lama_tidak_direka_dan_tidak_dapat_dikoreksi(pg,world):
    from app.models import ActivityLog
    w=world
    async with pg() as db:
        e=ActivityLog(table_name='finished_goods_stock',record_id=w['source'],action='UPDATE',field_name='jasa_id',new_value='40 karung → pabrik',changed_by=w['user'],aksi='pindah_kepemilikan_produk',gudang='g2');db.add(e);await db.commit();uid=e.id
        d=await s.legacy_detail(db,user=await db.get(User,w['user']),ident=uid);assert d['legacy'] and 'rekonsiliasi' in d['warning']
        listing=await s.listing(db,user=await db.get(User,w['user']),legacy=True);assert listing['total']==1

async def test_pagination_hanya_halaman_aktif_dan_angka_hasil_benar(pg,world):
    w=world
    for _ in range(28):await create(pg,w,amount=1)
    async with pg() as db:
        user=await db.get(User,w['user']);a=await s.listing(db,user=user,page=1);b=await s.listing(db,user=user,page=2)
        assert a['total']==b['total']==28 and len(a['items'])==25 and len(b['items'])==3
        assert not {x['id'] for x in a['items']} & {x['id'] for x in b['items']}
        src=await s.sources(db,user=user,ident=a['items'][0]['id'],search='Pelanggan B');assert src['total']==1 and src['items'][0]['owner']==w['owners'][2]

@pytest.mark.parametrize('role,view,allowed',[('admin',None,True),('superadmin',None,True),('operator','operator:g1',False),('operator','operator:g2',False),('superadmin','operator:g2',False)])
async def test_endpoint_langsung_dan_peran_efektif(pg,world,role,view,allowed):
    from tests.pg.test_riwayat_giling import _klien
    from tests.pg.formulir import cap_formulir
    w=world;i=await create(pg,w);b=await body(pg,w,i)
    async with await _klien(pg,peran=role,gudang='Gudang 2',lihat=view) as c:
        if view:c.cookies.set('produksi_lihat',view)
        for url in ('/kepemilikan','/kepemilikan/'+str(i),'/api/kepemilikan','/api/kepemilikan/'+str(i),'/api/kepemilikan/'+str(i)+'/sumber'):
            r=await c.get(url);assert r.status_code==(200 if allowed else 403),(url,r.status_code,r.text[:200])
        r=await c.post('/api/kepemilikan/'+str(i)+'/periksa',json=b,headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==(200 if allowed else 403),r.text

async def test_csrf_dan_status_retry_bukan_jalan_bypass(pg,world):
    from tests.pg.test_riwayat_giling import _klien
    from tests.pg.formulir import cap_formulir
    w=world;i=await create(pg,w);b=await body(pg,w,i)
    async with await _klien(pg,peran='admin') as c:
        r=await c.post('/api/kepemilikan/'+str(i)+'/periksa',json=b);assert r.status_code==403
        r=await c.post('/api/kepemilikan/'+str(i)+'/periksa',json=b,headers={'X-CSRF-Token':cap_formulir(c)});assert r.status_code==200
        b.update(review=r.json()['review'],confirm=True)
        r=await c.post('/api/kepemilikan/'+str(i)+'/simpan',json=b,headers={'X-CSRF-Token':cap_formulir(c)});assert r.status_code==200,r.text
        eid=r.json()['event_id'];again=await c.post('/api/kepemilikan/'+str(i)+'/simpan',json=b,headers={'X-CSRF-Token':cap_formulir(c)});assert again.json()['event_id']==eid
        status=await c.get('/api/kepemilikan-status/'+b['key']);assert status.json()['recorded'] is True
    async with await _klien(pg,peran='operator',gudang='Gudang 2') as c:
        assert (await c.get('/api/kepemilikan-status/'+b['key'])).status_code==403

async def test_seed_visual_terisolasi(pg,world):
    """Optional UI seed; never points at production or modifies real accounts."""
    import os,json
    from pathlib import Path
    from tests.pg.test_riwayat_giling import _klien
    from app.models import ProduksiAkun
    if os.environ.get('UJI_KEPEMILIKAN_VISUAL')!='1':pytest.skip('Penyiapan visual dijalankan terpisah dengan database khusus.')
    w=world;i=await create(pg,w);k=await create(pg,w,'karung',400);b=await create(pg,w,'broken',D('2000.25'));bek=await create(pg,w,'bekatul',D('1000.15'))
    async with await _klien(pg,peran='admin') as c:
        assert (await c.get('/kepemilikan/'+str(i))).status_code==200
    async with pg() as db:
        acct=await db.scalar(select(ProduksiAkun).order_by(ProduksiAkun.id.desc()).limit(1))
        Path('../visual.json').write_text(json.dumps(dict(username=acct.username,password='rahasia123',goods=i,packaging=k,broken=b,bekatul=bek,world=w)))

async def test_ganti_baris_satu_pesanan_sekaligus_turun(pg,world):
    w=world;i=await create(pg,w)
    async with pg() as db:
        row=await db.get(FinishedGoodsStock,w['other']);row.jasa_id=w['owners'][0];await db.commit()
    r,_=await change(pg,w,i,30,source_ids=[w['other']])
    assert r['plan']['after']['owners']==[w['owners'][0]]
    assert D(r['plan']['after']['kg'])==1470
    assert all(x['source_id']==w['other'] for x in r['plan']['after']['lines'])

async def test_fifo_karung_memakai_tanggal_pembelian_lama(pg,world):
    from datetime import timedelta
    w=world
    async with pg() as db:
        old=PackagingPurchase(kode='PKP-LAMA',packaging_material_id=w['material'],package_size_id=w['size'],jumlah_lembar=20,tanggal=now_local().date()-timedelta(days=5),waktu=now_local(),input_by=w['user'])
        db.add(old);await db.commit();oid=old.id
    i=await create(pg,w,'karung',10)
    async with pg() as db:
        ctx=await s.context(db,user=await db.get(User,w['user']),ident=i)
        assert ctx['original']['lines'][0]['source_id']==oid

async def test_audit_portal_koreksi_pihak_tidak_membocorkan_sumber_lain(pg,world):
    from app.models.portal import PortalAccount
    from tests.pg.test_portal_pelanggan import client
    w=world;i=await create(pg,w)
    await change(pg,w,i,30,source_ids=[w['other']])
    async with pg() as db:
        accounts=[PortalAccount(username='audit-kepemilikan-'+str(k),pelanggan_id=pid,password_hash='unused',active=True,token_version=1) for k,pid in enumerate(w['customers'])]
        db.add_all(accounts);await db.commit()
    for index,account in enumerate(accounts):
        async with client(account) as c:
            r=await c.get('/pelanggan/audit?rentang=semua')
            assert r.status_code==200
            assert 'source_before' not in r.text and 'target_id' not in r.text
            if index==1:assert 'JAS-KOREKSI-0' not in r.text and 'Pelanggan A' not in r.text
            else:assert 'JAS-KOREKSI-2' not in r.text and 'Pelanggan B' not in r.text
