import copy,uuid,asyncio
from decimal import Decimal as D
import pytest
from sqlalchemy import select,func
from app.models import User,FinishedGoodsStock,ByproductStock,PackagingPurchase,Peristiwa
from app.services import kepemilikan as old,kepemilikan_detail as s
from tests.pg.test_kepemilikan_koreksi import world
pytestmark=pytest.mark.asyncio

async def req(db,w,kind,id,dest,quantity,**kw):
    u=await db.get(User,w['user']);ctx=await s.konteks(db,user=u,kind=kind,id=id,bulk_key=kw.get('bulk_key',''))
    return dict(destination=dest,quantity=D(str(quantity)),bulk=D(str(kw.get('bulk',0))),bulk_key=kw.get('bulk_key',''),note='Sesuai kesepakatan',baseline=ctx['baseline'],key=uuid.uuid4().hex)

async def save(pg,w,kind,id,dest,quantity,**kw):
    async with pg() as db:
        body=await req(db,w,kind,id,dest,quantity,**kw);u=await db.get(User,w['user'])
        plan=await s.periksa(db,user=u,kind=kind,id=id,req=body);await db.rollback()
    body.update(review=plan['review'],confirm=True)
    async with pg() as db:
        result=await s.simpan(db,user=await db.get(User,w['user']),kind=kind,id=id,req=body);await db.commit()
    return result,body

@pytest.mark.parametrize('kind',['barang','curah','karung'])
@pytest.mark.parametrize('direction',['ke_pabrik','ke_pelanggan','antar_pelanggan'])
async def test_tiga_arah_sumber_spesifik_dan_konservasi(pg,world,kind,direction):
    w=world;model=old.MODELS[kind];id=w[{'barang':'source','curah':'broken','karung':'pack'}[kind]]
    origin=None if direction=='ke_pelanggan' else w['customers'][0] if kind=='karung' else w['owners'][0]
    dest=None if direction=='ke_pabrik' else w['customers'][1] if kind=='karung' else w['owners'][2]
    async with pg() as db:
        row=await db.get(model,id);old.set_owner(row,kind,origin);await db.commit();before=old.raw(row)
        identity=s.identity(row,kind);physical=await old.physical(db,kind,identity)
    token='pabrik' if dest is None else ('pelanggan:' if kind=='karung' else 'jasa:')+str(dest)
    result,body=await save(pg,w,kind,id,token,10)
    async with pg() as db:
        assert await old.physical(db,kind,identity)==physical
        root=await db.get(Peristiwa,result['events'][0]);assert root.muatan['lines'][0]['source_id']==id
        assert root.muatan['owners']==[origin] and root.muatan['customer']==dest
        target=await db.get(model,root.muatan['lines'][0]['target_id']);assert old.owner(target,kind)==dest
        assert old.qty(target,kind)==10
        for field in ['source_type','source_id','warehouse_id','hpp_per_kg','packaging_material_id','package_size_id','brand_id']:
            if field in before:assert old.raw(target)[field]==before[field]
        retry=await s.simpan(db,user=await db.get(User,w['user']),kind=kind,id=id,req=body);await db.commit();assert retry['retry']
        assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis==s.OP))==1

async def test_bobot_nyata_dan_karung_curah_atomik(pg,world):
    w=world
    async with pg() as db:
        a=await db.get(FinishedGoodsStock,w['source']);a.jumlah_karung=20;a.berat_total_kg=998;a.source_type='timbangan';a.source_id=911
        bulk=FinishedGoodsStock(product_sku_id=w['sku'],source_type='timbangan',source_id=911,jasa_id=a.jasa_id,warehouse_id=w['wh'],jumlah_karung=0,berat_total_kg=150,curah_kemas_ulang=True,waktu=a.waktu,input_by=w['user'],kemasan_mengurangi_stok=False)
        db.add(bulk);await db.commit();bid=bulk.id
    result,_=await save(pg,w,'barang',w['source'],'pabrik',10,bulk_key='curah_barang:'+str(bid),bulk=25)
    async with pg() as db:
        assert (await db.get(FinishedGoodsStock,w['source'])).berat_total_kg==D('499')
        assert (await db.get(FinishedGoodsStock,bid)).berat_total_kg==125
        assert len(result['events'])==2
        assert (await db.get(Peristiwa,result['events'][0])).muatan['kg']=='499.00'

