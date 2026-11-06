"""Penyimpanan Pengaturan melalui HTTP asli, selalu memakai database uji PostgreSQL."""
from io import BytesIO
import json
import pytest
from PIL import Image
from sqlalchemy import select, text, func
from app.models import (Warehouse, Dryer, Silo, JenisProsesProduksi, LiniProduksi,
                        AuditFasilitas, User, PurchaseBatch)
from app.database import now_local
from hmu_identitas import peran as P
from hmu_dokumen.perusahaan import baca
from tests.pg.test_pengaturan_usulan import master, klien, kirim, cap
from tests.pg.test_pengaturan_terpadu import fisik
from tests.pg.test_qc_berjalan import giling

pytestmark = pytest.mark.asyncio
COMPANY = dict(nama='PT Uji Terpisah',alamat='Alamat khusus uji',telepon='080000000',
               email='uji@example.com',website='https://example.com')


def gambar(fmt='PNG',size=(64,64)):
    b=BytesIO();Image.new('RGB',size,'green').save(b,format=fmt);return b.getvalue()

async def snapshot(pg):
    async with pg() as db:
        names=('warehouses','dryers','silos','jenis_proses_produksi','lini_produksi','setelan_pabrik','audit_fasilitas','activity_logs')
        return {t:(await db.execute(text(f"SELECT count(*),md5(coalesce(string_agg(to_jsonb(t)::text,'' ORDER BY to_jsonb(t)::text),'')) FROM {t} t"))).one() for t in names}

async def company_post(c,data=None,raw=None):
    fields={'_csrf':await cap(c),**(data or COMPANY)}
    return await c.post('/pengaturan/perusahaan',data=fields,
        files={'logo':('logo-uji.png',raw,'image/png')} if raw is not None else None)

async def test_perusahaan_postgres_simpan_logo_ubah_tanpa_logo_dan_bawaan(pg,master,giling,pemasok):
    from app.services.activity_log import ActivityLog
    c,_,uid=await klien(pg,P.SUPERADMIN)
    async with pg() as db:
        db.add(PurchaseBatch(kode_batch='GB-UJI-PENGATURAN',supplier_id=pemasok.id,
            berat_total_kg=1234,kondisi_gabah='basah',tanggal_pembelian=now_local().date(),
            waktu_pembelian=now_local(),input_by=uid,status_batch='baru',flag_unverified=False,sumber_berat='manual'))
        await db.commit()
    before=await fisik(pg)
    async with c:
        r=await company_post(c,raw=gambar());assert r.status_code==303
        async with pg() as db:
            first=await baca(db);logo=first.logo
            assert first.nama==COMPANY['nama'] and logo
        assert 'data:image/png;base64,' in (await c.get('/pengaturan/perusahaan')).text
        data={**COMPANY,'nama':'PT Uji Diubah','telepon':'080000001'}
        assert (await company_post(c,data)).status_code==303
        async with pg() as db:
            second=await baca(db);assert second.logo==logo and second.nama==data['nama']
        assert (await company_post(c,{**data,'logo_bawaan':'1'})).status_code==303
        async with pg() as db:
            assert not (await baca(db)).logo
            audits=list((await db.scalars(select(ActivityLog).where(ActivityLog.table_name=='setelan_pabrik'))).all())
            assert len(audits)==3
            assert any('sha256:' in str(x.new_value) for x in audits)
            assert all(logo not in str(x.new_value) for x in audits)
    assert await fisik(pg)==before

@pytest.mark.parametrize('bad,raw',[
    ({'nama':''},None),({'alamat':''},None),({'email':'tidak-valid'},None),
    ({'website':'javascript:alert(1)'},None),({'nama':'N'*121},None),
    ({},b'bukan gambar'),({},b'x'*(2*1024*1024+1)),({},gambar(size=(2049,20)))])
