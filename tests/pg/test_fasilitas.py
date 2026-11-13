import pytest
from sqlalchemy import select,func
from app.models import Warehouse,User,Dryer,LiniProduksi,JenisProsesProduksi,AuditFasilitas,DryingLot,PolishingProcess
from app.services.fasilitas import simpan_jenis,simpan_lini,pilih_lini,FasilitasError
from app.services.seed import seed_master
from app.database import now_local
pytestmark=pytest.mark.asyncio

async def dunia(pg):
    await seed_master()
    async with pg() as db:
        wh=list((await db.execute(select(Warehouse).order_by(Warehouse.id))).scalars())
        u=User(nama='Pengelola uji',role='superadmin',status='aktif');db.add(u)
        ops=[User(nama='Operator '+str(w.id),role='operator',status='aktif',default_warehouse_id=w.id) for w in wh]
        db.add_all(ops);await db.commit();return u,wh,ops

async def test_awal_tetap_satu_alat_per_jenis_dan_seed_idempoten(pg):
    await dunia(pg)
    async with pg() as db:
        assert [await db.scalar(select(func.count()).select_from(m)) for m in (Dryer,LiniProduksi,JenisProsesProduksi)]==[1,3,3]
        ids=list((await db.execute(select(LiniProduksi.id).order_by(LiniProduksi.id))).scalars())
    await seed_master()
    async with pg() as db:
        assert list((await db.execute(select(LiniProduksi.id).order_by(LiniProduksi.id))).scalars())==ids

async def test_master_edit_audit_versi_dan_operator_ditolak(pg):
    u,wh,ops=await dunia(pg)
    async with pg() as db:
        j=await simpan_jenis(db,user=u,nama='Jenis uji',kode='uji-baru');await db.commit();jid=j.id
        assert await db.scalar(select(func.count()).select_from(AuditFasilitas))==1
        with pytest.raises(PermissionError):await simpan_jenis(db,user=ops[0],nama='Tidak berhak',kode='ilegal')
        j=await simpan_jenis(db,user=u,id=jid,versi=1,nama='Nama diperbarui',kode='uji-baru');await db.commit();assert j.id==jid and j.versi==2
        with pytest.raises(FasilitasError,match='berubah'):await simpan_jenis(db,user=u,id=jid,versi=1,nama='Usang',kode='uji-baru')
        await db.rollback()
        with pytest.raises(FasilitasError,match='Kode jenis tetap'):await simpan_jenis(db,user=u,id=jid,versi=2,nama='Nama',kode='beda')

@pytest.mark.fondasi_multi
async def test_dua_line_independen_satu_line_dipakai_dan_izin(pg):
    u,wh,ops=await dunia(pg)
    async with pg() as db:
        j=await db.scalar(select(JenisProsesProduksi).where(JenisProsesProduksi.kode=='penyosohan'));jid=j.id
        awal=await db.scalar(select(LiniProduksi).where(LiniProduksi.jenis_proses_id==jid));aid=awal.id
        kedua=await simpan_lini(db,user=u,kode='sosoh-uji-2',nama='Line uji kedua',warehouse_id=wh[1].id,jenis_proses_id=jid);await db.commit();kid=kedua.id
        a=await pilih_lini(db,user=ops[1],kode_jenis='penyosohan',lini_id=aid)
        db.add(PolishingProcess(kode_proses='POL-UJI-LINE',status='proses',waktu_mulai=now_local(),created_by=ops[1].id,lini_produksi_id=a.id));await db.commit()
        with pytest.raises(FasilitasError,match='masih digunakan'):await pilih_lini(db,user=ops[1],kode_jenis='penyosohan',lini_id=aid)
        await db.rollback()
        assert (await pilih_lini(db,user=ops[1],kode_jenis='penyosohan',lini_id=kid)).id==kid
        with pytest.raises(FasilitasError):await pilih_lini(db,user=ops[0],kode_jenis='penyosohan',lini_id=kid)

