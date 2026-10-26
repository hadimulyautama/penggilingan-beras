"""Pratinjau memakai alokasi layanan; stok dan pembatalan diuji pada PG nyata."""
import pytest
from sqlalchemy import select,func,update,text
from app.models import (User,FinishedGoodsStock,ProductSku,BerasKeSilo,ActivityLog,
                        PolishingOutputLog,PolishingProcess,Warehouse)
from app.services.rencana_beras_silo import rincian
from app.penggilingan.gudang2 import service as g2
from tests.pg.test_masukkan_beras_silo import sosoh,_kemas_grade
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir
pytestmark=pytest.mark.asyncio


@pytest.mark.parametrize('bentuk',['curah','kemasan','curah_tercatat'])
async def test_rencana_baca_saja_sama_dengan_baris_simpan(pg,sosoh,bentuk):
    await _kemas_grade(pg,sosoh,grade='medium',jumlah_karung=40)
    async with pg() as db:
        row=await db.scalar(select(FinishedGoodsStock))
        if bentuk=='curah_tercatat':
            row.curah_kemas_ulang=True;row.jumlah_karung=0;await db.commit()
        pilihan='curah' if bentuk=='curah' else f'curah:{row.id}' if bentuk=='curah_tercatat' else f'sku:{row.product_sku_id}'
        sumber=pilihan+'|pabrik'
    async with pg() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        before=await rincian(db,'medium|pabrik',sumber)
        p=await rincian(db,'medium|pabrik',sumber,250,'C')
        assert p['rencana']['kg']==250 and p['rencana']['sisa_kg']==before['saldo_kg']-250
        assert await db.scalar(select(func.count()).select_from(BerasKeSilo))==0
        assert await db.scalar(select(func.sum(FinishedGoodsStock.berat_total_kg)))==1000
    async with await _klien(pg,sosoh['user'],'beras-rencana',mode='admin') as c:
        r=await c.post('/api/actions/masukkan-beras-silo',json=dict(jenis='medium|pabrik',sumber_stok=sumber,berat_kg=250,silo='C'),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200,r.text
        actual=r.json()['rincian_beras'];assert actual['kg']==250
        assert actual['setelah']['saldo_kg']==p['rencana']['sisa_kg']
        assert actual['karung']==(10 if bentuk=='kemasan' else 0)
    async with pg() as db:
        assert await db.scalar(select(func.sum(BerasKeSilo.berat_kg)))==250
        assert await g2.hitung_stok_silo(db,sosoh['silo_beras'])==250
        if bentuk=='kemasan':assert (await rincian(db,'medium|pabrik','curah|pabrik'))['saldo_kg']==7000
        if bentuk=='curah':assert (await rincian(db,'medium|pabrik',f'sku:{row.product_sku_id}|pabrik'))['karung']==40


@pytest.mark.parametrize('kg',[0,-1,'NaN','Infinity','abc',''])
async def test_pratinjau_tidak_mengarang_rencana_untuk_isian_salah(pg,sosoh,kg):
    async with pg() as db:
        d=await rincian(db,'medium|pabrik','curah|pabrik',kg)
        assert d['rencana'] is None and d['saldo_kg']==8000
        assert await db.scalar(select(func.count()).select_from(BerasKeSilo))==0


@pytest.mark.parametrize('kg,valid',[(250,True),(250.009,True),(250.011,False),(251,False)])
async def test_toleransi_kelipatan_kemasan_identik_dengan_layanan(pg,sosoh,kg,valid):
    await _kemas_grade(pg,sosoh,grade='medium',jumlah_karung=40)
    async with pg() as db:
        row=await db.scalar(select(FinishedGoodsStock));src=f'sku:{row.product_sku_id}'
        d=await rincian(db,'medium|pabrik',src+'|pabrik',kg)
        assert (d['rencana'] is not None)==valid
        if valid:
            await g2.masukkan_beras_ke_silo(db,user=await db.get(User,sosoh['user']),jenis='medium',sumber_stok=src,berat_kg=kg,nama_silo='C')
        else:
            with pytest.raises(g2.Gudang2Error):await g2.masukkan_beras_ke_silo(db,user=await db.get(User,sosoh['user']),jenis='medium',sumber_stok=src,berat_kg=kg,nama_silo='C')


async def test_saldo_berubah_setelah_pratinjau_ditolak_tanpa_alokasi_lain(pg,sosoh):
    await _kemas_grade(pg,sosoh,grade='medium',jumlah_karung=40)
    async with pg() as db:
        row=await db.scalar(select(FinishedGoodsStock));src=f'sku:{row.product_sku_id}|pabrik'
        assert (await rincian(db,'medium|pabrik',src,1000))['rencana']
        row.jumlah_karung=10;row.berat_total_kg=250;await db.commit()
    async with await _klien(pg,sosoh['user'],'beras-berubah',mode='admin') as c:
        r=await c.post('/api/actions/masukkan-beras-silo',json=dict(jenis='medium|pabrik',sumber_stok=src,berat_kg=1000,silo='C'),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==400 and '10 karung' in r.text
    async with pg() as db:assert await db.scalar(select(func.count()).select_from(BerasKeSilo))==0


@pytest.mark.parametrize('role,view,wh,izin',[
 ('operator',None,'g2',True),('operator',None,'g1',False),('admin',None,'g2',False),('superadmin',None,'g2',True),
 ('admin','operator:g2','g2',True),('admin','operator:g1','g1',False),('superadmin','operator:g1','g1',False),('staff',None,'g2',False)])
async def test_izin_ringkasan_dan_post_tetap_mengikuti_view_efektif(pg,sosoh,role,view,wh,izin):
    async with pg() as db:
        u=await db.get(User,sosoh['user']);u.role=role
        wid=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi==wh).limit(1))
        if wid is None:w=Warehouse(nama_gudang='Gudang uji hak',kode_fungsi=wh);db.add(w);await db.flush();wid=w.id
        u.default_warehouse_id=wid;await db.commit()
    async with await _klien(pg,sosoh['user'],'beras-izin',mode='operator' if role=='operator' else 'admin') as c:
        if view:assert (await c.post('/lihat-sebagai',data={'peran':view,'_csrf':cap_formulir(c)})).status_code==303
        r=await c.get('/api/actions/rincian-beras-silo',params=dict(jenis='medium|pabrik',sumber_stok='curah|pabrik',berat_kg='10'))
        assert (r.status_code==200) if izin else r.status_code in [401,403]
        r=await c.post('/api/actions/masukkan-beras-silo',json=dict(jenis='medium|pabrik',sumber_stok='curah|pabrik',berat_kg=10,silo='C'),headers={'X-CSRF-Token':cap_formulir(c)})
        assert (r.status_code==200) if izin else r.status_code in [401,403]


