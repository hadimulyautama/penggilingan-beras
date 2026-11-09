"""Master dinamis tidak boleh memutus stok, QC, sejarah atau izin efektif."""
import re
from types import SimpleNamespace
import pytest
import pytest_asyncio
from sqlalchemy import select, func, text
from app.models import User, RiceQualityStandard, SetelanPabrik, ActivityLog, PolishingProcess, PolishingOutputLog
from app.services import spesifikasi_beras as beras, jenis_hasil_samping as samping
from app.services.seed import seed_master
from app.database import now_local
from hmu_identitas import peran as P
from tests.pg.test_pengaturan_usulan import klien, kirim

pytestmark = pytest.mark.asyncio
URL='/pengaturan/spesifikasi-beras'
HS='/pengaturan/hasil-samping'

@pytest_asyncio.fixture
async def dunia(pg):
    await seed_master()
    c, _, uid = await klien(pg)
    async with pg() as db:
        user=await db.get(User,uid)
    yield c,user
    await c.aclose()

async def buat(db,user,nama='Ramos spesial'):
    row=await beras.simpan(db,user=user,nama=nama,broken='7,5',sosoh='110',aksi='tambah')
    await db.commit()
    return row

async def test_admin_kelola_dan_hapus_belum_dipakai(pg,dunia):
    c,user=dunia
    r=await kirim(c,URL+'/tambah',dict(nama='Ramos <uji>',broken='7,5',sosoh='110'),asal=URL)
    assert r.status_code==303
    async with pg() as db:
        row=next(r for r in await beras.rincian(db,pemakaian=True) if r['nama']=='Ramos <uji>')
        assert not row['dipakai'] and row['broken']=='7.5' and row['sosoh']=='110'
        assert row['kode'] in await beras.jenis_hasil(db)
        id_=row['id']
    page=await c.get(URL)
    assert 'Ramos &lt;uji&gt;' in page.text
    r=await kirim(c,URL+'/ubah',dict(id=id_,versi=row['versi'],nama='Ramos baru',broken='5',sosoh='105'),asal=URL)
    assert r.status_code==303
    # Form lama tidak boleh menimpa edit admin lain.
    stale=await kirim(c,URL+'/hapus',dict(id=id_,versi=row['versi']),asal=URL)
    assert stale.status_code==200 and 'telah berubah' in stale.text
    async with pg() as db:
        row=next(r for r in await beras.rincian(db) if r['id']==id_)
    assert (await kirim(c,URL+'/hapus',dict(id=id_,versi=row['versi']),asal=URL)).status_code==303
    async with pg() as db:
        assert await db.get(RiceQualityStandard,id_) is None
        assert await db.scalar(select(func.count()).select_from(ActivityLog).where(ActivityLog.record_id==id_,ActivityLog.aksi.like('spesifikasi_beras_%'))) == 3