async def test_pemakaian_karung_tidak_ikut_berpindah_dan_pembatalan_tetap_konsisten(pg,world):
    from app.penggilingan.inventory.packaging import hitung_stok_kemasan
    from tests.pg.test_kepemilikan_koreksi import change
    w=world
    async with pg() as db:
        a=await db.get(FinishedGoodsStock,w['source']);a.kemasan_mengurangi_stok=True;await db.commit()
        async def balances(db):return [await hitung_stok_kemasan(db,w['material'],w['size'],None,pelanggan_id=p) for p in [None,*w['customers']]]
        before=await balances(db)
    result,_=await save(pg,w,'barang',w['source'],'jasa:'+str(w['owners'][2]),30)
    async with pg() as db:assert await balances(db)==before
    root=result['events'][0]
    await change(pg,w,root,20)
    async with pg() as db:assert await balances(db)==before
    await change(pg,w,root,mode='batal')
    async with pg() as db:assert await balances(db)==before

@pytest.mark.parametrize('quantity',['0','-1','1.5','NaN','Infinity'])
async def test_jumlah_tidak_sah_tidak_menulis(pg,world,quantity):
    async with pg() as db:
        u=await db.get(User,world['user']);body=await req(db,world,'barang',world['source'],'pabrik',quantity)
        with pytest.raises(old.InventoryError):await s.periksa(db,user=u,kind='barang',id=world['source'],req=body)
        await db.rollback()
        assert await db.scalar(select(func.count()).select_from(Peristiwa))==0

async def test_sumber_terkunci_pemilik_dan_pagination(pg,world):
    from app.models import Pelanggan,Jasa
    w=world
    async with pg() as db:
        u=await db.get(User,w['user']);body=await req(db,w,'barang',w['source'],'jasa:'+str(w['owners'][1]),10)
        with pytest.raises(old.InventoryError,match='sama'):await s.periksa(db,user=u,kind='barang',id=w['source'],req=body)
        await db.rollback()
        for i in range(35):
            p=Pelanggan(nama_pelanggan=f'Tujuan pencarian {i:02}');db.add(p);await db.flush();db.add(Jasa(kode=f'JAS-CARI-{i}',pelanggan_id=p.id,status='berjalan'))
        await db.commit()
        u=await db.get(User,w['user']);first=await s.pelanggan(db,user=u,kind='barang',id=w['source'],q='Tujuan pencarian',page=1);second=await s.pelanggan(db,user=u,kind='barang',id=w['source'],q='Tujuan pencarian',page=2)
        assert first['total']==second['total']==35 and len(first['items'])==20 and len(second['items'])==15
        assert not {x['value'] for x in first['items']} & {x['value'] for x in second['items']}
        rows=await s.daftar_produk(db,user=u,jenis='beras_putih',owners=[w['owners'][0]])
        assert rows['total']==1 and rows['items'][0]['url'].endswith('/'+str(w['source']))

async def test_konflik_saldo_memerlukan_tinjau_ulang(pg,world):
    w=world
    async with pg() as db:
        body=await req(db,w,'barang',w['source'],'pabrik',30);pre=await s.periksa(db,user=await db.get(User,w['user']),kind='barang',id=w['source'],req=body);await db.rollback()
        row=await db.get(FinishedGoodsStock,w['source']);row.jumlah_karung=25;row.berat_total_kg=1250;await db.commit()
        body.update(review=pre['review'],confirm=True)
        with pytest.raises(old.InventoryError,match='berubah'):await s.simpan(db,user=await db.get(User,w['user']),kind='barang',id=w['source'],req=body)
        await db.rollback();assert await db.scalar(select(func.count()).select_from(Peristiwa))==0