async def test_fifo_curah_seluruh_proses_dan_pemeriksaan_asal_kedua(pg,sosoh):
    from app.database import now_local
    from app.models import PolishingSiloUsage
    async with pg() as db:
        await db.execute(update(PolishingOutputLog).values(berat_kg=100))
        p=PolishingProcess(kode_proses='POL-UJIR-KEDUA',status='proses',waktu_mulai=now_local(),created_by=sosoh['user']);db.add(p);await db.flush()
        db.add(PolishingOutputLog(polishing_process_id=p.id,jenis='medium',berat_kg=200,waktu_update=now_local(),input_by=sosoh['user']))
        db.add(PolishingSiloUsage(polishing_process_id=p.id,silo_id=sosoh['silo_beras'],berat_awal_kg=1000));await db.commit()
        d=await rincian(db,'medium|pabrik','curah|pabrik',150,'C')
        assert [r['kg']for r in d['rencana']['fifo']]==[100,50]
        assert d['rencana']['fifo'][1]['kode']=='POL-UJIR-KEDUA'
        with pytest.raises(g2.Gudang2Error,match='sedang memakai'):
            await g2.masukkan_beras_ke_silo(db,user=await db.get(User,sosoh['user']),jenis='medium',sumber_stok='curah',berat_kg=150,nama_silo='C')
        await db.rollback();assert await db.scalar(select(func.count()).select_from(BerasKeSilo))==0