async def test_dryer_g2_dan_izin_gudang(pg):
    u,wh,ops=await dunia(pg)
    async with pg() as db:
        j=await db.scalar(select(JenisProsesProduksi).where(JenisProsesProduksi.kode=='pengeringan'))
        d=Dryer(warehouse_id=wh[1].id,nama='Dryer uji G2',kapasitas_kg=20000,status='aktif');db.add(d);await db.flush()
        line=await simpan_lini(db,user=u,kode='dryer-uji-g2',nama=d.nama,warehouse_id=wh[1].id,jenis_proses_id=j.id,dryer_id=d.id);await db.commit()
        from app.penggilingan.gudang1.services.drying import pilih_dryer,DryingError
        assert (await pilih_dryer(db,d.id,user=ops[1])).id==d.id
        with pytest.raises(DryingError):await pilih_dryer(db,d.id,user=ops[0])
        assert (await pilih_lini(db,user=ops[1],kode_jenis='pengeringan',dryer_id=d.id)).id==line.id
        assert await db.scalar(select(func.count()).select_from(DryingLot))==0

async def test_dryer_g2_memulai_dan_menyelesaikan_tanpa_mengubah_bobot_asal(pg):
    from app.models import Supplier,PurchaseBatch
    from app.penggilingan.gudang1.services.drying import masuk_dryer,start_drying,finish_drying
    u,wh,ops=await dunia(pg)
    async with pg() as db:
        j=await db.scalar(select(JenisProsesProduksi).where(JenisProsesProduksi.kode=='pengeringan'))
        d=Dryer(warehouse_id=wh[1].id,nama='Dryer uji G2',kapasitas_kg=30000,status='aktif');db.add(d);await db.flush()
        l=await simpan_lini(db,user=u,kode='dryer-g2',nama=d.nama,warehouse_id=wh[1].id,jenis_proses_id=j.id,dryer_id=d.id)
        supplier=Supplier(nama_supplier='Pemasok fasilitas');db.add(supplier);await db.flush()
        b=PurchaseBatch(kode_batch='GB-UJI-FASILITAS',supplier_id=supplier.id,berat_total_kg=15000,kondisi_gabah='basah',tanggal_pembelian=now_local().date(),waktu_pembelian=now_local(),input_by=ops[1].id,status_batch='baru',flag_unverified=False,sumber_berat='manual');db.add(b);await db.commit();bid=b.id
        await masuk_dryer(db,user=ops[1],kode_batch_list=[b.kode_batch],dryer_id=d.id)
        r=await start_drying(db,user=ops[1],dryer_id=d.id,target_kadar_air=15,mode_dryer='15T')
        assert r.lot.lini_produksi_id==l.id
        await finish_drying(db,user=ops[1],kode_lot=r.lot.kode_lot,kadar_air_akhir=15)
        assert (await db.get(PurchaseBatch,bid)).berat_total_kg==15000
        from app.models import Silo,SiloStorage
        from app.penggilingan.gudang1.services.drying import finish_cooling
        from app.penggilingan.gudang1.services.silo import moving_finished
        sg=Silo(nama_silo='Silo Gabah Uji G2',warehouse_id=wh[1].id,jenis_isi='gabah',komoditas_diizinkan=['gabah_kering'],status='kosong');db.add(sg);await db.commit()
        await finish_cooling(db,user=ops[1],kode_lot=r.lot.kode_lot)
        await moving_finished(db,user=ops[1],nama_silo='Gabah Uji G2',kode_lot=r.lot.kode_lot)
        stored=await db.scalar(select(SiloStorage).where(SiloStorage.drying_lot_id==r.lot.id))
        assert stored.silo_id==sg.id
        assert (await db.get(PurchaseBatch,bid)).berat_total_kg==15000


