"""Menir tetap kg/FIFO pemilik; Reject memakai alokasi domain yang sama."""
import asyncio
import pytest
import pytest_asyncio
from sqlalchemy import select,func,update,text
from app.models import (User,Silo,Warehouse,PolishingOutputLog,PolishingProcess,
    PolishingSiloUsage,HasilSampingKeSilo,ActivityLog,OutgoingRecord,OutgoingItem,
    Jasa,Pelanggan,FinishedGoodsStock)
from app.database import now_local
from app.penggilingan.gudang2 import service as g2
from app.services.rencana_menir_silo import rincian
from tests.pg.test_masukkan_beras_silo import sosoh
from tests.pg.test_barang_keluar import _klien
from tests.pg.formulir import cap_formulir
pytestmark=pytest.mark.asyncio

@pytest_asyncio.fixture
async def menir(pg,sosoh):
    async with pg() as db:
        p=PolishingProcess(kode_proses='POL-MENIR-KEDUA',status='proses',waktu_mulai=now_local(),created_by=sosoh['user']);db.add(p);await db.flush()
        for pid,w in [(sosoh['proc_id'],450),(p.id,500)]:
            for jenis in ['menir','reject']:db.add(PolishingOutputLog(polishing_process_id=pid,jenis=jenis,berat_kg=w,waktu_update=now_local(),input_by=sosoh['user']))
        asal=await db.get(Silo,sosoh['silo_pk']);dest=Silo(nama_silo='Silo Campuran Timur',warehouse_id=asal.warehouse_id,jenis_isi='pk');db.add(dest);await db.flush()
        await db.commit();return dict(**sosoh,p2=p.id,dest=dest.id)

async def kirim(db,m,kg=275,owner=None,jenis='menir'):
    return await g2.masukkan_hasil_samping_ke_silo(db,user=await db.get(User,m['user']),jenis=jenis,jasa_id=owner,nama_silo='Campuran Timur',berat_kg=kg)

async def keluar(db,m,kg,jenis='menir',sku=None):
    r=OutgoingRecord(kode='OUT-MENIR-UJI-'+str(kg),tanggal=now_local().date(),waktu=now_local(),input_by=m['user'],status='selesai');db.add(r);await db.flush()
    db.add(OutgoingItem(outgoing_record_id=r.id,item_type='finished_goods' if sku else 'byproduct_curah',product_sku_id=sku,jenis_byproduct=None if sku else jenis,berat_kg=kg));await db.commit()

@pytest.mark.parametrize('jenis',['menir','reject'])
async def test_fifo_pengeluaran_dahulu_sama_dengan_layanan_lama(pg,menir,jenis):
    async with pg() as db:
        await keluar(db,menir,300,jenis)
        from app.penggilingan.gudang2.rencana_hasil_samping import saldo_sumber,alokasikan
        d=await saldo_sumber(db,jenis,None);assert d['saldo_kg']==650
        assert [w for _,w in alokasikan(d,jenis,275)]==[150,125]
        await kirim(db,menir,jenis=jenis)
        rows=(await db.scalars(select(HasilSampingKeSilo).order_by(HasilSampingKeSilo.id))).all()
        assert [float(r.berat_kg)for r in rows]==[150,125]
        assert [r.polishing_process_id for r in rows]==[menir['proc_id'],menir['p2']]
        assert (await saldo_sumber(db,jenis,None))['saldo_kg']==375
        assert await g2.hitung_stok_silo(db,menir['dest'])==275
        assert (await db.get(PolishingProcess,menir['p2'])).status=='proses'
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.table_name=='hasil_samping_ke_silo'))==2