async def test_rollback_seluruh_bagian_jika_bagian_kedua_gagal(pg,world,monkeypatch):
    w=world
    async with pg() as db:
        row=await db.get(FinishedGoodsStock,w['source']);row.source_type='timbangan';row.source_id=911
        bulk=FinishedGoodsStock(product_sku_id=w['sku'],source_type='timbangan',source_id=911,jasa_id=row.jasa_id,warehouse_id=w['wh'],jumlah_karung=0,berat_total_kg=150,curah_kemas_ulang=True,waktu=row.waktu,input_by=w['user'],kemasan_mengurangi_stok=False);db.add(bulk);await db.commit();bid=bulk.id
        body=await req(db,w,'barang',w['source'],'pabrik',20,bulk_key='curah_barang:'+str(bid),bulk=25);pre=await s.periksa(db,user=await db.get(User,w['user']),kind='barang',id=w['source'],req=body);await db.rollback()
    writer=old.initial
    async def fail_second(*args,**kwargs):
        if kwargs['kind']=='curah_barang':raise old.InventoryError('Gagal bagian kedua')
        return await writer(*args,**kwargs)
    monkeypatch.setattr(old,'initial',fail_second);body.update(review=pre['review'],confirm=True)
    async with pg() as db:
        with pytest.raises(old.InventoryError):await s.simpan(db,user=await db.get(User,w['user']),kind='barang',id=w['source'],req=body)
        await db.rollback();assert (await db.get(FinishedGoodsStock,w['source'])).jumlah_karung==100
        assert (await db.get(FinishedGoodsStock,bid)).berat_total_kg==150
        assert await db.scalar(select(func.count()).select_from(Peristiwa))==0

async def test_operator_baca_saja_dan_gudang_efektif(pg,world):
    from app.models import Warehouse
    w=world
    async with pg() as db:
        op=User(nama='Operator uji',role='operator',status='aktif',default_warehouse_id=w['wh']);db.add(op);await db.commit()
        ctx=await s.konteks(db,user=op,kind='barang',id=w['source']);assert not ctx['can_transfer']
        body=await req(db,w,'barang',w['source'],'pabrik',1)
        with pytest.raises(PermissionError):await s.periksa(db,user=op,kind='barang',id=w['source'],req=body)
        wh=await db.scalar(select(Warehouse).where(Warehouse.kode_fungsi=='g1'));op.default_warehouse_id=wh.id
        with pytest.raises(PermissionError):await s.konteks(db,user=op,kind='barang',id=w['source'])

@pytest.mark.parametrize('role,warehouse,view,read,write',[
 ('admin',None,None,True,True),('superadmin',None,None,True,True),
 ('operator','Gudang 2',None,True,False),('operator','Gudang 1',None,False,False),
 ('superadmin','Gudang 2','operator:g2',True,False)])
async def test_endpoint_detail_pemeriksaan_dan_izin_efektif(pg,world,role,warehouse,view,read,write):
    from tests.pg.test_riwayat_giling import _klien
    from tests.pg.formulir import cap_formulir
    w=world;body=await _body_for_endpoint(pg,w)
    async with await _klien(pg,peran=role,gudang=warehouse,lihat=view) as client:
        if view:client.cookies.set('produksi_lihat',view)
        for url in [f'/stok/sumber/barang/{w["source"]}',f'/api/stok-sumber/barang/{w["source"]}']:
            response=await client.get(url);assert response.status_code==(200 if read else 403),response.text[:300]
        r=await client.post(f'/api/stok-sumber/barang/{w["source"]}/periksa',json=body,headers={'X-CSRF-Token':cap_formulir(client)})
        assert r.status_code==(200 if write else 403),r.text[:300]