async def test_validasi_perusahaan_tidak_menimpa_nilai_sah(pg,master,bad,raw):
    c,_,_=await klien(pg,P.SUPERADMIN)
    async with c:
        assert (await company_post(c,raw=gambar())).status_code==303
        before=await snapshot(pg)
        r=await company_post(c,{**COMPANY,**bad},raw)
        assert r.status_code==422 and 'role="alert"' in r.text
        assert await snapshot(pg)==before
        assert COMPANY['nama'] in (await c.get('/pengaturan/perusahaan')).text

async def test_tambah_edit_gudang_dryer_silo_jenis_dan_line(pg,master,giling):
    c,_,_=await klien(pg,P.SUPERADMIN)
    before=await fisik(pg)
    async with c:
        r=await kirim(c,'/pengaturan/gudang/tambah',dict(nama='Gudang khusus uji',alamat='Alamat awal',latitude='-6,2',longitude='106,8',kembali_pengaturan='/pengaturan/gudang'))
        assert r.status_code==303
        async with pg() as db:
            w=await db.scalar(select(Warehouse).where(Warehouse.nama_gudang=='Gudang khusus uji'));wid=w.id
            assert w.kode_fungsi is None and float(w.latitude)==-6.2
        assert (await kirim(c,'/pengaturan/gudang/edit',dict(gudang_id=wid,nama='Gudang uji diubah',alamat='Alamat baru',latitude='-7,5',longitude='110,5',kembali_pengaturan='/pengaturan/gudang'))).status_code==303
        async with pg() as db:
            w=await db.get(Warehouse,wid);assert w.nama_gudang=='Gudang uji diubah' and w.alamat=='Alamat baru' and float(w.longitude)==110.5
        assert (await kirim(c,'/pengaturan/alat/dryer',dict(nama='Pengering lokal uji',warehouse_id=wid,kapasitas_kg='22000',kembali_pengaturan='/pengaturan/mesin'))).status_code==303
        async with pg() as db:
            d=await db.scalar(select(Dryer).where(Dryer.nama=='Pengering lokal uji'));did=d.id
            l=await db.scalar(select(LiniProduksi).where(LiniProduksi.dryer_id==did));lid=l.id
            assert d.warehouse_id==wid and l.warehouse_id==wid
        assert (await kirim(c,'/pengaturan/alat/dryer/edit',dict(dryer_id=did,nama='Pengering lokal diubah',kapasitas_kg='21500,5',target_kadar_air='14,2',tungku='Tungku uji',kembali_pengaturan=f'/pengaturan/mesin/{lid}'))).status_code==303
        async with pg() as db:
            d=await db.get(Dryer,did);assert float(d.kapasitas_kg)==21500.5 and float(d.target_kadar_air)==14.2
        assert (await kirim(c,'/pengaturan/alat/silo',dict(nama='LOKAL-UJI',warehouse_id=wid,jenis_isi='gabah',kembali_pengaturan='/pengaturan/silo'))).status_code==303
        async with pg() as db:
            s=await db.scalar(select(Silo).where(Silo.nama_silo=='Silo LOKAL-UJI'));sid=s.id
        assert (await kirim(c,'/pengaturan/alat/silo/edit',dict(silo_id=sid,nama='Silo lokal diubah',komoditas=['gabah_kering'],kembali_pengaturan='/pengaturan/silo'))).status_code==303
        async with pg() as db:
            s=await db.get(Silo,sid);assert s.warehouse_id==wid and s.nama_silo=='Silo lokal diubah' and s.komoditas_diizinkan==['gabah_kering']
        assert (await kirim(c,'/pengaturan/fasilitas',dict(objek='jenis',nama='Jenis lokal uji',kode='jenis-uji-lokal',aktif='on',kembali_pengaturan='/pengaturan/jenis-proses'))).status_code==303
        async with pg() as db:
            j=await db.scalar(select(JenisProsesProduksi).where(JenisProsesProduksi.kode=='jenis-uji-lokal'));jid=j.id
            edit=dict(objek='jenis',id=jid,versi=j.versi,nama='Jenis lokal diubah',kode=j.kode,aktif='on',kembali_pengaturan='/pengaturan/jenis-proses')
        assert (await kirim(c,'/pengaturan/fasilitas',edit)).status_code==303
        async with pg() as db:
            j=await db.get(JenisProsesProduksi,jid);assert j.nama=='Jenis lokal diubah' and j.versi==2
            milling=await db.scalar(select(JenisProsesProduksi.id).where(JenisProsesProduksi.kode=='penggilingan'))
        assert (await kirim(c,'/pengaturan/fasilitas',dict(objek='lini',nama='Line lokal uji',kode='line-uji',warehouse_id=wid,jenis_proses_id=milling,aktif='on',kembali_pengaturan='/pengaturan/mesin'))).status_code==303
        async with pg() as db:
            l=await db.scalar(select(LiniProduksi).where(LiniProduksi.kode=='line-uji'));lid2=l.id
            change=dict(objek='lini',id=lid2,versi=l.versi,nama='Line lokal diubah',kode=l.kode,warehouse_id=wid,jenis_proses_id=milling,aktif='on',kembali_pengaturan=f'/pengaturan/mesin/{lid2}')
        assert (await kirim(c,'/pengaturan/fasilitas',change)).status_code==303
        stable=await snapshot(pg)
        r=await kirim(c,'/pengaturan/fasilitas',dict(change,nama='Versi usang tidak boleh'))
        assert r.status_code==200 and 'Data berubah' in r.text
        assert await snapshot(pg)==stable
        async with pg() as db:
            assert (await db.get(LiniProduksi,lid2)).nama=='Line lokal diubah'
            assert await db.scalar(select(func.count()).select_from(AuditFasilitas))>=4
    assert await fisik(pg)==before