async def test_hasil_baru_stok_neraca_qc_nonaktif(pg,dunia):
    c,user=dunia
    from app.penggilingan.gudang2 import polishing as p
    from app.services import stok, qc_sosoh
    async with pg() as db:
        row=await buat(db,user);kode=row.kode;id_=row.id
        proc=PolishingProcess(kode_proses='POL-MASTER',status='proses',waktu_mulai=now_local(),created_by=user.id)
        db.add(proc);await db.commit();pid=proc.id;pkode=proc.kode_proses
        await p.catat_output(db,user=user,kode=pkode,jenis=kode,berat_kumulatif=600)
        q=await qc_sosoh.ambil_sampel(db,user=user,kode_proses=proc.kode_proses,jenis=kode,waktu_sampel=now_local())
        assert q.jenis==kode
        hasil=await stok.output_sosoh(db,pid)
        assert p.beras_dari_output(hasil)==600
        assert p.neraca_sosoh(1000,hasil).keluar_kg==600
        assert stok.kategori_dan_mutu(kode)==('beras_putih',kode)
        assert stok.nama_produk(kode)=='Ramos spesial'
        rows=await stok.stok_produk(db)
        assert next(r for r in rows if r.jenis==kode).sisa_kg==600
        old=(await db.get(PolishingOutputLog,1)).berat_kg
        detail=next(r for r in await beras.rincian(db) if r['id']==id_)
        with pytest.raises(ValueError,match='sudah dipakai'):
            await beras.simpan(db,user=user,id_=id_,versi=detail['versi'],aksi='hapus')
        await db.rollback()
        await beras.simpan(db,user=user,id_=id_,versi=detail['versi'],aksi='nonaktifkan');await db.commit()
        assert kode not in await beras.jenis_hasil(db)
        from app.web.form_selesai_penyosohan import ringkasan
        current = await ringkasan(db, kode_proses=pkode)
        old_grade = next(r for r in current['hasil'] if r['jenis'] == kode)
        assert not old_grade['aktif'] and old_grade['kg'] == 600
        assert kode in await beras.jenis_hasil(db,termasuk_nonaktif=True)
        assert (await db.get(PolishingOutputLog,1)).berat_kg==old
        with pytest.raises(p.Gudang2Error,match='aktif'):
            await p.catat_output(db,user=user,kode=pkode,jenis=kode,berat_kumulatif=700)
        await db.rollback()
        assert (await stok.output_sosoh(db,pid))[kode]==600

@pytest.mark.parametrize('peran,gd',[(P.OPERATOR,'Gudang 1'),(P.OPERATOR,'Gudang 2')])
async def test_izin_server(pg,dunia,peran,gd):
    c,_,_=await klien(pg,peran,gd,username='master_operator')
    async with c:
        for url in (URL,HS):
            assert (await c.get(url)).status_code==403
            assert (await kirim(c,url+'/tambah',dict(nama='Bocor',broken='5',sosoh='100',bentuk='curah'))).status_code==403
    async with pg() as db:
        assert not await db.scalar(select(RiceQualityStandard.id).where(RiceQualityStandard.nama=='Bocor'))

@pytest.mark.parametrize('broken,sosoh',[('NaN','100'),('-1','100'),('101','100'),('5','Infinity'),('','100'),('5','-1'),('1.111','100')])
async def test_validasi_tanpa_mutasi(pg,dunia,broken,sosoh):
    _,user=dunia
    async with pg() as db:
        with pytest.raises(ValueError):
            await beras.simpan(db,user=user,nama='Tidak valid',broken=broken,sosoh=sosoh)
        await db.rollback()
        assert not await db.scalar(select(RiceQualityStandard.id).where(RiceQualityStandard.nama=='Tidak valid'))

async def test_hasil_samping_dinamis_otomatis_dan_riwayat(pg,dunia):
    _,user=dunia
    from app.penggilingan.gudang2 import polishing as p
    from app.services import stok
    async with pg() as db:
        kode=await samping.simpan(db,user=user,aksi='tambah',nama='Dedak halus',bentuk='karung',kg_karung='30');await db.commit()
        proc=PolishingProcess(kode_proses='POL-SAMPING-MASTER',status='proses',waktu_mulai=now_local(),created_by=user.id)
        db.add(proc);await db.commit();pid=proc.id;pkode=proc.kode_proses
        await p.catat_output(db,user=user,kode=pkode,jenis=kode,berat_kumulatif=95)
        hasil=await stok.output_sosoh(db,pid)
        assert p.neraca_sosoh(1000,hasil).keluar_kg==95
        assert stok._packing_otomatis(kode,95)==(30,3,90,5)
        card=next(r for r in await stok.stok_produk(db) if r.jenis==kode)
        assert card.sisa_kg==95 and card.jumlah_karung_otomatis==3 and card.curah_otomatis_kg==5
        row=next(r for r in await samping.rincian(db) if r['kode']==kode)
        assert row['dipakai']
        with pytest.raises(ValueError,match='sudah dipakai'):
            await samping.simpan(db,user=user,aksi='hapus',kode=kode,versi=row['versi'])
        await db.rollback()
        with pytest.raises(ValueError,match='tidak dapat diubah'):
            await samping.simpan(db,user=user,aksi='ubah',kode=kode,versi=row['versi'],nama='Dedak halus',bentuk='karung',kg_karung='40')
        await db.rollback()
        await samping.simpan(db,user=user,aksi='nonaktifkan',kode=kode,versi=row['versi']);await db.commit()
        assert kode not in await beras.jenis_hasil(db)
        assert stok._packing_otomatis(kode,95)==(30,3,90,5)
        assert (await stok.output_sosoh(db,pid))[kode]==95