async def _body_for_endpoint(pg,w):
    async with pg() as db:
        body=await req(db,w,'barang',w['source'],'pabrik',10)
        return {k:str(v) if isinstance(v,D) else v for k,v in body.items()}

async def test_seed_visual_detail_terisolasi(pg,world):
    import os,json
    from pathlib import Path
    from tests.pg.test_riwayat_giling import _klien
    if os.environ.get('UJI_DETAIL_VISUAL')!='1':pytest.skip('Penyiapan visual hanya dijalankan terpisah.')
    async with await _klien(pg,peran='admin') as client:
        assert (await client.get('/stok/sumber/barang/'+str(world['source']))).status_code==200
    from app.models import ProduksiAkun
    async with pg() as db:
        acct=await db.scalar(select(ProduksiAkun).order_by(ProduksiAkun.id.desc()).limit(1))
        Path('../visual-detail.json').write_text(json.dumps(dict(username=acct.username,password='rahasia123',world=world)))

async def test_dua_penyimpan_bersamaan_tidak_mengambil_saldo_ganda(pg,world):
    w=world;bodies=[]
    for _ in range(2):
        async with pg() as db:
            b=await req(db,w,'barang',w['source'],'pabrik',70);pre=await s.periksa(db,user=await db.get(User,w['user']),kind='barang',id=w['source'],req=b);await db.rollback();b.update(review=pre['review'],confirm=True);bodies.append(b)
    async def worker(body):
        async with pg() as db:
            try:
                result=await s.simpan(db,user=await db.get(User,w['user']),kind='barang',id=w['source'],req=body);await db.commit();return result
            except old.InventoryError:
                await db.rollback();return None
    results=await asyncio.gather(*(worker(b) for b in bodies));assert sum(x is not None for x in results)==1
    async with pg() as db:
        assert (await db.get(FinishedGoodsStock,w['source'])).jumlah_karung==30
        assert await db.scalar(select(func.count()).select_from(Peristiwa).where(Peristiwa.jenis==s.OP))==1

async def test_daftar_sumber_dibatasi_sql_dan_konteks_kembali(pg,world):
    from app.web.kepemilikan_detail import kembali_detail
    w=world
    async with pg() as db:
        src=await db.get(FinishedGoodsStock,w['source'])
        for _ in range(29):
            data=old.raw(src);data.pop('id');data.pop('waktu');data.pop('tanggal',None)
            # Konstruktor hanya nilai native, waktu memakai objek asli.
            data['waktu']=src.waktu;db.add(FinishedGoodsStock(**data))
        await db.commit();u=await db.get(User,w['user'])
        a=await s.daftar_produk(db,user=u,jenis='beras_putih',owners=[w['owners'][0]],page=1);b=await s.daftar_produk(db,user=u,jenis='beras_putih',owners=[w['owners'][0]],page=2)
        assert a['total']==b['total']==30 and len(a['items'])==25 and len(b['items'])==5
    path='/stok/karung/detail?material=biasa&ukuran=50&pemilik=pabrik&sumber_page=2'
    assert kembali_detail(path)==path
    assert kembali_detail('https://evil.example/stok/karung/detail')=='/stok'

@pytest.mark.parametrize('jenis',['menir','reject','bekatul'])
async def test_curah_lain_memakai_jenis_yang_benar(pg,world,jenis):
    w=world
    async with pg() as db:
        row=await db.get(ByproductStock,w['broken']);row.jenis_produk=jenis;await db.commit()
        before=await old.physical(db,'curah',dict(jenis=jenis))
    await save(pg,w,'curah',w['broken'],'jasa:'+str(w['owners'][2]),'125.25')
    async with pg() as db:
        assert await old.physical(db,'curah',dict(jenis=jenis))==before
        assert D((await old.balance(db,'curah',dict(jenis=jenis),w['owners'][2]))['kg'])==D('125.25')