@pytest.mark.parametrize('jasa',[False,True])
async def test_tujuan_proses_lain_pabrik_diperbolehkan_jasa_ditolak(pg,sosoh,jasa):
    from app.database import now_local
    from app.models import PolishingSiloUsage,Jasa,Pelanggan
    async with pg() as db:
        jid=None
        if jasa:
            pel=Pelanggan(nama_pelanggan='Pemilik beras uji');db.add(pel);await db.flush();j=Jasa(kode='JAS-BERAS-NATIVE',pelanggan_id=pel.id);db.add(j);await db.flush();jid=j.id
            (await db.get(PolishingProcess,sosoh['proc_id'])).jasa_id=jid
        p=PolishingProcess(kode_proses='POL-UJIR-PENERIMA',status='proses',waktu_mulai=now_local(),created_by=sosoh['user'],jasa_id=jid);db.add(p);await db.flush()
        db.add(PolishingSiloUsage(polishing_process_id=p.id,silo_id=sosoh['silo_beras'],berat_awal_kg=1000));await db.commit()
        args=dict(user=await db.get(User,sosoh['user']),jenis='medium',sumber_stok='curah',berat_kg=100,nama_silo='C',jasa_id=jid)
        if jasa:
            with pytest.raises(g2.Gudang2Error,match='beras jasa'):await g2.masukkan_beras_ke_silo(db,**args)
            await db.rollback();assert await db.scalar(select(func.count()).select_from(BerasKeSilo))==0
        else:
            await g2.masukkan_beras_ke_silo(db,**args)
            usage=await db.scalar(select(PolishingSiloUsage).where(PolishingSiloUsage.polishing_process_id==p.id))
            assert float(usage.berat_masuk_kg)==100
            assert (await db.get(PolishingProcess,p.id)).status=='proses'


async def test_dua_kiriman_kemasan_tidak_memakai_karung_sama(pg,sosoh):
    import asyncio
    await _kemas_grade(pg,sosoh,grade='medium',jumlah_karung=10)
    async with pg() as db:sku=(await db.scalar(select(FinishedGoodsStock))).product_sku_id
    async def kirim():
        async with pg() as db:
            return await g2.masukkan_beras_ke_silo(db,user=await db.get(User,sosoh['user']),jenis='medium',sumber_stok=f'sku:{sku}',berat_kg=200,nama_silo='C')
    results=await asyncio.gather(kirim(),kirim(),return_exceptions=True)
    assert sum(isinstance(r,g2.Gudang2Error)for r in results)==1,results
    async with pg() as db:
        assert await db.scalar(select(func.sum(BerasKeSilo.berat_kg)))==200
        assert await db.scalar(select(func.sum(FinishedGoodsStock.jumlah_karung)))==2


async def test_gagal_audit_membatalkan_semua_alokasi(pg,sosoh,monkeypatch):
    await _kemas_grade(pg,sosoh,grade='medium',jumlah_karung=40)
    async with pg() as db:sku=(await db.scalar(select(FinishedGoodsStock))).product_sku_id
    async def gagal(*a,**kw):raise RuntimeError('Gangguan audit uji')
    monkeypatch.setattr(g2,'log_activity',gagal)
    with pytest.raises(RuntimeError,match='Gangguan audit'):
        async with pg() as db:await g2.masukkan_beras_ke_silo(db,user=await db.get(User,sosoh['user']),jenis='medium',sumber_stok=f'sku:{sku}',berat_kg=250,nama_silo='C')
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(BerasKeSilo))==0
        assert await db.scalar(select(func.sum(FinishedGoodsStock.jumlah_karung)))==40
        assert await g2.hitung_stok_silo(db,sosoh['silo_beras'])==0


