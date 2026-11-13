"""Uji pagar PostgreSQL, audit metadata dan HTTP aplikasi sungguhan."""
import json,os,time
import pytest
from sqlalchemy import text,select
from sqlalchemy.ext.asyncio import create_async_engine,async_sessionmaker
from sqlalchemy.exc import DBAPIError
from hmu_core import Perusahaan,LokasiPabrik,PenempatanGudang,Warehouse
from hmu_identitas import token
from hmu_identitas.ruang_data import RuangData,RuangDataTidakCocok,pasang_pagar
from app.models import SetelanPabrik
from app.services import ruang_perusahaan as svc
from tests.pg.test_masuk_detail_timbang import sidik
from tests.pg.test_koreksi_bahan_berjalan import running,dunia
from tests.pg.test_riwayat_giling import _klien
from app.web import security
A='d1d1241a-a329-464a-919e-4f2a65601bc8'
B='a1d1241a-a329-464a-919e-4f2a65601bc8'
pytestmark=[pytest.mark.asyncio,pytest.mark.fondasi_multi]

async def siapkan(pg):
    async with pg() as db:
        c=Perusahaan(kode='perusahaan-asli',nama='Perusahaan uji aman');db.add(c);await db.flush()
        s=LokasiPabrik(company_id=c.id,kode='lokasi',nama='Lokasi uji');db.add(s);await db.flush()
        for w in await db.scalars(select(Warehouse)):
            db.add(PenempatanGudang(warehouse_id=w.id,company_id=c.id,lokasi_pabrik_id=s.id))
        db.add(SetelanPabrik(kunci='organisasi_perusahaan_lama',nilai=json.dumps({'company_id':c.id})))
        await db.commit();return RuangData(c.id,A,int(time.time())+3600)

def konfigurasi(monkeypatch,r):
    monkeypatch.setenv('HMU_COMPANY_ID',str(r.company_id));monkeypatch.setenv('HMU_RUANG_DATA',r.ruang_id)
    monkeypatch.setenv('HMU_SESI_LAMA_SAMPAI',str(r.sesi_lama_sampai))

async def aktifkan(pg,r):
    async with pg() as db:
        plan=await svc.pratinjau(db,r)
        await svc.terapkan(db,r,bukti=plan['bukti'],nama_persis=plan['nama'],alasan='Aktivasi ruang uji yang terpisah')
        await db.commit()

async def test_penetapan_hanya_metadata_dan_audit_idempoten(pg,running):
    r=await siapkan(pg)
    async with pg() as db:before=await sidik(db)
    await aktifkan(pg,r)
    async with pg() as db:
        after=await sidik(db)
        assert {k:v for k,v in before.items() if k not in ('setelan_pabrik','activity_logs')}=={k:v for k,v in after.items() if k not in ('setelan_pabrik','activity_logs')}
        assert await db.scalar(text("SELECT count(*) FROM activity_logs WHERE aksi='penetapan_ruang_perusahaan'"))==1
    await aktifkan(pg,r)
    async with pg() as db:assert await sidik(db)==after

@pytest.mark.parametrize('operasi',['ubah','hapus','gudang-lain'])
async def test_pagar_database_menolak_identitas_dan_gudang_asing(pg,running,operasi):
    r=await siapkan(pg);await aktifkan(pg,r)
    async with pg() as db:
        if operasi=='gudang-lain':
            c=Perusahaan(kode='lain',nama='Lain');db.add(c);await db.flush()
            s=LokasiPabrik(company_id=c.id,kode='lain',nama='Lain');db.add(s);await db.flush()
        with pytest.raises(DBAPIError):
            if operasi=='ubah':await db.execute(text("UPDATE setelan_pabrik SET nilai='{}' WHERE kunci='ruang_data_perusahaan'"))
            elif operasi=='hapus':await db.execute(text("DELETE FROM setelan_pabrik WHERE kunci='ruang_data_perusahaan'"))
            else:await db.execute(text('UPDATE hmu_warehouse_sites SET company_id=:c,lokasi_pabrik_id=:s'),{'c':c.id,'s':s.id})
        await db.rollback()