@pytest.mark.parametrize('kind,jenis,quantity,weight',[('barang','beras_putih',20,1000),('curah','broken',D('125.25'),D('125.25'))])
async def test_pembaca_stok_dan_rekap_jasa_seimbang(pg,world,kind,jenis,quantity,weight):
    from app.services.stok import stok_produk,nama_produk
    from app.services.jasa import rekap_barang_jasa
    w=world;source=w['source'] if kind=='barang' else w['broken']
    async def read(db,owner):
        cards=await stok_produk(db,jasa_id=owner)
        stock=sum(D(str(c.sisa_kg)) for c in cards if c.jenis==jenis)
        rekap=await rekap_barang_jasa(db,owner)
        summary=sum(D(str(r['kg'])) for r in rekap['sisa'] if r['nama'].casefold()==nama_produk(jenis).casefold())
        assert stock==summary
        return stock
    async with pg() as db:before=[await read(db,o) for o in [w['owners'][0],w['owners'][2]]]
    await save(pg,w,kind,source,'jasa:'+str(w['owners'][2]),quantity)
    async with pg() as db:
        after=[await read(db,o) for o in [w['owners'][0],w['owners'][2]]]
        assert after==[before[0]-D(str(weight)),before[1]+D(str(weight))]

async def test_portal_pdf_dan_rekap_setelah_pindah_tidak_menulis_stok(pg,world):
    from io import BytesIO
    from pypdf import PdfReader
    from app.models.portal import PortalAccount
    from tests.pg.test_portal_pelanggan import client
    w=world
    await save(pg,w,'barang',w['source'],'jasa:'+str(w['owners'][2]),20)
    async with pg() as db:
        accounts=[PortalAccount(username='uji-detail-'+str(i),pelanggan_id=pid,password_hash='unused',active=True,token_version=1) for i,pid in enumerate(w['customers'])];db.add_all(accounts);await db.commit()
        before=[old.raw(x) for x in (await db.scalars(select(FinishedGoodsStock).order_by(FinishedGoodsStock.id))).all()]
        events=await db.scalar(select(func.count()).select_from(Peristiwa))
    for account,order,expected in [(accounts[0],w['owners'][0],'4.000'),(accounts[1],w['owners'][2],'4.920')]:
        async with client(account) as c:
            r=await c.get(f'/pelanggan/jasa/{order}/nota');assert r.status_code==200 and expected in r.text
            pdf=await c.get(f'/pelanggan/jasa/{order}/nota.pdf');assert pdf.status_code==200,pdf.text[:100]
            text='\n'.join(p.extract_text() or '' for p in PdfReader(BytesIO(pdf.content)).pages);assert expected in text
            other=w['owners'][2] if order==w['owners'][0] else w['owners'][0]
            assert (await c.get(f'/pelanggan/jasa/{other}/nota.pdf')).status_code==404
            assert (await c.get('/stok/sumber/barang/'+str(w['source']))).status_code in (303,403)
    async with pg() as db:
        assert [old.raw(x) for x in (await db.scalars(select(FinishedGoodsStock).order_by(FinishedGoodsStock.id))).all()]==before
        assert await db.scalar(select(func.count()).select_from(Peristiwa))==events

async def test_baris_curah_satu_partai_tetap_dapat_dipilih_di_halaman_berikut(pg,world):
    w=world
    async with pg() as db:
        a=await db.get(FinishedGoodsStock,w['source']);a.source_type='timbangan';a.source_id=911
        for _ in range(30):db.add(FinishedGoodsStock(product_sku_id=w['sku'],source_type='timbangan',source_id=911,jasa_id=a.jasa_id,warehouse_id=w['wh'],jumlah_karung=0,berat_total_kg=1,curah_kemas_ulang=True,waktu=a.waktu,input_by=w['user'],kemasan_mengurangi_stok=False))
        await db.commit();u=await db.get(User,w['user'])
        one=await s.konteks(db,user=u,kind='barang',id=w['source']);two=await s.konteks(db,user=u,kind='barang',id=w['source'],bulk_page=2)
        assert one['bulk_total']==two['bulk_total']==30
        assert len(one['bulk_options'])==25 and len(two['bulk_options'])==5
        assert not {r['key'] for r in one['bulk_options']} & {r['key'] for r in two['bulk_options']}
        key=two['bulk_options'][-1]['key']
    result,_=await save(pg,w,'barang',w['source'],'pabrik',0,bulk_key=key,bulk=1)
    assert len(result['events'])==1

