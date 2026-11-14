"""Dua perusahaan, lokasi dan gudang nyata; belum mengubah gerbang aplikasi."""
from dataclasses import FrozenInstanceError
import importlib.util
from pathlib import Path
import pytest
from sqlalchemy import select, text, func
from sqlalchemy.exc import IntegrityError
from hmu_core import User, Warehouse, Perusahaan, LokasiPabrik, KeanggotaanPerusahaan, PenempatanGudang,AksesLokasiAnggota
from hmu_identitas import peran as P
from hmu_identitas.organisasi import konteks_kerja, OrganisasiTidakDiizinkan
from tests.pg.test_masuk_detail_timbang import sidik
from tests.pg.test_koreksi_bahan_berjalan import running, dunia

pytestmark = [pytest.mark.asyncio, pytest.mark.fondasi_multi]


@pytest.fixture
async def organisasi(pg):
    async with pg() as db:
        u = User(nama='Lintas perusahaan', role=P.SUPERADMIN, status='aktif')
        luar = User(nama='Super tanpa anggota', role=P.SUPERADMIN, status='aktif')
        db.add_all([u, luar]); await db.flush()
        companies = [Perusahaan(kode='uji-a', nama='Perusahaan uji'), Perusahaan(kode='uji-b', nama='Perusahaan uji')]
        db.add_all(companies); await db.flush()
        sites, whs, members = [], [], []
        for i, c in enumerate(companies):
            m = KeanggotaanPerusahaan(company_id=c.id, user_id=u.id, peran=P.ADMIN if i == 0 else P.OPERATOR)
            db.add(m); members.append(m)
            for n in range(2):
                site = LokasiPabrik(company_id=c.id, kode='lokasi-'+str(n), nama='Nama lokasi sama')
                db.add(site); await db.flush(); sites.append(site)
                db.add(AksesLokasiAnggota(keanggotaan_id=m.id,company_id=c.id,lokasi_pabrik_id=site.id,semua_gudang=True))
                for k in range(2):
                    w = Warehouse(nama_gudang='Gudang sama', aktif=True)
                    db.add(w); await db.flush(); whs.append(w)
                    db.add(PenempatanGudang(company_id=c.id, lokasi_pabrik_id=site.id, warehouse_id=w.id))
        bebas=Warehouse(nama_gudang='Gudang historis tanpa lokasi',aktif=True)
        db.add(bebas);await db.flush()
        u.default_warehouse_id=whs[0].id
        await db.commit()
        return dict(uid=u.id, luar=luar.id, bebas=bebas.id, c=[c.id for c in companies], s=[s.id for s in sites],
                    w=[w.id for w in whs], m=[m.id for m in members])


def pilihan(x, perusahaan=0, lokasi=0, gudang=0):
    return dict(user_id=x['uid'], company_id=x['c'][perusahaan],
        lokasi_pabrik_id=x['s'][perusahaan*2+lokasi], warehouse_id=x['w'][perusahaan*4+lokasi*2+gudang])


async def test_dua_perusahaan_dua_lokasi_dua_gudang_dan_peran_sendiri(pg, organisasi):
    x=organisasi
    async with pg() as db:
        awal=await sidik(db)
        for i in range(2):
            for j in range(2):
                for k in range(2):
                    args=pilihan(x,i,j,k);ctx=await konteks_kerja(db,**args)
                    assert ctx.company_id==args['company_id'] and ctx.lokasi_pabrik_id==args['lokasi_pabrik_id']
                    assert ctx.warehouse_id==args['warehouse_id'] and ctx.keanggotaan_id==x['m'][i]
                    assert ctx.peran==(P.ADMIN if i==0 else P.OPERATOR)
                    with pytest.raises(FrozenInstanceError): ctx.company_id=x['c'][1-i]
        assert await sidik(db)==awal


@pytest.mark.parametrize('kasus',['perusahaan','lokasi','gudang','tanpa_anggota','id_teks','id_bool','id_nol'])
async def test_payload_campur_dan_super_luar_perusahaan_ditolak(pg,organisasi,kasus):
    args=pilihan(organisasi)
    args.update({'perusahaan':dict(company_id=organisasi['c'][1]),
      'lokasi':dict(lokasi_pabrik_id=organisasi['s'][1]), 'gudang':dict(warehouse_id=organisasi['w'][4]),
      'tanpa_anggota':dict(user_id=organisasi['luar']), 'id_teks':dict(company_id=str(args['company_id'])),
      'id_bool':dict(company_id=True), 'id_nol':dict(company_id=0)}[kasus])
    async with pg() as db:
        awal=await sidik(db)
        with pytest.raises(OrganisasiTidakDiizinkan,match='tidak tersedia'): await konteks_kerja(db,**args)
        assert await sidik(db)==awal


@pytest.mark.parametrize('objek',['perusahaan','lokasi','gudang','anggota','orang','peran'])
async def test_nonaktif_dan_peran_tak_dikenal_tidak_diberi_akses(pg,organisasi,objek):
    x=organisasi
    async with pg() as db:
        model,id,field,value={'perusahaan':(Perusahaan,x['c'][0],'aktif',False),
          'lokasi':(LokasiPabrik,x['s'][0],'aktif',False),'gudang':(Warehouse,x['w'][0],'aktif',False),
          'anggota':(KeanggotaanPerusahaan,x['m'][0],'aktif',False),'orang':(User,x['uid'],'status','nonaktif'),
          'peran':(KeanggotaanPerusahaan,x['m'][0],'peran','tidak-dikenal')}[objek]
        setattr(await db.get(model,id),field,value);await db.commit();awal=await sidik(db)
        with pytest.raises(OrganisasiTidakDiizinkan):await konteks_kerja(db,**pilihan(x))
        assert await sidik(db)==awal