@pytest.mark.parametrize('salah',['company','ruang','batas','tidak-ditetapkan'])
async def test_koneksi_salah_tidak_bisa_membaca_atau_menulis(pg,running,monkeypatch,salah):
    r=await siapkan(pg)
    if salah!='tidak-ditetapkan':await aktifkan(pg,r)
    bad=RuangData(r.company_id+(salah=='company'),B if salah=='ruang' else A,r.sesi_lama_sampai+(salah=='batas'))
    konfigurasi(monkeypatch,bad)
    engine=create_async_engine(os.environ['UJI_PG_URL']);pasang_pagar(engine,wajib=True)
    try:
        for sql in ['SELECT * FROM purchase_batches','DELETE FROM purchase_batches']:
            with pytest.raises(RuangDataTidakCocok):
                async with engine.begin() as conn:await conn.execute(text(sql))
    finally:await engine.dispose()

async def test_operator_lama_dan_baru_berjalan_cookie_perusahaan_lain_ditolak(pg,running,monkeypatch):
    async with await _klien(pg,peran='operator',gudang='g1') as client:
        old=client.cookies.get(security.NAMA_COOKIE)
        r=await siapkan(pg);await aktifkan(pg,r);konfigurasi(monkeypatch,r)
        async with pg() as db:pasang_pagar(db.bind,wajib=True)
        assert (await client.get('/pekerjaan')).status_code==200
        aid,versi=security.baca_token(old)
        claim=token.buat_token(security._kunci(),akun_id=aid,versi=versi,umur_detik=3600,ekstra={'company_id':r.company_id+1,'ruang_id':B})
        client.cookies.set(security.NAMA_COOKIE,claim)
        response=await client.get('/pekerjaan',follow_redirects=False)
        assert response.status_code in (302,303) and '/masuk' in response.headers['location']
        client.cookies.set(security.NAMA_COOKIE,old)
        assert (await client.get('/pekerjaan')).status_code==200

async def test_header_integrasi_perusahaan_lain_ditolak_sebelum_tiket(pg,running,monkeypatch):
    import httpx
    from fastapi import FastAPI
    from app.web.internal import router
    from app.config import settings
    r=await siapkan(pg);await aktifkan(pg,r);konfigurasi(monkeypatch,r)
    monkeypatch.setattr(settings,'internal_api_token','token-uji-saja')
    app=FastAPI();app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://uji') as client:
        for method in ['GET','POST']:
            path='/internal/pengiriman/tiket/1/'+('muatan' if method=='GET' else 'verifikasi')
            response=await client.request(method,path,headers={'X-Internal-Token':'token-uji-saja','X-HMU-Company':str(r.company_id+1),'X-HMU-Ruang':B})
            assert response.status_code==403 and 'berbeda perusahaan' in response.text