async def test_pratinjau_dalam_transaksi_read_only_dan_hasil_http(pg,menir):
    async with pg() as db:await keluar(db,menir,300)
    async with pg() as db:
        await db.execute(text('SET TRANSACTION READ ONLY'))
        d=await rincian(db,'pabrik',275,'Campuran Timur')
        assert d['saldo_kg']==650 and d['rencana']['sisa_kg']==375
        assert [r['kg'] for r in d['rencana']['fifo']]==[150,125]
        assert await db.scalar(select(func.count()).select_from(HasilSampingKeSilo))==0
    async with await _klien(pg,menir['user'],'menir-save',mode='admin') as c:
        r=await c.post('/api/actions/masukkan-menir-silo',json=dict(pemilik='pabrik',silo='Campuran Timur',berat_kg=275),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200,r.text
        d=r.json()['rincian_menir'];assert d['kg']==275 and d['setelah']['saldo_kg']==375 and len(d['codes'])==2

@pytest.mark.parametrize('kg',[0,-1,'NaN','Infinity','abc',''])
async def test_berat_tidak_sah_tidak_menghasilkan_rencana_atau_simpan(pg,menir,kg):
    async with pg() as db:
        d=await rincian(db,'pabrik',kg);assert d['rencana'] is None and d['saldo_kg']==950
    async with await _klien(pg,menir['user'],'menir-invalid',mode='admin') as c:
        r=await c.post('/api/actions/masukkan-menir-silo',json=dict(pemilik='pabrik',silo='Campuran Timur',berat_kg=kg),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==422

@pytest.mark.parametrize('kg',[275.25,950,950.004])
async def test_desimal_seluruh_saldo_dan_toleransi_tetap(pg,menir,kg):
    async with pg() as db:
        d=await rincian(db,'pabrik',kg);await kirim(db,menir,kg)
        assert float(await db.scalar(select(func.sum(HasilSampingKeSilo.berat_kg))))==min(kg,950)
        assert (await rincian(db,'pabrik'))['saldo_kg']==max(0,950-kg)
        assert d['rencana']['sisa_kg']==max(0,950-kg)

async def test_saldo_berubah_ditolak_tanpa_penulisan_tambahan(pg,menir):
    async with pg() as db:
        assert (await rincian(db,'pabrik',900))['rencana']
        await kirim(db,menir,100)
        with pytest.raises(g2.Gudang2Error,match='tersedia'):await kirim(db,menir,900)
        await db.rollback();assert await db.scalar(select(func.sum(HasilSampingKeSilo.berat_kg)))==100

@pytest.mark.parametrize('role,view,wh,izin',[
 ('operator',None,'g2',True),('operator',None,'g1',False),('admin',None,'g2',False),('superadmin',None,'g2',True),
 ('admin','operator:g2','g2',True),('admin','operator:g1','g1',False),('superadmin','operator:g1','g1',False),('staff',None,'g2',False)])
async def test_izin_baca_simpan_dan_view_efektif(pg,menir,role,view,wh,izin):
    async with pg() as db:
        u=await db.get(User,menir['user']);u.role=role
        wid=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi==wh).limit(1))
        if wid is None:w=Warehouse(nama_gudang='Gudang uji hak',kode_fungsi=wh);db.add(w);await db.flush();wid=w.id
        u.default_warehouse_id=wid;await db.commit()
    async with await _klien(pg,menir['user'],'menir-izin',mode='operator' if role=='operator' else 'admin') as c:
        if view:assert (await c.post('/lihat-sebagai',data={'peran':view,'_csrf':cap_formulir(c)})).status_code==303
        r=await c.get('/api/actions/rincian-menir-silo',params=dict(pemilik='pabrik',berat_kg='10'))
        assert r.status_code==200 if izin else r.status_code in [401,403]
        r=await c.post('/api/actions/masukkan-menir-silo',json=dict(pemilik='pabrik',berat_kg=10,silo='Campuran Timur'),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200 if izin else r.status_code in [401,403]

@pytest.mark.parametrize('jasa',[False,True])
async def test_pabrik_ke_proses_lain_jasa_ditolak(pg,menir,jasa):
    async with pg() as db:
        jid=None
        if jasa:
            pel=Pelanggan(nama_pelanggan='Pemilik menir');db.add(pel);await db.flush();j=Jasa(kode='JAS-MENIR-UJI',pelanggan_id=pel.id);db.add(j);await db.flush();jid=j.id
            await db.execute(update(PolishingProcess).values(jasa_id=jid))
        p=PolishingProcess(kode_proses='POL-MENIR-PENERIMA',status='proses',waktu_mulai=now_local(),created_by=menir['user'],jasa_id=jid);db.add(p);await db.flush()
        u=PolishingSiloUsage(polishing_process_id=p.id,silo_id=menir['dest'],berat_awal_kg=1000);db.add(u);await db.commit();pid=p.id
        if jasa:
            with pytest.raises(g2.Gudang2Error,match='stok jasa'):await kirim(db,menir,100,jid)
            await db.rollback();assert await db.scalar(select(func.count()).select_from(HasilSampingKeSilo))==0
            await db.refresh(u);assert float(u.berat_masuk_kg or 0)==0
        else:
            await kirim(db,menir,100);await db.refresh(u);assert float(u.berat_masuk_kg)==100
        assert (await db.get(PolishingProcess,pid)).status=='proses'

async def test_asal_kedua_juga_dilarang_ke_silonya_sendiri(pg,menir):
    async with pg() as db:
        db.add(PolishingSiloUsage(polishing_process_id=menir['p2'],silo_id=menir['dest'],berat_awal_kg=1000));await db.commit()
        d=await rincian(db,'pabrik',500,'Campuran Timur');assert d['peringatan_tujuan']
        with pytest.raises(g2.Gudang2Error,match='sedang memakai'):await kirim(db,menir,500)
        await db.rollback();assert await db.scalar(select(func.count()).select_from(HasilSampingKeSilo))==0

async def test_pindah_kepemilikan_hanya_bagian_haknya_dan_pengiriman_kemasan(pg,menir):
    from app.penggilingan.inventory.finished_goods import catat_packing
    async with pg() as db:
        await catat_packing(db,user=await db.get(User,menir['user']),kode_pol=menir['kode_pol'],kategori='menir',material_kode='putih',ukuran=50,jumlah_karung=2)
        row=await db.scalar(select(FinishedGoodsStock))
        pel=Pelanggan(nama_pelanggan='Pemilik bagian');db.add(pel);await db.flush();j=Jasa(kode='JAS-MENIR-PINDAH',pelanggan_id=pel.id);db.add(j);await db.flush();row.jasa_id=j.id;await db.commit()
        assert (await rincian(db,str(j.id)))['saldo_kg']==100
        assert (await rincian(db,'pabrik'))['saldo_kg']==850
        await kirim(db,menir,75,j.id)
        assert (await rincian(db,str(j.id)))['saldo_kg']==25
        assert (await rincian(db,'pabrik'))['saldo_kg']==850
        assert row.jumlah_karung==2 # Ledger pemindahan lama; bukan bongkar karung Broken.

async def test_gagal_audit_kedua_rollback_seluruh_alokasi(pg,menir,monkeypatch):
    import app.services.activity_log as audit
    original=audit.log_activity;n=0
    async def gagal(*a,**kw):
        nonlocal n;n+=1
        if n==2:raise RuntimeError('Gangguan audit terisolasi')
        return await original(*a,**kw)
    monkeypatch.setattr(audit,'log_activity',gagal)
    with pytest.raises(RuntimeError,match='Gangguan audit'):
        async with pg() as db:await kirim(db,menir,500)
    async with pg() as db:
        assert await db.scalar(select(func.count()).select_from(HasilSampingKeSilo))==0
        assert await g2.hitung_stok_silo(db,menir['dest'])==0

@pytest.mark.parametrize('jenis',['menir','reject'])
async def test_dua_kiriman_memeriksa_saldo_terbaru(pg,menir,jenis):
    async def satu():
        async with pg() as db:return await kirim(db,menir,600,jenis=jenis)
    results=await asyncio.gather(satu(),satu(),return_exceptions=True)
    async with pg() as db:
        total=float(await db.scalar(select(func.coalesce(func.sum(HasilSampingKeSilo.berat_kg),0))))
        assert total==600, (total,[str(x) for x in results])
        assert sum(isinstance(r,g2.Gudang2Error)for r in results)==1

async def test_pengiriman_kemasan_dan_curah_saldo_sama_dengan_stok(pg,menir):
    from app.penggilingan.inventory.finished_goods import catat_packing
    from app.services.stok import stok_produk
    async with pg() as db:
        await catat_packing(db,user=await db.get(User,menir['user']),kode_pol=menir['kode_pol'],kategori='menir',material_kode='putih',ukuran=50,jumlah_karung=4)
        row=await db.scalar(select(FinishedGoodsStock));await keluar(db,menir,100,sku=row.product_sku_id);await keluar(db,menir,200)
        for kg in [0,275]:
            if kg:await kirim(db,menir,kg)
            d=await rincian(db,'pabrik');card=next(k for k in await stok_produk(db) if k.jenis=='menir')
            assert d['saldo_kg']==card.sisa_kg==650-kg
        assert row.jumlah_karung==4

@pytest.mark.parametrize('salah',['pemilik','silo','komoditas'])
async def test_tujuan_dan_pemilik_tetap_dijaga(pg,menir,salah):
    async with pg() as db:
        if salah=='pemilik':
            pel=Pelanggan(nama_pelanggan='Pemilik silo lain');db.add(pel);await db.flush();j=Jasa(kode='JAS-MENIR-LAIN',pelanggan_id=pel.id);db.add(j);await db.flush()
            db.add(HasilSampingKeSilo(kode_pindah='HSS-PEMILIK-LAIN',polishing_process_id=menir['proc_id'],jenis='menir',silo_id=menir['dest'],berat_kg=10,tanggal=now_local().date(),waktu=now_local(),input_by=menir['user'],jasa_id=j.id));await db.commit()
        elif salah=='komoditas':
            (await db.get(Silo,menir['dest'])).komoditas_diizinkan=['beras_putih'];await db.commit()
        else:
            (await db.get(Silo,menir['dest'])).aktif=False;await db.commit()
        before=await db.scalar(select(func.count()).select_from(HasilSampingKeSilo))
        with pytest.raises(g2.Gudang2Error):await kirim(db,menir,100)
        await db.rollback();assert await db.scalar(select(func.count()).select_from(HasilSampingKeSilo))==before

async def test_pelanggan_sendiri_dan_nama_sama_tidak_tercampur(pg,menir):
    async with pg() as db:
        ids=[]
        for i in range(2):
            pel=Pelanggan(nama_pelanggan='Nama sama');db.add(pel);await db.flush();j=Jasa(kode=f'JAS-MENIR-{i}',pelanggan_id=pel.id);db.add(j);await db.flush();ids.append(j.id)
        (await db.get(PolishingProcess,menir['proc_id'])).jasa_id=ids[0]
        (await db.get(PolishingProcess,menir['p2'])).jasa_id=ids[1];await db.commit()
        assert (await rincian(db,str(ids[0])))['saldo_kg']==450
        assert (await rincian(db,str(ids[1])))['saldo_kg']==500
        await kirim(db,menir,450,ids[0])
        assert (await rincian(db,str(ids[0])))['saldo_kg']==0
        assert (await rincian(db,str(ids[1])))['saldo_kg']==500
        assert (await db.scalar(select(HasilSampingKeSilo))).jasa_id==ids[0]

async def test_picker_master_dan_kontrak_reject_tidak_berubah(pg,menir):
    async with await _klien(pg,menir['user'],'menir-picker',mode='admin') as c:
        opt=(await c.get('/api/actions/silo-hasil-samping-g2?jenis=menir')).json()
        assert any(x['value']=='Campuran Timur' for x in opt)
        owners=(await c.get('/api/actions/hasil-samping-pemilik-tersedia?jenis=menir')).json()
        assert [x['value']for x in owners]==['pabrik']
        r=await c.post('/api/actions/masukkan-reject-silo',json=dict(pemilik='pabrik',silo='Campuran Timur',berat_kg=125.5),headers={'X-CSRF-Token':cap_formulir(c)})
        assert r.status_code==200 and set(r.json())=={'ok','pesan','rincian_reject'}
        assert r.json()['rincian_reject']['kg']==125.5
    async with pg() as db:
        assert (await db.scalar(select(HasilSampingKeSilo))).jenis=='reject'
        assert (await rincian(db,'pabrik'))['saldo_kg']==950

async def test_undo_lama_belum_mendukung_hss_dinyatakan_jujur(pg,menir):
    from app.services.undo import undo_last,UndoError
    async with pg() as db:
        await kirim(db,menir,100)
        log=await db.scalar(select(ActivityLog).where(ActivityLog.table_name=='hasil_samping_ke_silo').order_by(ActivityLog.id.desc()))
        with pytest.raises(UndoError,match='belum bisa dibatalkan otomatis'):
            await undo_last(db,actor=await db.get(User,menir['user']),cakupan=None,log_id=log.id)
        await db.rollback();assert await db.scalar(select(func.sum(HasilSampingKeSilo.berat_kg)))==100