@pytest.mark.parametrize('kasus',['kode_perusahaan','kode_lokasi','anggota','gudang_dua_lokasi','gudang_lintas_perusahaan','hapus_perusahaan'])
async def test_integritas_database_menjaga_identitas_dan_relasi(pg,organisasi,kasus):
    x=organisasi
    async with pg() as db:
        awal=await sidik(db)
        with pytest.raises(IntegrityError):
            if kasus=='hapus_perusahaan': await db.delete(await db.get(Perusahaan,x['c'][0]))
            else:
                db.add({'kode_perusahaan':lambda:Perusahaan(kode='uji-a',nama='Duplikat'),
                  'kode_lokasi':lambda:LokasiPabrik(company_id=x['c'][0],kode='lokasi-0',nama='Duplikat'),
                  'anggota':lambda:KeanggotaanPerusahaan(company_id=x['c'][0],user_id=x['uid'],peran=P.OPERATOR),
                  'gudang_dua_lokasi':lambda:PenempatanGudang(warehouse_id=x['w'][0],company_id=x['c'][0],lokasi_pabrik_id=x['s'][1]),
                  'gudang_lintas_perusahaan':lambda:PenempatanGudang(warehouse_id=x['bebas'],company_id=x['c'][0],lokasi_pabrik_id=x['s'][2])}[kasus]())
            await db.flush()
        await db.rollback();assert await sidik(db)==awal


async def test_konteks_tidak_melakukan_autoflush_draf(pg,organisasi):
    async with pg() as db:
        awal=await sidik(db)
        draf=User(nama='Belum disimpan',role=P.OPERATOR,status='aktif');db.add(draf)
        await konteks_kerja(db,**pilihan(organisasi))
        assert draf.id is None and draf in db.new
        await db.rollback();assert await sidik(db)==awal


def migrasi():
    p=Path(__file__).resolve().parents[2]/'migrations/versions/0128_master_organisasi.py'
    spec=importlib.util.spec_from_file_location('uji_master_organisasi',p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


async def test_migrasi_tabel_kosong_tidak_mengubah_proses_transaksi_atau_master_lama(pg,running):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    async with pg() as db: awal=await sidik(db)
    m=migrasi()
    spec=importlib.util.spec_from_file_location('uji_console_migrasi',Path(__file__).resolve().parents[2]/'migrations/versions/0130_console_akses_anggota.py')
    akses=importlib.util.module_from_spec(spec);spec.loader.exec_module(akses)
    spec=importlib.util.spec_from_file_location('uji_monitoring_migrasi',Path(__file__).resolve().parents[2]/'migrations/versions/0132_monitoring_bantuan.py')
    monitoring=importlib.util.module_from_spec(spec);spec.loader.exec_module(monitoring)
    def putaran(conn):
        with Operations.context(MigrationContext.configure(conn)):
            # Turunkan dependensi terbaru lebih dahulu; jangan melemahkan FK
            # atau memakai CASCADE agar tes migrasi lama tetap dapat berjalan.
            monitoring.downgrade();akses.downgrade();m.downgrade()
            m.upgrade();akses.upgrade();monitoring.upgrade()
    async with pg.kw['bind'].begin() as conn: await conn.run_sync(putaran)
    async with pg() as db:
        assert await sidik(db)==awal
        for tabel in m.TABEL: assert await db.scalar(text('SELECT count(*) FROM '+tabel))==0
        # Bahan/proses lama tidak diasosiasikan ke perusahaan pertama.
        assert await db.scalar(select(func.count()).select_from(Warehouse))>0


async def test_downgrade_master_terisi_ditolak_tanpa_menghapus_apa_pun(pg,organisasi):
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    async with pg() as db:awal=await sidik(db)
    def turun(conn):
        with Operations.context(MigrationContext.configure(conn)): migrasi().downgrade()
    with pytest.raises(RuntimeError,match='sudah terisi'):
        async with pg.kw['bind'].begin() as conn:await conn.run_sync(turun)
    async with pg() as db: assert await sidik(db)==awal


async def test_gudang_lama_tidak_otomatis_diklaim_perusahaan(pg,organisasi):
    args=pilihan(organisasi);args['warehouse_id']=organisasi['bebas']
    async with pg() as db:
        awal=await sidik(db)
        with pytest.raises(OrganisasiTidakDiizinkan):await konteks_kerja(db,**args)
        assert await sidik(db)==awal


async def test_status_aktif_dan_peran_mengikuti_normalisasi_akun_bersama(pg,organisasi):
    async with pg() as db:
        u=await db.get(User,organisasi['uid']);u.status='AKTIF'
        m=await db.get(KeanggotaanPerusahaan,organisasi['m'][0]);m.peran=' '+P.ADMIN.upper()+' '
        await db.commit();awal=await sidik(db)
        assert (await konteks_kerja(db,**pilihan(organisasi))).peran==P.ADMIN
        assert await sidik(db)==awal