async def test_dua_database_id_transaksi_sama_pool_dan_penulisan_terpisah(monkeypatch):
    from uuid import uuid4
    from tests.pg.conftest import _url
    from sqlalchemy.engine import make_url
    url=make_url(_url())  # pagar loopback + nama uji_ dijalankan sebelum DDL
    admin=create_async_engine(url,isolation_level='AUTOCOMMIT')
    names=['uji_ruang_'+uuid4().hex[:12] for _ in range(2)]
    engines=[]
    try:
        async with admin.connect() as conn:
            for name in names:await conn.execute(text('CREATE DATABASE '+name))
        for i,name in enumerate(names):
            e=create_async_engine(url.set(database=name),pool_size=1,max_overflow=0)
            engines.append(e)
            r=RuangData(7+i,A if i==0 else B)
            async with e.begin() as conn:
                await conn.execute(text('CREATE TABLE setelan_pabrik(kunci text PRIMARY KEY,nilai text NOT NULL)'))
                await conn.execute(text('CREATE TABLE bukti_transaksi_uji(id int PRIMARY KEY,berat int NOT NULL)'))
                await conn.execute(text("INSERT INTO setelan_pabrik VALUES ('ruang_data_perusahaan',:v)"),{'v':json.dumps(dict(r.klaim(),sesi_lama_sampai=0))})
                await conn.execute(text('INSERT INTO bukti_transaksi_uji VALUES (1,:w)'),{'w':998+i})
            konfigurasi(monkeypatch,r);pasang_pagar(e,wajib=True)
        # Pool dipakai kembali; identitas tidak ikut berpindah dengan request.
        for _ in range(3):
            for i,e in enumerate(engines):
                async with e.begin() as c:assert await c.scalar(text('SELECT berat FROM bukti_transaksi_uji WHERE id=1'))==998+i
        async with engines[0].begin() as c:await c.execute(text('UPDATE bukti_transaksi_uji SET berat=900 WHERE id=1'))
        async with engines[1].begin() as c:assert await c.scalar(text('SELECT berat FROM bukti_transaksi_uji WHERE id=1'))==999
        konfigurasi(monkeypatch,RuangData(8,B))
        salah=create_async_engine(url.set(database=names[0]));pasang_pagar(salah,wajib=True)
        try:
            with pytest.raises(RuangDataTidakCocok):
                async with salah.begin() as c:await c.execute(text('DELETE FROM bukti_transaksi_uji'))
        finally:await salah.dispose()
    finally:
        for e in engines:await e.dispose()
        async with admin.connect() as conn:
            for name in names:await conn.execute(text('DROP DATABASE IF EXISTS '+name+' WITH (FORCE)'))
        await admin.dispose()

async def test_dokumen_perusahaan_baru_tidak_mewarisi_nama_dan_kontak_hmu(pg,monkeypatch):
    from hmu_dokumen.perusahaan import baca
    konfigurasi(monkeypatch,RuangData(7,A))
    async with pg() as db:
        with pytest.raises(ValueError,match='Identitas dokumen'):await baca(db)
        db.add(SetelanPabrik(kunci='identitas_perusahaan',nilai=json.dumps({'nama':'Perusahaan tujuh'})));await db.commit()
        d=await baca(db)
        assert d.nama=='Perusahaan tujuh' and not any([d.alamat,d.telepon,d.email,d.website,d.logo])

async def test_penempatan_gudang_dan_pengaturan_sendiri_tidak_bisa_memilih_registry_lain(pg,running,monkeypatch):
    from app.services.keanggotaan import RuangAdministrasi,otorisasi
    r=await siapkan(pg);await aktifkan(pg,r);konfigurasi(monkeypatch,r)
    async with pg() as db:
        c=Perusahaan(kode='registry-saja',nama='Registry lain');db.add(c);await db.flush()
        with pytest.raises(RuangDataTidakCocok):await otorisasi(db,RuangAdministrasi(running[0],c.id),c.id)

async def test_koreksi_bahan_dengan_pagar_aktif_tetap_menjaga_saldo(pg,running,monkeypatch):
    from tests.pg.test_koreksi_bahan_berjalan import save,g2
    from app.models import PolishingSiloUsage
    r=await siapkan(pg);await aktifkan(pg,r);konfigurasi(monkeypatch,r)
    async with pg() as db:pasang_pagar(db.bind,wajib=True)
    uid,kode,mid,it=running
    await save(pg,uid,kode,bahan=[dict(id=mid,sumber=str(it),jumlah=56)])
    async with pg() as db:
        assert await g2._sisa_tumpukan_intake(db,it)==2200
        usage=await db.scalar(select(PolishingSiloUsage))
        assert usage.berat_terpakai_kg==2500 and usage.berat_akhir_kg==300