async def test_hapus_default_tidak_dihidupkan_seed(pg,dunia):
    _,user=dunia
    async with pg() as db:
        row=next(r for r in await beras.rincian(db) if r['kode']=='sayur')
        assert row['nama']=='Ekonomis'
        await beras.simpan(db,user=user,id_=row['id'],versi=row['versi'],aksi='hapus');await db.commit()
        row=next(r for r in await samping.daftar(db) if r['kode']=='menir')
        await samping.simpan(db,user=user,kode='menir',versi=row['versi'],aksi='hapus');await db.commit()
    await seed_master()
    async with pg() as db:
        assert not await db.scalar(select(RiceQualityStandard.id).where(RiceQualityStandard.kode=='sayur'))
        assert 'menir' not in await beras.jenis_hasil(db)
        from app.penggilingan.gudang2.polishing import neraca_sosoh
        assert 'menir' not in {r.jenis for r in neraca_sosoh(1000, {}).samping}

@pytest.mark.parametrize('peran,view,allow',[(P.SUPERADMIN,None,True),(P.ADMIN,None,True),(P.SUPERADMIN,'operator:g2',False)])
async def test_peran_efektif_dan_navigasi(pg,dunia,peran,view,allow):
    from app.web.lihat_sebagai import NAMA_KUKI
    c,_,_=await klien(pg,peran,username='master_guard',nama='Pengelola Master')
    if view:c.cookies.set(NAMA_KUKI,view)
    async with c:
        home=await c.get('/pengaturan')
        for url in (URL,HS):
            assert (f'href="{url}"' in home.text)==allow
            assert (await c.get(url)).status_code==(200 if allow else 403)
        if not allow:
            assert (await kirim(c,HS+'/tambah',dict(nama='Bocor',bentuk='curah'))).status_code==403

async def test_samping_curah_hapus_dan_pilihan_keluar(pg,dunia):
    c,user=dunia
    from app.penggilingan.gudang2 import polishing as p
    from app.services import stok
    from app.services.barang_keluar import tersedia, BarisPerintah
    async with pg() as db:
        kode=await samping.simpan(db,user=user,aksi='tambah',nama='Tepung beras',bentuk='curah');await db.commit()
        row=next(r for r in await samping.daftar(db) if r['kode']==kode)
        assert not await samping.dipakai(db,kode)
        await samping.simpan(db,user=user,aksi='hapus',kode=kode,versi=row['versi']);await db.commit()
        assert kode not in await beras.jenis_hasil(db)
        kode=await samping.simpan(db,user=user,aksi='tambah',nama='Tepung beras',bentuk='curah');await db.commit()
        proc=PolishingProcess(kode_proses='POL-CURAH-MASTER',status='proses',waktu_mulai=now_local(),created_by=user.id)
        db.add(proc);await db.commit()
        await p.catat_output(db,user=user,kode=proc.kode_proses,jenis=kode,berat_kumulatif=95)
        assert stok._packing_otomatis(kode,95)==(0,0,0,95)
        saldo,nama=await tersedia(db,BarisPerintah(tipe='byproduct_curah',jenis=kode,berat_kg=20))
        assert saldo==95 and nama=='Tepung beras'
    # Jenis baru yang ada stok wajib ditawarkan di pemilih pengiriman.
    response=await c.get('/api/actions/barang-bisa-keluar')
    assert response.status_code==200,response.text
    choice = next(r for r in response.json() if r['value']=='cr:'+kode)
    assert 'curah' in choice['label'] and 'karung' not in choice['label']