async def test_beberapa_merek_ukuran_dan_tanpa_merek_tetap_terpisah(pg,sosoh):
    from app.penggilingan.inventory.finished_goods import catat_packing
    async with pg() as db:
        u=await db.get(User,sosoh['user'])
        for brand,size,n in [('Sakura',25,4),(None,50,2),('Sakura',5,10)]:
            await catat_packing(db,user=u,kode_pol=sosoh['kode_pol'],kategori='beras_putih',grade='medium',brand_nama=brand,material_kode='biasa',ukuran=size,jumlah_karung=n)
        rows=(await db.scalars(select(FinishedGoodsStock).order_by(FinishedGoodsStock.id))).all()
        data=[await rincian(db,'medium|pabrik',f'sku:{r.product_sku_id}|pabrik')for r in rows]
        assert [(r['merek'],r['ukuran'],r['saldo_kg'])for r in data]==[('Sakura',25,100),('Tanpa merek',50,100),('Sakura',5,50)]
        raw=(await rincian(db,'medium|pabrik','curah|pabrik'))['saldo_kg']
        await g2.masukkan_beras_ke_silo(db,user=u,jenis='medium',sumber_stok=f'sku:{rows[0].product_sku_id}',nama_silo='C',berat_kg=50)
        assert (await rincian(db,'medium|pabrik','curah|pabrik'))['saldo_kg']==raw
        assert (await rincian(db,'medium|pabrik',f'sku:{rows[1].product_sku_id}|pabrik'))['saldo_kg']==100
        assert (await rincian(db,'medium|pabrik',f'sku:{rows[2].product_sku_id}|pabrik'))['saldo_kg']==50


async def test_beras_b_olah_ulang_tetap_jenis_dan_sku_asli(pg,sosoh):
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.database import now_local
    async with pg() as db:
        db.add(PolishingOutputLog(polishing_process_id=sosoh['proc_id'],jenis='beras_b',berat_kg=300,waktu_update=now_local(),input_by=sosoh['user']));await db.commit()
        u=await db.get(User,sosoh['user'])
        await catat_packing(db,user=u,kode_pol=sosoh['kode_pol'],kategori='beras_b',material_kode='biasa',ukuran=25,jumlah_karung=4)
        row=await db.scalar(select(FinishedGoodsStock));src=f'sku:{row.product_sku_id}'
        d=await rincian(db,'beras_b|pabrik',src+'|pabrik',50,'C');assert d['rencana']['karung']==2 and d['jenis']=='beras_b'
        await g2.masukkan_beras_ke_silo(db,user=u,jenis='beras_b',sumber_stok=src,nama_silo='C',berat_kg=50)
        assert (await db.scalar(select(BerasKeSilo))).jenis=='beras_b'
        assert (await rincian(db,'medium|pabrik','curah|pabrik'))['saldo_kg']==8000


async def test_pemilik_pelanggan_tidak_tercampur_meskipun_nama_sama(pg,sosoh):
    from app.models import Jasa,Pelanggan
    await _kemas_grade(pg,sosoh,grade='medium',jumlah_karung=10)
    async with pg() as db:
        ids=[]
        for i in range(2):
            pel=Pelanggan(nama_pelanggan='Nama pelanggan sama');db.add(pel);await db.flush();j=Jasa(kode=f'JAS-BERAS-PEMILIK-{i}',pelanggan_id=pel.id);db.add(j);await db.flush();ids.append(j.id)
        row=await db.scalar(select(FinishedGoodsStock));row.jasa_id=ids[0]
        extra=FinishedGoodsStock(product_sku_id=row.product_sku_id,rice_quality_standard_id=row.rice_quality_standard_id,source_type=row.source_type,source_id=row.source_id,jasa_id=ids[1],jumlah_karung=4,berat_total_kg=100,warehouse_id=row.warehouse_id,waktu=row.waktu,input_by=row.input_by)
        db.add(extra);await db.commit()
        a=await rincian(db,'medium|jasa',f'sku:{row.product_sku_id}|{ids[0]}',50)
        b=await rincian(db,'medium|jasa',f'sku:{row.product_sku_id}|{ids[1]}',50)
        assert a['saldo_kg']==250 and b['saldo_kg']==100
        assert a['rencana']['fifo'][0]['stok_id']==row.id and b['rencana']['fifo'][0]['stok_id']==extra.id
        assert a['jasa_id']!=b['jasa_id']