@pytest.mark.parametrize('role,view,gd',[(P.ADMIN,None,None),(P.OPERATOR,None,'Gudang 1'),(P.OPERATOR,None,'Gudang 2'),(P.SUPERADMIN,P.ADMIN,None),(P.SUPERADMIN,'operator:g1',None),(P.SUPERADMIN,'operator:g2',None)])
async def test_semua_post_ditolak_peran_tidak_berwenang_dan_lihat_sebagai(pg,master,role,view,gd):
    superc,_,_=await klien(pg,P.SUPERADMIN,username='penjaga_super');await superc.aclose()
    c,_,uid=await klien(pg,role,gd)
    async with pg() as db:
        wid=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g1'))
        did=await db.scalar(select(Dryer.id).order_by(Dryer.id));sid=await db.scalar(select(Silo.id).order_by(Silo.id))
        jid=await db.scalar(select(JenisProsesProduksi.id).order_by(JenisProsesProduksi.id));l=await db.scalar(select(LiniProduksi).order_by(LiniProduksi.id))
        lid,version=l.id,l.versi
    async with c:
        c.cookies.clear()
        login=await c.post('/masuk',data={'_csrf':await cap(c,'/masuk'),'username':'pengaturan_uji','sandi':'rahasia123'})
        assert login.status_code==303
        assert (await c.get('/api/me')).status_code==200
        if view:
            assert (await kirim(c,'/lihat-sebagai',dict(peran=view,kembali_pengaturan='/pengaturan/peran'))).status_code==303
        before=await snapshot(pg)
        cases=[('/pengaturan/perusahaan',COMPANY),('/pengaturan/gudang/tambah',dict(nama='Tidak boleh')),
            ('/pengaturan/gudang/edit',dict(gudang_id=wid,nama='Tidak boleh')),
            ('/pengaturan/alat/dryer',dict(nama='Tidak boleh',kapasitas_kg='22000',warehouse_id=wid)),
            ('/pengaturan/alat/dryer/edit',dict(dryer_id=did,nama='Tidak boleh',kapasitas_kg='22000',target_kadar_air='14')),
            ('/pengaturan/alat/silo',dict(nama='Tidak boleh',gudang='g1')),
            ('/pengaturan/alat/silo/edit',dict(silo_id=sid,nama='Tidak boleh',komoditas=['gabah_kering'])),
            ('/pengaturan/fasilitas',dict(objek='jenis',nama='Tidak boleh',kode='ditolak',aktif='on')),
            ('/pengaturan/fasilitas',dict(objek='lini',id=lid,versi=version,nama='Tidak boleh',kode='ditolak',warehouse_id=wid,jenis_proses_id=jid,dryer_id=did,aktif='on'))]
        for path,data in cases:
            r=await kirim(c,path,data);assert r.status_code==403,(path,r.status_code)
        assert await snapshot(pg)==before
    async with pg() as db:assert (await db.get(User,uid)).role==role