async def test_sisa_jasa_mencakup_hasil_samping_baru(pg,dunia):
    _,user=dunia
    from app.models import Pelanggan,Jasa
    from app.services.jasa import sisa_jasa
    from app.penggilingan.gudang2 import polishing as p
    async with pg() as db:
        customer=Pelanggan(nama_pelanggan='Pemilik hasil samping');db.add(customer);await db.flush()
        jasa=Jasa(kode='JAS-MASTER-UJI',pelanggan_id=customer.id);db.add(jasa);await db.flush()
        kode=await samping.simpan(db,user=user,aksi='tambah',nama='Tepung milik pelanggan',bentuk='curah')
        proc=PolishingProcess(kode_proses='POL-JASA-MASTER',status='proses',waktu_mulai=now_local(),created_by=user.id,jasa_id=jasa.id)
        db.add(proc);await db.commit()
        await p.catat_output(db,user=user,kode=proc.kode_proses,jenis=kode,berat_kumulatif=75)
        sisa=await sisa_jasa(db,jasa.id)
        assert sisa.samping_kg==75

async def test_migrasi_sayur_ekonomis_menjaga_identitas_dan_catatan(pg,dunia):
    from importlib import import_module
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    _,user=dunia
    async with pg() as db:
        grade=await db.scalar(select(RiceQualityStandard).where(RiceQualityStandard.kode=='sayur'))
        medium=await db.scalar(select(RiceQualityStandard).where(RiceQualityStandard.kode=='medium'))
        grade.nama='Sayur';medium.nama='Medium milik pabrik'
        proc=PolishingProcess(kode_proses='POL-MIGRASI-MASTER',status='proses',waktu_mulai=now_local(),created_by=user.id)
        db.add(proc);await db.flush()
        log=PolishingOutputLog(polishing_process_id=proc.id,jenis='sayur',berat_kg=125,waktu_update=now_local(),input_by=user.id)
        db.add(log);await db.flush()
        snapshot=(grade.id,grade.kode,log.id,log.jenis,log.berat_kg)
        migration=import_module('migrations.versions.0124_master_hasil')
        def upgrade(sync):
            with Operations.context(MigrationContext.configure(sync)):
                from alembic import op
                op.create_check_constraint('ck_sampel_sosoh_jenis','sampel_qc_sosoh',"jenis IN ('medium','premium','medsuper','sayur','beras_b')")
                migration.upgrade()
        connection=await db.connection()
        await connection.run_sync(upgrade)
        await db.refresh(grade);await db.refresh(medium);await db.refresh(log)
        assert grade.nama=='Ekonomis' and medium.nama=='Medium milik pabrik'
        assert snapshot==(grade.id,grade.kode,log.id,log.jenis,log.berat_kg)

@pytest.mark.parametrize('jenis',['beras','samping'])
async def test_dua_admin_menambah_nama_sama_hanya_satu_master(pg,dunia,jenis):
    import asyncio
    _,user=dunia
    async def kirim_baru():
        async with pg() as db:
            try:
                if jenis=='beras':
                    await beras.simpan(db,user=user,nama='Nama serentak',broken='5',sosoh='100')
                else:
                    await samping.simpan(db,user=user,aksi='tambah',nama='Nama serentak',bentuk='curah')
                await db.commit()
                return True
            except ValueError:
                await db.rollback()
                return False
    assert sorted(await asyncio.gather(kirim_baru(),kirim_baru()))==[False,True]
    async with pg() as db:
        rows=await beras.rincian(db) if jenis=='beras' else await samping.daftar(db)
        assert sum(r['nama']=='Nama serentak' for r in rows)==1