async def test_hasil_membaca_saldo_pemilik_kanonis_setelah_penggabungan_lama(pg,sosoh):
    from app.models import Jasa,Pelanggan
    from app.database import now_local
    await _kemas_grade(pg,sosoh,grade='medium',jumlah_karung=10)
    async with pg() as db:
        pel=Pelanggan(nama_pelanggan='Pemilik dua pesanan');db.add(pel);await db.flush()
        j1=Jasa(kode='JAS-BERAS-SURVIVOR',pelanggan_id=pel.id);j2=Jasa(kode='JAS-BERAS-DIGABUNG',pelanggan_id=pel.id);db.add_all([j1,j2]);await db.flush()
        row=await db.scalar(select(FinishedGoodsStock));row.jasa_id=j2.id
        (await db.get(PolishingProcess,sosoh['proc_id'])).jasa_id=j2.id
        db.add(BerasKeSilo(kode_pindah='BRS-UJI-SEPEMILIK',source_type='timbangan',source_id=777,jenis='medium',silo_id=sosoh['silo_beras'],berat_kg=10,tanggal=now_local().date(),waktu=now_local(),input_by=sosoh['user'],jasa_id=j1.id))
        await db.commit();source=f'sku:{row.product_sku_id}|{j2.id}';survivor=j1.id
    async with await _klien(pg,sosoh['user'],'beras-gabung',mode='admin') as c:
        r=await c.post('/api/actions/masukkan-beras-silo',json=dict(jenis='medium|jasa',sumber_stok=source,berat_kg=50,silo='C'),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200,r.text
        after=r.json()['rincian_beras']['setelah'];assert after['jasa_id']==survivor and after['saldo_kg']==200
        assert after['karung']==8


@pytest.mark.parametrize('asal',['timbangan','retur'])
async def test_riwayat_sumber_non_proses_tetap_utuh_sampai_kemasan_habis(pg,sosoh,asal):
    from app.models import CustomerReturn,CustomerReturnItem
    from app.database import now_local
    await _kemas_grade(pg,sosoh,grade='medium',jumlah_karung=4)
    async with pg() as db:
        row=await db.scalar(select(FinishedGoodsStock));rid=row.id;row.source_type=asal;row.source_id=12345
        if asal=='retur':
            ret=CustomerReturn(kode='RET-FORM-BERAS',timbangan_transaksi_id=12345,kode_tiket='TKT-FORM-BERAS',berat_tiket_kg=100,berat_rincian_kg=100,selisih_kg=0,input_by=sosoh['user'],waktu=now_local());db.add(ret);await db.flush();row.source_id=ret.id
            ri=CustomerReturnItem(customer_return_id=ret.id,product_sku_id=row.product_sku_id,rice_quality_standard_id=row.rice_quality_standard_id,jumlah_karung=4,berat_total_kg=100,finished_goods_stock_id=row.id);db.add(ri);await db.flush();return_item_id=ri.id
        await db.commit();source=f'sku:{row.product_sku_id}|pabrik'
        d=await rincian(db,'medium|pabrik',source,100,'C')
        assert d['rencana']['fifo'][0]['source_type']==asal and d['rencana']['fifo'][0]['proses_id'] is None
    async with await _klien(pg,sosoh['user'],'beras-asal',mode='admin') as c:
        r=await c.post('/api/actions/masukkan-beras-silo',json=dict(jenis='medium|pabrik',sumber_stok=source,berat_kg=100,silo='C'),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200,r.text
        assert r.json()['rincian_beras']['setelah']['saldo_kg']==0
    async with pg() as db:
        move=await db.scalar(select(BerasKeSilo));assert move.polishing_process_id is None and move.source_type==asal
        if asal=='retur':
            row=await db.get(FinishedGoodsStock,rid);assert row.jumlah_karung==0 and row.berat_total_kg==0
            assert (await db.get(CustomerReturnItem,return_item_id)).finished_goods_stock_id==rid