@pytest.mark.parametrize('role,view,expected',[('superadmin',None,200),('admin',None,403),('operator',None,403),('superadmin','operator:g2',403)])
async def test_pengaturan_endpoint_dan_lihat_sebagai(pg,role,view,expected):
    await dunia(pg)
    from tests.pg.test_riwayat_giling import _klien
    from tests.pg.formulir import cap_formulir
    from app.web.lihat_sebagai import NAMA_KUKI
    async with await _klien(pg,peran='superadmin') as pengelola:
        pass
    async with await _klien(pg,peran=role,gudang='Gudang 2') as c:
        if view:c.cookies.set(NAMA_KUKI,view)
        r=await c.get('/pengaturan/fasilitas');assert r.status_code==expected,r.text
        if expected==200:assert r.url.path=='/pengaturan/mesin'
        if expected==200:
            assert 'Mesin &amp; line produksi' in r.text
            assert (await c.get('/pengaturan/jenis-proses')).status_code==200
            assert 'name="_csrf"' in r.text
        response=await c.post('/pengaturan/fasilitas',data={'_csrf':cap_formulir(c),'objek':'jenis','kode':'uji-web','nama':'Uji web','aktif':'on'})
        assert response.status_code==expected,response.text

from tests.pg.test_gudang2_operator_pg import gudang2

@pytest.mark.fondasi_multi
async def test_dua_proses_sosoh_terpisah_hasil_dan_silo(pg,gudang2):
    from app.penggilingan.gudang2 import polishing as p,service as g2
    from app.models import PolishingSiloUsage,PolishingOutputLog
    async with pg() as db:
        op=await db.get(User,gudang2['user'].id)
        jid=await db.scalar(select(JenisProsesProduksi.id).where(JenisProsesProduksi.kode=='penyosohan'))
        first=await db.scalar(select(LiniProduksi).where(LiniProduksi.jenis_proses_id==jid))
        second=LiniProduksi(kode='uji-kedua',nama='Line kedua khusus uji',warehouse_id=op.default_warehouse_id,jenis_proses_id=jid,aktif=True,versi=1);db.add(second);await db.commit()
        await g2.pindah_tumpukan_ke_silo(db,user=op,intake_id=gudang2['intake_tumpukan'],nama_silo='A',berat=1000)
        a=(await p.mulai_penyosohan(db,user=op,nama_silos=['A'],lini_id=first.id)).proc
        from app.services.berjalan import _kartu_silo_g2,_isian_silo
        async def asal(sid):return await _isian_silo(db,sid)
        cards=await _kartu_silo_g2(db,asal)
        assert any(k.kode=='Silo B' and k.aksi=='mulai_penyosohan' for k in cards)
        b=(await p.mulai_penyosohan(db,user=op,nama_silos=['B'],lini_id=second.id)).proc
        assert a.id!=b.id and a.lini_produksi_id!=b.lini_produksi_id
        for proc,kg in ((a,500),(b,6000)):
            await p.catat_output(db,user=op,kode=proc.kode_proses,jenis='medium',berat_kumulatif=kg)
        assert (await p._output_map(db,a.id))['medium']==500
        assert (await p._output_map(db,b.id))['medium']==6000
        assert await db.scalar(select(func.count()).select_from(PolishingSiloUsage))==2
        await p.selesai_penyosohan(db,user=op,kode=a.kode_proses,nama_silo='A',sisa_kg=100)
        assert await g2.hitung_stok_silo(db,(await g2.get_g2_silo(db,'A')).id)==100
        assert await g2.hitung_stok_silo(db,(await g2.get_g2_silo(db,'B')).id)==9800
        assert b.status=='proses'

async def test_dua_transaksi_tidak_dapat_mengklaim_line_yang_sama(pg):
    import asyncio
    u,wh,ops=await dunia(pg)
    async with pg() as db:
        j=await db.scalar(select(JenisProsesProduksi).where(JenisProsesProduksi.kode=='penyosohan'))
        line=await db.scalar(select(LiniProduksi).where(LiniProduksi.jenis_proses_id==j.id));lid=line.id
    async def klaim(n):
        async with pg() as db:
            try:
                await pilih_lini(db,user=ops[1],kode_jenis='penyosohan',lini_id=lid)
                db.add(PolishingProcess(kode_proses='POL-BALAP-'+str(n),status='proses',waktu_mulai=now_local(),created_by=ops[1].id,lini_produksi_id=lid));await db.commit();return 'ok'
            except FasilitasError:
                await db.rollback();return 'ditahan'
    assert sorted(await asyncio.gather(klaim(1),klaim(2)))==['ditahan','ok']