async def test_validasi_fasilitas_dan_gudang_tidak_menyimpan_sebagian(pg,master):
    c,_,_=await klien(pg,P.SUPERADMIN)
    async with pg() as db:
        did=await db.scalar(select(Dryer.id).order_by(Dryer.id));sid=await db.scalar(select(Silo.id).order_by(Silo.id))
        wid=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g1'))
        jid=await db.scalar(select(JenisProsesProduksi.id).where(JenisProsesProduksi.kode=='pengeringan'))
        w2=await db.scalar(select(Warehouse.id).where(Warehouse.kode_fungsi=='g2'))
        oldwh=await db.get(Warehouse,wid);duplicate=oldwh.nama_gudang
    async with c:
        before=await snapshot(pg)
        cases=[
          ('/pengaturan/gudang/tambah',dict(nama='G',kembali_pengaturan='/pengaturan/gudang'),'2–100'),
          ('/pengaturan/gudang/tambah',dict(nama='Gudang salah koordinat',latitude='91',kembali_pengaturan='/pengaturan/gudang'),'Koordinat'),
          ('/pengaturan/gudang/tambah',dict(nama=duplicate,kembali_pengaturan='/pengaturan/gudang'),'sudah digunakan'),
          ('/pengaturan/alat/dryer',dict(nama='Pengering salah',kapasitas_kg='0',warehouse_id=wid,kembali_pengaturan='/pengaturan/mesin'),'Kapasitas'),
          ('/pengaturan/alat/dryer/edit',dict(dryer_id=did,nama='Nama tetap lama',kapasitas_kg='28000',target_kadar_air='31',kembali_pengaturan='/pengaturan/mesin/1'),'5% dan 30%'),
          ('/pengaturan/alat/silo/edit',dict(silo_id=sid,nama='Nama silo tetap',komoditas=['bekatul'],kembali_pengaturan='/pengaturan/silo'),'komoditas'),
          ('/pengaturan/fasilitas',dict(objek='jenis',nama='Jenis salah',kode='kode tidak valid',aktif='on'),'kode'),
          ('/pengaturan/fasilitas',dict(objek='lini',nama='Line salah gudang',kode='salah-gudang',warehouse_id=w2,jenis_proses_id=jid,dryer_id=did,aktif='on'),'gudang'),
        ]
        for path,data,msg in cases:
            r=await kirim(c,path,data);assert r.status_code==200 and msg.lower() in r.text.lower(),(path,r.status_code)
            assert await snapshot(pg)==before

async def test_csrf_wajib_pada_post_pengaturan(pg,master):
    c,_,_=await klien(pg,P.SUPERADMIN)
    async with c:
        await cap(c)
        before=await snapshot(pg)
        for path in ['/pengaturan/perusahaan','/pengaturan/gudang/tambah','/pengaturan/alat/dryer','/pengaturan/alat/silo','/pengaturan/fasilitas']:
            assert (await c.post(path,data={'nama':'Tanpa CSRF'})).status_code==403
        assert await snapshot(pg)==before