async def test_contoh_karung_dan_curah_terikat_tetap_terpisah(pg,world):
    from app.models import OutgoingRecord,OutgoingItem,ProductSku
    from app.database import now_local
    w=world
    async with pg() as db:
        sku=await db.get(ProductSku,w['sku']);sku.kategori='broken'
        source=await db.get(FinishedGoodsStock,w['source']);source.jumlah_karung=60;source.berat_total_kg=3000;source.source_type='timbangan';source.source_id=911
        bulk=await db.get(ByproductStock,w['broken']);bulk.berat_kg=150;bulk.source_type=source.source_type;bulk.source_id=source.source_id
        now=now_local();record=OutgoingRecord(kode='OUT-TERIKAT',tanggal=now.date(),waktu=now,input_by=w['user'],status='perintah');db.add(record);await db.flush()
        db.add_all([OutgoingItem(outgoing_record_id=record.id,item_type='finished_goods',product_sku_id=w['sku'],jasa_id=w['owners'][0],jumlah_karung_perintah=10,berat_perintah_kg=500,jumlah_karung=0,berat_kg=0),OutgoingItem(outgoing_record_id=record.id,item_type='byproduct_curah',jenis_byproduct='broken',jasa_id=w['owners'][0],berat_perintah_kg=25,berat_kg=0)])
        await db.commit();u=await db.get(User,w['user'])
        ctx=await s.konteks(db,user=u,kind='barang',id=source.id,bulk_key='curah:'+str(bulk.id))
        assert [D(x['available']) for x in ctx['parts']]==[D(50),D(125)]
    result,_=await save(pg,w,'barang',w['source'],'pabrik',20,bulk_key='curah:'+str(w['broken']),bulk=25)
    async with pg() as db:
        ctx=await s.konteks(db,user=await db.get(User,w['user']),kind='barang',id=w['source'],bulk_key='curah:'+str(w['broken']))
        assert [D(x['total']) for x in ctx['parts']]==[D(40),D(125)]
        assert [D(x['available']) for x in ctx['parts']]==[D(30),D(100)]
        assert len(result['events'])==2

async def test_koreksi_transaksi_baru_tidak_melewati_reservasi_tujuan(pg,world):
    from app.models import OutgoingItem,OutgoingRecord
    from app.database import now_local
    from tests.pg.test_kepemilikan_koreksi import change
    w=world;result,_=await save(pg,w,'barang',w['source'],'jasa:'+str(w['owners'][2]),20)
    async with pg() as db:
        # Pool tujuan lama 80 karung ditambah 20; perintah masih memegang 90.
        now=now_local();record=OutgoingRecord(kode='OUT-TUJUAN-TERIKAT',tanggal=now.date(),waktu=now,input_by=w['user'],status='perintah');db.add(record);await db.flush()
        db.add(OutgoingItem(outgoing_record_id=record.id,item_type='finished_goods',product_sku_id=w['sku'],jasa_id=w['owners'][2],jumlah_karung_perintah=90,jumlah_karung=0,berat_perintah_kg=4500,berat_kg=0));await db.commit()
    with pytest.raises(old.InventoryError):await change(pg,w,result['events'][0],mode='batal')
    # Mengembalikan hanya 5 dari bagian bebas tetap sah.
    await change(pg,w,result['events'][0],15)