async def test_balapan_hapus_dan_pencatatan_hasil_tidak_memutus_stok(pg,dunia):
    import asyncio
    from app.penggilingan.gudang2 import polishing as p
    _,user=dunia
    async with pg() as db:
        kode=await samping.simpan(db,user=user,aksi='tambah',nama='Hasil bersamaan',bentuk='karung',kg_karung='25')
        proc=PolishingProcess(kode_proses='POL-BALAP-MASTER',status='proses',waktu_mulai=now_local(),created_by=user.id)
        db.add(proc);await db.commit()
        row=next(r for r in await samping.daftar(db) if r['kode']==kode)
    async def hapus():
        async with pg() as db:
            try:
                await samping.simpan(db,user=user,aksi='hapus',kode=kode,versi=row['versi'])
                await db.commit()
                return True
            except ValueError:
                await db.rollback()
                return False
    async def catat():
        async with pg() as db:
            try:
                await p.catat_output(db,user=user,kode='POL-BALAP-MASTER',jenis=kode,berat_kumulatif=100)
                return True
            except p.Gudang2Error:
                await db.rollback()
                return False
    deleted,recorded=await asyncio.gather(hapus(),catat())
    assert deleted != recorded
    async with pg() as db:
        exists=kode in [r['kode'] for r in await samping.daftar(db,termasuk_nonaktif=True)]
        kg=await db.scalar(select(func.coalesce(func.sum(PolishingOutputLog.berat_kg),0)).where(PolishingOutputLog.jenis==kode))
        assert exists==recorded and kg==(100 if recorded else 0)

async def test_referensi_kode_timbangan_huruf_besar_menghalangi_hapus(pg,dunia):
    _,user=dunia
    async with pg() as db:
        kode=await samping.simpan(db,user=user,aksi='tambah',nama='Hasil ditimbang',bentuk='curah')
        await db.commit()
        row=next(r for r in await samping.daftar(db) if r['kode']==kode)
        # Kontrak kolom tanpa FK di aplikasi lain, di database bersama.
        await db.execute(text('CREATE TABLE uji_ref_timbangan_master (jenis_kode varchar(30))'))
        try:
            await db.execute(text('INSERT INTO uji_ref_timbangan_master VALUES (:kode)'),{'kode':kode.upper()})
            assert await samping.dipakai(db,kode)
            with pytest.raises(ValueError,match='sudah dipakai'):
                await samping.simpan(db,user=user,aksi='hapus',kode=kode,versi=row['versi'])
            await samping.simpan(db,user=user,aksi='nonaktifkan',kode=kode,versi=row['versi'])
            assert kode not in [r['kode'] for r in await samping.daftar(db)]
        finally:
            await db.execute(text('DROP TABLE uji_ref_timbangan_master'))
        await db.commit()

async def test_bawaan_penerimaan_dapat_diganti_dan_tidak_menghidupkan_medium(pg,dunia):
    c,user=dunia
    async with pg() as db:
        assert (await beras.bawaan_penerimaan(db)).kode=='medium'
        medium=next(r for r in await beras.rincian(db) if r['kode']=='medium')
        await beras.simpan(db,user=user,aksi='hapus',id_=medium['id'],versi=medium['versi']);await db.commit()
        assert await beras.bawaan_penerimaan(db) is None
        row=await buat(db,user,'Beras penerimaan khusus');kode=row.kode
        detail=next(r for r in await beras.rincian(db) if r['id']==row.id)
    response=await kirim(c,URL+'/bawaan',dict(id=detail['id'],versi=detail['versi']),asal=URL)
    assert response.status_code==303,response.text
    async with pg() as db:
        assert (await beras.standar_penerimaan(db)).kode==kode
    action=next(r for r in (await c.get('/api/actions/menu')).json() if r['id']=='catat_beras_timbang_masuk')
    pilihan=next(f for f in action['fields'] if f['name']=='spesifikasi_beras')
    assert pilihan['bawaan']==kode and kode in dict(pilihan['options']) and 'medium' not in dict(pilihan['options'])

async def test_tiket_beras_memakai_jenis_baru_setelah_medium_dihapus(pg,dunia):
    c,user=dunia
    from tests.pg.test_tiket_produk_sekali import tiket
    from tests.pg.formulir import cap_formulir
    from app.models import FinishedGoodsStock
    async with pg() as db:
        row=await buat(db,user,'Beras masuk khusus');new_id=row.id;new_code=row.kode
        medium=next(r for r in await beras.rincian(db) if r['kode']=='medium')
        await beras.simpan(db,user=user,aksi='hapus',id_=medium['id'],versi=medium['versi']);await db.commit()
    tid=await tiket(pg,kode='MSK-SPEK-BARU')
    missing=await c.post('/api/actions/catat-produk-timbang-masuk',json={'timbangan_transaksi_id':tid},headers={'X-CSRF-Token':cap_formulir(c)})
    assert missing.status_code==400 and 'spesifikasi' in missing.text.lower()
    r=await c.post('/api/actions/catat-produk-timbang-masuk',json={'timbangan_transaksi_id':tid,'spesifikasi_beras':new_code},headers={'X-CSRF-Token':cap_formulir(c)})
    assert r.status_code==200,r.text
    async with pg() as db:
        row=await db.scalar(select(FinishedGoodsStock).where(FinishedGoodsStock.source_type=='timbangan',FinishedGoodsStock.source_id==tid))
        assert row.rice_quality_standard_id==new_id and row.berat_total_kg==998
        assert await beras.sudah_dipakai(db,await db.get(RiceQualityStandard,new_id))

async def test_tiket_broken_tetap_diterima_setelah_pilihan_hasil_dihapus(pg,dunia):
    c,user=dunia
    from tests.pg.test_tiket_produk_sekali import tiket
    from tests.pg.formulir import cap_formulir
    from app.models import ByproductStock
    async with pg() as db:
        row=next(r for r in await samping.daftar(db) if r['kode']=='broken')
        await samping.simpan(db,user=user,aksi='hapus',kode='broken',versi=row['versi']);await db.commit()
    tid=await tiket(pg,kind='BROKEN_MASUK',kode='MSK-BROKEN-MASTER')
    r=await c.post('/api/actions/catat-produk-timbang-masuk',json={'timbangan_transaksi_id':tid},headers={'X-CSRF-Token':cap_formulir(c)})
    assert r.status_code==200,r.text
    async with pg() as db:
        row=await db.scalar(select(ByproductStock).where(ByproductStock.source_type=='timbangan',ByproductStock.source_id==tid))
        assert row.berat_kg==998 and row.jenis_produk=='broken'
        master=next(r for r in await samping.rincian(db) if r['kode']=='broken')
        assert not master['aktif'] and master['dipakai']
        assert 'broken' not in await beras.jenis_hasil(db)

async def test_ringkasan_stok_memakai_sisa_curah_otomatis_jenis_baru(pg,dunia,monkeypatch):
    c,user=dunia
    from app.penggilingan.gudang2 import polishing as p
    from app.web import layar_produk
    async with pg() as db:
        kode=await samping.simpan(db,user=user,aksi='tambah',nama='Hasil otomatis ringkasan',bentuk='karung',kg_karung='30')
        proc=PolishingProcess(kode_proses='POL-CURAH-RINGKAS',status='proses',waktu_mulai=now_local(),created_by=user.id)
        db.add(proc);await db.commit()
        await p.catat_output(db,user=user,kode=proc.kode_proses,jenis=kode,berat_kumulatif=95)
    async def render(request,template,**ctx):
        return {'sisa':ctx['sisa_samping'],'curah':ctx['curah_samping']}
    monkeypatch.setattr(layar_produk,'render_laci',render)
    result=await c.get('/stok-produk',params={'jenis':kode})
    assert result.status_code==200,result.text
    assert result.json()=={'sisa':95,'curah':5}
